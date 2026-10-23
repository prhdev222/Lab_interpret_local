import json
import os
import subprocess
import sys
import tempfile
import unittest

from tools import make_gold

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOTE = "DM : FBS 120->130 HbA1c 7.2\nHT : BP 150/90\n22/10/69 : เวียนศีรษะ ยังสูบบุหรี่"


class Commands(unittest.TestCase):
    def test_draft_is_what_the_parser_reads(self):
        e = make_gold.draft_expected(NOTE)
        self.assertEqual(e["params"]["FBS"], [120, 130]); self.assertEqual(e["params"]["BP"], [[150, 90]])
        self.assertEqual(e["concepts"], {"smoking": "current", "dizziness": "present"})

    def test_corrections(self):
        e = make_gold.draft_expected(NOTE)
        self.assertIsNone(make_gold.apply_command(e, "p HbA1c 9 7.5")); self.assertEqual(e["params"]["HbA1c"], [9, 7.5])
        self.assertIsNone(make_gold.apply_command(e, "p bp 140/85 150/90")); self.assertEqual(e["params"]["BP"], [[140, 85], [150, 90]])
        self.assertIsNone(make_gold.apply_command(e, "d FBS")); self.assertNotIn("FBS", e["params"])
        self.assertIsNone(make_gold.apply_command(e, "c dizziness=absent")); self.assertEqual(e["concepts"]["dizziness"], "absent")
        self.assertIsNone(make_gold.apply_command(e, "dc smoking")); self.assertNotIn("smoking", e["concepts"])
        self.assertIsNone(make_gold.apply_command(e, "c smoking=former")); self.assertEqual(e["concepts"]["smoking"], "former")

    def test_bad_commands_change_nothing_and_explain(self):
        e = make_gold.draft_expected(NOTE); before = json.dumps(e, sort_keys=True)
        for bad in ("p Nope 1", "p FBS abc", "d Cr", "c dizziness=maybe", "c foo=present", "c smoking=sometimes", "dc zzz", "xyz", "p FBS"):
            self.assertIsNotNone(make_gold.apply_command(e, bad), bad)
        self.assertEqual(json.dumps(e, sort_keys=True), before)


class EndToEnd(unittest.TestCase):
    def test_session_writes_a_gold_file_the_evaluator_accepts(self):
        d = tempfile.mkdtemp(); notes, out = os.path.join(d, "n.txt"), os.path.join(d, "g.jsonl")
        open(notes, "w", encoding="utf-8").write(NOTE + "\n\nDM : FBS 95 Zork 5\n")
        script = "p HbA1c 9\n\n\nq\n"                                   # fix note 1, accept it; note 2: accept as read; quit
        r = subprocess.run([sys.executable, "tools/make_gold.py", notes, "--out", out], cwd=ROOT, input="p HbA1c 9\n\n\n", capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = [json.loads(l) for l in open(out, encoding="utf-8")]
        self.assertEqual(len(rows), 2); self.assertEqual(rows[0]["expected"]["params"]["HbA1c"], [9])
        ev = subprocess.run([sys.executable, "eval/evaluate_parser.py", "--gold", out], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(ev.returncode, 0, ev.stderr)
        again = subprocess.run([sys.executable, "tools/make_gold.py", notes, "--out", out], cwd=ROOT, input="", capture_output=True, text=True)
        self.assertIn("ทำต่อ", again.stdout)                              # resumes instead of starting over


if __name__ == "__main__":
    unittest.main()
