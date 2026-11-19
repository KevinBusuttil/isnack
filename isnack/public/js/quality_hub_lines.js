// The factory lines each Quality Hub tab records on (Quality Hub Settings,
// 2026-11). A tab's records offer only its lines, on the Quality Hub's dialogs
// and on their forms, and take its line when it has just one; a tab with no
// lines offers every line. The records refuse another line
// (quality_hub_settings.check_factory_line): a Link takes any line typed in full.
//
// A record's Work Order is one of its Factory Line's (2026-11): a Work Order is
// planned on the line that makes its product, so a record on a packing line
// offers the Work Orders of the production lines it packs for (the settings'
// Packing Lines) as well as its own. A Process record's Product Item is the
// item its Work Order makes, filled in when the Work Order is picked; without a
// Work Order it offers Finished Goods items.
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

	// the production lines each packing line packs for, as last loaded ({} before)
	packs_for: {},

	// each Work Order's line and item, by name, once read
	work_orders: {},

	// each Work Order's reading, by name (a promise)
	_details: {},

	/** Load the lines as the settings give them now. */
	load() {
		this._loading = Promise.all([
			frappe.xcall("isnack.isnack.doctype.quality_hub_settings.quality_hub_settings.get_factory_lines"),
			frappe.xcall("isnack.isnack.doctype.quality_hub_settings.quality_hub_settings.get_packing_lines"),
		]).then(([lines, packs_for]) => {
			this.lines = lines || {};
			this.packs_for = packs_for || {};
			return this.lines;
		});
		return this._loading;
	},

	/** The settings as last loaded, once they are (loading them if no one has). */
	ready() {
		return this._loading || this.load();
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

	/** The lines whose Work Orders a record on ``line`` offers: its own and,
	 *  on a packing line, those of the production lines it packs for. null
	 *  before a line is picked: every Work Order. */
	work_order_lines(line) {
		if (!line) return null;
		const lines = [line];
		Object.keys(this.packs_for)
			.filter((packing_line) => this.same_line(packing_line, line))
			.forEach((packing_line) => {
				(this.packs_for[packing_line] || []).forEach((production_line) => {
					if (!lines.some((other) => this.same_line(other, production_line))) lines.push(production_line);
				});
			});
		return lines;
	},

	/** The Work Order query of a record on ``line``: the Work Orders of its
	 *  lines, none cancelled, or every Work Order before a line is picked.
	 *  ``df``, the field's, says so under them. */
	work_order_query(line, df) {
		const lines = this.work_order_lines(line);
		if (df) df.filter_description = lines ? __("Work Orders for {0}", [line]) : null;
		if (!lines) return {};
		return {
			filters: [
				["Work Order", "custom_factory_line", "in", lines],
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

	/** Whether a record on ``line`` does not offer ``work_order``: false when
	 *  either is missing or the Work Order cannot be read. */
	off_line(work_order, line) {
		if (!work_order || !line) return Promise.resolve(false);
		return Promise.all([this.ready(), this.work_order_details(work_order)]).then(([, details]) => {
			if (!details || !("factory_line" in details)) return false;
			return !this.work_order_lines(line).some((other) => this.same_line(other, details.factory_line));
		});
	},

	/** The record's line changed: a Work Order it does not offer is taken off.
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

	/** The record's Work Order changed: one its line does not offer (typed in
	 *  full) is taken off; another fills in the Product Item, where the record
	 *  has one, with the item it makes. */
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
			message: __("{0} is not a Work Order for {1}: pick one from the list.", [work_order, line]),
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
