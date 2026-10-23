import contextlib
import io
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from server.app import serve
from server.db import MAX_FAILS

NOTE = """DM : FBS 120->130->110 HbA1C 12->10->6.5%
HT : BP 150/90mmHg HMBP 120/80mmHg
Obesity : BW 110-->100Kg BMI 31
CKD : Cr 1.5 GFR 54
22/10/69 : มีเวียนศีรษะ ฉันได้น้อย ยังสูบบุหรี่อยู่"""


class ServerCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dbpath = os.path.join(cls.tmp.name, "app.db")
        cls.stdout, cls.stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(cls.stdout):                       # captures the one-time admin PIN banner
            cls.httpd, cls.db = serve("127.0.0.1", 0, cls.dbpath, quiet=False)
        cls.port = cls.httpd.server_address[1]
        cls.admin_pin = cls.stdout.getvalue().split("PIN ")[1].split()[0]
        cls._err = sys.stderr; sys.stderr = cls.stderr                      # request log lines (method/path/status) go here
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        sys.stderr = cls._err
        cls.httpd.shutdown(); cls.httpd.server_close(); cls.db.con.close(); cls.tmp.cleanup()

    def call(self, path, data=None, token=None, method="POST", ctype="application/json", raw=None):
        body = raw if raw is not None else json.dumps(data or {}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=None if method == "GET" else body, method=method)
        req.add_header("Content-Type", ctype)
        if token: req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                raw_body = r.read()
                try: return r.status, json.loads(raw_body or b"{}"), r.headers
                except ValueError: return r.status, {"_raw": raw_body.decode("utf-8", "replace")}, r.headers
        except urllib.error.HTTPError as e:
            raw_body = e.read()
            try: return e.code, json.loads(raw_body), e.headers
            except ValueError: return e.code, {}, e.headers

    def login(self, user="admin", pin=None):
        code, d, _ = self.call("/api/login", {"username": user, "pin": pin or self.admin_pin})
        return code, d


class Auth(ServerCase):
    def test_first_admin_pin_is_random_8_digits_not_1234(self):
        self.assertRegex(self.admin_pin, r"^\d{8}$")
        self.assertNotEqual(self.admin_pin, "1234")

    def test_login_ok_and_wrong(self):
        code, d = self.login(); self.assertEqual(code, 200); self.assertTrue(d["user"]["isAdmin"])
        self.assertEqual(self.login(pin="00000000")[0], 401)
        self.assertEqual(self.login(user="nobody")[0], 401)

    def test_same_error_for_unknown_user_and_wrong_pin(self):
        self.assertEqual(self.login(user="nobody")[1]["error"], self.login(pin="99999999")[1]["error"])

    def test_pages_and_api_need_login(self):
        for path in ("/api/generate", "/api/me", "/api/admin/users", "/api/admin/stats"):
            self.assertEqual(self.call(path, {"note": "DM : HbA1c 7"})[0], 401, path)

    def test_lockout_after_repeated_failures(self):
        self.db.add_user("locktest", "123456", "ทดสอบล็อก", "staff")
        for _ in range(MAX_FAILS):
            self.assertEqual(self.login("locktest", "wrong1")[0], 401)
        code, d = self.login("locktest", "123456")                           # correct PIN is refused while locked
        self.assertEqual(code, 401); self.assertIn("ล็อก", d["error"])

    def test_session_check_works_with_GET_as_the_page_does(self):
        token = self.login()[1]["token"]
        code, d, _ = self.call("/api/me", method="GET", token=token)
        self.assertEqual(code, 200); self.assertEqual(d["user"]["username"], "admin")
        self.assertEqual(self.call("/api/me", method="GET")[0], 401)
        self.assertEqual(self.call("/api/me", method="GET", token="not-a-token")[0], 401)

    def test_logout_invalidates_token(self):
        token = self.login()[1]["token"]
        self.assertEqual(self.call("/api/me", token=token)[0], 200)
        self.call("/api/logout", token=token)
        self.assertEqual(self.call("/api/me", token=token)[0], 401)

    def test_tokens_are_not_stored_in_plaintext(self):
        token = self.login()[1]["token"]
        with open(self.dbpath, "rb") as f: raw = f.read()
        self.assertNotIn(token.encode(), raw)

    def test_pin_is_not_stored_in_plaintext_and_hashes_are_salted(self):
        with open(self.dbpath, "rb") as f: raw = f.read()
        self.assertNotIn(self.admin_pin.encode(), raw)
        self.db.add_user("twin1", "samepin1", "a"); self.db.add_user("twin2", "samepin1", "b")
        h = {r["username"]: r["pin_hash"] for r in self.db.con.execute("SELECT username, pin_hash FROM users WHERE username LIKE 'twin%'")}
        self.assertNotEqual(h["twin1"], h["twin2"])


class Generate(ServerCase):
    def setUp(self):
        self.token = self.login()[1]["token"]

    def gen(self, **kw):
        return self.call("/api/generate", {"note": NOTE, "age": 60, "sex": "M", "pattern": "standard", "monkMode": False, **kw}, token=self.token)

    def test_example_note(self):
        code, d, _ = self.gen()
        self.assertEqual(code, 200)
        self.assertIn("HbA1c", d["result"]); self.assertIn("ท่านยังสูบบุหรี่อยู่", d["result"])
        self.assertTrue(any("น้ำตาลในเลือดต่ำ" in n["text"] for n in d["clinician"]))
        self.assertEqual(d["params_read"], 8)
        self.assertEqual(d["unparsed_lines"], [])
        self.assertIn("DRAFT", d["status"])

    def test_new_diseases_tags_and_manual_thai_cv_value_reach_the_page(self):
        code, d, _ = self.gen(note="CKD : Cr 1.8 eGFR 38 U/S KUB increased echo, no hydro\nDR : NPDR mild\nMAFLD : ALT 85 AST 60 Plt 180", age=60, sex="M", tcvr="22.5")
        self.assertEqual(code, 200)
        labels = {(t["label"], t["value"]) for row in d["table"] for t in row["tags"]}
        self.assertIn(("U/S ไต echo เพิ่ม", "present"), labels); self.assertIn(("U/S hydronephrosis", "absent"), labels); self.assertIn(("NPDR mild", "present"), labels)
        self.assertIn("FIB-4", d["result"]); self.assertIn("22.5", d["result"]); self.assertIn("กรอกเอง", " ".join(n["text"] for n in d["clinician"]))

    def test_monk_and_patterns(self):
        d = self.gen(monkMode=True, pattern="simple")[1]
        self.assertIn("พระคุณเจ้า", d["result"]); self.assertNotIn("รับประทาน", d["result"])
        self.assertNotEqual(self.gen(pattern="detailed")[1]["result"], self.gen(pattern="simple")[1]["result"])

    def test_bad_inputs(self):
        self.assertEqual(self.call("/api/generate", {"note": ""}, token=self.token)[0], 400)
        self.assertEqual(self.call("/api/generate", {"note": 123}, token=self.token)[0], 400)
        self.assertEqual(self.call("/api/generate", {"note": "x" * 30000}, token=self.token)[0], 413)
        self.assertEqual(self.call("/api/generate", raw=b"{not json", token=self.token)[0], 400)
        self.assertEqual(self.call("/api/generate", raw=b"[1,2]", token=self.token)[0], 400)
        self.assertEqual(self.call("/api/generate", {"note": "x"}, token=self.token, ctype="text/plain")[0], 415)

    def test_garbage_in_gives_polite_empty_result_not_an_error(self):
        code, d, _ = self.call("/api/generate", {"note": "สวัสดีครับ วันนี้อากาศดี"}, token=self.token)
        self.assertEqual(code, 200); self.assertEqual(d["interpreted"], 0); self.assertIn("ไม่พบค่า", d["result"])
        self.assertEqual(len(d["unparsed_lines"]), 1)

    def test_nothing_about_the_note_is_stored_or_logged(self):
        # Distinctive markers only: the database file is full of hex hashes, so a short needle such as "143" can collide by chance.
        marker = "ทดสอบเครื่องหมายเฉพาะ"
        marker_note = f"DM : HbA1c 8.37 FBS 143\n22/10/69 : มีเวียนศีรษะ ใจสั่น {marker}"
        self.call("/api/generate", {"note": marker_note, "age": 61, "sex": "F"}, token=self.token)
        with open(self.dbpath, "rb") as f: raw = f.read()
        for needle in (marker, "8.37", "เวียนศีรษะ", "ใจสั่น", "HbA1c", "FBS"):
            self.assertNotIn(needle.encode("utf-8"), raw, f"{needle!r} found in the database file")
        logs = self.stderr.getvalue()
        for needle in (marker, "8.37", "เวียนศีรษะ", "ใจสั่น", "HbA1c", "FBS"):
            self.assertNotIn(needle, logs, f"{needle!r} found in the request log")
        self.assertIn("/api/generate", logs)                                   # the log does exist (method/path/status only)

    def test_usage_counters_hold_no_patient_data(self):
        self.gen()
        row = dict(self.db.con.execute("SELECT * FROM usage_log ORDER BY id DESC LIMIT 1").fetchone())
        self.assertEqual(set(row), {"id", "user_id", "pattern", "monk_mode", "created_at"})


class Resilience(ServerCase):
    def test_internal_error_gives_500_without_leaking_and_server_survives(self):
        import server.app as app
        token = self.login()[1]["token"]
        original = app.parse_note
        app.parse_note = lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("SECRET-NOTE-CONTENT 8.37"))
        try:
            code, d, _ = self.call("/api/generate", {"note": "DM : HbA1c 8.37"}, token=token)
        finally:
            app.parse_note = original
        self.assertEqual(code, 500); self.assertNotIn("SECRET", json.dumps(d, ensure_ascii=False)); self.assertNotIn("8.37", json.dumps(d))
        logs = self.stderr.getvalue()
        self.assertIn("internal error: RuntimeError", logs); self.assertNotIn("SECRET-NOTE-CONTENT", logs); self.assertNotIn("8.37", logs)
        self.assertEqual(self.call("/api/generate", {"note": "DM : HbA1c 8"}, token=token)[0], 200)      # still alive

    def test_oversize_body_is_rejected_even_if_the_client_keeps_sending(self):
        token = self.login()[1]["token"]
        try:
            code = self.call("/api/generate", raw=b"x" * 100000, token=token)[0]
            self.assertEqual(code, 413)
        except (urllib.error.URLError, ConnectionError, OSError):
            pass                                                                # connection dropped = also a rejection


class Admin(ServerCase):
    def setUp(self):
        self.token = self.login()[1]["token"]

    def adm(self, **d):
        return self.call("/api/admin/users", d, token=self.token)

    def test_user_lifecycle(self):
        self.assertEqual(self.adm(action="add", username="nurse1", displayName="พยาบาลหนึ่ง", pin="654321", role="nurse")[0], 200)
        self.assertEqual(self.adm(action="add", username="nurse1", displayName="ซ้ำ", pin="654321")[0], 400)
        self.assertEqual(self.adm(action="add", username="shortpin", displayName="x", pin="1234")[0], 400)
        users = self.adm(action="list")[1]["users"]
        uid = next(u["id"] for u in users if u["username"] == "nurse1")
        self.assertNotIn("pin_hash", users[0]); self.assertNotIn("salt", users[0])
        t2 = self.login("nurse1", "654321")[1]["token"]
        self.assertEqual(self.call("/api/admin/users", {"action": "list"}, token=t2)[0], 403)             # non-admin refused
        self.assertEqual(self.call("/api/admin/stats", {}, token=t2)[0], 403)
        self.assertEqual(self.adm(action="reset_pin", userId=uid, pin="111111", confirmPin="wrong")[0], 403)
        self.assertEqual(self.adm(action="reset_pin", userId=uid, pin="111111", confirmPin=self.admin_pin)[0], 200)
        self.assertEqual(self.call("/api/me", token=t2)[0], 401)                                          # reset_pin kills old sessions
        self.assertEqual(self.login("nurse1", "654321")[0], 401); self.assertEqual(self.login("nurse1", "111111")[0], 200)
        self.assertEqual(self.adm(action="delete", userId=uid)[0], 200)
        self.assertEqual(self.login("nurse1", "111111")[0], 401)

    def test_usernames_and_display_names_cannot_carry_markup(self):
        for bad in ("a'b", "<script>", "x y", "a", "x" * 40, "ไทย"):
            self.assertEqual(self.adm(action="add", username=bad, displayName="ok", pin="654321")[0], 400, bad)
        self.assertEqual(self.adm(action="add", username="okname", displayName="x" * 61, pin="654321")[0], 400)
        self.assertEqual(self.adm(action="add", username="okname2", displayName="พญ.สมศรี <b>", pin="654321")[0], 200)   # stored as text; the page escapes it

    def test_admin_cannot_be_deleted(self):
        admin_id = next(u["id"] for u in self.adm(action="list")[1]["users"] if u["username"] == "admin")
        self.adm(action="delete", userId=admin_id)
        self.assertEqual(self.login()[0], 200)

    def test_stats_shape(self):
        d = self.call("/api/admin/stats", {}, token=self.token)[1]
        self.assertEqual(set(d), {"daily", "perUser", "perPattern", "activeSessions", "totalLogs"})


class LearningLog(ServerCase):
    NOTE = "DM : FBS 112 BS 118 HbA1c 7.2\nCKD : Cr 1.5\n22/10/69 : เวียนศรีษะ นายทดสอบ HN99887766"

    def setUp(self):
        from engine import learning_log
        self.ll = learning_log
        self.old = learning_log.PATH; learning_log.PATH = os.path.join(tempfile.mkdtemp(), "log.json")
        self.addCleanup(lambda: setattr(learning_log, "PATH", self.old))
        self.token = self.login()[1]["token"]

    def learn(self, token=None, **kw):
        return self.call("/api/learn", kw, token=token or self.token)

    def adm(self, token=None, **kw):
        return self.call("/api/admin/learning", kw, token=token or self.token)

    def test_login_needed_and_off_by_default(self):
        self.assertEqual(self.call("/api/learn", {"action": "status"})[0], 401)
        self.assertFalse(self.learn(action="status")[1]["enabled"])
        self.assertEqual(self.learn(action="preview", note=self.NOTE)[0], 403); self.assertEqual(self.learn(action="save", note=self.NOTE)[0], 403)
        self.assertFalse(os.path.exists(self.ll.PATH))
        self.assertFalse(self.call("/api/generate", {"note": self.NOTE, "age": 60, "sex": "M"}, token=self.token)[1]["learning"])

    def test_only_admin_controls_the_log(self):
        self.call("/api/admin/users", {"action": "add", "username": "nurse5", "displayName": "n", "pin": "654321"}, token=self.token)
        t2 = self.login("nurse5", "654321")[1]["token"]
        for action in ("status", "set", "export", "clear"):
            self.assertEqual(self.adm(token=t2, action=action, enabled=True)[0], 403, action)
        self.assertEqual(self.call("/api/admin/learning", {"action": "status"})[0], 401)

    def test_preview_shows_exactly_what_would_be_stored_and_save_stores_only_that(self):
        self.assertTrue(self.adm(action="set", enabled=True)[1]["enabled"])
        self.assertTrue(self.call("/api/generate", {"note": self.NOTE, "age": 61, "sex": "F"}, token=self.token)[1]["learning"])
        d = self.learn(action="preview", note=self.NOTE)[1]
        text = " ".join(d["rows"]); self.assertIn("'bs'", text); self.assertIn("เวียนศรีษะ", text)
        self.assertEqual(self.ll.status()["rows"], 0)                                   # preview stores nothing
        d = self.learn(action="save", note=self.NOTE)[1]
        self.assertTrue(d["success"]); self.assertGreater(d["stored"], 0)
        raw = open(self.ll.PATH, encoding="utf-8").read()
        for needle in ("นายทดสอบ", "99887766", "22/10/69", "admin", self.NOTE.splitlines()[0], "61", "\"F\""):
            self.assertNotIn(needle, raw, needle)                                       # no name, HN, date, user, note line, age or sex

    def test_bad_inputs(self):
        self.adm(action="set", enabled=True)
        for kw in (dict(action="save", note=""), dict(action="save", note="x" * 30000), dict(action="nope")):
            self.assertEqual(self.learn(**kw)[0], 400, kw)

    def test_export_and_clear(self):
        self.adm(action="set", enabled=True); self.learn(action="save", note=self.NOTE)
        self.assertTrue(self.adm(action="export")[1]["rows"])
        self.assertEqual(self.adm(action="clear")[1]["rows"], 0)


class TargetsEditor(ServerCase):
    def setUp(self):
        from engine import targets_edit
        self.te = targets_edit
        d = tempfile.mkdtemp(); self.old = targets_edit.PATH; targets_edit.PATH = os.path.join(d, "t.json")
        with open(self.old, encoding="utf-8") as f, open(targets_edit.PATH, "w", encoding="utf-8") as g: g.write(f.read())
        self.addCleanup(lambda: setattr(targets_edit, "PATH", self.old))
        self.token = self.login()[1]["token"]

    def call_t(self, token=None, **kw):
        return self.call("/api/admin/targets", kw, token=token or self.token)

    def test_admin_only(self):
        self.call("/api/admin/users", {"action": "add", "username": "nurse3", "displayName": "n", "pin": "654321"}, token=self.token)
        t2 = self.login("nurse3", "654321")[1]["token"]
        self.assertEqual(self.call_t(token=t2, action="get")[0], 403); self.assertEqual(self.call_t(token=t2, action="save", changes={"dm.hba1c.target_max": 7.5})[0], 403)
        self.assertEqual(self.call("/api/admin/targets", {"action": "get"})[0], 401)

    def test_get_then_save_round_trip(self):
        code, d, _ = self.call_t(action="get")
        self.assertEqual(code, 200); self.assertIn("DRAFT", d["status"])
        row = next(r for r in d["rows"] if r["path"] == "dm.hba1c.target_max")
        self.assertEqual((row["kind"], row["value"]), ("num", 7.0)); self.assertTrue(row["label"])
        code, d, _ = self.call_t(action="save", changes={"dm.hba1c.target_max": 7.5})
        self.assertFalse(d["success"]); self.assertTrue(d["needsConfirm"])                     # a seeded example (HbA1c 7.4) changes: the doctor must confirm
        self.assertIn("HbA1c 7.4", " ".join(x["note"] for x in d["diffs"]))
        code, d, _ = self.call_t(action="save", changes={"dm.hba1c.target_max": 7.5}, confirm=True)
        self.assertTrue(d["success"], d); self.assertEqual(d["changed"], ["dm.hba1c.target_max"])
        d = self.call_t(action="get")[1]
        self.assertEqual(next(r for r in d["rows"] if r["path"] == "dm.hba1c.target_max")["value"], 7.5)

    def test_bad_save_is_polite_and_changes_nothing(self):
        before = open(self.te.PATH, "rb").read()
        for changes in ({"ckd.egfr_stage.g2_from": 95}, {"_meta.status": "x"}, "x", {}, None):
            code, d, _ = self.call_t(action="save", changes=changes)
            self.assertEqual(code, 200); self.assertFalse(d["success"]); self.assertTrue(d["errors"])
        self.assertEqual(open(self.te.PATH, "rb").read(), before)
        self.assertEqual(self.call_t(action="nope")[0], 400)


class GoldenCases(ServerCase):
    def setUp(self):
        from engine import golden
        self.g = golden
        d = tempfile.mkdtemp(); self.old = golden.PATH; golden.PATH = os.path.join(d, "g.json")
        golden.save([{"id": "g-1", "note": "DM : HbA1c 7.4", "age": 60, "sex": "M", "confirmed": False}])
        self.addCleanup(lambda: setattr(golden, "PATH", self.old))
        self.token = self.login()[1]["token"]

    def gc(self, **kw):
        return self.call("/api/admin/golden", kw, token=self.token)

    def test_admin_only(self):
        self.call("/api/admin/users", {"action": "add", "username": "nurse4", "displayName": "n", "pin": "654321"}, token=self.token)
        t2 = self.login("nurse4", "654321")[1]["token"]
        self.assertEqual(self.call("/api/admin/golden", {"action": "list"}, token=t2)[0], 403)
        self.assertEqual(self.call("/api/admin/golden", {"action": "list"})[0], 401)

    def test_list_add_confirm_delete(self):
        d = self.gc(action="list")[1]
        self.assertEqual(d["cases"][0]["id"], "g-1"); self.assertIn("HbA1c", d["cases"][0]["patient"]); self.assertFalse(d["cases"][0]["confirmed"])
        code, d, _ = self.gc(action="add", note="HT : BP 150/90", age=60, sex="M"); self.assertEqual((code, d["id"]), (200, "g-2"))
        self.assertEqual(self.gc(action="confirm", id="g-2", confirmed=True)[0], 200)
        c = next(x for x in self.gc(action="list")[1]["cases"] if x["id"] == "g-2")
        self.assertTrue(c["confirmed"]); self.assertFalse(c["changedSinceConfirmed"])
        self.assertTrue(self.g.load()[1]["approved"]["findings"])                      # what was confirmed is remembered
        self.assertEqual(self.gc(action="delete", id="g-2")[0], 200); self.assertEqual(len(self.g.load()), 1)

    def test_bad_inputs(self):
        for kw in (dict(note=""), dict(note="x" * 3000), dict(note="DM : FBS 100", age="abc"), dict(note="DM : FBS 100", age=500), dict(note="DM : FBS 100", sex="X")):
            self.assertEqual(self.gc(action="add", **kw)[0], 400, kw)
        self.assertEqual(self.gc(action="confirm", id="nope", confirmed=True)[0], 404)
        self.assertEqual(self.gc(action="nope")[0], 400)

    def test_confirmed_case_is_called_out_when_a_later_change_alters_it(self):
        self.gc(action="confirm", id="g-1", confirmed=True)
        from engine import targets_edit
        old = targets_edit.PATH
        d = tempfile.mkdtemp(); targets_edit.PATH = os.path.join(d, "t.json")
        with open(old, encoding="utf-8") as f, open(targets_edit.PATH, "w", encoding="utf-8") as g: g.write(f.read())
        self.addCleanup(lambda: setattr(targets_edit, "PATH", old))
        r = self.call("/api/admin/targets", {"action": "save", "changes": {"dm.hba1c.target_max": 7.5}}, token=self.token)[1]
        self.assertTrue(r["needsConfirm"]); self.assertEqual(r["violated"], ["g-1"])

    def test_typical_range_warning_needs_confirmation_even_with_no_example_changing(self):
        from engine import targets_edit
        old = targets_edit.PATH
        d = tempfile.mkdtemp(); targets_edit.PATH = os.path.join(d, "t.json")
        with open(old, encoding="utf-8") as f, open(targets_edit.PATH, "w", encoding="utf-8") as g: g.write(f.read())
        self.addCleanup(lambda: setattr(targets_edit, "PATH", old))
        self.g.save([])                                                                  # no examples: only the range warning can ask for confirmation
        ch = {"dm.hba1c.target_max": 9.0, "dm.hba1c.mild_high_below": 9.5, "dm.hba1c.high_below": 11}
        r = self.call("/api/admin/targets", {"action": "save", "changes": ch}, token=self.token)[1]
        self.assertTrue(r["needsConfirm"]); self.assertTrue(any("นอกช่วงที่พบทั่วไป" in w for w in r["warnings"]))
        self.assertTrue(self.call("/api/admin/targets", {"action": "save", "changes": ch, "confirm": True}, token=self.token)[1]["success"])


class RuleEditor(ServerCase):
    GOOD = {"disable_builtin": [], "rules": [{"id": "t.ldl", "enabled": True, "problem": "Dyslipidemia", "level": "attention",
            "when": {"all": [{"param": "LDL", "op": ">=", "value": 160}, {"problem": "DM"}]},
            "patient": {"short": "LDL {LDL} สูงในผู้ที่เป็นเบาหวาน", "long": "ค่า LDL ของ{ท่าน}คือ {LDL} mg/dL สูงในผู้ที่เป็นเบาหวาน ควรปรึกษาแพทย์"}, "clinician": "LDL {LDL} + DM"}]}

    def setUp(self):
        from engine import custom_rules
        self.cr = custom_rules
        d = tempfile.mkdtemp(); self.old = custom_rules.PATH; custom_rules.PATH = os.path.join(d, "c.json")
        self.addCleanup(lambda: setattr(custom_rules, "PATH", self.old))
        self.token = self.login()[1]["token"]

    def rules(self, **kw):
        return self.call("/api/admin/rules", kw, token=self.token)

    def test_only_admin_may_use_it(self):
        self.call("/api/admin/users", {"action": "add", "username": "nurse2", "displayName": "n", "pin": "654321"}, token=self.token)
        t2 = self.login("nurse2", "654321")[1]["token"]
        for action in ("get", "try", "save"):
            self.assertEqual(self.call("/api/admin/rules", {"action": action, "data": self.GOOD, "note": "DM : FBS 100"}, token=t2)[0], 403)
        self.assertEqual(self.call("/api/admin/rules", {"action": "get"})[0], 401)

    def test_get_lists_choices_and_builtin_rules(self):
        code, d, _ = self.rules(action="get")
        self.assertEqual(code, 200)
        self.assertIn("LDL", [p["name"] for p in d["params"]]); self.assertIn("DM", d["problems"])
        self.assertIn("dm.hba1c.status", [b["id"] for b in d["builtin"]]); self.assertTrue(all(b["text"] for b in d["builtin"]))

    def test_try_does_not_save_and_shows_what_fires(self):
        code, d, _ = self.rules(action="try", data=self.GOOD, note="DM : FBS 100\nDLP : LDL 170")
        self.assertEqual(code, 200); self.assertIn("custom.t.ldl", d["fired"]); self.assertIn("LDL 170", d["result"])
        self.assertFalse(os.path.exists(self.cr.PATH))

    def test_save_validates_everything_and_never_writes_a_bad_file(self):
        bad = {"rules": [{**self.GOOD["rules"][0], "patient": {"short": "สูงเกิน 160", "long": "สูงเกิน 160"}}]}
        d = self.rules(action="save", data=bad)[1]
        self.assertFalse(d["success"]); self.assertTrue(d["errors"]); self.assertFalse(os.path.exists(self.cr.PATH))
        self.assertTrue(self.rules(action="save", data=self.GOOD)[1]["success"])
        self.assertEqual(json.load(open(self.cr.PATH, encoding="utf-8"))["rules"][0]["id"], "t.ldl")

    def test_rule_that_changes_an_example_needs_confirmation(self):
        from engine import golden
        old = golden.PATH; d = tempfile.mkdtemp(); golden.PATH = os.path.join(d, "g.json")
        self.addCleanup(lambda: setattr(golden, "PATH", old))
        golden.save([{"id": "g-1", "note": "DM : FBS 100\nDLP : LDL 170", "age": 60, "sex": "M", "confirmed": False}])
        r = self.rules(action="save", data=self.GOOD)[1]
        self.assertFalse(r["success"]); self.assertTrue(r["needsConfirm"]); self.assertFalse(os.path.exists(self.cr.PATH))
        self.assertTrue(any("สูงในผู้ที่เป็นเบาหวาน" in a["text"] for x in r["diffs"] for a in x["added"]))
        self.assertTrue(self.rules(action="save", data=self.GOOD, confirm=True)[1]["success"])

    def test_saved_rule_is_used_by_the_next_interpretation_without_restart_and_a_backup_is_kept(self):
        self.rules(action="save", data=self.GOOD)
        _, d, _ = self.call("/api/generate", {"note": "DM : FBS 100\nDLP : LDL 170", "age": 60, "sex": "M"}, token=self.token)
        self.assertIn("สูงในผู้ที่เป็นเบาหวาน", d["result"])
        self.rules(action="save", data={"disable_builtin": [], "rules": []})
        self.assertTrue(os.path.exists(self.cr.PATH + ".bak"))
        _, d, _ = self.call("/api/generate", {"note": "DM : FBS 100\nDLP : LDL 170", "age": 60, "sex": "M"}, token=self.token)
        self.assertNotIn("สูงในผู้ที่เป็นเบาหวาน", d["result"])

    def test_bad_inputs_are_polite(self):
        self.assertEqual(self.rules(action="nope")[0], 400)
        self.assertEqual(self.rules(action="try", data=self.GOOD, note="")[0], 400)
        for junk in (None, 5, "x", [], {"rules": "x"}):
            code, d, _ = self.rules(action="save", data=junk)
            self.assertEqual(code, 200); self.assertFalse(d["success"])


class Transport(ServerCase):
    def test_security_headers_and_page(self):
        code, _, h = self.call("/", method="GET")
        self.assertEqual(h["X-Frame-Options"], "DENY"); self.assertIn("default-src 'none'", h["Content-Security-Policy"])
        self.assertNotIn("googleapis", h["Content-Security-Policy"]); self.assertIn("default-src 'none'", h["Content-Security-Policy"])
        self.assertEqual(h["Cache-Control"], "no-store"); self.assertNotIn("Server", [k for k in h.keys() if "python" in h[k].lower()])
        self.assertNotIn("Access-Control-Allow-Origin", h)

    def test_the_page_is_served(self):
        code, d, h = self.call("/", method="GET")
        self.assertEqual(code, 200); self.assertIn("text/html", h["Content-Type"]); self.assertIn("Lab Interpreter", d["_raw"])

    def test_unknown_paths(self):
        self.assertEqual(self.call("/nope", method="GET")[0], 404)
        self.assertEqual(self.call("/api/nope", {})[0], 404)
        self.assertEqual(self.call("/../../etc/passwd", method="GET")[0], 404)
        self.assertEqual(self.call("/%2e%2e/%2e%2e/etc/passwd", method="GET")[0], 404)

    def test_default_bind_is_local_only(self):
        self.assertEqual(self.httpd.server_address[0], "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
