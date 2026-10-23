import json
import os
import stat
import tempfile
import unittest

from engine import learning_log as LL
from tests.test_learn_terms import TEXTS
from tools import learn_terms

MARKERS = ["นายทดสอบ", "99887766", "22/10/69", "สมชาย", "HN"]
NOTE = ("DM : FBS 112 BS 118 HbA1c 7.2\nHT : BP 150/90\nCKD : Cr 1.5 Zork 99999\nDiab : FBS 100 HbA1c 6.5\n"
        "22/10/69 : เวียนศรีษะ นายทดสอบ HN99887766 สมชาย")


class WithLog(unittest.TestCase):
    def setUp(self):
        self.old, self.max = LL.PATH, LL.MAX_ROWS
        LL.PATH = os.path.join(tempfile.mkdtemp(), "log.json")
        self.addCleanup(lambda: (setattr(LL, "PATH", self.old), setattr(LL, "MAX_ROWS", self.max)))


class Rows(unittest.TestCase):
    def test_nothing_identifying_or_free_text_is_extracted(self):
        rows = learn_terms.extract_rows(NOTE)
        blob = json.dumps(rows, ensure_ascii=False)
        for m in MARKERS:
            self.assertNotIn(m, blob, m)
        self.assertNotIn("Zork", blob); self.assertNotIn("zork", blob)                     # value fits no known parameter: dropped
        self.assertTrue(all(set(r) <= {"k", "p", "v", "g", "t", "pair", "with"} for r in rows))

    def test_expected_features_are_there(self):
        rows = learn_terms.extract_rows(NOTE)
        self.assertIn({"k": "known", "p": "FBS", "v": 112.0, "g": "DM"}, rows)
        self.assertTrue(any(r["k"] == "unk" and r["t"] == "bs" and r["v"] == 118.0 and r["g"] == "DM" for r in rows))
        self.assertTrue(any(r["k"] == "word" and r["t"] == "เวียนศรีษะ" for r in rows))
        self.assertTrue(any(r["k"] == "prob" and r["t"] == "diab" for r in rows))

    def test_long_or_odd_names_are_not_kept(self):
        rows = learn_terms.extract_rows("DM : FBS 100 Averyveryverylongname 120")
        self.assertFalse([r for r in rows if r["k"] == "unk"])

    def test_learning_from_log_rows_gives_the_same_answers_as_from_notes(self):
        rows = [r for t in TEXTS for r in learn_terms.extract_rows(t)]                      # as the log would hold them: no note index
        by = {s["term"]: s for s in learn_terms.learn_rows(rows, 5)}
        for term, target in (("bs", "FBS"), ("crea", "Creatinine"), ("wgt", "BW"), ("hba", "HbA1c"), ("เวียนศรีษะ", "dizziness")):
            self.assertEqual(by[term]["target"], target, term)


class Log(WithLog):
    def test_off_by_default_and_stores_nothing(self):
        self.assertFalse(LL.status()["enabled"])
        self.assertEqual(LL.add_rows([{"k": "word", "t": "x"}]), 0); self.assertFalse(os.path.exists(LL.PATH))

    def test_enable_store_export_clear(self):
        LL.set_enabled(True)
        self.assertEqual(LL.add_rows([{"k": "word", "t": f"w{i}"} for i in range(5)]), 5)
        self.assertEqual(LL.status(), {"enabled": True, "rows": 5, "max": LL.MAX_ROWS}); self.assertEqual(len(LL.export()["rows"]), 5)
        LL.clear(); self.assertEqual(LL.status()["rows"], 0); self.assertTrue(LL.status()["enabled"])

    def test_rows_are_inserted_at_random_positions(self):
        LL.set_enabled(True)
        for i in range(60):
            LL.add_rows([{"k": "word", "t": f"{i:03d}"}])
        order = [r["t"] for r in LL.export()["rows"]]
        self.assertEqual(sorted(order), sorted(f"{i:03d}" for i in range(60))); self.assertNotEqual(order, sorted(order))

    def test_cap_and_file_permissions(self):
        LL.MAX_ROWS = 3; LL.set_enabled(True)
        self.assertEqual(LL.add_rows([{"k": "word", "t": str(i)} for i in range(10)]), 3); self.assertEqual(LL.add_rows([{"k": "word", "t": "z"}]), 0)
        self.assertEqual(stat.S_IMODE(os.stat(LL.PATH).st_mode), 0o600)

    def test_broken_file_is_treated_as_empty_and_off(self):
        open(LL.PATH, "w").write("{ nope")
        self.assertEqual(LL.status()["rows"], 0); self.assertFalse(LL.status()["enabled"])


if __name__ == "__main__":
    unittest.main()
