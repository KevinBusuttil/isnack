// Copyright (c) 2026, Busuttil Technologies Limited and contributors
// For license information, please see license.txt

// The Metal Detector ID offers the detectors used on the log's Factory Line
// (their Factory Lines), as the Quality Hub's dialog does; a detector picked
// that is not used on a line picked afterwards is taken off. The log refuses
// one not used on its line (a Link takes any detector typed in full).
const metal_detectors_on_line = (factory_line) =>
	factory_line ? [["Metal Detector Factory Line", "factory_line", "=", factory_line]] : [];

frappe.ui.form.on("QC Metal Detector Log", {
	setup(frm) {
		frm.set_query("metal_detector_id", () => ({ filters: metal_detectors_on_line(frm.doc.factory_line) }));
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
