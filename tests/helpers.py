"""Shared test setup for the sheet, import/export and RBAC tests."""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    import flask  # noqa: F401
except ImportError:
    sys.path.insert(1, os.path.join(ROOT, "vendor", "flask-bundle.zip"))

from backend import create_app  # noqa: E402
from backend.services import totp  # noqa: E402
from tests.test_api import PASSWORD, TEST_CONFIG, login  # noqa: E402


class AppCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app({**TEST_CONFIG, "DB_PATH": os.path.join(self.tmp.name, "t.db"),
                               "BACKUP_DIR": os.path.join(self.tmp.name, "b")})
        self.c = self.client()
        login(self.c)

    def tearDown(self):
        self.tmp.cleanup()

    def client(self):
        c = self.app.test_client()
        c.environ_base["HTTP_X_REQUESTED_WITH"] = "WIMMG"
        return c

    def add(self, date, item, amount, paid="", should="", kind="expense", category="", note=""):
        r = self.c.post("/api/sheet/entries", json={"date": date, "item": item, "amount": amount, "paid_from": paid,
                                                    "should_pay": should, "kind": kind, "category": category, "note": note})
        self.assertEqual(r.status_code, 201, r.get_json())
        return r.get_json()

    def item(self, name, category, limit, account):
        r = self.c.post("/api/sheet/items", json={"name": name, "category": category, "limit": limit, "account": account})
        self.assertEqual(r.status_code, 201, r.get_json())
        return r.get_json()

    def as_user(self, username, role_name, password="Temp-pass-12345"):
        roles = {r["name"]: r["id"] for r in self.c.get("/api/roles").get_json()["roles"]}
        r = self.c.post("/api/users", json={"username": username, "role_id": roles[role_name], "password": password})
        self.assertEqual(r.status_code, 201, r.get_json())
        c = self.client()
        s = c.post("/api/auth/login", json={"username": username, "password": password}).get_json()
        self.assertEqual(s["state"], "change_pw")
        new = "Chosen-pass-98765"
        s = c.post("/api/auth/first-password", json={"current": password, "new": new, "confirm": new}).get_json()
        self.assertEqual(s["state"], "mfa_setup")
        secret = c.post("/api/auth/mfa/begin").get_json()["secret"]
        self.assertEqual(c.post("/api/auth/mfa/confirm", json={"code": totp.code_at(secret, totp.current_step())}).get_json()["state"], "ok")
        return c
