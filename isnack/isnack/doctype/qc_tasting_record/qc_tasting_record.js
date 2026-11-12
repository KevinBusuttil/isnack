// A taster's Overall %, worked out as the scores are given (the record works it
// out again on save): the stars given on Shape, Colour, Smell, Taste and Texture
// over full marks. A Rating holds the fraction of stars given (4 of 5 is 0.8).
(() => {
	const CRITERIA = ["appearance_score", "colour_score", "aroma_score", "taste_score", "texture_score"];

	const set_overall_percent = (frm, cdt, cdn) => {
		const row = locals[cdt][cdn];
		const given = CRITERIA.reduce((sum, fieldname) => sum + Math.min(flt(row[fieldname]), 1), 0);
		frappe.model.set_value(cdt, cdn, "overall_percent", flt((given / CRITERIA.length) * 100, 2));
	};

	frappe.ui.form.on("QC Tasting Score", Object.fromEntries(CRITERIA.map((fieldname) => [fieldname, set_overall_percent])));

	// the five scores sit side by side in the grid, one unit each: smaller
	// stars so all five show (isnack.css, .qc-tasting-scores)
	frappe.ui.form.on("QC Tasting Record", {
		refresh(frm) {
			frm.fields_dict.scores.$wrapper.addClass("qc-tasting-scores");
		},
	});
})();
