#!/usr/bin/env python3
"""Validates data/custom_rules.json and optionally dry-runs it on a note.

  python3 tools/check_rules.py
  python3 tools/check_rules.py --try "DM : HbA1c 9\nDLP : LDL 170" --age 60 --sex M      (\\n = new line)
Nothing is written. Exit code 1 if any rule is invalid, so you can use it before saving."""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import custom_rules  # noqa: E402
from engine.parse_note import parse_note  # noqa: E402
from engine.rules import RULES, evaluate  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", default=custom_rules.PATH); ap.add_argument("--try", dest="note"); ap.add_argument("--age"); ap.add_argument("--sex")
    a = ap.parse_args()
    try:
        data = json.load(open(a.file, encoding="utf-8"))
    except (OSError, ValueError) as e:
        sys.exit(f"อ่านไฟล์ไม่ได้: {e}")
    good, errors, disabled = custom_rules.validate(data, {r["id"] for r in RULES})
    total = len(data.get("rules", [])) if isinstance(data, dict) else 0
    print(f"กฎที่เพิ่มเอง: {total} ข้อ · ใช้งาน (enabled) และผ่านการตรวจ: {len(good)} · ปิดกฎมาตรฐาน: {len(disabled)} {disabled or ''}")
    for r in good:
        print(f"  ✓ {r['id']:<28} ถ้า {custom_rules.describe(r['when'])}  → {r['level']}")
    for e in errors:
        print(f"  ✗ {e}")
    if a.note:
        res = evaluate(parse_note(a.note.replace("\\n", "\n")), {"age": a.age, "sex": a.sex})
        fired = [f["id"] for f in res["findings"] + res["clinician_notes"] if f.get("custom")]
        print("\nกฎที่เพิ่มเองที่ทำงานกับบันทึกนี้:", fired or "ไม่มี")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
