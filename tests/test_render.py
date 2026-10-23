import datetime
import itertools
import json
import os
import random
import re
import unittest

from engine.lexicon import DATA_DIR
from engine.parse_note import parse_note
from engine.render import fill, render_clinician, render_patient
from engine.rules import evaluate

TODAY = datetime.date(2026, 10, 22)
TPL = json.load(open(os.path.join(DATA_DIR, "templates.json"), encoding="utf-8"))
GLOSS = json.load(open(os.path.join(DATA_DIR, "glossary.json"), encoding="utf-8"))


def ev(note, age=60, sex="M", tcvr=None):
    return evaluate(parse_note(note, today=TODAY), {"age": age, "sex": sex, "tcvr": tcvr})


def battery():
    """Notes chosen so that every finding key in templates.json is produced at least once."""
    notes = []
    for h in (6.5, 7.5, 9, 11): notes.append(f"DM : HbA1c {h}")
    notes += ["DM : HbA1c 9->7.4", "DM : HbA1c 7->8", "DM : HbA1c 7.0->7.2", "DM : HbA1c 12->10->6.5"]
    for f in (60, 75, 100, 150, 200): notes.append(f"DM : FBS {f}")
    for comorbid in ("", "DM : FBS 100\n"):
        for bp in ("BP 120/70", "BP 150/90", "BP 190/100"): notes.append(f"{comorbid}HT : {bp}")
    notes += ["HT : HMBP 120/70", "HT : HMBP 150/90", "HT : BP 150/90 HMBP 120/80", "HT : BP 125/75 HMBP 140/90"]
    for b in (17, 21, 24, 27, 32): notes.append(f"Obesity : BMI {b}")
    notes += ["Obesity : BW 110->100", "Obesity : BW 100->110", "Obesity : BW 100->99"]
    for e in (95, 75, 50, 40, 20, 10): notes.append(f"CKD : eGFR {e}")
    notes += ["CKD : eGFR 70->55->48", "CKD : eGFR 40->52", "CKD : Cr 1.5", "CKD : Cr 1.5 eGFR 90"]
    notes += ["22/10/69 : ยังสูบบุหรี่อยู่", "22/10/69 : เลิกสูบบุหรี่แล้ว", "22/10/69 : เวียนศีรษะ ใจสั่น", "22/10/69 : ฉันได้น้อย"]
    # dyslipidemia
    for v in (90, 140, 170, 200): notes.append(f"DLP : LDL {v}")
    notes += ["DM : FBS 100\nDLP : LDL 110", "DLP : LDL 160->120", "DLP : LDL 120->160"]
    for v in (120, 170, 300, 600): notes.append(f"DLP : TG {v}")
    for v in (35, 50): notes.append(f"DLP : HDL {v}")
    for v in (180, 220, 260): notes.append(f"DLP : TC {v}")
    # anemia / CBC
    for v in (14, 12, 9, 7): notes.append(f"CBC : Hb {v}")
    notes += ["CBC : Hb 8->10", "CBC : Hb 10->8", "CBC : MCV 70", "CBC : MCV 90", "CBC : MCV 110",
              "CBC : Hb 9.2 MCV 68 RBC 4.9 RDW 17 Hct 28", "CBC : Hct 28 RBC 4.9 MCV 90", "CBC : Hb 9 Hct 40"]
    # warfarin
    notes += ["Warfarin : INR 2.5", "Warfarin : INR 1.5", "Warfarin : INR 3.5", "Warfarin : INR 5.0", "Warfarin : INR 3 goal 2.5-3.5",
              "Warfarin : INR 2.5\n22/10/69 : เลือดกำเดา ฟกช้ำ ฉันได้น้อย", "DM : FBS 100\n22/10/69 : ถ่ายดำ"]
    # DN / DR / MAFLD / CAD / Stroke / COPD / Asthma / ultrasound / waist / SpO2
    for u in (10, 100, 500): notes.append(f"DM : UACR {u}")
    notes += ["DM : UMA 40 mg/g", "DM/DN : UACR 100 eGFR 50", "CKD : eGFR 70 U/S KUB normal size", "CKD : U/S KUB increased echo", "CKD : U/S KUB small kidney, hydronephrosis, stone",
              "CKD : U/S KUB renal mass, cyst, asymmetry", "Obesity : Waist 85", "Obesity : Waist 100", "Obesity : BW 80 Height 170"]
    notes += ["DR : no DR", "DR : NPDR mild", "DR : NPDR moderate, laser", "DR : NPDR severe", "DR : PDR", "DR : NPDR, DME", "DR : no DR, NPDR mild", "DM : HbA1c 7"]
    notes += ["MAFLD : ALT 30 AST 25", "MAFLD : ALT 80 AST 60", "MAFLD : ALT 150 AST 90", "MAFLD : ALT 40 AST 35 Plt 250", "MAFLD : ALT 80 AST 60 Plt 180", "MAFLD : ALT 30 AST 25 Plt 300",
              "MAFLD : ALT 90 AST 120 Plt 100", "MAFLD : LSM 6", "MAFLD : LSM 10", "MAFLD : LSM 15", "MAFLD : CAP 200", "MAFLD : CAP 255", "MAFLD : CAP 270", "MAFLD : CAP 300",
              "MAFLD : ALT 90 AST 120 Plt 100 LSM 5", "MAFLD : ultrasound cirrhosis"]
    notes += ["CAD : LVEF 60", "CAD : LVEF 45", "CAD : LVEF 30", "CAD : PCI", "Stroke : ischemic mRS 3", "Stroke : mRS 2", "Stroke : hemorrhagic, statin", "CAD : s/p PCI, statin, ASA\nLDL 90"]
    notes += ["COPD : FEV1 85 FEV1/FVC 0.6", "COPD : FEV1 60 FEV1/FVC 0.6", "COPD : FEV1 40 FEV1/FVC 0.6", "COPD : FEV1 25 FEV1/FVC 0.6", "COPD : FEV1 60", "COPD : FEV1 60 FEV1/FVC 0.8",
              "COPD : mMRC 1 CAT 5 Exac 0", "COPD : mMRC 3 Exac 1", "COPD : CAT 12 Exac 2", "COPD : mMRC 0 Exac 0 ExacHosp 1", "COPD : CAT 5", "COPD : SpO2 85", "COPD : SpO2 91"]
    notes += ["Asthma : ACT 22", "Asthma : ACT 17", "Asthma : ACT 10", "Asthma : PEF 400 PEFbest 450", "Asthma : PEF 300 PEFbest 450", "Asthma : PEF 150 PEFbest 450", "Asthma : Exac 0", "Asthma : Exac 2", "Vitals : SpO2 97", "Vitals : SpO2 92", "Vitals : SpO2 85"]
    notes += ["22/10/69 : เจ็บหน้าอก", "22/10/69 : พูดไม่ชัด อ่อนแรง", "DM : FBS 100\n22/10/69 : ตามัว", "COPD : FEV1 60\n22/10/69 : ไอ เสมหะ"]
    return notes


class TemplateLint(unittest.TestCase):
    patient_texts = []

    @classmethod
    def setUpClass(cls):
        t = cls.patient_texts
        for v in TPL["findings"].values(): t += [v["short"], v["long"]]
        for v in TPL["advice"].values(): t += [v["short"]] + v["long"]
        t += list(TPL["redflags"].values()) + list(TPL["notes"].values()) + [TPL["followup"], TPL["empty"]] + list(TPL["titles"].values())
        t += GLOSS["monk_extra_advice"]

    def test_no_clinical_number_is_written_into_a_sentence(self):
        allowed = [r"FEV1", r"FIB-4", r"SpO2", r"HbA1c", r"mL/min/1\.73m²", r"\bG[1-5][ab]?\b", r"\bG[1-5]\b"]
        for text in self.patient_texts:
            stripped = _strip_placeholders(text)
            for pat in allowed: stripped = re.sub(pat, "", stripped)
            self.assertIsNone(re.search(r"\d", stripped), f"digit hard-coded in: {text}")

    def test_register_words_use_glossary_tokens(self):
        for text in self.patient_texts:
            plain = _strip_placeholders(text).replace("อาหารเสริม", "")
            for lay in ("รับประทาน", "อาหาร", "ร่างกาย", "นอนหลับ", "ออกกำลังกาย", "เจ็บป่วย"):
                self.assertNotIn(lay, plain, f"'{lay}' must be a glossary token ({{...}}) in: {text}")

    def test_patient_text_never_diagnoses_prescribes_or_names_drugs(self):
        banned = ["เป็นโรค", "ท่านเป็น", "สั่งยา", "ให้ยา", "เพิ่มยา", "ลดยา", "ปรับยา", "metformin", "insulin", "อินซูลิน", "เมตฟอร์มิน", "statin", "สแตติน", "aspirin", "แอสไพริน"]   # warfarin is allowed: the Warfarin module is about that drug
        for text in self.patient_texts:
            low = text.lower().replace("ห้ามปรับยา", "").replace("ห้ามปรับหรือหยุดยา", "")       # telling the patient NOT to adjust is the opposite of prescribing
            for b in banned:
                self.assertNotIn(b, low, f"'{b}' in: {text}")

    def test_every_clinician_text_is_marked_as_a_hint_not_an_order(self):
        for k, text in TPL["clinician"].items():
            for bad in ("ต้องให้ยา", "ให้ยา", "สั่งยา", "หยุดยา"):
                self.assertNotIn(bad, text, k)


def _strip_placeholders(s):
    return re.sub(r"\{[^{}]+\}", "", s)


class Rendering(unittest.TestCase):
    def test_every_template_is_exercised_and_renders(self):
        produced = set()
        for note in battery():
            r = ev(note)
            produced |= {f["key"] for f in r["findings"]}
            for pattern, monk in itertools.product(("simple", "standard", "detailed"), (False, True)):
                text = render_patient(r, pattern, monk)
                self.assertNotRegex(text, r"[{}]", (note, pattern, monk))
            render_clinician(r)
        for v in (5, 15, 25, 40):                                                      # Thai CV risk entered by the user
            produced |= {f["key"] for f in ev("HT : BP 120/70", tcvr=v)["findings"]}
        missing = set(TPL["findings"]) - produced
        self.assertEqual(missing, set(), "templates that no rule can produce / battery does not reach")
        self.assertEqual(produced - set(TPL["findings"]), set())

    def test_every_clinician_key_exists(self):
        used = set()
        for note in battery() + ["DM : HbA1c 12->10->6.5\n22/10/69 : เวียนศีรษะ ฉันได้น้อย", "DM : HbA1c 65", "DM : LDL 130\nfoo bar", "CKD : Cr 1.5 eGFR 54"]:
            r = ev(note, age=None, sex=None) if "CKD : Cr 1.5 eGFR 54" in note else ev(note)
            used |= {n["key"] for n in r["clinician_notes"]}
            render_clinician(r)
        for age, sex, e in ((None, None, 54), (60, "M", 54), (60, "M", 90)):          # no age/sex, consistent, mismatching
            r = ev(f"CKD : Cr 1.5 eGFR {e}", age=age, sex=sex); used |= {n["key"] for n in r["clinician_notes"]}; render_clinician(r)
        for note in ("CBC : Hb 9", "DLP : HDL 35", "Obesity : Height 170"):                    # no sex given / a value that has no rule yet
            r = ev(note, age=None, sex=None); used |= {n["key"] for n in r["clinician_notes"]}; render_clinician(r)
        for kw in (dict(tcvr=15), dict(tcvr=15, age=80)):                               # entered risk; entered risk outside the validated age range
            r = ev("HT : BP 120/70", **kw); used |= {n["key"] for n in r["clinician_notes"]}; render_clinician(r)
        for note, kw in (("Obesity : Waist 100", dict(sex=None)), ("MAFLD : ALT 80 AST 60 Plt 180", dict(age=30)), ("MAFLD : ALT 80 AST 60 Plt 180", dict(age=None)),
                         ("HT : BP 150/90 TC 200\n22/10/69 : ไม่สูบบุหรี่", {}), ("HT : BP 150/90", {}), ("DM : FBS 100\n22/10/69 : ฉัน 1 มื้อ", {})):
            r = ev(note, **kw); used |= {n["key"] for n in r["clinician_notes"]}; render_clinician(r)
        for note in ("Warfarin : INR 2.5\n22/10/69 : ฉันได้น้อย เลือดกำเดา",):
            r = ev(note); used |= {n["key"] for n in r["clinician_notes"]}; render_clinician(r)
        self.assertEqual(set(TPL["clinician"]) - used - {"data.unparsed", "data.custom_error", "data.disabled_rules"}, set(), "clinician texts never produced")   # last two: tests/test_custom_rules.py

    def test_monk_register_has_no_lay_words(self):
        for note in battery():
            text = render_patient(ev(note), "detailed", True)
            plain = text.replace("อาหารเสริม", "")
            for lay in ("รับประทาน", "ร่างกาย", "นอนหลับ", "ออกกำลังกาย", "เจ็บป่วย"):
                self.assertNotIn(lay, plain, note)
            self.assertNotIn("อาหาร", plain.replace("ภัตตาหาร", ""), note)
            self.assertNotIn("ท่าน", plain, note)
            self.assertIn("🙏 ขอนมัสการ พระคุณเจ้า", text)
            self.assertIn("กราบนมัสการ", text)

    def test_normal_register_has_no_monk_words(self):
        for note in battery():
            text = render_patient(ev(note), "detailed", False)
            for monk_word in ("พระคุณเจ้า", "ภัตตาหาร", "เดินจงกรม", "สังขาร", "น้ำปานะ", "จำวัด"):
                self.assertNotIn(monk_word, text, note)

    def test_simple_never_drops_an_attention_or_alert_finding(self):
        note = "DM : FBS 60 HbA1c 11\nHT : BP 190/100 HMBP 150/90\nObesity : BMI 32 BW 100->110\nCKD : eGFR 20\n22/10/69 : ยังสูบบุหรี่ เวียนศีรษะ ฉันได้น้อย"
        r = ev(note)
        text = render_patient(r, "simple", False)
        must = [f for f in r["findings"] if f["level"] in ("attention", "alert")]
        self.assertGreater(len(must), 8)
        for f in must:
            short = fill(TPL["findings"][f["key"]]["short"], _mp(f))
            self.assertIn(short, text.replace("🟡 ", "").replace("🔴 ", ""), f["key"])

    def test_clinician_only_content_never_reaches_the_patient_text(self):
        r = ev("DM : HbA1c 12->10->6.5\nHT : BP 150/90 HMBP 120/80\nCKD : Cr 1.5 eGFR 54\n22/10/69 : เวียนศีรษะ ฉันได้น้อย")
        text = render_patient(r, "detailed", False)
        for banned in ("น้ำตาลในเลือดต่ำ", "white-coat", "CKD-EPI", "albuminuria", "UACR", "ภาวะน้ำตาลต่ำ"):
            self.assertNotIn(banned, text)

    def test_empty_note_message(self):
        text = render_patient(ev(""), "standard", False)
        self.assertIn("ไม่พบค่า", text)

    def test_unknown_placeholder_is_an_error_not_a_silent_blank(self):
        with self.assertRaises(KeyError):
            fill("ค่า {ไม่มีช่องนี้}", {})


def _mp(f):
    from engine.render import _mapping
    return _mapping(f["values"], False, TPL)


class Fuzz(unittest.TestCase):
    def test_random_notes_never_break_the_pipeline(self):
        rnd = random.Random(11)
        parts = ["DM : HbA1c {a}->{b}", "DM : FBS {c}", "HT : BP {s}/{d} HMBP {s2}/{d2}", "Obesity : BW {w}->{w2} BMI {m}", "CKD : Cr {cr} GFR {g}",
                 "22/10/69 : เวียนศีรษะ ฉันได้น้อย ยังสูบบุหรี่อยู่", "22/10/69 : ไม่มีเวียนศีรษะ", "foo bar", "Gout : uric 9"]
        for _ in range(1500):
            note = "\n".join(rnd.sample(parts, rnd.randint(1, len(parts))))
            note = note.format(a=rnd.choice([3, 6.5, 12, 25, 0]), b=round(rnd.uniform(0, 20), 1), c=rnd.choice([0, 55, 100, 700]), s=rnd.randint(40, 260), d=rnd.randint(20, 170),
                               s2=rnd.randint(80, 200), d2=rnd.randint(40, 120), w=rnd.randint(10, 320), w2=rnd.randint(10, 320), m=round(rnd.uniform(5, 90), 1),
                               cr=round(rnd.uniform(0.05, 20), 2), g=rnd.randint(0, 220))
            r = ev(note, rnd.choice([None, 5, 60, 90, 150]), rnd.choice([None, "M", "F", "x"]))
            for pattern, monk in itertools.product(("simple", "standard", "detailed"), (False, True)):
                self.assertNotRegex(render_patient(r, pattern, monk), r"[{}]")
            render_clinician(r)


if __name__ == "__main__":
    unittest.main()
