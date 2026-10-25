import contextlib
import io
import os
import sqlite3
import sys
import tempfile
import threading
import unittest

from engine import tagger
from server.app import serve
from tests.test_server import ServerCase

HAVE_MODEL = tagger.available()


class NameBefore(unittest.TestCase):
    """Pure text logic (no model needed): which unknown word sits in front of the numbers."""
    known = {"dm", "ht", "mg/dl", "kg", "fbs", "bp", "hba1c"}

    def name(self, text, at, bound=0):
        r = tagger._name_before(text, at, bound, self.known)
        return None if r is None else (r[0], text[r[1]:r[2]])

    def test_after_header_colon(self):
        t = "DM : sugar 120"
        self.assertEqual(self.name(t, t.index("120")), ("sugar", "sugar"))

    def test_two_word_name_after_previous_value(self):
        t = "DM : FBS 120->130 glycated Hb 9.4"
        self.assertEqual(self.name(t, t.index("9.4"), bound=t.index("130") + 3), ("glycated Hb", "glycated Hb"))

    def test_unit_and_header_words_are_not_part_of_the_name(self):
        t = "DM sugar 120"
        self.assertEqual(self.name(t, t.index("120")), ("sugar", "sugar"))
        t2 = "FBS 120 mg/dL creat 2.1"
        self.assertEqual(self.name(t2, t2.index("2.1"), bound=t2.index("120") + 3), ("creat", "creat"))

    def test_no_name_or_known_name_gives_none(self):
        self.assertIsNone(self.name("DM : 120", 5))
        self.assertIsNone(self.name("DM : FBS 120", 9))                    # FBS is already a known word: nothing to teach
        self.assertIsNone(self.name("a b c d e 120", 10))                  # too many words to be a name

    def test_name_stays_on_its_own_line(self):
        t = "DM : sugar 120\n99"
        self.assertIsNone(self.name(t, t.index("99")))


@unittest.skipUnless(HAVE_MODEL, "onnxruntime/numpy or ml_tagger model not available")
class WithModel(unittest.TestCase):
    def test_unknown_name_is_suggested_with_a_usable_offset(self):
        note = "DM : sugar 120->130\nHT : BP 150/90\nCKD : Cr 1.5 GFR 54"
        items = tagger.suggest(note)
        self.assertEqual([i["param"] for i in items], ["FBS"])
        i = items[0]
        self.assertEqual(i["values"], ["120", "130"])
        self.assertEqual(note[i["ns"]:i["ne"]], "sugar")
        fixed = note[:i["ns"]] + i["alias"] + note[i["ne"]:]               # what pressing the button does
        from engine.parse_note import collect_params, parse_note
        self.assertEqual(collect_params(parse_note(fixed))["FBS"]["series"], [120.0, 130.0])

    def test_fully_read_note_gets_no_suggestion(self):
        self.assertEqual(tagger.suggest("DM : FBS 120->130 HbA1c 8.1%\nHT : BP 150/90\nCKD : Cr 1.5 GFR 54\n22/10/69 : ใจสั่น"), [])

    def test_thai_digits_keep_offsets(self):
        note = "เบาหวาน : sugar ๑๒๐"
        items = tagger.suggest(note)
        self.assertTrue(items and note[items[0]["ns"]:items[0]["ne"]] == "sugar")


class Endpoint(ServerCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dbpath = os.path.join(cls.tmp.name, "app.db")
        cls.stdout, cls.stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(cls.stdout):
            cls.httpd, cls.db = serve("127.0.0.1", 0, cls.dbpath, quiet=False, use_tagger=True)
        cls.port = cls.httpd.server_address[1]
        cls.admin_pin = cls.stdout.getvalue().split("PIN ")[1].split()[0]
        cls._err = sys.stderr; sys.stderr = cls.stderr
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    def token(self):
        return self.login()[1]["token"]

    def test_needs_login(self):
        self.assertEqual(self.call("/api/suggest", {"action": "suggest", "note": "x"})[0], 401)

    def test_generate_tells_the_page_the_helper_is_on(self):
        code, d, _ = self.call("/api/generate", {"note": "DM : FBS 120"}, self.token())
        self.assertEqual((code, d["tagger"]), (200, True))

    def test_status_tells_the_page_whether_to_show_the_switch(self):
        self.assertEqual(self.call("/api/suggest", {"action": "status"}, self.token())[1], {"available": HAVE_MODEL})

    def test_feedback_stores_only_counters_never_text(self):
        t = self.token()
        self.assertEqual(self.call("/api/suggest", {"action": "feedback", "param": "FBS", "accepted": True, "conf": 0.97, "note": "SECRETNOTE-123", "name": "SECRETNAME"}, t)[0], 200)
        self.assertEqual(self.call("/api/suggest", {"action": "feedback", "param": "FBS", "accepted": False, "conf": 0.6}, t)[0], 200)
        st = self.call("/api/admin/stats", {}, t)[1]["tagger"]
        self.assertEqual(st["total"], 2)
        self.assertEqual({b["band"]: (b["accepted"], b["rejected"]) for b in st["byBand"]}, {">=0.95": (1, 0), "<0.8": (0, 1)})
        raw = sqlite3.connect(self.dbpath).execute("SELECT group_concat(param || accepted || conf_band) FROM tagger_feedback").fetchone()[0]
        self.assertNotIn("SECRET", raw)
        cols = [r[1] for r in sqlite3.connect(self.dbpath).execute("PRAGMA table_info(tagger_feedback)")]
        self.assertEqual(cols, ["id", "param", "accepted", "conf_band", "created_at"])

    def test_feedback_rejects_bad_input(self):
        t = self.token()
        for bad in ({"param": "NOPE", "accepted": True, "conf": 1}, {"param": "FBS", "accepted": "yes", "conf": 1}, {"param": "FBS", "accepted": True, "conf": "x"}):
            self.assertEqual(self.call("/api/suggest", dict(bad, action="feedback"), t)[0], 400)

    def test_note_is_not_stored_or_logged(self):
        t = self.token()
        self.call("/api/suggest", {"action": "suggest", "note": "DM : zzmarkerzz 120"}, t)
        self.assertNotIn("zzmarkerzz", self.stderr.getvalue())
        self.assertNotIn(b"zzmarkerzz", open(self.dbpath, "rb").read())


class Disabled(ServerCase):
    def test_off_by_default(self):
        t = self.login()[1]["token"]
        code, d, _ = self.call("/api/generate", {"note": "DM : FBS 120"}, t)
        self.assertFalse(d["tagger"])
        self.assertEqual(self.call("/api/suggest", {"action": "suggest", "note": "DM : sugar 120"}, t)[1], {"available": False, "items": []})
        self.assertEqual(self.call("/api/suggest", {"action": "status"}, t)[1], {"available": False, "items": []})


if __name__ == "__main__":
    unittest.main()


class TeachTheRules(unittest.TestCase):
    """Route 1: a doctor's accepted suggestion becomes a dictionary word (after an admin approves), so the RULES read it next time."""

    def rows(self, term, param, n):
        return [{"k": "taught", "t": term, "p": param} for _ in range(n)]

    def test_two_confirmations_make_a_suggestion_and_one_does_not(self):
        from tools.learn_terms import learn_rows
        self.assertEqual([s for s in learn_rows(self.rows("sugar", "FBS", 1)) if s["term"] == "sugar"], [])
        s = [s for s in learn_rows(self.rows("sugar", "FBS", 2)) if s["term"] == "sugar"]
        self.assertEqual((s[0]["kind"], s[0]["target"], s[0]["notes"], s[0]["confidence"]), ("param_alias", "FBS", 2, "high"))

    def test_conflicting_answers_are_low_confidence_and_listed(self):
        from tools.learn_terms import learn_rows
        s = [s for s in learn_rows(self.rows("zz", "FBS", 2) + self.rows("zz", "eGFR", 2)) if s["term"] == "zz"][0]
        self.assertEqual(s["confidence"], "low")
        self.assertTrue(s["alternatives"])

    def test_bad_rows_are_ignored(self):
        from tools.learn_terms import learn_rows
        bad = self.rows("x;drop table", "FBS", 3) + self.rows("sugar", "NOTAPARAM", 3) + self.rows("a" * 40, "FBS", 3)
        self.assertEqual([s for s in learn_rows(bad) if s["kind"] == "param_alias"], [])

    def test_end_to_end_into_a_temp_dictionary(self):
        import json, shutil
        from engine.lexicon import Lexicon
        from engine.parse_note import collect_params, parse_note
        from tools.apply_terms import apply_and_write
        from tools.learn_terms import learn_rows
        lex_path = os.path.join(tempfile.mkdtemp(), "lexicon.json")
        shutil.copy(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "lexicon.json"), lex_path)
        rows = self.rows("sugar", "FBS", 2) + self.rows("glycated Hb", "HbA1c", 2) + self.rows("น้ำตาลสะสม", "HbA1c", 2)
        chosen = [s for s in learn_rows(rows) if s["kind"] == "param_alias"]
        self.assertEqual(sorted(s["term"] for s in chosen), ["glycated hb", "sugar", "น้ำตาลสะสม"])
        r = apply_and_write(chosen, path=lex_path)
        self.assertTrue(r["success"], r)
        lex = Lexicon(json.load(open(lex_path, encoding="utf-8")))
        got = collect_params(parse_note("DM : sugar 120->130 glycated Hb 9.4", lexicon=lex))
        self.assertEqual((got["FBS"]["series"], got["HbA1c"]["series"]), ([120.0, 130.0], [9.4]))
        self.assertEqual(collect_params(parse_note("DM : น้ำตาลสะสม 8.2", lexicon=lex))["HbA1c"]["series"], [8.2])

    def test_unreadable_or_malformed_names_are_refused_and_never_added(self):
        import json
        from unittest import mock
        from tools import apply_terms
        data = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "lexicon.json"), encoding="utf-8"))
        new, done, refused = apply_terms.apply(data, [{"approve": True, "kind": "param_alias", "term": "9sugar", "target": "FBS"}])
        self.assertEqual((done, len(refused)), ([], 1))
        with mock.patch.object(apply_terms, "_alias_is_read", return_value=False):
            new, done, refused = apply_terms.apply(data, [{"approve": True, "kind": "param_alias", "term": "sugar", "target": "FBS"}])
        self.assertEqual(done, [])
        self.assertNotIn("sugar", new["params"]["FBS"]["aliases"])
        self.assertTrue(apply_terms._alias_is_read(apply_terms.apply(data, [{"approve": True, "kind": "param_alias", "term": "sugar", "target": "FBS"}])[0], "FBS", "sugar"))


class TaughtEndpoint(ServerCase):
    def setUp(self):
        from engine import learning_log
        self.ll = learning_log
        self.old = learning_log.PATH
        learning_log.PATH = os.path.join(tempfile.mkdtemp(), "log.json")
        self.addCleanup(lambda: setattr(learning_log, "PATH", self.old))
        self.t = self.login()[1]["token"]

    def test_refused_while_the_log_is_off(self):
        self.assertEqual(self.call("/api/learn", {"action": "taught", "term": "sugar", "param": "FBS"}, self.t)[0], 403)

    def test_stores_only_term_and_parameter(self):
        self.call("/api/admin/learning", {"action": "set", "enabled": True}, self.t)
        code, d, _ = self.call("/api/learn", {"action": "taught", "term": "Sugar", "param": "FBS", "note": "SECRET NOTE"}, self.t)
        self.assertEqual((code, d["stored"]), (200, 1))
        self.assertEqual(self.ll.export()["rows"], [{"k": "taught", "t": "sugar", "p": "FBS"}])

    def test_bad_input_is_rejected(self):
        self.call("/api/admin/learning", {"action": "set", "enabled": True}, self.t)
        for bad in ({"term": "x;y", "param": "FBS"}, {"term": "sugar", "param": "LDL"}, {"term": "", "param": "FBS"}, {"term": 5, "param": "FBS"}, {"term": "a" * 40, "param": "FBS"}):
            self.assertEqual(self.call("/api/learn", dict(bad, action="taught"), self.t)[0], 400, bad)
        self.assertEqual(self.ll.export()["rows"], [])
