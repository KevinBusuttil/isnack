// Operator Hub — Kiosk-ready: operator-required actions, materials snapshot, line-centric Work Orders
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
  // Scan history configuration constants
  const SCAN_CODE_MAX_LENGTH = 60;
  const SCAN_HISTORY_MAX_ENTRIES = 20;
  // Pattern to extract item code from backend messages like "Consumed X unit of ITEM123" or "item ABC-XYZ"
  const SCAN_ITEM_PATTERN = /(?:of|item)\s+([A-Z0-9_-]+)/i;
  // Pattern to extract quantity from backend messages like "Consumed 12.5 Kg" or "consumed 1 Nos"
  const SCAN_QTY_PATTERN = /consumed\s+([\d.]+)\s+(\w+)/i;
  // Delay between opening multiple print dialogs to prevent browser blocking
  const PRINT_DIALOG_DELAY_MS = 500;

  // ============================================================
  // Load QZ Tray Library (for silent printing support)
  // ============================================================
  (function loadQzTray() {
    // Check if QZ Tray is already loaded (typically from local installation)
    if (typeof qz !== 'undefined') {
      return;
    }
    
    // QZ Tray is typically loaded from the local installation at http://localhost:8182/qz-tray.js
    // Try loading from local installation first (HTTP for compatibility), fall back to CDN
    const qzScript = document.createElement('script');
    qzScript.src = 'http://localhost:8182/qz-tray.js';
    qzScript.async = true;
    qzScript.onerror = () => {
      console.info('QZ Tray not found at localhost, trying CDN fallback...');
      // Fallback to CDN if local installation is not available
      const cdnScript = document.createElement('script');
      cdnScript.src = 'https://cdn.jsdelivr.net/npm/qz-tray@2.2/qz-tray.js';
      cdnScript.async = true;
      cdnScript.onerror = () => {
        console.warn('Failed to load QZ Tray library. Silent printing will not be available.');
      };
      document.head.appendChild(cdnScript);
    };
    document.head.appendChild(qzScript);
  })();

  // ============================================================
  // QZ Tray Silent Printing Support
  // ============================================================
  
  /**
   * Check if QZ Tray is available and ready to use
   * @returns {boolean} True if QZ Tray is available
   */
  function isQzTrayAvailable() {
    return typeof qz !== 'undefined' && qz.websocket;
  }

  /**
   * Connect to QZ Tray WebSocket if not already connected
   * @returns {Promise<boolean>} Resolves to true if connected, false otherwise
   */
  async function ensureQzConnection() {
    if (!isQzTrayAvailable()) {
      return false;
    }
    
    try {
      if (!qz.websocket.isActive()) {
        await qz.websocket.connect();
      }
      return true;
    } catch (err) {
      console.error('Failed to connect to QZ Tray:', err);
      return false;
    }
  }

  /**
   * Print a label using QZ Tray (silent printing)
   * @param {string} printUrl - The URL to print
   * @param {string} printerName - Name of the printer from Network Printer Settings
   * @returns {Promise<boolean>} Resolves to true if successful, false otherwise
   */
  async function printWithQzTray(printUrl, printerName) {
    if (!isQzTrayAvailable()) {
      console.warn('QZ Tray is not available');
      return false;
    }

    // Validate printer name
    if (!printerName || typeof printerName !== 'string' || printerName.trim() === '') {
      console.error('Invalid printer name provided to QZ Tray');
      return false;
    }

    try {
      // Ensure connection
      const connected = await ensureQzConnection();
      if (!connected) {
        throw new Error('Could not connect to QZ Tray');
      }

      // Fetch the print content - properly remove trigger_print parameter
      const url = new URL(printUrl, window.location.origin);
      
      // Security: Validate that the URL is from the same origin to prevent SSRF attacks
      if (url.origin !== window.location.origin) {
        throw new Error('Print URL must be from the same origin');
      }
      
      url.searchParams.delete('trigger_print');
      
      const response = await fetch(url.toString());
      if (!response.ok) {
        throw new Error(`Failed to fetch print content: ${response.status}`);
      }
      const htmlContent = await response.text();

      // Configure QZ printer
      const config = qz.configs.create(printerName.trim(), {
        units: 'mm',
        size: { width: 62, height: 84 },
        scaleContent: false,
        rasterize: false
      });

      // Print as HTML/pixel format
      const data = [{
        type: 'pixel',
        format: 'html',
        flavor: 'plain',
        data: htmlContent
      }];

      await qz.print(config, data);
      return true;
    } catch (err) {
      console.error('QZ Tray print error:', err);
      return false;
    }
  }

  /**
   * Show a warning dialog when QZ Tray is required but not available
   */
  function showQzTrayWarning() {
    frappe.msgprint({
      title: __('QZ Tray Required'),
      indicator: 'orange',
      message: `
        <p>Silent printing is enabled but QZ Tray is not installed or not running.</p>
        <p>Please install QZ Tray from <a href="https://qz.io/download/" target="_blank" rel="noopener noreferrer">https://qz.io/download/</a></p>
        <p>Falling back to browser print dialog...</p>
      `
    });
  }

  /**
   * Handle label printing - either silent via QZ Tray or via browser dialog
   * @param {string} printUrl - The URL to print
   * @param {boolean} enableSilentPrinting - Whether silent printing is enabled
   * @param {string} printerName - Name of the printer to use
   * @param {string} context - Context for logging (e.g., 'new label', 'reprint')
   */
  async function handleLabelPrint(printUrl, enableSilentPrinting, printerName, context = 'label') {
    if (enableSilentPrinting && printerName) {
      // Attempt silent printing via QZ Tray
      if (!isQzTrayAvailable()) {
        showQzTrayWarning();
        // Fallback to browser dialog
        window.open(printUrl, '_blank');
        frappe.show_alert({message: `Print dialog opened for ${context}`, indicator: 'green'});
        return;
      }

      try {
        const success = await printWithQzTray(printUrl, printerName);
        if (success) {
          frappe.show_alert({message: `Label sent to printer for ${context}`, indicator: 'green'});
        } else {
          throw new Error('QZ Tray printing failed');
        }
      } catch (err) {
        console.error('Silent printing failed, falling back to dialog:', err);
        frappe.show_alert({message: 'Silent printing failed, opening print dialog', indicator: 'orange'});
        window.open(printUrl, '_blank');
      }
    } else {
      // Use standard browser print dialog
      window.open(printUrl, '_blank');
      frappe.show_alert({message: `Print dialog opened for ${context}`, indicator: 'green'});
    }
  }

  // ============================================================
  // End QZ Tray Support
  // ============================================================

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

  // Migrate from old single-line storage to multi-line storage
  const migrateLineStorage = () => {
    const oldLine = localStorage.getItem('kiosk_line');
    const newLines = localStorage.getItem('kiosk_lines');
    if (oldLine && !newLines) {
      localStorage.setItem('kiosk_lines', JSON.stringify([oldLine]));
      localStorage.removeItem('kiosk_line');
      return [oldLine];
    }
    if (newLines) {
      try {
        return JSON.parse(newLines);
      } catch (e) {
        console.error('Failed to parse kiosk_lines from localStorage:', e);
        localStorage.removeItem('kiosk_lines');
        return [];
      }
    }
    return [];
  };

  const state  = {
    current_wo: null,
    orders: [],
    current_lines: migrateLineStorage(),
    current_emp: null,
    current_emp_name: null,
    current_is_fg: false,
    current_wo_status: null,
    current_stage_status: null
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
      $('#kiosk-line-label').text(state.current_lines.length ? state.current_lines.join(', ') : '—');
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
    const hasWO   = !!state.current_wo;
    const enableCore = hasEmp && hasWO;
    const isAllocated = state.current_stage_status === 'Staged';
    const enableActions = enableCore && isAllocated;
    const status = state.current_wo_status;

    // Enable Start button only if status is "Not Started" and fully allocated
    const isStartDisabled = !enableActions || status !== "Not Started";
    $('#btn-start',  $root).prop('disabled', isStartDisabled);

    // Dynamic Pause/Resume button
    const $pauseBtn = $('#btn-pause', $root);
    if (status === "Stopped") {
      $pauseBtn.text('Resume').removeClass('btn-warning').addClass('btn-success');
    } else {
      $pauseBtn.text('Pause').removeClass('btn-success').addClass('btn-warning');
    }
    $pauseBtn.prop('disabled', !enableActions);

    $('#btn-load',    $root).prop('disabled', !enableActions);
    $('#btn-request', $root).prop('disabled', !enableActions);
    $('#btn-return',  $root).prop('disabled', !enableActions);
    
    // End Shift Return only requires operator and line (no work order needed)
    $('#btn-end-shift-return', $root).prop('disabled', !(hasEmp && state.current_lines.length));

    $('#btn-label',   $root).prop('disabled', !(enableActions && state.current_is_fg));
    $('#btn-label-history', $root).prop('disabled', !(enableActions && state.current_is_fg));
    
    // End WO button: enabled when operator set + WO selected + WO allocated + not already ended
    const isProductionEnded = state.current_production_ended || false;
    $('#btn-end-wo', $root).prop('disabled', !(enableActions && !isProductionEnded));
    
    // Close Production button: enabled when operator set + line(s) set (no specific WO required)
    $('#btn-close-production', $root).prop('disabled', !(hasEmp && state.current_lines.length));

    if (!hasEmp) {
      ensureOperatorNotice();
    } else if (hasWO && !isAllocated) {
      setStatus('<b>Work Order not fully allocated</b>', 'warning');
    }
  }

  // Keep scanner focused
  const focus_scan = () => scan.trigger('focus');
  let scanFocusTimer = null;
  let scanMode = false;
  function setScanMode(enable){
    const on = !!enable;
    if (on === scanMode) return;
    scanMode = on;
    if (scanFocusTimer) { clearInterval(scanFocusTimer); scanFocusTimer = null; }
    if (scanMode) {
      focus_scan();
      scanFocusTimer = setInterval(focus_scan, 1500);
    }
  }

  // Print channel
  if (!window.__opHubRealtimeBound) {
    frappe.realtime.on('isnack_print', ({ printer, raw }) => { window.postMessage({ type: 'PRINT_RAW', printer, raw }, '*'); });
    window.__opHubRealtimeBound = true;
  }

  // Choose line — via server (no client get_list)
  $('#kiosk-choose-line', $root).on('click', async () => {
    setScanMode(false);
    const r = await rpc('isnack.api.mes_ops.list_workstations');
    const opts = (r.message || []);
    const d = new frappe.ui.Dialog({
      title: 'Select Factory Lines',
      fields: [{ 
        label:'Factory Lines', 
        fieldname:'lines', 
        fieldtype:'MultiSelectPills', 
        options: opts,
        reqd:1,
        default: state.current_lines
      }],
      primary_action_label: 'Apply',
      primary_action: v => {
        const selectedLines = v.lines || [];
        state.current_lines = selectedLines;
        localStorage.setItem('kiosk_lines', JSON.stringify(selectedLines));
        $('#kiosk-line-label').text(selectedLines.length ? selectedLines.join(', ') : '—');

        // Reset current WO context when line changes
        state.current_wo = null;
        state.current_is_fg = false;
        state.current_wo_status = null;
        state.current_stage_status = null;

        // Clear banner + materials so we don't show data from previous line
        banner.html('');
        render_mat_empty('Select a Work Order to load materials.');
        refreshButtonStates();

        d.hide();
        load_queue();   // this will load queue for the new line
      }
    });
    d.show();
  });

  // Choose operator
  $('#kiosk-choose-emp', $root).on('click', () => {
    setScanMode(false);  // avoid hidden scanner stealing focus inside dialog    
    const d = new frappe.ui.Dialog({
      title: 'Set Operator',
      fields: [
        { label:'Employee', fieldname:'employee', fieldtype:'Link', options:'Employee', reqd:1 }, 
      ],
      primary_action_label: 'Set',
      primary_action: async v => {
        const payload = v.employee ? { employee: v.employee } : null;
        if (!payload) { frappe.msgprint('Pick an Employee'); return; }
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
        <td class="text-end">${fmt(it.transferred)}</td>
        <td class="text-end"><span class="badge bg-info">${fmt(it.consumed)}</span></td>
        <td class="text-end ${(+it.remain<0?'text-danger':'text-success')}">${fmt(it.remain)}</td>
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
    $matWrap.addClass('d-none'); $matEmpty.removeClass('d-none').text(msg || 'Select a Work Order to load materials.');
  }

  // =============== Queue & grid ===============
  function load_queue() {
    setStatus('Loading queue…');
    const args = state.current_lines.length ? { lines: JSON.stringify(state.current_lines) } : {};
    return rpc('isnack.api.mes_ops.get_line_queue', args).then(r => {
      const prev = state.current_wo;
      state.orders = r.message || r || []; render_grid();
      if (prev && state.orders.find(o => o.name === prev)) {
        set_active_work_order(prev);
      } else if (state.orders.length) {
        set_active_work_order(state.orders[0].name);
      } else {
        state.current_wo = null;
        state.current_is_fg = false;
        state.current_wo_status = null;
        state.current_stage_status = null;
        state.current_production_ended = false;
        banner.html('');
        render_mat_empty('Select a Work Order to load materials.');
        refreshButtonStates();
      }
      flashStatus(`Loaded ${state.orders.length} work order(s)`, 'success');
    });
  }
  load_queue();

  function render_grid() {
    grid.empty();
    if (!state.orders.length) { grid.html('<div class="text-muted">No work orders in queue for this line.</div>'); return; }
    state.orders.forEach(row => {
      const chipType = row.type === 'FG' ? 'chip chip-fg' : 'chip chip-sf';
      const stage = (row.stage_status || '').toLowerCase();
      let allocChip = '';
      if (stage === 'staged') {
        allocChip = '<span class="chip chip-allocated">Allocated</span>';
      } else if (stage === 'partial') {
        allocChip = '<span class="chip chip-partial">Partly Allocated</span>';
      } else if (stage) {
        allocChip = '<span class="chip chip-not-allocated">Not Allocated</span>';
      }
      const stClass = ({
        'Not Started':'chip chip-ns',
        'In Process':'chip chip-running',
        'Stopped':'chip chip-paused',
        'Completed':'chip chip-running'
      }[row.status] || 'chip chip-ns');
      const el = $(`
        <button class="list-group-item list-group-item-action py-3 d-flex justify-content-between align-items-center" type="button">
          <div class="fw-semibold">
            <span class="me-2">${frappe.utils.escape_html(row.name)}</span>
            <span class="text-muted">— ${frappe.utils.escape_html(row.item_name || '')}</span>
            <span class="text-muted ms-2">Qty ${row.for_quantity}</span>
            ${row.line ? `<span class="text-muted ms-2">Line ${frappe.utils.escape_html(row.line)}</span>` : ''}
          </div>
          <div class="d-flex gap-2 align-items-center">
            <span class="${chipType}">${row.type}</span>
            ${allocChip}
            <span class="${stClass}">${row.status}</span>
          </div>
        </button>
      `);
      el.on('click', () => set_active_work_order(row.name)); grid.append(el);
    });
  }

  function set_active_work_order(wo_name) {
    state.current_wo = wo_name;
    const row = (state.orders || []).find(x => x.name === wo_name);
    state.current_is_fg = row ? (row.type === 'FG') : false;
    state.current_wo_status = row ? row.status : null;
    state.current_stage_status = row ? row.stage_status : null;
    state.current_production_ended = row ? (row.custom_production_ended || false) : false;

    rpc('isnack.api.mes_ops.get_wo_banner', { work_order: wo_name })
      .then(r => banner.html(r.message && r.message.html ? r.message.html : '—'));

    refreshButtonStates();
    if (state.current_wo) load_materials_snapshot(state.current_wo); else render_mat_empty('Select a Work Order to load materials.');
    flashStatus(`Selected ${wo_name} (${state.current_is_fg ? 'FG' : 'SF'})`, 'neutral');
  }

  // ---------- Scanner handling ----------
  const okTone  = new Audio('/assets/frappe/sounds/submit.mp3');
  const errTone = new Audio('/assets/frappe/sounds/cancel.mp3');
  const $scanStatus = $('#scan-status');

  async function handleScanValue(raw) {
    if (!raw) return;
    if (/^EMP:/i.test(raw)) {
      flashStatus('Use Set Operator to choose the operator', 'warning');
      return;
    }
    if (!state.current_emp) { ensureOperatorNotice(); try { errTone.play().catch(()=>{}); } catch(_) {} return; }
    if (!state.current_wo){ flashStatus('Pick a Work Order first', 'warning'); try { errTone.play().catch(()=>{}); } catch(_) {} return; }

    setStatus('Processing scan…');
    
    // Add timestamp for this scan
    const scanTime = new Date().toLocaleTimeString();
    
    rpc('isnack.api.mes_ops.scan_material', { work_order: state.current_wo, code: raw })
      .then(async r => {
        const { ok, msg } = r.message || {};
        const safeMsg = msg || 'Scan processed';
        frappe.show_alert({ message: safeMsg, indicator: ok ? 'green' : 'red' });
        
        // Update scan history in dialog if it exists
        const $scanHistoryList = $('#scan-history-list');
        if ($scanHistoryList.length > 0) {
          // Remove "no scans yet" message if it exists
          if ($scanHistoryList.find('.scan-history-empty').length > 0) {
            $scanHistoryList.empty();
          }
          
          // Parse the barcode to extract item info from backend response message
          // Using configurable patterns to match various message formats
          let itemInfo = 'Unknown';
          let qtyInfo = '';
          
          // Try to extract item code from the message
          const itemMatch = safeMsg.match(SCAN_ITEM_PATTERN);
          if (itemMatch) {
            itemInfo = itemMatch[1];
          }
          
          // Try to extract quantity from message
          const qtyMatch = safeMsg.match(SCAN_QTY_PATTERN);
          if (qtyMatch) {
            qtyInfo = `${qtyMatch[1]} ${qtyMatch[2]}`;
          }
          
          // Create scan entry with proper styling
          const statusClass = ok ? 'scan-success' : 'scan-failed';
          const statusIcon = ok ? '✓' : '✗';
          const statusText = ok ? 'Success' : 'Failed';
          const badgeClass = ok ? 'bg-success' : 'bg-danger';
          
          const scanEntry = $(`
            <div class="scan-entry ${statusClass} mb-2 p-2">
              <div class="d-flex justify-content-between align-items-start mb-1">
                <span class="badge ${badgeClass} me-2">${statusIcon} ${statusText}</span>
                <span class="text-muted small">${scanTime}</span>
              </div>
              <div class="small mb-1">
                <strong>Raw Code:</strong> <code class="scan-code">${frappe.utils.escape_html(raw.substring(0, SCAN_CODE_MAX_LENGTH))}${raw.length > SCAN_CODE_MAX_LENGTH ? '...' : ''}</code>
              </div>
              ${itemInfo !== 'Unknown' ? `<div class="small mb-1"><strong>Item:</strong> ${frappe.utils.escape_html(itemInfo)}</div>` : ''}
              ${qtyInfo ? `<div class="small mb-1"><strong>Qty:</strong> ${frappe.utils.escape_html(qtyInfo)}</div>` : ''}
              <div class="small text-muted">${frappe.utils.escape_html(safeMsg)}</div>
            </div>
          `);
          
          // Prepend to show newest first
          $scanHistoryList.prepend(scanEntry);
          
          // Limit to configured max entries
          if ($scanHistoryList.children().length > SCAN_HISTORY_MAX_ENTRIES) {
            $scanHistoryList.children().last().remove();
          }
          
          // Auto-scroll to show the newest entry
          $scanHistoryList.scrollTop(0);
        }
        
        if (ok) {
          alerts.length && alerts.addClass('d-none').text('');
          $scanStatus.length && $scanStatus.text('Material').removeClass().addClass('badge bg-success');
          flashStatus(safeMsg || 'Loaded material', 'success');
          if (state.current_wo) await load_materials_snapshot(state.current_wo);
          try { okTone.play().catch(()=>{}); } catch(_) {}
        } else {
          alerts.length && alerts.removeClass('d-none').text(safeMsg || 'Scan failed');
          $scanStatus.length && $scanStatus.text('Error').removeClass().addClass('badge bg-danger');
          flashStatus(safeMsg || 'Scan failed', 'error'); try { errTone.play().catch(()=>{}); } catch(_) {}
        }
      });
  }

  scan.on('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); const raw = scan.val().trim(); scan.val(''); handleScanValue(raw); } });
  scan.on('change',  (e) => { const raw = (e.target.value || '').trim(); scan.val(''); handleScanValue(raw); });

  // Helper function to update status and banner after an action
  async function updateAfterAction() {
    await load_queue();
    const row = (state.orders || []).find(x => x.name === state.current_wo);
    state.current_wo_status = row ? row.status : null;
    state.current_stage_status = row ? row.stage_status : null;
    const r = await rpc('isnack.api.mes_ops.get_wo_banner', { work_order: state.current_wo }); 
    banner.html(r.message && r.message.html ? r.message.html : '—'); 
    refreshButtonStates();
  }

  // ---------- Buttons ----------
  $('#btn-start',$root).on('click', async () => {
    if (!state.current_wo || !state.current_emp) { ensureOperatorNotice(); return; }
    await rpc('isnack.api.mes_ops.set_work_order_state', { work_order: state.current_wo, action:'Start' });
    flashStatus(`Started — ${state.current_wo}`, 'success');
    await updateAfterAction();
  });

  $('#btn-pause',$root).on('click', async () => {
    if (!state.current_wo || !state.current_emp) { ensureOperatorNotice(); return; }
    // Check if we're in Stopped state -> this is a Resume action
    const action = (state.current_wo_status === 'Stopped') ? 'Resume' : 'Pause';
    await rpc('isnack.api.mes_ops.set_work_order_state', { work_order: state.current_wo, action });
    flashStatus(`${action}d — ${state.current_wo}`, action === 'Resume' ? 'success' : 'warning');
    await updateAfterAction();
  });

  $('#btn-load',$root).on('click', () => {
    if (!state.current_wo || !state.current_emp) { ensureOperatorNotice(); return; }
    
    // Create scan history container HTML
    const scanHistoryHTML = `
      <div class="scan-history-container">
        <div class="h6 mb-2">Scan History</div>
        <div id="scan-history-list" class="scan-history-list">
          <div class="text-muted small scan-history-empty">
            No scans yet. Start scanning materials...
          </div>
        </div>
      </div>
    `;
    
    const d = new frappe.ui.Dialog({ 
      title: 'Load / Scan Materials',
      fields: [
        { 
          fieldname:'info', 
          fieldtype:'HTML', 
          options:'<div class="text-muted">Scan raw, semi-finished, or packaging barcodes now…</div>' 
        },
        { 
          fieldname:'scan_history', 
          fieldtype:'HTML', 
          options: scanHistoryHTML 
        }
      ]
    });
    
    d.show();
    setScanMode(true);
    flashStatus(`Ready to scan for ${state.current_wo}`); 
    focus_scan();
  });

  $('#btn-request',$root).on('click', () => {
    if (!state.current_wo || !state.current_emp) { ensureOperatorNotice(); return; }
    setScanMode(false);  // let the dialog keep focus
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
        rpc('isnack.api.mes_ops.request_material', { work_order: state.current_wo, ...v })
          .then(r => { d.hide(); frappe.msgprint('Material Request: ' + (r.message && r.message.mr)); flashStatus('Material request submitted', 'success'); });
      }
    });
    d.show();
  });

  // Return Materials
  $('#btn-return',$root).on('click', () => {
    if (!state.current_wo || !state.current_emp) { ensureOperatorNotice(); return; }
    setScanMode(false);  // keep focus inside the return dialog
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
          await rpc('isnack.api.mes_ops.return_materials', { work_order: state.current_wo, lines: JSON.stringify(lines) });
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

  // End Shift Return - return WIP without work order
  $('#btn-end-shift-return', $root).on('click', async () => {
    if (!state.current_lines.length) {
      frappe.msgprint('Please set a Factory Line first');
      return;
    }
    if (!state.current_emp) {
      ensureOperatorNotice();
      return;
    }
    
    setScanMode(false);
    
    // If multiple lines are selected, ask user to choose which line to return WIP from
    let selectedLine;
    if (state.current_lines.length > 1) {
      const lineDialog = new frappe.ui.Dialog({
        title: 'Select Line for WIP Return',
        fields: [{
          label: 'Factory Line',
          fieldname: 'line',
          fieldtype: 'Select',
          options: state.current_lines.join('\n'),
          reqd: 1
        }],
        primary_action_label: 'Continue',
        primary_action: (values) => {
          selectedLine = values.line;
          lineDialog.hide();
          performWIPReturn(selectedLine);
        }
      });
      lineDialog.show();
    } else {
      selectedLine = state.current_lines[0];
      performWIPReturn(selectedLine);
    }
  });
  
  async function performWIPReturn(line) {
    setStatus('Loading WIP inventory…');
    
    try {
      const resp = await rpc('isnack.api.mes_ops.get_wip_inventory', { line: line });
      const wipItems = (resp && resp.message && resp.message.items) || [];
      
      if (!wipItems.length) {
        frappe.msgprint(`No items in WIP for line ${line}`);
        flashStatus('No WIP inventory', 'neutral');
        return;
      }
      
      // Build table HTML for WIP items
      const tableHTML = `
        <div class="table-responsive" style="max-height:400px; overflow:auto;">
          <table class="table table-sm table-bordered">
            <thead style="position:sticky; top:0; background:white; z-index:1;">
              <tr>
                <th>Item Code</th>
                <th>Item Name</th>
                <th>Available Qty</th>
                <th>Return Qty</th>
                <th>Batch</th>
                <th>UoM</th>
              </tr>
            </thead>
            <tbody id="wip-items-tbody"></tbody>
          </table>
        </div>
      `;
      
      const d = new frappe.ui.Dialog({
        title: `End Shift Return — ${line}`,
        size: 'large',
        fields: [
          { fieldname: 'wip_table', fieldtype: 'HTML', options: tableHTML }
        ],
        primary_action_label: 'Post Return',
        primary_action: async () => {
          const itemsToReturn = [];
          const $tbody = d.$wrapper.find('#wip-items-tbody');
          
          $tbody.find('tr').each((idx, tr) => {
            const $tr = $(tr);
            const returnQty = parseFloat($tr.find('.return-qty-input').val()) || 0;
            if (returnQty > 0) {
              const itemCode = $tr.data('item-code');
              const batchNo = $tr.data('batch-no') || null;
              itemsToReturn.push({
                item_code: itemCode,
                qty: returnQty,
                batch_no: batchNo
              });
            }
          });
          
          if (!itemsToReturn.length) {
            frappe.msgprint('No items to return (all quantities are 0)');
            return;
          }
          
          setStatus('Posting WIP return…');
          try {
            await rpc('isnack.api.mes_ops.return_wip_to_staging', {
              line: line,
              items: JSON.stringify(itemsToReturn)
            });
            d.hide();
            frappe.show_alert({ message: 'WIP return posted successfully', indicator: 'green' });
            flashStatus('WIP return completed', 'success');
          } catch (err) {
            console.error('Error posting WIP return', err);
          }
        }
      });
      d.$wrapper.addClass('end-shift-return-dialog');
      
      d.show();
      
      // Populate table with WIP items
      const $tbody = d.$wrapper.find('#wip-items-tbody');
      wipItems.forEach((item) => {
        const row = $(`
          <tr data-item-code="${frappe.utils.escape_html(item.item_code)}" data-batch-no="${frappe.utils.escape_html(item.batch_no || '')}">
            <td><strong>${frappe.utils.escape_html(item.item_code)}</strong></td>
            <td>${frappe.utils.escape_html(item.item_name || '')}</td>
            <td class="text-end">${item.qty}</td>
            <td><input type="number" class="form-control form-control-sm return-qty-input" value="${item.qty}" min="0" max="${item.qty}" step="0.01" style="width:100px;"></td>
            <td>${frappe.utils.escape_html(item.batch_no || '—')}</td>
            <td>${frappe.utils.escape_html(item.uom)}</td>
          </tr>
        `);
        $tbody.append(row);
      });
      
      flashStatus('WIP inventory loaded', 'neutral');
      
    } catch (err) {
      console.error('Error loading WIP inventory', err);
    }
  }

  async function showPrintLabelDialog() {
    // Fetch default print format from Factory Settings
    const defaultPrintFormat = await frappe.db.get_single_value('Factory Settings', 'default_label_print_format');
    
    // Validate that a default print format is configured
    if (!defaultPrintFormat) {
      frappe.msgprint({
        title: __('Configuration Error'),
        message: __('No default label print format is configured in Factory Settings. Please set "Default Label Print Format" before printing labels.'),
        indicator: 'red'
      });
      return;
    }

    const d = new frappe.ui.Dialog({
      title:'Print Carton Label (FG only)',
      fields: [
        { label:'Carton Qty', fieldname:'qty', fieldtype:'Float', reqd:1, default:12 }
      ],
      primary_action_label:'Print',
      primary_action: async (v) => {
        setStatus('Creating label and opening print dialog…');
        try {
          const r = await rpc('isnack.api.mes_ops.print_label', { 
            work_order: state.current_wo, 
            carton_qty: v.qty, 
            template: defaultPrintFormat 
          });
          d.hide();
          if (r.message && r.message.print_url) {
            // Use QZ Tray if enabled, otherwise use browser dialog
            await handleLabelPrint(
              r.message.print_url,
              r.message.enable_silent_printing,
              r.message.printer_name,
              state.current_wo
            );
            flashStatus(`Label ready for ${state.current_wo}`, 'success');
          }
        } catch (err) {
          console.error('Print label error:', err);
          frappe.show_alert({message: 'Failed to create label', indicator: 'red'});
        }
      }
    });
    d.show();
  }

  async function showLabelHistoryDialog() {
    if (!state.current_wo || !state.current_emp || !state.current_is_fg) return;
    setScanMode(false);

    const d = new frappe.ui.Dialog({
      title:`Label History — ${state.current_wo}`,
      fields: [
        { fieldtype:'Section Break', label:'Previously Printed Labels' },
        { fieldname:'labels_html', fieldtype:'HTML' }
      ],
      primary_action_label:'Print New Label',
      primary_action: () => {
        d.hide();
        showPrintLabelDialog();
      }
    });

    d.show();
    const $box = d.fields_dict.labels_html.$wrapper;
    $box.html('<div class="text-muted">Loading labels…</div>');

    try {
      const resp = await rpc('isnack.api.mes_ops.list_label_records', { work_order: state.current_wo });
      const rows = (resp && resp.message) || [];
      if (!rows.length) {
        $box.html('<div class="text-muted">No labels recorded for this Work Order yet.</div>');
        return;
      }

      const table = $(`
        <div class="table-responsive">
          <table class="table table-sm table-bordered">
            <thead>
              <tr>
                <th>Label</th>
                <th>Qty</th>
                <th>Item</th>
                <th>Batch</th>
                <th>Template</th>
                <th>Created</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody></tbody>
          </table>
        </div>
      `);
      const $tbody = table.find('tbody');
      rows.forEach((row) => {
        const $tr = $(`
          <tr>
            <td>${frappe.utils.escape_html(row.name)}</td>
            <td>${row.quantity ?? ''}</td>
            <td>${frappe.utils.escape_html(row.item_code || '')}</td>
            <td>${frappe.utils.escape_html(row.batch_no || '')}</td>
            <td>${frappe.utils.escape_html(row.label_template || '')}</td>
            <td>${frappe.utils.escape_html(row.creation || '')}</td>
            <td>
              <button class="btn btn-xs btn-primary me-1" data-action="reprint">Reprint</button>
              <button class="btn btn-xs btn-outline-secondary" data-action="split">Split</button>
            </td>
          </tr>
        `);
        $tr.data('row', row);
        $tbody.append($tr);
      });
      $box.html(table);

      $tbody.on('click', 'button[data-action]', async (e) => {
        const $btn = $(e.currentTarget);
        const action = $btn.data('action');
        const row = $btn.closest('tr').data('row');

        if (action === 'reprint') {
          setStatus('Opening print dialog…');
          const result = await rpc('isnack.api.mes_ops.print_label_record', {
            label_record: row.name,
            reason_code: 'reprint'
          });
          if (result.message && result.message.print_urls && result.message.print_urls.length > 0) {
            const enableSilent = result.message.enable_silent_printing;
            const printerName = result.message.printer_name;
            
            // Print all items with delay between prints
            // Sequential execution is intentional to avoid overwhelming the printer queue
            // and to prevent browser popup blockers when using print dialogs
            for (let idx = 0; idx < result.message.print_urls.length; idx++) {
              const url = result.message.print_urls[idx];
              
              // Add delay between prints (except for first print)
              if (idx > 0) {
                await new Promise(resolve => setTimeout(resolve, PRINT_DIALOG_DELAY_MS));
              }
              
              await handleLabelPrint(url, enableSilent, printerName, `${row.name} item ${idx + 1}`);
            }
            
            // Show success message
            const action = enableSilent ? 'sent to printer' : 'dialog(s) opened';
            const count = result.message.print_urls.length;
            frappe.show_alert({
              message: `${count} label(s) ${action}`, 
              indicator: 'green'
            });
          }
          return;
        }

        if (action === 'split') {
          const splitDialog = new frappe.ui.Dialog({
            title: `Split Label — ${row.name}`,
            fields: [
              { label:'Quantities (comma-separated)', fieldname:'quantities', fieldtype:'Data', reqd:1 },
              { label:'Reason', fieldname:'reason', fieldtype:'Data', default:'split' }
            ],
            primary_action_label:'Split & Print',
            primary_action: async (v) => {
              const quantities = (v.quantities || '')
                .split(',')
                .map((val) => parseFloat(val.trim()))
                .filter((val) => !Number.isNaN(val) && val > 0);
              if (!quantities.length) {
                frappe.msgprint('Provide one or more positive quantities.');
                return;
              }
              setStatus('Opening print dialogs for splits…');
              const result = await rpc('isnack.api.mes_ops.print_label_record', {
                label_record: row.name,
                quantities,
                reason_code: v.reason || 'split'
              });
              splitDialog.hide();
              if (result.message && result.message.print_urls) {
                // Print each split quantity - either via QZ Tray or browser dialog
                const enableSilent = result.message.enable_silent_printing;
                const printerName = result.message.printer_name;
                
                // Sequential execution is intentional to avoid overwhelming the printer queue
                // and to prevent browser popup blockers when using print dialogs
                for (let idx = 0; idx < result.message.print_urls.length; idx++) {
                  const url = result.message.print_urls[idx];
                  // Add fixed delay between prints (except for first print)
                  if (idx > 0) {
                    await new Promise(resolve => setTimeout(resolve, PRINT_DIALOG_DELAY_MS));
                  }
                  await handleLabelPrint(url, enableSilent, printerName, `${row.name} split ${idx + 1}`);
                }
                
                // Show success message
                const action = enableSilent ? 'sent to printer' : 'dialog(s) opened';
                const count = result.message.print_urls.length;
                frappe.show_alert({
                  message: `${count} label(s) ${action}`, 
                  indicator: 'green'
                });
              }
            }
          });
          splitDialog.show();
        }
      });
    } catch (e) {
      console.error(e);
      $box.html('<div class="text-danger">Failed to load label history.</div>');
    }
  }

  // Print Label (FG)
  $('#btn-label',$root).on('click', async () => {
    if (!state.current_wo || !state.current_emp || !state.current_is_fg) return;
    setScanMode(false);
    await showPrintLabelDialog();
  });

  // Label History — list, reprint, and split labels tied to current Work Order
  $('#btn-label-history',$root).on('click', async () => {
    if (!state.current_wo || !state.current_emp || !state.current_is_fg) return;
    await showLabelHistoryDialog();
  });

  // >>> NEW: End WO - Mark work order as ended and consume semi-finished materials <<<
  $('#btn-end-wo',$root).on('click', async () => {
    if (!state.current_wo || !state.current_emp) { ensureOperatorNotice(); return; }
    setScanMode(false);

    // Get semi-finished components (slurry / rice mix etc.) for this WO
    let sfgRows = [];
    try {
      const r2 = await rpc('isnack.api.mes_ops.get_sfg_components_for_wo', { work_order: state.current_wo });
      sfgRows = (r2.message && r2.message.items) || [];
    } catch (e) {
      console.warn('get_sfg_components_for_wo failed', e);
    }

    const fields = [];

    if (sfgRows.length) {
      fields.push({ fieldtype: 'Section Break', label: 'Semi-finished usage (slurry / rice mix)' });
      fields.push({ fieldtype: 'HTML', fieldname: 'sfg_help' });

      sfgRows.forEach((row, idx) => {
        fields.push({
          label: `${(row.item_code || '')} — ${(row.item_name || '')}`,
          fieldname: `sfg_${idx}`,
          fieldtype: 'Float',
          default: 0,
          description: row.uom ? `UOM: ${row.uom}` : '',
        });
      });
    } else {
      fields.push({ 
        fieldtype: 'HTML', 
        fieldname: 'no_sfg_help',
        options: '<div class="text-muted">No semi-finished materials to record. Click End WO to mark this work order as ended.</div>'
      });
    }

    const d = new frappe.ui.Dialog({
      title:'End Work Order',
      fields,
      primary_action_label:'End WO',
      primary_action: (v) => {
        setStatus('Ending work order…');

        const sfgUsage = [];
        sfgRows.forEach((row, idx) => {
          const key = `sfg_${idx}`;
          const rawVal = v[key];
          const qty = parseFloat(rawVal || 0);
          if (qty > 0) {
            sfgUsage.push({ item_code: row.item_code, qty: qty });
          }
        });

        rpc('isnack.api.mes_ops.end_work_order', {
          work_order: state.current_wo,
          sfg_usage: JSON.stringify(sfgUsage),
        }).then(() => {
          d.hide();
          flashStatus(`Ended — ${state.current_wo}`, 'success');
          load_queue();
        });
      }
    });

    const f = d.get_field('sfg_help');
    if (f && f.$wrapper) {
      f.$wrapper.html('<div class="text-muted small mb-2">Enter the actual quantities of semi-finished materials used. They will be consumed from the Semi-finished warehouse.</div>');
    }

    d.show();
  });

  // >>> NEW: Close Production - Complete all ended work orders <<<
  $('#btn-close-production',$root).on('click', async () => {
    if (!state.current_emp || !state.current_lines.length) { 
      flashStatus('Set operator and line first', 'warning'); 
      return; 
    }
    setScanMode(false);

    setStatus('Loading ended work orders…');

    // Get ended work orders
    let endedWOs = [];
    try {
      const r = await rpc('isnack.api.mes_ops.get_ended_work_orders', { 
        lines: JSON.stringify(state.current_lines) 
      });
      endedWOs = (r.message && r.message.work_orders) || [];
    } catch (e) {
      console.error('get_ended_work_orders failed', e);
      flashStatus('Failed to load ended work orders', 'error');
      return;
    }

    if (!endedWOs.length) {
      flashStatus('No ended work orders found for this line', 'warning');
      return;
    }

    // Get packaging items
    let packagingItems = [];
    try {
      const r2 = await rpc('isnack.api.mes_ops.get_packaging_items', {});
      packagingItems = (r2.message && r2.message.items) || [];
    } catch (e) {
      console.warn('get_packaging_items failed', e);
    }

    const fields = [];

    // Show list of ended WOs
    fields.push({ fieldtype: 'Section Break', label: 'Ended Work Orders' });
    fields.push({ 
      fieldtype: 'HTML', 
      fieldname: 'ended_wo_list',
      options: '<div class="mb-3">' + endedWOs.map(wo => 
        `<div class="border rounded p-2 mb-2"><strong>${wo.name}</strong>: ${wo.item_name} (Qty: ${wo.qty})</div>`
      ).join('') + '</div>'
    });

    // Good and Reject quantities
    fields.push({ fieldtype: 'Section Break', label: 'Total Production' });
    fields.push({ label:'Total Good Qty', fieldname:'good_qty', fieldtype:'Float', reqd:1, default: 0 });
    fields.push({ label:'Total Reject Qty', fieldname:'reject_qty', fieldtype:'Float', default: 0 });

    // Packaging materials
    if (packagingItems.length) {
      fields.push({ fieldtype: 'Section Break', label: 'Packaging Materials Used' });
      fields.push({ 
        fieldtype: 'HTML', 
        fieldname: 'packaging_help',
        options: '<div class="text-muted small mb-2">Enter total quantities of packaging materials used across all ended work orders.</div>'
      });

      packagingItems.forEach((item, idx) => {
        fields.push({
          label: `${item.item_code} — ${item.item_name || ''}`,
          fieldname: `pkg_${idx}`,
          fieldtype: 'Float',
          default: 0,
          description: item.stock_uom ? `UOM: ${item.stock_uom}` : '',
        });
      });
    }

    const d = new frappe.ui.Dialog({
      title:'Close Production',
      fields,
      size: 'large',
      primary_action_label:'Close Production',
      primary_action: (v) => {
        if (!v.good_qty || v.good_qty <= 0) {
          frappe.msgprint('Total Good Qty must be greater than zero');
          return;
        }

        setStatus('Closing production…');

        const packagingUsage = [];
        packagingItems.forEach((item, idx) => {
          const key = `pkg_${idx}`;
          const rawVal = v[key];
          const qty = parseFloat(rawVal || 0);
          if (qty > 0) {
            packagingUsage.push({ item_code: item.item_code, qty: qty });
          }
        });

        rpc('isnack.api.mes_ops.close_production', {
          good_qty: v.good_qty,
          reject_qty: v.reject_qty || 0,
          packaging_usage: JSON.stringify(packagingUsage),
          lines: JSON.stringify(state.current_lines),
        }).then(() => {
          d.hide();
          flashStatus(`Production closed for ${endedWOs.length} work order(s)`, 'success');
          load_queue();
        }).catch(err => {
          console.error('close_production failed', err);
        });
      }
    });

    d.show();
  });

  // Initial
  refreshButtonStates();
  render_mat_empty('Select a Work Order to load materials.');
}
