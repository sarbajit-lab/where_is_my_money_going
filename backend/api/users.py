"""/api/users, /api/roles, /api/app-settings, /api/audit - the RBAC screens and the Admin's settings."""
from flask import Blueprint, jsonify, request, session

from .. import permissions
from ..errors import ApiError
from ..services import audit, settings, users as svc

bp = Blueprint("users", __name__)


def _body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("Send the form as JSON")
    return data


@bp.get("/users")
def list_users():
    return jsonify(svc.list_users())


@bp.post("/users")
def create_user():
    return jsonify(svc.create_user(_body())), 201


@bp.put("/users/<int:uid>")
def update_user(uid):
    return jsonify(svc.update_user(uid, _body(), session.get("uid")))


@bp.delete("/users/<int:uid>")
def delete_user(uid):
    svc.delete_user(uid, session.get("uid"))
    return jsonify({"deleted": uid})


@bp.post("/users/<int:uid>/reset-password")
def reset_password(uid):
    return jsonify(svc.reset_password(uid, _body().get("password")))


@bp.post("/users/<int:uid>/reset-mfa")
def reset_mfa(uid):
    return jsonify(svc.reset_mfa(uid))


@bp.post("/users/<int:uid>/unlock")
def unlock(uid):
    svc.unlock(uid)
    return jsonify({"unlocked": uid})


@bp.get("/roles")
def list_roles():
    return jsonify({"roles": svc.list_roles(), "catalogue": permissions.PERMISSIONS})


@bp.post("/roles")
def create_role():
    return jsonify(svc.create_role(_body())), 201


@bp.put("/roles/<int:rid>")
def update_role(rid):
    return jsonify(svc.update_role(rid, _body()))


@bp.delete("/roles/<int:rid>")
def delete_role(rid):
    svc.delete_role(rid)
    return jsonify({"deleted": rid})


@bp.get("/app-settings")
def get_settings():
    return jsonify(settings.all_options())


@bp.put("/app-settings")
def put_settings():
    out = settings.save_options(_body())
    audit.log("settings.change", ", ".join(sorted(_body())))
    return jsonify(out)


@bp.get("/audit")
def get_audit():
    return jsonify(audit.recent())
