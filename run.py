#!/usr/bin/env python3
"""Start WIMMG (Where Is My Money Going?), by Sarbajit Pal - House of Lad Pal (HLP).

    python3 run.py            start on http://127.0.0.1:5000
    python3 run.py --open     start and open the browser
    python3 run.py --port 5050
    python3 run.py --reset-password [--user NAME]   forgot a password (default user: admin)
    python3 run.py --reset-mfa [--user NAME]        lost your phone: set up the authenticator again at next login

Flask is bundled in vendor/flask-bundle.zip, so no pip install or internet is needed.
"""
import argparse
import getpass
import os
import sys
import threading
import webbrowser

sys.dont_write_bytecode = True     # no __pycache__ folders: nothing stale is left behind after updates

if sys.version_info < (3, 10):
    sys.exit(f"WIMMG needs Python 3.10 or newer; this is Python {sys.version.split()[0]}. "
             "Install a newer Python from https://www.python.org/downloads/")

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

try:
    import flask  # noqa: F401  (use an installed Flask if there is one)
except ImportError:
    sys.path.insert(1, os.path.join(ROOT, "vendor", "flask-bundle.zip"))

from backend import config, create_app  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="WIMMG - Where Is My Money Going?")
    parser.add_argument("--host", default=config.HOST)
    parser.add_argument("--port", type=int, default=config.PORT)
    parser.add_argument("--allow-network", action="store_true",
                        help="allow a --host other than this computer (other devices could then reach the login page)")
    parser.add_argument("--open", action="store_true", help="open the app in the browser")
    parser.add_argument("--reset-password", action="store_true", help="set a new login password for a user")
    parser.add_argument("--reset-mfa", action="store_true", help="remove the authenticator; set it up again at next login")
    parser.add_argument("--user", default="admin", help="the user for --reset-password / --reset-mfa (default: admin)")
    parser.add_argument("--demo", action="store_true",
                        help="try the app with sample data (separate demo-data/ folder, your real data is untouched)")
    args = parser.parse_args()

    if args.demo:
        demo_dir = os.path.join(ROOT, "demo-data")
        config.DB_PATH = os.path.join(demo_dir, "wimmg.db")
        config.BACKUP_DIR = os.path.join(demo_dir, "backups")

    if args.host not in ("127.0.0.1", "localhost", "::1") and not args.allow_network:
        sys.exit(f"Refusing to listen on {args.host}: that would let other devices on your network reach the app.\n"
                 "It's meant to run on this computer only (127.0.0.1). If you really need it, add --allow-network.")

    if args.reset_password or args.reset_mfa:
        return reset_from_terminal(args)

    app = create_app({"DB_PATH": config.DB_PATH, "BACKUP_DIR": config.BACKUP_DIR,
                      "ALLOWED_HOSTS": [args.host] if args.allow_network else []})
    if args.demo:
        from backend.demo import seed_demo
        from backend.demo import seed_demo_sheet
        seed_demo_sheet(app)
        if seed_demo(app):
            print("  Demo: sample data created (it stays in demo-data/). Log in with the first-login details shown above.")
    url = f"http://{args.host}:{args.port}"
    print(f"\n  WIMMG running at {url}{'  [DEMO]' if args.demo else ''}")
    print(f"  Data: {config.DB_PATH}")
    print("  Press Ctrl+C to stop.\n")
    if args.open:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    serve(app, args.host, args.port)


def serve(app, host, port):
    """Use the Waitress production server if it is installed; otherwise Werkzeug's threaded server, quietly.

    Either is fine here: the app listens on 127.0.0.1 only and has a single user.
    """
    try:
        from waitress import serve as waitress_serve
    except ImportError:
        waitress_serve = None
    if waitress_serve:
        print("  Server: Waitress")
        waitress_serve(app, host=host, port=port, threads=8, ident="WIMMG")
        return
    import logging
    from werkzeug.serving import make_server
    logging.getLogger("werkzeug").setLevel(logging.WARNING)   # no line per request
    server = make_server(host, port, app, threaded=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")
    finally:
        server.server_close()


def reset_from_terminal(args):
    """Recovery that needs access to this computer instead of email."""
    from backend import db
    from backend.errors import ApiError
    from backend.services import auth

    create_app({"DB_PATH": config.DB_PATH, "BACKUP_DIR": config.BACKUP_DIR})   # makes sure the database is up to date
    conn = db.connect(config.DB_PATH)
    try:
        if not conn.execute("SELECT COUNT(*) FROM users WHERE username = ?", (args.user,)).fetchone()[0]:
            print(f"There is no user called '{args.user}'.")
            return 1
        if args.reset_password:
            while True:
                pw = getpass.getpass("New password: ")
                if pw != getpass.getpass("Repeat new password: "):
                    print("  The passwords don't match. Try again.")
                    continue
                try:
                    auth.cli_reset_password(conn, args.user, pw)
                    break
                except ApiError as e:
                    print(f"  {e.message}")
            print(f"Password changed for {args.user}. Existing logins were signed out.")
        if args.reset_mfa:
            auth.cli_reset_mfa(conn, args.user)
            print(f"Authenticator removed for {args.user}. At the next login a new QR code is shown.")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
