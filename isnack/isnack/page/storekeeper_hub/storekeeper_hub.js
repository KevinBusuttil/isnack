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
    factory_line: '',
    src_warehouse: '',
    posting_date: '',
    pallet_id: '',
    hours: 24,
    selected_bucket: null,  // full bucket object from server
    selected_wos: [],       // names of selected WOs from the chosen bucket
    cart: [],                // [{item_code, item_name, has_batch_no, batch_no, uom, qty, note}]
    selected_transfers: []  // names of Stock Entries selected for picklist
  };

  const fmt_qty = (qty) => {
    const n = parseFloat(qty);
    if (isNaN(n)) return qty ?? '';
    // limit to 3 decimals, strip trailing zeros
    return n.toFixed(3).replace(/\.?0+$/, '');
  };

    const round_qty = (value) => {
    const n = parseFloat(value);
    if (isNaN(n)) return 0;
    return parseFloat(n.toFixed(3));
  };

  const fetch_item_details = async (item_code) => {
    const code = (item_code || '').trim();
    if (!code) {
      return { item_code: '', item_name: '', stock_uom: '', has_batch_no: 0 };
    }

    const d = await frappe.db.get_value('Item', code, ['name', 'item_name', 'stock_uom', 'has_batch_no']);
    if (d && d.message && d.message.name) {
      return d.message;
    }
    return { item_code: code, item_name: '', stock_uom: '', has_batch_no: 0 };
  };

  // ---------- Toolbar Controls ----------
  const $filters = $hub.find('.filters');

  const factory_line = frappe.ui.form.make_control({
    df: { fieldtype: 'Link', label: 'Factory Line', fieldname: 'factory_line', options: 'Factory Line', reqd: 0 },
    parent: $filters.find('.factory-line'),
    render_input: true
  });

  const src_wh = frappe.ui.form.make_control({
    df: { fieldtype: 'Link', label: 'Source Warehouse', fieldname: 'src_warehouse', options: 'Warehouse', reqd: 1 },
    parent: $filters.find('.src-warehouse'),
    render_input: true
  });

  // Default Source Warehouse from Stock Settings
  frappe.db.get_single_value('Stock Settings', 'default_warehouse').then(val => {
    console.log('Default Source Warehouse value to', val);

    const current = src_wh.get_value();
    if (val && !current) {
      src_wh.set_value(val).then(() => {
        state.src_warehouse = src_wh.get_value() || val || '';
      });
    } else {
      state.src_warehouse = current || val || '';

    state.src_warehouse = src_wh.get_value() || '';
    console.log('Default Source Warehouse set to', state.src_warehouse);
    }
  });
  src_wh.$input && src_wh.$input.on('change', () => {
    state.src_warehouse = src_wh.get_value() || '';
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

  // Ensure posting date has a value before first load (defaults to today if empty)
  async function ensure_posting_date_default() {
    if (!posting_date.get_value()) {
      await posting_date.set_value(frappe.datetime.get_today());
    }
    state.posting_date = posting_date.get_value() || '';
  }

  const refresh_btn = $filters.find('.refresh');
  const picklist_btn = $filters.find('.generate-picklist');
  const se_transfer_btn = $filters.find('.se-transfer');
  const se_issue_btn    = $filters.find('.se-issue');
  const se_receipt_btn  = $filters.find('.se-receipt');
  const po_receipt_btn  = $filters.find('.po-receipt'); 

  const read_factory_line = () => {
  const raw = (factory_line.$input && factory_line.$input.val()) || factory_line.get_value() || '';
  const value = (raw || '').trim();
  if (!value && factory_line.get_value()) {
    // ensure the control is actually cleared so the next refresh doesn't reuse stale value
    factory_line.set_value('');
  }
  return value || null;
};


  const refresh = () => {
    state.factory_line = read_factory_line();
    state.src_warehouse = src_wh.get_value();
    state.posting_date = posting_date.get_value() || '';
    load_buckets();
    load_staged();
    load_manual_entries();
    load_pallets();
  };

  refresh_btn.on('click', refresh);

  // --- Generate Picklist from selected transfers ---
  const generate_picklist = () => {
    if (!state.selected_transfers.length) {
      frappe.msgprint(__('Please select at least one staged Stock Entry in "Staged Today".'));
      return;
    }

    const d = new frappe.ui.Dialog({
      title: __('Generate Picklist'),
      fields: [
        {
          fieldname: 'group_same_items',
          fieldtype: 'Check',
          label: __('Group same items (by Item + Batch + Warehouse)'),
          default: 1
        }
      ],
      primary_action_label: __('Create Picklist'),
      primary_action: async (values) => {
        d.hide();
        try {
          const r = await frappe.call({
            method: 'isnack.isnack.page.storekeeper_hub.storekeeper_hub.generate_picklist',
            args: {
              transfers: state.selected_transfers,
              group_same_items: values.group_same_items ? 1 : 0
            },
            freeze: true,
            freeze_message: __('Generating picklist…')
          });
          if (r.message && r.message.name) {
            frappe.show_alert({
              message: __('Picklist {0} created', [r.message.name]),
              indicator: 'green'
            });
            frappe.set_route('Form', 'Picklist', r.message.name);
          }
        } catch (e) {
          console.error(e);
        }
      }
    });

    d.show();
  };

  picklist_btn.on('click', generate_picklist);

  // Optional live refresh on factory line change
  if (factory_line.$input) factory_line.$input.on('change', refresh);

  function make_stock_entry(purpose, defaults = {}) {
    frappe.model.with_doctype('Stock Entry', () => {
      const doc = frappe.model.get_new_doc('Stock Entry');
      doc.purpose = purpose;
      doc.stock_entry_type = purpose;
      Object.assign(doc, defaults);
      frappe.set_route('Form', 'Stock Entry', doc.name);
    });
  }

  function ensure_src_wh() {
    // read from the control, not from cached state
    const wh = src_wh.get_value();

    if (!wh) {
      frappe.msgprint(__('Please select a Source Warehouse first.'));
      return null;
    }

    // keep state in sync for the rest of the page
    state.src_warehouse = wh;
    return wh;
  }

  se_transfer_btn.on('click', () => {
    const wh = ensure_src_wh();
    if (!wh) return;
    make_stock_entry('Material Transfer', {
      from_warehouse: wh
    });
  });

  se_issue_btn.on('click', () => {
    const wh = ensure_src_wh();
    if (!wh) return;
    make_stock_entry('Material Issue', {
      from_warehouse: wh
    });
  });

  se_receipt_btn.on('click', () => {
    const wh = ensure_src_wh();
    if (!wh) return;
    make_stock_entry('Material Receipt', {
      to_warehouse: wh
    });
  });

  po_receipt_btn.on('click', () => {
    show_po_receipt_dialog();
  });

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
  const $manual  = $hub.find('.manual-se');
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
        factory_line: state.factory_line || null,
        posting_date: state.posting_date || null
      }
    });

    $buckets.empty();
    (r.message || []).forEach(b => {
      const allAllocated = (b.wos || []).length && (b.wos || []).every(
        wo => (wo.stage_status || '').toLowerCase() === 'staged'
      );      
      const $bucket = $(`
        <div class="bucket ${allAllocated ? 'fully-allocated' : ''}">
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
            <button class="btn btn-xs btn-primary select-bucket" ${allAllocated ? 'disabled' : ''}>
              ${allAllocated ? __('Fully Allocated') : __('Select for Allocation')}
            </button>

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
      $bucket.find('.select-bucket').on('click', async () => {
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
        await auto_fill_cart_from_selection();
      });

      $buckets.append($bucket);
    });

    if (!$buckets.children().length) {
      $buckets.append('<div class="muted">No open Work Orders for this factory line.</div>');
    }
  }

  // ---------- Cart ----------
  const $cart_scan = $hub.find('.cart-scan');
  const $cart_rows = $hub.find('.cart-rows');

  async function auto_fill_cart_from_selection() {
    if (!state.selected_wos || !state.selected_wos.length) {
      return;
    }

    const r = await frappe.call({
      method: 'isnack.isnack.page.storekeeper_hub.storekeeper_hub.get_consolidated_remaining_items',
      args: { selected_wos: state.selected_wos }
    });

    state.cart = (r.message || []).map(item => ({
      item_code: item.item_code,
      item_name: item.item_name || '',
      has_batch_no: !!item.has_batch_no,
      batch_no: '',
      uom: item.uom || '',
      qty: round_qty(item.qty || 0),
      note: ''
    }));

    redraw_cart();
  }

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
      const want = round_qty(r.message.qty || 0);
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
          <td>
            <div class="item-cell">
              <input class="form-control form-control-sm c-item" value="${frappe.utils.escape_html(r.item_code || '')}">
              <div class="muted item-name">${frappe.utils.escape_html(r.item_name || '')}</div>
            </div>
          </td>
          <td><div class="batch-holder"></div></td>
          <td><input class="form-control form-control-sm c-uom"   style="max-width: 80px;" value="${frappe.utils.escape_html(r.uom || '')}"></td>
          <td><input type="number" class="form-control form-control-sm c-qty" style="max-width: 100px;" value="${fmt_qty(r.qty || 0)}"></td>
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
      const $itemInput = $tr.find('.c-item');
      const $itemName = $tr.find('.item-name');
      const $batchHolder = $tr.find('.batch-holder');

      let batchControl = frappe.ui.form.make_control({
        df: {
          fieldtype: 'Link',
          options: 'Batch',
          placeholder: __('Batch'),
          get_query: () => ({
            query: 'isnack.isnack.page.storekeeper_hub.storekeeper_hub.batch_link_query',
            filters: {
              item_code: r.item_code || null,
              has_expired: 0,
              warehouse: src_wh.get_value() || state.src_warehouse || null
            }
          })
        },
        parent: $batchHolder,
        render_input: true
      });
      batchControl.set_value(r.batch_no || '');
      batchControl.$input && batchControl.$input.on('change', () => { r.batch_no = batchControl.get_value(); });

      $itemInput.on('change', async e => {
        r.item_code = e.target.value;
        // reset batch on item change to force re-selection
        r.batch_no = '';
        r.item_name = '';
        r.has_batch_no = false;
        if (batchControl) {
          batchControl.set_value('');
          batchControl.refresh();
        }
      });

      const details = await fetch_item_details(r.item_code);
      if (details && details.name) {
        r.item_code = details.name;
        r.item_name = details.item_name || '';
        r.has_batch_no = !!details.has_batch_no;
        if (details.stock_uom) r.uom = details.stock_uom;
        $itemInput.val(details.name);
        $itemName.text(details.item_name || '');
        $tr.find('.c-uom').val(r.uom || '');
        if (batchControl) {
          batchControl.refresh();
        }
      } else {
        $itemName.text('');
      }

      $tr.find('.c-uom').on('change',   e => { r.uom = e.target.value; });
      $tr.find('.c-qty').on('change',   e => {
        const rounded = round_qty(e.target.value || 0);
        r.qty = rounded;
        $(e.currentTarget).val(fmt_qty(rounded));
      });
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
    let item_name = '';
    let has_batch_no = false;

    const d = await frappe.db.get_value('Item', code, ['name', 'item_name', 'stock_uom', 'has_batch_no']);
    if (d && d.message && d.message.name) {
      item_code = d.message.name;
      stock_uom = d.message.stock_uom;
      item_name = d.message.item_name || '';
      has_batch_no = !!d.message.has_batch_no;
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
      item_name: item_name,
      has_batch_no: has_batch_no,
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
    state.cart.push({ item_code: '', item_name: '', has_batch_no: false, batch_no: '', uom: '', qty: 0, note: '' });
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
      if (m.qty > 0) row.qty = round_qty(m.qty);
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
    const missing_batch = state.cart.filter(row => row.has_batch_no && !row.batch_no);
    if (missing_batch.length) {
      const codes = missing_batch.map(row => row.item_code).filter(Boolean).join(', ');
      frappe.msgprint(__('Select batch codes for batch-managed items before allocating. Missing: {0}', [codes || __('(unknown item)')]));
      return;
    }

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

  // ---------- Recently Staged / Staged Today ----------
  async function load_staged(){
    $staged.empty().append('<div class="muted">Loading…</div>');
    const r = await frappe.call({
      method: 'isnack.isnack.page.storekeeper_hub.storekeeper_hub.get_recent_transfers',
      args: {
        factory_line: state.factory_line || null,
        hours: state.hours,
        posting_date: state.posting_date || null   // see section 2 below
      }
    });

    $staged.empty();

    const prev_selected = new Set(state.selected_transfers || []);
    state.selected_transfers = [];

    (r.message || []).forEach(se => {
      const is_selected = prev_selected.has(se.name);

      const open_btn = $(`<button class="btn btn-xs btn-default">Open</button>`)
        .on('click', (e) => {
          e.stopPropagation();
          frappe.set_route('Form', 'Stock Entry', se.name);
        });

      const print_btn = $(`<button class="btn btn-xs btn-secondary">Reprint</button>`)
        .on('click', async (e) => {
          e.stopPropagation();
          await frappe.call({
            method: 'isnack.isnack.page.storekeeper_hub.storekeeper_hub.print_labels',
            args: { stock_entry: se.name }
          });
          frappe.show_alert({ message: __('Sent to printer'), indicator: 'green' });
        });

      const info = (se.remarks || '').includes('Pallet:')
        ? se.remarks
        : (se.to_warehouse || '');

      const in_picklist_badge = se.in_picklist
        ? '<span class="chip in-picklist">' + __('In Picklist') + '</span>'
        : '';

      const $row = $(`
        <div class="hub-row staged-row ${is_selected ? 'selected' : ''}" data-name="${se.name}">
          <div class="cell">
            <div class="staged-header">
              <input type="checkbox" class="pick-transfer" ${is_selected ? 'checked' : ''} />
              <div class="staged-main">
                <b>${frappe.utils.escape_html(se.name)}</b> ${in_picklist_badge}<br>
                <span class="muted">${frappe.utils.escape_html(info || '')}</span>
              </div>
            </div>
          </div>
          <div class="cell staged-meta">
            ${frappe.datetime.str_to_user(se.posting_date)} ${se.posting_time || ''}
          </div>
          <div class="cell"><div class="btn-group"></div></div>
        </div>
      `);

      $row.find('.btn-group').append(open_btn, print_btn);

      const sync_selected = (checked) => {
        const name = se.name;
        const idx = state.selected_transfers.indexOf(name);
        if (checked) {
          if (idx === -1) state.selected_transfers.push(name);
          $row.addClass('selected');
        } else {
          if (idx !== -1) state.selected_transfers.splice(idx, 1);
          $row.removeClass('selected');
        }
      };

      // initialise selection
      sync_selected(is_selected);

      // Checkbox toggles selection
      $row.find('.pick-transfer').on('change', (e) => {
        sync_selected(e.currentTarget.checked);
      });

      // Clicking the card (but not buttons/checkbox) also toggles selection
      $row.on('click', (e) => {
        if ($(e.target).closest('button,.pick-transfer').length) return;
        const $cb = $row.find('.pick-transfer');
        $cb.prop('checked', !$cb.prop('checked')).trigger('change');
      });

      $staged.append($row);
    });

    if (!$staged.children().length) {
      $staged.append('<div class="muted">Nothing staged for this production date</div>');
    }
  }

  // ---------- Recent Manual Stock Entries ----------
  async function load_manual_entries(){
    if (!$manual.length) return;

    $manual.empty().append('<div class="muted">Loading…</div>');

    const r = await frappe.call({
      method: 'isnack.isnack.page.storekeeper_hub.storekeeper_hub.get_recent_manual_stock_entries',
      args: {
        source_warehouse: src_wh.get_value() || null,
        hours: state.hours
        // purposes: JSON.stringify(['Material Transfer', 'Material Issue', 'Material Receipt'])
      }
    });

    $manual.empty();

    (r.message || []).forEach(se => {
      const open_btn = $('<button class="btn btn-xs btn-default">Open</button>')
        .on('click', () => frappe.set_route('Form', 'Stock Entry', se.name));

      const from_wh = se.from_warehouse || '';
      const to_wh   = se.to_warehouse || '';
      let wh_text = '';

      if (from_wh && to_wh && from_wh !== to_wh) {
        wh_text = `${frappe.utils.escape_html(from_wh)} &rarr; ${frappe.utils.escape_html(to_wh)}`;
      } else {
        wh_text = frappe.utils.escape_html(from_wh || to_wh || '');
      }

      const $row = $(`
        <div class="hub-row manual-row">
          <div class="cell">
            <b>${frappe.utils.escape_html(se.name)}</b>
            <span class="muted"> · ${frappe.utils.escape_html(se.purpose || '')}</span><br>
            <span class="muted">${wh_text}</span>
          </div>
          <div class="cell">
            ${frappe.datetime.str_to_user(se.posting_date)} ${se.posting_time || ''}
          </div>
          <div class="cell"></div>
        </div>
      `);

      $row.find('.cell:last').append(open_btn);
      $manual.append($row);
    });

    if (!$manual.children().length) {
      $manual.append('<div class="muted">No manual stock entries in the last 24h</div>');
    }
  }


  // ---------- Pallet Tracker ----------
  async function load_pallets(){
    $pallets.empty().append('<div class="muted">Loading…</div>');
    const r = await frappe.call({
      method: 'isnack.isnack.page.storekeeper_hub.storekeeper_hub.get_recent_pallets',
      args: { factory_line: state.factory_line || null, hours: state.hours }
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

  // ---------- PO Receipt Dialog ----------

  let po_receipt_dialog = null;

  function show_po_receipt_dialog() {
    if (po_receipt_dialog) {
      po_receipt_dialog.show();
      return;
    }

    po_receipt_dialog = new frappe.ui.Dialog({
      title: __('PO Receipt'),
      size: 'extra-large',
      static: true,
      fields: [
        {
          fieldname: 'po_section',
          fieldtype: 'Section Break',
          label: __('Purchase Order'),
        },
        {
          fieldname: 'purchase_order',
          fieldtype: 'Link',
          label: __('Purchase Order'),
          options: 'Purchase Order',
          reqd: 1,
          get_query: () => {
            return {
              // use page-level Python module as query
              query: 'isnack.isnack.page.storekeeper_hub.storekeeper_hub.get_open_purchase_orders',
            };
          },
          onchange: () => {
            const d = po_receipt_dialog;
            const po = d.get_value('purchase_order');
            if (po) {
              load_po_items_into_dialog(po);
            } else {
              d.set_value('items', []);
            }
          },
        },
        {
          fieldname: 'col_break_1',
          fieldtype: 'Column Break',
        },
        {
          fieldname: 'company',
          fieldtype: 'Link',
          label: __('Company'),
          options: 'Company',
          read_only: 1,
        },
        {
          fieldname: 'supplier',
          fieldtype: 'Link',
          label: __('Supplier'),
          options: 'Supplier',
          read_only: 1,
        },
        {
          fieldname: 'items_section',
          fieldtype: 'Section Break',
          label: __('Items to Receive'),
        },
        {
          fieldname: 'items',
          fieldtype: 'Table',
          label: __('Items'),
          in_place_edit: true,
          allow_bulk_edit: false,
          reqd: 1,
          cannot_add_rows: 1,      
          cannot_delete_rows: 1,
          hide_toolbar: 1,
          fields: [
            {
              fieldname: 'item_code',
              fieldtype: 'Data',
              label: __('Item Code'),
              in_list_view: 1,
              read_only: 1,
              width: '100px',
              columns: 1,
            },
            {
              fieldname: 'item_name',
              fieldtype: 'Data',
              label: __('Item Name'),
              in_list_view: 1,
              read_only: 1,
              width: '160px',
              columns: 2,
            },
            {
              fieldname: 'uom',
              fieldtype: 'Data',
              label: __('UoM'),
              in_list_view: 1,
              read_only: 1,
              width: '40px',
              columns: 1,
            },
            {
              fieldname: 'ordered_qty',
              fieldtype: 'Float',
              label: __('Ordered'),
              in_list_view: 1,
              read_only: 1,
              width: '100px',
              columns: 1,
            },
            {
              fieldname: 'pending_qty',
              fieldtype: 'Float',
              label: __('Pending'),
              in_list_view: 1,
              read_only: 1,
              width: '80px',
              columns: 1,
            },
            {
              fieldname: 'accepted_qty',
              fieldtype: 'Float',
              label: __('Accepted Qty'),
              in_list_view: 1,
              width: '100px',
              columns: 1,
            },
            {
              fieldname: 'rejected_qty',
              fieldtype: 'Float',
              label: __('Rejected Qty'),
              in_list_view: 1,
              width: '100px',
              columns: 1,
            },
            {
              fieldname: 'batch_no',
              fieldtype: 'Data',
              label: __('Batch No'),
              in_list_view: 1,
              width: '100px',
              columns: 1,
            },
            {
              fieldname: 'expiry_date',
              fieldtype: 'Date',
              label: __('Expiry Date'),
              in_list_view: 1,
              width: '100px',
              columns: 1,
            },
            {
              fieldname: 'requires_batch',
              fieldtype: 'Check',
              label: __('Requires Batch'),
              hidden: 1,
            },
            {
              fieldname: 'already_received_qty',
              fieldtype: 'Float',
              label: __('Already Received'),
              in_list_view: 1,
              read_only: 1,
              width: '100px',
              columns: 1,
            },
            {
              fieldname: 'po_detail',
              fieldtype: 'Data',
              label: __('PO Detail'),
              hidden: 1,
            },
          ],
        },
      ],
      primary_action_label: __('Post'),
      primary_action: () => {
        post_po_receipt();
      },
      secondary_action_label: __('Cancel'),
      secondary_action: () => {
        if (po_receipt_dialog) {
            po_receipt_dialog.hide();
        }
    },

    });

    po_receipt_dialog.show();
  }

  function load_po_items_into_dialog(po_name) {
    const d = po_receipt_dialog;
    frappe.call({
      method: 'isnack.isnack.page.storekeeper_hub.storekeeper_hub.get_po_items',
      args: {
        purchase_order: po_name,
      },
      freeze: true,
      freeze_message: __('Loading PO Items...'),
      callback: function (r) {
        if (!r.message) return;

        d.set_value('company', r.message.company || '');
        d.set_value('supplier', r.message.supplier || '');

        const rows = (r.message.items || []).map((row) => {
          return {
            item_code: row.item_code,
            item_name: row.item_name,
            uom: row.uom,
            ordered_qty: row.qty,
            pending_qty: row.pending_qty,
            accepted_qty: row.pending_suggested || 0,
            rejected_qty: 0,
            batch_no: '',
            expiry_date: row.default_expiry_date || null,
            requires_batch: row.requires_batch,
            already_received_qty: row.received_qty,
            po_detail: row.name,
          };
        });

        const items_field = d.get_field('items');
        const grid = items_field.grid;

        // fill the grid
        grid.df.data = rows;
        grid.refresh();

      },
    });
  }

  function post_po_receipt() {
    const d = po_receipt_dialog;
    const values = d.get_values();

    if (!values || !values.purchase_order) {
      frappe.msgprint({
        title: __('Missing Data'),
        message: __('Please select a Purchase Order.'),
        indicator: 'red',
      });
      return;
    }

    const grid = d.get_field('items').grid;

    // Build items from the live DOM + row docs
    const rows = (grid.grid_rows || [])
      .map(row => {
        const doc = { ...row.doc };              // base data from grid
        const $row = $(row.row);                 // row DOM

        // pull latest visible values from inputs
        const acc_input = $row.find('input[data-fieldname="accepted_qty"]');
        const rej_input = $row.find('input[data-fieldname="rejected_qty"]');
        const batch_input = $row.find('input[data-fieldname="batch_no"]');
        const exp_input = $row.find('input[data-fieldname="expiry_date"]');

        if (acc_input.length) {
          doc.accepted_qty = flt(acc_input.val() || 0);
        }
        if (rej_input.length) {
          doc.rejected_qty = flt(rej_input.val() || 0);
        }
        if (batch_input.length) {
          doc.batch_no = batch_input.val() || '';
        }
        if (exp_input.length) {
          doc.expiry_date = exp_input.val() || null;
        }

        return doc;
      })
      .filter(row => row && row.item_code);      // ignore any empty/template rows

    console.log('PO Receipt Items (from DOM):', rows);  // optional debug

    const items = rows.filter((row) => {
      const accepted = flt(row.accepted_qty || 0);
      const rejected = flt(row.rejected_qty || 0);
      return accepted > 0 || rejected > 0;
    });

    if (!items.length) {
      frappe.msgprint({
        title: __('No Quantities Entered'),
        message: __('Enter Accepted or Rejected quantities for at least one item.'),
        indicator: 'orange',
      });
      return;
    }

    // Basic validation: accepted + rejected must not exceed pending
    for (let row of items) {
      const pending = flt(row.pending_qty || 0);
      const total = flt(row.accepted_qty || 0) + flt(row.rejected_qty || 0);
      if (total > pending + 0.0001) {
        frappe.throw(
          __('Row {0}: Accepted + Rejected ({1}) cannot be greater than Pending ({2}) for item {3}.', [
            row.idx || '',
            total,
            pending,
            row.item_code,
          ])
        );
      }

      if (row.requires_batch && !row.batch_no) {
        frappe.throw(__('Row {0}: Batch No is required for item {1}.', [row.idx || '', row.item_code]));
      }
    }

    frappe.call({
      method: 'isnack.isnack.page.storekeeper_hub.storekeeper_hub.post_po_receipt',
      args: {
        purchase_order: values.purchase_order,
        items: items,
      },
      freeze: true,
      freeze_message: __('Posting Purchase Receipt...'),
      callback: function (r) {
        if (r.exc) return;
        const pr_name = r.message && r.message.purchase_receipt;
        d.hide();

        let msg = __('PO Receipt saved successfully.');
        if (pr_name) {
          msg += '<br>' + __('Purchase Receipt: {0}', [
            `<a href="/app/purchase-receipt/${pr_name}" target="_blank">${pr_name}</a>`,
          ]);
        }

        frappe.msgprint({
          title: __('Success'),
          message: msg,
          indicator: 'green',
        });
      },
    });
  }

  // ---------- Initial Paint ----------
  const redraw_and_refresh = async () => {
    await ensure_posting_date_default();
    redraw_cart();
    refresh();
  };
  redraw_and_refresh();
};
