#!/usr/bin/env python3
"""Builds the answer key (gold file) that eval/evaluate_parser.py needs, from YOUR de-identified notes, on YOUR machine.

  python3 tools/make_gold.py my_notes.txt --out my_gold.jsonl           (notes separated by a blank line, or one per line)
  python3 eval/evaluate_parser.py --gold my_gold.jsonl                   (then measure)

For each note it shows what the parser read; a doctor presses Enter if that is right, or fixes it:
  p NAME v1 v2 ...     set a parameter, oldest value first (blood pressure as 150/90)       e.g.  p HbA1c 9 7.5      p BP 150/90
  d NAME               the parameter is not really in the note (remove it)                  e.g.  d Cr
  c ID=value           set a symptom/habit of the latest dated line (present/absent, or smoking: current/former/never/not_smoking)   e.g.  c dizziness=present
  dc ID                remove a symptom/habit
  s                    skip this note        q   save and quit        ?   help
The gold file contains note text: it is patient-derived data. Use de-identified notes only, keep it on this machine, never commit or upload it.
Re-running with the same --out continues where you stopped.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.lexicon import load_lexicon  # noqa: E402
from engine.parse_note import collect_params, latest_visit, parse_note  # noqa: E402
from tools.learn_terms import split_notes  # noqa: E402


def draft_expected(note: str) -> dict:
    """What the parser currently reads (the doctor corrects this; it is a starting point, not the truth)."""
    parsed = parse_note(note)
    visit = latest_visit(parsed)
    return {"params": {k: v["series"] for k, v in collect_params(parsed).items() if not v["invalid"]},
            "concepts": {c["id"]: c["value"] for c in (visit["concepts"] if visit else [])}}


def _num(tok: str):
    m = re.fullmatch(r"(\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)", tok)
    if m:
        return [float(m[1]), float(m[2])]
    return float(tok)


def apply_command(exp: dict, cmd: str, lex=None) -> str | None:
    """Applies one correction to `exp` in place. Returns an error message, or None if it worked."""
    lex = lex or load_lexicon()
    parts = cmd.split()
    if not parts:
        return None
    op, args = parts[0].lower(), parts[1:]
    try:
        if op == "p" and len(args) >= 2:
            name = lex.param_alias.get(re.sub(r"\s+", "", args[0].lower()))
            if not name: return f"ไม่รู้จักค่า '{args[0]}'"
            exp["params"][name] = [_num(a) for a in args[1:]]
        elif op == "d" and len(args) == 1:
            name = lex.param_alias.get(re.sub(r"\s+", "", args[0].lower()), args[0])
            if name not in exp["params"]: return f"ไม่มีค่า {name} ให้ลบ"
            del exp["params"][name]
        elif op == "c" and len(args) == 1 and "=" in args[0]:
            cid, val = args[0].split("=", 1)
            ok = {"present", "absent"} if cid != "smoking" else {"current", "former", "never", "not_smoking"}
            if cid != "smoking" and cid not in lex.concepts: return f"ไม่รู้จักอาการ '{cid}' (ดู data/lexicon.json → concepts)"
            if val not in ok: return f"ค่าต้องเป็นหนึ่งใน {sorted(ok)}"
            exp["concepts"][cid] = val
        elif op == "dc" and len(args) == 1:
            if args[0] not in exp["concepts"]: return f"ไม่มี {args[0]} ให้ลบ"
            del exp["concepts"][args[0]]
        else:
            return "คำสั่งไม่ถูกต้อง (พิมพ์ ? ดูวิธีใช้)"
    except ValueError:
        return "ตัวเลขไม่ถูกต้อง"
    return None


def show(exp: dict) -> str:
    ps = "\n".join(f"    {k}: {' -> '.join('/'.join(f'{x:g}' for x in v) if isinstance(v, list) else f'{v:g}' for v in vals)}" for k, vals in exp["params"].items()) or "    (ไม่มี)"
    cs = ", ".join(f"{k}={v}" for k, v in exp["concepts"].items()) or "(ไม่มี)"
    return f"  ระบบอ่านได้:\n{ps}\n  อาการ/พฤติกรรมวันล่าสุด: {cs}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file"); ap.add_argument("--out", default="my_gold.jsonl")
    a = ap.parse_args()
    notes = split_notes(open(a.file, encoding="utf-8").read())
    done = 0
    if os.path.exists(a.out):
        done = sum(1 for l in open(a.out, encoding="utf-8") if l.strip())
        print(f"พบ {a.out} มี {done} ข้อแล้ว ทำต่อจากข้อที่ {done + 1} (ข้อที่ข้ามไม่นับ)")
    print("⚠ ไฟล์เฉลยมีข้อความบันทึก ใช้เฉพาะบันทึกที่ตัดข้อมูลระบุตัวตนแล้ว เก็บในเครื่องนี้เท่านั้น ห้าม commit/อัปโหลด\n")
    with open(a.out, "a", encoding="utf-8") as out:
        for i, note in enumerate(notes[done:], done + 1):
            exp = draft_expected(note)
            while True:
                print(f"\n── บันทึกที่ {i}/{len(notes)} ──\n{note}\n{show(exp)}")
                cmd = input("Enter=ถูกต้อง | p/d/c/dc แก้ | s ข้าม | q จบ | ? ช่วยเหลือ > ").strip()
                if cmd in ("", "ok"):
                    out.write(json.dumps({"note": note, "expected": exp}, ensure_ascii=False) + "\n"); out.flush(); break
                if cmd == "s": break
                if cmd == "q": print(f"บันทึกแล้ว: {a.out}"); return
                if cmd == "?": print(__doc__); continue
                err = apply_command(exp, cmd)
                if err: print("  ✗", err)
    print(f"\nเสร็จ: {a.out}\nวัดความแม่นยำ: python3 eval/evaluate_parser.py --gold {a.out}")


if __name__ == "__main__":
    main()
