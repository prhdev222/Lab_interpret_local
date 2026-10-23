#!/usr/bin/env python3
"""Maintenance commands that work even if you forgot the admin PIN (needs access to the machine).

  python3 manage.py reset-pin admin         # asks for a new PIN
  python3 manage.py add-user NAME "Display name" [doctor|nurse|pharmacist|staff]
  python3 manage.py list-users
"""
import getpass
import os
import sys

from server.db import DB, MIN_PIN

DB_PATH = os.environ.get("LAB_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "app.db"))


def ask_pin() -> str:
    a, b = getpass.getpass(f"PIN ใหม่ (อย่างน้อย {MIN_PIN} หลัก): "), getpass.getpass("พิมพ์ซ้ำ: ")
    if a != b:
        sys.exit("PIN ไม่ตรงกัน")
    return a


def main(argv):
    db = DB(DB_PATH)
    if len(argv) >= 2 and argv[0] == "reset-pin":
        row = db.con.execute("SELECT id FROM users WHERE username=?", (argv[1],)).fetchone()
        if not row:
            sys.exit("ไม่พบผู้ใช้")
        db.set_pin(row["id"], ask_pin()); print("เปลี่ยน PIN แล้ว (session เดิมถูกล้าง)")
    elif len(argv) >= 3 and argv[0] == "add-user":
        db.add_user(argv[1], ask_pin(), argv[2], argv[3] if len(argv) > 3 else "staff"); print("เพิ่มผู้ใช้แล้ว")
    elif argv[:1] == ["list-users"]:
        for u in db.list_users():
            print(u["id"], u["username"], u["display_name"], u["role"], "admin" if u["is_admin"] else "")
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
