"""The weekly sheet: items & limits, running "limit left", paid-from / should-pay settlement, insights."""
import unittest

from tests.helpers import AppCase


class SheetTest(AppCase):
    def setUp(self):
        super().setUp()
        self.item("Grocery", "Utility", 6500, "Bank U")
        self.item("Petrol", "Utility", 6000, "Bank U")
        self.item("Eating out", "Fun", None, "Bank F")

    def test_limit_left_runs_in_entry_order(self):
        # entered out of date order on purpose: the running figure follows the order of entry, like the spreadsheet
        a = self.add("2026-11-02", "Grocery", 1170, "Bank U", "Bank U")
        b = self.add("2026-11-01", "Grocery", 97, "Card X", "Bank U")
        c = self.add("2026-11-05", "Grocery", 324, "Bank U")
        self.assertEqual([a["limit_left"], b["limit_left"], c["limit_left"]], [5330, 5233, 4909])
        # a different month starts again from the full limit
        d = self.add("2026-12-01", "Grocery", 100, "Bank U")
        self.assertEqual(d["limit_left"], 6400)
        # no limit -> no figure; income does not use up the limit
        self.assertIsNone(self.add("2026-11-03", "Eating out", 500, "Card X", "Bank F")["limit_left"])
        inc = self.add("2026-11-04", "Grocery", 50, "Bank U", "Bank U", kind="income")
        self.assertIsNone(inc["limit_left"])
        rows = self.c.get("/api/sheet/entries?month=2026-11").get_json()["rows"]
        self.assertEqual([r["limit_left"] for r in rows if r["item"] == "Grocery" and r["kind"] == "expense"], [5330, 5233, 4909])

    def test_editing_and_deleting_recomputes(self):
        a = self.add("2026-11-01", "Petrol", 2500, "Bank U")
        b = self.add("2026-11-02", "Petrol", 350, "Bank U")
        self.assertEqual(b["limit_left"], 3150)
        self.assertEqual(self.c.put(f"/api/sheet/entries/{a['id']}", json={"date": "2026-11-01", "item": "Petrol", "amount": 1000,
                                                                          "paid_from": "Bank U"}).status_code, 200)
        self.assertEqual(self.c.get(f"/api/sheet/entries?month=2026-11").get_json()["rows"][1]["limit_left"], 4650)
        self.assertEqual(self.c.delete(f"/api/sheet/entries/{a['id']}").status_code, 200)
        self.assertEqual(self.c.get("/api/sheet/entries?month=2026-11").get_json()["rows"][0]["limit_left"], 5650)

    def test_item_spent_and_left_for_a_month(self):
        self.add("2026-11-01", "Grocery", 2275, "Bank U")
        self.add("2026-10-01", "Grocery", 999, "Bank U")
        items = {i["name"]: i for i in self.c.get("/api/sheet/items?month=2026-11").get_json()["items"]}
        self.assertEqual((items["Grocery"]["spent"], items["Grocery"]["left"]), (2275, 4225))
        self.assertIsNone(items["Eating out"]["left"])
        self.assertEqual(items["Petrol"]["spent"], 0)

    def test_should_pay_defaults_from_the_item_and_new_things_are_created(self):
        e = self.add("2026-11-01", "Grocery", 10, "Card X")
        self.assertEqual((e["paid_from"], e["should_pay"]), ("Card X", "Bank U"))
        e = self.add("2026-11-01", "Brand new thing", 10, "Card X", "Bank Z", category="Misc")
        self.assertEqual((e["category"], e["should_pay"]), ("Misc", "Bank Z"))
        names = [a["name"] for a in self.c.get("/api/sheet/accounts").get_json()]
        self.assertIn("Bank Z", names)

    def test_validation(self):
        bad = lambda **kw: self.c.post("/api/sheet/entries", json={"date": "2026-11-01", "item": "Grocery", "amount": 5, **kw})
        self.assertEqual(bad(date="31/11/2026").status_code, 400)
        self.assertEqual(bad(amount=0).status_code, 400)
        self.assertEqual(bad(amount="abc").status_code, 400)
        self.assertEqual(bad(item="  ").status_code, 400)
        self.assertEqual(bad(kind="gift").status_code, 400)
        self.assertEqual(bad(amount="1e5").status_code, 400)

    def test_bulk_save_keeps_good_rows_and_reports_bad_ones(self):
        r = self.c.post("/api/sheet/entries/bulk", json={"rows": [
            {"client_id": "a", "date": "2026-11-01", "item": "Grocery", "amount": 10},
            {"client_id": "b", "date": "nope", "item": "Grocery", "amount": 10},
            {"client_id": "c", "date": "2026-11-02", "item": "Petrol", "amount": 20}]}).get_json()
        self.assertEqual([s["client_id"] for s in r["saved"]], ["a", "c"])
        self.assertEqual(r["errors"][0]["client_id"], "b")
        self.assertEqual(self.c.get("/api/sheet/entries").get_json()["total"], 2)

    def test_items_with_entries_cannot_be_deleted(self):
        self.add("2026-11-01", "Grocery", 10)
        gid = next(i["id"] for i in self.c.get("/api/sheet/items").get_json()["items"] if i["name"] == "Grocery")
        self.assertEqual(self.c.delete(f"/api/sheet/items/{gid}").status_code, 400)
        eid = next(i["id"] for i in self.c.get("/api/sheet/items").get_json()["items"] if i["name"] == "Eating out")
        self.assertEqual(self.c.delete(f"/api/sheet/items/{eid}").status_code, 200)

    def test_settlement_nets_who_owes_whom(self):
        # Card X paid 300 that Bank U should pay; Bank U paid 100 that Card X should pay -> Bank U owes Card X 200
        self.add("2026-11-01", "Grocery", 300, "Card X", "Bank U")
        self.add("2026-11-02", "Grocery", 100, "Bank U", "Card X")
        self.add("2026-11-03", "Grocery", 999, "Bank U", "Bank U")           # same account: nothing to settle
        ins = self.c.get("/api/sheet/insights?month=2026-11").get_json()
        self.assertEqual(ins["settlement"]["transfers"], [{"from": "Bank U", "to": "Card X", "amount": 200}])
        self.assertEqual({a["name"]: a["net"] for a in ins["settlement"]["accounts"]}, {"Card X": 200, "Bank U": -200})
        # income received in the wrong account flips the direction
        self.add("2026-11-04", "Grocery", 50, "Card X", "Bank U", kind="income")
        ins = self.c.get("/api/sheet/insights?month=2026-11").get_json()
        self.assertEqual(ins["settlement"]["transfers"][0]["amount"], 150)

    def test_insights_totals_and_limits(self):
        self.add("2026-10-05", "Grocery", 7000, "Bank U")                    # over its 6,500 limit
        self.add("2026-11-05", "Grocery", 1000, "Bank U")
        self.add("2026-11-06", "Eating out", 500, "Card X")
        self.add("2026-11-07", "Eating out", 200, "Card X", kind="income")
        ins = self.c.get("/api/sheet/insights?month=2026-11").get_json()
        self.assertEqual(ins["totals"], {"entries": 3, "expense": 1500, "income": 200, "net": -1300})
        self.assertEqual([c["name"] for c in ins["by_category"]], ["Utility", "Fun"])
        allins = self.c.get("/api/sheet/insights").get_json()
        self.assertEqual(allins["overspent"][0]["name"], "Grocery")
        self.assertEqual(allins["overspent"][0]["over"], 500)
        self.assertEqual([m["month"] for m in allins["monthly"]], ["2026-10", "2026-11"])

    def test_search_filters_and_paging(self):
        self.add("2026-11-01", "Grocery", 10, note="milk run")
        self.add("2026-11-02", "Petrol", 20)
        self.assertEqual(self.c.get("/api/sheet/entries?q=milk").get_json()["total"], 1)
        self.assertEqual(self.c.get("/api/sheet/entries?q=%25").get_json()["total"], 0)        # % is not a wildcard
        self.assertEqual(self.c.get("/api/sheet/entries?category=Utility&limit=1").get_json()["total"], 2)
        self.assertEqual(len(self.c.get("/api/sheet/entries?limit=1").get_json()["rows"]), 1)

    def test_bootstrap_has_hints_for_suggestions(self):
        self.add("2026-11-01", "Grocery", 123, "Card X")
        boot = self.c.get("/api/sheet/bootstrap?month=2026-11").get_json()
        gid = next(i["id"] for i in boot["items"] if i["name"] == "Grocery")
        self.assertEqual(boot["hints"][str(gid)]["last_amount"], 123)
        self.assertEqual(boot["spent"][str(gid)], 123)
        self.assertIn("Utility", boot["categories"])


if __name__ == "__main__":
    unittest.main()
