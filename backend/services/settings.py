"""Key/value app settings stored in the `settings` table, plus the user-configurable security options."""
from ..db import get_db, rows
from ..errors import ApiError


def get_many(keys):
    marks = ",".join("?" for _ in keys)
    return {r["key"]: r["value"] for r in rows(f"SELECT key, value FROM settings WHERE key IN ({marks})", tuple(keys))}


def get(key, default=None):
    return get_many([key]).get(key, default)


def set_many(values):
    conn = get_db()
    conn.executemany(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        list(values.items()),
    )
    conn.commit()


# ---------------------------------------------------------------- options an Admin can change in the app
# key -> (label, kind, default, min, max, help)
OPTIONS = {
    "idle_minutes":     ("Log out after idle minutes", "int", 30, 5, 1440,
                         "No clicks or typing for this long ends the session."),
    "session_hours":    ("Longest login (hours)", "int", 12, 1, 168,
                         "A login always ends after this many hours, even if you stay active."),
    "max_failures":     ("Wrong attempts before lock", "int", 5, 3, 20,
                         "Wrong password or authenticator codes in a row before the user is locked."),
    "lock_minutes":     ("Lock time (minutes)", "int", 5, 1, 1440, "How long a locked user must wait."),
    "min_password":     ("Shortest password", "int", 10, 8, 64, "Applies to new and changed passwords."),
    "mfa_required":     ("Authenticator code at login", "bool", True, None, None,
                         "Every login needs the 6-digit code from an authenticator app. Recommended."),
    "auto_backup_days": ("Automatic backup every (days)", "int", 7, 1, 90,
                         "A backup is made on start-up when the last automatic one is older than this."),
    "backup_keep":      ("Backups to keep", "int", 10, 3, 200, "Older backup files are deleted automatically."),
    "autosave_rows":    ("Sheet: save a row when I leave it", "bool", True, None, None,
                         "Complete rows are saved as soon as you move to another row, no Save click needed."),
    "currency_symbol":  ("Currency symbol", "text", "₹", None, None, "Shown in front of amounts."),
}


def _coerce(key, raw):
    label, kind, default, lo, hi, _help = OPTIONS[key]
    if kind == "bool":
        return raw in (True, 1, "1", "true", "True", "on")
    if kind == "text":
        text = str(raw if raw is not None else "").strip()
        if not text or len(text) > 4:
            raise ApiError(f"{label}: use 1 to 4 characters", field=key)
        return text
    try:
        n = int(raw)
    except (TypeError, ValueError):
        raise ApiError(f"{label}: enter a whole number", field=key)
    if not lo <= n <= hi:
        raise ApiError(f"{label}: choose between {lo} and {hi}", field=key)
    return n


def option(key):
    """Current value of one option (default when never changed or when the stored value is unusable)."""
    default = OPTIONS[key][2]
    raw = get(key)
    if raw is None:
        return default
    try:
        return _coerce(key, raw)
    except ApiError:
        return default


def all_options():
    stored = get_many(list(OPTIONS))
    out = {}
    for key, (label, kind, default, lo, hi, help_) in OPTIONS.items():
        try:
            value = _coerce(key, stored[key]) if key in stored else default
        except ApiError:
            value = default
        out[key] = {"label": label, "kind": kind, "value": value, "default": default, "min": lo, "max": hi, "help": help_}
    return out


def save_options(values):
    clean = {}
    for key, raw in (values or {}).items():
        if key not in OPTIONS:
            raise ApiError(f"Unknown setting: {key}")
        value = _coerce(key, raw)
        clean[key] = ("1" if value else "0") if OPTIONS[key][1] == "bool" else str(value)
    if clean:
        set_many(clean)
    return all_options()
