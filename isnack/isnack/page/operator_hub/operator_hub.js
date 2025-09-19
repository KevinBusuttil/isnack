// Operator Hub — uses external HTML (no injection of markup), adds Status Bar + clock

frappe.pages['operator-hub'].on_page_load = function (wrapper) {
  // keep your scaffold
  const page = frappe.ui.make_app_page({
    parent: wrapper,
    title: 'Operator Hub',
    single_column: true
  });

  const $main = $(page.main);

  // IMPORTANT: this path must match /assets/<app_name>/...
  const templateURL = '/assets/isnack/page/operator_hub/operator_hub.html';

  fetch(templateURL, { cache: 'no-store' })
    .then(r => {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.text();
    })
    .then(html => {
      $main.html(html);
      init_operator_hub($main);   // bind behavior after HTML is in the DOM
    })
    .catch(err => {
      console.error('Failed to load operator_hub.html', err);
      $main.html('<div class="alert alert-danger m-3">Failed to load Operator Hub UI.</div>');
    });
};

// All logic goes here; runs AFTER HTML is injected
function init_operator_hub($root) {
  const banner = $('#wo-banner', $root);
  const grid   = $('#wo-grid',   $root);
  const alerts = $('#alerts',    $root);
  const scan   = $('#scan',      $root);

  const state  = { current_wo: null, assigned: [] };

  // --- Status bar elements ---
  const $statusBar  = $('#status-bar');         // bottom sticky region
  const $statusMsg  = $('#status-message');
  const $statusConn = $('#status-connection');

  // --- Status helpers ---
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

  // Online / Offline indication
  setConnection(navigator.onLine);
  window.addEventListener('online',  () => setConnection(true));
  window.addEventListener('offline', () => setConnection(false));

  // Live clock (24h HH:MM)
  const $clock = $('#op-time', $root);
  function tick() {
    const d = new Date();
    const hh = String(d.getHours()).padStart(2,'0');
    const mm = String(d.getMinutes()).padStart(2,'0');
    $clock.text(`${hh}:${mm}`);
  }
  tick();
  setInterval(tick, 30000);

  // Safe RPC wrapper (nice errors to status bar)
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

  // Load assigned WOs
  rpc('isnack.api.mes_ops.get_assigned_work_orders').then(r => {
    state.assigned = r.message || [];
    render_grid();
    if (!state.current_wo && state.assigned.length) set_active(state.assigned[0].name);
    flashStatus(`Loaded ${state.assigned.length} work order(s)`, 'success');
  });

  function render_grid() {
    grid.empty();
    if (!state.assigned.length) {
      grid.html('<div class="text-muted">No work orders assigned.</div>');
      return;
    }
    state.assigned.forEach(row => {
      const chipType = row.type === 'FG' ? 'chip chip-fg' : 'chip chip-sf';
      const stClass = ({
        'Not Started':'chip chip-ns','In Process':'chip chip-running',
        'On Hold':'chip chip-paused','Stopped':'chip chip-stopped','Completed':'chip chip-running'
      }[row.status] || 'chip chip-ns');

      const el = $(`
        <button class="list-group-item list-group-item-action py-3 d-flex justify-content-between align-items-center" type="button">
          <div class="fw-semibold">
            <span class="me-2">${frappe.utils.escape_html(row.name)}</span>
            <span class="text-muted">— ${frappe.utils.escape_html(row.item_name)}</span>
            <span class="text-muted ms-2">Target ${row.qty}</span>
          </div>
          <div class="d-flex gap-2">
            <span class="${chipType}">${row.type}</span>
            <span class="${stClass}">${row.status}</span>
          </div>
        </button>
      `);
      el.on('click', () => set_active(row.name));
      grid.append(el);
    });
  }

  function set_active(wo_name) {
    state.current_wo = wo_name;

    rpc('isnack.api.mes_ops.get_wo_banner', { work_order: wo_name })
      .then(r => banner.html(r.message && r.message.html ? r.message.html : '—'));

    rpc('isnack.api.mes_ops.is_finished_good', { work_order: wo_name })
      .then(r => {
        $('#btn-label', $root).prop('disabled', !r.message);
        flashStatus(`Selected ${wo_name} (${r.message ? 'FG' : 'SF'})`, 'neutral');
      });
  }

  // Scanner handling
  scan.on('change', (e) => {
    const code = (e.target.value || '').trim();
    scan.val('');
    if (!code || !state.current_wo) return;
    setStatus('Processing scan…');

    rpc('isnack.api.mes_ops.scan_material', {
      work_order: state.current_wo, code
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
  });

  // Buttons
  $('#btn-load', $root).on('click', () => {
    if (!state.current_wo) return;
    new frappe.ui.Dialog({
      title: 'Load / Scan Materials',
      fields: [{ fieldname: 'info', fieldtype: 'HTML', options: '<div class="text-muted">Scan raw, semi-finished, or packaging barcodes now…</div>' }]
    }).show();
    flashStatus(`Ready to scan for ${state.current_wo}`);
    focus_scan();
  });

  $('#btn-prod', $root).on('click', () => {
    if (!state.current_wo) return;
    const d = new frappe.ui.Dialog({
      title:'Production Control',
      fields: [
        { label:'Action', fieldname:'action', fieldtype:'Select', options:['Start','Pause','Stop'], reqd:1 },
        { label:'Reason (if Pause/Stop)', fieldname:'reason', fieldtype:'Select', options:['Changeover','Material Shortage','Breakdown','Quality Check','Other'] },
        { label:'Remarks', fieldname:'remarks', fieldtype:'Small Text' }
      ],
      primary_action_label:'Apply',
      primary_action: (v) => {
        rpc('isnack.api.mes_ops.set_wo_status', { work_order: state.current_wo, ...v })
          .then(() => {
            d.hide();
            set_active(state.current_wo);
            const tone = v.action === 'Start' ? 'success' : (v.action === 'Pause' ? 'warning' : 'error');
            flashStatus(`${v.action} — ${state.current_wo}`, tone);
          });
      }
    });
    d.show();
  });

  $('#btn-label', $root).on('click', () => {
    if (!state.current_wo) return;
    const d = new frappe.ui.Dialog({
      title:'Print Carton Label (FG only)',
      fields: [
        { label:'Carton Qty', fieldname:'qty', fieldtype:'Float', reqd:1, default:12 },
        { label:'Template',   fieldname:'template', fieldtype:'Link', options:'Print Template', reqd:1 },
        { label:'Printer',    fieldname:'printer', fieldtype:'Data', reqd:1, default:'ZPL_PRN_1' }
      ],
      primary_action_label:'Print',
      primary_action: (v) => {
        setStatus('Sending label to printer…');
        rpc('isnack.api.mes_ops.print_label', {
          work_order: state.current_wo, carton_qty: v.qty, template: v.template, printer: v.printer
        }).then(() => {
          d.hide();
          frappe.show_alert({message:'Label printed', indicator:'green'});
          flashStatus(`Label printed — ${state.current_wo}`, 'success');
        });
      }
    });
    d.show();
  });

  $('#btn-request', $root).on('click', () => {
    if (!state.current_wo) return;
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
    const d = new frappe.ui.Dialog({
      title:'Close / End Work Order',
      fields: [
        { label:'Good Qty', fieldname:'good', fieldtype:'Float', reqd:1 },
        { label:'Rejects',  fieldname:'rejects', fieldtype:'Float', default:0 },
        { label:'Remarks',  fieldname:'remarks', fieldtype:'Small Text' }
      ],
      primary_action_label:'Complete',
      primary_action: (v) => {
        setStatus('Completing work order…');
        rpc('isnack.api.mes_ops.complete_work_order', { work_order: state.current_wo, ...v })
          .then(() => {
            d.hide();
            flashStatus(`Completed — ${state.current_wo}`, 'success');
            // refresh list to reflect status changes
            return rpc('isnack.api.mes_ops.get_assigned_work_orders');
          })
          .then(r => { state.assigned = r.message || []; render_grid(); });
      }
    });
    d.show();
  });

  // Tiny CSS nicety (safe to keep)
  $('<style>').text(`
    .mes-operator .card { border-color: var(--gray-200); }
    .mes-operator .badge { font-size: .8rem; }
  `).appendTo(document.head);
}
