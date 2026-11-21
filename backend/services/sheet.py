"""The weekly sheet: master items (category, monthly limit, usual account), accounts and the ledger entries.

An entry says: on <date>, <amount> was spent (or received) for <item>; <paid_from> actually paid, <should_pay> should have.
"Limit left" on a row is the item's monthly limit minus everything spent on that item in that month up to and
including that row (in the order the rows were entered), exactly like the spreadsheet this replaces.
"""
import sqlite3
from datetime import date as _date, datetime

from ..db import get_db, one, rows
from ..errors import ApiError
from ..money import to_paise, to_rupees

KINDS = ("expense", "income")
DEFAULT_CATEGORY = "Uncategorised"


# ---------------------------------------------------------------- helpers

def _name(value, label, field="name", max_len=80):
    text = " ".join(str(value or "").split())
    if not text:
        raise ApiError(f"{label} is required", field=field)
    if len(text) > max_len:
        raise ApiError(f"{label} is too long (max {max_len} characters)", field=field)
    return text


def _paise_or_none(value, field="monthly_limit"):
    try:
        p = to_paise(value)
    except ValueError as e:
        raise ApiError(str(e), field=field)
    if p is not None and p < 0:
        raise ApiError("The limit can't be negative", field=field)
    return p


def valid_month(month):
    try:
        datetime.strptime(month or "", "%Y-%m")
    except ValueError:
        raise ApiError("Month must look like 2026-11", field="month")
    return month


def valid_date(value):
    try:
        d = datetime.strptime(str(value or ""), "%Y-%m-%d").date()
    except ValueError:
        raise ApiError("Enter a valid date", field="date")
    if not 1990 <= d.year <= 2100:
        raise ApiError("Enter a date between 1990 and 2100", field="date")
    return d.isoformat()


def month_bounds(month):
    y, m = int(month[:4]), int(month[5:7])
    last = (_date(y + (m == 12), m % 12 + 1, 1) - _date(y, m, 1)).days
    return f"{month}-01", f"{month}-{last:02d}"


# ---------------------------------------------------------------- accounts

def _account_out(r):
    r = dict(r)
    r["active"] = bool(r["active"])
    return r


def list_accounts(include_inactive=True):
    cond = "" if include_inactive else "WHERE a.active = 1"
    data = rows(f"""SELECT a.*,
        (SELECT COUNT(*) FROM sheet_entries e WHERE e.paid_from_id = a.id OR e.should_pay_id = a.id) AS used,
        (SELECT COUNT(*) FROM sheet_items i WHERE i.account_id = a.id) AS items
        FROM sheet_accounts a {cond} ORDER BY a.sort_order, a.name COLLATE NOCASE""")
    return [_account_out(r) for r in data]


def get_or_create_account(name):
    if name is None or not str(name).strip():
        return None
    name = _name(name, "Account", "account")
    r = one("SELECT id FROM sheet_accounts WHERE name = ?", (name,))
    if r:
        return r["id"]
    cur = get_db().execute("INSERT INTO sheet_accounts (name, sort_order) VALUES (?, "
                           "(SELECT COALESCE(MAX(sort_order), 0) + 1 FROM sheet_accounts))", (name,))
    return cur.lastrowid


def create_account(data):
    name = _name(data.get("name"), "Account")
    try:
        cur = get_db().execute("INSERT INTO sheet_accounts (name, note, sort_order) VALUES (?, ?, "
                               "(SELECT COALESCE(MAX(sort_order), 0) + 1 FROM sheet_accounts))",
                               (name, str(data.get("note") or "")[:200]))
        get_db().commit()
    except sqlite3.IntegrityError:
        raise ApiError("An account with that name already exists", field="name")
    return [a for a in list_accounts() if a["id"] == cur.lastrowid][0]


def update_account(aid, data):
    r = one("SELECT * FROM sheet_accounts WHERE id = ?", (aid,))
    if not r:
        raise ApiError("Account not found", status=404)
    name = _name(data.get("name", r["name"]), "Account")
    try:
        get_db().execute("UPDATE sheet_accounts SET name = ?, note = ?, active = ? WHERE id = ?",
                         (name, str(data.get("note", r["note"]) or "")[:200], 1 if data.get("active", r["active"]) else 0, aid))
        get_db().commit()
    except sqlite3.IntegrityError:
        raise ApiError("An account with that name already exists", field="name")
    return [a for a in list_accounts() if a["id"] == aid][0]


def delete_account(aid):
    a = [a for a in list_accounts() if a["id"] == aid]
    if not a:
        raise ApiError("Account not found", status=404)
    if a[0]["used"] or a[0]["items"]:
        raise ApiError("This account is used by entries or items. Switch it to inactive instead.")
    get_db().execute("DELETE FROM sheet_accounts WHERE id = ?", (aid,))
    get_db().commit()


# ---------------------------------------------------------------- items (the "properties" list)

_ITEM_SELECT = """SELECT i.id, i.name, i.category, i.monthly_limit, i.account_id, i.active, i.sort_order,
       a.name AS account, (SELECT COUNT(*) FROM sheet_entries e WHERE e.item_id = i.id) AS used
    FROM sheet_items i LEFT JOIN sheet_accounts a ON a.id = i.account_id"""


def _item_out(r, spent=None, received=None):
    out = {"id": r["id"], "name": r["name"], "category": r["category"], "limit": to_rupees(r["monthly_limit"]),
           "account_id": r["account_id"], "account": r["account"], "active": bool(r["active"]),
           "used": r["used"]}
    if spent is not None:
        out["spent"] = to_rupees(spent)
        out["received"] = to_rupees(received or 0)
        out["left"] = None if r["monthly_limit"] is None else to_rupees(r["monthly_limit"] - spent)
    return out


def list_items(month=None, include_inactive=True):
    """All items; with `month` also what was spent on each that month and what is left of its limit."""
    cond = "" if include_inactive else " WHERE i.active = 1"
    items = rows(_ITEM_SELECT + cond + " ORDER BY i.category COLLATE NOCASE, i.sort_order, i.name COLLATE NOCASE")
    if not month:
        return [_item_out(r) for r in items]
    valid_month(month)
    first, last = month_bounds(month)
    sums = {r["item_id"]: r for r in rows(
        "SELECT item_id, SUM(CASE WHEN kind='expense' THEN amount ELSE 0 END) AS spent, "
        "SUM(CASE WHEN kind='income' THEN amount ELSE 0 END) AS received FROM sheet_entries "
        "WHERE date BETWEEN ? AND ? GROUP BY item_id", (first, last))}
    return [_item_out(r, sums.get(r["id"], {}).get("spent", 0), sums.get(r["id"], {}).get("received", 0)) for r in items]


def get_or_create_item(name, category=None, account_id=None):
    """The item with this name (case-insensitive), created with the category/account when it is new."""
    name = _name(name, "Item", "item")
    r = one("SELECT id FROM sheet_items WHERE name = ?", (name,))
    if r:
        return r["id"], False
    cat = " ".join(str(category or "").split())[:60] or DEFAULT_CATEGORY
    cur = get_db().execute("INSERT INTO sheet_items (name, category, account_id, sort_order) VALUES (?,?,?,"
                           "(SELECT COALESCE(MAX(sort_order), 0) + 1 FROM sheet_items))", (name, cat, account_id))
    return cur.lastrowid, True


def _item_fields(data, cur=None):
    name = _name(data.get("name", cur["name"] if cur else None), "Item")
    cat = " ".join(str(data.get("category", cur["category"] if cur else "") or "").split())[:60] or DEFAULT_CATEGORY
    if "limit" in data or "monthly_limit" in data:
        limit = _paise_or_none(data.get("limit", data.get("monthly_limit")))
    else:
        limit = cur["monthly_limit"] if cur else None
    if "account" in data:
        account_id = get_or_create_account(data.get("account"))
    else:
        account_id = data.get("account_id", cur["account_id"] if cur else None)
        if account_id is not None and not one("SELECT id FROM sheet_accounts WHERE id = ?", (account_id,)):
            raise ApiError("Choose a listed account", field="account_id")
    return name, cat, limit, account_id


def create_item(data):
    name, cat, limit, account_id = _item_fields(data)
    try:
        cur = get_db().execute("INSERT INTO sheet_items (name, category, monthly_limit, account_id, sort_order) VALUES (?,?,?,?,"
                               "(SELECT COALESCE(MAX(sort_order), 0) + 1 FROM sheet_items))", (name, cat, limit, account_id))
        get_db().commit()
    except sqlite3.IntegrityError:
        raise ApiError("An item with that name already exists", field="name")
    return get_item(cur.lastrowid)


def get_item(iid):
    r = one(_ITEM_SELECT + " WHERE i.id = ?", (iid,))
    if not r:
        raise ApiError("Item not found", status=404)
    return _item_out(r)


def update_item(iid, data):
    cur = one("SELECT * FROM sheet_items WHERE id = ?", (iid,))
    if not cur:
        raise ApiError("Item not found", status=404)
    name, cat, limit, account_id = _item_fields(data, cur)
    try:
        get_db().execute("UPDATE sheet_items SET name = ?, category = ?, monthly_limit = ?, account_id = ?, active = ? WHERE id = ?",
                         (name, cat, limit, account_id, 1 if data.get("active", cur["active"]) else 0, iid))
        get_db().commit()
    except sqlite3.IntegrityError:
        raise ApiError("An item with that name already exists", field="name")
    return get_item(iid)


def delete_item(iid):
    it = get_item(iid)
    if it["used"]:
        raise ApiError("This item has entries. Switch it to inactive instead of deleting it.")
    get_db().execute("DELETE FROM sheet_items WHERE id = ?", (iid,))
    get_db().commit()


def categories():
    return [r["category"] for r in rows("SELECT DISTINCT category FROM sheet_items ORDER BY category COLLATE NOCASE")]


# ---------------------------------------------------------------- entries

_RUN = """SELECT e.id AS rid,
       i.monthly_limit - SUM(CASE WHEN e.kind = 'expense' THEN e.amount ELSE 0 END)
           OVER (PARTITION BY e.item_id, substr(e.date, 1, 7) ORDER BY e.id
                 ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS left_p
    FROM sheet_entries e JOIN sheet_items i ON i.id = e.item_id"""

ENTRY_SELECT = f"""WITH run AS ({_RUN})
SELECT e.id, e.date, e.kind, e.item_id, i.name AS item, i.category, e.amount, e.paid_from_id, e.should_pay_id,
       pf.name AS paid_from, sp.name AS should_pay, e.note, e.created_by, i.monthly_limit,
       CASE WHEN e.kind = 'expense' THEN run.left_p END AS left_p
FROM sheet_entries e
JOIN sheet_items i ON i.id = e.item_id
LEFT JOIN sheet_accounts pf ON pf.id = e.paid_from_id
LEFT JOIN sheet_accounts sp ON sp.id = e.should_pay_id
LEFT JOIN run ON run.rid = e.id"""


def _entry_out(r):
    return {
        "id": r["id"], "date": r["date"], "kind": r["kind"], "item_id": r["item_id"], "item": r["item"],
        "category": r["category"], "amount": to_rupees(r["amount"]),
        "paid_from_id": r["paid_from_id"], "paid_from": r["paid_from"],
        "should_pay_id": r["should_pay_id"], "should_pay": r["should_pay"],
        "note": r["note"], "created_by": r["created_by"],
        "limit": to_rupees(r["monthly_limit"]), "limit_left": to_rupees(r["left_p"]),
    }


def _filters(args):
    where, params = [], []
    month = args.get("month")
    if month:
        first, last = month_bounds(valid_month(month))
        where.append("e.date BETWEEN ? AND ?")
        params += [first, last]
    if args.get("from"):
        where.append("e.date >= ?")
        params.append(valid_date(args["from"]))
    if args.get("to"):
        where.append("e.date <= ?")
        params.append(valid_date(args["to"]))
    if args.get("item_id"):
        where.append("e.item_id = ?")
        params.append(int(args["item_id"]))
    if args.get("category"):
        where.append("i.category = ?")
        params.append(args["category"])
    if args.get("account_id"):
        where.append("(e.paid_from_id = ? OR e.should_pay_id = ?)")
        params += [int(args["account_id"])] * 2
    if args.get("kind") in KINDS:
        where.append("e.kind = ?")
        params.append(args["kind"])
    q = (args.get("q") or "").strip()
    if q:
        where.append("(i.name LIKE ? ESCAPE '\\' OR e.note LIKE ? ESCAPE '\\' OR i.category LIKE ? ESCAPE '\\')")
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        params += [like] * 3
    return (" WHERE " + " AND ".join(where)) if where else "", params


def list_entries(args):
    where, params = _filters(args)
    order = "ASC" if args.get("order", "asc") == "asc" else "DESC"
    try:
        limit = max(1, min(int(args.get("limit", 500)), 1_000_000))
        offset = max(0, int(args.get("offset", 0)))
    except ValueError:
        raise ApiError("limit and offset must be numbers")
    data = rows(f"{ENTRY_SELECT}{where} ORDER BY e.id {order} LIMIT ? OFFSET ?", params + [limit, offset])
    tot = one(f"SELECT COUNT(*) AS n, COALESCE(SUM(CASE WHEN e.kind='expense' THEN e.amount END),0) AS exp, "
              f"COALESCE(SUM(CASE WHEN e.kind='income' THEN e.amount END),0) AS inc "
              f"FROM sheet_entries e JOIN sheet_items i ON i.id = e.item_id{where}", params)
    return {"rows": [_entry_out(r) for r in data], "total": tot["n"],
            "expense": to_rupees(tot["exp"]), "income": to_rupees(tot["inc"])}


def get_entry(eid):
    r = one(ENTRY_SELECT + " WHERE e.id = ?", (eid,))
    if not r:
        raise ApiError("Entry not found", status=404)
    return _entry_out(r)


def prepare(data):
    """Validate one entry and resolve item / accounts by name (creating missing ones). Returns column values."""
    d = valid_date(data.get("date"))
    kind = data.get("kind") or "expense"
    if kind not in KINDS:
        raise ApiError("Type must be Expense or Income", field="kind")
    try:
        amount = to_paise(data.get("amount"))
    except ValueError as e:
        raise ApiError(str(e), field="amount")
    if amount is None or amount <= 0:
        raise ApiError("Enter an amount above zero", field="amount")
    if data.get("item_id") and not data.get("item"):
        r = one("SELECT name FROM sheet_items WHERE id = ?", (int(data["item_id"]),))
        if not r:
            raise ApiError("Item not found", field="item")
        data = {**data, "item": r["name"]}
    should_id = get_or_create_account(data.get("should_pay"))
    item_id, _new = get_or_create_item(data.get("item"), data.get("category"), should_id)
    if should_id is None:
        should_id = (one("SELECT account_id FROM sheet_items WHERE id = ?", (item_id,)) or {}).get("account_id")
    paid_id = get_or_create_account(data.get("paid_from"))
    return {"date": d, "kind": kind, "item_id": item_id, "amount": amount, "paid_from_id": paid_id,
            "should_pay_id": should_id, "note": str(data.get("note") or "").strip()[:200]}


def create_entry(data, who=""):
    v = prepare(data)
    cur = get_db().execute(
        "INSERT INTO sheet_entries (date, kind, item_id, amount, paid_from_id, should_pay_id, note, created_by) "
        "VALUES (:date, :kind, :item_id, :amount, :paid_from_id, :should_pay_id, :note, :who)", {**v, "who": who})
    get_db().commit()
    return get_entry(cur.lastrowid)


def create_many(items, who=""):
    """Save several rows. Each row stands alone: a bad row is reported and the good ones are saved."""
    saved, errors = [], []
    for n, data in enumerate(items):
        key = data.get("client_id", n) if isinstance(data, dict) else n
        try:
            if not isinstance(data, dict):
                raise ApiError("Bad row")
            saved.append({"client_id": key, "entry": create_entry(data, who)})
        except ApiError as e:
            get_db().rollback()
            errors.append({"client_id": key, "error": e.message, "field": e.field})
    return {"saved": saved, "errors": errors}


def update_entry(eid, data):
    if not one("SELECT id FROM sheet_entries WHERE id = ?", (eid,)):
        raise ApiError("Entry not found", status=404)
    v = prepare(data)
    get_db().execute(
        "UPDATE sheet_entries SET date=:date, kind=:kind, item_id=:item_id, amount=:amount, paid_from_id=:paid_from_id, "
        "should_pay_id=:should_pay_id, note=:note, updated_at=datetime('now','localtime') WHERE id=:id", {**v, "id": eid})
    get_db().commit()
    return get_entry(eid)


def delete_entry(eid):
    n = get_db().execute("DELETE FROM sheet_entries WHERE id = ?", (eid,)).rowcount
    get_db().commit()
    if not n:
        raise ApiError("Entry not found", status=404)


# ---------------------------------------------------------------- what the entry form needs

def spent_by_month(months):
    """{month: {item_id: spent_rupees}} for the months asked (limit tracking while typing)."""
    out = {}
    for m in months[:24]:
        first, last = month_bounds(valid_month(m))
        out[m] = {r["item_id"]: to_rupees(r["s"]) for r in rows(
            "SELECT item_id, SUM(amount) AS s FROM sheet_entries WHERE kind='expense' AND date BETWEEN ? AND ? "
            "GROUP BY item_id", (first, last))}
    return out


def bootstrap(month):
    """Everything the sheet needs in one go: items, accounts, what each item usually uses, and this month's totals."""
    items = list_items(include_inactive=False)
    # per item: the account that paid last time, and the last amount (from history)
    hints = {}
    for r in rows("""SELECT e.item_id, e.paid_from_id, e.should_pay_id, e.amount, e.kind, c.n
                     FROM sheet_entries e
                     JOIN (SELECT MAX(id) AS last_id, COUNT(*) AS n FROM sheet_entries GROUP BY item_id) c ON c.last_id = e.id"""):
        hints[r["item_id"]] = {"paid_from_id": r["paid_from_id"], "should_pay_id": r["should_pay_id"],
                               "last_amount": to_rupees(r["amount"]), "kind": r["kind"], "count": r["n"]}
    return {"items": items, "accounts": list_accounts(include_inactive=False), "categories": categories(),
            "hints": hints, "spent": spent_by_month([month])[month], "month": month}


# ---------------------------------------------------------------- insights

def _range(args):
    frm, to = args.get("from"), args.get("to")
    if args.get("month"):
        frm, to = month_bounds(valid_month(args["month"]))
    return (valid_date(frm) if frm else None), (valid_date(to) if to else None)


def insights(args):
    frm, to = _range(args)
    cond, params = [], []
    if frm:
        cond.append("e.date >= ?"); params.append(frm)
    if to:
        cond.append("e.date <= ?"); params.append(to)
    where = (" WHERE " + " AND ".join(cond)) if cond else ""
    base = "FROM sheet_entries e JOIN sheet_items i ON i.id = e.item_id"

    tot = one(f"SELECT COUNT(*) AS n, COALESCE(SUM(CASE WHEN e.kind='expense' THEN e.amount END),0) AS exp, "
              f"COALESCE(SUM(CASE WHEN e.kind='income' THEN e.amount END),0) AS inc, MIN(e.date) AS first, MAX(e.date) AS last "
              f"{base}{where}", params)
    by_cat = rows(f"SELECT i.category AS name, SUM(e.amount) AS v, COUNT(*) AS n {base}{where}"
                  f"{' AND' if where else ' WHERE'} e.kind='expense' GROUP BY i.category ORDER BY v DESC", params)
    by_item = rows(f"SELECT i.id, i.name, i.category, SUM(e.amount) AS v, COUNT(*) AS n {base}{where}"
                   f"{' AND' if where else ' WHERE'} e.kind='expense' GROUP BY i.id ORDER BY v DESC LIMIT 25", params)
    monthly = rows(f"SELECT substr(e.date,1,7) AS month, "
                   f"SUM(CASE WHEN e.kind='expense' THEN e.amount ELSE 0 END) AS expense, "
                   f"SUM(CASE WHEN e.kind='income' THEN e.amount ELSE 0 END) AS income {base}{where} "
                   f"GROUP BY substr(e.date,1,7) ORDER BY month", params)
    # month x category (heat map data)
    grid = rows(f"SELECT substr(e.date,1,7) AS month, i.category AS name, SUM(e.amount) AS v {base}{where}"
                f"{' AND' if where else ' WHERE'} e.kind='expense' GROUP BY 1, 2", params)

    # who paid vs who should have paid
    pair = {}
    for r in rows(f"SELECT e.kind, e.paid_from_id AS p, e.should_pay_id AS s, SUM(e.amount) AS v {base}{where}"
                  f"{' AND' if where else ' WHERE'} e.paid_from_id IS NOT NULL AND e.should_pay_id IS NOT NULL "
                  f"GROUP BY e.kind, e.paid_from_id, e.should_pay_id", params):
        if r["p"] == r["s"]:
            continue
        # expense: p fronted the money, so s owes p.  income: p holds money that belongs to s, so p owes s.
        creditor, debtor = (r["p"], r["s"]) if r["kind"] == "expense" else (r["s"], r["p"])
        pair[(debtor, creditor)] = pair.get((debtor, creditor), 0) + r["v"]
    acc_name = {a["id"]: a["name"] for a in list_accounts()}
    transfers, nets = [], {}
    for (debtor, creditor), v in list(pair.items()):
        back = pair.get((creditor, debtor), 0)
        if (debtor, creditor) in pair and v > back:
            transfers.append({"from": acc_name[debtor], "to": acc_name[creditor], "amount": to_rupees(v - back)})
            nets[debtor] = nets.get(debtor, 0) - (v - back)
            nets[creditor] = nets.get(creditor, 0) + (v - back)
    transfers.sort(key=lambda t: -t["amount"])
    accounts = [{"name": acc_name[k], "net": to_rupees(v)} for k, v in sorted(nets.items(), key=lambda kv: -kv[1])]
    flow = rows(f"SELECT a.name, SUM(CASE WHEN e.kind='expense' THEN e.amount ELSE 0 END) AS paid, "
                f"SUM(CASE WHEN e.kind='income' THEN e.amount ELSE 0 END) AS received "
                f"{base} JOIN sheet_accounts a ON a.id = e.paid_from_id{where} GROUP BY a.id ORDER BY paid DESC", params)
    share = {r["name"]: r["v"] for r in rows(
        f"SELECT a.name, SUM(e.amount) AS v {base} JOIN sheet_accounts a ON a.id = e.should_pay_id{where}"
        f"{' AND' if where else ' WHERE'} e.kind='expense' GROUP BY a.id", params)}

    # limit usage per item for the month at the end of the range (or this month)
    month = args.get("limit_month") or (to or frm or datetime.now().strftime("%Y-%m-%d"))[:7]
    limits = [i for i in list_items(month, include_inactive=False) if i["limit"]]
    limits.sort(key=lambda i: -(i["spent"] / i["limit"]))
    # how often each item went over its limit in the range
    over = rows(f"""SELECT name, category, COUNT(*) AS months, SUM(over) AS over FROM (
                      SELECT i.name, i.category, substr(e.date,1,7) AS m,
                             SUM(e.amount) - i.monthly_limit AS over
                      {base}{where}{' AND' if where else ' WHERE'} e.kind='expense' AND i.monthly_limit IS NOT NULL
                      GROUP BY i.id, substr(e.date,1,7) HAVING SUM(e.amount) > i.monthly_limit)
                    GROUP BY name, category ORDER BY over DESC LIMIT 15""", params)

    return {
        "range": {"from": frm, "to": to, "first_entry": tot["first"], "last_entry": tot["last"]},
        "totals": {"entries": tot["n"], "expense": to_rupees(tot["exp"]), "income": to_rupees(tot["inc"]),
                   "net": to_rupees(tot["inc"] - tot["exp"])},
        "by_category": [{"name": r["name"], "value": to_rupees(r["v"]), "count": r["n"]} for r in by_cat],
        "by_item": [{"id": r["id"], "name": r["name"], "category": r["category"], "value": to_rupees(r["v"]), "count": r["n"]}
                    for r in by_item],
        "monthly": [{"month": r["month"], "expense": to_rupees(r["expense"]), "income": to_rupees(r["income"])} for r in monthly],
        "grid": [{"month": r["month"], "name": r["name"], "value": to_rupees(r["v"])} for r in grid],
        "settlement": {"transfers": transfers, "accounts": accounts},
        "accounts": [{"name": r["name"], "paid": to_rupees(r["paid"]), "received": to_rupees(r["received"]),
                      "should_pay": to_rupees(share.get(r["name"], 0))} for r in flow],
        "limits": {"month": month, "items": limits},
        "overspent": [{"name": r["name"], "category": r["category"], "months": r["months"], "over": to_rupees(r["over"])} for r in over],
    }
