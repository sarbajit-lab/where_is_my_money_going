# Security

## What this app is designed for

WIMMG is a **personal app that runs on your own computer** (several people can have their own logins, with roles). The server listens on
`127.0.0.1` only, so other devices on your network or the internet can't reach it. It also refuses any request
that isn't addressed to `127.0.0.1` / `localhost`, so a web page you visit can't reach it through "DNS rebinding".

## What protects your data

- Login with a password (stored as a salted scrypt hash) **and** a 6-digit code from an authenticator app
- Repeated wrong passwords or codes lock the user for a while; idle sessions end after a set time (both adjustable)
- There is no email and no password-reset link: an Admin resets a user from the app, or you run `python3 run.py --reset-password --user NAME`
- Session timeout, lockout, password length and 2-step login are configurable by an Admin (Settings > App settings)
- Roles control exactly what each user can see and do (Settings > Roles); every change is written to the Activity log
- Session cookies are HttpOnly and SameSite=Strict; state-changing API calls require a custom header (CSRF protection)
- The page may only load and send data to the app itself (Content-Security-Policy); no CDNs, fonts or analytics
- `data/` and `backups/` are readable only by your user account (folders 700, files 600)
- The browser is told not to remember what you type into the app's fields

## What it does not protect against

- **The database file is not encrypted.** `data/wimmg.db` is a normal file. Anyone who can log in to your
  computer account can copy it. Use a password on your
  computer account and disk encryption if possible.
- Someone with access to your computer can run `python3 run.py --reset-password` / `--reset-mfa`.
  This is deliberate, so you can't lock yourself out of your own data.
- Exposing the app beyond localhost (`--host 0.0.0.0`, port forwarding, a reverse proxy) is **not supported**.

## Reporting a problem

Please open a GitHub issue **without** sensitive details, or contact the maintainer privately through GitHub,
and describe the steps to reproduce.
