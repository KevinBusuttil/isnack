// Copyright (c) 2026, Busuttil Technologies Limited and contributors
// For license information, please see license.txt

// The Metal Detector ID offers the detectors used on the log's Factory Line
// (their Factory Lines), as the Quality Hub's dialog does; a detector picked
// that is not used on a line picked afterwards is taken off. The log refuses
// one not used on its line (a Link takes any detector typed in full).
const metal_detectors_on_line = (factory_line) =>
	factory_line ? [["Metal Detector Factory Line", "factory_line", "=", factory_line]] : [];

// The Metal Detector ID, and each test's Test Time and Test Piece Type, are
// mandatory on a log made since 2026-11; a log made before (earlier_layout)
// keeps what it recorded. The doctype cannot say that per log, so the form
// marks them (the log itself refuses a log made since without them:
// QCMetalDetectorLog.require_detector_and_tests).
frappe.ui.form.on("QC Metal Detector Log", {
	refresh(frm) {
		const since = !frm.doc.earlier_layout;
		frm.toggle_reqd("metal_detector_id", since);
		const grid = frm.fields_dict.tests.grid;
		const columns = ["test_time", "test_piece_type"];
		columns.forEach((fieldname) => grid.toggle_reqd(fieldname, since));
		// the grid keeps the header it drew last, the previous log's included:
		// draw it again when its marks are not this log's
		const marked = (fieldname) => (grid.visible_columns || []).some(([df]) => df.fieldname === fieldname && df.reqd);
		if ((grid.visible_columns || []).length && columns.some((fieldname) => !!marked(fieldname) !== since)) {
			grid.reset_grid();
		}
	},

	setup(frm) {
		// no line yet: every detector, and no empty "Filters applied for" under them
		frm.set_query("metal_detector_id", () =>
			frm.doc.factory_line ? { filters: metal_detectors_on_line(frm.doc.factory_line) } : {}
		);
	},

	factory_line(frm) {
		const { metal_detector_id, factory_line } = frm.doc;
		if (!metal_detector_id || !factory_line) return;
		frappe.db
			.get_list("Metal Detector", {
				filters: [["name", "=", metal_detector_id], ...metal_detectors_on_line(factory_line)],
				limit: 1,
			})
			.then((on_line) => {
				// used on it, or the line or detector changed again meanwhile
				if (on_line.length || frm.doc.factory_line !== factory_line || frm.doc.metal_detector_id !== metal_detector_id) {
					return;
				}
				frm.set_value("metal_detector_id", "");
				frappe.show_alert({
					message: __("{0} is not used on {1}: pick a metal detector on that line.", [metal_detector_id, factory_line]),
					indicator: "orange",
				});
			});
	},
});
