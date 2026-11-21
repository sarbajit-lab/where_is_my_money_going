"""/api/sheet - the weekly sheet: entries, items & limits, accounts, insights, Excel/CSV import and export."""
from datetime import datetime

from flask import Blueprint, Response, jsonify, request, session

from ..errors import ApiError
from ..services import audit, importer, sheet as svc

bp = Blueprint("sheet", __name__)


def _body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("Send the data as JSON")
    return data


def _who():
    return session.get("uname", "")


def _month():
    return request.args.get("month") or datetime.now().strftime("%Y-%m")


@bp.get("/sheet/bootstrap")
def bootstrap():
    return jsonify(svc.bootstrap(svc.valid_month(_month())))


@bp.get("/sheet/spent")
def spent():
    months = [m for m in (request.args.get("months") or "").split(",") if m]
    return jsonify(svc.spent_by_month(months))


# ---- entries
@bp.get("/sheet/entries")
def list_entries():
    return jsonify(svc.list_entries(request.args))


@bp.post("/sheet/entries")
def create_entry():
    return jsonify(svc.create_entry(_body(), _who())), 201


@bp.post("/sheet/entries/bulk")
def bulk():
    items = _body().get("rows")
    if not isinstance(items, list) or len(items) > 2000:
        raise ApiError("Send up to 2000 rows")
    return jsonify(svc.create_many(items, _who()))


@bp.put("/sheet/entries/<int:eid>")
def update_entry(eid):
    return jsonify(svc.update_entry(eid, _body()))


@bp.delete("/sheet/entries/<int:eid>")
def delete_entry(eid):
    svc.delete_entry(eid)
    return jsonify({"deleted": eid})


# ---- items and accounts
@bp.get("/sheet/items")
def items():
    month = request.args.get("month")
    return jsonify({"items": svc.list_items(month), "categories": svc.categories(), "accounts": svc.list_accounts()})


@bp.post("/sheet/items")
def create_item():
    return jsonify(svc.create_item(_body())), 201


@bp.put("/sheet/items/<int:iid>")
def update_item(iid):
    return jsonify(svc.update_item(iid, _body()))


@bp.delete("/sheet/items/<int:iid>")
def delete_item(iid):
    svc.delete_item(iid)
    return jsonify({"deleted": iid})


@bp.get("/sheet/accounts")
def accounts():
    return jsonify(svc.list_accounts())


@bp.post("/sheet/accounts")
def create_account():
    return jsonify(svc.create_account(_body())), 201


@bp.put("/sheet/accounts/<int:aid>")
def update_account(aid):
    return jsonify(svc.update_account(aid, _body()))


@bp.delete("/sheet/accounts/<int:aid>")
def delete_account(aid):
    svc.delete_account(aid)
    return jsonify({"deleted": aid})


@bp.get("/sheet/insights")
def insights():
    return jsonify(svc.insights(request.args))


# ---- import / export
def _upload():
    """(raw bytes, filename, pasted text) from a multipart upload or a JSON body with {text}."""
    up = request.files.get("file")
    if up and up.filename:
        return up.read(), up.filename, None
    text = request.form.get("text") if request.form else (request.get_json(silent=True) or {}).get("text")
    if text and text.strip():
        return None, "", text
    raise ApiError("Choose a file, or paste the rows copied from Excel")


@bp.post("/sheet/import/preview")
def import_preview():
    raw, name, text = _upload()
    return jsonify(importer.preview(raw, name, text))


@bp.post("/sheet/import")
def import_commit():
    raw, name, text = _upload()
    skip = (request.form.get("skip_duplicates", "1") if request.form else "1") not in ("0", "false")
    result = importer.commit(raw, name, text, skip_duplicates=skip, who=_who())
    audit.log("import", f"{result['imported']} entries, {result['properties']} items from {name or 'pasted text'}")
    return jsonify(result), 201


def _download(data, name, mime):
    return Response(data, mimetype=mime, headers={"Content-Disposition": f"attachment; filename={name}"})


@bp.get("/sheet/export.xlsx")
def export_xlsx():
    stamp = datetime.now().strftime("%Y-%m-%d")
    audit.log("export", "xlsx")
    return _download(importer.export_xlsx(request.args, _month()), f"WIMMG_{stamp}.xlsx",
                     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@bp.get("/sheet/export.csv")
def export_csv():
    what = "properties" if request.args.get("what") == "properties" else "transactions"
    stamp = datetime.now().strftime("%Y-%m-%d")
    audit.log("export", f"csv {what}")
    return _download(importer.export_csv(request.args, _month(), what), f"WIMMG_{what}_{stamp}.csv", "text/csv")


@bp.get("/sheet/template.csv")
def template():
    return _download(importer.template_csv(), "WIMMG_import_template.csv", "text/csv")
