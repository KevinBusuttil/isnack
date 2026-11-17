// The factory lines each Quality Hub tab records on (Quality Hub Settings,
// 2026-11). A tab's records offer only its lines, on the Quality Hub's dialogs
// and on their forms, and take its line when it has just one; a tab with no
// lines offers every line. The records refuse another line
// (quality_hub_settings.check_factory_line): a Link takes any line typed in full.
frappe.provide("isnack.quality_hub_lines");

Object.assign(isnack.quality_hub_lines, {
	// the record types whose line the settings restrict (TAB_FIELDS)
	DOCTYPES: [
		"QC Puffs Extruder Record",
		"QC Rice Extruder Record",
		"QC Frying Line Record",
		"QC Tasting Record",
		"QC Packaging Check",
		"QC Weight Check",
		"QC Metal Detector Log",
	],

	// each record type's lines, by doctype, as last loaded ({} before)
	lines: {},

	/** Load the lines as the settings give them now. */
	load() {
		return frappe
			.xcall("isnack.isnack.doctype.quality_hub_settings.quality_hub_settings.get_factory_lines")
			.then((lines) => {
				this.lines = lines || {};
				return this.lines;
			});
	},

	/** The lines records of ``doctypes`` (recorded together) may all be on:
	 *  those their tabs share. null when no tab is given any: every line. */
	lines_for(doctypes) {
		const given = doctypes.map((doctype) => this.lines[doctype] || []).filter((lines) => lines.length);
		if (!given.length) return null;
		return given.reduce((shared, lines) => shared.filter((line) => lines.includes(line)));
	},

	/** The Factory Line query of ``doctypes``' records: their lines, or every
	 *  line. ``df``, the field's, says so under the lines offered. */
	query(doctypes, df) {
		const lines = this.lines_for(doctypes);
		if (df) df.filter_description = lines ? __("The lines Quality Hub Settings gives this tab") : null;
		return lines ? { filters: [["Factory Line", "name", "in", lines]] } : {};
	},

	/** The line of ``doctypes``' records when there is just one. */
	only_line(doctypes) {
		const lines = this.lines_for(doctypes);
		return lines && lines.length === 1 ? lines[0] : null;
	},
});

isnack.quality_hub_lines.DOCTYPES.forEach((doctype) => {
	frappe.ui.form.on(doctype, {
		setup(frm) {
			frm.set_query("factory_line", () =>
				isnack.quality_hub_lines.query([frm.doctype], frm.fields_dict.factory_line && frm.fields_dict.factory_line.df)
			);
		},

		onload(frm) {
			// the settings as they are now; a new record takes its tab's only line
			isnack.quality_hub_lines.load().then(() => {
				const line = isnack.quality_hub_lines.only_line([frm.doctype]);
				if (line && frm.is_new() && !frm.doc.factory_line) frm.set_value("factory_line", line);
			});
		},
	});
});
