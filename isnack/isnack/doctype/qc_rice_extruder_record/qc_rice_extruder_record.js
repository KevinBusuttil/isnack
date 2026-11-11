// Readings recorded in the earlier layout (before 2026-11) can be corrected or
// removed on a draft or an amendment, but not added to: new readings go in
// Readings and Oven / Slurry Readings (rice_readings, rice_oven_readings). This
// hides Add Row; the controller drops or refuses a row added another way (Tab
// out of the last cell, the grid's shortcuts, a paste).
frappe.ui.form.on("QC Rice Extruder Record", {
	refresh(frm) {
		for (const fieldname of ["readings", "oven_readings"]) {
			frm.set_df_property(fieldname, "cannot_add_rows", 1);
		}
	},
});
