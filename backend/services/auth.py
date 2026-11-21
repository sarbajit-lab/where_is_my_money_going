"""Login, authenticator (MFA), lockout, first-time admin and password changes.

Session stages (stored in Flask's signed session cookie):
  change_pw  password ok, but it is a temporary one (first start, or reset by an Admin): choose a new one
  mfa_setup  password ok, authenticator not set up yet -> must scan QR + confirm a code
  mfa        password ok, waiting for the 6-digit code
  ok         fully logged in
"""
import os
import re
import secrets
import string
from datetime import datetime, timedelta, timezone

from werkzeug.security import check_password_hash, generate_password_hash

from .. import permissions
from ..db import get_db, one
from ..errors import ApiError
from . import settings, totp

DEFAULT_ADMIN = "admin"
USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{1,39}$")
# a real hash to compare against when the username is unknown, so timing doesn't reveal it
_DUMMY_HASH = generate_password_hash("not-a-real-password", method="scrypt")

USER_SELECT = ("SELECT u.*, r.name AS role_name, r.permissions AS role_permissions "
               "FROM users u JOIN roles r ON r.id = u.role_id ")


def _utcnow():
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(dt):
    return dt.isoformat()


def hash_password(pw):
    return generate_password_hash(pw, method="scrypt")


def random_password(n=14):
    """Readable temporary password: letters and digits, always with both."""
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(n))
        if any(c.isdigit() for c in pw) and any(c.islower() for c in pw) and any(c.isupper() for c in pw):
            return pw


def min_password():
    return settings.option("min_password")


def check_password_rules(pw, minimum=None):
    n = minimum or min_password()
    if not isinstance(pw, str) or len(pw) < n:
        raise ApiError(f"Password must be at least {n} characters", field="password")
    if len(pw) > 200:
        raise ApiError("Password is too long", field="password")
    if pw.isdigit() or pw.lower() == pw and pw.isalpha():
        raise ApiError("Use a mix of letters and numbers or symbols", field="password")


def check_username(name):
    name = (name or "").strip()
    if not USERNAME_RE.match(name):
        raise ApiError("Username: 2 to 40 letters, digits or . _ - @ (no spaces)", field="username")
    return name


def with_permissions(user):
    if user is not None:
        user["permissions"] = permissions.parse(user.pop("role_permissions", ""))
    return user


def user_by_id(uid):
    return with_permissions(one(USER_SELECT + "WHERE u.id = ?", (uid,)))


def user_by_name(name):
    return with_permissions(one(USER_SELECT + "WHERE u.username = ?", ((name or "").strip(),)))


def public(user):
    """What the browser may know about a user (never hashes or secrets)."""
    return {
        "id": user["id"], "username": user["username"], "full_name": user["full_name"],
        "role": user["role_name"], "permissions": user["permissions"],
        "last_login_at": user["last_login_at"], "mfa_enabled": bool(user["totp_secret"]),
    }


def mfa_required():
    return bool(settings.option("mfa_required"))


# ---------------------------------------------------------------- first-time admin

def ensure_default_admin(conn, password=None, must_change=True, data_dir=None):
    """First start: create the default Admin so there is something to log in with.

    The random password is shown in the terminal (and saved to data/FIRST_LOGIN.txt) and must be changed at the first login.
    Returns the password when a user was created, otherwise None."""
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
        return None
    role = conn.execute("SELECT id FROM roles WHERE name = 'Admin'").fetchone()[0]
    password = password or random_password()
    conn.execute("INSERT INTO users (username, full_name, password_hash, role_id, must_change_password) VALUES (?,?,?,?,?)",
                 (DEFAULT_ADMIN, "Administrator", hash_password(password), role, 1 if must_change else 0))
    conn.commit()
    if data_dir and must_change:
        try:
            path = os.path.join(data_dir, "FIRST_LOGIN.txt")
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as fh:
                fh.write(f"WIMMG first login\nUsername: {DEFAULT_ADMIN}\nPassword: {password}\n\n"
                         "You must choose a new password at your first login. This file is deleted then.\n")
        except OSError:
            pass
    return password


def remove_first_login_file(data_dir):
    try:
        os.remove(os.path.join(data_dir, "FIRST_LOGIN.txt"))
    except OSError:
        pass


# ---------------------------------------------------------------- lockout

def _check_lock(user):
    if user["locked_until"]:
        until = datetime.fromisoformat(user["locked_until"])
        if until > _utcnow():
            mins = max(1, int((until - _utcnow()).total_seconds() // 60) + 1)
            raise ApiError(f"Too many wrong attempts. Try again in {mins} minute{'s' if mins > 1 else ''}.", status=429)


def _fail(user):
    limit, minutes = settings.option("max_failures"), settings.option("lock_minutes")
    n = user["failed_attempts"] + 1
    locked = _iso(_utcnow() + timedelta(minutes=minutes)) if n >= limit else None
    get_db().execute("UPDATE users SET failed_attempts = ?, locked_until = ? WHERE id = ?",
                     (0 if locked else n, locked, user["id"]))
    get_db().commit()
    if locked:
        raise ApiError(f"Too many wrong attempts. Locked for {minutes} minutes.", status=429)


def _succeed(user, step=None):
    sql = "UPDATE users SET failed_attempts = 0, locked_until = NULL"
    params = []
    if step is not None:
        sql += ", totp_last_step = ?"
        params.append(step)
    get_db().execute(sql + " WHERE id = ?", params + [user["id"]])
    get_db().commit()


def mark_login(uid):
    get_db().execute("UPDATE users SET last_login_at = datetime('now','localtime') WHERE id = ?", (uid,))
    get_db().commit()


# ---------------------------------------------------------------- login

def check_login(username, password):
    user = user_by_name(username)
    if not user or not user["active"]:
        check_password_hash(_DUMMY_HASH, password or "")
        raise ApiError("Username or password is incorrect", status=401)
    _check_lock(user)
    if not check_password_hash(user["password_hash"], password or ""):
        _fail(user)
        raise ApiError("Username or password is incorrect", status=401)
    _succeed(user)
    return user_by_id(user["id"])


def stage_after_password(user):
    """Where the login goes after the password was accepted."""
    if user["must_change_password"]:
        return "change_pw"
    if not mfa_required():
        return "ok"
    return "mfa" if user["totp_secret"] else "mfa_setup"


def stage_after_change(user):
    if not mfa_required():
        return "ok"
    return "mfa" if user["totp_secret"] else "mfa_setup"


def check_code(user, code):
    _check_lock(user)
    step = totp.verify(user["totp_secret"], code, user["totp_last_step"])
    if step is None:
        _fail(user)
        raise ApiError("That code isn't right. Use the current 6-digit code from your authenticator app.", status=401,
                       field="code")
    _succeed(user, step)


def enable_totp(user, secret, code):
    step = totp.verify(secret, code, 0)
    if step is None:
        raise ApiError("That code doesn't match. Check the time on your phone and try the newest code.", field="code")
    get_db().execute("UPDATE users SET totp_secret = ?, totp_last_step = ? WHERE id = ?", (secret, step, user["id"]))
    get_db().commit()


def change_password(user, current, new):
    if not check_password_hash(user["password_hash"], current or ""):
        raise ApiError("Current password is incorrect", field="current")
    if check_password_hash(user["password_hash"], new or ""):
        raise ApiError("Choose a password different from the current one", field="new")
    check_password_rules(new)
    set_password(user["id"], new, must_change=False)


def set_password(uid, new, must_change=False):
    get_db().execute(
        "UPDATE users SET password_hash = ?, password_version = password_version + 1, failed_attempts = 0, "
        "locked_until = NULL, must_change_password = ? WHERE id = ?", (hash_password(new), 1 if must_change else 0, uid))
    get_db().commit()


# ---------------------------------------------------------------- terminal helpers (run.py --reset-*)

def cli_reset_password(conn, username, new):
    row = conn.execute("SELECT value FROM settings WHERE key = 'min_password'").fetchone()
    try:
        minimum = int(row[0]) if row else 10
    except (TypeError, ValueError):
        minimum = 10
    check_password_rules(new, minimum)
    n = conn.execute("UPDATE users SET password_hash = ?, password_version = password_version + 1, "
                     "failed_attempts = 0, locked_until = NULL, must_change_password = 0, active = 1 "
                     "WHERE username = ?", (hash_password(new), username)).rowcount
    conn.commit()
    return n


def cli_reset_mfa(conn, username):
    n = conn.execute("UPDATE users SET totp_secret = NULL, totp_last_step = 0, password_version = password_version + 1, "
                     "failed_attempts = 0, locked_until = NULL WHERE username = ?", (username,)).rowcount
    conn.commit()
    return n


def idle_minutes():
    return settings.option("idle_minutes")


def session_seconds():
    return settings.option("session_hours") * 3600
