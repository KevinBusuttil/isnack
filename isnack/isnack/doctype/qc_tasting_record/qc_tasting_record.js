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
		setup(frm) {
			// a finished good's batch: the item the Work Order makes, once picked
			frm.set_query("batch_no", () => {
				const work_order = frm.doc.work_order;
				frm.fields_dict.batch_no.df.filter_description = work_order
					? __("Batches of the item Work Order {0} makes", [work_order])
					: __("Batches of finished goods");
				return {
					query: "isnack.isnack.doctype.qc_tasting_record.qc_tasting_record.finished_good_batches",
					filters: work_order ? { work_order } : {},
				};
			});
		},

		work_order(frm) {
			// a batch of another product than the Work Order makes is taken off
			// (picked before the Work Order, or kept when it changed)
			const work_order = frm.doc.work_order;
			const batch = frm.doc.batch_no;
			const lines = isnack.quality_hub_lines;
			if (!work_order || !batch || !frm.doc.item_code || !lines || !lines.work_order_details) return;
			lines.work_order_details(work_order).then((details) => {
				const made = details && details.production_item;
				// picked again meanwhile, or of the item it makes
				if (!made || frm.doc.work_order !== work_order || frm.doc.batch_no !== batch) return;
				if (!frm.doc.item_code || frm.doc.item_code === made) return;
				frm.set_value("batch_no", "");
				frappe.show_alert({
					message: __("Batch {0} is of {1}, not of {2}, which Work Order {3} makes: pick a batch of it.", [
						batch, frm.doc.item_code, made, work_order,
					]),
					indicator: "orange",
				});
			});
		},

		refresh(frm) {
			frm.fields_dict.scores.$wrapper.addClass("qc-tasting-scores");
		},
	});
})();
