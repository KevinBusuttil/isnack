// Maintenance Technician Hub — mobile/tablet-friendly operational view.
frappe.pages['maintenance-technician-hub'].on_page_load = function (wrapper) {
  const page = frappe.ui.make_app_page({
    parent: wrapper, title: 'Maintenance Technician Hub', single_column: true,
  });
  const $main = $(page.main);
  const templateURL = '/assets/isnack/page/maintenance_technician_hub/maintenance_technician_hub.html';

  fetch(templateURL, { cache: 'no-store' })
    .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.text(); })
    .then(html => { $main.html(html); new MaintenanceTechnicianHub($main, page); })
    .catch(err => {
      console.error('Failed to load technician hub', err);
      $main.html('<div class="alert alert-danger m-3">Failed to load Technician Hub UI.</div>');
    });
};

const BUCKETS = [
  ['overdue', 'Overdue', 'c-overdue', 'b-overdue'],
  ['due_today', 'Due Today', 'c-due_today', 'b-due_today'],
  ['next_7_days', 'Due in Next 7 Days', 'c-next_7_days', 'b-next_7_days'],
  ['in_progress', 'In Progress', 'c-in_progress', 'b-in_progress'],
  ['waiting_for_parts', 'Waiting for Parts', 'c-waiting_for_parts', 'b-waiting_for_parts'],
  ['completed', 'Completed Recently', 'c-completed', 'b-completed'],
];

class MaintenanceTechnicianHub {
  constructor($root, page) {
    this.$root = $root;
    this.page = page;
    this.is_manager = ['Maintenance Manager', 'Maintenance Supervisor', 'System Manager']
      .some(r => (frappe.user_roles || []).includes(r));
    this.technician = frappe.session.user;
    this.bind();
    this.maybe_setup_manager_select();
    const params = frappe.utils.get_query_params();
    if (params.asset) { this.$root.find('#mth-scan-input').val(params.asset); this.do_lookup(); }
    if (params.log) { this.open_detail(params.log); }
    this.refresh();
  }

  bind() {
    this.$root.find('#mth-refresh-btn').on('click', () => this.refresh());
    this.$root.find('#mth-scan-btn').on('click', () => this.do_lookup());
    this.$root.find('#mth-scan-input').on('keydown', (e) => {
      if (e.key === 'Enter') this.do_lookup();
    });
    this.$root.on('click', '[data-action]', (e) => {
      const $b = $(e.currentTarget);
      this.handle_action($b.data('action'), $b.data('log'), $b.data('asset'));
    });
  }

  maybe_setup_manager_select() {
    if (!this.is_manager) return;
    const $sel = this.$root.find('#mth-tech-select').show();
    frappe.call('isnack.api.maintenance_hub.get_technicians').then(r => {
      const techs = r.message || [];
      $sel.append('<option value="">— View as technician —</option>');
      techs.forEach(t => $sel.append(`<option value="${t.user}">${frappe.utils.escape_html(t.full_name)}</option>`));
      $sel.on('change', () => { this.technician = $sel.val() || frappe.session.user; this.refresh(); });
    });
  }

  refresh() {
    const args = {};
    if (this.is_manager && this.technician !== frappe.session.user) args.technician = this.technician;
    this.$root.find('#mth-board').html('<div class="mth-loading">Loading…</div>');
    frappe.call('isnack.api.maintenance_hub.get_technician_work', args).then(r => {
      this.data = r.message || { buckets: {}, counts: {} };
      this.render();
    });
  }

  render() {
    const counts = this.data.counts || {};
    const $summary = this.$root.find('#mth-summary').empty();
    BUCKETS.forEach(([key, label, cls]) => {
      $summary.append(`<span class="mth-chip ${cls}">${counts[key] || 0} <small>${label}</small></span>`);
    });

    const $board = this.$root.find('#mth-board').empty();
    let any = false;
    BUCKETS.forEach(([key, label, cls, bcls]) => {
      const items = (this.data.buckets || {})[key] || [];
      const $sec = $(`<div class="mth-section"></div>`);
      $sec.append(`<div class="mth-section-title"><span class="mth-dot ${cls}"></span>${label} <span style="color:#8d99a6;font-weight:500">(${items.length})</span></div>`);
      const $cards = $('<div class="mth-cards"></div>');
      if (!items.length) {
        $cards.append('<div class="mth-empty">Nothing here.</div>');
      } else {
        any = true;
        items.forEach(it => $cards.append(this.card_html(it, bcls)));
      }
      $sec.append($cards);
      $board.append($sec);
    });
    if (!any) $board.prepend('<div class="mth-empty" style="font-size:16px">No maintenance work assigned to you right now. 🎉</div>');
  }

  card_html(it, bcls) {
    const esc = frappe.utils.escape_html;
    const status = it.custom_operational_status || 'Planned';
    const due = it.due_date ? frappe.datetime.str_to_user(it.due_date) : '—';
    const dur = it.custom_estimated_duration_mins ? `${it.custom_estimated_duration_mins} min` : '';
    const safety = it.custom_safety_warning
      ? `<div class="mth-safety">⚠ ${esc(it.custom_safety_warning)}</div>` : '';
    const parts = it.required_parts_summary
      ? `<div class="mth-parts">🔧 ${esc(it.required_parts_summary)}</div>` : '';
    return `
      <div class="mth-card ${bcls}">
        <h4>${esc(it.task || it.name)}</h4>
        <div class="mth-meta"><b>${esc(it.asset_display_name || it.asset || '')}</b> ${it.asset ? '(' + esc(it.asset) + ')' : ''}</div>
        <div class="mth-meta">📍 ${esc(it.asset_location || '—')} &nbsp; • &nbsp; ${esc(it.maintenance_type || '')}</div>
        <div class="mth-meta mth-due">📅 Due: ${due} ${dur ? '• ⏱ ' + dur : ''}</div>
        <span class="mth-status c-${it.bucket}">${esc(status)}</span>
        ${safety}${parts}
        <div class="mth-actions">
          <button class="mth-btn mth-btn-sm mth-btn-success" data-action="start" data-log="${it.name}">Start</button>
          <button class="mth-btn mth-btn-sm mth-btn-primary" data-action="detail" data-log="${it.name}">View Details</button>
          <button class="mth-btn mth-btn-sm mth-btn-success" data-action="complete" data-log="${it.name}">Complete</button>
          <button class="mth-btn mth-btn-sm mth-btn-warn" data-action="complete_issue" data-log="${it.name}">Complete w/ Issue</button>
          <button class="mth-btn mth-btn-sm" data-action="cannot" data-log="${it.name}">Cannot Complete</button>
          <button class="mth-btn mth-btn-sm mth-btn-danger" data-action="breakdown" data-asset="${esc(it.asset || '')}" data-log="${it.name}">Report Breakdown</button>
          <button class="mth-btn mth-btn-sm" data-action="view_asset" data-asset="${esc(it.asset || '')}">View Asset</button>
        </div>
      </div>`;
  }

  handle_action(action, log, asset) {
    switch (action) {
      case 'start': return this.start(log);
      case 'detail': return this.open_detail(log);
      case 'complete': return this.complete(log, false);
      case 'complete_issue': return this.complete(log, true);
      case 'cannot': return this.cannot_complete(log);
      case 'breakdown': return this.report_breakdown(asset, log);
      case 'view_asset': return asset && frappe.set_route('Form', 'Asset', asset);
    }
  }

  start(log) {
    frappe.call('isnack.api.maintenance_hub.start_task', { log }).then(() => {
      frappe.show_alert({ message: __('Task started'), indicator: 'green' });
      this.refresh();
    });
  }

  complete(log, with_issue) {
    const fields = [
      { fieldname: 'completion_notes', fieldtype: 'Small Text', label: __('Completion Notes') },
    ];
    if (with_issue) fields.push({ fieldname: 'issue_detail', fieldtype: 'Small Text', label: __('Describe the Issue'), reqd: 1 });
    frappe.prompt(fields, (v) => {
      frappe.call('isnack.api.maintenance_hub.complete_task', {
        log, completion_notes: v.completion_notes || '',
        with_issue: with_issue ? 1 : 0, issue_detail: v.issue_detail || '',
      }).then(r => {
        frappe.show_alert({ message: __('Marked {0}', [r.message.status]), indicator: 'green' });
        this.refresh();
      });
    }, with_issue ? __('Complete with Issue') : __('Complete Task'), __('Submit'));
  }

  cannot_complete(log) {
    frappe.prompt([{ fieldname: 'reason', fieldtype: 'Small Text', label: __('Reason'), reqd: 1 }],
      (v) => {
        frappe.call('isnack.api.maintenance_hub.cannot_complete', { log, reason: v.reason })
          .then(() => { frappe.show_alert({ message: __('Recorded'), indicator: 'orange' }); this.refresh(); });
      }, __('Unable to Complete'), __('Submit'));
  }

  report_breakdown(asset, log) {
    if (!asset) { frappe.msgprint(__('No asset linked.')); return; }
    frappe.prompt([
      { fieldname: 'severity', fieldtype: 'Select', label: __('Severity'), options: 'Low\nMedium\nHigh\nCritical', default: 'Medium', reqd: 1 },
      { fieldname: 'issue_type', fieldtype: 'Select', label: __('Issue Type'), options: '\nMechanical\nElectrical\nHydraulic\nPneumatic\nSoftware\nSafety\nOther' },
      { fieldname: 'machine_stopped', fieldtype: 'Check', label: __('Machine Stopped') },
      { fieldname: 'description', fieldtype: 'Small Text', label: __('Description'), reqd: 1 },
    ], (v) => {
      frappe.call('isnack.api.maintenance_breakdown.report_breakdown', {
        asset, description: v.description, severity: v.severity, issue_type: v.issue_type,
        machine_stopped: v.machine_stopped ? 1 : 0, linked_asset_maintenance_log: log,
      }).then(r => frappe.show_alert({ message: __('Breakdown {0} reported', [r.message.name]), indicator: 'red' }));
    }, __('Report Breakdown'), __('Submit'));
  }

  do_lookup() {
    const code = (this.$root.find('#mth-scan-input').val() || '').trim();
    if (!code) return;
    frappe.call('isnack.api.maintenance_hub.lookup_asset', { code }).then(r => {
      const d = r.message;
      const $p = this.$root.find('#mth-asset-panel');
      if (!d || !d.found) { $p.show().html(`<b>No asset found</b> for code "${frappe.utils.escape_html(code)}".`); return; }
      this.render_asset_panel($p, d);
    });
  }

  render_asset_panel($p, d) {
    const esc = frappe.utils.escape_html;
    const a = d.asset_detail || {};
    let html = `<div style="display:flex;justify-content:space-between;align-items:center">
      <h3 style="margin:0">${esc(a.asset_name || d.asset)} <small style="color:#8d99a6">${esc(d.asset)}</small></h3>
      <button class="mth-btn mth-btn-sm" id="mth-asset-close">✕</button></div>
      <div class="mth-meta">📍 ${esc(a.location || '—')} • ${esc(a.asset_category || '')} ${a.serial_no ? '• SN ' + esc(a.serial_no) : ''}</div>`;
    html += `<div style="margin-top:8px"><b>Open maintenance (${(d.open_logs || []).length})</b></div>`;
    (d.open_logs || []).forEach(l => {
      html += `<div class="mth-part-row">• ${esc(l.task || l.name)} — ${esc(l.custom_operational_status || '')}
        <button class="mth-btn mth-btn-sm mth-btn-primary" data-action="detail" data-log="${l.name}">Open</button></div>`;
    });
    if (d.breakdowns && d.breakdowns.length) {
      html += `<div style="margin-top:6px"><b>Open breakdowns (${d.breakdowns.length})</b></div>`;
      d.breakdowns.forEach(b => html += `<div class="mth-meta">⚠ ${esc(b.severity)} — ${esc(b.description || '')}</div>`);
    }
    html += `<div class="mth-actions" style="margin-top:10px">
      <button class="mth-btn mth-btn-sm mth-btn-danger" data-action="breakdown" data-asset="${esc(d.asset)}">Report Breakdown</button>
      <button class="mth-btn mth-btn-sm" data-action="view_asset" data-asset="${esc(d.asset)}">Open Asset</button></div>`;
    if (d.documents && d.documents.length) {
      html += `<div style="margin-top:6px"><b>Documents:</b> ` +
        d.documents.map(f => `<a href="${f.file_url}" target="_blank">${esc(f.file_name)}</a>`).join(' • ') + `</div>`;
    }
    $p.show().html(html);
    $p.find('#mth-asset-close').on('click', () => $p.hide().empty());
  }

  open_detail(log) {
    frappe.call('isnack.api.maintenance_hub.get_task_detail', { log }).then(r => {
      new MaintenanceTaskDetail(r.message, () => this.refresh());
    });
  }
}

// ---- Task detail dialog ----------------------------------------------------
class MaintenanceTaskDetail {
  constructor(data, on_change) {
    this.data = data;
    this.on_change = on_change;
    this.dialog = new frappe.ui.Dialog({
      title: __('Task: {0}', [data.task || data.name]),
      size: 'large',
      fields: [{ fieldtype: 'HTML', fieldname: 'body' }],
    });
    this.render();
    this.dialog.show();
  }

  render() {
    const esc = frappe.utils.escape_html;
    const d = this.data; const a = d.asset_detail || {};
    let h = `<div class="mth-detail">
      <div class="mth-detail-row"><b>Asset</b><span>${esc(a.asset_name || d.asset || '')} (${esc(d.asset || '')})</span></div>
      <div class="mth-detail-row"><b>Serial No</b><span>${esc(a.serial_no || '—')}</span></div>
      <div class="mth-detail-row"><b>Location</b><span>${esc(a.location || '—')}</span></div>
      <div class="mth-detail-row"><b>Status</b><span>${esc(d.custom_operational_status || '')}</span></div>
      <div class="mth-detail-row"><b>Last Maintenance</b><span>${d.last_completion_date ? frappe.datetime.str_to_user(d.last_completion_date) : '—'}</span></div>
      <div class="mth-detail-row"><b>Next Due</b><span>${d.next_due_date ? frappe.datetime.str_to_user(d.next_due_date) : (d.due_date ? frappe.datetime.str_to_user(d.due_date) : '—')}</span></div>
      <div class="mth-detail-row"><b>Description</b><span>${esc(d.description || '—')}</span></div>`;
    if (d.custom_safety_warning) h += `<div class="mth-safety">⚠ ${esc(d.custom_safety_warning)}</div>`;
    h += `</div><hr/>`;

    // Checklist
    h += `<h5>Checklist</h5><div id="mtd-checklist">`;
    if (!(d.checklist || []).length) {
      h += `<div class="mth-empty">No checklist yet. Press <b>Start</b> to generate it from the template.</div>`;
    } else {
      d.checklist.forEach(c => h += this.checkitem_html(c, esc));
    }
    h += `</div><hr/>`;

    // Readings
    h += `<h5>Readings</h5><div id="mtd-readings">`;
    (d.readings || []).forEach(rd => h += `<div class="mth-reading-row">• ${esc(rd.reading_type)}: <b>${rd.reading_value}</b> ${esc(rd.uom || '')} ${rd.is_out_of_range ? '<span style="color:#e24c4c">⚠ out of range</span>' : ''}</div>`);
    h += `</div><button class="mth-btn mth-btn-sm" id="mtd-add-reading">+ Add Reading</button><hr/>`;

    // Spare parts
    h += `<h5>Spare Parts</h5><div id="mtd-spares">`;
    (d.spare_parts || []).forEach(p => h += `<div class="mth-part-row">• [${esc(p.part_type)}] ${esc(p.item_name || p.item_code)} req ${p.required_qty || 0} / used ${p.consumed_qty || 0} (avail ${p.available_qty || 0}) — ${esc(p.status || '')}</div>`);
    h += `</div><div class="mth-actions">
      <button class="mth-btn mth-btn-sm" id="mtd-add-part">+ Add Part</button>
      <button class="mth-btn mth-btn-sm" id="mtd-mr">Create Material Request</button>
      <button class="mth-btn mth-btn-sm" id="mtd-mi">Create Material Issue</button></div><hr/>`;

    // Attachments
    h += `<h5>Photos / Attachments</h5><div>`;
    (d.attachments || []).forEach(f => h += `<a href="${f.file_url}" target="_blank">${esc(f.file_name)}</a> `);
    h += `</div><button class="mth-btn mth-btn-sm" id="mtd-upload">+ Upload Photo</button>`;

    // Footer actions
    h += `<hr/><div class="mth-actions">
      <button class="mth-btn mth-btn-success" id="mtd-start">Start</button>
      <button class="mth-btn mth-btn-success" id="mtd-complete">Complete</button>
      <button class="mth-btn mth-btn-warn" id="mtd-complete-issue">Complete with Issue</button>
      <button class="mth-btn" id="mtd-cannot">Cannot Complete</button></div>`;

    this.dialog.fields_dict.body.$wrapper.html(h);
    this.bind();
  }

  checkitem_html(c, esc) {
    const cls = c.is_safety_step ? 'mth-checkitem safety' : 'mth-checkitem';
    let input = '';
    const id = `chk-${c.name}`;
    if (c.input_type === 'Checkbox') input = `<input type="checkbox" id="${id}" ${c.response_value === '1' ? 'checked' : ''}/>`;
    else if (c.input_type === 'Pass/Fail') input = `<select id="${id}"><option value=""></option><option ${c.pass_fail === 'Pass' ? 'selected' : ''}>Pass</option><option ${c.pass_fail === 'Fail' ? 'selected' : ''}>Fail</option><option ${c.pass_fail === 'N/A' ? 'selected' : ''}>N/A</option></select>`;
    else if (c.input_type === 'Number' || c.input_type === 'Reading') input = `<input type="number" step="any" id="${id}" value="${c.numeric_value != null ? c.numeric_value : ''}" placeholder="${c.uom || ''}"/>`;
    else input = `<input type="text" id="${id}" value="${esc(c.response_value || '')}"/>`;
    return `<div class="${cls}" data-name="${c.name}" data-type="${c.input_type}">
      <div>${c.required ? '<b style="color:#e24c4c">*</b> ' : ''}${esc(c.instruction || '')} ${c.is_safety_step ? '🛡' : ''}</div>
      <div class="mth-reading-row" style="margin-top:6px">${input}
        <button class="mth-btn mth-btn-sm mtd-save-chk" data-name="${c.name}">Save</button>
        ${c.is_out_of_range ? '<span style="color:#e24c4c">⚠</span>' : ''}</div></div>`;
  }

  bind() {
    const log = this.data.name;
    const $w = this.dialog.fields_dict.body.$wrapper;
    $w.find('#mtd-start').on('click', () => frappe.call('isnack.api.maintenance_hub.start_task', { log }).then(() => this.reload()));
    $w.find('#mtd-complete').on('click', () => this.complete(false));
    $w.find('#mtd-complete-issue').on('click', () => this.complete(true));
    $w.find('#mtd-cannot').on('click', () => {
      frappe.prompt([{ fieldname: 'reason', fieldtype: 'Small Text', label: __('Reason'), reqd: 1 }],
        (v) => frappe.call('isnack.api.maintenance_hub.cannot_complete', { log, reason: v.reason }).then(() => { this.close_refresh(); }),
        __('Unable to Complete'), __('Submit'));
    });

    $w.find('.mtd-save-chk').on('click', (e) => {
      const name = $(e.currentTarget).data('name');
      const $item = $w.find(`.mth-checkitem[data-name="${name}"]`);
      const type = $item.data('type');
      const $inp = $item.find(`#chk-${name}`);
      const args = { name };
      if (type === 'Checkbox') args.response_value = $inp.is(':checked') ? '1' : '0';
      else if (type === 'Pass/Fail') args.pass_fail = $inp.val();
      else if (type === 'Number' || type === 'Reading') args.numeric_value = $inp.val();
      else args.response_value = $inp.val();
      frappe.call('isnack.api.maintenance_checklist.save_checklist_response', args)
        .then(() => frappe.show_alert({ message: __('Saved'), indicator: 'green' }));
    });

    $w.find('#mtd-add-reading').on('click', () => {
      frappe.prompt([
        { fieldname: 'reading_type', fieldtype: 'Select', label: __('Type'), options: 'Temperature\nPressure\nVibration\nRunning Hours\nOil Level\nBattery Voltage\nAir Pressure\nCycle Count\nOther', reqd: 1 },
        { fieldname: 'reading_value', fieldtype: 'Float', label: __('Value'), reqd: 1 },
        { fieldname: 'uom', fieldtype: 'Data', label: __('UOM') },
        { fieldname: 'min_value', fieldtype: 'Float', label: __('Min') },
        { fieldname: 'max_value', fieldtype: 'Float', label: __('Max') },
        { fieldname: 'comments', fieldtype: 'Data', label: __('Comments') },
      ], (v) => frappe.call('isnack.api.maintenance_readings.add_reading', Object.assign({ asset_maintenance_log: log }, v)).then((r) => {
        if (r.message.is_out_of_range) frappe.msgprint(__('⚠ Reading is out of range.'));
        this.reload();
      }), __('Add Reading'), __('Save'));
    });

    $w.find('#mtd-add-part').on('click', () => {
      frappe.prompt([
        { fieldname: 'item_code', fieldtype: 'Link', options: 'Item', label: __('Item'), reqd: 1 },
        { fieldname: 'part_type', fieldtype: 'Select', options: 'Required\nConsumed', default: 'Consumed', label: __('Part Type') },
        { fieldname: 'required_qty', fieldtype: 'Float', label: __('Required Qty') },
        { fieldname: 'consumed_qty', fieldtype: 'Float', label: __('Consumed Qty') },
        { fieldname: 'source_warehouse', fieldtype: 'Link', options: 'Warehouse', label: __('Source Warehouse') },
      ], (v) => frappe.call('isnack.api.maintenance_spares.add_spare_part', Object.assign({ asset_maintenance_log: log }, v)).then(() => this.reload()),
        __('Add Spare Part'), __('Save'));
    });

    $w.find('#mtd-mr').on('click', () => frappe.call('isnack.api.maintenance_spares.create_material_request', { asset_maintenance_log: log }).then(r => {
      if (r.message.ok) frappe.msgprint(__('Draft Material Request {0} created. Review & submit it.', [`<a href="${r.message.url}">${r.message.material_request}</a>`]));
      else frappe.msgprint(r.message.message);
    }));
    $w.find('#mtd-mi').on('click', () => frappe.call('isnack.api.maintenance_spares.create_material_issue', { asset_maintenance_log: log }).then(r => {
      if (r.message.ok) frappe.msgprint(__('Draft Stock Entry {0} created. Review & submit it.', [`<a href="${r.message.url}">${r.message.stock_entry}</a>`]));
      else frappe.msgprint(r.message.message);
    }));

    $w.find('#mtd-upload').on('click', () => {
      new frappe.ui.FileUploader({
        doctype: 'Asset Maintenance Log', docname: log,
        on_success: () => this.reload(),
      });
    });
  }

  complete(with_issue) {
    const log = this.data.name;
    const fields = [{ fieldname: 'completion_notes', fieldtype: 'Small Text', label: __('Completion Notes') }];
    if (with_issue) fields.push({ fieldname: 'issue_detail', fieldtype: 'Small Text', label: __('Describe the Issue'), reqd: 1 });
    frappe.prompt(fields, (v) => {
      frappe.call('isnack.api.maintenance_hub.complete_task', {
        log, completion_notes: v.completion_notes || '', with_issue: with_issue ? 1 : 0, issue_detail: v.issue_detail || '',
      }).then(() => this.close_refresh());
    }, with_issue ? __('Complete with Issue') : __('Complete Task'), __('Submit'));
  }

  reload() {
    frappe.call('isnack.api.maintenance_hub.get_task_detail', { log: this.data.name }).then(r => {
      this.data = r.message; this.render(); if (this.on_change) this.on_change();
    });
  }

  close_refresh() {
    this.dialog.hide();
    if (this.on_change) this.on_change();
  }
}
