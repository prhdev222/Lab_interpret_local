#!/usr/bin/env python3
"""Local web server for the lab interpreter. Standard library only.

  python3 -m server.app                 # http://127.0.0.1:8741  (this machine only)
  python3 -m server.app --port 8123 --db data/app.db

Privacy by construction: a note is parsed in memory, the answer is returned, and nothing about it is written anywhere
(no database row, no log line, no file). The database holds user accounts and usage counters only.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from engine.lexicon import load_lexicon
from engine.parse_note import MAX_CHARS, collect_params, parse_note
from engine import learning_log
from engine.render import render_clinician, render_patient
from engine.rules import evaluate

from .db import DB, MIN_PIN

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC = os.path.join(ROOT, "public")
MAX_BODY = 64 * 1024
SEC_HEADERS = {
    "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer", "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                               "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
}


def make_handler(db: DB, quiet: bool = True):
    class Handler(BaseHTTPRequestHandler):
        server_version = "LabInterpreter"
        sys_version = ""

        def log_message(self, fmt, *args):            # never log request bodies; method + path + status only
            if not quiet:
                sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

        # ---- helpers
        def send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in SEC_HEADERS.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def js(self, data, code: int = 200):
            self.send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"))

        def err(self, code: int, msg: str):
            self.js({"error": msg}, code)

        def token(self) -> str:
            h = self.headers.get("Authorization", "")
            return h[7:] if h.startswith("Bearer ") else ""

        def user(self):
            return db.session_user(self.token())

        def body(self):
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                self.err(415, "ต้องส่งเป็น JSON"); return None
            try:
                n = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self.err(400, "ข้อมูลไม่ถูกต้อง"); return None
            if n > MAX_BODY:
                self.err(413, "ข้อมูลใหญ่เกินไป"); return None
            try:
                data = json.loads(self.rfile.read(n) or b"{}")
            except (json.JSONDecodeError, UnicodeDecodeError):
                self.err(400, "ข้อมูลไม่ถูกต้อง"); return None
            if not isinstance(data, dict):
                self.err(400, "ข้อมูลไม่ถูกต้อง"); return None
            return data

        def guarded(self, fn, *args):
            """An unexpected error must neither kill the connection silently nor leak details or note content into a log."""
            try:
                fn(*args)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as e:                                           # noqa: BLE001 - last line of defence
                sys.stderr.write(f"internal error: {type(e).__name__}\n")   # type only, never the message (it may echo input)
                try:
                    self.err(500, "เกิดข้อผิดพลาดภายในระบบ")
                except Exception:                                            # noqa: BLE001
                    pass

        def do_GET(self):
            self.guarded(self._get)

        def do_POST(self):
            self.guarded(self._post)

        # ---- GET: the page only
        def _get(self):
            path = self.path.split("?")[0]
            if path in ("/", "/index.html"):
                with open(os.path.join(PUBLIC, "index.html"), "rb") as f:
                    return self.send(200, f.read(), "text/html; charset=utf-8")
            if path == "/api/health":
                return self.js({"ok": True})
            if path == "/api/me":                                            # the page checks its saved session with GET on reload
                return self.me({})
            self.err(404, "ไม่พบหน้านี้")

        # ---- POST: the API
        def _post(self):
            path = self.path.split("?")[0]
            routes = {"/api/login": self.login, "/api/logout": self.logout, "/api/me": self.me, "/api/generate": self.generate,
                      "/api/admin/users": self.admin_users, "/api/admin/stats": self.admin_stats, "/api/admin/rules": self.admin_rules, "/api/admin/targets": self.admin_targets, "/api/admin/golden": self.admin_golden, "/api/learn": self.learn_example, "/api/admin/signoff": self.admin_signoff, "/api/admin/learning": self.admin_learning}
            fn = routes.get(path)
            if fn is None:
                return self.err(404, "ไม่พบ API นี้")
            data = self.body()
            if data is None:
                return
            fn(data)

        def login(self, d):
            username, pin = str(d.get("username", "")).strip(), str(d.get("pin", "")).strip()
            if not username or not pin:
                return self.err(400, "กรุณาใส่ชื่อผู้ใช้และ PIN")
            token, user, msg = db.login(username, pin)
            if token is None:
                return self.err(401, msg)
            self.js({"token": token, "user": {k: v for k, v in user.items() if k != "id"}})

        def logout(self, d):
            db.logout(self.token()); self.js({"success": True})

        def me(self, d):
            u = self.user()
            if not u:
                return self.err(401, "กรุณา login ก่อน")
            self.js({"user": {k: v for k, v in u.items() if k != "id"}})

        def generate(self, d):
            u = self.user()
            if not u:
                return self.err(401, "กรุณา login ก่อน")
            note = d.get("note", "")
            if not isinstance(note, str) or not note.strip():
                return self.err(400, "กรุณาใส่บันทึก")
            if len(note) > MAX_CHARS:
                return self.err(413, f"บันทึกยาวเกิน {MAX_CHARS} ตัวอักษร")
            pattern = d.get("pattern") if d.get("pattern") in ("simple", "standard", "detailed") else "standard"
            monk = bool(d.get("monkMode"))
            parsed = parse_note(note)
            result = evaluate(parsed, {"age": d.get("age"), "sex": d.get("sex"), "tcvr": d.get("tcvr")})
            params = collect_params(parsed)
            lex_tags = {k: v.get("label", k) for k, v in load_lexicon().data.get("tags", {}).items() if isinstance(v, dict)}
            table = [{"line": p["line_no"], "problem": p["name"], "known": p["known"], "source": p["source"],
                      "values": [{"param": v["param"], "series": v["series"], "unit": v["unit"], "kind": v.get("kind", "number"), "invalid": v["invalid"], "flags": v["flags"], "has_rules": v["has_rules"]} for v in p["values"]],
                      "tags": [{"label": lex_tags.get(t["id"], t["id"]), "value": t["value"], "source": t["source"]} for t in p.get("tags", [])],
                      "unparsed": p["unparsed"]} for p in parsed["problems"]]
            visits = [{"line": v["line_no"], "date_be": v["date_be"], "warning": v["date_warning"], "concepts": v["concepts"], "leftover": v["leftover"]} for v in parsed["visits"]]
            db.log_use(u["id"], pattern, monk)                                  # counters only; no note content
            self.js({"result": render_patient(result, pattern, monk), "clinician": render_clinician(result), "table": table, "visits": visits,
                     "unparsed_lines": parsed["unparsed_lines"], "warnings": result["warnings"], "status": result["targets_status"],
                     "interpreted": len(result["findings"]), "params_read": len(params), "learning": learning_log.status()["enabled"]})

        @staticmethod
        def _describe_row(r):
            if r["k"] == "known": return f"ค่าที่รู้จัก {r['p']} = {r['v']:g} (บรรทัด {r['g']})"
            if r["k"] == "unk": return f"คำย่อที่ไม่รู้จัก '{r['t']}' = {r['v']:g} (บรรทัด {r['g']}; ในบรรทัดมี {', '.join(r['with']) or '-'})"
            if r["k"] == "word": return f"คำที่สะกดใกล้อาการที่รู้จัก '{r['t']}'"
            return f"ชื่อโรคที่ไม่รู้จัก '{r['t']}' (ในบรรทัดมี {', '.join(r['with']) or '-'})"

        def learn_example(self, d):
            """A doctor saves ONE example for learning, after seeing exactly what would be stored. Needs the log to be switched on by an admin."""
            if not self.user():
                return self.err(401, "กรุณา login ก่อน")
            action = d.get("action")
            if action == "status":
                return self.js({"enabled": learning_log.status()["enabled"]})
            if action not in ("preview", "save"):
                return self.err(400, "action ไม่ถูกต้อง")
            if not learning_log.status()["enabled"]:
                return self.err(403, "ยังไม่ได้เปิดการเก็บตัวอย่าง (admin เปิดได้ที่ปุ่ม 🧠)")
            note = d.get("note", "")
            if not isinstance(note, str) or not note.strip() or len(note) > MAX_CHARS:
                return self.err(400, "กรุณาใส่บันทึก")
            from tools.learn_terms import extract_rows
            rows = extract_rows(note)
            if action == "preview":
                return self.js({"rows": [self._describe_row(r) for r in rows], "count": len(rows)})
            return self.js({"success": True, "stored": learning_log.add_rows(rows)})

        def admin_signoff(self, d):
            """Sign-off of the reviewed rules (admin). The status falls back to DRAFT by itself if anything reviewed is edited later."""
            u = self._admin()
            if not u:
                return
            from engine import signoff
            action = d.get("action")
            if action == "status":
                c = signoff.checklist()
                return self.js({"state": signoff.state(), "status": signoff.effective_status(), "blockers": signoff.blockers(c), "examples": c["examples"],
                                "history": signoff.history(), "phrase": signoff.PHRASE})
            if action == "sign":
                ok, errors = signoff.sign(d.get("name"), d.get("phrase"))
                if ok:
                    import subprocess
                    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "dump_rules.py")], cwd=ROOT, capture_output=True, timeout=60)
                return self.js({"success": ok, "errors": errors})
            if action == "revoke":
                signoff.revoke(str(u.get("displayName") or u.get("username") or "")); return self.js({"success": True})
            self.err(400, "action ไม่ถูกต้อง")

        def admin_learning(self, d):
            if not self._admin():
                return
            action = d.get("action")
            if action == "status":
                return self.js(learning_log.status())
            if action == "set":
                learning_log.set_enabled(bool(d.get("enabled"))); return self.js(learning_log.status())
            if action == "export":
                return self.js(learning_log.export())
            if action == "clear":
                learning_log.clear(); return self.js(learning_log.status())
            if action in ("suggest", "apply"):
                from tools import apply_terms, learn_terms
                try:
                    min_count = max(1, min(50, int(d.get("minCount", 3))))
                except (TypeError, ValueError):
                    return self.err(400, "minCount ไม่ถูกต้อง")
                suggestions = learn_terms.learn_rows(learning_log.export()["rows"], min_count)       # always recomputed here: the page cannot inject its own words
                if action == "suggest":
                    return self.js({"suggestions": suggestions, "rows": learning_log.status()["rows"], "minCount": min_count})
                want = d.get("selected")
                if not isinstance(want, list) or not want:
                    return self.err(400, "ยังไม่ได้เลือกข้อ")
                keys = {(w.get("kind"), w.get("term"), w.get("target")) for w in want if isinstance(w, dict)}
                chosen = [s for s in suggestions if (s["kind"], s["term"], s["target"]) in keys and s["kind"] in apply_terms.KINDS]
                if not chosen:
                    return self.err(400, "ข้อที่เลือกไม่ตรงกับข้อเสนอปัจจุบัน (ข้อมูลอาจเปลี่ยน) ให้สร้างข้อเสนอใหม่")
                return self.js(apply_terms.apply_and_write(chosen))
            self.err(400, "action ไม่ถูกต้อง")

        def admin_rules(self, d):
            """Rule editor (admin only). get = current file + choices; try = evaluate a draft on a note; save = validate everything, then write."""
            if not self._admin():
                return
            from engine import custom_rules
            from engine.lexicon import load_lexicon
            from engine.rules import RULES, load_targets
            ids = {r["id"] for r in RULES}
            action = d.get("action")
            if action == "get":
                lex, t = load_lexicon(), load_targets()
                try:
                    with open(custom_rules.PATH, encoding="utf-8") as f:
                        data = json.load(f)
                except (OSError, ValueError):
                    data = {"disable_builtin": [], "rules": []}
                _, errors, _ = custom_rules.validate(data, ids)
                for r in data.get("rules", []) if isinstance(data, dict) else []:
                    if isinstance(r, dict) and isinstance(r.get("when"), dict):
                        try: r["_describe"] = custom_rules.describe(r["when"])
                        except Exception: r["_describe"] = "(อ่านเงื่อนไขไม่ได้ แก้ในไฟล์)"
                params = [{"name": n, "unit": sp.get("unit", ""), "kind": sp.get("kind", "number")} for n, sp in lex.params.items() if sp.get("kind") != "range"]
                concepts = [{"id": "smoking", "label": "การสูบบุหรี่"}] + [{"id": k, "label": v["label"]} for k, v in lex.concepts.items()]
                builtin = [{"id": r["id"], "problem": r["problem"], "text": r["describe"](t)} for r in RULES]
                return self.js({"data": data, "errors": errors, "builtin": builtin, "params": params, "concepts": concepts,
                                "problems": sorted(set(lex.problem_alias.values())), "limits": {"rules": custom_rules.MAX_RULES}})
            draft = d.get("data")
            if action == "try":
                note = d.get("note", "")
                if not isinstance(note, str) or not note.strip() or len(note) > MAX_CHARS:
                    return self.err(400, "กรุณาใส่บันทึกตัวอย่าง")
                _, errors, _ = custom_rules.validate(draft, ids)
                result = evaluate(parse_note(note), {"age": d.get("age"), "sex": d.get("sex")}, custom_override=draft)
                fired = [f["id"] for f in result["findings"] + result["clinician_notes"] if f.get("custom")]
                return self.js({"errors": errors, "fired": fired, "result": render_patient(result, "standard", bool(d.get("monkMode"))), "clinician": render_clinician(result)})
            if action == "save":
                from engine import golden
                _, errors, _ = custom_rules.validate(draft, ids)
                if errors:
                    return self.js({"success": False, "errors": errors})
                diffs = golden.compare({}, {"custom_override": draft})[:60]
                violated = golden.approved_violations({"custom_override": draft})
                if (diffs or violated) and not d.get("confirm"):
                    return self.js({"success": False, "needsConfirm": True, "warnings": [], "diffs": diffs, "violated": violated, "errors": []})
                ok, errors = custom_rules.save(draft, ids)
                if not ok:
                    return self.js({"success": False, "errors": errors})
                return self.js({"success": True})
            self.err(400, "action ไม่ถูกต้อง")

        def admin_targets(self, d):
            """Threshold editor (admin only): get = editable values with Thai labels; save = {path: value} validated as a whole, then written."""
            if not self._admin():
                return
            from engine import targets_edit as te
            action = d.get("action")
            if action == "get":
                with open(te.PATH, encoding="utf-8") as f:
                    t = json.load(f)
                rows = [{"path": p, "kind": k, "value": v, "group": p.rsplit(".", 1)[0] if "." in p else "", "key": p.rsplit(".", 1)[-1],
                         "label": te.KEYS.get(p.rsplit(".", 1)[-1], p.rsplit(".", 1)[-1])} for p, k, v in te.leaves(t)]
                return self.js({"rows": rows, "groups": te.GROUPS, "status": t["_meta"]["status"], "lastEdit": t["_meta"].get("last_web_edit")})
            if action == "save":
                from engine import golden
                from engine.rules import load_targets
                with open(te.PATH, encoding="utf-8") as f:
                    current = json.load(f)
                proposed, errors = te.apply_changes(current, d.get("changes"))
                if errors:
                    return self.js({"success": False, "errors": errors, "changed": []})
                changed = [p for p, _, v in te.leaves(proposed) if te._get(current, p) != v]
                warns = te.warnings(current, proposed, changed)
                diffs = golden.compare({}, {"targets": proposed})[:60]
                violated = golden.approved_violations({"targets": proposed})
                if (warns or diffs or violated) and not d.get("confirm"):
                    return self.js({"success": False, "needsConfirm": True, "warnings": warns, "diffs": diffs, "violated": violated, "errors": [], "changed": changed})
                ok, errors, changed = te.save(d.get("changes"))
                if ok:
                    import subprocess                                          # keep the physician sign-off sheet in step with the numbers
                    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "dump_rules.py")], cwd=ROOT, capture_output=True, timeout=60)
                return self.js({"success": ok, "errors": errors, "changed": changed})
            self.err(400, "action ไม่ถูกต้อง")

        def admin_golden(self, d):
            """Example notes (synthetic only) used as a safety net: list with current output / add / confirm / delete."""
            if not self._admin():
                return
            from engine import golden
            cases = golden.load()
            action = d.get("action")
            if action == "list":
                out = []
                for c in cases:
                    snap = golden.snapshot(c)
                    res = evaluate(parse_note(c["note"]), {"age": c.get("age"), "sex": c.get("sex")})
                    out.append({"id": c["id"], "note": c["note"], "age": c.get("age"), "sex": c.get("sex"), "confirmed": bool(c.get("confirmed")),
                                "changedSinceConfirmed": bool(c.get("confirmed") and isinstance(c.get("approved"), dict) and golden.diff_snapshots(c["approved"], snap)),
                                "patient": render_patient(res, "standard", False), "clinician": [n["text"] for n in render_clinician(res)]})
                return self.js({"cases": out, "max": golden.MAX_CASES})
            if action == "add":
                if len(cases) >= golden.MAX_CASES:
                    return self.err(400, f"มีตัวอย่างครบ {golden.MAX_CASES} ข้อแล้ว")
                case, msg = golden.validate_new(d.get("note"), d.get("age"), d.get("sex"))
                if msg:
                    return self.err(400, msg)
                case["id"], case["confirmed"] = golden.next_id(cases), False
                cases.append(case); golden.save(cases)
                return self.js({"success": True, "id": case["id"]})
            target = next((c for c in cases if c.get("id") == d.get("id")), None)
            if action in ("confirm", "delete") and target is None:
                return self.err(404, "ไม่พบตัวอย่างนี้")
            if action == "confirm":
                if d.get("confirmed"):
                    target["confirmed"], target["approved"] = True, golden.snapshot(target)         # remembers WHAT was confirmed
                else:
                    target["confirmed"] = False; target.pop("approved", None)
                golden.save(cases); return self.js({"success": True})
            if action == "delete":
                golden.save([c for c in cases if c is not target]); return self.js({"success": True})
            self.err(400, "action ไม่ถูกต้อง")

        def _admin(self):
            u = self.user()
            if not u:
                self.err(401, "กรุณา login ก่อน"); return None
            if not u["isAdmin"]:
                self.err(403, "ไม่มีสิทธิ์ admin"); return None
            return u

        def admin_users(self, d):
            u = self._admin()
            if not u:
                return
            action = d.get("action")
            try:
                if action == "list":
                    return self.js({"users": db.list_users()})
                if action == "add":
                    username, display, pin = str(d.get("username", "")).strip(), str(d.get("displayName", "")).strip(), str(d.get("pin", "")).strip()
                    if not (username and display and pin):
                        return self.err(400, "ข้อมูลไม่ครบ")
                    if not re.fullmatch(r"[A-Za-z0-9_.\-]{2,32}", username):
                        return self.err(400, "ชื่อผู้ใช้ใช้ได้เฉพาะ a-z, 0-9, _ . - ยาว 2-32 ตัว")
                    if len(display) > 60 or any(ord(c) < 32 for c in display):
                        return self.err(400, "ชื่อแสดงยาวเกิน 60 ตัวอักษรหรือมีอักขระควบคุม")
                    role = d.get("role") if d.get("role") in ("doctor", "nurse", "pharmacist", "staff") else "staff"
                    db.add_user(username, pin, display, role)
                    return self.js({"success": True})
                if action == "delete":
                    db.delete_user(int(d.get("userId"))); return self.js({"success": True})
                if action == "reset_pin":
                    if not db.check_pin(u["id"], str(d.get("confirmPin", ""))):
                        return self.err(403, "PIN ของ admin ไม่ถูกต้อง")
                    db.set_pin(int(d.get("userId")), str(d.get("pin", ""))); return self.js({"success": True})
                if action == "clear_sessions":
                    db.clear_sessions(self.token()); return self.js({"success": True, "message": "ล้าง sessions ทั้งหมดแล้ว (ยกเว้นของคุณ)"})
                if action == "clear_logs":
                    db.clear_logs(); return self.js({"success": True, "message": "ล้าง usage log ทั้งหมดแล้ว"})
            except (ValueError, TypeError) as e:
                return self.err(400, str(e))
            self.err(400, "unknown action")

        def admin_stats(self, d):
            if self._admin():
                self.js(db.stats())

    return Handler


def serve(host: str, port: int, db_path: str, quiet: bool = True) -> tuple[ThreadingHTTPServer, DB]:
    db = DB(db_path)
    if db.user_count() == 0:
        pin = "".join(secrets.choice("0123456789") for _ in range(8))
        db.add_user("admin", pin, "ผู้ดูแลระบบ", "doctor", is_admin=True)
        print(f"\n  สร้างบัญชีผู้ดูแลครั้งแรก:  ชื่อผู้ใช้ admin   PIN {pin}\n  (แสดงครั้งเดียวเท่านั้น จดไว้แล้วเปลี่ยนในหน้า 'จัดการผู้ใช้' หรือใช้ python3 manage.py reset-pin admin)\n", flush=True)
    httpd = ThreadingHTTPServer((host, port), make_handler(db, quiet))
    return httpd, db


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1", help="default 127.0.0.1 = this machine only")
    ap.add_argument("--port", type=int, default=8741)
    ap.add_argument("--db", default=os.path.join(ROOT, "data", "app.db"))
    ap.add_argument("--verbose", action="store_true", help="log method/path/status (never bodies)")
    a = ap.parse_args()
    httpd, _ = serve(a.host, a.port, a.db, quiet=not a.verbose)
    print(f"Lab Interpreter: http://{a.host}:{a.port}/   (Ctrl+C เพื่อหยุด)", flush=True)
    if a.host not in ("127.0.0.1", "localhost", "::1"):
        print("  คำเตือน: เปิดให้เครื่องอื่นในเครือข่ายเข้าถึงได้ ควรใช้ HTTPS และให้ IT ตรวจสอบก่อน", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
