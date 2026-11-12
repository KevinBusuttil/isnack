// Each sample's Status is mandatory on a check made since 2026-11; a check made
// before (earlier_layout) keeps the Overall Status it was given. The doctype
// cannot say so per check, so the form marks the column (the check itself
// refuses a sample without one: QCWeightCheck.require_sample_status).
frappe.ui.form.on("QC Weight Check", {
	refresh(frm) {
		frm.fields_dict.samples.grid.toggle_reqd("status", !frm.doc.earlier_layout);
	},
});
