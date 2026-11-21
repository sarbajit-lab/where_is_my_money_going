# Changelog

All notable changes to WIMMG are listed here, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com) and versions follow [Semantic Versioning](https://semver.org).
The app shows this file under **Settings > About & changelog**.

**How to maintain it:** while you work, add a line under `## [Unreleased]` in the right group (Added / Changed /
Fixed / Removed / Security). To release: rename `Unreleased` to the new version and date, add a fresh empty
`Unreleased` above it, change the number in `VERSION`, and copy the highlights into `RELEASE_NOTES.md`.

## [Unreleased]

## [1.0.0] - 2026-11-21

First release of WIMMG, a new variant by Sarbajit Pal (House of Lad Pal, HLP), built on an earlier open-source
(MIT) offline account-book app.

### Added
- **Sheet**: a spreadsheet-style entry screen. Type a whole week of entries without any "+ Add" click; Tab/Enter
  move between cells, a new row is always ready, and rows save themselves when you leave them (or press Save all,
  Ctrl+Enter / Ctrl+S).
- **Auto-suggest from your history** for Item, Paid from and Should pay. Choosing an item fills its category,
  default Should-pay account and the usual Paid-from.
- **Paid from / Should pay** on every entry, with a **settle-up** view (who owes whom, netted) in Insights.
- **Live limits**: every item has a monthly limit; "Limit left" shows on each row and in a Limits panel, updating
  as you type, including rows not yet saved. Calculated in entry order, exactly like the original Excel sheet.
- **Items & limits** screen (the old "Properties" tab): item, category, monthly limit, default account.
- **Import / export in your Excel format**: Transactions (Date, Item, Category, Amount, Limit Left, Paid From,
  Should Pay) and Properties (Master Items, Category, Limit, Spent, Limit Left, Account). Reads .xlsx, CSV, TSV or
  pasted text; shows a preview; skips duplicates, so re-importing a dump is safe. Exports .xlsx or CSV.
- **Paste rows copied from Excel** straight into the Sheet.
- **Insights**: spending by category and item, month by month, income vs expense, with no internet needed.
- **Users and roles (RBAC)**: built-in Admin, Editor and Viewer roles plus custom roles with fine-grained
  permissions; user management; Activity log.
- **First-run Admin**: a default `admin` user with a random one-time password (printed in the terminal and saved in
  `data/FIRST_LOGIN.txt`); you must change it and set up the authenticator at first login.
- **Configurable security** (Settings > App settings): idle timeout, maximum session length, lockout, minimum
  password length, whether 2-step login is required, auto-backup, autosave and currency symbol.
- WIMMG name, logo and House of Lad Pal (HLP) branding; this changelog and release notes in the app.

### Changed
- Login is by username + password + authenticator code (no email address).
- Default database file is `data/wimmg.db`; backups are named `wimmg_backup_*`.
- The earlier account-book screens (Dashboard, Transactions, Accounts, Investments, Loans, Budget, Reports) are kept
  under "Classic account book".

### Removed
- Email, password-reset links and registration: the app never needs the internet. Use the Admin screen or
  `python3 run.py --reset-password --user NAME` instead.

### Security
- Content-Security-Policy allows only the app itself; no CDNs, fonts or analytics.
- Spreadsheet imports reject XML entities; exports neutralise formula injection (cells starting with = + - @).
