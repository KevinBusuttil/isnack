// Operator Hub — Kiosk-ready: operator-required actions, materials snapshot, line-centric Job Cards
frappe.pages['operator-hub'].on_page_load = function (wrapper) {
  const page = frappe.ui.make_app_page({ parent: wrapper, title: 'Operator Hub', single_column: true });
  const $main = $(page.main);
  const templateURL = '/assets/isnack/page/operator_hub/operator_hub.html';

  fetch(templateURL, { cache: 'no-store' })
    .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.text(); })
    .then(html => { $main.html(html); init_operator_hub($main); })
    .catch(err => { console.error('Failed to load operator_hub.html', err);
      $main.html('<div class="alert alert-danger m-3">Failed to load Operator Hub UI.</div>'); });
};

function init_operator_hub($root) {
  const banner = $('#wo-banner', $root);
  const grid   = $('#wo-grid',   $root);
  const alerts = $('#alerts',    $root);
  const scan   = $('#scan',      $root);

  // Materials panel
  const $matEmpty  = $('#mat-empty', $root);
  const $matWrap   = $('#mat-content', $root);
  const $matTBody  = $('#mat-req-tbody', $root);
  const $matScans  = $('#mat-scans', $root);
  const $matWOLbl  = $('#mat-wo-label', $root);

  const state  = {
    current_card: null,
    current_wo: null,
    cards: [],
    current_line: localStorage.getItem('kiosk_line') || null,
    current_emp: null,
    current_emp_name: null,
    current_is_fg: false
  };

  // Status bar
  const $statusBar  = $('#status-bar');
  const $statusMsg  = $('#status-message');
  const $statusConn = $('#status-connection');

  // ---- Theme (Industrial Teal) ----
  $root.addClass('op-teal');
  (function ensureCSS(){
    const cssURL = '/assets/isnack/page/operator_hub/operator_hub.css';
    if (!document.querySelector(`link[href="${cssURL}"]`)) {
      const link = document.createElement('link'); link.rel = 'stylesheet'; link.href = cssURL; document.head.appendChild(link);
    }
  })();

  // ---- Kiosk chrome toggle ----
  function applyKioskChrome(enable){
    document.body.classList.toggle('op-kiosk', !!enable);
    localStorage.setItem('op_kiosk_chrome', enable ? '1' : '0');
    let btn = document.getElementById('kiosk-exit');
    if (enable && !btn) { btn = document.createElement('button'); btn.id = 'kiosk-exit';
      btn.className = 'btn btn-sm btn-outline-secondary'; btn.textContent = 'Exit Kiosk';
      btn.onclick = () => applyKioskChrome(false); document.body.appendChild(btn); }
    else if (!enable && btn) { btn.remove(); }
  }
  applyKioskChrome(localStorage.getItem('op_kiosk_chrome') === '1');

  // ---- Header controls ----
  (function wireKioskControls(){
    const hasHeader = $('#op-toolbar', $root).length > 0;

    function bindCommon() {
      $('#kiosk-fullscreen').off('click').on('click', () => {
        if (!document.fullscreenElement) document.documentElement.requestFullscreen().catch(()=>{});
        else document.exitFullscreen().catch(()=>{});
      });
      $('#kiosk-toggle-chrome').off('click').on('click', () => {
        const on = !document.body.classList.contains('op-kiosk');
        applyKioskChrome(on);
        $('#kiosk-toggle-chrome').text(on ? 'Show Header' : 'Hide Header');
      });
      window.addEventListener('keydown', (e) => {
        if (e.ctrlKey && e.shiftKey && (e.key === 'K' || e.key === 'k')) { e.preventDefault(); $('#kiosk-toggle-chrome').trigger('click'); }
      }, { passive: false });
    }

    if (hasHeader) {
      $('#kiosk-line-label').text(state.current_line || '—');
      $('#kiosk-emp-label').text(state.current_emp_name || '—');
      bindCommon();
    } else {
      if (!$('#kiosk-controls', $root).length) {
        const $row = $(`
          <div id="kiosk-controls" class="d-flex align-items-center gap-2 mb-2">
            <span class="badge bg-info text-dark">Line: <span id="kiosk-line-label">—</span></span>
            <button id="kiosk-choose-line" class="btn btn-sm btn-outline-primary">Set Line</button>
            <span class="badge bg-secondary">Operator: <span id="kiosk-emp-label">—</span></span>
            <button id="kiosk-choose-emp" class="btn btn-sm btn-outline-secondary">Set Operator</button>
            <button id="kiosk-clear-emp" class="btn btn-sm btn-outline-danger">Clear</button>
            <button id="kiosk-fullscreen" class="btn btn-sm btn-outline-primary">Full Screen</button>
            <button id="kiosk-toggle-chrome" class="btn btn-sm btn-outline-secondary">Hide Header</button>
          </div>
        `);
        $row.insertBefore($root.find('#wo-grid'));
      }
      bindCommon();
    }
  })();

  // ---- Status helpers ----
  function setConnection(isOnline) {
    $statusConn.text(isOnline ? 'Online' : 'Offline');
    $statusBar.removeClass('bg-danger bg-warning bg-success bg-dark').addClass(isOnline ? 'bg-dark' : 'bg-danger');
  }
  function setStatus(message, tone = 'neutral') {
    $statusMsg.html(message);
    $statusBar.removeClass('bg-danger bg-warning bg-success bg-dark');
    if (tone === 'success') $statusBar.addClass('bg-success');
    else if (tone === 'warning') $statusBar.addClass('bg-warning');
    else if (tone === 'error') $statusBar.addClass('bg-danger');
    else $statusBar.addClass('bg-dark');
  }
  function flashStatus(message, tone = 'neutral', ms = 2500) {
    setStatus(message, tone);
    setTimeout(() => { if (state.current_emp) setStatus('Ready', 'neutral'); }, ms);
  }
  function ensureOperatorNotice(){ if (!state.current_emp) setStatus('<b>Set Operator first to continue</b>', 'warning'); }

  setConnection(navigator.onLine);
  window.addEventListener('online',  () => setConnection(true));
  window.addEventListener('offline', () => setConnection(false));

  // Clock + shift
  const $clock = $('#op-time', $root);
  const $shift = $('#shift-label', $root);
  function updateClockShift() {
    const d = new Date();
    const hh = String(d.getHours()).padStart(2,'0'); const mm = String(d.getMinutes()).padStart(2,'0');
    $clock.text(`${hh}:${mm}`);
    if ($shift.length) { const h = d.getHours(); $shift.text((h >= 6 && h < 14) ? 'A' : (h >= 14 && h < 22) ? 'B' : 'C'); }
  }
  updateClockShift(); setInterval(updateClockShift, 30_000);

  // Safe RPC
  async function rpc(path, args) {
    try { return await frappe.call(path, args); }
    catch (err) { console.error('RPC error', path, err); flashStatus('Error: ' + (err?.message || path), 'error'); throw err; }
  }

  // ---------- Enable/disable ----------
  function refreshButtonStates() {
    const hasEmp  = !!state.current_emp;
    const hasCard = !!state.current_card;
    const hasWO   = !!state.current_wo;
    const enableCore = hasEmp && hasCard;

    $('#btn-start',  $root).prop('disabled', !enableCore);
    $('#btn-pause',  $root).prop('disabled', !enableCore);
    $('#btn-stop',   $root).prop('disabled', !enableCore);

    $('#btn-load',    $root).prop('disabled', !enableCore);
    $('#btn-request', $root).prop('disabled', !enableCore);
    $('#btn-return',  $root).prop('disabled', !enableCore);

    $('#btn-label',   $root).prop('disabled', !(enableCore && state.current_is_fg));
    $('#btn-close',   $root).prop('disabled', !(hasEmp && hasWO));
    ensureOperatorNotice();
  }

  // Keep scanner focused
  const focus_scan = () => scan.trigger('focus');
  setInterval(focus_scan, 1500); focus_scan();

  // Print channel
  if (!window.__opHubRealtimeBound) {
    frappe.realtime.on('isnack_print', ({ printer, raw }) => { window.postMessage({ type: 'PRINT_RAW', printer, raw }, '*'); });
    window.__opHubRealtimeBound = true;
  }

  // Choose line — via server (no client get_list)
  $('#kiosk-choose-line', $root).on('click', async () => {
    const r = await rpc('isnack.api.mes_ops.list_workstations');
    const opts = (r.message || []).join('\n');
    const d = new frappe.ui.Dialog({
      title: 'Select Line (Workstation)',
      fields: [{ label:'Workstation', fieldname:'line', fieldtype:'Select', options: opts, reqd:1 }],
      primary_action_label: 'Apply',
      primary_action: v => {
        state.current_line = v.line; localStorage.setItem('kiosk_line', v.line);
        $('#kiosk-line-label').text(v.line); d.hide(); load_queue();
      }
    });
    d.show();
  });

  // Choose operator
  $('#kiosk-choose-emp', $root).on('click', () => {
    const d = new frappe.ui.Dialog({
      title: 'Set Operator',
      fields: [
        { label:'Employee', fieldname:'employee', fieldtype:'Link', options:'Employee' },
        { fieldtype:'Section Break' },
        { label:'Scan Badge', fieldname:'badge', fieldtype:'Data', description:'Scan or type EMP:123456 and press Enter' }
      ],
      primary_action_label: 'Set',
      primary_action: async v => {
        let payload = v.employee ? { employee: v.employee } : (v.badge ? { badge: v.badge.replace(/^EMP:/i, '') } : null);
        if (!payload) { frappe.msgprint('Pick an Employee or scan a Badge'); return; }
        const r = await frappe.call('isnack.api.mes_ops.resolve_employee', payload);
        if (r.message && r.message.ok) {
          state.current_emp = r.message.employee; state.current_emp_name = r.message.employee_name;
          $('#kiosk-emp-label').text(state.current_emp_name); d.hide(); refreshButtonStates();
          flashStatus(`Operator: ${state.current_emp_name}`, 'success');
        } else { frappe.msgprint('Could not resolve employee.'); }
      }
    });
    d.show();
  });

  $('#kiosk-clear-emp', $root).on('click', () => {
    state.current_emp = null; state.current_emp_name = null;
    $('#kiosk-emp-label').text('—'); refreshButtonStates(); flashStatus('Operator cleared', 'warning');
  });

  // === Materials snapshot ===
  function fmt(n){ return (n==null) ? '-' : (Math.round(n*1000)/1000).toLocaleString(); }

  async function load_materials_snapshot(work_order){
    const r = await rpc('isnack.api.mes_ops.get_materials_snapshot', { work_order });
    const data = r.message || {};
    if (!data.ok) { render_mat_empty(data.msg || 'No data'); return; }

    $matWOLbl.text(data.wo || '');
    const rows = data.rows || [];
    const frag = document.createDocumentFragment();
    rows.forEach(it => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td class="fw-semibold">${frappe.utils.escape_html(it.item_code || '')}</td>
        <td class="text-truncate" title="${frappe.utils.escape_html(it.item_name || '')}">${frappe.utils.escape_html(it.item_name || '')}</td>
        <td class="text-end">${frappe.utils.escape_html(it.uom || '')}</td>
        <td class="text-end">${fmt(it.required)}</td>
        <td class="text-end">${fmt(it.issued)}</td>
        <td class="text-end ${(+it.remain>0?'text-danger':'text-success')}">${fmt(it.remain)}</td>
      `;
      frag.appendChild(tr);
    });
    $matTBody.empty()[0].appendChild(frag);

    const sed = data.scans || [];
    const sFrag = document.createDocumentFragment();
    if (!sed.length) {
      const li = document.createElement('li'); li.className = 'list-group-item'; li.textContent = 'No issues recorded yet.'; sFrag.appendChild(li);
    } else {
      sed.forEach(r => {
        const li = document.createElement('li');
        li.className = 'list-group-item d-flex justify-content-between';
        li.innerHTML = `
          <span>
            <span class="fw-semibold">${frappe.utils.escape_html(r.item_code || '')}</span>
            <span class="text-muted">${r.batch_no ? ' — Batch ' + frappe.utils.escape_html(r.batch_no) : ''}</span>
            <span class="text-muted"> · ${frappe.utils.escape_html(r.uom || '')}</span>
          </span>
          <span class="ms-2">${fmt(parseFloat(r.qty) || 0)}</span>
        `;
        sFrag.appendChild(li);
      });
    }
    $matScans.empty()[0].appendChild(sFrag);

    $matEmpty.addClass('d-none'); $matWrap.removeClass('d-none');
  }

  function render_mat_empty(msg){
    $matWOLbl.text('—'); $matTBody.empty(); $matScans.empty();
    $matWrap.addClass('d-none'); $matEmpty.removeClass('d-none').text(msg || 'Select a Job Card to load materials.');
  }

  // =============== Queue & grid ===============
  function load_queue() {
    setStatus('Loading queue…');
    const args = state.current_line ? { line: state.current_line } : {};
    return rpc('isnack.api.mes_ops.get_line_queue', args).then(r => {
      state.cards = r.message || r || []; render_grid();
      if (!state.current_card && state.cards.length) set_active_card(state.cards[0].name);
      flashStatus(`Loaded ${state.cards.length} job card(s)`, 'success');
    });
  }
  load_queue();

  function render_grid() {
    grid.empty();
    if (!state.cards.length) { grid.html('<div class="text-muted">No job cards in queue for this line.</div>'); return; }
    state.cards.forEach(row => {
      const chipType = row.type === 'FG' ? 'chip chip-fg' : 'chip chip-sf';
      const stClass = ({'Open':'chip chip-ns','Work In Progress':'chip chip-running','On Hold':'chip chip-paused','Completed':'chip chip-running'}[row.status] || 'chip chip-ns');
      const el = $(`
        <button class="list-group-item list-group-item-action py-3 d-flex justify-content-between align-items-center" type="button">
          <div class="fw-semibold">
            <span class="me-2">${frappe.utils.escape_html(row.name)}</span>
            <span class="text-muted">— ${frappe.utils.escape_html(row.item_name || '')}</span>
            <span class="text-muted ms-2">Op ${frappe.utils.escape_html(row.operation || '')}</span>
            <span class="text-muted ms-2">Qty ${row.for_quantity}</span>
            <span class="text-muted ms-2">Crew ${row.crew_open}</span>
          </div>
          <div class="d-flex gap-2 align-items-center">
            <span class="${chipType}">${row.type}</span>
            <span class="${stClass}">${row.status}</span>
          </div>
        </button>
      `);
      el.on('click', () => set_active_card(row.name)); grid.append(el);
    });
  }

  function set_active_card(card_name) {
    state.current_card = card_name;
    const row = (state.cards || []).find(x => x.name === card_name);
    state.current_wo = row ? row.work_order : null;
    state.current_is_fg = row ? (row.type === 'FG') : false;

    rpc('isnack.api.mes_ops.get_card_banner', { job_card: card_name })
      .then(r => banner.html(r.message && r.message.html ? r.message.html : '—'));

    refreshButtonStates();
    if (state.current_wo) load_materials_snapshot(state.current_wo); else render_mat_empty('Select a Job Card to load materials.');
    flashStatus(`Selected ${card_name} (${state.current_is_fg ? 'FG' : 'SF'})`, 'neutral');
  }

  // ---------- Scanner handling ----------
  const okTone  = new Audio('/assets/frappe/sounds/submit.mp3');
  const errTone = new Audio('/assets/frappe/sounds/cancel.mp3');
  const $scanStatus = $('#scan-status');

  async function resolveBadge(badge){
    const r = await frappe.call('isnack.api.mes_ops.resolve_employee', { badge });
    if (r.message && r.message.ok) {
      state.current_emp = r.message.employee; state.current_emp_name = r.message.employee_name;
      $('#kiosk-emp-label').text(state.current_emp_name);
      $scanStatus.length && $scanStatus.text('Badge').removeClass().addClass('badge bg-info');
      refreshButtonStates(); flashStatus(`Operator: ${state.current_emp_name}`, 'success');
      try { okTone.play().catch(()=>{}); } catch(_) {}
    } else {
      $scanStatus.length && $scanStatus.text('Unknown').removeClass().addClass('badge bg-danger');
      ensureOperatorNotice(); try { errTone.play().catch(()=>{}); } catch(_) {}
    }
  }

  async function handleScanValue(raw) {
    if (!raw) return;
    if (/^EMP:/i.test(raw)) return resolveBadge(raw.replace(/^EMP:/i, ''));
    if (!state.current_card && /^[A-Z0-9\-]{4,20}$/i.test(raw)) return resolveBadge(raw);
    if (!state.current_emp) { ensureOperatorNotice(); try { errTone.play().catch(()=>{}); } catch(_) {} return; }
    if (!state.current_card){ flashStatus('Pick a Job Card first', 'warning'); try { errTone.play().catch(()=>{}); } catch(_) {} return; }

    setStatus('Processing scan…');
    rpc('isnack.api.mes_ops.scan_material', { job_card: state.current_card, code: raw })
      .then(async r => {
        const { ok, msg } = r.message || {};
        frappe.show_alert({ message: msg || 'Scan processed', indicator: ok ? 'green' : 'red' });
        if (ok) {
          alerts.length && alerts.addClass('d-none').text('');
          $scanStatus.length && $scanStatus.text('Material').removeClass().addClass('badge bg-success');
          flashStatus(msg || 'Loaded material', 'success');
          if (state.current_wo) await load_materials_snapshot(state.current_wo);
          try { okTone.play().catch(()=>{}); } catch(_) {}
        } else {
          alerts.length && alerts.removeClass('d-none').text(msg || 'Scan failed');
          $scanStatus.length && $scanStatus.text('Error').removeClass().addClass('badge bg-danger');
          flashStatus(msg || 'Scan failed', 'error'); try { errTone.play().catch(()=>{}); } catch(_) {}
        }
      });
  }

  scan.on('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); const raw = scan.val().trim(); scan.val(''); handleScanValue(raw); } });
  scan.on('change',  (e) => { const raw = (e.target.value || '').trim(); scan.val(''); handleScanValue(raw); });

  // ---------- Buttons ----------
  $('#btn-start',$root).on('click', async () => {
    if (!state.current_card || !state.current_emp) { ensureOperatorNotice(); return; }
    await rpc('isnack.api.mes_ops.set_card_status', { job_card: state.current_card, action:'Start', employee: state.current_emp });
    flashStatus(`Started — ${state.current_card}`, 'success');
    const r = await rpc('isnack.api.mes_ops.get_card_banner', { job_card: state.current_card }); banner.html(r.message.html); load_queue();
  });

  $('#btn-pause',$root).on('click', async () => {
    if (!state.current_card || !state.current_emp) { ensureOperatorNotice(); return; }
    await rpc('isnack.api.mes_ops.set_card_status', { job_card: state.current_card, action:'Pause', employee: state.current_emp });
    flashStatus(`Paused — ${state.current_card}`, 'warning');
    const r = await rpc('isnack.api.mes_ops.get_card_banner', { job_card: state.current_card }); banner.html(r.message.html); load_queue();
  });

  $('#btn-stop',$root).on('click', async () => {
    if (!state.current_card || !state.current_emp) { ensureOperatorNotice(); return; }
    await rpc('isnack.api.mes_ops.set_card_status', { job_card: state.current_card, action:'Stop', employee: state.current_emp });
    flashStatus(`Stopped — ${state.current_card}`, 'error');
    const r = await rpc('isnack.api.mes_ops.get_card_banner', { job_card: state.current_card }); banner.html(r.message.html); load_queue();
  });

  $('#btn-load',$root).on('click', () => {
    if (!state.current_card || !state.current_emp) { ensureOperatorNotice(); return; }
    new frappe.ui.Dialog({ title: 'Load / Scan Materials',
      fields: [{ fieldname:'info', fieldtype:'HTML', options:'<div class="text-muted">Scan raw, semi-finished, or packaging barcodes now…</div>' }]
    }).show();
    flashStatus(`Ready to scan for ${state.current_card}`); focus_scan();
  });

  $('#btn-request',$root).on('click', () => {
    if (!state.current_card || !state.current_emp) { ensureOperatorNotice(); return; }
    const d = new frappe.ui.Dialog({
      title:'Request More Material',
      fields: [
        { label:'Item',   fieldname:'item_code', fieldtype:'Link', options:'Item', reqd:1 },
        { label:'Qty',    fieldname:'qty', fieldtype:'Float', reqd:1 },
        { label:'Reason', fieldname:'reason', fieldtype:'Select', options:['Evaporation/Wastage','Overweight Spec','Machine Loss','Short Pick','Other'] }
      ],
      primary_action_label:'Send Request',
      primary_action: (v) => {
        setStatus('Submitting material request…');
        rpc('isnack.api.mes_ops.request_material', { job_card: state.current_card, ...v })
          .then(r => { d.hide(); frappe.msgprint('Material Request: ' + (r.message && r.message.mr)); flashStatus('Material request submitted', 'success'); });
      }
    });
    d.show();
  });

  // Return Materials
  $('#btn-return',$root).on('click', () => {
    if (!state.current_card || !state.current_emp) { ensureOperatorNotice(); return; }
    const lines = [];
    const listHTML = `
      <div class="mb-2 text-muted">Scan an item barcode, enter quantity (UoM), optional batch, then click <b>Add</b>. When done, click <b>Post Returns</b>.</div>
      <div id="ret-list" class="list-group" style="max-height:220px; overflow:auto;"></div>
    `;
    const d = new frappe.ui.Dialog({
      title:'Return Materials',
      fields: [
        { label:'Scan / Item Code', fieldname:'scan', fieldtype:'Data', reqd:0, description:'Scan barcode or type item code' },
        { label:'Qty', fieldname:'qty', fieldtype:'Float', reqd:1, default:1 },
        { label:'Batch (optional)', fieldname:'batch', fieldtype:'Data' },
        { fieldname:'list', fieldtype:'HTML', options:listHTML },
      ],
      primary_action_label:'Post Returns',
      primary_action: async () => {
        if (!lines.length) { frappe.msgprint('No items to return'); return; }
        setStatus('Posting returns…');
        try {
          await rpc('isnack.api.mes_ops.return_materials', { job_card: state.current_card, lines: JSON.stringify(lines) });
          d.hide(); flashStatus('Return transfer posted', 'success');
          if (state.current_wo) load_materials_snapshot(state.current_wo);
        } catch {}
      }
    });

    function redraw(){
      const $box = d.$wrapper.find('#ret-list'); $box.empty();
      if (!lines.length){ $box.append(`<div class="list-group-item text-muted">Nothing added yet.</div>`); return; }
      lines.forEach((r, idx) => {
        $box.append(`
          <div class="list-group-item d-flex justify-content-between align-items-center">
            <span><b>${frappe.utils.escape_html(r.item_code)}</b>${r.batch_no ? `<span class="text-muted"> — Batch ${frappe.utils.escape_html(r.batch_no)}</span>` : ''}</span>
            <span><span class="me-3">${r.qty}</span><button type="button" class="btn btn-sm btn-outline-danger" data-del="${idx}">Remove</button></span>
          </div>`);
      });
      $box.find('[data-del]').on('click', (e) => { const i = +e.currentTarget.getAttribute('data-del'); lines.splice(i,1); redraw(); });
    }
    function addLine(){
      const v = d.get_values(); const code=(v.scan||'').trim(); const qty=+v.qty||0; const batch=(v.batch||'').trim();
      if (!code || qty<=0){ frappe.msgprint('Item and positive qty required'); return; }
      lines.push({ item_code: code, qty, batch_no: batch || undefined });
      d.set_value('scan',''); d.set_value('qty',1); d.set_value('batch',''); redraw();
      setTimeout(() => d.get_field('scan').$input && d.get_field('scan').$input.focus(), 50);
    }
    const $add = $(`<button class="btn btn-sm btn-primary">Add</button>`);
    d.$wrapper.find('.modal-body .form-column:first').append($('<div class="mt-2"></div>').append($add));
    $add.on('click', addLine);
    d.$wrapper.on('keydown', '[data-fieldname="scan"] input', (e) => { if (e.key === 'Enter') { e.preventDefault(); addLine(); } });

    d.show(); redraw(); setTimeout(() => d.get_field('scan').$input && d.get_field('scan').$input.focus(), 60);
  });

  // Print Label (FG) — uses Factory Settings defaults for template/printer
  $('#btn-label',$root).on('click', async () => {
    if (!state.current_card || !state.current_emp || !state.current_is_fg) return;

    // Pull defaults from Factory Settings
    const [tplDefault, prnDefault] = await Promise.all([
      frappe.db.get_single_value('Factory Settings', 'default_label_template'),
      frappe.db.get_single_value('Factory Settings', 'default_label_printer'),
    ]);

    const d = new frappe.ui.Dialog({
      title:'Print Carton Label (FG only)',
      fields: [
        { label:'Carton Qty', fieldname:'qty', fieldtype:'Float', reqd:1, default:12 },
        { label:'Template',   fieldname:'template', fieldtype:'Link', options:'Label Template', reqd:1, default: tplDefault || '' },
        { label:'Printer',    fieldname:'printer', fieldtype:'Data', reqd:1, default: prnDefault || '' }
      ],
      primary_action_label:'Print',
      primary_action: (v) => {
        setStatus('Sending label to printer…');
        rpc('isnack.api.mes_ops.print_label', { job_card: state.current_card, carton_qty: v.qty, template: v.template, printer: v.printer })
          .then(() => { d.hide(); frappe.show_alert({message:'Label sent', indicator:'green'}); flashStatus(`Label printed — ${state.current_card}`, 'success'); });
      }
    });
    d.show();
  });

  $('#btn-close',$root).on('click', async () => {
    if (!state.current_wo || !state.current_emp) { ensureOperatorNotice(); return; }
    let remainingDefault = 0;
    try { const r = await rpc('isnack.api.mes_ops.get_wo_progress', { work_order: state.current_wo });
      remainingDefault = (r.message && r.message.remaining) || 0; } catch {}
    const d = new frappe.ui.Dialog({
      title:'Close / End Work Order',
      fields: [
        { label:'Good Qty', fieldname:'good', fieldtype:'Float', reqd:1, default: remainingDefault },
        { label:'Rejects',  fieldname:'rejects', fieldtype:'Float', default: 0 },
        { label:'Remarks',  fieldname:'remarks', fieldtype:'Small Text' }
      ],
      primary_action_label:'Complete',
      primary_action: (v) => {
        setStatus('Completing work order…');
        rpc('isnack.api.mes_ops.complete_work_order', { work_order: state.current_wo, ...v })
          .then(() => { d.hide(); flashStatus(`Completed — ${state.current_wo}`, 'success'); load_queue(); });
      }
    });
    d.show();
  });

  // Initial
  refreshButtonStates();
  render_mat_empty('Select a Job Card to load materials.');
}
