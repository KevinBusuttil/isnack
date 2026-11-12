// A check made since 2026-11 judges each sample: Status (mandatory) and
// Remarks. A check made before (earlier_layout) keeps its samples as they were
// (gross, tare, net weight, in range) and the Overall Status it was given. The
// doctype cannot say either per check, so the form sets the Samples grid's
// columns and marks the Status required (the check itself refuses a sample
// without one: QCWeightCheck.require_sample_status).
frappe.ui.form.on("QC Weight Check", {
	refresh(frm) {
		const grid = frm.fields_dict.samples.grid;
		const earlier = !!frm.doc.earlier_layout;
		const columns = { remarks: !earlier, status: !earlier, tare_weight: earlier, net_weight: earlier, in_range: earlier };
		for (const [fieldname, shown] of Object.entries(columns)) {
			const df = grid.fields_map[fieldname];
			if (df && !!df.in_list_view !== shown) grid.update_docfield_property(fieldname, "in_list_view", shown ? 1 : 0);
		}
		grid.toggle_reqd("status", !earlier);
		// the grid keeps the columns it drew last, the previous check's
		// included: draw them again when they are not this check's
		const drawn = new Set((grid.visible_columns || []).map(([df]) => df.fieldname));
		const status_marked = (grid.visible_columns || []).some(([df]) => df.fieldname === "status" && df.reqd);
		if (Object.entries(columns).some(([fieldname, shown]) => drawn.has(fieldname) !== shown) || status_marked === earlier) {
			grid.reset_grid();
		}
	},
});
