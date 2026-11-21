"""A small who-did-what log for the multi-user app (logins, user changes, imports, backups)."""
from flask import session

from ..db import get_db, rows


def log(action, detail="", actor=None):
    if actor is None:
        actor = session.get("uname", "") if session else ""
    conn = get_db()
    conn.execute("INSERT INTO audit_log (actor, action, detail) VALUES (?, ?, ?)", (actor, action, str(detail)[:500]))
    conn.execute("DELETE FROM audit_log WHERE id <= (SELECT MAX(id) FROM audit_log) - 5000")     # keep the newest 5000
    conn.commit()


def recent(limit=200):
    return rows("SELECT at, actor, action, detail FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))
