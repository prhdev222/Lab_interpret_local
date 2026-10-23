#!/usr/bin/env python3
"""Writes docs/RULES_REVIEW.md: everything a physician must read and approve, generated from the live rules and data files,
so the document cannot drift from what the program actually does.   python3 tools/dump_rules.py"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine.rules import RULES, load_targets  # noqa: E402

DATA = os.path.join(ROOT, "data")
tpl = json.load(open(os.path.join(DATA, "templates.json"), encoding="utf-8"))
gloss = json.load(open(os.path.join(DATA, "glossary.json"), encoding="utf-8"))
t = load_targets()


def flat(d, prefix=""):
    for k, v in d.items():
        if k.startswith("_"): continue
        if isinstance(v, dict) and not {"source", "needs_citation"} >= set(v) - set(v):
            yield from flat(v, f"{prefix}{k}.")
        else:
            yield f"{prefix}{k}", v


L = []
add = L.append
add("# เอกสารตรวจกฎ (สร้างอัตโนมัติ จากกฎและไฟล์ข้อมูลที่รันอยู่จริง)\n")
from engine import signoff  # noqa: E402
add(f"สถานะ: **{signoff.effective_status(t['_meta']['status'])}**  ·  เวอร์ชันข้อมูล: {t['_meta']['version']}\n")
add("> ห้ามใช้กับผู้ป่วยจริงจนกว่าแพทย์จะตรวจทุกข้อด้านล่างและลงนามรับรอง แก้เกณฑ์ที่ `data/targets.json` แก้ถ้อยคำที่ `data/templates.json` แก้คำสงฆ์ที่ `data/glossary.json` แล้วรัน `python3 tools/dump_rules.py` เพื่อสร้างเอกสารนี้ใหม่ และ `python3 -m unittest discover -s tests -t .` เพื่อตรวจว่าไม่มีอะไรพัง\n")

add("## 1. คำถามที่ต้องให้แพทย์ตัดสินใจ\n")
for q in [
    "**ค่าที่ขอบเกณฑ์:** ระบบใช้ \"ต่ำกว่า\" (<) เสมอ เช่น เป้า BP < 130/80 แล้วค่าล่าง 80 ถือว่า **ยังไม่ถึงเป้าหมาย** (ข้อความใช้คำว่า \"ยังไม่ถึงเป้าหมาย\" ไม่ใช่ \"สูงกว่า\") เห็นด้วยหรือไม่",
    "**BP เป้าหมายเข้มขึ้นเป็น < 130/80 เมื่อบันทึกมี DM หรือ CKD** (ทั้ง BP คลินิกและที่บ้าน) ใช้ตามนี้ไหม หรือใช้ < 140/90 เสมอ",
    "**เป้า HbA1c เดียว (≤ 7.0%) สำหรับทุกคน** ผู้สูงอายุ/เปราะบางมักใช้เป้าหลวมกว่า ต้องการให้มีเป้าตามกลุ่มหรือกรอกเป้าเป็นรายคนหรือไม่",
    "**ความดันที่บ้าน 135/85 (ทั่วไป)** และเกณฑ์ white-coat / masked ใช้ค่าตามที่ตั้งไว้ถูกหรือไม่",
    "**HbA1c ลดรวม ≥ 2 จุด** เป็นเกณฑ์เตือนแพทย์เรื่องน้ำตาลต่ำ (ไม่ทราบช่วงเวลาระหว่างค่า เพราะบันทึกไม่มีวันที่ต่อค่า) เหมาะสมหรือไม่",
    "**ข้อสังเกต 'DM + เวียนศีรษะ/ใจสั่น + รับประทานได้น้อยลง'** ถ้อยคำเหมาะสมหรือไม่ (ข้อความนี้แสดงเฉพาะแพทย์ ไม่พิมพ์ให้ผู้ป่วย)",
    "**ค่า eGFR ที่ระบบคำนวณเอง** (เมื่อไม่มี eGFR แต่มี Cr + อายุ + เพศ) ใช้ CKD-EPI 2021 ถูกต้องตามที่ รพ. ใช้หรือไม่ และข้อความระบุว่า \"(คำนวณโดยระบบ)\"",
    "**BMI เกณฑ์คนเอเชีย** (23 / 25 / 30) และ **น้ำหนักเปลี่ยน ≥ 5%** ถือว่ามีนัย ใช้ได้หรือไม่",
    "**คำสงฆ์ในไฟล์ glossary.json** (เช่น \"อดอาหาร\" → \"งดภัตตาหาร\", \"ออกกำลังกาย\" → \"เดินจงกรม\", \"น้ำดื่ม\" → \"น้ำปานะ\") และข้อความวิถีสงฆ์สองข้อ ตั้งต้นจากรายการในรีโปเดิมของแพทย์ ต้องให้ผู้ที่เชี่ยวชาญตรวจ",
    f"**เบอร์สายด่วนเลิกบุหรี่ ({t['lifestyle']['quitline']})** ตรวจสอบว่ายังใช้ได้ก่อนใช้งานจริง",
    "**คำแนะนำทั่วไปต่อโรค** (หัวข้อ 4) ครบและเหมาะสมหรือไม่ มีอะไรที่ไม่ควรมีหรือขาดไป",
    f"**เป้า LDL: {t['dlp']['ldl']['goal_default']} (ทั่วไป) และ {t['dlp']['ldl']['goal_dm_or_ckd']} (เมื่อบันทึกมี DM/CKD)** ระบบยังไม่รู้ว่าผู้ป่วยมี ASCVD หรือไม่ (เป้าจะต่ำกว่านี้) ต้องการช่องให้ระบุความเสี่ยงหรือไม่ · เกณฑ์ TG / HDL / TC ตามตารางหัวข้อ 3 ใช้ได้หรือไม่",
    "**Thai CV risk:** ระบบ **ไม่คำนวณ** (สมการไม่ได้เผยแพร่ในแหล่งที่ตรวจสอบได้ และเงื่อนไขของเครื่องมือรามาธิบดีจำกัดการใช้) มีเพียงช่องให้กรอกค่า % ที่ได้จากเครื่องมือเอง (ใช้ออฟไลน์ได้) แบ่งกลุ่ม <10 / 10-<20 / 20-<30 / ≥30 และมีรายการตรวจว่าบันทึกมีข้อมูลครบไหม (อายุ เพศ สูบบุหรี่ SBP และ TC/BMI/รอบเอว อย่างน้อยหนึ่ง; เบาหวานถือว่าไม่เป็นถ้าไม่เขียน DM) ตรวจรายการนี้กับเครื่องมือเวอร์ชันที่ใช้จริง และเกณฑ์ขอบเขต 30 · ถ้าต้องการให้คำนวณเอง ต้องมีสมการต้นฉบับ/ใบอนุญาต และกรณีทดสอบจากเครื่องมือจริง",
    f"**DN / KDIGO:** UACR (หรือ urine microalbumin UMA ที่ **ต้องเขียนหน่วย mg/g**) A1 < {t['ckd']['albuminuria']['a2_from']}, A2 ถึง {t['ckd']['albuminuria']['a3_above']}, A3 มากกว่า · ตารางความเสี่ยง KDIGO (G x A) แสดงเฉพาะแพทย์ · ข้อความ 'ต้องตรวจซ้ำเพื่อยืนยัน' เหมาะสมหรือไม่",
    "**U/S KUB (ในบรรทัด CKD):** คำที่ระบบรู้อยู่ใน `data/lexicon.json` หมวด tags (echo เพิ่ม, ไตเล็ก, hydronephrosis, นิ่ว, ก้อน, cyst, ไม่เท่ากัน, ปกติ) 'no hydro' = ไม่มี · ก้อน = ระดับแจ้งเตือน ถ้อยคำเหมาะสมหรือไม่ มีคำที่ใช้บ่อยแต่ขาดไปหรือไม่",
    "**DR:** ระดับ (no DR, NPDR mild/moderate/severe, PDR, DME, เคยรักษา) อ่านจากข้อความในบรรทัด `DR :` · ระบบไม่บอกความถี่ในการตรวจตา และเตือนแพทย์เมื่อ DM ไม่มีผลตรวจตาในบันทึก",
    f"**MAFLD:** ค่าสูงสุดปกติ ALT/AST ตั้งต้น {t['mafld']['enzymes']['uln']} U/L (ควรใช้ค่าของห้องแล็บ รพ. และอาจแยกเพศ) · FIB-4 คำนวณเอง เกณฑ์ {t['mafld']['fib4']['low_below']} / {t['mafld']['fib4']['high_above']} (อายุ ≥ {t['mafld']['fib4']['older_age']} ใช้ {t['mafld']['fib4']['low_below_older']}) ไม่ใช้ถ้าอายุ < {t['mafld']['fib4']['min_age']} · Fibroscan LSM {t['mafld']['lsm']['low_below']} / {t['mafld']['lsm']['high_from']} kPa และ CAP {t['mafld']['cap']['s1_from']} / {t['mafld']['cap']['s2_from']} / {t['mafld']['cap']['s3_from']} dB/m (เกณฑ์ต่างกันตามรุ่นเครื่อง/probe และงานวิจัย) ใช้ชุดไหน · ระบบไม่ทราบคุณภาพการตรวจ Fibroscan",
    f"**CAD / Stroke:** เป้า LDL เมื่อเป็น CAD หรือ Stroke ชนิดขาดเลือดใช้ {t['dlp']['ldl']['goal_ascvd']} (Stroke ที่ไม่ระบุชนิดหรือเลือดออกจะ **ไม่** ใช้) · เป้า BP < 130/80 เมื่อมี CAD/Stroke/DN · เตือนแพทย์เมื่อบันทึกไม่ระบุ statin/ยาต้านเกล็ดเลือด (ไม่ได้แปลว่าไม่ได้รับ) · EF ≤ {t['cad']['lvef']['reduced_to']} ลดลง, ≤ {t['cad']['lvef']['mild_to']} ลดลงเล็กน้อย · mRS แสดงเฉพาะแพทย์",
    f"**COPD / Asthma:** GOLD 1-4 ตาม FEV1 % ({t['copd']['gold']['g1_from']}/{t['copd']['gold']['g2_from']}/{t['copd']['gold']['g3_from']}) และต้องมี FEV1/FVC < {t['copd']['gold']['obstruction_below']} · กลุ่ม A/B/E (mMRC ≥ {t['copd']['symptoms']['mmrc_high_from']} หรือ CAT ≥ {t['copd']['symptoms']['cat_high_from']}; E = กำเริบ ≥ {t['copd']['exac']['frequent_from']} หรือนอน รพ. ≥ {t['copd']['exac']['hosp_from']}) แสดงเฉพาะแพทย์ · SpO2 ใน COPD ไม่บอกผู้ป่วยว่าต่ำ ยกเว้น ≤ {t['spo2']['copd_alert_to']}% · ACT {t['asthma']['act']['good_from']}/{t['asthma']['act']['partly_from']} และโซน PEF {t['asthma']['pef']['green_from']}/{t['asthma']['pef']['yellow_from']}% ใช้ได้หรือไม่",
    f"**รอบเอวคนเอเชีย** ชาย ≥ {t['obesity']['waist']['male_from']} / หญิง ≥ {t['obesity']['waist']['female_from']} ซม. และ BMI คำนวณจาก BW + Height เมื่อไม่มี BMI (ระบุว่า 'คำนวณโดยระบบ')",
    "**ภาวะซีด:** ใช้เกณฑ์ WHO แยกตามเพศ (ชาย < 13, หญิง < 12) และ **ไม่แปล Hb ถ้าไม่ระบุเพศ** ยังไม่แยกตั้งครรภ์/ผู้สูงอายุ/ผู้ป่วย CKD ต้องการหรือไม่ · ดัชนี Mentzer และการตรวจความสอดคล้อง MCV, Hct, RBC แสดงเฉพาะแพทย์",
    f"**วาฟาริน/INR:** ถ้าไม่ระบุ `goal` ใช้เป้า {t['warfarin']['default_goal'][0]}-{t['warfarin']['default_goal'][1]} แล้วบอกแพทย์ · INR ≥ {t['warfarin']['alert_above']} (และสูงกว่าเป้า) ถือว่าสูงมาก · ระบบ **ไม่แนะนำขนาดยาและไม่ให้ผู้ป่วยปรับยา** · ข้อสังเกต 'รับประทานได้น้อยลง → INR อาจสูงขึ้น' เหมาะสมหรือไม่ · ถ้ามีคลินิกวาฟารินแยกอยู่แล้ว ต้องการให้ระบบนี้ครอบคลุม INR หรือไม่",
]:
    add(f"- [ ] {q}")
add("")

add("## 2. กฎทั้งหมด\n")
add("| รหัสกฎ | กลุ่ม | ทำอะไร |")
add("|---|---|---|")
for r in RULES:
    add(f"| `{r['id']}` | {r['problem']} | {r['describe'](t)} |")
add("\nหมายเหตุ: กฎที่ขึ้นต้นด้วย `[เฉพาะแพทย์]` แสดงให้แพทย์ในกล่อง \"ข้อสังเกตสำหรับแพทย์\" เท่านั้น ไม่ถูกพิมพ์ให้ผู้ป่วย กฎไม่วินิจฉัยและไม่สั่งยา\n")

add("## 3. ค่าเกณฑ์ทั้งหมด (data/targets.json)\n")
add("| ค่า | ตั้งไว้ | แหล่งอ้างอิง | ต้องระบุฉบับ |")
add("|---|---|---|---|")
def walk(d, path=()):
    for k, v in d.items():
        if k.startswith("_"): continue
        if isinstance(v, dict):
            src = v.get("source"); need = v.get("needs_citation")
            leaf = {kk: vv for kk, vv in v.items() if kk not in ("source", "needs_citation")}
            if all(not isinstance(x, dict) for x in leaf.values()):
                vals = ", ".join(f"{kk} = {vv}" for kk, vv in leaf.items())
                add(f"| `{'.'.join(path + (k,))}` | {vals} | {src or '—'} | {'☐ ใช่' if need else '—'} |")
            else:
                walk(v, path + (k,))
walk(t)
add("")

add("## 4. คำแนะนำและสัญญาณอันตรายที่พิมพ์ให้ผู้ป่วย\n")
for p, a in tpl["advice"].items():
    add(f"**{tpl['problem_titles'].get(p, p)}**")
    for line in a["long"]: add(f"- {line}")
    add("")
add("**สัญญาณที่ต้องมาพบแพทย์ทันที**")
for p, text in tpl["redflags"].items(): add(f"- {tpl['problem_titles'].get(p, p)}: {text}")
add("")

add("## 5. ถ้อยคำต่อผู้ป่วยทุกประโยค (แยกตามรหัสผลที่กฎสร้าง)\n")
add("ช่อง `{...}` ระบบเติมค่าให้ ตัวเลขเกณฑ์ไม่ได้เขียนอยู่ในข้อความ\n")
add("| รหัส | ฉบับสั้น | ฉบับยาว |")
add("|---|---|---|")
for k, v in tpl["findings"].items():
    add(f"| `{k}` | {v['short']} | {v['long']} |")
add("")
add("## 6. ข้อสังเกตสำหรับแพทย์ (ไม่พิมพ์ให้ผู้ป่วย)\n")
for k, v in tpl["clinician"].items(): add(f"- `{k}`: {v}")
add("")
add("## 7. คำสงฆ์ (glossary.json)\n")
add("| ช่อง | ภาษาทั่วไป | ภาษาสงฆ์ |")
add("|---|---|---|")
for k in gloss["normal"]:
    add(f"| `{{{k}}}` | {gloss['normal'][k] or '—'} | {gloss['monk'][k] or '—'} |")
add("")
for a in gloss["monk_extra_advice"]: add(f"- (เพิ่มเมื่อเป็นพระและมีเบาหวาน/ความดัน/ไต/น้ำหนัก) {a}")
add("")
add("## 8. การลงนามรับรอง\n")
add("| ผู้ตรวจ | ตำแหน่ง | วันที่ | เวอร์ชันข้อมูลที่ตรวจ | ลายมือชื่อ |")
add("|---|---|---|---|---|")
add(f"|  |  |  | {t['_meta']['version']} |  |")
text = "\n".join(L) + "\n"
path = os.path.join(ROOT, "docs", "RULES_REVIEW.md")
if "--check" in sys.argv:                          # exit 1 if the committed document is out of date with the data/rules
    current = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    print("docs/RULES_REVIEW.md is up to date" if current == text else "docs/RULES_REVIEW.md is STALE: run python3 tools/dump_rules.py")
    sys.exit(0 if current == text else 1)
os.makedirs(os.path.join(ROOT, "docs"), exist_ok=True)
open(path, "w", encoding="utf-8").write(text)
print(f"wrote docs/RULES_REVIEW.md  ({len(RULES)} rules, {len(tpl['findings'])} patient sentences, {len(tpl['clinician'])} clinician hints)")
