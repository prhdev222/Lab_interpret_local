"""HTML + JS of the admin rule editor, inserted into the page by tools/build_ui.py (kept apart so the build script stays readable)."""

MODAL = r'''  <!-- ===== RULES MODAL (admin) ===== -->
  <div class="modal-overlay" id="rulesModal">
    <div class="modal" style="max-width:820px;max-height:92vh;overflow:auto;">
      <h3>📐 กฎที่แพทย์เพิ่ม/ปิดเอง</h3>
      <p style="font-size:12.5px;">กฎที่นี่ใช้กับทุกคนที่ใช้เครื่องนี้ · ระบบตรวจก่อนบันทึกทุกครั้ง กฎที่ไม่ผ่านจะไม่ถูกบันทึก · ข้อความถึงผู้ป่วย <b>ห้ามมีตัวเลข</b> ให้แทรกค่าด้วย {ชื่อค่า} เช่น {LDL}</p>
      <div id="rulesMsg"></div>
      <div id="rulesBody"></div>
      <hr style="margin:14px 0;border:none;border-top:1px solid var(--border);">
      <h3 style="font-size:14px;">🧪 ลองกับบันทึกตัวอย่าง (ยังไม่บันทึกกฎ ไม่เก็บบันทึก)</h3>
      <textarea id="rtNote" spellcheck="false" style="width:100%;min-height:90px;margin-top:6px;font-family:inherit;" placeholder="DM : HbA1c 9&#10;DLP : LDL 170"></textarea>
      <div style="display:flex;gap:8px;margin-top:6px;align-items:center;">
        <input type="text" id="rtAge" inputmode="numeric" maxlength="3" placeholder="อายุ" style="width:80px;">
        <select id="rtSex" style="padding:8px;border:1.5px solid var(--border);border-radius:8px;"><option value="">เพศ ไม่ระบุ</option><option value="M">ชาย</option><option value="F">หญิง</option></select>
        <button class="save" onclick="rulesTry()">ลอง</button>
      </div>
      <div id="rtOut" style="margin-top:8px;font-size:12.5px;line-height:1.6;white-space:pre-wrap;"></div>
      <div class="modal-btns" style="margin-top:14px;">
        <button class="cancel" onclick="closeRulesModal()">ปิด</button>
        <button class="save" onclick="rulesSave()">💾 บันทึกกฎทั้งหมด</button>
      </div>
    </div>
  </div>

'''

JS = r'''    // ===== Rule editor (admin) =====
    let RE = null;                                   // { data, builtin, params, concepts, problems, form, rows, join, editing }
    const OPS = ['<', '<=', '>', '>=', '==', '!='];
    const LEVEL_TH = { ok: 'ดี (ok)', attention: 'ควรระวัง (attention)', alert: 'แจ้งเตือน (alert)', info: 'เฉพาะแพทย์ (info)' };

    async function rulesCall(body) {
      const res = await fetch(API + '/api/admin/rules', { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token }, body: JSON.stringify(body) });
      return res.json();
    }
    function rulesMsg(html, bad) { document.getElementById('rulesMsg').innerHTML = html ? `<div style="margin:8px 0;padding:8px 10px;border-radius:8px;background:${bad ? '#FEE2E2' : '#DCFCE7'};font-size:12.5px;">${html}</div>` : ''; }

    async function showRulesModal() {
      document.getElementById('rulesModal').classList.add('show');
      const d = await rulesCall({ action: 'get' });
      if (d.error) { rulesMsg(esc(d.error), true); return; }
      RE = { ...d, form: null, rows: [], join: 'all', editing: -1 };
      rulesMsg(d.errors.length ? '⚠ พบปัญหาในไฟล์กฎที่มีอยู่:<br>' + d.errors.map(esc).join('<br>') : '', true);
      renderRules();
    }
    function closeRulesModal() { document.getElementById('rulesModal').classList.remove('show'); }

    function flatRows(w) {                           // rule condition -> form rows, or null if the rule is too nested for the form
      const leaf = c => {
        let not = false;
        if (c && c.not) { not = true; c = c.not; }
        if (!c || c.all || c.any || c.not) return null;
        if (c.param !== undefined) return { kind: 'param', not, param: c.param, field: c.field || '', op: c.op, value: c.value };
        if (c.problem !== undefined) return { kind: 'problem', not, problem: c.problem };
        if (c.concept !== undefined) return { kind: 'concept', not, concept: c.concept, is: c.is || 'present' };
        if (c.patient === 'age') return { kind: 'age', not, op: c.op, value: c.value };
        if (c.patient === 'sex') return { kind: 'sex', not, op: c.op, value: c.value };
        return null;
      };
      const list = w.all || w.any || [w];
      const rows = list.map(leaf);
      return rows.includes(null) ? null : { rows, join: w.any ? 'any' : 'all' };
    }
    function rowToCond(r) {
      let c;
      if (r.kind === 'param') { c = { param: r.param, op: r.op, value: Number(r.value) }; if (r.field) c.field = r.field; }
      else if (r.kind === 'problem') c = { problem: r.problem };
      else if (r.kind === 'concept') c = { concept: r.concept, is: r.is };
      else if (r.kind === 'age') c = { patient: 'age', op: r.op, value: Number(r.value) };
      else c = { patient: 'sex', op: r.op === '!=' ? '!=' : '==', value: r.value };
      return r.not ? { not: c } : c;
    }
    function sel(opts, cur, expr) { return `<select onchange="${expr}" style="width:auto;min-width:80px;padding:6px;border:1.5px solid var(--border);border-radius:6px;">` + opts.map(o => `<option value="${esc(o[0])}"${o[0] === cur ? ' selected' : ''}>${esc(o[1])}</option>`).join('') + '</select>'; }

    function renderRules() {
      const E = RE.data.rules || [];
      let h = '<h3 style="font-size:14px;">กฎที่เพิ่มเอง</h3>';
      h += E.length ? '<table class="user-table"><tr><th>เปิด</th><th>รหัส</th><th>เงื่อนไข</th><th>ระดับ</th><th></th></tr>' + E.map((r, i) =>
        `<tr><td><input type="checkbox" ${r.enabled === false ? '' : 'checked'} onchange="ruleToggle(${i})"></td><td>${esc(r.id)}</td><td style="font-size:12px;">${esc(r._describe || '')}</td><td>${esc(r.level)}</td>` +
        `<td><button class="del-btn" onclick="ruleEdit(${i})">แก้</button> <button class="del-btn" onclick="ruleDelete(${i})">ลบ</button></td></tr>`).join('') + '</table>' : '<div style="color:var(--text-light);font-size:12.5px;">ยังไม่มีกฎ</div>';
      h += '<div style="margin-top:8px;"><button class="save" onclick="ruleNew()">➕ เพิ่มกฎใหม่</button></div>';
      if (RE.form) h += renderForm();
      const dis = new Set(RE.data.disable_builtin || []);
      h += '<hr style="margin:14px 0;border:none;border-top:1px solid var(--border);"><h3 style="font-size:14px;">กฎมาตรฐาน — ติ๊ก = ลบ/ปิดกฎนั้น (เมื่อมีมาตรฐานใหม่มาแทน) · ติ๊กออก = เอากลับมาใช้</h3><input type="text" oninput="builtinFilter(this.value)" placeholder="ค้นหากฎ เช่น hba1c, ldl, bp, ckd" style="width:100%;padding:6px;margin-bottom:6px;"><div style="font-size:12px;max-height:240px;overflow:auto;border:1px solid var(--border);border-radius:8px;padding:6px 10px;">' +
        RE.builtin.map(b => `<label class="bl-row" data-q="${esc((b.id + ' ' + b.text).toLowerCase())}" style="display:block;margin:3px 0;"><input type="checkbox" ${dis.has(b.id) ? 'checked' : ''} data-id="${esc(b.id)}" onchange="builtinToggle(this.dataset.id)"> <b>${esc(b.id)}</b> <span style="color:var(--text-light)">${esc(b.text)}</span></label>`).join('') + '</div>';
      document.getElementById('rulesBody').innerHTML = h;
    }

    function renderForm() {
      const f = RE.form, P = RE.params.map(p => [p.name, p.name + (p.unit ? ' (' + p.unit + ')' : '')]), opSel = (i, r) => sel(OPS.map(o => [o, o]), r.op, `rowSet(${i},'op',this.value)`);
      let h = '<div style="margin-top:12px;border:1.5px solid var(--border);border-radius:10px;padding:10px 12px;"><b>' + (RE.editing >= 0 ? 'แก้กฎ' : 'กฎใหม่') + '</b>';
      h += `<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px;"><input type="text" value="${esc(f.id)}" oninput="formSet('id', this.value)" placeholder="รหัสกฎ เช่น my.ldl_dm" style="flex:1;min-width:150px;">` +
        sel(RE.problems.concat(['Custom']).map(x => [x, 'กลุ่ม: ' + x]), f.problem, "formSet('problem', this.value)") +
        sel(Object.keys(LEVEL_TH).map(k => [k, LEVEL_TH[k]]), f.level, "formSet('level', this.value)") + '</div>';
      h += `<div style="margin-top:8px;font-size:12.5px;">เงื่อนไข: ต้องเข้า ${sel([['all', 'ทุกข้อ'], ['any', 'ข้อใดข้อหนึ่ง']], RE.join, 'formJoin(this.value)')}</div>`;
      h += RE.rows.map((r, i) => {
        let c = `<label style="display:inline-flex;gap:4px;align-items:center;"><input type="checkbox" style="width:auto;" ${r.not ? 'checked' : ''} onchange="rowSet(${i},'not',this.checked)"> ไม่ใช่</label> `;
        if (r.kind === 'param') {
          const bp = (RE.params.find(p => p.name === r.param) || {}).kind === 'bp';
          c += sel(P, r.param, `rowParam(${i},this.value)`) +
            sel(bp ? [['sys', 'ตัวบน'], ['dia', 'ตัวล่าง']] : [['', 'ล่าสุด'], ['first', 'ค่าแรก'], ['delta', 'เปลี่ยน (ล่าสุด-แรก)'], ['pct', 'เปลี่ยน %']], r.field || (bp ? 'sys' : ''), `rowSet(${i},'field',this.value)`) +
            opSel(i, r) + ` <input type="text" value="${esc(r.value)}" oninput="rowSet(${i},'value',this.value)" style="width:80px;">`;
        } else if (r.kind === 'problem') c += 'บันทึกมีโรค ' + sel(RE.problems.map(x => [x, x]), r.problem, `rowSet(${i},'problem',this.value)`);
        else if (r.kind === 'concept') c += 'วันนี้ ' + sel(RE.concepts.map(x => [x.id, x.label]), r.concept, `rowConcept(${i},this.value)`) +
          sel(r.concept === 'smoking' ? [['current', 'ยังสูบ'], ['former', 'เลิกแล้ว'], ['never', 'ไม่เคย'], ['not_smoking', 'ไม่สูบ']] : [['present', 'มี'], ['absent', 'ไม่มี']], r.is, `rowSet(${i},'is',this.value)`);
        else if (r.kind === 'age') c += 'อายุ ' + opSel(i, r) + ` <input type="text" value="${esc(r.value)}" oninput="rowSet(${i},'value',this.value)" style="width:70px;">`;
        else c += 'เพศ ' + sel([['M', 'ชาย'], ['F', 'หญิง']], r.value, `rowSet(${i},'value',this.value)`);
        return `<div style="margin-top:6px;display:flex;gap:6px;flex-wrap:wrap;align-items:center;font-size:12.5px;">${c} <button class="del-btn" onclick="rowDel(${i})">ลบข้อ</button></div>`;
      }).join('');
      h += '<div style="margin-top:6px;font-size:12.5px;">เพิ่มข้อ: ' + [['param', 'ค่าแล็บ/ค่าวัด'], ['problem', 'โรคในบันทึก'], ['concept', 'อาการวันนี้'], ['age', 'อายุ'], ['sex', 'เพศ']].map(k => `<button class="del-btn" onclick="rowAdd('${k[0]}')">+ ${k[1]}</button>`).join(' ') + '</div>';
      const ta = (key, label, ph) => `<div style="margin-top:8px;font-size:12.5px;">${label}<textarea oninput="formSet('${key}', this.value)" spellcheck="false" style="width:100%;min-height:52px;font-family:inherit;" placeholder="${ph}">${esc(f[key])}</textarea></div>`;
      h += ta('short', 'ข้อความสั้นถึงผู้ป่วย (ไม่บังคับ · ห้ามมีตัวเลข · ใช้ {LDL} แทนค่า · คำสงฆ์ใช้ {ท่าน} {ทาน} {อาหาร} {ออกกำลัง} {กาย} {นอน})', 'LDL {LDL} สูง ควรปรึกษาแพทย์');
      h += ta('long', 'ข้อความยาวถึงผู้ป่วย (ต้องมีถ้ามีข้อความสั้น)', 'ค่า LDL ของ{ท่าน}คือ {LDL} mg/dL ...');
      h += ta('clinician', 'ข้อความเฉพาะแพทย์ (ไม่บังคับ · มีตัวเลขได้)', 'LDL {LDL} ร่วมกับ DM');
      h += '<div style="margin-top:10px;"><button class="save" onclick="ruleCommit()">ใช้กฎนี้ (ยังไม่บันทึกลงไฟล์ จนกว่าจะกด 💾)</button> <button class="cancel" onclick="ruleCancel()">ยกเลิก</button></div></div>';
      return h;
    }

    function formSet(k, v) { RE.form[k] = v; }
    function formLevel(v) { RE.form.level = v; }
    function formJoin(v) { RE.join = v; }
    function rowSet(i, k, v) { RE.rows[i][k] = v; }
    function rowParam(i, v) { RE.rows[i].param = v; RE.rows[i].field = ''; renderRules(); }
    function rowConcept(i, v) { RE.rows[i].concept = v; RE.rows[i].is = v === 'smoking' ? 'current' : 'present'; renderRules(); }
    function rowDel(i) { RE.rows.splice(i, 1); renderRules(); }
    function rowAdd(kind) {
      const base = { param: { kind, not: false, param: RE.params[0].name, field: '', op: '>=', value: '' }, problem: { kind, not: false, problem: RE.problems[0] },
        concept: { kind, not: false, concept: RE.concepts[0].id, is: 'present' }, age: { kind, not: false, op: '>=', value: '' }, sex: { kind, not: false, op: '==', value: 'M' } }[kind];
      RE.rows.push(base); renderRules();
    }
    function ruleNew() { RE.form = { id: '', problem: 'Custom', level: 'attention', short: '', long: '', clinician: '' }; RE.rows = []; RE.join = 'all'; RE.editing = -1; renderRules(); }
    function ruleCancel() { RE.form = null; renderRules(); }
    function ruleEdit(i) {
      const r = RE.data.rules[i], fr = flatRows(r.when);
      if (!fr) { rulesMsg('กฎนี้ซ้อนเงื่อนไขเกินกว่าฟอร์มจะแสดง · แก้ได้ที่ไฟล์ data/custom_rules.json (กฎยังทำงานตามปกติ)', true); return; }
      RE.form = { id: r.id, problem: r.problem || 'Custom', level: r.level, short: (r.patient || {}).short || '', long: (r.patient || {}).long || '', clinician: r.clinician || '' };
      RE.rows = fr.rows; RE.join = fr.join; RE.editing = i; renderRules();
    }
    function ruleCommit() {
      const f = RE.form;
      if (!RE.rows.length) { rulesMsg('ต้องมีเงื่อนไขอย่างน้อยหนึ่งข้อ', true); return; }
      const conds = RE.rows.map(rowToCond), rule = { id: f.id.trim(), enabled: true, problem: f.problem, level: f.level, when: conds.length === 1 ? conds[0] : { [RE.join]: conds } };
      if (f.short.trim() || f.long.trim()) rule.patient = { short: f.short.trim(), long: f.long.trim() };
      if (f.clinician.trim()) rule.clinician = f.clinician.trim();
      if (RE.editing >= 0) { rule.enabled = RE.data.rules[RE.editing].enabled !== false; RE.data.rules[RE.editing] = rule; } else RE.data.rules.push(rule);
      RE.form = null; rulesMsg('เพิ่มเข้ารายการแล้ว กด 💾 บันทึกกฎทั้งหมด เพื่อให้ระบบตรวจและใช้งาน หรือกด "ลอง" เพื่อทดสอบก่อน', false); renderRules();
    }
    function ruleToggle(i) { const r = RE.data.rules[i]; r.enabled = r.enabled === false; }
    function ruleDelete(i) { RE.data.rules.splice(i, 1); RE.form = null; renderRules(); }
    function builtinFilter(q) {
      q = q.trim().toLowerCase();
      document.querySelectorAll('#rulesBody .bl-row').forEach(el => { el.style.display = !q || el.dataset.q.includes(q) ? 'block' : 'none'; });
    }
    function builtinToggle(id) {
      const s = new Set(RE.data.disable_builtin || []);
      if (s.has(id)) s.delete(id); else s.add(id);
      RE.data.disable_builtin = [...s];
    }
    function cleanData() {                           // what is sent: only the fields the file format knows
      return { disable_builtin: RE.data.disable_builtin || [], rules: (RE.data.rules || []).map(r => { const { _describe, ...rest } = r; return rest; }) };
    }
    async function rulesTry() {
      if (!RE) return;
      const d = await rulesCall({ action: 'try', data: cleanData(), note: document.getElementById('rtNote').value, age: document.getElementById('rtAge').value || null, sex: document.getElementById('rtSex').value });
      if (d.error) { document.getElementById('rtOut').textContent = d.error; return; }
      document.getElementById('rtOut').innerHTML = (d.errors.length ? '<div style="color:#B91C1C">⚠ ' + d.errors.map(esc).join('<br>⚠ ') + '</div>' : '') +
        `<div><b>กฎที่เพิ่มเองที่ทำงาน:</b> ${d.fired.length ? esc(d.fired.join(', ')) : 'ไม่มี'}</div><hr><div>${esc(d.result)}</div><hr><div>${d.clinician.map(n => esc(n.icon + ' ' + n.text)).join('<br>')}</div>`;
    }
    function impactHtml(d, confirmFn) {
      let h = '';
      if (d.warnings && d.warnings.length) h += '<div style="color:#B45309;"><b>⚠ ควรตรวจสอบ</b><br>' + d.warnings.map(esc).join('<br>') + '</div>';
      if (d.violated && d.violated.length) h += '<div style="color:#B91C1C;margin-top:6px;"><b>❗ เปลี่ยนผลของตัวอย่างที่แพทย์เคยยืนยันแล้ว:</b> ' + d.violated.map(esc).join(', ') + '</div>';
      if (d.diffs && d.diffs.length) {
        h += '<div style="margin-top:6px;"><b>ผลที่จะเปลี่ยนกับบันทึกตัวอย่าง (' + d.diffs.length + ' ข้อ)</b></div>' + d.diffs.map(x =>
          `<div style="margin-top:6px;padding:6px 8px;border:1px solid var(--border);border-radius:8px;background:#fff;"><div style="font-size:12px;color:var(--text-light);white-space:pre-wrap;">${esc(x.id)}${x.confirmed ? ' ✓ยืนยันแล้ว' : ''} · ${esc(x.note)}</div>` +
          x.removed.map(r => `<div style="text-decoration:line-through;color:#6B7280;">${esc(r.text)}</div>`).join('') + x.added.map(r => `<div>${esc(r.text)}</div>`).join('') +
          (x.notes_removed.length || x.notes_added.length ? `<div style="font-size:12px;color:var(--text-light);">เฉพาะแพทย์: ${x.notes_removed.map(k => '− ' + esc(k)).concat(x.notes_added.map(k => '+ ' + esc(k))).join(' · ')}</div>` : '') +
          (x.error ? '<div style="color:#B91C1C">เกิดข้อผิดพลาดกับตัวอย่างนี้ (' + esc(x.error) + ')</div>' : '') + '</div>').join('');
      }
      return h + `<div style="margin-top:8px;"><button class="save" onclick="${confirmFn}()">ยืนยันและบันทึก</button> <span style="font-size:12px;">หรือปิดหน้าต่างเพื่อยกเลิก</span></div>`;
    }
    async function rulesConfirm() { await rulesSave(true); }
    async function rulesSave(confirm) {
      if (!RE) return;
      const d = await rulesCall({ action: 'save', data: cleanData(), confirm: !!confirm });
      if (d.needsConfirm) { rulesMsg(impactHtml(d, 'rulesConfirm'), true); return; }
      if (d.error) { rulesMsg(esc(d.error), true); return; }
      if (!d.success) { rulesMsg('❌ ยังไม่ได้บันทึก เพราะมีกฎที่ไม่ผ่านการตรวจ:<br>' + d.errors.map(esc).join('<br>'), true); return; }
      rulesMsg('✅ บันทึกแล้ว ใช้ได้ทันทีโดยไม่ต้องรีสตาร์ต (สำรองฉบับก่อนหน้าไว้ที่ data/custom_rules.json.bak)', false);
      const g = await rulesCall({ action: 'get' }); RE = { ...g, form: null, rows: [], join: 'all', editing: -1 }; renderRules();
    }

'''


TARGETS_MODAL = r'''  <!-- ===== TARGETS MODAL (admin) ===== -->
  <div class="modal-overlay" id="targetsModal">
    <div class="modal" style="max-width:820px;max-height:92vh;overflow:auto;">
      <h3>🎯 เกณฑ์และค่าเป้าหมาย</h3>
      <p style="font-size:12.5px;">แก้ตัวเลขเกณฑ์ที่กฎมาตรฐานใช้ · มีผลกับทุกคนทันที · ระบบตรวจลำดับค่าก่อนบันทึก (เช่น G1 > G2 > G3a) ถ้าไม่ผ่านจะไม่บันทึกอะไรเลย · ช่อง "อ้างอิง" ควรใส่ฉบับแนวทางที่ใช้ แล้วติ๊กว่าอ้างอิงแล้ว</p>
      <div id="targetsMsg"></div>
      <div id="targetsBody"></div>
      <div class="modal-btns" style="margin-top:14px;">
        <button class="cancel" onclick="closeTargetsModal()">ปิด</button>
        <button class="save" onclick="targetsSave()">💾 บันทึกเกณฑ์ที่แก้</button>
      </div>
    </div>
  </div>

'''

TARGETS_JS = r'''    // ===== Thresholds editor (admin) =====
    let TG = null;                                   // { rows, groups, cur: {path: value}, changes: {path: value} }
    function targetsMsg(html, bad) { document.getElementById('targetsMsg').innerHTML = html ? `<div style="margin:8px 0;padding:8px 10px;border-radius:8px;background:${bad ? '#FEE2E2' : '#DCFCE7'};font-size:12.5px;">${html}</div>` : ''; }
    async function targetsCall(body) {
      const res = await fetch(API + '/api/admin/targets', { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token }, body: JSON.stringify(body) });
      return res.json();
    }
    async function showTargetsModal() {
      document.getElementById('targetsModal').classList.add('show');
      const d = await targetsCall({ action: 'get' });
      if (d.error) { targetsMsg(esc(d.error), true); return; }
      TG = { ...d, cur: {}, changes: {} };
      d.rows.forEach(r => { TG.cur[r.path] = r.kind === 'pair' ? r.value.slice() : r.value; });
      targetsMsg(esc(d.status) + (d.lastEdit ? ' · แก้ผ่านหน้าเว็บล่าสุด ' + esc(d.lastEdit) : ''), true);
      renderTargets();
    }
    function closeTargetsModal() { document.getElementById('targetsModal').classList.remove('show'); }
    function renderTargets() {
      const order = [], by = {};
      TG.rows.forEach(r => { if (!by[r.group]) { by[r.group] = []; order.push(r.group); } by[r.group].push(r); });
      const inp = (r, idx) => `<input type="text" inputmode="decimal" value="${esc(idx === null ? r.value : r.value[idx])}" oninput="targetSet(this,${JSON.stringify(r.path).replace(/"/g, '&quot;')},'${r.kind}',${idx})" style="width:90px;padding:5px;">`;
      document.getElementById('targetsBody').innerHTML = order.map(g => `<div style="margin-top:12px;border:1px solid var(--border);border-radius:10px;padding:8px 12px;"><b style="font-size:13px;">${esc(TG.groups[g] || g)}</b>` +
        by[g].map(r => {
          let c;
          if (r.kind === 'num') c = inp(r, null);
          else if (r.kind === 'pair') c = inp(r, 0) + ' , ' + inp(r, 1);
          else if (r.kind === 'bool') c = `<input type="checkbox" ${r.value ? 'checked' : ''} onchange="targetSet(this,${JSON.stringify(r.path).replace(/"/g, '&quot;')},'bool',null)" style="width:auto;">`;
          else c = `<input type="text" value="${esc(r.value)}" oninput="targetSet(this,${JSON.stringify(r.path).replace(/"/g, '&quot;')},'text',null)" style="width:100%;padding:5px;">`;
          return `<div style="display:flex;gap:10px;align-items:center;margin-top:6px;font-size:12.5px;flex-wrap:wrap;"><span style="min-width:230px;flex:0 0 auto;">${esc(r.label)}</span>${c}</div>`;
        }).join('') + '</div>').join('');
    }
    function targetSet(el, path, kind, idx) {
      let v;
      if (kind === 'bool') v = el.checked;
      else if (kind === 'text') v = el.value;
      else if (kind === 'pair') { v = TG.cur[path].slice(); v[idx] = el.value.trim() === '' ? NaN : Number(el.value); }
      else v = el.value.trim() === '' ? NaN : Number(el.value);
      TG.cur[path] = v;
      const orig = TG.rows.find(r => r.path === path).value;
      const same = JSON.stringify(v) === JSON.stringify(orig);
      if (same) delete TG.changes[path]; else TG.changes[path] = v;
      el.style.borderColor = same ? '' : '#F59E0B';
    }
    async function targetsConfirm() { await targetsSave(true); }
    async function targetsSave(confirm) {
      if (!TG) return;
      if (!Object.keys(TG.changes).length) { targetsMsg('ยังไม่ได้แก้ค่าใด', true); return; }
      const d = await targetsCall({ action: 'save', changes: TG.changes, confirm: !!confirm });
      if (d.error) { targetsMsg(esc(d.error), true); return; }
      if (d.needsConfirm) { targetsMsg(impactHtml(d, 'targetsConfirm'), true); return; }
      if (!d.success) { targetsMsg('❌ ยังไม่ได้บันทึก:<br>' + d.errors.map(esc).join('<br>'), true); return; }
      await showTargetsModal();
      targetsMsg('✅ บันทึกแล้ว (' + d.changed.map(esc).join(', ') + ') ใช้ได้ทันที · สำรองฉบับก่อนหน้าที่ data/targets.json.bak · เอกสารตรวจกฎ docs/RULES_REVIEW.md อัปเดตแล้ว', false);
    }

'''


GOLDEN_MODAL = r'''  <!-- ===== GOLDEN CASES MODAL (admin) ===== -->
  <div class="modal-overlay" id="goldenModal">
    <div class="modal" style="max-width:820px;max-height:92vh;overflow:auto;">
      <h3>✅ บันทึกตัวอย่างสำหรับตรวจผลกระทบ</h3>
      <p style="font-size:12.5px;">ก่อนบันทึกการแก้เกณฑ์หรือกฎ ระบบจะรันตัวอย่างเหล่านี้ แล้วบอกว่าผลเปลี่ยนตรงไหน · ติ๊ก "ยืนยันว่าถูก" เมื่อแพทย์ตรวจผลของตัวอย่างนั้นแล้ว (ถ้าการแก้ครั้งหน้าทำให้ผลเปลี่ยน จะแจ้งเป็นพิเศษ) · <b style="color:#B91C1C">ห้ามใส่ข้อมูลผู้ป่วยจริง</b> ใช้ตัวอย่างสมมติเท่านั้น</p>
      <div id="goldenMsg"></div>
      <div style="border:1.5px solid var(--border);border-radius:10px;padding:8px 12px;">
        <b style="font-size:13px;">เพิ่มตัวอย่างใหม่ (สมมติ)</b>
        <textarea id="gcNote" spellcheck="false" style="width:100%;min-height:70px;margin-top:6px;font-family:inherit;" placeholder="DM : HbA1c 7.4"></textarea>
        <div style="display:flex;gap:8px;margin-top:6px;align-items:center;">
          <input type="text" id="gcAge" inputmode="numeric" maxlength="3" placeholder="อายุ" style="width:80px;">
          <select id="gcSex" style="padding:8px;border:1.5px solid var(--border);border-radius:8px;"><option value="">เพศ ไม่ระบุ</option><option value="M">ชาย</option><option value="F">หญิง</option></select>
          <button class="save" onclick="goldenAdd()">เพิ่ม</button>
        </div>
      </div>
      <div id="goldenBody"></div>
      <div class="modal-btns" style="margin-top:14px;"><button class="cancel" onclick="closeGoldenModal()">ปิด</button></div>
    </div>
  </div>

'''

GOLDEN_JS = r'''    // ===== Golden cases (admin) =====
    async function goldenCall(body) {
      const res = await fetch(API + '/api/admin/golden', { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token }, body: JSON.stringify(body) });
      return res.json();
    }
    function goldenMsg(html, bad) { document.getElementById('goldenMsg').innerHTML = html ? `<div style="margin:8px 0;padding:8px 10px;border-radius:8px;background:${bad ? '#FEE2E2' : '#DCFCE7'};font-size:12.5px;">${html}</div>` : ''; }
    async function showGoldenModal() { document.getElementById('goldenModal').classList.add('show'); await renderGolden(); }
    function closeGoldenModal() { document.getElementById('goldenModal').classList.remove('show'); }
    async function renderGolden() {
      const d = await goldenCall({ action: 'list' });
      if (d.error) { goldenMsg(esc(d.error), true); return; }
      const done = d.cases.filter(c => c.confirmed).length;
      goldenMsg(`ตัวอย่าง ${d.cases.length} ข้อ · แพทย์ยืนยันแล้ว ${done} ข้อ`, false);
      document.getElementById('goldenBody').innerHTML = d.cases.map(c => `<details style="margin-top:8px;border:1px solid var(--border);border-radius:8px;padding:6px 10px;"><summary style="cursor:pointer;font-size:12.5px;">` +
        `${c.confirmed ? '✓' : '○'} ${esc(c.id)} · ${esc(c.note.replace(/\n/g, ' ⏎ ').slice(0, 90))}${c.changedSinceConfirmed ? ' <b style="color:#B91C1C">⚠ ผลเปลี่ยนจากที่ยืนยัน</b>' : ''}</summary>` +
        `<div style="font-size:12px;color:var(--text-light);margin-top:4px;white-space:pre-wrap;">อายุ ${esc(c.age ?? '-')} · เพศ ${esc(c.sex || '-')}\n${esc(c.note)}</div>` +
        `<div style="white-space:pre-wrap;font-size:12.5px;margin-top:6px;">${esc(c.patient)}</div><div style="font-size:12px;margin-top:6px;">${c.clinician.map(t => 'ℹ️ ' + esc(t)).join('<br>')}</div>` +
        `<div style="margin-top:8px;"><label style="font-size:12.5px;"><input type="checkbox" style="width:auto;" ${c.confirmed ? 'checked' : ''} data-id="${esc(c.id)}" onchange="goldenConfirm(this.dataset.id, this.checked)"> แพทย์ตรวจแล้ว ผลนี้ถูกต้อง</label> ` +
        `<button class="del-btn" data-id="${esc(c.id)}" onclick="goldenDelete(this.dataset.id)">ลบตัวอย่าง</button></div></details>`).join('');
    }
    async function goldenAdd() {
      const d = await goldenCall({ action: 'add', note: document.getElementById('gcNote').value, age: document.getElementById('gcAge').value || null, sex: document.getElementById('gcSex').value });
      if (d.error) { goldenMsg(esc(d.error), true); return; }
      document.getElementById('gcNote').value = ''; await renderGolden();
    }
    async function goldenConfirm(id, checked) { await goldenCall({ action: 'confirm', id, confirmed: checked }); await renderGolden(); }
    async function goldenDelete(id) { await goldenCall({ action: 'delete', id }); await renderGolden(); }

'''


LEARN_BOX = r'''            <div id="learnBox" class="no-print" style="display:none;margin:10px 0;border:1.5px dashed var(--border);border-radius:10px;padding:8px 12px;font-size:12.5px;"></div>
'''

LEARN_MODAL = r'''  <!-- ===== LEARNING LOG MODAL (admin) ===== -->
  <div class="modal-overlay" id="learnModal">
    <div class="modal" style="max-width:700px;max-height:92vh;overflow:auto;">
      <h3>🧠 เก็บตัวอย่างเพื่อให้ระบบเรียนรู้ตัวย่อ</h3>
      <p style="font-size:12.5px;">ปิดอยู่เป็นค่าตั้งต้น · เมื่อเปิด แพทย์จะเห็นปุ่ม "บันทึกตัวอย่างนี้เพื่อปรับปรุง" ในหน้าผลลัพธ์ และเลือกเก็บเป็นรายเคส · ที่เก็บคือ <b>เฉพาะคำย่อ/ตัวเลข/ชื่อบรรทัดโรค</b> ไม่เก็บข้อความบันทึก อายุ เพศ วันที่ ชื่อผู้ใช้ · ข้อมูลนี้มาจากผู้ป่วย ควรได้รับอนุญาตจาก DPO ของ รพ. ก่อนเปิดใช้</p>
      <div id="learnAdminMsg"></div>
      <label style="font-size:13px;"><input type="checkbox" id="learnToggle" style="width:auto;" onchange="learnAdminSet(this.checked)"> เปิดการเก็บตัวอย่าง</label>
      <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap;">
        <button class="save" onclick="learnAdminExport()">ดูข้อมูลที่เก็บไว้ (สำเนาไปใช้กับ learn_terms.py ได้)</button>
        <button class="cancel" onclick="learnAdminClear()">ล้างทั้งหมด</button>
      </div>
      <textarea id="learnOut" readonly spellcheck="false" style="display:none;width:100%;min-height:160px;margin-top:10px;font-family:monospace;font-size:11px;"></textarea>
      <hr style="margin:14px 0;border:none;border-top:1px solid var(--border);">
      <h3 style="font-size:14px;">💡 ข้อเสนอคำใหม่จากข้อมูลที่เก็บไว้</h3>
      <p style="font-size:12.5px;">ระบบเสนอว่าคำย่อที่ไม่รู้จักน่าจะหมายถึงอะไร · <b>ไม่เพิ่มเองเลย</b> แพทย์ติ๊กเฉพาะข้อที่ถูก แล้วกดใช้ · ระบบปฏิเสธคำที่ซ้ำกับคำเดิม และปฏิเสธถ้าทำให้ที่เคยอ่านถูกกลับอ่านต่างไป · เมื่อเพิ่มคำแล้ว สถานะลงนามกลับเป็น DRAFT ต้องลงนามใหม่</p>
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;"><label style="font-size:12.5px;">พบอย่างน้อย <input type="text" id="sgMin" value="3" inputmode="numeric" maxlength="2" style="width:50px;padding:5px;display:inline-block;"> ครั้ง</label><button class="save" onclick="learnSuggest()">สร้างข้อเสนอ</button></div>
      <div id="sgBody" style="margin-top:8px;"></div>
      <div class="modal-btns" style="margin-top:14px;"><button class="cancel" onclick="closeLearnModal()">ปิด</button></div>
    </div>
  </div>

'''

LEARN_JS = r'''    // ===== Learning log =====
    async function learnCall(path, body) {
      const res = await fetch(API + path, { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token }, body: JSON.stringify(body) });
      return res.json();
    }
    function learnInit(enabled) {
      const box = document.getElementById('learnBox');
      box.style.display = enabled ? 'block' : 'none';
      box.innerHTML = enabled ? '<button class="del-btn" onclick="learnPreview()">🧠 บันทึกตัวอย่างนี้เพื่อปรับปรุงระบบ</button> <span style="color:var(--text-light)">ดูก่อนว่าจะเก็บอะไร ยังไม่เก็บจนกว่าจะยืนยัน</span>' : '';
    }
    async function learnPreview() {
      const d = await learnCall('/api/learn', { action: 'preview', note: document.getElementById('labValues').value });
      const box = document.getElementById('learnBox');
      if (d.error) { box.innerHTML = '<span style="color:#B91C1C">' + esc(d.error) + '</span>'; return; }
      box.innerHTML = '<b>จะเก็บเฉพาะรายการนี้ (ไม่เก็บข้อความบันทึก อายุ เพศ วันที่):</b><div style="margin:6px 0;">' + (d.rows.length ? d.rows.map(r => '• ' + esc(r)).join('<br>') : 'ไม่มีอะไรให้เก็บ') + '</div>' +
        (d.rows.length ? '<button class="save" onclick="learnSave()">ยืนยันเก็บ</button> ' : '') + '<button class="cancel" onclick="learnInit(true)">ยกเลิก</button>';
    }
    async function learnSave() {
      const d = await learnCall('/api/learn', { action: 'save', note: document.getElementById('labValues').value });
      document.getElementById('learnBox').innerHTML = d.error ? '<span style="color:#B91C1C">' + esc(d.error) + '</span>' : '✅ เก็บแล้ว ' + esc(d.stored) + ' รายการ';
    }
    function learnAdminMsg(st) { document.getElementById('learnAdminMsg').innerHTML = `<div style="margin:8px 0;padding:8px 10px;border-radius:8px;background:#EEF2FF;font-size:12.5px;">สถานะ: ${st.enabled ? 'เปิด' : 'ปิด'} · เก็บไว้ ${esc(st.rows)} รายการ (สูงสุด ${esc(st.max)})</div>`; document.getElementById('learnToggle').checked = !!st.enabled; }
    async function showLearnModal() { document.getElementById('learnModal').classList.add('show'); document.getElementById('learnOut').style.display = 'none'; document.getElementById('sgBody').innerHTML = ''; learnAdminMsg(await learnCall('/api/admin/learning', { action: 'status' })); }
    function closeLearnModal() { document.getElementById('learnModal').classList.remove('show'); }
    async function learnAdminSet(on) { learnAdminMsg(await learnCall('/api/admin/learning', { action: 'set', enabled: on })); }
    async function learnAdminExport() { const d = await learnCall('/api/admin/learning', { action: 'export' }); const o = document.getElementById('learnOut'); o.style.display = 'block'; o.value = JSON.stringify(d); }
    async function learnAdminClear() { learnAdminMsg(await learnCall('/api/admin/learning', { action: 'clear' })); document.getElementById('learnOut').style.display = 'none'; }
    let SG = [];
    const SG_EV = { median_here: 'ค่ากลางที่พบ', median_known: 'ค่ากลางของค่าที่รู้จัก', inside_range: 'อยู่ในช่วงที่เป็นไปได้', line_context: 'บรรทัดโรคตรงกัน', spelling: 'สะกดใกล้กัน', range_specificity: 'ช่วงค่าแคบ (ชี้ชัด)', known_param_also_in_same_line: 'ค่านี้เขียนอยู่ในบรรทัดเดียวกันแล้ว (ยิ่งสูงยิ่งไม่น่าใช่ชื่อแทน)' };
    const SG_KIND = { param_alias: 'ค่า', concept_phrase: 'อาการ', problem_alias: 'ชื่อโรค' };
    async function learnSuggest() {
      const d = await learnCall('/api/admin/learning', { action: 'suggest', minCount: parseInt(document.getElementById('sgMin').value, 10) || 3 });
      const box = document.getElementById('sgBody');
      if (d.error) { box.innerHTML = '<span style="color:#B91C1C">' + esc(d.error) + '</span>'; return; }
      SG = d.suggestions.filter(s => s.target);
      if (!SG.length) { box.innerHTML = '<div style="font-size:12.5px;">ยังไม่มีข้อเสนอ (ข้อมูลที่เก็บไว้ ' + esc(d.rows) + ' แถว ยังไม่พอ หรือทุกคำอยู่ในพจนานุกรมแล้ว) · ลองลดจำนวนครั้งขั้นต่ำ</div>'; return; }
      box.innerHTML = SG.map((s, i) => `<label style="display:block;margin-top:6px;padding:6px 8px;border:1px solid var(--border);border-radius:8px;font-size:12.5px;text-transform:none;font-weight:400;">` +
        `<input type="checkbox" style="width:auto;" id="sg${i}"> <b>${esc(s.term)}</b> → <b>${esc(s.target)}</b> <span style="color:var(--text-light)">(${esc(SG_KIND[s.kind] || s.kind)} · พบ ${esc(s.notes)} ครั้ง · คะแนน ${esc(s.score)}</span>` +
        (s.confidence === 'low' ? ' <span style="color:#B45309">· ไม่แน่ใจ ตรวจให้ดี</span>' : '') + `)<div style="color:var(--text-light);margin-left:22px;">${esc(typeof s.evidence === 'string' ? s.evidence : Object.entries(s.evidence).map(([k, v]) => (SG_EV[k] || k) + ' ' + v).join(' · '))}` +
        (s.alternatives.length ? ' · ตัวเลือกอื่น: ' + s.alternatives.map(a => esc(a.target) + ' ' + esc(a.score)).join(', ') : '') + '</div></label>').join('') +
        '<div style="margin-top:8px;"><button class="save" onclick="learnApply()">ใช้ข้อที่เลือก</button></div>';
    }
    async function learnApply() {
      const chosen = SG.filter((s, i) => document.getElementById('sg' + i) && document.getElementById('sg' + i).checked).map(s => ({ kind: s.kind, term: s.term, target: s.target }));
      if (!chosen.length) { document.getElementById('learnAdminMsg').innerHTML = '<div style="margin:8px 0;padding:8px 10px;border-radius:8px;background:#FEE2E2;font-size:12.5px;">ยังไม่ได้ติ๊กข้อใด</div>'; return; }
      const d = await learnCall('/api/admin/learning', { action: 'apply', minCount: parseInt(document.getElementById('sgMin').value, 10) || 3, selected: chosen });
      const msg = d.error ? esc(d.error) : d.success ? '✅ เพิ่มแล้ว: ' + d.applied.map(esc).join(', ') + (d.refused.length ? '<br>ไม่ได้เพิ่ม: ' + d.refused.map(esc).join('; ') : '') + '<br>สถานะลงนามกลับเป็น DRAFT ต้องตรวจและลงนามใหม่ · สำรองพจนานุกรมเดิมที่ data/lexicon.json.bak'
        : '❌ ยังไม่ได้เพิ่ม' + (d.refused && d.refused.length ? '<br>' + d.refused.map(esc).join('; ') : '') + (d.regression && d.regression.length ? '<br>จะทำให้บันทึกที่เคยอ่านถูกอ่านต่างไป:<br>' + d.regression.map(esc).join('<br>') : '');
      document.getElementById('learnAdminMsg').innerHTML = `<div style="margin:8px 0;padding:8px 10px;border-radius:8px;background:${d.success ? '#DCFCE7' : '#FEE2E2'};font-size:12.5px;">${msg}</div>`;
      if (d.success) await learnSuggest();
    }

'''


SIGN_MODAL = r'''  <!-- ===== SIGN-OFF MODAL (admin) ===== -->
  <div class="modal-overlay" id="signModal">
    <div class="modal" style="max-width:700px;max-height:92vh;overflow:auto;">
      <h3>✍️ ลงนามรับรองกฎและเกณฑ์</h3>
      <p style="font-size:12.5px;">ลงนามได้เมื่อแพทย์ตรวจครบ (ระบุอ้างอิงทุกกลุ่ม และยืนยันผลตัวอย่างทุกข้อ) · การลงนามผูกกับเนื้อหาที่ตรวจ ถ้าแก้เกณฑ์ ถ้อยคำ พจนานุกรม หรือกฎหลังลงนาม สถานะจะกลับเป็น DRAFT เอง · ระบบบันทึกชื่อผู้ลงนามและวันที่เท่านั้น ไม่ได้ตัดสินความถูกต้องทางคลินิก</p>
      <div id="signMsg"></div>
      <div id="signBody"></div>
      <div class="modal-btns" style="margin-top:14px;"><button class="cancel" onclick="closeSignModal()">ปิด</button></div>
    </div>
  </div>

'''

SIGN_JS = r'''    // ===== Sign-off (admin) =====
    async function signCall(body) {
      const res = await fetch(API + '/api/admin/signoff', { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token }, body: JSON.stringify(body) });
      return res.json();
    }
    function signMsg(html, bad) { document.getElementById('signMsg').innerHTML = html ? `<div style="margin:8px 0;padding:8px 10px;border-radius:8px;background:${bad ? '#FEE2E2' : '#DCFCE7'};font-size:12.5px;">${html}</div>` : ''; }
    async function showSignModal() { document.getElementById('signModal').classList.add('show'); await renderSign(); }
    function closeSignModal() { document.getElementById('signModal').classList.remove('show'); }
    async function renderSign() {
      const d = await signCall({ action: 'status' });
      if (d.error) { signMsg(esc(d.error), true); return; }
      signMsg('สถานะตอนนี้: <b>' + esc(d.status) + '</b>', !d.state.signed);
      let h = d.blockers.length ? '<div style="margin-top:8px;"><b>ยังลงนามไม่ได้ เพราะ:</b><br>' + d.blockers.map(b => '✗ ' + esc(b)).join('<br>') + '</div>' : '<div style="margin-top:8px;">✓ เงื่อนไขครบ พร้อมลงนาม</div>';
      h += `<div style="margin-top:10px;"><input type="text" id="signName" maxlength="60" placeholder="ชื่อผู้ตรวจรับรอง เช่น นพ.สมชาย ใจดี" style="width:100%;padding:8px;"></div>` +
        `<div style="margin-top:6px;"><input type="text" id="signPhrase" placeholder="พิมพ์ ${esc(d.phrase)} เพื่อยืนยัน" style="width:100%;padding:8px;"></div>` +
        '<div style="margin-top:8px;"><button class="save" onclick="signDo()">ลงนามรับรอง</button> ' + (d.state.signed || d.state.edited_after ? '<button class="cancel" onclick="signRevoke()">ถอนการลงนาม</button>' : '') + '</div>';
      if (d.history.length) h += '<div style="margin-top:10px;font-size:12px;color:var(--text-light);">ประวัติ: ' + d.history.map(x => esc(x.date) + ' ' + (x.action === 'sign' ? 'ลงนามโดย ' : 'ถอนโดย ') + esc(x.by)).join(' · ') + '</div>';
      document.getElementById('signBody').innerHTML = h;
    }
    async function signDo() {
      const d = await signCall({ action: 'sign', name: document.getElementById('signName').value, phrase: document.getElementById('signPhrase').value });
      if (d.error) { signMsg(esc(d.error), true); return; }
      await renderSign();
      if (!d.success) signMsg('❌ ยังไม่ได้ลงนาม:<br>' + d.errors.map(esc).join('<br>'), true);
    }
    async function signRevoke() { await signCall({ action: 'revoke' }); await renderSign(); }

'''
