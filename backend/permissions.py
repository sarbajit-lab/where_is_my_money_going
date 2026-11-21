"""What a role can be allowed to do (RBAC). Roles are stored in the database; this file is the catalogue of
permission keys and the rule that maps an API request to the permission it needs."""

PERMISSIONS = {
    "view":            "See the sheet, limits, insights and every other screen",
    "data.write":      "Add, edit and delete entries (sheet, transactions, investments, loans, budget)",
    "masters.write":   "Change items, categories, monthly limits and accounts",
    "data.import":     "Import Excel / CSV files",
    "data.export":     "Export Excel / CSV files",
    "backup.manage":   "Back up and restore the database",
    "settings.manage": "Change app settings (session timeout, security rules)",
    "users.manage":    "Create users, change roles, reset passwords and logins",
}
ALL = tuple(PERMISSIONS)


def parse(text):
    """'view,data.write' -> ['view', 'data.write'] (unknown keys dropped, order of the catalogue)."""
    have = {p.strip() for p in (text or "").split(",")}
    return [p for p in ALL if p in have]


def join(perms):
    return ",".join(p for p in ALL if p in set(perms))


def required(method, path):
    """The permission an API request needs, or None when any logged-in user may call it."""
    method = method.upper()
    read = method in ("GET", "HEAD", "OPTIONS")
    p = path[len("/api/"):] if path.startswith("/api/") else path
    top = p.split("/", 1)[0]

    if top == "auth":
        return None                                   # your own login, password and authenticator
    if top in ("users", "roles", "audit"):
        return "users.manage"
    if top == "app-settings":
        return None if read else "settings.manage"
    if p in ("system/backups", "system/backup-to", "system/restore", "system/restore-backup"):
        return "backup.manage"
    if p == "system/export.csv" or p.startswith("sheet/export"):
        return "data.export"
    if p.startswith("sheet/import"):
        return "data.import"
    if p.startswith("sheet/template"):
        return "view"
    if top in ("sheet",) and p.split("/")[1:2] in (["items"], ["accounts"]) and not read:
        return "masters.write"
    if top == "masters" and not read:
        return "masters.write"
    return "view" if read else "data.write"
