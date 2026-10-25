"""Synthetic OPD-note generator with per-number gold labels. No patient data.
Seen aliases are used for training; UNSEEN aliases (not in the rule parser's lexicon either) are used only for testing,
to measure whether a tiny tagger can classify a number whose name it has never seen."""
import random, re

CLASSES = ["FBS", "HbA1c", "BP", "HomeBP", "BW", "BMI", "Creatinine", "eGFR"]
SEEN = {
    "FBS": ["FBS", "fbs", "FPG", "fpg"],
    "HbA1c": ["HbA1c", "HbA1C", "hba1c", "A1c", "a1c", "Hb A1c"],
    "BP": ["BP", "bp"],
    "HomeBP": ["HMBP", "hmbp", "home BP", "HBPM"],
    "BW": ["BW", "wt", "weight", "น้ำหนัก"],
    "BMI": ["BMI", "bmi"],
    "Creatinine": ["Cr", "creatinine", "Scr", "cr"],
    "eGFR": ["GFR", "eGFR", "egfr", "gfr"],
}
UNSEEN = {
    "FBS": ["sugar", "glucose", "FBG", "น้ำตาล", "FPG-lab"],
    "HbA1c": ["glycated Hb", "HgbA1c", "น้ำตาลสะสม", "HbA 1c", "A1-c"],
    "BP": ["SBP/DBP", "ความดันโลหิต", "pressure", "BP.clinic"],
    "HomeBP": ["HBP", "ความดันที่บ้าน", "homeBP2", "BPhome"],
    "BW": ["body weight", "นน.", "Wt.", "น้ำหนักตัว"],
    "BMI": ["ดัชนีมวลกาย", "BMI.calc", "b.m.i"],
    "Creatinine": ["creat", "Cre", "ครีแอทินิน", "S.Cr"],
    "eGFR": ["e-GFR", "eGFR(CKD-EPI)", "อัตรากรอง", "GFR.ckdepi"],
}
HEAD = {
    "dm": ["DM", "T2DM", "dm", "เบาหวาน"], "ht": ["HT", "HTN", "ความดัน"],
    "ob": ["Obesity", "Obese", "อ้วน"], "ckd": ["CKD", "ไตเรื้อรัง", "KUB"],
}
ARROWS = ["->", "-->", "→", "=>", " -> ", "--->", " >> "]
FREE = ["มีเวียนศีรษะ", "ฉันได้น้อย", "ใจสั่น", "ยังสูบบุหรี่อยู่", "ไม่มีเวียนศีรษะ", "นอนไม่หลับ", "ฉัน 1 มื้อ", "ปวดหัว 2 วัน"]
THAI = str.maketrans("0123456789", "๐๑๒๓๔๕๖๗๘๙")
NUM = re.compile(r"\d+(?:\.\d+)?(?:/\d+){0,2}")


def fmt(v): return f"{v:g}"


def vals(rnd, lo, hi, nd=0):
    n = rnd.choices([1, 2, 3], [5, 3, 2])[0]
    out = [round(rnd.uniform(lo, hi), nd) for _ in range(n)]
    return [int(v) if nd == 0 else v for v in out]


def gen_note(rnd, unseen=False):
    pool = UNSEEN if unseen else SEEN
    arrow = rnd.choice(ARROWS)
    unit_on = rnd.random() < 0.5
    items = []                                            # (class, text pieces)

    def alias(c):
        # in unseen mode every parameter name is unseen, except BMI/BP which keep seen names half the time
        if unseen and c in ("BMI", "BP") and rnd.random() < 0.5: return rnd.choice(SEEN[c])
        return rnd.choice(pool[c])

    spec = {
        "FBS": lambda: ([fmt(v) for v in vals(rnd, 70, 240)], "mg/dL"),
        "HbA1c": lambda: ([fmt(v) for v in vals(rnd, 5.5, 13, 1)], "%"),
        "BP": lambda: ([f"{max(s, d + 20)}/{d}" for s, d in [(rnd.randint(105, 180), rnd.randint(60, 105)) for _ in range(rnd.choice([1, 1, 2]))]], "mmHg"),
        "HomeBP": lambda: ([f"{max(s, d + 20)}/{d}" for s, d in [(rnd.randint(100, 165), rnd.randint(58, 98))]], "mmHg"),
        "BW": lambda: ([fmt(v) for v in vals(rnd, 40, 130)], "Kg"),
        "BMI": lambda: ([fmt(round(rnd.uniform(17, 42), 1))], ""),
        "Creatinine": lambda: ([fmt(round(rnd.uniform(0.6, 4.5), 1))], "mg/dL"),
        "eGFR": lambda: ([fmt(rnd.randint(8, 105))], ""),
    }
    groups = [("dm", ["FBS", "HbA1c"]), ("ht", ["BP", "HomeBP"]), ("ob", ["BW", "BMI"]), ("ckd", ["Creatinine", "eGFR"])]
    lines = []
    for key, cls in groups:
        if rnd.random() < 0.7:
            cs = [c for c in cls if rnd.random() < 0.85] or [cls[0]]
            if rnd.random() < 0.12:                      # a parameter written under a "wrong" header (header is not a shortcut)
                other = rnd.choice([c for c in CLASSES if c not in cs]); cs.append(other)
            rnd.shuffle(cs) if rnd.random() < 0.2 else None
            lines.append((rnd.choice(HEAD[key]), cs))
    if not lines: lines = [("DM", ["FBS"])]
    rnd.shuffle(lines) if rnd.random() < 0.15 else None
    parts_all = []
    for head, cs in lines:
        sep = rnd.choice([" : ", ": ", " :", "："]) if rnd.random() < 0.9 else " "
        chunks = []
        for c in cs:
            vs, unit = spec[c]()
            u = unit if (unit_on and unit) else ""
            chunks.append((alias(c), c, vs, u))
        parts_all.append((head, sep, chunks))
    # build text with char labels
    text, lab = "", []

    def add(s, label=None):
        nonlocal text, lab
        text += s; lab += [label] * len(s)

    for li, (head, sep, chunks) in enumerate(parts_all):
        if li: add("\n")
        add(head); add(sep)
        for ci, (name, c, vs, u) in enumerate(chunks):
            if ci: add(rnd.choice([" ", " ", "  ", ", "]))
            add(name); add(rnd.choice([" ", " ", "=", ": "]))
            for vi, v in enumerate(vs):
                if vi: add(arrow)
                add(v, c)
            add(u)
            if rnd.random() < 0.08: add(" " + rnd.choice(["(home)", "(OPD)", "ครั้งก่อน"]))
    if rnd.random() < 0.7:                                # dated free-text line with distractor numbers
        d = f"{rnd.randint(1, 28)}/{rnd.randint(1, 12)}/{rnd.choice(['69', '68', '2569'])}"
        add("\n"); add(d); add(" : ")
        add(" ".join(rnd.sample(FREE, rnd.randint(1, 3))))
    if rnd.random() < 0.1: add(f"\nอายุ {rnd.randint(40, 85)} ปี")
    if rnd.random() < 0.5 and True:                      # Thai digits: same positions, same labels
        text = text.translate(THAI)
    return text, [l or "O" for l in lab]


def tokens(text):
    norm = text.translate(str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789"))
    return [(m.start(), m.end()) for m in NUM.finditer(norm)]


if __name__ == "__main__":
    r = random.Random(1)
    for u in (False, True):
        t, l = gen_note(r, u)
        print(t); print([(t[a:b], l[a]) for a, b in tokens(t)]); print("---")
