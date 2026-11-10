// Readings recorded in the earlier layout (before 2026-11) can be corrected or
// removed on a draft or an amendment, but not added to: new readings go in
// Readings and Oven Readings (puffs_readings, puffs_oven_readings).
frappe.ui.form.on("QC Puffs Extruder Record", {
	refresh(frm) {
		for (const fieldname of ["readings", "oven_readings"]) {
			frm.set_df_property(fieldname, "cannot_add_rows", 1);
		}
	},
});
