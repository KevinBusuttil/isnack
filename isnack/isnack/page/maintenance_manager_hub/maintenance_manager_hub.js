// Maintenance Manager Hub — KPIs, work views, reassignment & verification.
frappe.pages['maintenance-manager-hub'].on_page_load = function (wrapper) {
  const page = frappe.ui.make_app_page({
    parent: wrapper, title: 'Maintenance Manager Hub', single_column: true,
  });
  const $main = $(page.main);
  const templateURL = '/assets/isnack/page/maintenance_manager_hub/maintenance_manager_hub.html';
  fetch(templateURL, { cache: 'no-store' })
    .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.text(); })
    .then(html => { $main.html(html); new MaintenanceManagerHub($main); })
    .catch(err => {
      console.error('Failed to load manager hub', err);
      $main.html('<div class="alert alert-danger m-3">Failed to load Manager Hub UI.</div>');
    });
};

const KPI_DEFS = [
  ['overdue', 'Overdue', 'alert'],
  ['due_today', 'Due Today', 'warn'],
  ['due_this_week', 'Due This Week', ''],
  ['unassigned', 'Unassigned', 'warn'],
  ['waiting_for_parts', 'Waiting for Parts', ''],
  ['pending_verification', 'Pending Verification', 'ok'],
  ['critical_breakdowns', 'Critical Breakdowns', 'alert'],
];

const REPORTS = [
  'Maintenance Due Next 30 Days',
  'Overdue Maintenance',
  'Technician Workload',
  'Maintenance Compliance',
];

class MaintenanceManagerHub {
  constructor($root) {
    this.$root = $root;
    this.view = 'today';
    this.bind();
    this.load();
  }

  bind() {
    this.$root.find('.mmh-tab').on('click', (e) => {
      const v = $(e.currentTarget).data('view');
      this.view = v;
      this.$root.find('.mmh-tab').removeClass('active');
      $(e.currentTarget).addClass('active');
      this.render_view();
    });
    this.$root.on('click', '[data-act]', (e) => {
      const $b = $(e.currentTarget);
      this.action($b.data('act'), $b.data('log'));
    });
  }

  load() {
    frappe.call('isnack.api.maintenance_hub.get_manager_dashboard', { view: this.view }).then(r => {
      this.data = r.message;
      this.render_kpis();
      this.render_view();
    });
  }

  render_kpis() {
    const k = (this.data && this.data.kpis) || {};
    const $k = this.$root.find('#mmh-kpis').empty();
    KPI_DEFS.forEach(([key, label, cls]) => {
      const v = k[key] || 0;
      $k.append(`<div class="mmh-kpi ${v && cls ? cls : ''}"><div class="v">${v}</div><div class="l">${label}</div></div>`);
    });
  }

  render_view() {
    const $b = this.$root.find('#mmh-body').empty();
    if (this.view === 'reports') return this.render_reports($b);
    if (this.view === 'breakdown') return this.render_breakdowns($b);
    if (this.view === 'calendar') { frappe.set_route('List', 'Asset Maintenance Log', 'Calendar'); return; }
    if (this.view === 'kanban') { frappe.set_route('List', 'Asset Maintenance Log'); return; }
    // list views (today/this_week/next_30) — reload from server for fresh filter
    frappe.call('isnack.api.maintenance_hub.get_manager_dashboard', { view: this.view }).then(r => {
      this.data = r.message; this.render_kpis(); this.render_list($b, r.message.logs || []);
    });
  }

  render_list($b, logs) {
    const esc = frappe.utils.escape_html;
    const today = (this.data && this.data.server_date) || frappe.datetime.now_date();
    let h = `<div class="mmh-row header"><div>Task / Asset</div><div>Technician</div><div>Due</div><div>Status</div><div>Type</div><div>Actions</div></div>`;
    if (!logs.length) { $b.html(h + '<div class="mmh-empty">No tasks in this window.</div>'); return; }
    logs.forEach(l => {
      const overdue = l.due_date && l.due_date < today;
      h += `<div class="mmh-row">
        <div><b>${esc(l.task || l.name)}</b><br><small>${esc(l.asset_display_name || l.asset || '')}</small></div>
        <div>${esc((l.custom_assigned_technician || '').split('@')[0] || '<i>unassigned</i>')}</div>
        <div class="${overdue ? 'mmh-overdue' : ''}">${l.due_date ? frappe.datetime.str_to_user(l.due_date) : '—'}</div>
        <div><span class="mmh-pill">${esc(l.custom_operational_status || 'Planned')}</span></div>
        <div>${esc(l.maintenance_type || '')}</div>
        <div class="mmh-actions">
          <button class="mmh-btn" data-act="reassign" data-log="${l.name}">Reassign</button>
          <button class="mmh-btn" data-act="status" data-log="${l.name}">Status</button>
          <button class="mmh-btn" data-act="verify" data-log="${l.name}">Verify</button>
          <button class="mmh-btn" data-act="open" data-log="${l.name}">Open</button>
        </div></div>`;
    });
    $b.html(h);
  }

  render_reports($b) {
    let h = '<h4>Reports</h4>';
    REPORTS.forEach(r => h += `<a class="mmh-report-link" href="/app/query-report/${encodeURIComponent(r)}">📊 ${r}</a>`);
    $b.html(h);
  }

  render_breakdowns($b) {
    frappe.call('frappe.client.get_list', {
      doctype: 'Asset Breakdown',
      filters: { status: ['not in', ['Resolved', 'Cancelled']] },
      fields: ['name', 'asset_name', 'severity', 'status', 'description', 'machine_stopped'],
      order_by: 'severity desc, reported_on desc', limit_page_length: 50,
    }).then(r => {
      const esc = frappe.utils.escape_html;
      let h = `<div class="mmh-row header"><div>Asset</div><div>Severity</div><div>Status</div><div>Stopped</div><div>Description</div><div></div></div>`;
      (r.message || []).forEach(b => {
        h += `<div class="mmh-row">
          <div>${esc(b.asset_name || '')}</div>
          <div><span class="mmh-pill">${esc(b.severity)}</span></div>
          <div>${esc(b.status)}</div>
          <div>${b.machine_stopped ? '🛑' : ''}</div>
          <div>${esc((b.description || '').slice(0, 80))}</div>
          <div><a class="mmh-btn" href="/app/asset-breakdown/${b.name}">Open</a></div></div>`;
      });
      if (!(r.message || []).length) h += '<div class="mmh-empty">No open breakdowns.</div>';
      $b.html(h);
    });
  }

  action(act, log) {
    if (act === 'open') return frappe.set_route('Form', 'Asset Maintenance Log', log);
    if (act === 'verify') {
      return frappe.prompt([{ fieldname: 'comments', fieldtype: 'Small Text', label: __('Verification Comments') }],
        (v) => frappe.call('isnack.api.maintenance_hub.verify_task', { log, comments: v.comments }).then(() => { frappe.show_alert({ message: __('Verified'), indicator: 'green' }); this.load(); }),
        __('Verify Task'), __('Verify'));
    }
    if (act === 'status') {
      return frappe.prompt([
        { fieldname: 'status', fieldtype: 'Select', label: __('Status'), reqd: 1,
          options: ['Planned', 'Assigned', 'Acknowledged', 'In Progress', 'Waiting for Parts', 'Waiting for Shutdown', 'Completed', 'Completed with Issue', 'Cannot Complete', 'Skipped', 'Cancelled', 'Overdue', 'Pending Verification', 'Verified'].join('\n') },
        { fieldname: 'comment', fieldtype: 'Small Text', label: __('Comment') },
      ], (v) => frappe.call('isnack.api.maintenance_hub.set_operational_status', { log, status: v.status, comment: v.comment }).then(() => { frappe.show_alert({ message: __('Updated'), indicator: 'blue' }); this.load(); }),
        __('Change Status'), __('Save'));
    }
    if (act === 'reassign') {
      frappe.call('isnack.api.maintenance_hub.get_technicians').then(r => {
        const opts = (r.message || []).map(t => t.user).join('\n');
        frappe.prompt([
          { fieldname: 'technician', fieldtype: 'Select', label: __('Technician'), options: opts, reqd: 1 },
          { fieldname: 'due_date', fieldtype: 'Date', label: __('New Due Date (optional)') },
        ], (v) => frappe.call('isnack.api.maintenance_hub.reassign_task', { log, technician: v.technician, due_date: v.due_date }).then(() => { frappe.show_alert({ message: __('Reassigned'), indicator: 'green' }); this.load(); }),
          __('Reassign Task'), __('Assign'));
      });
    }
  }
}
