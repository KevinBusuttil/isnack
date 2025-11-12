frappe.provide('storekeeper');

storekeeper.WIP_BY_LINE = {
  'Frying': 'WIP - Frying',
  'Execution': 'WIP - Execution'
};


frappe.pages['storekeeper_hub'].on_page_load = function(wrapper) {
  const page = frappe.ui.make_app_page({
    parent: wrapper,
    title: 'Storekeeper Hub',
    single_column: true
  });

  $(frappe.render_template('storekeeper_hub', {})).appendTo(page.body);

  const $hub = $(wrapper).find('.storekeeper-hub');
  const state = {
    company: frappe.defaults.get_default('company'),
    line: 'Frying',
    hours: 24
  };

  // Filters
  const $filters = $hub.find('.filters');
  const company = frappe.ui.form.make_control({
    df: {fieldtype: 'Link', label: 'Company', fieldname: 'company', options: 'Company', default: state.company, reqd: 1},
    parent: $filters,
    render_input: true
  });
  const line = frappe.ui.form.make_control({
    df: {fieldtype: 'Select', label: 'Line', fieldname: 'line', options: ['Frying','Execution'], default: state.line},
    parent: $filters,
    render_input: true
  });
  const refresh_btn = $('<button class="btn btn-sm btn-primary ml-2">Refresh</button>').appendTo($filters);

  const refresh = () => {
    state.company = company.get_value();
    state.line = line.get_value();
    load_queue();
    load_picks();
    load_staged();
  };

  refresh_btn.on('click', refresh);

  // Scan box handlers
  const $scan = $hub.find('.scan-input');
  const $clear = $hub.find('.clear-scan');
  const route_to = (doctype, name) => frappe.set_route('Form', doctype, name);

  const open_by_scan = async (code) => {
    code = (code || '').trim();
    if (!code) return;

    // Pallet ID (Stock Entry Item name) → find parent Stock Entry
    let resp = await frappe.call({
      method: 'isnack.isnack.page.storekeeper_hub.storekeeper_hub.find_se_by_item_row',
      args: { rowname: code }
    });
    if (resp && resp.message) {
      return route_to('Stock Entry', resp.message);
    }

    // Direct Stock Entry
    if (/^MAT-STE-|^STE-/.test(code)) return route_to('Stock Entry', code);

    // Work Order
    if (/^WO-/.test(code)) return route_to('Work Order', code);

    frappe.show_alert({message: __('Not recognized'), indicator: 'orange'});
  };

  $scan.on('keydown', (e) => {
    if (e.key === 'Enter') open_by_scan($scan.val());
  });
  $clear.on('click', () => { $scan.val(''); $scan.focus(); });

  // Lists
  const $queue = $hub.find('.list.queue');
  const $picks = $hub.find('.list.picks');
  const $staged = $hub.find('.list.staged');

  const wip_for = (wo) => wo.wip_warehouse || storekeeper.WIP_BY_LINE[wo.manufacturing_line] || '';

  const row_html = (cols) => `<div class="hub-row">${cols.map(c => `<div class="cell">${c}</div>`).join('')}</div>`;

  async function load_queue(){
    $queue.empty().append('<div class="text-muted">Loading…</div>');
    const r = await frappe.call({
      method: 'isnack.isnack.page.storekeeper_hub.storekeeper_hub.get_queue',
      args: { company: state.company, line: line.get_value() }
    });
    $queue.empty();
    (r.message || []).forEach(wo => {
      const make_pick_btn = $(`<button class="btn btn-xs btn-primary">Create Pick List</button>`)
        .on('click', async () => {
          const target_wip = wip_for(wo);
          const res = await frappe.call({
            method: 'isnack.isnack.page.storekeeper_hub.storekeeper_hub.create_pick_list',
            args: { work_order: wo.name, target_wip }
          });
          frappe.set_route('Form', 'Pick List', res.message);
        });
      const open_wo_btn = $(`<button class="btn btn-xs btn-default">Open WO</button>`)
        .on('click', () => frappe.set_route('Form', 'Work Order', wo.name));

      const badge = `<span class="indicator ${wo.stage_status==='Staged'?'green':wo.stage_status==='Partial'?'orange':'red'}">${wo.stage_status}</span>`;
      const cols = [
        `<b>${wo.name}</b><br><span class="text-muted">${wo.item_name}</span>`,
        `Qty: ${wo.qty} ${wo.uom}<br>Line: ${wo.manufacturing_line || '-'}<br>WIP: ${frappe.utils.escape_html(wip_for(wo) || '-')}`,
        badge,
        `<div class="btn-group">${make_pick_btn[0].outerHTML}${open_wo_btn[0].outerHTML}</div>`
      ];
      const $row = $(row_html(cols));
      $row.find('.btn-group').replaceWith($('<div class="btn-group"/>').append(make_pick_btn, open_wo_btn));
      $queue.append($row);
    });
    if (!$queue.children().length) $queue.append('<div class="text-muted">Nothing to stage</div>');
  }

  async function load_picks(){
    $picks.empty().append('<div class="text-muted">Loading…</div>');
    const r = await frappe.call({
      method: 'isnack.isnack.page.storekeeper_hub.storekeeper_hub.get_picks',
      args: { my_only: 1 }
    });
    $picks.empty();
    (r.message || []).forEach(p => {
      const open_btn = $(`<button class="btn btn-xs btn-default">Open</button>`).on('click', ()=> frappe.set_route('Form', 'Pick List', p.name));
      $picks.append($(row_html([
        `<b>${p.name}</b><br><span class="text-muted">WO ${p.work_order || ''}</span>`,
        `${frappe.datetime.str_to_user(p.modified)}`,
        open_btn[0].outerHTML
      ])).find('.btn-xs').replaceWith(open_btn).end());
    });
    if (!$picks.children().length) $picks.append('<div class="text-muted">No open picks</div>');
  }

  async function load_staged(){
    $staged.empty().append('<div class="text-muted">Loading…</div>');
    const r = await frappe.call({
      method: 'isnack.isnack.page.storekeeper_hub.storekeeper_hub.get_recent_transfers',
      args: { line: state.line, hours: state.hours }
    });
    $staged.empty();
    (r.message || []).forEach(se => {
      const open_btn = $(`<button class="btn btn-xs btn-default">Open</button>`).on('click', ()=> frappe.set_route('Form', 'Stock Entry', se.name));
      const print_btn = $(`<button class="btn btn-xs btn-secondary">Reprint</button>`)
        .on('click', async ()=> {
          await frappe.call({
            method: 'isnack.isnack.page.storekeeper_hub.storekeeper_hub.print_labels',
            args: { stock_entry: se.name }
          });
          frappe.show_alert({message: __('Sent to printer'), indicator: 'green'});
        });
      $staged.append($(row_html([
        `<b>${se.name}</b><br><span class="text-muted">${se.to_warehouse || ''}</span>`,
        `${frappe.datetime.str_to_user(se.posting_date)} ${se.posting_time || ''}`,
        `<div class="btn-group"></div>`
      ])).find('.btn-group').append(open_btn, print_btn).end());
    });
    if (!$staged.children().length) $staged.append('<div class="text-muted">Nothing staged recently</div>');
  }

  // Initial
  refresh();
};