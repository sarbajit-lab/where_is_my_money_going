# WIMMG 1.0.0 - Where Is My Money Going?

*By Sarbajit Pal, House of Lad Pal (HLP). Released 2026-11-21.*

WIMMG turns the weekly "open Excel, type, check limits" routine into a fast, fully offline app that you can
keep on your own computer.

## Highlights
- **Enter a week in one go**: spreadsheet-like Sheet, no per-entry "+ Add", suggestions from your own history.
- **Paid from / Should pay** on every entry, with netted settle-up.
- **Limits you can see while typing**: Limit Left per row and a live Limits panel.
- **Your Excel format in and out**: import your existing dumps, export the same layout back.
- **Users and roles**, an Admin created on first start, and settings for session timeout and more.
- **100% offline**: nothing is sent anywhere; the database stays on your computer.

## Upgrading / first run
1. Run `./start.sh` (or `python3 run.py`). Python 3.10+; nothing else to install.
2. Copy the one-time Admin password shown in the terminal (also in `data/FIRST_LOGIN.txt`).
3. Log in, choose a new password, scan the authenticator QR code.
4. Go to **Import & export** and load your Properties first, then your Transactions.

## Notes
- Limit Left follows entry order within a month, so it matches your Excel sheet.
- The export has two extra trailing columns (Type, Note) so income and notes survive a round trip.
- Full list of changes: see CHANGELOG.md.
