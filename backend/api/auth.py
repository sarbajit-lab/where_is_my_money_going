"""/api/auth - login with username + password + authenticator code, logout, first-time password change.

Every other /api route requires a fully logged-in session and the permission it needs (see `guard`).
"""
import time

from flask import Blueprint, current_app, jsonify, request, session

from .. import permissions
from ..errors import ApiError
from ..services import audit, auth as svc, settings, totp

bp = Blueprint("auth", __name__)

CSRF_HEADER = "WIMMG"

PUBLIC = {
    "/api/auth/status", "/api/auth/login", "/api/auth/login/code", "/api/auth/first-password",
    "/api/auth/mfa/begin", "/api/auth/mfa/confirm", "/api/auth/logout",
}
PENDING_MINUTES = 15          # a half-finished login (password ok, code not yet entered) is dropped after this long


def _body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("Send the form as JSON")
    return data


def _start(user, stage):
    session.clear()
    session.permanent = True
    now = int(time.time())
    session.update(uid=user["id"], pv=user["password_version"], stage=stage, last=now, t0=now, uname=user["username"])


def _finish(user):
    """Fully logged in."""
    session["stage"] = "ok"
    session["last"] = session["t0"] = int(time.time())
    svc.mark_login(user["id"])
    audit.log("login", "", actor=user["username"])


def current_user(required_stage="ok"):
    """The logged-in user for this request, or None. Ends the session if it is stale."""
    uid = session.get("uid")
    if not uid:
        return None
    user = svc.user_by_id(uid)
    if not user or not user["active"] or user["password_version"] != session.get("pv"):
        session.clear()               # password changed/reset elsewhere, or the user was disabled: log out
        return None
    now = time.time()
    stage = session.get("stage")
    if stage == "ok":
        if now - session.get("last", 0) > svc.idle_minutes() * 60 or now - session.get("t0", 0) > svc.session_seconds():
            session.clear()           # idle too long, or logged in for longer than the allowed time
            return None
    elif now - session.get("t0", 0) > PENDING_MINUTES * 60:
        session.clear()
        return None
    if required_stage and stage != required_stage:
        return None
    return user


def guard():
    """Runs before every request (registered in create_app)."""
    path = request.path
    if not path.startswith("/api/"):
        return None
    # CSRF protection: browsers can't add this header to cross-site form posts
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("X-Requested-With") != CSRF_HEADER:
        return jsonify({"error": "Missing request header"}), 400
    if path in PUBLIC:
        return None
    user = current_user("ok")
    if not user:
        return jsonify({"error": "Please log in", "auth": True}), 401
    need = permissions.required(request.method, path)
    if need and need not in user["permissions"]:
        return jsonify({"error": "Your role doesn't allow this. Ask an Admin."}), 403
    session["last"] = int(time.time())
    return None


def _status_payload():
    user = current_user(required_stage=None) if session.get("uid") else None
    state = session.get("stage") if user else "logged_out"
    return {
        "state": state if state in ("ok", "mfa", "mfa_setup", "change_pw") else "logged_out",
        "user": svc.public(user) if user and state == "ok" else None,
        "username": user["username"] if user and state != "ok" else None,
        "idle_minutes": svc.idle_minutes(),
        "mfa_required": svc.mfa_required(),
        "min_password": svc.min_password(),
        "currency": settings.option("currency_symbol"),
        "autosave_rows": settings.option("autosave_rows"),
        "version": current_app.config["APP_VERSION"],
    }


@bp.get("/auth/status")
def status():
    return jsonify(_status_payload())


@bp.post("/auth/login")
def login():
    d = _body()
    user = svc.check_login(d.get("username"), d.get("password"))
    stage = svc.stage_after_password(user)
    _start(user, stage)
    if stage == "ok":
        _finish(user)
    return jsonify(_status_payload())


@bp.post("/auth/first-password")
def first_password():
    """The temporary password (first start, or reset by an Admin) must be replaced before anything else."""
    user = current_user("change_pw")
    if not user:
        raise ApiError("Your login expired. Enter your password again.", status=401)
    d = _body()
    if d.get("new") != d.get("confirm"):
        raise ApiError("The two new passwords don't match", field="confirm")
    svc.change_password(user, d.get("current"), d.get("new"))
    svc.remove_first_login_file(current_app.config["DATA_DIR"])
    fresh = svc.user_by_id(user["id"])
    session["pv"] = fresh["password_version"]
    stage = svc.stage_after_change(fresh)
    session["stage"] = stage
    if stage == "ok":
        _finish(fresh)
    return jsonify(_status_payload())


@bp.post("/auth/login/code")
def login_code():
    user = current_user("mfa")
    if not user:
        raise ApiError("Your login expired. Enter your password again.", status=401)
    svc.check_code(user, _body().get("code"))
    _finish(user)
    return jsonify(_status_payload())


@bp.post("/auth/mfa/begin")
def mfa_begin():
    """New authenticator secret: during first setup, or from Settings when logged in (re-pairing a new phone)."""
    user = current_user("mfa_setup") or current_user("ok")
    if not user:
        raise ApiError("Please log in", status=401)
    secret = totp.new_secret()
    session["pending_secret"] = secret
    return jsonify({"secret": secret, "uri": totp.otpauth_uri(secret, user["username"])})


@bp.post("/auth/mfa/confirm")
def mfa_confirm():
    was_setup = session.get("stage") == "mfa_setup"
    user = current_user("mfa_setup") or current_user("ok")
    secret = session.get("pending_secret")
    if not user or not secret:
        raise ApiError("Start the authenticator setup again", status=400)
    svc.enable_totp(user, secret, _body().get("code"))
    session.pop("pending_secret", None)
    if was_setup:
        _finish(user)
    else:
        session["stage"] = "ok"
        session["last"] = int(time.time())
    return jsonify(_status_payload())


@bp.post("/auth/logout")
def logout():
    session.clear()
    return jsonify({"state": "logged_out"})


# ---------------------------------------------------------------- logged-in account settings

@bp.get("/auth/security")
def security():
    user = current_user("ok")
    return jsonify({
        "user": svc.public(user),
        "idle_minutes": svc.idle_minutes(),
        "mfa_required": svc.mfa_required(),
        "min_password": svc.min_password(),
    })


@bp.post("/auth/password")
def change_password():
    d = _body()
    if d.get("new") != d.get("confirm"):
        raise ApiError("The two new passwords don't match", field="confirm")
    user = current_user("ok")
    if not user:
        raise ApiError("Please log in", status=401)
    svc.change_password(user, d.get("current"), d.get("new"))
    fresh = svc.user_by_id(user["id"])
    session["pv"] = fresh["password_version"]       # keep this session, log out others
    audit.log("password.change", "")
    return jsonify({"message": "Password changed"})


@bp.put("/auth/profile")
def profile():
    from ..db import get_db
    user = current_user("ok")
    name = (_body().get("full_name") or "").strip()[:80]
    get_db().execute("UPDATE users SET full_name = ? WHERE id = ?", (name, user["id"]))
    get_db().commit()
    return jsonify(svc.public(svc.user_by_id(user["id"])))
