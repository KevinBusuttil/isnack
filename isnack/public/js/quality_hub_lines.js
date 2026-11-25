// The factory lines each Quality Hub tab records on (Quality Hub Settings,
// 2026-11). A tab's records offer only its lines, on the Quality Hub's dialogs
// and on their forms, and take its line when it has just one; a tab with no
// lines offers every line. The records refuse another line
// (quality_hub_settings.check_factory_line): a Link takes any line typed in full.
//
// A record's Work Order is one of its Factory Line's, whatever the tab
// (2026-11): the Work Order's own line (its Factory Section) is the record's. A
// Process record's Product Item is the item its Work Order makes, filled in
// when the Work Order is picked; without a Work Order it offers Finished Goods
// items. A Tasting record's Batch No is a batch of the finished good its Work
// Order makes, or of any finished good when it makes none: a batch of another
// is taken off when the Work Order is picked.
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

	// each Work Order's line and item, by name, once read
	work_orders: {},

	// each Work Order's reading, by name (a promise)
	_details: {},

	// the finished good each Work Order makes ("" for none), by name, once read
	finished_goods_made: {},

	// each Work Order's finished good reading, by name (a promise)
	_made: {},

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

	/** The same factory line, case and surrounding spaces aside (as the
	 *  database matches a link). */
	same_line(one, other) {
		return String(one || "").trim().toLowerCase() === String(other || "").trim().toLowerCase();
	},

	/** The Work Order query of a record on ``line``: the Work Orders on that
	 *  line, none cancelled, or every Work Order before a line is picked.
	 *  ``df``, the field's, says so under them. */
	work_order_query(line, df) {
		if (df) df.filter_description = line ? __("Work Orders on {0}", [line]) : null;
		if (!line) return {};
		return {
			filters: [
				["Work Order", "custom_factory_line", "=", line],
				["Work Order", "docstatus", "<", 2],
			],
		};
	},

	/** The Product Item query of a record on ``work_order``: the item it makes,
	 *  once read (reading it now for the next search), or Finished Goods items
	 *  without a Work Order. ``df``, the field's, says so under them. */
	product_query(work_order, df) {
		const known = work_order ? this.work_orders[work_order] : null;
		if (work_order && !known) this.work_order_details(work_order);
		const item = known && known.production_item;
		if (df) df.filter_description = item ? __("The item Work Order {0} makes", [work_order]) : __("Finished Goods items");
		return { filters: item ? [["Item", "name", "=", item]] : [["Item", "item_group", "=", "Finished Goods"]] };
	},

	/** A Work Order's line and the item it makes, read once: {factory_line,
	 *  production_item}, or {} when it cannot be read. */
	work_order_details(work_order) {
		if (!work_order) return Promise.resolve({});
		if (!this._details[work_order]) {
			this._details[work_order] = frappe
				.xcall("isnack.isnack.doctype.quality_hub_settings.quality_hub_settings.get_work_order_details", { work_order })
				.then((details) => {
					this.work_orders[work_order] = details || {};
					return this.work_orders[work_order];
				})
				.catch(() => {
					// asked again next time
					delete this._details[work_order];
					return {};
				});
		}
		return this._details[work_order];
	},

	/** The finished good ``work_order`` makes, read once: its item, or "" when
	 *  it makes another item or cannot be read (finished_good_made). */
	finished_good_made(work_order) {
		if (!work_order) return Promise.resolve("");
		if (!this._made[work_order]) {
			this._made[work_order] = frappe
				.xcall("isnack.isnack.doctype.qc_tasting_record.qc_tasting_record.finished_good_made", { work_order })
				.then((item) => {
					this.finished_goods_made[work_order] = item || "";
					return this.finished_goods_made[work_order];
				})
				.catch(() => {
					// asked again next time
					delete this._made[work_order];
					return "";
				});
		}
		return this._made[work_order];
	},

	/** A Tasting record's Batch No query on ``work_order``: the batches of
	 *  finished goods, of the one it makes when it makes one (the query, on the
	 *  server, narrows them). ``df``, the field's, says so under them once that
	 *  is read (reading it now for the next search). */
	tasting_batch_query(work_order, df) {
		const made = work_order ? this.finished_goods_made[work_order] : "";
		if (work_order && made === undefined) this.finished_good_made(work_order);
		if (df) {
			df.filter_description = made
				? __("Batches of the item Work Order {0} makes", [work_order])
				: __("Batches of finished goods");
		}
		return {
			query: "isnack.isnack.doctype.qc_tasting_record.qc_tasting_record.finished_good_batches",
			filters: work_order ? { work_order } : {},
		};
	},

	/** A Tasting record's Work Order changed: a batch of another product than
	 *  the finished good it makes (picked before the Work Order, or kept when it
	 *  changed) is taken off. ``record`` as for work_order_changed. */
	tasting_work_order_changed(record) {
		const work_order = record.get("work_order");
		const batch = record.get("batch_no");
		// (read without a batch too: the Batch No's search names it)
		if (!work_order) return Promise.resolve();
		return this.finished_good_made(work_order).then((made) => {
			// no batch, or the Work Order or the batch picked again meanwhile
			if (!batch || !record.alive() || record.get("work_order") !== work_order || record.get("batch_no") !== batch) return;
			const item = record.get("item_code");
			// it makes none, or a batch of the one it makes
			if (!made || !item || item === made) return;
			record.set("batch_no", "");
			if (record.has("item_code")) record.set("item_code", "");
			frappe.show_alert({
				message: __("Batch {0} is of {1}, not of {2}, which Work Order {3} makes: pick a batch of it.", [
					batch, item, made, work_order,
				]),
				indicator: "orange",
			});
		});
	},

	/** Whether ``work_order`` is not on ``line``: false when either is missing
	 *  or the Work Order cannot be read. */
	off_line(work_order, line) {
		if (!work_order || !line) return Promise.resolve(false);
		return this.work_order_details(work_order).then((details) => {
			if (!details || !("factory_line" in details)) return false;
			return !this.same_line(details.factory_line, line);
		});
	},

	/** The record's line changed: a Work Order on another line is taken off.
	 *  ``record`` reads and sets the fields of a form or a dialog. */
	line_changed(record) {
		const work_order = record.get("work_order");
		const line = record.get("factory_line");
		if (!work_order || !line) return Promise.resolve();
		return this.off_line(work_order, line).then((off) => {
			// offered, or the line or Work Order changed again meanwhile
			if (!off || !record.alive() || record.get("work_order") !== work_order || record.get("factory_line") !== line) return;
			this.take_off(record, work_order, line);
		});
	},

	/** The record's Work Order changed: one on another line (typed in full) is
	 *  taken off; another fills in the Product Item, where the record has one,
	 *  with the item it makes. */
	work_order_changed(record) {
		const work_order = record.get("work_order");
		const line = record.get("factory_line");
		if (!work_order) return Promise.resolve();
		return Promise.all([this.off_line(work_order, line), this.work_order_details(work_order)]).then(([off, details]) => {
			// picked again meanwhile
			if (!record.alive() || record.get("work_order") !== work_order) return;
			if (off) {
				// the line changed meanwhile: its own change decides
				if (record.get("factory_line") === line) this.take_off(record, work_order, line);
				return;
			}
			const item = details && details.production_item;
			if (item && record.has("product_item") && record.get("product_item") !== item) record.set("product_item", item);
		});
	},

	take_off(record, work_order, line) {
		record.set("work_order", "");
		frappe.show_alert({
			message: __("{0} is not on {1}: pick a Work Order on that line.", [work_order, line]),
			indicator: "orange",
		});
	},

	/** A form's record, for line_changed and work_order_changed: the document
	 *  open when the change was made (a form shows one document at a time). */
	form_record(frm) {
		const doc = frm.doc;
		return {
			get: (fieldname) => frm.doc[fieldname],
			set: (fieldname, value) => frm.set_value(fieldname, value),
			has: (fieldname) => !!frm.fields_dict[fieldname],
			alive: () => frm.doc === doc,
		};
	},
});

isnack.quality_hub_lines.DOCTYPES.forEach((doctype) => {
	frappe.ui.form.on(doctype, {
		setup(frm) {
			const lines = isnack.quality_hub_lines;
			const df = (fieldname) => frm.fields_dict[fieldname] && frm.fields_dict[fieldname].df;
			frm.set_query("factory_line", () => lines.query([frm.doctype], df("factory_line")));
			frm.set_query("work_order", () => lines.work_order_query(frm.doc.factory_line, df("work_order")));
			if (frm.fields_dict.product_item) {
				frm.set_query("product_item", () => lines.product_query(frm.doc.work_order, df("product_item")));
			}
		},

		onload(frm) {
			// the settings as they are now; a new record takes its tab's only line
			isnack.quality_hub_lines.load().then(() => {
				const line = isnack.quality_hub_lines.only_line([frm.doctype]);
				if (line && frm.is_new() && !frm.doc.factory_line) frm.set_value("factory_line", line);
			});
			// the item the Work Order makes, ready for the Product Item's search
			if (frm.fields_dict.product_item && frm.doc.work_order) {
				isnack.quality_hub_lines.work_order_details(frm.doc.work_order);
			}
		},

		factory_line(frm) {
			isnack.quality_hub_lines.line_changed(isnack.quality_hub_lines.form_record(frm));
		},

		work_order(frm) {
			isnack.quality_hub_lines.work_order_changed(isnack.quality_hub_lines.form_record(frm));
		},
	});
});
