"""Users, roles and what each role may do."""
import unittest

from tests.helpers import AppCase


class RbacTest(AppCase):
    def setUp(self):
        super().setUp()
        self.item("Grocery", "Utility", 1000, "Bank U")

    def test_viewer_can_look_but_not_change(self):
        v = self.as_user("vera", "Viewer")
        self.assertEqual(v.get("/api/sheet/entries").status_code, 200)
        self.assertEqual(v.get("/api/sheet/insights").status_code, 200)
        self.assertEqual(v.post("/api/sheet/entries", json={"date": "2026-11-01", "item": "Grocery", "amount": 5}).status_code, 403)
        self.assertEqual(v.post("/api/sheet/entries/bulk", json={"rows": []}).status_code, 403)
        self.assertEqual(v.post("/api/sheet/items", json={"name": "X"}).status_code, 403)
        self.assertEqual(v.get("/api/sheet/export.xlsx").status_code, 403)
        self.assertEqual(v.post("/api/sheet/import", data={"text": "a"}).status_code, 403)
        self.assertEqual(v.get("/api/users").status_code, 403)
        self.assertEqual(v.put("/api/app-settings", json={"idle_minutes": 99}).status_code, 403)
        self.assertEqual(v.post("/api/system/backups").status_code, 403)
        self.assertEqual(v.post("/api/entries", json={}).status_code, 403)          # classic modules follow the same rules
        self.assertEqual(v.get("/api/app-settings").status_code, 200)               # reading display settings is fine

    def test_editor_can_work_but_not_administer(self):
        e = self.as_user("eddie", "Editor")
        r = e.post("/api/sheet/entries", json={"date": "2026-11-01", "item": "Grocery", "amount": 5})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(e.post("/api/sheet/items", json={"name": "Milk"}).status_code, 201)
        self.assertEqual(e.get("/api/sheet/export.xlsx").status_code, 200)
        self.assertEqual(e.get("/api/users").status_code, 403)
        self.assertEqual(e.post("/api/system/backups").status_code, 403)
        self.assertEqual(e.get("/api/audit").status_code, 403)

    def test_custom_role(self):
        r = self.c.post("/api/roles", json={"name": "Spouse", "description": "adds entries only", "permissions": ["data.write"]})
        self.assertEqual(r.status_code, 201, r.get_json())
        self.assertIn("view", r.get_json()["permissions"])                         # anything else needs "view"
        u = self.as_user("sam", "Spouse")
        self.assertEqual(u.post("/api/sheet/entries", json={"date": "2026-11-01", "item": "Grocery", "amount": 5}).status_code, 201)
        self.assertEqual(u.post("/api/sheet/items", json={"name": "Milk"}).status_code, 403)
        rid = r.get_json()["id"]
        self.assertEqual(self.c.delete(f"/api/roles/{rid}").status_code, 400)       # still has a user
        self.assertEqual(self.c.put(f"/api/roles/{rid}", json={"permissions": ["view", "masters.write"]}).status_code, 200)
        self.assertEqual(u.post("/api/sheet/items", json={"name": "Milk"}).status_code, 201)   # the change applies at once
        self.assertEqual(self.c.post("/api/roles", json={"name": "X", "permissions": ["fly"]}).status_code, 400)

    def test_admin_role_is_protected(self):
        roles = {r["name"]: r for r in self.c.get("/api/roles").get_json()["roles"]}
        self.assertEqual(self.c.put(f"/api/roles/{roles['Admin']['id']}", json={"permissions": ["view"]}).status_code, 400)
        self.assertEqual(self.c.delete(f"/api/roles/{roles['Admin']['id']}").status_code, 400)
        self.assertEqual(self.c.delete(f"/api/roles/{roles['Viewer']['id']}").status_code, 400)       # built-in

    def test_last_admin_cannot_be_removed(self):
        me = next(u for u in self.c.get("/api/users").get_json() if u["username"] == "admin")
        roles = {r["name"]: r["id"] for r in self.c.get("/api/roles").get_json()["roles"]}
        self.assertEqual(self.c.delete(f"/api/users/{me['id']}").status_code, 400)
        self.assertEqual(self.c.put(f"/api/users/{me['id']}", json={"role_id": roles["Viewer"]}).status_code, 400)
        self.assertEqual(self.c.put(f"/api/users/{me['id']}", json={"role_id": roles["Admin"], "active": False}).status_code, 400)

    def test_second_admin_allows_changes(self):
        self.as_user("ann", "Admin")
        users = {u["username"]: u for u in self.c.get("/api/users").get_json()}
        roles = {r["name"]: r["id"] for r in self.c.get("/api/roles").get_json()["roles"]}
        self.assertEqual(self.c.put(f"/api/users/{users['ann']['id']}", json={"role_id": roles["Viewer"]}).status_code, 200)

    def test_disabled_user_is_logged_out_and_cannot_log_in(self):
        u = self.as_user("dave", "Editor")
        uid = next(x["id"] for x in self.c.get("/api/users").get_json() if x["username"] == "dave")
        roles = {r["name"]: r["id"] for r in self.c.get("/api/roles").get_json()["roles"]}
        self.assertEqual(self.c.put(f"/api/users/{uid}", json={"role_id": roles["Editor"], "active": False}).status_code, 200)
        self.assertEqual(u.get("/api/sheet/entries").status_code, 401)
        self.assertEqual(self.client().post("/api/auth/login", json={"username": "dave", "password": "Chosen-pass-98765"}).status_code, 401)

    def test_reset_password_and_authenticator(self):
        self.as_user("erin", "Editor")
        uid = next(x["id"] for x in self.c.get("/api/users").get_json() if x["username"] == "erin")
        r = self.c.post(f"/api/users/{uid}/reset-password", json={}).get_json()
        pw = r["temporary_password"]
        c = self.client()
        self.assertEqual(c.post("/api/auth/login", json={"username": "erin", "password": pw}).get_json()["state"], "change_pw")
        self.assertEqual(self.c.post(f"/api/users/{uid}/reset-mfa").status_code, 200)
        user = next(x for x in self.c.get("/api/users").get_json() if x["username"] == "erin")
        self.assertFalse(user["mfa_enabled"])

    def test_user_validation_and_duplicates(self):
        roles = {r["name"]: r["id"] for r in self.c.get("/api/roles").get_json()["roles"]}
        post = lambda **kw: self.c.post("/api/users", json={"role_id": roles["Viewer"], **kw})
        self.assertEqual(post(username="a b").status_code, 400)
        self.assertEqual(post(username="ok-user", password="weak").status_code, 400)
        self.assertEqual(post(username="ok-user").status_code, 201)
        self.assertEqual(post(username="OK-USER").status_code, 400)
        self.assertEqual(self.c.post("/api/users", json={"username": "zed", "role_id": 999}).status_code, 400)

    def test_secrets_never_reach_the_browser(self):
        self.as_user("fay", "Viewer")
        text = self.c.get("/api/users").get_data(as_text=True) + self.c.get("/api/auth/status").get_data(as_text=True)
        self.assertNotIn("password_hash", text)
        self.assertNotIn("totp_secret", text)
        self.assertNotIn("scrypt", text)

    def test_activity_log(self):
        self.as_user("gus", "Viewer")
        actions = [a["action"] for a in self.c.get("/api/audit").get_json()]
        self.assertIn("user.create", actions)
        self.assertIn("login", actions)

    def test_settings_are_validated(self):
        self.assertEqual(self.c.put("/api/app-settings", json={"idle_minutes": 1}).status_code, 400)
        self.assertEqual(self.c.put("/api/app-settings", json={"idle_minutes": "x"}).status_code, 400)
        self.assertEqual(self.c.put("/api/app-settings", json={"nope": 1}).status_code, 400)
        self.assertEqual(self.c.put("/api/app-settings", json={"idle_minutes": 45, "currency_symbol": "$"}).status_code, 200)
        got = self.c.get("/api/app-settings").get_json()
        self.assertEqual((got["idle_minutes"]["value"], got["currency_symbol"]["value"]), (45, "$"))


if __name__ == "__main__":
    unittest.main()
