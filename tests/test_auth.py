"""Login, first-time admin, authenticator (MFA), lockout, session limits and password tests."""
import os
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    import flask  # noqa: F401
except ImportError:
    sys.path.insert(1, os.path.join(ROOT, "vendor", "flask-bundle.zip"))

from backend import create_app  # noqa: E402
from backend.services import totp  # noqa: E402

PASSWORD = "Correct-horse-42"
NEW_PASSWORD = "Another-horse-77"


def code(secret, offset=0):
    return totp.code_at(secret, totp.current_step() + offset)


class AuthTest(unittest.TestCase):
    def setUp(self, must_change=False):
        self.tmp = tempfile.TemporaryDirectory()
        self.make_app(must_change)
        self.c = self.new_client()

    def make_app(self, must_change=False):
        self.app = create_app({
            "TESTING": True, "DB_PATH": os.path.join(self.tmp.name, "t.db"), "BACKUP_DIR": os.path.join(self.tmp.name, "b"),
            "SECRET_KEY": b"test-secret-key-test-secret-key!", "INITIAL_ADMIN_PASSWORD": PASSWORD,
            "FIRST_LOGIN_MUST_CHANGE": must_change})

    def tearDown(self):
        self.tmp.cleanup()

    def new_client(self):
        c = self.app.test_client()
        c.environ_base["HTTP_X_REQUESTED_WITH"] = "WIMMG"
        return c

    def state(self, c=None):
        return (c or self.c).get("/api/auth/status").get_json()["state"]

    def setup_mfa(self, c=None):
        c = c or self.c
        r = c.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
        self.assertEqual(r.status_code, 200, r.get_json())
        secret = c.post("/api/auth/mfa/begin").get_json()["secret"]
        self.assertEqual(c.post("/api/auth/mfa/confirm", json={"code": code(secret)}).get_json()["state"], "ok")
        return secret

    # ------------------------------------------------------------------
    def test_default_admin_and_data_protected(self):
        self.assertEqual(self.state(), "logged_out")
        self.assertEqual(self.c.get("/api/sheet/entries").status_code, 401)
        r = self.c.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
        self.assertEqual(r.get_json()["state"], "mfa_setup")
        self.assertEqual(self.c.get("/api/sheet/entries").status_code, 401)        # a password alone shows nothing
        begin = self.c.post("/api/auth/mfa/begin").get_json()
        self.assertTrue(begin["uri"].startswith("otpauth://totp/WIMMG"))
        self.assertEqual(self.c.post("/api/auth/mfa/confirm", json={"code": "000000"}).status_code, 400)
        self.assertEqual(self.c.post("/api/auth/mfa/confirm", json={"code": code(begin["secret"])}).get_json()["state"], "ok")
        self.assertEqual(self.c.get("/api/sheet/entries").status_code, 200)
        me = self.c.get("/api/auth/status").get_json()["user"]
        self.assertEqual((me["username"], me["role"]), ("admin", "Admin"))
        self.assertIn("users.manage", me["permissions"])

    def test_first_login_forces_a_new_password(self):
        self.tearDown(); self.setUp(must_change=True)
        r = self.c.post("/api/auth/login", json={"username": "ADMIN", "password": PASSWORD})   # username is case-insensitive
        self.assertEqual(r.get_json()["state"], "change_pw")
        self.assertEqual(self.c.get("/api/sheet/entries").status_code, 401)
        self.assertEqual(self.c.post("/api/auth/mfa/begin").status_code, 401)           # no shortcut around the change
        bad = self.c.post("/api/auth/first-password", json={"current": PASSWORD, "new": "short", "confirm": "short"})
        self.assertEqual(bad.status_code, 400)
        same = self.c.post("/api/auth/first-password", json={"current": PASSWORD, "new": PASSWORD, "confirm": PASSWORD})
        self.assertEqual(same.status_code, 400)
        ok = self.c.post("/api/auth/first-password", json={"current": PASSWORD, "new": NEW_PASSWORD, "confirm": NEW_PASSWORD})
        self.assertEqual(ok.get_json()["state"], "mfa_setup")
        c2 = self.new_client()
        self.assertEqual(c2.post("/api/auth/login", json={"username": "admin", "password": PASSWORD}).status_code, 401)
        self.assertEqual(c2.post("/api/auth/login", json={"username": "admin", "password": NEW_PASSWORD}).get_json()["state"], "mfa_setup")

    def test_first_login_file_written_and_removed(self):
        self.tearDown(); self.setUp(must_change=True)
        path = os.path.join(self.tmp.name, "FIRST_LOGIN.txt")
        self.assertTrue(os.path.exists(path))
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        self.assertIn(PASSWORD, open(path).read())
        self.c.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
        self.c.post("/api/auth/first-password", json={"current": PASSWORD, "new": NEW_PASSWORD, "confirm": NEW_PASSWORD})
        self.assertFalse(os.path.exists(path))

    def test_login_needs_password_and_code(self):
        secret = self.setup_mfa()
        c = self.new_client()
        self.assertEqual(c.post("/api/auth/login", json={"username": "admin", "password": "wrong-password-1"}).status_code, 401)
        self.assertEqual(c.post("/api/auth/login", json={"username": "nobody", "password": PASSWORD}).status_code, 401)
        r = c.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
        self.assertEqual(r.get_json()["state"], "mfa")
        self.assertEqual(c.get("/api/sheet/entries").status_code, 401)
        self.assertEqual(c.post("/api/auth/login/code", json={"code": "123456"}).status_code, 401)
        good = code(secret, 1)
        self.assertEqual(c.post("/api/auth/login/code", json={"code": good}).get_json()["state"], "ok")
        c2 = self.new_client()
        c2.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
        self.assertEqual(c2.post("/api/auth/login/code", json={"code": good}).status_code, 401)   # a code is single-use

    def test_lockout_uses_configured_limit(self):
        secret = self.setup_mfa()
        self.c.put("/api/app-settings", json={"max_failures": 3})
        c = self.new_client()
        for _ in range(2):
            self.assertEqual(c.post("/api/auth/login", json={"username": "admin", "password": "bad-password-1"}).status_code, 401)
        self.assertEqual(c.post("/api/auth/login", json={"username": "admin", "password": "bad-password-1"}).status_code, 429)
        r = c.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
        self.assertEqual(r.status_code, 429)

    def test_mfa_can_be_made_optional(self):
        self.setup_mfa()
        self.assertEqual(self.c.put("/api/app-settings", json={"mfa_required": False}).status_code, 200)
        c = self.new_client()
        self.assertEqual(c.post("/api/auth/login", json={"username": "admin", "password": PASSWORD}).get_json()["state"], "ok")

    def test_logout(self):
        self.setup_mfa()
        self.assertEqual(self.c.post("/api/auth/logout").status_code, 200)
        self.assertEqual(self.c.get("/api/sheet/entries").status_code, 401)
        self.assertEqual(self.state(), "logged_out")

    def test_csrf_header_required(self):
        self.setup_mfa()
        raw = self.app.test_client()
        with self.c.session_transaction() as s:
            cookie_session = dict(s)
        with raw.session_transaction() as s:
            s.update(cookie_session)
        self.assertEqual(raw.post("/api/system/backups").status_code, 400)

    def test_only_answers_on_this_computer(self):
        for host in ("evil.example", "evil.example:5000", "127.0.0.1.evil.example"):
            self.assertEqual(self.c.get("/api/auth/status", headers={"Host": host}).status_code, 403, host)
            self.assertEqual(self.c.get("/", headers={"Host": host}).status_code, 403, host)
        for host in ("127.0.0.1:5000", "localhost:9999", "[::1]:5000", "localhost"):
            self.assertEqual(self.c.get("/api/auth/status", headers={"Host": host}).status_code, 200, host)

    def test_data_files_private(self):
        mode = lambda p: os.stat(p).st_mode & 0o777
        self.assertEqual(mode(self.tmp.name + "/t.db"), 0o600)
        self.assertEqual(mode(self.tmp.name + "/b"), 0o700)

    def test_idle_timeout_is_configurable(self):
        self.setup_mfa()
        with self.c.session_transaction() as s:
            s["last"] = int(time.time()) - 31 * 60                    # default is 30 minutes
        self.assertEqual(self.c.get("/api/sheet/entries").status_code, 401)

    def test_idle_timeout_can_be_raised(self):
        self.setup_mfa()
        self.assertEqual(self.c.put("/api/app-settings", json={"idle_minutes": 60}).status_code, 200)
        with self.c.session_transaction() as s:
            s["last"] = int(time.time()) - 31 * 60
        self.assertEqual(self.c.get("/api/sheet/entries").status_code, 200)
        with self.c.session_transaction() as s:
            s["last"] = int(time.time()) - 61 * 60
        self.assertEqual(self.c.get("/api/sheet/entries").status_code, 401)

    def test_longest_login_is_enforced(self):
        self.setup_mfa()
        with self.c.session_transaction() as s:
            s["t0"] = int(time.time()) - 13 * 3600
        self.assertEqual(self.c.get("/api/sheet/entries").status_code, 401)

    def test_change_password_keeps_this_session(self):
        self.setup_mfa()
        other = self.new_client()
        other.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
        self.assertEqual(self.c.post("/api/auth/password", json={"current": "wrong", "new": NEW_PASSWORD, "confirm": NEW_PASSWORD}).status_code, 400)
        self.assertEqual(self.c.post("/api/auth/password", json={"current": PASSWORD, "new": NEW_PASSWORD, "confirm": NEW_PASSWORD}).status_code, 200)
        self.assertEqual(self.c.get("/api/sheet/entries").status_code, 200)
        self.assertEqual(self.new_client().post("/api/auth/login", json={"username": "admin", "password": PASSWORD}).status_code, 401)

    def test_min_password_setting(self):
        self.setup_mfa()
        self.assertEqual(self.c.put("/api/app-settings", json={"min_password": 14}).status_code, 200)
        r = self.c.post("/api/auth/password", json={"current": PASSWORD, "new": "Abcdefgh1234", "confirm": "Abcdefgh1234"})
        self.assertEqual(r.status_code, 400)

    def test_terminal_reset_mfa_and_password(self):
        from backend import db
        from backend.services import auth
        self.setup_mfa()
        conn = db.connect(self.app.config["DB_PATH"])
        auth.cli_reset_mfa(conn, "admin")
        self.assertEqual(auth.cli_reset_password(conn, "admin", NEW_PASSWORD), 1)
        conn.close()
        self.assertEqual(self.c.get("/api/sheet/entries").status_code, 401)
        r = self.new_client().post("/api/auth/login", json={"username": "admin", "password": NEW_PASSWORD})
        self.assertEqual(r.get_json()["state"], "mfa_setup")

    def test_no_email_or_online_features(self):
        self.assertFalse(os.path.exists(os.path.join(ROOT, "backend", "services", "mailer.py")))
        self.assertEqual(self.c.post("/api/auth/forgot", json={"email": "x@y.com"}).status_code, 401)

    def test_totp_known_vector(self):
        secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
        self.assertEqual(totp.code_at(secret, 59 // 30), "287082")


if __name__ == "__main__":
    unittest.main()
