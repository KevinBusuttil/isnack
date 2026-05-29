frappe.ui.form.off("Production Plan", "make_work_order");

frappe.ui.form.on("Production Plan", {
  onload(frm) {
    isnack_load_production_plan_defaults(frm);
  },

  po_items_add(frm, cdt, cdn) {
    // Default the Finished Goods (For Warehouse) on new Assembly Items rows.
    if (frm.__isnack_default_fg_warehouse) {
      frappe.model.set_value(cdt, cdn, "warehouse", frm.__isnack_default_fg_warehouse);
    }
  },

  refresh(frm) {
    // Restrict Assembly Items to the configured Production Assembly Item Group.
    // Applied in refresh (not setup) because ERPNext's setup_queries sets this
    // same get_query during setup and would otherwise win; refresh always runs
    // after setup, so ours is the one that sticks.
    frm.set_query("item_code", "po_items", () => {
      const filters = { is_stock_item: 1 };
      if (frm.__isnack_assembly_item_group) {
        filters.item_group = frm.__isnack_assembly_item_group;
      }
      return { query: "erpnext.controllers.queries.item_query", filters };
    });

    if (!frm.doc.__islocal) {
      frm.add_custom_button(
        __("Work Orders"),
        () => frappe.set_route("List", "Work Order", { production_plan: frm.doc.name }),
        __("View")
      );
    }

    if (!frm.doc.__islocal && frm.doc.docstatus === 1) {
      frm.add_custom_button(__("Print Pallet Labels"), () =>
        isnack_show_pallet_label_dialog(frm)
      );
    }
  },

  make_work_order(frm) {
    // Guard: if not submitted, just run directly
    if (!frm.doc.name || frm.doc.docstatus !== 1) {
      return frm.events._run_make_work_order(frm);
    }

    // Prevent double clicks while request is running
    if (frm._making_work_orders) {
      return;
    }

    const confirm_again = () => {
      frappe.confirm(
        __("Work Orders already exist for this Production Plan. Create again?"),
        () => frm.events._run_make_work_order(frm),
        () => {}
      );
    };

    // If we already created WOs this session, confirm immediately
    if (frm._work_orders_created) {
      return confirm_again();
    }

    frappe.call({
      method: "frappe.client.get_list",
      args: {
        doctype: "Work Order",
        fields: ["name"],
        filters: { production_plan: frm.doc.name },
        limit_page_length: 1,
      },
      callback(r) {
        const has_existing = Array.isArray(r.message) && r.message.length > 0;

        if (!has_existing) {
          return frm.events._run_make_work_order(frm);
        }

        confirm_again();
      },
    });
  },

  _run_make_work_order(frm) {
    frm._making_work_orders = true;

    frappe.call({
      method: "make_work_order",
      freeze: true,
      doc: frm.doc,
      callback: function () {
        // Mark that WOs were created in this session
        frm._work_orders_created = true;
        frm.reload_doc();
      },
      always: function () {
        frm._making_work_orders = false;
      },
    });
  },
});

// Load Production Plan defaults from Factory Settings and cache them on the
// form so the Assembly Items item-group filter and Finished Goods Warehouse
// default can be applied without an extra round trip per row/lookup.
// Uses a whitelisted server method because Factory Settings is only readable
// by System Manager; a direct client read would be denied for planners.
function isnack_load_production_plan_defaults(frm) {
  frappe.call({
    method: "isnack.overrides.production_plan.get_production_plan_defaults",
    callback(r) {
      const d = (r && r.message) || {};
      frm.__isnack_assembly_item_group = d.assembly_item_group || null;
      frm.__isnack_default_fg_warehouse = d.default_finished_goods_warehouse || null;
    },
  });
}

// Pallet-label reprint dialog for a Production Plan's closed Work Orders.
// Self-contained (not shared with the Operator Hub dialog) and read-only —
// it only reprints labels, it does not move stock or change Work Orders.
async function isnack_show_pallet_label_dialog(frm) {
  const production_plan = frm.doc.name;

  const default_print_format = await frappe.db.get_single_value(
    "Factory Settings",
    "default_fg_label_print_format"
  );
  if (!default_print_format) {
    frappe.msgprint({
      title: __("Configuration Error"),
      message: __(
        'No default label print format is configured in Factory Settings. Please set "Default FG Label Print Format" before printing labels.'
      ),
      indicator: "red",
    });
    return;
  }

  let pallet_data;
  try {
    const r = await frappe.call({
      method: "isnack.api.mes_ops.get_pallet_label_data_for_production_plan",
      args: { production_plan },
    });
    pallet_data = (r && r.message) || {};
  } catch (e) {
    frappe.msgprint({
      title: __("Error"),
      message: __("Failed to load pallet label data."),
      indicator: "red",
    });
    return;
  }

  const items = pallet_data.items || [];
  const allowed_pallet_uoms = pallet_data.allowed_pallet_uoms || [];

  if (!items.length) {
    frappe.msgprint(__("No closed Work Orders found for this Production Plan."));
    return;
  }

  // Recalculate pallet_qty for a grid row from its carton qty + pallet type.
  async function calculate_pallet_qty(row) {
    if (!row || !row.doc) return;
    const pallet_type = row.doc.pallet_type;
    const carton_qty = row.doc.carton_qty || 0;
    if (!pallet_type || !carton_qty) {
      row.doc.pallet_qty = null;
      row.refresh();
      return;
    }
    try {
      const r = await frappe.call({
        method: "isnack.api.mes_ops.get_pallet_conversion_factor",
        args: {
          item_code: row.doc.item_code,
          from_uom: row.doc.default_uom,
          to_uom: pallet_type,
        },
      });
      const result = (r && r.message) || {};
      if (result.found && result.conversion_factor) {
        row.doc.pallet_qty = carton_qty / result.conversion_factor;
      } else {
        row.doc.pallet_qty = null;
      }
      row.refresh();
    } catch (err) {
      frappe.show_alert({
        message: __("Failed to get conversion factor"),
        indicator: "orange",
      });
    }
  }

  const d = new frappe.ui.Dialog({
    title: __("Print Pallet Label (FG only)"),
    size: "extra-large",
    fields: [
      {
        fieldname: "pallet_items",
        fieldtype: "Table",
        label: __("Pallet Label Items"),
        cannot_add_rows: true,
        cannot_delete_rows: true,
        in_place_edit: true,
        data: [],
        fields: [
          { fieldname: "item_code", fieldtype: "Data", label: __("Item Code"), in_list_view: 1, read_only: 1, columns: 2 },
          { fieldname: "description", fieldtype: "Data", label: __("Description"), in_list_view: 1, read_only: 1, columns: 2 },
          { fieldname: "carton_qty", fieldtype: "Float", label: __("Carton Qty"), in_list_view: 1, read_only: 0, columns: 1,
            onchange: function () { calculate_pallet_qty(this.grid_row); } },
          { fieldname: "pallet_type", fieldtype: "Link", label: __("Pallet Type"), in_list_view: 1, options: "UOM", columns: 2,
            get_query: () => ({ filters: { name: ["in", allowed_pallet_uoms] } }),
            onchange: function () { calculate_pallet_qty(this.grid_row); } },
          { fieldname: "pallet_qty", fieldtype: "Float", label: __("Pallet Qty"), in_list_view: 1, read_only: 0, columns: 1 },
          { fieldname: "printed_status", fieldtype: "Data", label: __("Printed"), in_list_view: 1, read_only: 1, columns: 2 },
          { fieldname: "default_uom", fieldtype: "Data", label: __("Default UOM"), in_list_view: 0 },
          { fieldname: "work_orders", fieldtype: "Data", label: __("Work Orders"), hidden: 1, in_list_view: 0 },
        ],
      },
    ],
    primary_action_label: __("Print Labels"),
    primary_action: async () => {
      const grid_data = d.fields_dict.pallet_items.grid.get_data();
      const rows_to_print = grid_data.filter(
        (row) => row.pallet_type && row.pallet_qty > 0
      );
      if (!rows_to_print.length) {
        frappe.show_alert({
          message: __("Select a pallet type and quantity for at least one item"),
          indicator: "orange",
        });
        return;
      }

      d.disable_primary_action();
      let printed_count = 0;
      for (const row of rows_to_print) {
        try {
          const r = await frappe.call({
            method: "isnack.api.mes_ops.print_pallet_label",
            args: {
              item_code: row.item_code,
              pallet_qty: row.pallet_qty,
              pallet_type: row.pallet_type,
              carton_qty: row.carton_qty,
              work_orders: JSON.stringify(row.work_orders || []),
              template: default_print_format,
            },
          });
          const urls = ((r && r.message) || {}).print_urls || [];
          for (let i = 0; i < urls.length; i++) {
            if (printed_count > 0) {
              await new Promise((res) => setTimeout(res, 500));
            }
            window.open(urls[i], "_blank");
            printed_count++;
          }
        } catch (err) {
          frappe.show_alert({
            message: __("Failed to print label for {0}", [row.item_code]),
            indicator: "red",
          });
        }
      }

      if (printed_count > 0) {
        frappe.show_alert({
          message: __("{0} pallet label(s) opened for printing", [printed_count]),
          indicator: "green",
        });
        d.hide();
      } else {
        d.enable_primary_action();
      }
    },
  });

  items.forEach((item) => {
    const total = item.total_wo_count || 0;
    const printed = item.printed_wo_count || 0;
    const when = item.last_printed_on
      ? " " + String(item.last_printed_on).slice(0, 10)
      : "";
    let printed_status;
    if (printed === 0) {
      printed_status = __("Not printed");
    } else if (printed >= total) {
      printed_status = __("Printed") + when;
    } else {
      printed_status = __("Partial ({0}/{1})", [printed, total]) + when;
    }
    d.fields_dict.pallet_items.df.data.push({
      item_code: item.item_code,
      description: item.item_name || item.description || "",
      carton_qty: item.carton_qty,
      pallet_type: "",
      pallet_qty: 0,
      printed_status: printed_status,
      default_uom: item.default_uom,
      work_orders: item.work_orders || [],
    });
  });
  d.fields_dict.pallet_items.grid.refresh();

  d.show();
}