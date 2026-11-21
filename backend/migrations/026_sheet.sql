-- 026_sheet.sql
-- The weekly "sheet": a flat ledger like a spreadsheet. Each row says what was bought (an item), how much,
-- which account PAID it and which account SHOULD have paid it. Items live in a master list with a category,
-- a monthly limit and the account that normally pays for them. Amounts are INTEGER paise (Rs 1 = 100).

CREATE TABLE sheet_accounts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    note       TEXT    NOT NULL DEFAULT '',
    active     INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE sheet_items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    category      TEXT    NOT NULL DEFAULT 'Uncategorised' COLLATE NOCASE,
    monthly_limit INTEGER CHECK (monthly_limit IS NULL OR monthly_limit >= 0),   -- paise; NULL = no limit
    account_id    INTEGER REFERENCES sheet_accounts (id),                         -- the account that should pay
    active        INTEGER NOT NULL DEFAULT 1,
    sort_order    INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE sheet_entries (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    date          TEXT    NOT NULL,                                   -- YYYY-MM-DD
    kind          TEXT    NOT NULL DEFAULT 'expense' CHECK (kind IN ('expense', 'income')),
    item_id       INTEGER NOT NULL REFERENCES sheet_items (id),
    amount        INTEGER NOT NULL CHECK (amount > 0),                -- paise
    paid_from_id  INTEGER REFERENCES sheet_accounts (id),             -- expense: account that paid; income: account it landed in
    should_pay_id INTEGER REFERENCES sheet_accounts (id),             -- the account that should have paid / received
    note          TEXT    NOT NULL DEFAULT '',
    created_by    TEXT    NOT NULL DEFAULT '',
    created_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX idx_sheet_entries_date ON sheet_entries (date);
CREATE INDEX idx_sheet_entries_item ON sheet_entries (item_id, date);
CREATE INDEX idx_sheet_entries_paid ON sheet_entries (paid_from_id);
CREATE INDEX idx_sheet_entries_should ON sheet_entries (should_pay_id);
