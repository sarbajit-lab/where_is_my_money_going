"""Users and roles (the RBAC screens in Settings)."""
import sqlite3

from .. import permissions
from ..db import get_db, one, rows
from ..errors import ApiError
from . import audit, auth


def _user_out(u):
    return {
        "id": u["id"], "username": u["username"], "full_name": u["full_name"], "role_id": u["role_id"],
        "role": u["role_name"], "active": bool(u["active"]), "mfa_enabled": bool(u["totp_secret"]),
        "must_change_password": bool(u["must_change_password"]), "last_login_at": u["last_login_at"],
        "created_at": u["created_at"],
    }


def list_users():
    return [_user_out(u) for u in rows(auth.USER_SELECT + "ORDER BY u.username COLLATE NOCASE")]


def _role(role_id):
    r = one("SELECT * FROM roles WHERE id = ?", (role_id,))
    if not r:
        raise ApiError("Choose a role", field="role_id")
    return r


def _admins_left_without(user_id):
    """How many other active users could still manage users if this one were removed/disabled/demoted."""
    n = 0
    for u in rows(auth.USER_SELECT + "WHERE u.active = 1 AND u.id != ?", (user_id,)):
        if "users.manage" in permissions.parse(u["role_permissions"]):
            n += 1
    return n


def create_user(data):
    username = auth.check_username(data.get("username"))
    role = _role(data.get("role_id"))
    password = (data.get("password") or "").strip() or auth.random_password()
    auth.check_password_rules(password)
    try:
        cur = get_db().execute(
            "INSERT INTO users (username, full_name, password_hash, role_id, must_change_password) VALUES (?,?,?,?,1)",
            (username, (data.get("full_name") or "").strip()[:80], auth.hash_password(password), role["id"]))
        get_db().commit()
    except sqlite3.IntegrityError:
        raise ApiError("That username is already taken", field="username")
    audit.log("user.create", f"{username} as {role['name']}")
    out = _user_out(auth.user_by_id(cur.lastrowid))
    out["temporary_password"] = password
    return out


def update_user(uid, data, acting_id):
    u = auth.user_by_id(uid)
    if not u:
        raise ApiError("User not found", status=404)
    role = _role(data.get("role_id", u["role_id"]))
    active = 1 if data.get("active", bool(u["active"])) else 0
    keeps_admin = active and "users.manage" in permissions.parse(role["permissions"])
    if not keeps_admin and "users.manage" in u["permissions"] and u["active"] and not _admins_left_without(uid):
        raise ApiError("At least one active user must be able to manage users", field="role_id")
    if uid == acting_id and not active:
        raise ApiError("You can't deactivate yourself", field="active")
    get_db().execute("UPDATE users SET full_name = ?, role_id = ?, active = ?, "
                     "password_version = password_version + CASE WHEN ? OR ? != role_id THEN 1 ELSE 0 END WHERE id = ?",
                     ((data.get("full_name", u["full_name"]) or "").strip()[:80], role["id"], active,
                      0 if active else 1, role["id"], uid))
    get_db().commit()
    audit.log("user.update", f"{u['username']}: role {role['name']}, {'active' if active else 'disabled'}")
    return _user_out(auth.user_by_id(uid))


def reset_password(uid, new=None):
    u = auth.user_by_id(uid)
    if not u:
        raise ApiError("User not found", status=404)
    new = (new or "").strip() or auth.random_password()
    auth.check_password_rules(new)
    auth.set_password(uid, new, must_change=True)
    audit.log("user.reset_password", u["username"])
    return {"username": u["username"], "temporary_password": new}


def reset_mfa(uid):
    u = auth.user_by_id(uid)
    if not u:
        raise ApiError("User not found", status=404)
    get_db().execute("UPDATE users SET totp_secret = NULL, totp_last_step = 0, password_version = password_version + 1, "
                     "failed_attempts = 0, locked_until = NULL WHERE id = ?", (uid,))
    get_db().commit()
    audit.log("user.reset_mfa", u["username"])
    return {"username": u["username"]}


def unlock(uid):
    get_db().execute("UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE id = ?", (uid,))
    get_db().commit()


def delete_user(uid, acting_id):
    u = auth.user_by_id(uid)
    if not u:
        raise ApiError("User not found", status=404)
    if uid == acting_id:
        raise ApiError("You can't delete yourself")
    if "users.manage" in u["permissions"] and u["active"] and not _admins_left_without(uid):
        raise ApiError("At least one active user must be able to manage users")
    get_db().execute("DELETE FROM users WHERE id = ?", (uid,))
    get_db().commit()
    audit.log("user.delete", u["username"])


# ---------------------------------------------------------------- roles

def _role_out(r):
    return {"id": r["id"], "name": r["name"], "description": r["description"], "is_system": bool(r["is_system"]),
            "permissions": permissions.parse(r["permissions"]), "users": r["n"]}


def list_roles():
    return [_role_out(r) for r in rows(
        "SELECT r.*, (SELECT COUNT(*) FROM users u WHERE u.role_id = r.id) AS n FROM roles r ORDER BY r.is_system DESC, r.name")]


def _clean_perms(perms):
    if not isinstance(perms, list):
        raise ApiError("Choose the permissions", field="permissions")
    bad = [p for p in perms if p not in permissions.PERMISSIONS]
    if bad:
        raise ApiError(f"Unknown permission: {bad[0]}", field="permissions")
    p = set(perms)
    if p and "view" not in p:
        p.add("view")                      # anything else needs at least the right to look
    return permissions.join(p)


def create_role(data):
    name = (data.get("name") or "").strip()
    if not name or len(name) > 40:
        raise ApiError("Give the role a name (up to 40 characters)", field="name")
    try:
        cur = get_db().execute("INSERT INTO roles (name, description, permissions) VALUES (?,?,?)",
                               (name, (data.get("description") or "").strip()[:120], _clean_perms(data.get("permissions"))))
        get_db().commit()
    except sqlite3.IntegrityError:
        raise ApiError("A role with that name already exists", field="name")
    audit.log("role.create", name)
    return [r for r in list_roles() if r["id"] == cur.lastrowid][0]


def update_role(rid, data):
    r = one("SELECT * FROM roles WHERE id = ?", (rid,))
    if not r:
        raise ApiError("Role not found", status=404)
    if r["name"] == "Admin":
        raise ApiError("The Admin role always has every permission and can't be changed")
    name = (data.get("name", r["name"]) or "").strip()
    if not name or len(name) > 40:
        raise ApiError("Give the role a name (up to 40 characters)", field="name")
    perms = _clean_perms(data.get("permissions", permissions.parse(r["permissions"])))
    if "users.manage" not in permissions.parse(perms) and "users.manage" in permissions.parse(r["permissions"]):
        left = [u for u in rows(auth.USER_SELECT + "WHERE u.active = 1 AND u.role_id != ?", (rid,))
                if "users.manage" in permissions.parse(u["role_permissions"])]
        if not left:
            raise ApiError("At least one active user must be able to manage users", field="permissions")
    try:
        get_db().execute("UPDATE roles SET name = ?, description = ?, permissions = ? WHERE id = ?",
                         (name if not r["is_system"] else r["name"], (data.get("description", r["description"]) or "").strip()[:120],
                          perms, rid))
        get_db().commit()
    except sqlite3.IntegrityError:
        raise ApiError("A role with that name already exists", field="name")
    audit.log("role.update", name)
    return [x for x in list_roles() if x["id"] == rid][0]


def delete_role(rid):
    r = one("SELECT * FROM roles WHERE id = ?", (rid,))
    if not r:
        raise ApiError("Role not found", status=404)
    if r["is_system"]:
        raise ApiError("Built-in roles can't be deleted")
    if one("SELECT COUNT(*) AS n FROM users WHERE role_id = ?", (rid,))["n"]:
        raise ApiError("Move its users to another role first")
    get_db().execute("DELETE FROM roles WHERE id = ?", (rid,))
    get_db().commit()
    audit.log("role.delete", r["name"])
