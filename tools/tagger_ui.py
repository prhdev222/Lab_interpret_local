"""Page pieces for the optional number tagger (server started with --tagger). Kept apart like rules_editor_ui.py."""

BOX = r'''            <div id="suggestBox" class="no-print" style="display:none;margin:10px 0;border:1.5px solid #F0B35A;background:#FFFBEB;border-radius:10px;padding:8px 12px;font-size:12.5px;line-height:1.8;"></div>
'''

TOGGLE = r'''
            <label id="tgRow" class="no-print" style="display:none;margin-top:6px;font-size:12.5px;cursor:pointer;"><input type="checkbox" id="tgToggle" onchange="suggestToggle()"> 💡 ตัวช่วยเดาด้วย ML (ทดลอง) <span style="color:var(--text-light)">— ปิด = ใช้ระบบกฎอย่างเดียว เปิด = กฎอ่านก่อน แล้ว ML เสนอเฉพาะตัวเลขที่กฎอ่านไม่ออก (ต้องกดยืนยัน)</span></label>'''

JS = r'''
    // ===== Number tagger suggestions (optional, experimental; the doctor must press a button for each one) =====
    let suggestNote = '', suggestItems = [];
    function suggestOn() { return document.getElementById('tgToggle').checked; }
    async function suggestStatus() {
      try {
        const d = await learnCall('/api/suggest', { action: 'status' });
        document.getElementById('tgRow').style.display = d.available ? 'block' : 'none';
        let saved = false; try { saved = localStorage.getItem('lab_tagger') === '1'; } catch (e) { /* private window: stays off */ }
        document.getElementById('tgToggle').checked = !!d.available && saved;
      } catch (e) { document.getElementById('tgRow').style.display = 'none'; }
    }
    function suggestToggle() {
      try { localStorage.setItem('lab_tagger', suggestOn() ? '1' : '0'); } catch (e) { /* not essential */ }
      const box = document.getElementById('suggestBox');
      suggestItems = []; box.style.display = 'none'; box.innerHTML = '';
      if (suggestOn() && suggestNote) suggestLoad(suggestNote);
    }
    function suggestInit(enabled, note) {
      suggestNote = note; suggestItems = [];
      const box = document.getElementById('suggestBox');
      box.style.display = 'none'; box.innerHTML = '';
      if (enabled && suggestOn()) suggestLoad(note);
    }
    async function suggestLoad(note) {
      const d = await learnCall('/api/suggest', { action: 'suggest', note });
      if (!d.available || !d.items || !d.items.length) return;
      suggestItems = d.items; suggestRender();
    }
    function suggestRender() {
      const box = document.getElementById('suggestBox');
      const rows = [];
      suggestItems.forEach((it, i) => {
        if (!it) return;
        const nm = it.name ? '“' + esc(it.name) + '”' : 'ตัวเลข';
        const act = it.name
          ? `<button class="save" onclick="suggestAccept(${i})">ใช้ ${esc(it.alias)} แทน “${esc(it.name)}” แล้วอ่านใหม่</button>`
          : '<span style="color:var(--text-light)">(ไม่พบชื่อให้แก้ ถ้าถูกให้แก้บันทึกเอง)</span>';
        rows.push(`<div>• ${nm} = ${esc(it.values.join(', '))} → น่าจะเป็น <b>${esc(it.label)}</b> (มั่นใจ ${Math.round(it.conf * 100)}%) ${act} <button class="cancel" onclick="suggestReject(${i})">ไม่ใช่</button></div>`);
      });
      const box2 = box;
      if (!rows.length) { box2.style.display = 'none'; box2.innerHTML = ''; return; }
      box2.style.display = 'block';
      box2.innerHTML = '<b>💡 ตัวเลขที่ระบบกฎอ่านไม่ออก — โมเดลเล็กเดาให้ (ทดลอง)</b><div style="color:var(--text-light);margin-bottom:4px;">โมเดลอาจเดาผิดแม้ตัวเลขมั่นใจสูง · ระบบไม่ใช้ค่าเหล่านี้จนกว่าคุณจะกด "ใช้" (การกดคือการแก้ชื่อในบันทึก ซึ่งเห็นและแก้กลับได้)</div>' + rows.join('');
    }
    async function suggestAccept(i) {
      const it = suggestItems[i];
      const ta = document.getElementById('labValues');
      const lead = ta.value.length - ta.value.trimStart().length;
      if (!it || ta.value.trim() !== suggestNote || ta.value.substr(lead + it.ns, it.ne - it.ns) !== it.name) { alert('บันทึกถูกแก้ไปแล้ว กรุณากด "แปลผล" ใหม่ก่อน'); return; }
      await learnCall('/api/suggest', { action: 'feedback', param: it.param, accepted: true, conf: it.conf });
      ta.value = ta.value.slice(0, lead + it.ns) + it.alias + ta.value.slice(lead + it.ne);
      generate();
    }
    async function suggestReject(i) {
      const it = suggestItems[i];
      if (it) await learnCall('/api/suggest', { action: 'feedback', param: it.param, accepted: false, conf: it.conf });
      suggestItems[i] = null; suggestRender();
    }
'''

STATS_JS = r'''      if (data.tagger && data.tagger.total) {
        html += '<div class="stats-section"><h4>💡 ตัวช่วยเดาตัวเลข: หมอกด "ใช้" / "ไม่ใช่" (นับเท่านั้น ไม่เก็บข้อความ)</h4><table class="stats-table"><tr><th>ความมั่นใจ</th><th>ใช้</th><th>ไม่ใช่</th><th>ใช้ถูก %</th></tr>';
        for (const b of data.tagger.byBand) { const n = b.accepted + b.rejected; html += `<tr><td>${esc(b.band)}</td><td>${esc(b.accepted)}</td><td>${esc(b.rejected)}</td><td>${n ? Math.round(100 * b.accepted / n) : 0}%</td></tr>`; }
        html += '</table><div style="font-size:11.5px;color:var(--text-light);margin-top:4px;">"ใช้" = หมอยอมรับคำเดา ไม่ใช่การตรวจว่าถูกจริงทุกกรณี</div></div>';
      }
      document.getElementById('statsContent').innerHTML = html;'''
