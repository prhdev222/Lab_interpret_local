import contextlib
import io
import json
import random
import subprocess
import sys
import unittest

sys.path.insert(0, "tools")
sys.path.insert(0, "eval")
from evaluate_parser import evaluate  # noqa: E402
from suggest_terms import suggest  # noqa: E402
from synth_notes import make  # noqa: E402


def records(n, seed=1):
    rnd = random.Random(seed)
    return [make(rnd) for _ in range(n)]


class Synthetic(unittest.TestCase):
    def test_deterministic(self):
        self.assertEqual(records(30), records(30))
        self.assertNotEqual(records(30), records(30, seed=2))

    def test_parser_reads_every_synthetic_style_correctly(self):
        out = io.StringIO()
        res = evaluate(records(600), out=out)
        wrong = [p for p in res["problems"]]
        self.assertEqual(wrong, [], out.getvalue())

    def test_all_styles_present(self):
        notes = "\n".join(r["note"] for r in records(300))
        for marker in ("T2DM", "HTN", "Obese", "๑", "：", "-->", "→", "=>", "hba1c"):
            self.assertIn(marker, notes)


class Evaluate(unittest.TestCase):
    def test_detects_wrong_missed_and_invented(self):
        recs = [{"note": "DM : HbA1c 7.0", "expected": {"params": {"HbA1c": [8.0], "FBS": [100]}, "concepts": {}}},
                {"note": "DM : FBS 100", "expected": {"params": {}, "concepts": {}}}]
        res = evaluate(recs, out=io.StringIO())
        kinds = {(f, k) for _, f, k in res["problems"]}
        self.assertEqual(kinds, {("HbA1c", "wrong value"), ("FBS", "missed"), ("FBS", "not in the note (invented)")})
        self.assertEqual(res["perfect"], 0)

    def test_report_hides_note_text_by_default(self):
        secret = "DM : HbA1c 7.0 นายสมชายใจดี"
        buf = io.StringIO()
        evaluate([{"note": secret, "expected": {"params": {"HbA1c": [9.9]}, "concepts": {}}}], out=buf)
        self.assertNotIn("สมชาย", buf.getvalue()); self.assertNotIn("7.0", buf.getvalue())
        buf2 = io.StringIO()
        evaluate([{"note": secret, "expected": {"params": {"HbA1c": [9.9]}, "concepts": {}}}], show_text=True, out=buf2)
        self.assertIn("สมชาย", buf2.getvalue())                                    # only when explicitly asked

    def test_command_line_runs(self):
        r = subprocess.run([sys.executable, "eval/evaluate_parser.py", "--synthetic", "40"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr); self.assertIn("read perfectly: 40 (100.0%)", r.stdout)


class SuggestTerms(unittest.TestCase):
    def test_frequent_unknown_words_are_suggested_rare_ones_are_not(self):
        notes = [f"22/10/69 : นอนไม่หลับ ชื่อลับ{i}" for i in range(6)] + ["22/10/69 : คลื่นไส้"]
        res = dict(suggest(notes, min_count=5))
        self.assertEqual(res, {"นอนไม่หลับ": 6})                                    # 'ชื่อลับN' (one-offs) and 'คลื่นไส้' (1 note) are hidden

    def test_phrases_with_digits_are_skipped(self):
        res = dict(suggest(["22/10/69 : โทร0812345678"] * 10, min_count=5))
        self.assertEqual(res, {})

    def test_known_words_are_not_suggested(self):
        self.assertEqual(suggest(["22/10/69 : มีเวียนศีรษะ ฉันได้น้อย"] * 10, 1), [])


if __name__ == "__main__":
    unittest.main()
