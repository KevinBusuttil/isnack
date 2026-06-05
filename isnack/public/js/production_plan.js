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
      frm.add_custom_button(__("Print Work Orders"), () =>
        isnack_print_work_orders(frm)
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

frappe.ui.form.on("Production Plan Item", {
  // Default the Finished Goods (For Warehouse) when an item is chosen. This
  // covers the pre-rendered first row, which never fires po_items_add.
  item_code(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    if (frm.__isnack_default_fg_warehouse && !row.warehouse) {
      frappe.model.set_value(cdt, cdn, "warehouse", frm.__isnack_default_fg_warehouse);
    }
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

// Print all Work Orders linked to the Production Plan as a single PDF using
// the "Work Order Detailed" print format.
function isnack_print_work_orders(frm) {
  frappe.call({
    method: "frappe.client.get_list",
    args: {
      doctype: "Work Order",
      fields: ["name"],
      filters: { production_plan: frm.doc.name },
      order_by: "creation asc",
      limit_page_length: 0,
    },
    callback(r) {
      const names = (r.message || []).map((d) => d.name);
      if (!names.length) {
        frappe.msgprint(__("No Work Orders found for this Production Plan."));
        return;
      }
      const url =
        "/api/method/frappe.utils.print_format.download_multi_pdf" +
        "?doctype=" + encodeURIComponent("Work Order") +
        "&name=" + encodeURIComponent(JSON.stringify(names)) +
        "&format=" + encodeURIComponent("Work Order Detailed");
      window.open(url, "_blank");
    },
  });
}

// Pallet-label reprint dialog for a Production Plan's closed Work Orders.
// Mirrors the Operator Hub → Print Labels dialog (including pallet splits)
// so the production manager gets the same UI/UX as line operators. Adds a
// Production-Plan-only "Printed" column so reprints can be targeted.
const ISNACK_PRINT_DIALOG_DELAY_MS = 500;

// The Operator Hub dialog visual theme (.op-dialog) lives in the Operator
// Hub page CSS; pull it in on demand so the Production Plan dialog matches
// pixel-for-pixel. All rules in that file are scoped to .op-teal / .op-dialog
// / body[data-route="operator-hub"], so loading it here cannot leak styles
// into the Production Plan form itself.
function isnack_ensure_op_dialog_css() {
  const cssURL = "/assets/isnack/page/operator_hub/operator_hub.css";
  if (!document.querySelector(`link[href="${cssURL}"]`)) {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = cssURL;
    document.head.appendChild(link);
  }
}

function isnack_op_dialog(opts) {
  const d = new frappe.ui.Dialog(opts);
  if (d && d.$wrapper) d.$wrapper.addClass("isn-dialog-theme op-dialog");
  return d;
}

async function isnack_show_pallet_label_dialog(frm) {
  const production_plan = frm.doc.name;

  isnack_ensure_op_dialog_css();

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
  const allowedPalletUoms = pallet_data.allowed_pallet_uoms || [];

  if (!items.length) {
    frappe.msgprint(__("No closed Work Orders found for this Production Plan."));
    return;
  }

  // Recalculate pallet_qty for a grid row from its carton qty + pallet type.
  async function calculatePalletQty(row) {
    if (!row || !row.doc) return;
    const palletType = row.doc.pallet_type;
    const cartonQty = row.doc.carton_qty || 0;
    if (!palletType || !cartonQty) {
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
          to_uom: palletType,
        },
      });
      const result = (r && r.message) || {};
      if (result.found && result.conversion_factor) {
        row.doc.pallet_qty = cartonQty / result.conversion_factor;
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

  // Compact summary shown in the grid Split column. Per-pallet carton qty
  // is intentionally omitted to avoid truncation — re-tick the row and
  // click Split Selected Row… to view/edit full allocation.
  function formatSplitsSummary(splits) {
    if (!splits || !splits.length) return "";
    const types = splits.map((s) => {
      const name = (s.pallet_type || "").trim();
      return name.replace(/\s+pallet\s*$/i, "") || name;
    });
    return types.join(" + ");
  }

  // Reflect splits onto the parent grid row: when split, blank pallet_type
  // (since multiple types apply) and show total pallet_qty + summary.
  function applySplitsToParentRow(gridRow) {
    if (!gridRow || !gridRow.doc) return;
    const splits = gridRow.doc.splits || [];
    if (splits.length >= 2) {
      gridRow.doc.pallet_type = "";
      gridRow.doc.pallet_qty = splits.reduce(
        (acc, s) => acc + (parseFloat(s.pallet_qty) || 0),
        0
      );
      gridRow.doc.splits_summary = formatSplitsSummary(splits);
    } else if (splits.length === 1) {
      // Single-split == regular single-pallet-type flow; collapse it.
      gridRow.doc.pallet_type = splits[0].pallet_type || "";
      gridRow.doc.pallet_qty = parseFloat(splits[0].pallet_qty) || 0;
      gridRow.doc.splits_summary = "";
      gridRow.doc.splits = [];
    } else {
      gridRow.doc.splits_summary = "";
    }
    gridRow.refresh();
  }

  function showSplitDialog(parentGridRow) {
    if (!parentGridRow || !parentGridRow.doc) return;
    const parentDoc = parentGridRow.doc;
    const totalCarton = parseFloat(parentDoc.carton_qty) || 0;
    if (!totalCarton) {
      frappe.show_alert({ message: __("Set carton qty first"), indicator: "orange" });
      return;
    }
    const itemCode = parentDoc.item_code;
    const fromUom = parentDoc.default_uom;

    const seed = parentDoc.splits && parentDoc.splits.length
      ? parentDoc.splits.map((s) => ({ ...s }))
      : [{
          pallet_type: parentDoc.pallet_type || "",
          carton_qty: totalCarton,
          pallet_qty: parseFloat(parentDoc.pallet_qty) || 0,
        }];

    async function calcSubPalletQty(subRow) {
      if (!subRow || !subRow.doc) return;
      const pt = subRow.doc.pallet_type;
      const cq = parseFloat(subRow.doc.carton_qty) || 0;
      if (!pt || !cq) {
        subRow.doc.pallet_qty = null;
        subRow.refresh();
        return;
      }
      try {
        const r = await frappe.call({
          method: "isnack.api.mes_ops.get_pallet_conversion_factor",
          args: { item_code: itemCode, from_uom: fromUom, to_uom: pt },
        });
        const result = (r && r.message) || {};
        if (result.found && result.conversion_factor) {
          subRow.doc.pallet_qty = cq / result.conversion_factor;
        } else {
          subRow.doc.pallet_qty = null;
        }
        subRow.refresh();
      } catch (err) {
        console.error("Conversion factor fetch failed (split):", err);
      }
    }

    const sd = isnack_op_dialog({
      title: __("Split {0} — total {1} {2}", [itemCode, totalCarton, fromUom || ""]).trim(),
      size: "large",
      fields: [
        {
          fieldname: "help",
          fieldtype: "HTML",
          options: `<div class="text-muted" style="margin-bottom:8px;">${__(
            "Allocate the total carton qty (<b>{0}</b>) across one or more pallet types. The split must sum exactly to the total.",
            [totalCarton]
          )}</div>`,
        },
        {
          fieldname: "split_rows",
          fieldtype: "Table",
          label: __("Splits"),
          cannot_add_rows: false,
          cannot_delete_rows: false,
          in_place_edit: true,
          data: seed,
          fields: [
            {
              fieldname: "pallet_type",
              fieldtype: "Link",
              label: __("Pallet Type"),
              options: "UOM",
              in_list_view: 1,
              columns: 4,
              get_query: () => ({ filters: { name: ["in", allowedPalletUoms] } }),
              onchange: function () {
                calcSubPalletQty(this.grid_row).then(refreshRemaining);
              },
            },
            {
              fieldname: "carton_qty",
              fieldtype: "Float",
              label: __("Carton Qty"),
              in_list_view: 1,
              columns: 3,
              onchange: function () {
                calcSubPalletQty(this.grid_row).then(refreshRemaining);
              },
            },
            {
              fieldname: "pallet_qty",
              fieldtype: "Float",
              label: __("Pallet Qty"),
              in_list_view: 1,
              columns: 3,
            },
          ],
        },
        {
          fieldname: "remaining_html",
          fieldtype: "HTML",
          options: '<div class="isn-split-remaining" style="margin-top:6px;"></div>',
        },
      ],
      primary_action_label: __("Save Split"),
      primary_action: () => {
        const data = sd.fields_dict.split_rows.grid.get_data();
        const valid = data.filter(
          (r) => r.pallet_type && (parseFloat(r.carton_qty) || 0) > 0
        );
        if (!valid.length) {
          frappe.show_alert({
            message: __("Add at least one split row with pallet type and carton qty"),
            indicator: "orange",
          });
          return;
        }
        const seen = new Set();
        for (const r of valid) {
          if (seen.has(r.pallet_type)) {
            frappe.show_alert({
              message: __('Duplicate pallet type "{0}" — merge them into one row', [r.pallet_type]),
              indicator: "red",
            });
            return;
          }
          seen.add(r.pallet_type);
        }
        const sum = valid.reduce(
          (acc, r) => acc + (parseFloat(r.carton_qty) || 0),
          0
        );
        if (Math.abs(sum - totalCarton) > 0.0001) {
          frappe.show_alert({
            message: __("Splits must sum to {0}. Currently {1}.", [totalCarton, sum]),
            indicator: "red",
          });
          return;
        }
        const missingQty = valid.find(
          (r) => !((parseFloat(r.pallet_qty) || 0) > 0)
        );
        if (missingQty) {
          frappe.show_alert({
            message: __('Enter Pallet Qty for "{0}"', [missingQty.pallet_type]),
            indicator: "red",
          });
          return;
        }
        parentDoc.splits = valid.map((r) => ({
          pallet_type: r.pallet_type,
          carton_qty: parseFloat(r.carton_qty) || 0,
          pallet_qty: parseFloat(r.pallet_qty) || 0,
        }));
        applySplitsToParentRow(parentGridRow);
        sd.hide();
      },
      secondary_action_label: __("Clear Split"),
      secondary_action: () => {
        parentDoc.splits = [];
        parentDoc.splits_summary = "";
        parentGridRow.refresh();
        sd.hide();
      },
    });

    function refreshRemaining() {
      const data = sd.fields_dict.split_rows.grid.get_data();
      const sum = data.reduce(
        (acc, r) => acc + (parseFloat(r.carton_qty) || 0),
        0
      );
      const rem = totalCarton - sum;
      const balanced = Math.abs(rem) < 0.0001;
      const tone = balanced ? "success" : rem < 0 ? "danger" : "warning";
      const label = balanced
        ? __("Balanced")
        : rem < 0
          ? __("Over-allocated by")
          : __("Remaining");
      const remDisp = balanced ? "" : ` <b>${Math.abs(rem)}</b>`;
      sd.$wrapper
        .find(".isn-split-remaining")
        .html(
          `<div class="text-${tone}">${__("Allocated")} <b>${sum}</b> / ${totalCarton} • ${label}${remDisp}</div>`
        );
    }

    sd.show();
    setTimeout(async () => {
      const grid = sd.fields_dict.split_rows.grid;
      for (const gr of grid.grid_rows || []) {
        if (
          gr.doc &&
          gr.doc.pallet_type &&
          (parseFloat(gr.doc.carton_qty) || 0) > 0 &&
          !gr.doc.pallet_qty
        ) {
          await calcSubPalletQty(gr);
        }
      }
      refreshRemaining();
    }, 50);
  }

  const d = isnack_op_dialog({
    title: __("Print Pallet Label (FG only)"),
    size: "extra-large",
    fields: [
      {
        fieldname: "pallet_split_help",
        fieldtype: "HTML",
        options:
          '<div class="text-muted" style="margin:0 0 8px 0;">' +
          __(
            "Tick a row and click <b>Split Selected Row…</b> to allocate its carton qty across multiple pallet types (e.g. 800 on EURO 1 + 200 on EURO 4). Re-tick a split row and click the same button to view or edit its allocation."
          ) +
          "</div>",
      },
      {
        fieldname: "pallet_items",
        fieldtype: "Table",
        label: __("Pallet Label Items"),
        cannot_add_rows: true,
        cannot_delete_rows: true,
        in_place_edit: true,
        data: [],
        fields: [
          {
            fieldname: "item_code",
            fieldtype: "Data",
            label: __("Item Code"),
            in_list_view: 1,
            read_only: 1,
            columns: 2,
          },
          {
            fieldname: "description",
            fieldtype: "Data",
            label: __("Description"),
            in_list_view: 1,
            read_only: 1,
            columns: 2,
          },
          {
            fieldname: "default_uom",
            fieldtype: "Data",
            label: __("Default UOM"),
            in_list_view: 0,
            read_only: 1,
          },
          {
            fieldname: "carton_qty",
            fieldtype: "Float",
            label: __("Carton Qty"),
            in_list_view: 1,
            read_only: 0,
            columns: 1,
            onchange: function () {
              if (
                this.grid_row &&
                this.grid_row.doc &&
                (this.grid_row.doc.splits || []).length
              ) {
                this.grid_row.doc.splits = [];
                this.grid_row.doc.splits_summary = "";
                frappe.show_alert({
                  message: __("Split cleared — carton qty changed"),
                  indicator: "orange",
                });
              }
              calculatePalletQty(this.grid_row);
            },
          },
          {
            fieldname: "pallet_type",
            fieldtype: "Link",
            label: __("Pallet Type"),
            in_list_view: 1,
            options: "UOM",
            columns: 2,
            get_query: () => ({ filters: { name: ["in", allowedPalletUoms] } }),
            onchange: function () {
              if (
                this.grid_row &&
                this.grid_row.doc &&
                (this.grid_row.doc.splits || []).length
              ) {
                this.grid_row.doc.splits = [];
                this.grid_row.doc.splits_summary = "";
              }
              calculatePalletQty(this.grid_row);
            },
          },
          {
            fieldname: "pallet_qty",
            fieldtype: "Float",
            label: __("Pallet Qty"),
            in_list_view: 1,
            read_only: 0,
            columns: 1,
          },
          {
            fieldname: "splits_summary",
            fieldtype: "Data",
            label: __("Split"),
            in_list_view: 1,
            read_only: 1,
            columns: 1,
          },
          {
            fieldname: "printed_status",
            fieldtype: "Data",
            label: __("Printed"),
            in_list_view: 1,
            read_only: 1,
            columns: 1,
          },
          {
            fieldname: "work_orders",
            fieldtype: "Data",
            label: __("Work Orders"),
            hidden: 1,
            in_list_view: 0,
          },
        ],
      },
    ],
    secondary_action_label: __("Split Selected Row…"),
    secondary_action: () => {
      const grid = d.fields_dict.pallet_items.grid;
      const rows = grid.grid_rows || [];
      const selected = rows.filter(function (gr) {
        if (!gr || !gr.doc) return false;
        if (gr.doc.__checked === 1 || gr.doc.__checked === true) return true;
        if (gr.wrapper && gr.wrapper.find(".grid-row-check").is(":checked")) {
          return true;
        }
        return false;
      });
      if (selected.length === 0) {
        frappe.show_alert({
          message: __("Tick the row you want to split first"),
          indicator: "orange",
        });
        return;
      }
      if (selected.length > 1) {
        frappe.show_alert({
          message: __("Tick only one row at a time to split"),
          indicator: "orange",
        });
        return;
      }
      showSplitDialog(selected[0]);
    },
    primary_action_label: __("Print Labels"),
    primary_action: async () => {
      const gridData = d.fields_dict.pallet_items.grid.get_data();

      // Expand each item row into one print job per pallet-type split.
      // Rows with no splits and a single pallet_type behave as before.
      const rowsToPrint = [];
      for (const row of gridData) {
        const splits = row.splits || [];
        if (splits.length >= 2) {
          const splitSum = splits.reduce(
            (acc, s) => acc + (parseFloat(s.carton_qty) || 0),
            0
          );
          if (
            Math.abs(splitSum - (parseFloat(row.carton_qty) || 0)) > 0.0001
          ) {
            frappe.show_alert({
              message: __(
                "Split for {0} does not match carton qty — re-open Split…",
                [row.item_code]
              ),
              indicator: "red",
            });
            return;
          }
          for (const s of splits) {
            rowsToPrint.push({
              item_code: row.item_code,
              work_orders: row.work_orders || [],
              pallet_type: s.pallet_type,
              carton_qty: parseFloat(s.carton_qty) || 0,
              pallet_qty: parseFloat(s.pallet_qty) || 0,
            });
          }
        } else if (row.pallet_type && (parseFloat(row.pallet_qty) || 0) > 0) {
          rowsToPrint.push({
            item_code: row.item_code,
            work_orders: row.work_orders || [],
            pallet_type: row.pallet_type,
            carton_qty: parseFloat(row.carton_qty) || 0,
            pallet_qty: parseFloat(row.pallet_qty) || 0,
          });
        }
      }

      if (!rowsToPrint.length) {
        frappe.show_alert({
          message: __("No items with pallet type selected"),
          indicator: "orange",
        });
        return;
      }

      d.disable_primary_action();
      let printedCount = 0;
      for (const row of rowsToPrint) {
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
          for (const url of urls) {
            if (printedCount > 0) {
              await new Promise((res) =>
                setTimeout(res, ISNACK_PRINT_DIALOG_DELAY_MS)
              );
            }
            window.open(url, "_blank");
            printedCount++;
          }
        } catch (err) {
          frappe.show_alert({
            message: __("Failed to print label for {0}", [row.item_code]),
            indicator: "red",
          });
        }
      }

      if (printedCount > 0) {
        frappe.show_alert({
          message: __("{0} pallet label(s) opened for printing", [printedCount]),
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
      default_uom: item.default_uom,
      carton_qty: item.carton_qty,
      pallet_type: "",
      pallet_qty: 0,
      splits: [],
      splits_summary: "",
      printed_status: printed_status,
      work_orders: item.work_orders || [],
    });
  });
  d.fields_dict.pallet_items.grid.refresh();

  d.show();
}