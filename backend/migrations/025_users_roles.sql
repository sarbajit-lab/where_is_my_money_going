-- migrate: foreign_keys off
-- 025_users_roles.sql
-- Role-based access control (RBAC): several users, each with a role that lists what they may do.
-- The single-user "email" login becomes a "username"; an existing login is kept and becomes an Admin.
-- Password reset by email is removed (the app is fully offline): an Admin resets passwords from the app instead.

CREATE TABLE roles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    description TEXT    NOT NULL DEFAULT '',
    permissions TEXT    NOT NULL DEFAULT '',          -- comma-separated permission keys (see backend/permissions.py)
    is_system   INTEGER NOT NULL DEFAULT 0,           -- 1 = built-in (Admin cannot lose any permission or be deleted)
    created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

INSERT INTO roles (name, description, permissions, is_system) VALUES
    ('Admin',  'Everything, including users, roles, settings and backups',
     'view,data.write,masters.write,data.import,data.export,backup.manage,settings.manage,users.manage', 1),
    ('Editor', 'Add and change entries, items and limits; import and export',
     'view,data.write,masters.write,data.import,data.export', 1),
    ('Viewer', 'Read-only: look at the sheet, limits and insights',
     'view', 1);

CREATE TABLE users_new (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    username             TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    full_name            TEXT    NOT NULL DEFAULT '',
    password_hash        TEXT    NOT NULL,                 -- scrypt, salted (werkzeug.security)
    password_version     INTEGER NOT NULL DEFAULT 1,       -- bumped on password change/reset: logs out old sessions
    totp_secret          TEXT,                             -- base32; NULL until the authenticator is set up
    totp_last_step       INTEGER NOT NULL DEFAULT 0,       -- last accepted 30-second step (blocks code re-use)
    failed_attempts      INTEGER NOT NULL DEFAULT 0,
    locked_until         TEXT,                             -- ISO timestamp (UTC)
    last_login_at        TEXT,
    created_at           TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    role_id              INTEGER NOT NULL REFERENCES roles (id),
    active               INTEGER NOT NULL DEFAULT 1,
    must_change_password INTEGER NOT NULL DEFAULT 0
);
INSERT INTO users_new (id, username, password_hash, password_version, totp_secret, totp_last_step,
                       failed_attempts, locked_until, last_login_at, created_at, role_id)
    SELECT id, email, password_hash, password_version, totp_secret, totp_last_step,
           failed_attempts, locked_until, last_login_at, created_at, (SELECT id FROM roles WHERE name = 'Admin')
    FROM users;
DROP TABLE password_resets;
DROP TABLE users;
ALTER TABLE users_new RENAME TO users;

-- who did what (logins, user changes, imports, backups)
CREATE TABLE audit_log (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    at     TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    actor  TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX idx_audit_at ON audit_log (at);
