#!/usr/bin/env python3
"""Builds public/index.html from the upstream page (upstream/public/index.html) with explicit, asserted edits.
Every edit must match exactly once; if the upstream file ever changes, this fails loudly instead of producing a half-patched page."""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rules_editor_ui  # noqa: E402
import tagger_ui  # noqa: E402

SRC, DST = "upstream/public/index.html", "public/index.html"
s = open(SRC, encoding="utf-8").read()


def sub(old: str, new: str, count: int = 1):
    global s
    n = s.count(old)
    assert n == count, f"expected {count} match(es), found {n} for: {old[:70]!r}"
    s = s.replace(old, new)


def cut(start: str, end: str, replacement: str = ""):
    """Replace everything from `start` up to (not including) `end`."""
    global s
    a, b = s.find(start), s.find(end)
    assert a != -1 and b > a, f"cut markers not found: {start[:50]!r} .. {end[:50]!r}"
    assert s.count(start) == 1, f"start marker not unique: {start[:50]!r}"
    s = s[:a] + replacement + s[b:]


# ---- 1. no external requests (the upstream page fetched Google Fonts on every load)
sub('  <link href="https://fonts.googleapis.com/css2?family=Sarabun:wght@300;400;600;700&display=swap" rel="stylesheet">\n', "")
sub("font-family: 'Sarabun', sans-serif;", "font-family: 'Sarabun', 'Noto Sans Thai', 'Leelawadee UI', 'Thonburi', 'Tahoma', sans-serif;")
sub("<title>Lab Interpreter — แปลผล Lab สำหรับผู้ป่วย</title>", "<title>Lab Interpreter — แปลผล Lab สำหรับผู้ป่วย (ระบบกฎ ใช้ในเครื่อง)</title>")

# ---- 2. the knowledge-base feature is gone (rules live in data/*.json, reviewed by a physician)
cut('  <!-- ===== KNOWLEDGE BASE MODAL ===== -->', '  <!-- ===== MAIN CONTENT ===== -->')
sub('      <button class="hdr-btn" onclick="showKnowledgeModal()" id="kbBtn" style="display:none">📚 คลังความรู้</button>\n', "")
sub("        document.getElementById('kbBtn').style.display = 'inline-flex';\n", "")
sub("      document.getElementById('kbBtn').style.display = 'none';\n", "")
cut("    // ===== Knowledge Base =====", "    // ===== Patterns =====")

# ---- 3. patterns: simple / standard / detailed only (no free-form prompt for a model any more)
cut('            <div class="pattern-option" data-pattern="custom"', '          <!-- Monk Toggle -->',
    '          </div>\n')                                                   # keeps the </div> that closes .pattern-grid (it sat inside the removed block)
cut("    const patterns = {", "    // ===== UI =====")                       # prompt strings + monkAddon: replaced by data/templates.json + glossary.json
sub("      document.getElementById('customEditor').classList.toggle('show', currentPattern === 'custom');\n", "")
sub("custom: '✏️ กำหนดเอง', ", "")

cut("    function addTag(t) {", "    // ===== Generate (via Backend Proxy) =====")      # helper of the removed custom-pattern editor

# ---- 3b. admin rule editor (modal + script + header button)
sub("  <!-- ===== ADMIN MODAL ===== -->", rules_editor_ui.MODAL + rules_editor_ui.TARGETS_MODAL + rules_editor_ui.GOLDEN_MODAL + rules_editor_ui.LEARN_MODAL + "  <!-- ===== ADMIN MODAL ===== -->")
sub('      <button class="hdr-btn" onclick="showAdminModal()" id="adminBtn" style="display:none">👥 จัดการผู้ใช้</button>',
    '      <button class="hdr-btn" onclick="showLearnModal()" id="learnBtn" style="display:none">🧠 เรียนรู้</button>\n      <button class="hdr-btn" onclick="showGoldenModal()" id="goldenBtn" style="display:none">✅ ตัวอย่าง</button>\n      <button class="hdr-btn" onclick="showTargetsModal()" id="targetsBtn" style="display:none">🎯 เกณฑ์</button>\n      <button class="hdr-btn" onclick="showRulesModal()" id="rulesBtn" style="display:none">📐 กฎ</button>\n      <button class="hdr-btn" onclick="showAdminModal()" id="adminBtn" style="display:none">👥 จัดการผู้ใช้</button>')
sub("    // ===== Admin =====", rules_editor_ui.JS + rules_editor_ui.TARGETS_JS + rules_editor_ui.GOLDEN_JS + rules_editor_ui.LEARN_JS + tagger_ui.JS + "    // ===== Admin =====")
sub("document.getElementById('adminBtn').style.display = 'inline-flex';", "document.getElementById('adminBtn').style.display = 'inline-flex'; document.getElementById('rulesBtn').style.display = 'inline-flex'; document.getElementById('targetsBtn').style.display = 'inline-flex'; document.getElementById('goldenBtn').style.display = 'inline-flex'; document.getElementById('learnBtn').style.display = 'inline-flex';")
sub("document.getElementById('adminBtn').style.display = 'none';", "document.getElementById('adminBtn').style.display = 'none'; document.getElementById('rulesBtn').style.display = 'none'; document.getElementById('targetsBtn').style.display = 'none'; document.getElementById('goldenBtn').style.display = 'none'; document.getElementById('learnBtn').style.display = 'none';")

# ---- 4. input form: one note box + age/sex (nothing identifying)
cut('          <div class="form-group">\n            <label>ประวัติผู้ป่วย</label>', '          <button class="btn-primary" id="generateBtn"', '''          <div class="form-group" style="display:flex;gap:10px;">
            <div style="flex:1;">
              <label>อายุ (ปี) <span style="font-weight:400;color:var(--text-light)">ใช้ตรวจ eGFR</span></label>
              <input type="text" inputmode="numeric" maxlength="3" id="ptAge" placeholder="เช่น 60">
            </div>
            <div style="width:140px;">
              <label>เพศ</label>
              <select id="ptSex" style="width:100%;padding:10px;border:1.5px solid var(--border);border-radius:8px;font-family:inherit;">
                <option value="">ไม่ระบุ</option><option value="M">ชาย</option><option value="F">หญิง</option>
              </select>
            </div>
          </div>
          <div class="form-group">
            <label>Thai CV risk (% ใน 10 ปี) <span style="font-weight:400;color:var(--text-light)">ไม่บังคับ · กรอกจากเครื่องมือของรามาธิบดีเอง ระบบไม่คำนวณและไม่ต้องใช้อินเทอร์เน็ต</span></label>
            <input type="text" inputmode="decimal" maxlength="5" id="ptTcvr" placeholder="เช่น 12.5" style="width:140px;">
          </div>
          <div class="form-group">
            <label>บันทึก OPD (รูปแบบของแพทย์ผู้ใช้)</label>
            <textarea id="labValues" class="large" spellcheck="false"
              placeholder="DM : FBS 120->130->110 HbA1C 12->10->6.5%&#10;HT : BP 150/90mmHg HMBP 120/80mmHg&#10;Obesity : BW 110-->100Kg BMI 31&#10;CKD : Cr 1.5 GFR 54&#10;22/10/69 : มีเวียนศีรษะ ฉันได้น้อย ยังสูบบุหรี่อยู่"></textarea>
            <div style="font-size:11px;color:var(--text-light);margin-top:4px;">ค่าซ้ายสุด = เก่าสุด · ขวาสุด = ล่าสุด · ระบบไม่เดา ส่วนที่ไม่เข้าใจจะแสดงให้ตรวจสอบ</div>
          </div>
''')
sub('<div class="notice">⚠️ ห้ามใส่ชื่อ-นามสกุล หรือข้อมูลระบุตัวตนผู้ป่วย</div>',
    '<div class="notice">⚠️ ห้ามใส่ชื่อ-นามสกุล, HN หรือข้อมูลระบุตัวตนผู้ป่วย · ข้อมูลไม่ถูกบันทึกและไม่ออกจากเครื่องนี้</div>')
sub('<div style="font-size:12px;">เลือก Pattern → ใส่ค่า Lab → กดแปลผล</div>', '<div style="font-size:12px;">ใส่บันทึก OPD → กดแปลผล</div>')
sub('กำลังวิเคราะห์...<br><span\n                style="font-size:11px;opacity:0.7;">อาจใช้เวลา 10-30 วินาที</span>', 'กำลังอ่านบันทึก...<br><span\n                style="font-size:11px;opacity:0.7;">ระบบกฎ ใช้เวลาไม่ถึงวินาที</span>')

# ---- 5. review step: show what the system READ (the safety check) + doctor-only hints, above the editable draft
sub('''            <textarea class="edit-area" id="editArea" spellcheck="false"></textarea>''', '''            <div id="draftWarn" class="no-print" style="display:none;background:#FFF4E5;border:1.5px solid #F0B35A;border-radius:10px;padding:10px 12px;margin:10px 0;font-size:12.5px;line-height:1.6;"></div>
''' + rules_editor_ui.LEARN_BOX + tagger_ui.BOX + '''            <details id="readBox" class="no-print" open style="margin:10px 0;border:1.5px solid var(--border);border-radius:10px;padding:8px 12px;">
              <summary style="cursor:pointer;font-weight:600;font-size:13px;">🔎 สิ่งที่ระบบอ่านได้จากบันทึก (ตรวจให้ตรงกับที่เขียนก่อนยืนยัน)</summary>
              <div id="readTable" style="margin-top:8px;font-size:12.5px;line-height:1.7;"></div>
            </details>
            <details id="clinBox" class="no-print" open style="margin:10px 0;border:1.5px solid #C9D8F0;background:#F4F8FE;border-radius:10px;padding:8px 12px;">
              <summary style="cursor:pointer;font-weight:600;font-size:13px;">🩺 ข้อสังเกตสำหรับแพทย์ (ไม่พิมพ์ให้ผู้ป่วย)</summary>
              <div id="clinList" style="margin-top:8px;font-size:12.5px;line-height:1.7;"></div>
            </details>
            <textarea class="edit-area" id="editArea" spellcheck="false"></textarea>''')

# ---- 6. generate(): send the note to the rule engine
cut("    // ===== Generate (via Backend Proxy) =====", "    // ===== Review Workflow =====", r'''    // ===== Generate (local rule engine; nothing is stored) =====
    function esc(t) { return String(t ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
    const fmtV = (v, kind) => Array.isArray(v) ? `${v[0]}${kind === 'range' ? '–' : '/'}${v[1]}` : v;

    function renderRead(data) {
      let h = '';
      for (const p of data.table) {
        h += `<div style="margin-bottom:6px;"><b>${esc(p.problem)}</b>${p.known ? '' : ' <span style="color:#B45309">(ชื่อปัญหาไม่รู้จัก)</span>'}: `;
        h += p.values.map(v => `${esc(v.param)} <b>${esc(v.series.map(x => fmtV(x, v.kind)).join(' → '))}</b> ${esc(v.unit)}` +
          (v.invalid ? ' <span style="color:#B91C1C">⚠ ข้าม ไม่แปลผล</span>' : (v.has_rules ? '' : ' <span style="color:#6B7280">(ยังไม่มีกฎ)</span>')) +
          v.flags.map(f => `<div style="color:#B45309;margin-left:14px;">⚠ ${esc(f)}</div>`).join('')).join(' · ');
        if (p.tags && p.tags.length) h += ' ' + p.tags.map(t => `<span style="background:#EEF2FF;border-radius:6px;padding:1px 6px;">${esc(t.label)}=<b>${t.value === 'absent' ? 'ไม่มี' : 'มี'}</b></span>`).join(' ');
        if (p.unparsed) h += `<div style="color:#B45309;margin-left:14px;">? ไม่เข้าใจ: ${esc(p.unparsed)}</div>`;
        h += '</div>';
      }
      for (const v of data.visits) {
        h += `<div style="margin-bottom:6px;"><b>${esc(v.date_be || 'วันที่?')}</b>: ` +
          (v.concepts.map(c => `${esc(c.label)}=<b>${esc({ present: 'มี', absent: 'ไม่มี', current: 'ยังสูบ', former: 'เลิกแล้ว', never: 'ไม่เคย', not_smoking: 'ไม่สูบ' }[c.value] || c.value)}</b>`).join(' · ') || '—') +
          (v.warning ? ` <span style="color:#B91C1C">⚠ ${esc(v.warning)}</span>` : '') +
          (v.leftover.length ? `<div style="color:#B45309;margin-left:14px;">? ไม่เข้าใจ: ${esc(v.leftover.join(' '))}</div>` : '') + '</div>';
      }
      for (const u of data.unparsed_lines) h += `<div style="color:#B45309;">? ไม่เข้าใจทั้งบรรทัด: ${esc(u.text)}</div>`;
      for (const w of data.warnings) h += `<div style="color:#B45309;">⚠ ${esc(w)}</div>`;
      document.getElementById('readTable').innerHTML = h || '<div>ไม่พบข้อมูลที่อ่านได้</div>';
      document.getElementById('clinList').innerHTML = data.clinician.length
        ? data.clinician.map(n => `<div>${n.icon} ${esc(n.text)}</div>`).join('') : '<div style="color:var(--text-light)">ไม่มี</div>';
      const warn = document.getElementById('draftWarn');
      warn.style.display = /DRAFT/.test(data.status) ? 'block' : 'none';
      warn.innerHTML = `⚠️ <b>กฎและแม่แบบยังเป็นร่าง ยังไม่ผ่านการตรวจทานโดยแพทย์</b> (${esc(data.status)}) — ตรวจเกณฑ์และถ้อยคำก่อนใช้กับผู้ป่วยจริง`;
    }

    async function generate() {
      if (!token) { alert('กรุณา login ก่อน'); return; }
      const note = document.getElementById('labValues').value.trim();
      if (!note) { alert('กรุณาใส่บันทึก OPD'); return; }
      document.getElementById('placeholder').style.display = 'none';
      document.getElementById('loading').classList.add('show');
      document.getElementById('reviewStep').style.display = 'none';
      document.getElementById('confirmedStep').style.display = 'none';
      document.getElementById('reviewBtns').style.display = 'none';
      document.getElementById('confirmedBtns').style.display = 'none';
      document.getElementById('generateBtn').disabled = true;
      try {
        const res = await fetch(API + '/api/generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token },
          body: JSON.stringify({ note, age: document.getElementById('ptAge').value || null, sex: document.getElementById('ptSex').value, tcvr: document.getElementById('ptTcvr').value || null, pattern: currentPattern, monkMode })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'เกิดข้อผิดพลาด');
        renderRead(data); learnInit(!!data.learning); suggestInit(!!data.tagger, note);
        document.getElementById('editArea').value = data.result;
        document.getElementById('loading').classList.remove('show');
        document.getElementById('reviewStep').style.display = 'block';
        document.getElementById('reviewBtns').style.display = 'flex';
        document.getElementById('printSubtitle').textContent = 'จัดทำโดย Lab Interpreter' + (monkMode ? ' (ฉบับพระสงฆ์)' : '') + ' — กรุณาปรึกษาแพทย์เพิ่มเติม';
      } catch (err) {
        document.getElementById('loading').classList.remove('show');
        document.getElementById('placeholder').style.display = 'flex';
        alert('ข้อผิดพลาด: ' + err.message);
      }
      document.getElementById('generateBtn').disabled = false;
    }

''')

# ---- 7. clearAll, PIN length, print disclaimer (no AI is involved any more)
sub("['patientHistory', 'labValues', 'extraNotes'].forEach(id => document.getElementById(id).value = '');",
    "['labValues', 'ptAge', 'ptSex', 'ptTcvr'].forEach(id => document.getElementById(id).value = '');\n      document.getElementById('readTable').innerHTML = ''; document.getElementById('clinList').innerHTML = '';")
sub('placeholder="PIN (4+ หลัก)"', 'placeholder="PIN (6+ หลัก)"')
sub("(อย่างน้อย 4 หลัก):`", "(อย่างน้อย 6 หลัก):`")
sub("if (!newPin || newPin.length < 4) { if (newPin !== null) alert('PIN ต้องอย่างน้อย 4 หลัก'); return; }",
    "if (!newPin || newPin.length < 6) { if (newPin !== null) alert('PIN ต้องอย่างน้อย 6 หลัก'); return; }")
sub("⚠️ เอกสารนี้สร้างโดยระบบ AI เพื่อช่วยอธิบายผลตรวจเลือดเบื้องต้น <strong>ไม่ใช่การวินิจฉัยโรค</strong>",
    "⚠️ เอกสารนี้สร้างจากกฎที่แพทย์กำหนดและตรวจสอบโดยบุคลากรทางการแพทย์ เพื่อช่วยอธิบายผลตรวจเบื้องต้น <strong>ไม่ใช่การวินิจฉัยโรค</strong>")

# ---- 8. escape everything that came from the server before it goes into innerHTML (admin lists, stats)
sub("html += `<tr><td>${u.username}</td><td>${u.display_name}</td>", "html += `<tr><td>${esc(u.username)}</td><td>${esc(u.display_name)}</td>")
sub("for (const d of data.daily) { html += `<tr><td>${d.day}</td><td>${d.count}</td></tr>`; }", "for (const d of data.daily) { html += `<tr><td>${esc(d.day)}</td><td>${esc(d.count)}</td></tr>`; }")
sub("html += `<tr><td>${u.display_name}</td><td>${u.username}</td><td>${u.count}</td></tr>`", "html += `<tr><td>${esc(u.display_name)}</td><td>${esc(u.username)}</td><td>${esc(u.count)}</td></tr>`")
sub("html += `<tr><td>${patternNames[p.pattern] || p.pattern}</td><td>${p.count}</td></tr>`", "html += `<tr><td>${esc(patternNames[p.pattern] || p.pattern)}</td><td>${esc(p.count)}</td></tr>`")

# ---- 9. one "⚙️ ตั้งค่า" menu for every admin tool (keeps the header short on small screens)
sub("</style>", """
    .menu-wrap { position: relative; display: none; }
    .menu-list { display: none; position: absolute; right: 0; top: calc(100% + 6px); min-width: 220px; background: #fff; border: 1px solid var(--border); border-radius: 12px;
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.18); padding: 6px; z-index: 150; flex-direction: column; gap: 2px; }
    .menu-list.open { display: flex; }
    .menu-list .hdr-btn { display: flex !important; width: 100%; justify-content: flex-start; background: transparent; color: #1F2937; border: none; text-align: left; padding: 9px 12px; border-radius: 8px; }
    .menu-list .hdr-btn:hover { background: #EEF2F0; }
  </style>""")
cut('    <div class="header-right">', '      <button class="hdr-btn" onclick="doLogout()">', """    <div class="header-right">
      <span class="monk-badge" id="monkBadge">🙏 ภาษาสงฆ์</span>
      <div class="menu-wrap" id="menuWrap">
        <button class="hdr-btn" onclick="toggleMenu()" id="menuBtn">⚙️ ตั้งค่า ▾</button>
        <div class="menu-list" id="adminMenuList">
          <button class="hdr-btn" onclick="showRulesModal()" id="rulesBtn">📐 กฎ (เพิ่ม/ปิดกฎ)</button>
          <button class="hdr-btn" onclick="showTargetsModal()" id="targetsBtn">🎯 เกณฑ์และค่าเป้าหมาย</button>
          <button class="hdr-btn" onclick="showGoldenModal()" id="goldenBtn">✅ บันทึกตัวอย่าง</button>
          <button class="hdr-btn" onclick="showLearnModal()" id="learnBtn">🧠 เรียนรู้ตัวย่อ</button>
          <button class="hdr-btn" onclick="showStatsModal()" id="statsBtn">📊 สถิติการใช้งาน</button>
          <button class="hdr-btn" onclick="showAdminModal()" id="adminBtn">👥 จัดการผู้ใช้</button>
        </div>
      </div>
""")
sub("document.getElementById('statsBtn').style.display = 'inline-flex';", "document.getElementById('statsBtn').style.display = 'inline-flex'; document.getElementById('menuWrap').style.display = 'block';")
sub("document.getElementById('statsBtn').style.display = 'none';", "document.getElementById('statsBtn').style.display = 'none'; document.getElementById('menuWrap').style.display = 'none'; closeMenu();")
sub("    // ===== Admin =====", """    // ===== Admin menu =====
    function closeMenu() { document.getElementById('adminMenuList').classList.remove('open'); }
    function toggleMenu() { document.getElementById('adminMenuList').classList.toggle('open'); }
    document.addEventListener('click', e => { if (!e.target.closest('#menuWrap') || e.target.closest('#adminMenuList .hdr-btn')) closeMenu(); });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closeMenu(); });

    // ===== Admin =====""")

sub("      document.getElementById('statsContent').innerHTML = html;", tagger_ui.STATS_JS)

# the page must not talk to anything but its own origin, and must not carry a dead feature
for banned in ("fonts.googleapis", "openrouter", "knowledge", "kbModal", "customEditor", "customText", "addTag", "patientHistory", "monkAddon", "patterns["):
    assert banned not in s, f"leftover reference: {banned}"
open(DST, "w", encoding="utf-8").write(s)
print(f"wrote {DST}: {len(s):,} bytes")
