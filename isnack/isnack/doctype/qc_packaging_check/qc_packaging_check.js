// A check made since 2026-11 passes only when its four checks are all ticked:
// its Overall Status follows the ticks as they are given (the check works it
// out again on save: checks_result in qc_packaging_check.py). A check made
// before (earlier_layout) keeps its variance result and has no Overall Status.
(() => {
	const CHECKS = ["print_quality_ok", "seal_integrity_ok", "label_correct", "artwork_matches"];

	const set_overall_status = (frm) => {
		if (frm.doc.docstatus !== 0 || frm.doc.earlier_layout) return;
		const status = CHECKS.every((fieldname) => cint(frm.doc[fieldname])) ? "Pass" : "Fail";
		if (frm.doc.overall_status !== status) frm.set_value("overall_status", status);
	};

	frappe.ui.form.on("QC Packaging Check", {
		refresh(frm) {
			// a new check (or a Duplicate, which leaves it out) shows it at once
			if (frm.is_new()) set_overall_status(frm);
		},
		...Object.fromEntries(CHECKS.map((fieldname) => [fieldname, set_overall_status])),
	});
})();
