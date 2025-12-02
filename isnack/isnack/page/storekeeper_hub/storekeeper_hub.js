frappe.pages['storekeeper-hub'].on_page_load = function(wrapper) {
  'use strict';

  const page = frappe.ui.make_app_page({
    parent: wrapper,
    title: 'Storekeeper Hub',
    single_column: true
  });

  // Load theme CSS (Deep Cerulean)
  $('<link rel="stylesheet" type="text/css" href="/assets/isnack/css/storekeeper_hub.css">').appendTo(document.head);

  // Render static HTML template
  $(frappe.render_template('storekeeper_hub', {})).appendTo(page.body);

  const $hub = $(wrapper).find('.storekeeper-hub');

  const state = {
    routing: '',
    src_warehouse: '',
    posting_date: '',
    pallet_id: '',
    hours: 24,
    selected_bucket: null,  // full bucket object from server
    selected_wos: [],       // names of selected WOs from the chosen bucket
    cart: []                // [{item_code, batch_no, uom, qty, note}]
  };

  const fmt_qty = (qty) => {
    const n = parseFloat(qty);
    if (isNaN(n)) return qty ?? '';
    // limit to 3 decimals, strip trailing zeros
    return n.toFixed(3).replace(/\.?0+$/, '');
  };

  // ---------- Toolbar Controls ----------
  const $filters = $hub.find('.filters');

  const routing = frappe.ui.form.make_control({
    df: { fieldtype: 'Link', label: 'Routing', fieldname: 'routing', options: 'Routing', reqd: 0 },
    parent: $filters.find('.routing'),
    render_input: true
  });

  const src_wh = frappe.ui.form.make_control({
    df: { fieldtype: 'Link', label: 'Source Warehouse', fieldname: 'src_warehouse', options: 'Warehouse', reqd: 1 },
    parent: $filters.find('.src-warehouse'),
    render_input: true
  });

  // Default Source Warehouse from Stock Settings
  frappe.db.get_single_value('Stock Settings', 'default_warehouse').then(val => {
    if (val && !src_wh.get_value()) {
      src_wh.set_value(val);
    }
  });

  const posting_date = frappe.ui.form.make_control({
    df: {
      fieldtype: 'Date',
      label: 'Prod. Plan Posting Date',
      fieldname: 'posting_date'
    },
    parent: $filters.find('.pallet-id'),   // reuse the same slot in the toolbar
    render_input: true
  });

  // Optional: default to today
  posting_date.set_value(frappe.datetime.get_today());

  const refresh_btn = $filters.find('.refresh');

  const refresh = () => {
    state.routing = routing.get_value();
    state.src_warehouse = src_wh.get_value();
    state.posting_date = posting_date.get_value();
    load_buckets();
    load_staged();
    load_pallets();
  };

  refresh_btn.on('click', refresh);
  // Optional live refresh on routing change
  if (routing.$input) routing.$input.on('change', refresh);

  // ---------- Global Scan ----------
  const $scan = $hub.find('.scan-input');
  const $clear = $hub.find('.clear-scan');
  const route_to = (doctype, name) => frappe.set_route('Form', doctype, name);

  const open_by_scan = async (code) => {
    code = (code || '').trim();
    if (!code) return;

    // Treat non-WO/STE codes as Pallet ID to tag transfers
    if (!/^WO-|^MAT-STE-|^STE-/.test(code)) {
      state.pallet_id = code;
      frappe.show_alert({
        message: __('Pallet set: {0}', [frappe.utils.escape_html(code)]),
        indicator: 'blue'
      });
      return;
    }

    // Stock Entry Detail rowname -> Stock Entry (if scanned a row barcode)
    try {
      const resp = await frappe.call({
        method: 'isnack.isnack.page.storekeeper_hub.storekeeper_hub.find_se_by_item_row',
        args: { rowname: code }
      });
      if (resp && resp.message) return route_to('Stock Entry', resp.message);
    } catch (e) {
      // ignore and continue
    }

    // Stock Entry code
    if (/^MAT-STE-|^STE-/.test(code)) return route_to('Stock Entry', code);

    // Work Order
    if (/^WO-/.test(code)) return route_to('Work Order', code);

    frappe.show_alert({ message: __('Not recognized'), indicator: 'orange' });
  };

  $scan.on('keydown', (e) => { if (e.key === 'Enter') open_by_scan($scan.val()); });
  $clear.on('click', () => { $scan.val(''); $scan.focus(); });

  // ---------- DOM: Buckets & Right Panels ----------
  const $buckets = $hub.find('.buckets');
  const $staged  = $hub.find('.staged');
  const $pallets = $hub.find('.pallets');

  // Visual cues for WO selection within a bucket
  function paint_selection($bucket) {
    // Clear previous selection visuals
    $hub.find('.bucket').removeClass('selected');
    $hub.find('.wo-row').removeClass('selected unselected');

    if (!$bucket || !state.selected_wos || !state.selected_wos.length) return;

    $bucket.addClass('selected');
    $bucket.find('.wo-row').each((_, el) => {
      const $row = $(el);
      const name = $row.find('.wo-check').data('name');
      if (state.selected_wos.includes(name)) {
        $row.addClass('selected').removeClass('unselected');
      } else {
        $row.addClass('unselected').removeClass('selected');
      }
    });
  }

  // ---------- Load Buckets (Same-BOM groups) ----------
  async function load_buckets(){
    $buckets.empty().append('<div class="muted">Loading…</div>');
    const r = await frappe.call({
      method: 'isnack.isnack.page.storekeeper_hub.storekeeper_hub.get_buckets',
      args: {
        routing: routing.get_value() || null,
        posting_date: posting_date.get_value() || null
      }
    });

    $buckets.empty();
    (r.message || []).forEach(b => {
      const $bucket = $(`
        <div class="bucket">
          <div class="title">
            ${frappe.utils.escape_html(b.item_name)}
            <span class="muted">(${frappe.utils.escape_html(b.item_code)})</span>
          </div>
          <div class="meta">
            BOM: ${frappe.utils.escape_html(b.bom_no)} ·
            WOs: ${b.wos.length} ·
            Total Qty: ${fmt_qty(b.total_qty)} ${frappe.utils.escape_html(b.uom || '')}
          </div>
          <div class="wo-list"></div>
          <div class="mt-2">
            <button class="btn btn-xs btn-primary select-bucket">Select for Allocation</button>
          </div>
        </div>
      `);

      // Render WO rows
      const $wol = $bucket.find('.wo-list');

      b.wos.forEach(wo => {
        // date only, no time
        const planned = wo.planned_start_date
          ? frappe.datetime.str_to_user(wo.planned_start_date).split(' ')[0]
          : '';

        let statusChip = '';
        const status = (wo.stage_status || '').toLowerCase();
        if (status === 'staged') {
          statusChip = '<span class="chip allocated">Allocated</span>';
        } else if (status === 'partial') {
          statusChip = '<span class="chip partly-allocated">Partly Allocated</span>';
        }

        const itemLabel = frappe.utils.escape_html(
          wo.item_name || wo.production_item || ''
        );

        const $row = $(`
          <div class="wo-row">
            <input type="checkbox" class="wo-check" data-name="${wo.name}" checked />
            <div class="wo-main">
              <div class="wo-header">
                <div class="wo-title">
                  <b>${frappe.utils.escape_html(wo.name)}</b>
                  ${statusChip}
                </div>
                <div class="muted wo-date">${planned}</div>
              </div>
              <div class="muted">
                ${itemLabel} · ${fmt_qty(wo.qty)} ${frappe.utils.escape_html(wo.uom || '')}
              </div>
            </div>
          </div>
        `);
        $wol.append($row);
      });

      // Live update selection when ticks change
      $bucket.on('change', '.wo-check', (e) => {
        const name = $(e.currentTarget).data('name');
        if (e.currentTarget.checked) {
          if (!state.selected_wos.includes(name)) state.selected_wos.push(name);
        } else {
          state.selected_wos = state.selected_wos.filter(x => x !== name);
        }
        paint_selection($bucket);
      });

      // Select bucket button: capture only checked WOs
      $bucket.find('.select-bucket').on('click', () => {
        state.selected_bucket = b;
        state.selected_wos = [];
        $bucket.find('.wo-check').each((_, el) => {
          if (el.checked) state.selected_wos.push($(el).data('name'));
        });
        frappe.show_alert({
          message: __('Selected bucket: {0} (WOs: {1})', [b.bom_no, state.selected_wos.length]),
          indicator: 'green'
        });
        paint_selection($bucket);
      });

      $buckets.append($bucket);
    });

    if (!$buckets.children().length) {
      $buckets.append('<div class="muted">No open Work Orders for this routing.</div>');
    }
  }

  // ---------- Cart ----------
  const $cart_scan = $hub.find('.cart-scan');
  const $cart_rows = $hub.find('.cart-rows');

  // Add "Fill Cart to Remaining" next to existing buttons
  const $cart_inputs = $hub.find('.cart .cart-inputs');
  const $fillCartBtn = $('<button class="btn btn-sm btn-default fill-cart">Fill Cart to Remaining</button>');
  $cart_inputs.append($fillCartBtn);

  async function set_auto_qty_for_row(idx) {
    const row = state.cart[idx];
    if (!row || !row.item_code) return;
    if (!state.selected_wos || !state.selected_wos.length) return;

    const r = await frappe.call({
      method: 'isnack.isnack.page.storekeeper_hub.storekeeper_hub.get_consolidated_remaining',
      args: { selected_wos: state.selected_wos, item_code: row.item_code }
    });
    if (r && r.message) {
      const want = parseFloat(r.message.qty || 0);
      if (want > 0) row.qty = want;
      if (!row.uom && r.message.uom) row.uom = r.message.uom;
      redraw_cart();
    }
  }

  function redraw_cart(){
    $cart_rows.empty();
    if (!state.cart.length) {
      $cart_rows.append(`<tr><td colspan="6" class="muted">Scan items to add to cart…</td></tr>`);
      return;
    }
    state.cart.forEach((r, idx) => {
      const $tr = $(`
        <tr>
          <td><input class="form-control form-control-sm c-item"  value="${frappe.utils.escape_html(r.item_code || '')}"></td>
          <td><input class="form-control form-control-sm c-batch" value="${frappe.utils.escape_html(r.batch_no || '')}"></td>
          <td><input class="form-control form-control-sm c-uom"   style="max-width: 80px;" value="${frappe.utils.escape_html(r.uom || '')}"></td>
          <td><input type="number" class="form-control form-control-sm c-qty" style="max-width: 100px;" value="${r.qty || 0}"></td>
          <td><input class="form-control form-control-sm c-notes" value="${frappe.utils.escape_html(r.note || '')}"></td>
          <td>
            <div class="btn-group">
              <button class="btn btn-xs btn-default fill">Fill</button>
              <button class="btn btn-xs btn-default del">✕</button>
            </div>
          </td>
        </tr>
      `);

      // Bind row handlers
      $tr.find('.c-item').on('change', e => { r.item_code = e.target.value; });
      $tr.find('.c-batch').on('change', e => { r.batch_no = e.target.value; });
      $tr.find('.c-uom').on('change',   e => { r.uom = e.target.value; });
      $tr.find('.c-qty').on('change',   e => { r.qty = parseFloat(e.target.value || 0); });
      $tr.find('.c-notes').on('change', e => { r.note = e.target.value; });
      $tr.find('.del').on('click', () => { state.cart.splice(idx, 1); redraw_cart(); });
      $tr.find('.fill').on('click', () => set_auto_qty_for_row(idx));

      $cart_rows.append($tr);
    });
  }

  async function add_item_to_cart(code){
    code = (code || '').trim();
    if (!code) return;

    // First resolve the "real" item code (Item.name if it exists)
    let item_code = code;
    let stock_uom = '';

    const d = await frappe.db.get_value('Item', code, ['name', 'stock_uom']);
    if (d && d.message && d.message.name) {
      item_code = d.message.name;
      stock_uom = d.message.stock_uom;
    }

    // Check if this item is already in the cart
    const existing = state.cart.find(r => r.item_code === item_code);
    if (existing) {
      frappe.msgprint(
        __('Item {0} for Work Order was already scanned', [item_code])
      );
      return;
    }

    // New row
    state.cart.push({
      item_code: item_code,
      batch_no: '',
      uom: stock_uom || '',
      qty: 1,
      note: ''
    });

    const idx = state.cart.length - 1;
    redraw_cart();
    // Auto-fill from consolidated remaining across selected WOs
    set_auto_qty_for_row(idx);
  }


  $hub.find('.add-manual').on('click', () => {
    state.cart.push({ item_code: '', batch_no: '', uom: '', qty: 0, note: '' });
    redraw_cart();
  });

  $hub.find('.clear-cart').on('click', () => { state.cart = []; redraw_cart(); });

  $hub.find('.fill-cart').on('click', async () => {
    if (!state.selected_wos || !state.selected_wos.length) {
      frappe.msgprint(__('Select a WO bucket first.'));
      return;
    }
    const codes = state.cart.map(r => r.item_code).filter(Boolean);
    if (!codes.length) return;

    const r = await frappe.call({
      method: 'isnack.isnack.page.storekeeper_hub.storekeeper_hub.get_consolidated_remaining_bulk',
      args: { selected_wos: state.selected_wos, item_codes: codes }
    });

    const map = {};
    (r.message || []).forEach(x => { if (x && x.item_code) map[x.item_code] = x; });
    state.cart.forEach(row => {
      const m = map[row.item_code];
      if (!m) return;
      if (m.qty > 0) row.qty = m.qty;
      if (!row.uom && m.uom) row.uom = m.uom;
    });
    redraw_cart();
  });

  $cart_scan.on('keydown', (e) => {
    if (e.key === 'Enter') {
      add_item_to_cart($cart_scan.val());
      $cart_scan.val('');
    }
  });

  // ---------- Allocate & Create Transfers (Option C) ----------
  $hub.find('.allocate-create').on('click', async () => {
    if (!state.cart.length) return frappe.msgprint(__('Cart is empty.'));
    if (!state.selected_bucket || !state.selected_wos.length) return frappe.msgprint(__('Select a WO bucket and at least one Work Order.'));
    if (!src_wh.get_value()) return frappe.msgprint(__('Please select Source Warehouse.'));

    const args = {
      pallet_id: state.pallet_id || '',
      source_warehouse: src_wh.get_value(),
      selected_wos: state.selected_wos,
      items: state.cart
    };

    frappe.call({
      method: 'isnack.isnack.page.storekeeper_hub.storekeeper_hub.create_consolidated_transfers',
      args,
      freeze: true,
      freeze_message: __('Allocating & creating Stock Entries…'),
      callback: (r) => {
        if (!r.message) return;

        const { transfers } = r.message;
        const $out = $hub.find('.alloc-results').empty();

        if (!transfers || !transfers.length) {
          $out.append(`<div class="muted">Nothing was created (no remaining quantities?).</div>`);
        } else {
          transfers.forEach(se => {
            const $row = $(`
              <div class="hub-row">
                <div class="cell">
                  <b>${frappe.utils.escape_html(se.name)}</b>
                  <div class="muted">WO ${frappe.utils.escape_html(se.work_order || '')}</div>
                </div>
                <div class="cell">
                  ${frappe.utils.escape_html(se.to_warehouse || '')}<br>
                  <span class="muted">${frappe.datetime.str_to_user(se.posting_date)} ${se.posting_time || ''}</span>
                </div>
                <div class="cell">
                  <div class="btn-group">
                    <button class="btn btn-xs btn-default open">Open</button>
                    <button class="btn btn-xs btn-secondary print">Print</button>
                  </div>
                </div>
              </div>
            `);
            $row.find('.open').on('click', () => frappe.set_route('Form', 'Stock Entry', se.name));
            $row.find('.print').on('click', async () => {
              await frappe.call({
                method: 'isnack.isnack.page.storekeeper_hub.storekeeper_hub.print_labels',
                args: { stock_entry: se.name }
              });
              frappe.show_alert({ message: __('Sent to printer'), indicator: 'green' });
            });
            $out.append($row);
          });

          // Reset cart after success and refresh buckets + side panels
          state.cart = [];
          redraw_cart();
          refresh();
        }
      }
    });
  });

  // ---------- Recently Staged ----------
  async function load_staged(){
    $staged.empty().append('<div class="muted">Loading…</div>');
    const r = await frappe.call({
      method: 'isnack.isnack.page.storekeeper_hub.storekeeper_hub.get_recent_transfers',
      args: {
        routing: state.routing || null,
        hours: state.hours,                     // used as fallback when no date
        posting_date: state.posting_date || null
      }
    });
    $staged.empty();
    (r.message || []).forEach(se => {
      const open_btn = $(`<button class="btn btn-xs btn-default">Open</button>`)
        .on('click', () => frappe.set_route('Form', 'Stock Entry', se.name));
      const print_btn = $(`<button class="btn btn-xs btn-secondary">Reprint</button>`)
        .on('click', async () => {
          await frappe.call({
            method: 'isnack.isnack.page.storekeeper_hub.storekeeper_hub.print_labels',
            args: { stock_entry: se.name }
          });
          frappe.show_alert({ message: __('Sent to printer'), indicator: 'green' });
        });
      const info = (se.remarks || '').includes('Pallet:') ? se.remarks : (se.to_warehouse || '');
      $staged.append($(`
        <div class="hub-row">
          <div class="cell"><b>${se.name}</b><br><span class="muted">${frappe.utils.escape_html(info || '')}</span></div>
          <div class="cell">${frappe.datetime.str_to_user(se.posting_date)} ${se.posting_time || ''}</div>
          <div class="cell"><div class="btn-group"></div></div>
        </div>
      `).find('.btn-group').append(open_btn, print_btn).end());
    });
    if (!$staged.children().length)
      $staged.append('<div class="muted">Nothing staged for this production date</div>');

  }

  // ---------- Pallet Tracker ----------
  async function load_pallets(){
    $pallets.empty().append('<div class="muted">Loading…</div>');
    const r = await frappe.call({
      method: 'isnack.isnack.page.storekeeper_hub.storekeeper_hub.get_recent_pallets',
      args: { routing: state.routing || null, hours: state.hours }
    });
    $pallets.empty();
    (r.message || []).forEach(p => {
      const open_btn = $(`<button class="btn btn-xs btn-default">Open</button>`)
        .on('click', () => frappe.set_route('Form', 'Stock Entry', p.name));
      $pallets.append($(`
        <div class="hub-row">
          <div class="cell"><b>${frappe.utils.escape_html(p.pallet_id || '')}</b><br><span class="muted">${frappe.utils.escape_html(p.to_warehouse || '')}</span></div>
          <div class="cell">${frappe.datetime.str_to_user(p.posting_date)} ${p.posting_time || ''}</div>
          <div class="cell"></div>
        </div>
      `).find('.cell:last').append(open_btn).end());
    });
    if (!$pallets.children().length) $pallets.append('<div class="muted">No pallets in the last 24h</div>');
  }

  // ---------- Initial Paint ----------
  const redraw_and_refresh = () => { redraw_cart(); refresh(); };
  redraw_and_refresh();
};
