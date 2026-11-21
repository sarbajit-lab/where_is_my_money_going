"""Import and export the sheet in the same layout as the spreadsheet it replaces.

Transactions:  Date | Item | Category | Amount | Limit Left | Paid From | Should Pay   (+ optional Type | Note)
Properties:    Master Items | Category | Limit | Spent | Limit Left | Account

Files can be .xlsx (every sheet is looked at, the layout tells which is which), .csv / .tsv, or text pasted from Excel.
"""
import csv
import io
import re
from collections import Counter
from datetime import date, datetime, timedelta

from ..db import get_db, rows
from ..errors import ApiError
from ..money import to_paise, to_rupees
from . import sheet as sheet_svc
from . import xlsx

EPOCH = date(1899, 12, 30)
MAX_ROWS = 200_000

TX_COLUMNS = {
    "date": {"date", "transactiondate", "txndate"},
    "item": {"item", "items", "masteritem", "masteritems", "description", "particulars"},
    "category": {"category", "group"},
    "amount": {"amount", "amt", "value"},
    "paid_from": {"paidfrom", "paidby", "paidfromaccount", "account"},
    "should_pay": {"shouldpay", "shouldpayfrom", "shouldbepaidfrom", "shouldpayby"},
    "kind": {"type", "kind", "entrytype"},
    "note": {"note", "notes", "remark", "remarks", "comment"},
}
PROP_COLUMNS = {
    "item": {"masteritems", "masteritem", "item", "items"},
    "category": {"category"},
    "limit": {"limit", "monthlylimit", "budget"},
    "account": {"account", "shouldpay", "defaultaccount"},
}
DATE_FORMATS = ("%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%d %B %Y", "%d-%b-%Y", "%d-%b-%y", "%d %b, %Y", "%b %d %Y",
                "%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y")
MONTH_FIRST = ("%m/%d/%Y", "%m-%d-%Y")        # only tried when day-first is impossible (e.g. 11/25/2026)


def _norm(h):
    return re.sub(r"[^a-z0-9]", "", str(h or "").lower())


def _text(v):
    if v is None:
        return ""
    if isinstance(v, float) and v == int(v):
        v = int(v)
    return " ".join(str(v).split())


# ---------------------------------------------------------------- reading a file into tables

def tables_from(raw, filename="", text=None):
    """{name: rows} from an uploaded file (bytes) or pasted text."""
    if text is not None:
        return {"Pasted": _delimited(text)}
    name = (filename or "").lower()
    if raw[:2] == b"PK" or name.endswith((".xlsx", ".xlsm")):
        return xlsx.read_xlsx(raw)
    if raw[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        raise ApiError("That is an old .xls file. In Excel choose Save As → .xlsx (or CSV), then import that.")
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            return {"CSV": _delimited(raw.decode(enc))}
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise ApiError("Couldn't read that file as text.")


def _delimited(text):
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []
    sample = lines[:30]
    counts = {d: sum(ln.count(d) for ln in sample) for d in ("\t", ",", ";")}
    delim = max(counts, key=lambda d: (counts[d], d == "\t", d == ","))
    return [r for r in csv.reader(io.StringIO("\n".join(lines)), delimiter=delim)]


def _find_header(table, wanted):
    """First row (within 20) that has the key columns; returns (row index, {field: column index})."""
    for ri, row in enumerate(table[:20]):
        cols = {}
        for ci, cell in enumerate(row):
            n = _norm(cell)
            for field, names in wanted.items():
                if n in names and field not in cols:
                    cols[field] = ci
        yield ri, cols


def classify(table):
    """('transactions'|'properties'|None, header row, columns)."""
    for ri, cols in _find_header(table, TX_COLUMNS):
        if {"date", "item", "amount"} <= set(cols):
            return "transactions", ri, cols
    for ri, cols in _find_header(table, PROP_COLUMNS):
        header = {_norm(c) for c in table[ri]}
        if "item" in cols and "limit" in cols and "date" not in header:
            return "properties", ri, cols
    return None, 0, {}


# ---------------------------------------------------------------- cell parsing

def parse_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if 20000 < v < 80000:
            return EPOCH + timedelta(days=int(v))
        raise ValueError("not a date")
    s = _text(v)
    if not s:
        raise ValueError("empty")
    if re.fullmatch(r"\d{5}(\.\d+)?", s) and 20000 < float(s) < 80000:
        return EPOCH + timedelta(days=int(float(s)))
    s = re.sub(r"(?<=\d)(st|nd|rd|th)\b", "", s)
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    for fmt in MONTH_FIRST:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"'{s[:20]}' is not a date")


def parse_amount(v):
    """-> paise (may be negative). Accepts 1,170 / ₹1,170.50 / (500) / -2,899 / 1170."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return to_paise(v)
    s = str(v).strip()
    neg = s.startswith("(") and s.endswith(")")
    s = re.sub(r"[₹\s]|Rs\.?|INR", "", s.strip("()"), flags=re.I).replace("−", "-")
    p = to_paise(s)
    return -p if neg and p is not None else p


def _cell(row, cols, field):
    i = cols.get(field)
    return row[i] if i is not None and i < len(row) else None


# ---------------------------------------------------------------- analysis (preview) and commit

def parse_transactions(table, head, cols):
    out, issues = [], []
    for ri in range(head + 1, len(table)):
        row = table[ri]
        if not any(_text(c) for c in row):
            continue
        line = ri + 1
        if len(out) + len(issues) > MAX_ROWS:
            raise ApiError("That file has too many rows.")
        raw_date, item = _cell(row, cols, "date"), _text(_cell(row, cols, "item"))
        if not _text(raw_date) and not item and parse_amount_safe(_cell(row, cols, "amount")) is None:
            continue
        try:
            d = parse_date(raw_date)
            amount = parse_amount(_cell(row, cols, "amount"))
            if not item:
                raise ValueError("Item is empty")
            if amount is None or amount == 0:
                raise ValueError("Amount is empty or zero")
        except ValueError as e:
            issues.append({"line": line, "error": str(e)})
            continue
        kind = _text(_cell(row, cols, "kind")).lower()
        kind = "income" if kind.startswith(("inc", "cr", "rec")) else "expense"
        if amount < 0:                       # a negative expense is money coming back
            kind, amount = ("income" if kind == "expense" else "expense"), -amount
        out.append({"line": line, "date": d.isoformat(), "item": item, "category": _text(_cell(row, cols, "category")),
                    "amount_p": amount, "paid_from": _text(_cell(row, cols, "paid_from")),
                    "should_pay": _text(_cell(row, cols, "should_pay")), "kind": kind,
                    "note": _text(_cell(row, cols, "note"))})
    return out, issues


def parse_amount_safe(v):
    try:
        return parse_amount(v)
    except ValueError:
        return None


def parse_properties(table, head, cols):
    out, issues = [], []
    for ri in range(head + 1, len(table)):
        row = table[ri]
        name = _text(_cell(row, cols, "item"))
        if not name:
            if any(_text(c) for c in row):
                issues.append({"line": ri + 1, "error": "Item name is empty"})
            continue
        try:
            raw = _cell(row, cols, "limit")
            limit = parse_amount(raw)
            if limit is not None and limit < 0:
                raise ValueError("Limit can't be negative")
        except ValueError as e:
            issues.append({"line": ri + 1, "error": str(e)})
            continue
        out.append({"line": ri + 1, "item": name, "category": _text(_cell(row, cols, "category")),
                    "limit_p": limit, "account": _text(_cell(row, cols, "account"))})
    return out, issues


def _tx_key(d, item, amount, paid, should, kind):
    return (d, item.lower(), amount, paid.lower(), should.lower(), kind)


def analyse(raw=None, filename="", text=None):
    """Read a file and report what importing it would do, without changing anything."""
    tables = tables_from(raw, filename, text)
    tx, props, issues, skipped = [], [], [], []
    for name, table in tables.items():
        kind, head, cols = classify(table)
        if kind == "transactions":
            ok, bad = parse_transactions(table, head, cols)
            tx += [{**r, "sheet": name} for r in ok]
            issues += [{**b, "sheet": name} for b in bad]
        elif kind == "properties":
            ok, bad = parse_properties(table, head, cols)
            props += [{**r, "sheet": name} for r in ok]
            issues += [{**b, "sheet": name} for b in bad]
        elif table:
            skipped.append(name)
    if not tx and not props:
        raise ApiError("Couldn't find a table to import. The first row needs the headings "
                       "Date, Item, Amount (and usually Category, Paid From, Should Pay) — or Master Items, Category, Limit, Account.")
    return {"transactions": tx, "properties": props, "issues": issues, "skipped_sheets": skipped}


def _existing_counts(dates):
    if not dates:
        return Counter()
    cnt = Counter()
    for r in rows("""SELECT e.date, i.name AS item, e.amount, COALESCE(pf.name,'') AS pf, COALESCE(sp.name,'') AS sp, e.kind
                     FROM sheet_entries e JOIN sheet_items i ON i.id = e.item_id
                     LEFT JOIN sheet_accounts pf ON pf.id = e.paid_from_id LEFT JOIN sheet_accounts sp ON sp.id = e.should_pay_id
                     WHERE e.date BETWEEN ? AND ?""", (min(dates), max(dates))):
        cnt[_tx_key(r["date"], r["item"], r["amount"], r["pf"], r["sp"], r["kind"])] += 1
    return cnt


def split_duplicates(tx):
    """Mark rows already in the database. Counts are matched like a multiset: a file with the same row twice and a
    database holding it once imports it once more."""
    have = _existing_counts([r["date"] for r in tx])
    fresh, dup = [], []
    for r in tx:
        k = _tx_key(r["date"], r["item"], r["amount_p"], r["paid_from"], r["should_pay"], r["kind"])
        if have[k] > 0:
            have[k] -= 1
            dup.append(r)
        else:
            fresh.append(r)
    return fresh, dup


def preview(raw=None, filename="", text=None):
    a = analyse(raw, filename, text)
    fresh, dup = split_duplicates(a["transactions"])
    known_items = {r["name"].lower() for r in rows("SELECT name FROM sheet_items")}
    known_acc = {r["name"].lower() for r in rows("SELECT name FROM sheet_accounts")}
    names_items = {r["item"] for r in a["transactions"]} | {r["item"] for r in a["properties"]}
    names_acc = {x for r in a["transactions"] for x in (r["paid_from"], r["should_pay"]) if x} | \
                {r["account"] for r in a["properties"] if r["account"]}
    dates = [r["date"] for r in a["transactions"]]
    sample = [{"line": r["line"], "date": r["date"], "item": r["item"], "category": r["category"],
               "amount": to_rupees(r["amount_p"]), "paid_from": r["paid_from"], "should_pay": r["should_pay"],
               "kind": r["kind"], "duplicate": r in dup} for r in a["transactions"][:15]]
    return {
        "transactions": len(a["transactions"]), "new_transactions": len(fresh), "duplicates": len(dup),
        "properties": len(a["properties"]), "issues": a["issues"][:50], "issue_count": len(a["issues"]),
        "new_items": sorted(n for n in names_items if n.lower() not in known_items)[:200],
        "new_accounts": sorted(n for n in names_acc if n.lower() not in known_acc),
        "first_date": min(dates) if dates else None, "last_date": max(dates) if dates else None,
        "income_rows": sum(1 for r in a["transactions"] if r["kind"] == "income"),
        "sample": sample, "skipped_sheets": a["skipped_sheets"],
    }


def commit(raw=None, filename="", text=None, skip_duplicates=True, who=""):
    """Import for real, in one transaction: either everything is saved or nothing."""
    a = analyse(raw, filename, text)
    tx = a["transactions"]
    dup = []
    if skip_duplicates:
        tx, dup = split_duplicates(tx)
    conn = get_db()
    before_items = conn.execute("SELECT COUNT(*) FROM sheet_items").fetchone()[0]
    before_acc = conn.execute("SELECT COUNT(*) FROM sheet_accounts").fetchone()[0]
    try:
        for p in a["properties"]:
            acc = sheet_svc.get_or_create_account(p["account"]) if p["account"] else None
            iid, _ = sheet_svc.get_or_create_item(p["item"], p["category"], acc)
            conn.execute("UPDATE sheet_items SET monthly_limit = ?, category = COALESCE(NULLIF(?, ''), category), "
                         "account_id = COALESCE(?, account_id) WHERE id = ?", (p["limit_p"], p["category"], acc, iid))
        mismatched = set()
        for r in tx:
            should = sheet_svc.get_or_create_account(r["should_pay"]) if r["should_pay"] else None
            iid, new = sheet_svc.get_or_create_item(r["item"], r["category"], should)
            if not new and r["category"]:
                cur = conn.execute("SELECT category FROM sheet_items WHERE id = ?", (iid,)).fetchone()[0]
                if cur.lower() != r["category"].lower():
                    mismatched.add(r["item"])
            if should is None:
                should = conn.execute("SELECT account_id FROM sheet_items WHERE id = ?", (iid,)).fetchone()[0]
            paid = sheet_svc.get_or_create_account(r["paid_from"]) if r["paid_from"] else None
            conn.execute("INSERT INTO sheet_entries (date, kind, item_id, amount, paid_from_id, should_pay_id, note, created_by) "
                         "VALUES (?,?,?,?,?,?,?,?)", (r["date"], r["kind"], iid, r["amount_p"], paid, should, r["note"], who))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {
        "imported": len(tx), "skipped_duplicates": len(dup), "properties": len(a["properties"]),
        "problems": a["issues"][:50], "problem_count": len(a["issues"]),
        "new_items": conn.execute("SELECT COUNT(*) FROM sheet_items").fetchone()[0] - before_items,
        "new_accounts": conn.execute("SELECT COUNT(*) FROM sheet_accounts").fetchone()[0] - before_acc,
        "category_differs": sorted(mismatched)[:50],
    }


# ---------------------------------------------------------------- export

TX_HEADER = ["Date", "Item", "Category", "Amount", "Limit Left", "Paid From", "Should Pay", "Type", "Note"]
PROP_HEADER = ["Master Items", "Category", "Limit", "Spent", "Limit Left", "Account"]


def _num(v):
    return None if v is None else (int(v) if float(v) == int(v) else v)


def export_rows(args):
    data = sheet_svc.list_entries({**args, "limit": 1_000_000, "order": "asc"})["rows"]
    out = []
    for r in data:
        out.append([date.fromisoformat(r["date"]), r["item"], r["category"], _num(r["amount"]),
                    _num(r["limit_left"]) if r["limit_left"] is not None else 0,
                    r["paid_from"] or "", r["should_pay"] or "", r["kind"].title(), r["note"]])
    return out


def export_props(month):
    out = []
    for i in sheet_svc.list_items(month):
        out.append([i["name"], i["category"], _num(i["limit"]), _num(i["spent"]),
                    _num(i["left"]), i["account"] or ""])
    return out


def export_xlsx(args, month):
    tx = export_rows(args)
    return xlsx.write_xlsx([
        xlsx.Sheet("Transactions", [TX_HEADER] + tx, [14, 24, 16, 12, 12, 16, 16, 10, 30]),
        xlsx.Sheet("Properties", [PROP_HEADER] + export_props(month), [26, 16, 12, 12, 12, 16]),
    ])


def _csv_cell(v):
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v                      # stops Excel running text as a formula
    return v


def export_csv(args, month, what="transactions"):
    buf = io.StringIO()
    buf.write("﻿")
    w = csv.writer(buf)
    if what == "properties":
        w.writerow(PROP_HEADER)
        for r in export_props(month):
            w.writerow([_csv_cell(c) if c is not None else "" for c in r])
    else:
        w.writerow(TX_HEADER)
        for r in export_rows(args):
            w.writerow([r[0].strftime("%b ") + str(r[0].day) + r[0].strftime(", %Y")] + [_csv_cell(c) if c is not None else "" for c in r[1:]])
    return buf.getvalue()


def template_csv():
    buf = io.StringIO()
    buf.write("﻿")
    w = csv.writer(buf)
    w.writerow(TX_HEADER[:7])
    w.writerow(["Nov 1, 2026", "Grocery", "Utility", 1170, "", "Bank A", "Bank A"])
    w.writerow(["Nov 2, 2026", "Outside Food", "Savings", 396, "", "Card B", "Bank A"])
    return buf.getvalue()
