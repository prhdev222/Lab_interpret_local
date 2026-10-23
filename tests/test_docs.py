import json
import os
import subprocess
import sys
import unittest

from engine.rules import RULES

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = open(os.path.join(ROOT, "docs", "RULES_REVIEW.md"), encoding="utf-8").read()
TPL = json.load(open(os.path.join(ROOT, "data", "templates.json"), encoding="utf-8"))


class ReviewDocument(unittest.TestCase):
    def test_is_up_to_date_with_the_data_and_rules(self):
        r = subprocess.run([sys.executable, "tools/dump_rules.py", "--check"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + "  (run: python3 tools/dump_rules.py)")

    def test_lists_every_rule_and_every_sentence(self):
        for rule in RULES:
            self.assertIn(f"`{rule['id']}`", DOC)
        for key in list(TPL["findings"]) + list(TPL["clinician"]):
            self.assertIn(f"`{key}`", DOC)

    def test_says_draft_and_has_a_signature_block(self):
        self.assertIn("DRAFT", DOC); self.assertIn("การลงนามรับรอง", DOC)


if __name__ == "__main__":
    unittest.main()
