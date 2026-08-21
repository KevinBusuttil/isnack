// Copyright (c) 2026, Busuttil Technologies Limited and contributors
// For license information, please see license.txt

// Backport of ERPNext version-15's "Allow Editing of Items and Quantities in
// Work Order" grid behaviour onto v15.87.2.
//
// This reproduces the *current* upstream implementation
// (work_order.js `toggle_items_editable`, as it stands after commits 1d36cb5 ->
// 62d5870 -> 3c327d5), not the original feature commit. Upstream deliberately
// stopped using `frm.toggle_enable("required_items", ...)`: that disabled the
// whole grid, which also killed the Operation column and made the state
// impossible to refresh cleanly. The current form controls four things and
// nothing else:
//
//   cannot_add_rows / cannot_delete_rows  on the required_items table
//   read_only                             on item_code and required_qty
//
// Everything else stays exactly as the doctype declares it. transferred_qty,
// consumed_qty, returned_qty, rate, amount and the availability columns are
// read_only in Work Order Item itself and are never touched here, so they stay
// read-only in both states. Docstatus and permission handling are left entirely
// to Frappe: on a submitted or cancelled Work Order the grid is already locked
// by the framework, and these property changes cannot unlock it.
//
// The flag comes from the server via `__onload.allow_editing_items`, set by
// isnack.overrides.work_order.CustomWorkOrder.onload(), so the client never
// queries Manufacturing Settings itself (Work Order users generally cannot read
// it) and can never disagree with the server-side rule.

frappe.ui.form.on("Work Order", {
	refresh(frm) {
		frm.trigger("isnack_toggle_items_editable");
	},

	isnack_toggle_items_editable(frm) {
		let allow_edit = true;
		if (!frm.doc.__onload?.allow_editing_items) allow_edit = false;

		frm.set_df_property("required_items", "cannot_delete_rows", !allow_edit);
		frm.set_df_property("required_items", "cannot_add_rows", !allow_edit);

		const grid = frm.fields_dict["required_items"]?.grid;
		if (!grid) return;

		grid.update_docfield_property("item_code", "read_only", !allow_edit);
		grid.update_docfield_property("required_qty", "read_only", !allow_edit);
		grid.refresh();
	},
});
