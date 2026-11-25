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

	// the Batch No's search and take-off, shared with the Quality Hub's dialog
	const tasting_lines = () => {
		const lines = globalThis.isnack && isnack.quality_hub_lines;
		return lines && lines.tasting_batch_query ? lines : null;
	};

	// the five scores sit side by side in the grid, one unit each: smaller
	// stars so all five show (isnack.css, .qc-tasting-scores)
	frappe.ui.form.on("QC Tasting Record", {
		setup(frm) {
			// a finished good's batch: of the one the Work Order makes, when it
			// makes one (isnack.quality_hub_lines, as on the Quality Hub; a desk
			// loaded before the rule came has none: the record still refuses)
			frm.set_query("batch_no", () => {
				const lines = tasting_lines();
				return lines ? lines.tasting_batch_query(frm.doc.work_order, frm.fields_dict.batch_no.df) : {};
			});
		},

		onload(frm) {
			// the finished good the Work Order makes, ready for the Batch No's search
			const lines = tasting_lines();
			if (lines && frm.doc.work_order) lines.finished_good_made(frm.doc.work_order);
		},

		work_order(frm) {
			// a batch of another product than the finished good it makes is taken off
			const lines = tasting_lines();
			if (lines) lines.tasting_work_order_changed(lines.form_record(frm));
		},

		refresh(frm) {
			frm.fields_dict.scores.$wrapper.addClass("qc-tasting-scores");
		},
	});
})();
