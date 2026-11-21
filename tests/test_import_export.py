"""Excel / CSV import and export in the spreadsheet layout. Uses made-up data only."""
import io
import unittest
import zipfile
from datetime import date

from backend.services import xlsx
from tests.helpers import AppCase

TX = """Date\tItem\tCategory\tAmount\tLimit Left\tPaid From\tShould Pay
Nov 1, 2026\tGrocery\tUtility\t1,170\t5,330\tBank U\tBank U
Nov 2, 2026\tGrocery\tUtility\t97\t5,233\tCard X\tBank U
Nov 3, 2026\tEating out\tFun\t396\t0\tCard X\tBank F
Nov 3, 2026\tEating out\tFun\t396\t0\tCard X\tBank F
"""
PROPS = """Master Items\tCategory\tLimit\tSpent\tLimit Left\tAccount
Grocery\tUtility\t6,500\t0\t6,500\tBank U
Eating out\tFun\t\t0\t\tBank F
Rent\tHome\t0\t0\t0\tBank U
"""


class ImportExportTest(AppCase):
    def post(self, path, **data):
        return self.c.post(path, data=data)

    def test_paste_properties_then_transactions(self):
        self.assertEqual(self.post("/api/sheet/import", text=PROPS).get_json()["properties"], 3)
        prev = self.post("/api/sheet/import/preview", text=TX).get_json()
        self.assertEqual((prev["transactions"], prev["new_transactions"], prev["duplicates"]), (4, 4, 0))
        self.assertEqual(prev["new_accounts"], ["Card X"])
        r = self.post("/api/sheet/import", text=TX).get_json()
        self.assertEqual(r["imported"], 4)
        rows = self.c.get("/api/sheet/entries?month=2026-11").get_json()["rows"]
        self.assertEqual([x["limit_left"] for x in rows[:2]], [5330, 5233])           # same figures as the "Limit Left" column
        self.assertEqual(rows[0]["date"], "2026-11-01")
        items = {i["name"]: i for i in self.c.get("/api/sheet/items").get_json()["items"]}
        self.assertEqual((items["Grocery"]["limit"], items["Eating out"]["limit"], items["Rent"]["limit"]), (6500, None, 0))

    def test_importing_twice_skips_duplicates_but_keeps_genuine_repeats(self):
        self.post("/api/sheet/import", text=TX)
        again = self.post("/api/sheet/import", text=TX).get_json()
        self.assertEqual((again["imported"], again["skipped_duplicates"]), (0, 4))
        self.assertEqual(self.c.get("/api/sheet/entries").get_json()["total"], 4)       # the two identical rows were both kept once
        more = TX + "Nov 3, 2026\tEating out\tFun\t396\t0\tCard X\tBank F\n"
        self.assertEqual(self.post("/api/sheet/import", text=more).get_json()["imported"], 1)
        self.assertEqual(self.post("/api/sheet/import", text=more, skip_duplicates="0").get_json()["imported"], 5)

    def test_bad_rows_are_reported_not_fatal(self):
        text = TX + "not a date\tGrocery\tUtility\t5\t\tA\tB\nNov 5, 2026\t\tUtility\t5\t\tA\tB\nNov 5, 2026\tGrocery\tUtility\tabc\t\tA\tB\n"
        prev = self.post("/api/sheet/import/preview", text=text).get_json()
        self.assertEqual(prev["issue_count"], 3)
        self.assertEqual(self.post("/api/sheet/import", text=text).get_json()["imported"], 4)

    def test_date_and_amount_formats(self):
        text = "Date,Item,Amount\n2026-11-01,A,\"1,000.50\"\n05/11/2026,B,(250)\n6 Nov 2026,C,₹ 75\n12/25/2026,D,10\n"
        self.post("/api/sheet/import", text=text)
        rows = {r["item"]: r for r in self.c.get("/api/sheet/entries").get_json()["rows"]}
        self.assertEqual(rows["A"]["amount"], 1000.5)
        self.assertEqual((rows["B"]["date"], rows["B"]["kind"], rows["B"]["amount"]), ("2026-11-05", "income", 250))   # negative = money back
        self.assertEqual((rows["C"]["date"], rows["C"]["amount"]), ("2026-11-06", 75))
        self.assertEqual(rows["D"]["date"], "2026-12-25")                       # 25 can't be a month: read as month-first

    def test_xlsx_roundtrip_with_both_tabs(self):
        self.post("/api/sheet/import", text=PROPS)
        self.post("/api/sheet/import", text=TX)
        r = self.c.get("/api/sheet/export.xlsx?month=2026-11")
        self.assertEqual(r.status_code, 200)
        self.assertIn("spreadsheetml", r.mimetype)
        book = xlsx.read_xlsx(r.data)
        self.assertEqual(list(book), ["Transactions", "Properties"])
        self.assertEqual(book["Transactions"][0][:7], ["Date", "Item", "Category", "Amount", "Limit Left", "Paid From", "Should Pay"])
        self.assertEqual(book["Transactions"][1][0], date(2026, 11, 1))
        self.assertEqual(book["Transactions"][1][3:5], [1170, 5330])
        # importing the file back changes nothing: every row is recognised as already there
        up = self.c.post("/api/sheet/import", data={"file": (io.BytesIO(r.data), "WIMMG.xlsx")}).get_json()
        self.assertEqual((up["imported"], up["skipped_duplicates"], up["properties"]), (0, 4, 3))

    def test_export_to_empty_database_then_import_elsewhere(self):
        self.post("/api/sheet/import", text=PROPS + "")
        self.post("/api/sheet/import", text=TX)
        data = self.c.get("/api/sheet/export.xlsx").data
        fresh = AppCase()
        fresh.setUp()
        try:
            r = fresh.c.post("/api/sheet/import", data={"file": (io.BytesIO(data), "x.xlsx")}).get_json()
            self.assertEqual((r["imported"], r["properties"]), (4, 3))
            self.assertEqual(fresh.c.get("/api/sheet/entries").get_json()["total"], 4)
        finally:
            fresh.tearDown()

    def test_csv_exports(self):
        self.post("/api/sheet/import", text=PROPS)
        self.post("/api/sheet/import", text=TX)
        tx = self.c.get("/api/sheet/export.csv").data.decode("utf-8-sig").splitlines()
        self.assertEqual(tx[0], "Date,Item,Category,Amount,Limit Left,Paid From,Should Pay,Type,Note")
        self.assertEqual(tx[1], '"Nov 1, 2026",Grocery,Utility,1170,5330,Bank U,Bank U,Expense,')
        props = self.c.get("/api/sheet/export.csv?what=properties&month=2026-11").data.decode("utf-8-sig").splitlines()
        self.assertIn("Grocery,Utility,6500,1267,5233,Bank U", props)
        self.assertEqual(self.c.get("/api/sheet/template.csv").status_code, 200)

    def test_csv_export_neutralises_formulas(self):
        self.add("2026-11-01", "=HYPERLINK(\"x\")", 5, note="+cmd")
        text = self.c.get("/api/sheet/export.csv").data.decode("utf-8-sig")
        self.assertIn("'=HYPERLINK", text)
        self.assertIn("'+cmd", text)

    def test_rejects_unreadable_files(self):
        self.assertEqual(self.c.post("/api/sheet/import", data={"file": (io.BytesIO(b"PK\x03\x04junk"), "a.xlsx")}).status_code, 400)
        self.assertEqual(self.c.post("/api/sheet/import", data={"file": (io.BytesIO(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"), "old.xls")}).status_code, 400)
        self.assertEqual(self.c.post("/api/sheet/import", data={"text": "hello\nworld"}).status_code, 400)
        self.assertEqual(self.c.post("/api/sheet/import", data={}).status_code, 400)

    def test_xlsx_with_entity_bomb_is_refused(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("xl/workbook.xml", '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><workbook/>')
        self.assertEqual(self.c.post("/api/sheet/import", data={"file": (io.BytesIO(buf.getvalue()), "b.xlsx")}).status_code, 400)

    def test_blank_rows_and_extra_columns_are_ignored(self):
        text = "Notes about my sheet\n\nDate\tItem\tAmount\tColour\n\nNov 1, 2026\tA\t5\tred\n\n"
        self.assertEqual(self.post("/api/sheet/import", text=text).get_json()["imported"], 1)


if __name__ == "__main__":
    unittest.main()
