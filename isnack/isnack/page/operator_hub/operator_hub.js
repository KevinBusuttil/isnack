// Operator Hub — Kiosk-ready: line-centric Job Cards, employee claim/leave, line-aware scan

frappe.pages['operator-hub'].on_page_load = function (wrapper) {
  const page = frappe.ui.make_app_page({
    parent: wrapper,
    title: 'Operator Hub',
    single_column: true
  });

  const $main = $(page.main);
  const templateURL = '/assets/isnack/page/operator_hub/operator_hub.html';

  fetch(templateURL, { cache: 'no-store' })
    .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.text(); })
    .then(html => { $main.html(html); init_operator_hub($main); })
    .catch(err => {
      console.error('Failed to load operator_hub.html', err);
      $main.html('<div class="alert alert-danger m-3">Failed to load Operator Hub UI.</div>');
    });
};

function init_operator_hub($root) {
  const banner = $('#wo-banner', $root);
  const grid   = $('#wo-grid',   $root);
  const alerts = $('#alerts',    $root);
  const scan   = $('#scan',      $root);

  const state  = {
    current_card: null,
    current_wo: null,
    cards: [],
    current_line: localStorage.getItem('kiosk_line') || null,
    current_emp: null,
    current_emp_name: null
  };

  // Status bar
  const $statusBar  = $('#status-bar');
  const $statusMsg  = $('#status-message');
  const $statusConn = $('#status-connection');

  // scope styles to this page & load page CSS
  $root.addClass('op-teal');
  (() => {
    const cssURL = '/assets/isnack/page/operator_hub/operator_hub.css';
    if (!document.querySelector(`link[href="${cssURL}"]`)) {
      const link = document.createElement('link');
      link.rel = 'stylesheet';
      link.href = cssURL;
      document.head.appendChild(link);
    }
  })();

  function setConnection(isOnline) {
    $statusConn.text(isOnline ? 'Online' : 'Offline');
    $statusBar.removeClass('bg-danger bg-warning bg-success bg-dark')
              .addClass(isOnline ? 'bg-dark' : 'bg-danger');
  }
  function setStatus(message, tone = 'neutral') {
    $statusMsg.text(message);
    $statusBar.removeClass('bg-danger bg-warning bg-success bg-dark');
    if (tone === 'success') $statusBar.addClass('bg-success');
    else if (tone === 'warning') $statusBar.addClass('bg-warning');
    else if (tone === 'error') $statusBar.addClass('bg-danger');
    else $statusBar.addClass('bg-dark');
  }
  function flashStatus(message, tone = 'neutral', ms = 2500) {
    setStatus(message, tone);
    setTimeout(() => setStatus('Ready', 'neutral'), ms);
  }

  setConnection(navigator.onLine);
  window.addEventListener('online',  () => setConnection(true));
  window.addEventListener('offline', () => setConnection(false));

  // Live clock
  const $clock = $('#op-time', $root);
  function tick() {
    const d = new Date();
    const hh = String(d.getHours()).padStart(2,'0');
    const mm = String(d.getMinutes()).padStart(2,'0');
    $clock.text(`${hh}:${mm}`);
  }
  tick(); setInterval(tick, 30000);

  // Safe RPC
  function rpc(path, args) {
    return frappe.call(path, args).catch(err => {
      console.error('RPC error', path, err);
      flashStatus('Error: ' + (err?.message || path), 'error');
      throw err;
    });
  }

  // Keep scanner focused
  const focus_scan = () => scan.trigger('focus');
  setInterval(focus_scan, 1500); focus_scan();

  // Inject Kiosk controls if missing
  (function ensureKioskControls(){
    if (!$('#kiosk-controls', $root).length) {
      const $row = $(`
        <div id="kiosk-controls" class="d-flex align-items-center gap-2 mb-2">
          <span class="badge bg-info text-dark">Line: <span id="kiosk-line-label">—</span></span>
          <button id="kiosk-choose-line" class="btn btn-sm btn-outline-primary">Set Line</button>
          <span class="badge bg-secondary">Operator: <span id="kiosk-emp-label">—</span></span>
          <button id="kiosk-choose-emp" class="btn btn-sm btn-outline-secondary">Set Operator</button>
          <button id="kiosk-clear-emp" class="btn btn-sm btn-outline-danger">Clear</button>
        </div>
      `);
      $row.insertBefore($root.find('#wo-grid'));
    }
    $('#kiosk-line-label').text(state.current_line || '—');
    $('#kiosk-emp-label').text(state.current_emp_name || '—');
  })();

  // Realtime print listener (bind once)
  if (!window.__opHubRealtimeBound) {
    frappe.realtime.on('isnack_print', ({ printer, raw }) => {
      window.postMessage({ type: 'PRINT_RAW', printer, raw }, '*');
    });
    window.__opHubRealtimeBound = true;
  }

  // Choose line
  $('#kiosk-choose-line', $root).on('click', async () => {
    const ws = await frappe.db.get_list('Workstation', {fields:['name'], limit: 200, order_by: 'name asc'});
    const opts = (ws || []).map(x => x.name).join('\n');
    const d = new frappe.ui.Dialog({
      title: 'Select Line (Workstation)',
      fields: [{ label:'Workstation', fieldname:'line', fieldtype:'Select', options: opts, reqd:1 }],
      primary_action_label: 'Apply',
      primary_action: v => {
        state.current_line = v.line;
        localStorage.setItem('kiosk_line', v.line);
        $('#kiosk-line-label').text(v.line);
        d.hide();
        load_queue(); // reload queue for this line
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
          state.current_emp = r.message.employee;
          state.current_emp_name = r.message.employee_name;
          $('#kiosk-emp-label').text(state.current_emp_name);
          d.hide();
        } else {
          frappe.msgprint('Could not resolve employee.');
        }
      }
    });
    d.show();
  });

  $('#kiosk-clear-emp', $root).on('click', () => {
    state.current_emp = null; state.current_emp_name = null;
    $('#kiosk-emp-label').text('—');
  });

  // Load queue for current line
  function load_queue() {
    setStatus('Loading queue…');
    const args = state.current_line ? { line: state.current_line } : {};
    return rpc('isnack.api.mes_ops.get_line_queue', args).then(r => {
      state.cards = r.message || r || [];
      render_grid();
      if (!state.current_card && state.cards.length) set_active_card(state.cards[0].name);
      flashStatus(`Loaded ${state.cards.length} job card(s)`, 'success');
    });
  }
  load_queue();

  function render_grid() {
    grid.empty();
    if (!state.cards.length) {
      grid.html('<div class="text-muted">No job cards in queue for this line.</div>');
      return;
    }
    state.cards.forEach(row => {
      const chipType = row.type === 'FG' ? 'chip chip-fg' : 'chip chip-sf';
      const stClass = ({
        'Open':'chip chip-ns','Work In Progress':'chip chip-running',
        'On Hold':'chip chip-paused','Completed':'chip chip-running'
      }[row.status] || 'chip chip-ns');

      const el = $(`
        <button class="list-group-item list-group-item-action py-3 d-flex justify-content-between align-items-center" type="button">
          <div class="fw-semibold">
            <span class="me-2">${frappe.utils.escape_html(row.name)}</span>
            <span class="text-muted">— ${frappe.utils.escape_html(row.item_name || '')}</span>
            <span class="text-muted ms-2">Op ${frappe.utils.escape_html(row.operation || '')}</span>
            <span class="text-muted ms-2">Qty ${row.for_quantity}</span>
            <span class="text-muted ms-2">Crew ${row.crew_open}</span>
          </div>
          <div class="d-flex gap-2">
            <span class="${chipType}">${row.type}</span>
            <span class="${stClass}">${row.status}</span>
          </div>
        </button>
      `);
      el.on('click', () => set_active_card(row.name));
      grid.append(el);
    });
  }

  function set_active_card(card_name) {
    state.current_card = card_name;

    // derive the WO from our cached list
    const row = (state.cards || []).find(x => x.name === card_name);
    state.current_wo = row ? row.work_order : null;

    rpc('isnack.api.mes_ops.get_card_banner', { job_card: card_name })
      .then(r => banner.html(r.message && r.message.html ? r.message.html : '—'));

    // enable label button only if FG
    if (row) {
      const isFG = row.type === 'FG';
      $('#btn-label', $root).prop('disabled', !isFG);
      flashStatus(`Selected ${card_name} (${isFG ? 'FG' : 'SF'})`, 'neutral');
    } else {
      $('#btn-label', $root).prop('disabled', true);
    }
  }

  // Scanner input helpers
  async function handleScanValue(raw) {
    if (!raw) return;

    // Badge fast-path: EMP:<code>
    if (/^EMP:/i.test(raw)) {
      const badge = raw.replace(/^EMP:/i, '');
      const r = await frappe.call('isnack.api.mes_ops.resolve_employee', { badge });
      if (r.message && r.message.ok) {
        state.current_emp = r.message.employee;
        state.current_emp_name = r.message.employee_name;
        $('#kiosk-emp-label').text(state.current_emp_name);
        flashStatus(`Operator: ${state.current_emp_name}`, 'success');
      } else {
        flashStatus('Unknown badge', 'error');
      }
      return;
    }

    // Material scan
    if (!state.current_card) { flashStatus('Pick a Job Card first', 'warning'); return; }
    setStatus('Processing scan…');

    rpc('isnack.api.mes_ops.scan_material', {
      job_card: state.current_card, code: raw
    }).then(r => {
      const { ok, msg } = r.message || {};
      frappe.show_alert({ message: msg || 'Scan processed', indicator: ok ? 'green' : 'red' });
      if (ok) {
        if (alerts.length) alerts.addClass('d-none').text('');
        flashStatus(msg || 'Loaded material', 'success');
      } else {
        if (alerts.length) alerts.removeClass('d-none').text(msg || 'Scan failed');
        flashStatus(msg || 'Scan failed', 'error');
      }
    });
  }

  // Scanner handling — support Enter AND change events
  scan.on('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      const raw = scan.val().trim();
      scan.val('');
      handleScanValue(raw);
    }
  });
  scan.on('change', (e) => {
    const raw = (e.target.value || '').trim();
    scan.val('');
    handleScanValue(raw);
  });

  // Ensure Claim/Leave buttons exist (if not in your HTML)
  (function ensureClaimLeaveButtons(){
    if (!$('#btn-claim', $root).length) {
      $('<button id="btn-claim" class="btn btn-outline-primary ms-2">Claim</button>').insertAfter($('#btn-prod', $root));
    }
    if (!$('#btn-leave', $root).length) {
      $('<button id="btn-leave" class="btn btn-outline-secondary ms-2">Leave</button>').insertAfter($('#btn-claim', $root));
    }
  })();

  // Claim / Leave (must have operator set)
  $('#btn-claim', $root).on('click', () => {
    if (!state.current_card) return;
    if (!state.current_emp) { frappe.msgprint('Set Operator first.'); return; }
    rpc('isnack.api.mes_ops.claim_job_card', { job_card: state.current_card, employee: state.current_emp })
      .then(() => rpc('isnack.api.mes_ops.get_card_banner', { job_card: state.current_card }))
      .then(r => banner.html(r.message.html))
      .then(load_queue);
  });

  $('#btn-leave', $root).on('click', () => {
    if (!state.current_card) return;
    if (!state.current_emp) { frappe.msgprint('Set Operator first.'); return; }
    rpc('isnack.api.mes_ops.leave_job_card', { job_card: state.current_card, employee: state.current_emp })
      .then(() => rpc('isnack.api.mes_ops.get_card_banner', { job_card: state.current_card }))
      .then(r => banner.html(r.message.html))
      .then(load_queue);
  });

  // Buttons (dialogs)
  $('#btn-load', $root).on('click', () => {
    if (!state.current_card) return;
    new frappe.ui.Dialog({
      title: 'Load / Scan Materials',
      fields: [{ fieldname: 'info', fieldtype: 'HTML', options: '<div class="text-muted">Scan raw, semi-finished, or packaging barcodes now…</div>' }]
    }).show();
    flashStatus(`Ready to scan for ${state.current_card}`);
    focus_scan();
  });

  $('#btn-prod', $root).on('click', () => {
    if (!state.current_card) return;
    const d = new frappe.ui.Dialog({
      title:'Production Control (Job Card)',
      fields: [
        { label:'Action', fieldname:'action', fieldtype:'Select', options:['Start','Pause','Stop'], reqd:1 },
        { label:'Reason (if Pause/Stop)', fieldname:'reason', fieldtype:'Select', options:['Changeover','Material Shortage','Breakdown','Quality Check','Other'] },
        { label:'Remarks', fieldname:'remarks', fieldtype:'Small Text' }
      ],
      primary_action_label:'Apply',
      primary_action: (v) => {
        rpc('isnack.api.mes_ops.set_card_status', { job_card: state.current_card, ...v })
          .then(() => {
            d.hide();
            set_active_card(state.current_card);
            const tone = v.action === 'Start' ? 'success' : (v.action === 'Pause' ? 'warning' : 'error');
            flashStatus(`${v.action} — ${state.current_card}`, tone);
            return load_queue();
          });
      }
    });
    d.show();
  });

  $('#btn-label', $root).on('click', () => {
    if (!state.current_card) return;
    const d = new frappe.ui.Dialog({
      title:'Print Carton Label (FG only)',
      fields: [
        { label:'Carton Qty', fieldname:'qty', fieldtype:'Float', reqd:1, default:12 },
        // backend supports Label Template or Print Template
        { label:'Template',   fieldname:'template', fieldtype:'Link', options:'Print Template', reqd:1 },
        { label:'Printer',    fieldname:'printer', fieldtype:'Data', reqd:1, default:'ZPL_PRN_1' }
      ],
      primary_action_label:'Print',
      primary_action: (v) => {
        setStatus('Sending label to printer…');
        rpc('isnack.api.mes_ops.print_label', {
          job_card: state.current_card, carton_qty: v.qty, template: v.template, printer: v.printer
        }).then(() => {
          d.hide();
          frappe.show_alert({message:'Label sent', indicator:'green'});
          flashStatus(`Label printed — ${state.current_card}`, 'success');
        });
      }
    });
    d.show();
  });

  $('#btn-request', $root).on('click', () => {
    if (!state.current_card) return;
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
          .then(r => {
            d.hide();
            frappe.msgprint('Material Request: ' + (r.message && r.message.mr));
            flashStatus('Material request submitted', 'success');
          });
      }
    });
    d.show();
  });

  $('#btn-close', $root).on('click', () => {
    if (!state.current_wo) return;
    rpc('isnack.api.mes_ops.get_wo_progress', { work_order: state.current_wo })
      .then(r => {
        const p = r.message || {};
        const d = new frappe.ui.Dialog({
          title:'Close / End Work Order',
          fields: [
            { label:'Good Qty', fieldname:'good', fieldtype:'Float', reqd:1, default: p.remaining || 0 },
            { label:'Rejects',  fieldname:'rejects', fieldtype:'Float', default: 0 },
            { label:'Remarks',  fieldname:'remarks', fieldtype:'Small Text' }
          ],
          primary_action_label:'Complete',
          primary_action: (v) => {
            setStatus('Completing work order…');
            rpc('isnack.api.mes_ops.complete_work_order', { work_order: state.current_wo, ...v })
              .then(() => { d.hide(); flashStatus(`Completed — ${state.current_wo}`, 'success'); return load_queue(); });
          }
        });
        d.show();
      });
  });
}
