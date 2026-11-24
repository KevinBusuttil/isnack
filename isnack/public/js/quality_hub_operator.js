// The Operator of a QC record (2026-11): an Employee, picked as the Operator
// Hub's Set Operator picks one, by ID or name, among the Employees who are
// Active. Unlike the Operator Hub, it is not locked to the logged-in user: the
// QC inspector names the operator whose work was checked. Operator Name shows
// the Employee's name; the server sets it on save (isnack/utils/qc_operator.py).
// A record made before the Operator came keeps the name typed on it.
//
// Quality users hold no permission on Employee: the Operator's search and its
// name come from isnack.utils.qc_operator, and the Link is not checked here
// (Frappe's check needs Employee permission) but on the server, on save.
frappe.provide("isnack.quality_hub_operator");

Object.assign(isnack.quality_hub_operator, {
	// the record types that name an Employee as their Operator (OPERATOR_DOCTYPES)
	OPERATOR_DOCTYPES: [
		"QC Receiving Record",
		"QC Puffs Extruder Record",
		"QC Rice Extruder Record",
		"QC Frying Line Record",
		"QC Tasting Record",
		"QC Packaging Check",
		"QC Weight Check",
		"QC Metal Detector Log",
	],

	// each Active Employee's name and status, by ID, once read (a promise)
	_operators: {},

	/** The Operator's query: the Active Employees, by ID or name. */
	query() {
		return { query: "isnack.utils.qc_operator.search_operators" };
	},

	/** The Operator's lookup on ``doctype``'s field itself, from which Frappe
	 *  copies each document's, and the list's and Report View's filters: the
	 *  search above, no "Create a new", and no check here (Frappe's needs
	 *  Employee permission; the server checks the link on save). Set before a
	 *  document's copy is made: Frappe checks a link a new record comes with
	 *  (from a list's filter or the address) before its form's refresh. */
	prepare(doctype) {
		const df = frappe.meta.get_docfield(doctype, "operator");
		if (!df) return;
		Object.assign(df, { ignore_link_validation: 1, only_select: 1, get_query: () => this.query() });
	},

	/** An Employee's {employee, employee_name, status}: {} when there is no
	 *  such Employee, null when it cannot be known now (the request failed, or
	 *  the desk is offline, where Frappe never answers). Only an Active
	 *  Employee's is kept: HR may set the others back to Active. */
	details(employee) {
		if (!employee) return Promise.resolve({});
		if (!this._operators[employee]) {
			if (typeof navigator !== "undefined" && navigator.onLine === false) return Promise.resolve(null);
			this._operators[employee] = frappe
				.xcall("isnack.utils.qc_operator.get_operator", { employee })
				.then((details) => {
					if (!details || details.status !== "Active") delete this._operators[employee];
					return details || {};
				})
				.catch(() => {
					// asked again next time
					delete this._operators[employee];
					return null;
				});
		}
		return this._operators[employee];
	},

	/** Whether ``doc`` was made before the Operator came: no Operator, a name
	 *  typed in Operator Name (a new record only as an amendment of one). */
	made_before(doc) {
		return !doc.operator && !!doc.operator_name && (!doc.__islocal || !!doc.amended_from);
	},

	/** The name typed on ``frm``'s document, if it was made before the
	 *  Operator: decided on the document as loaded or saved, not as edited
	 *  since (an Employee picked and not saved leaves it as it was). */
	typed_name(frm) {
		const typed = (frm.__operator_typed = frm.__operator_typed || {});
		if (!frm.is_dirty() || !(frm.doc.name in typed)) {
			typed[frm.doc.name] = this.made_before(frm.doc) ? frm.doc.operator_name : "";
		}
		return typed[frm.doc.name];
	},

	/** The record's Operator changed: Operator Name shows the Employee's name,
	 *  or, emptied, the name the record had typed on it, if any. An Employee who
	 *  is not Active, typed in full, is taken off; one that cannot be looked up
	 *  now is left as picked, for the server to check on save. ``record`` reads
	 *  and sets the fields of a form or a dialog. */
	operator_changed(record) {
		const employee = record.get("operator");
		if (!employee) {
			record.set("operator_name", record.typed || "");
			return Promise.resolve();
		}
		// no name but its own: not the one shown for the Operator picked before
		if (record.get("operator_name")) record.set("operator_name", "");
		return this.details(employee).then((details) => {
			// picked again meanwhile, or the dialog closed
			if (!record.alive() || record.get("operator") !== employee) return;
			if (!details) return;
			if (details.status === "Active") {
				record.set("operator_name", details.employee_name || employee);
				return;
			}
			record.set("operator", "");
			record.set("operator_name", record.typed || "");
			frappe.show_alert({
				// (the value comes from the box or the address: shown as text)
				message: __("{0} is not an active Employee: pick the Operator from the list.", [
					frappe.utils.escape_html(employee),
				]),
				indicator: "orange",
			});
		});
	},

	/** A form's record, for operator_changed: the document open when the change
	 *  was made, and the name typed on it if it was made before the Operator. */
	form_record(frm) {
		const doc = frm.doc;
		return {
			get: (fieldname) => frm.doc[fieldname],
			set: (fieldname, value) => frm.set_value(fieldname, value),
			alive: () => frm.doc === doc,
			typed: this.typed_name(frm),
		};
	},

	/** Hide the Operator's open-link arrow from a user who may not read
	 *  Employee: it opens a page they are refused. */
	hide_open_link(field) {
		if (field && field.$link_open && !frappe.model.can_read("Employee")) field.$link_open.addClass("hide");
	},
});

frappe.provide("frappe.listview_settings");

isnack.quality_hub_operator.OPERATOR_DOCTYPES.forEach((doctype) => {
	// the list's and Report View's filters on Operator: the same lookup (none of
	// these record types has listview settings of its own)
	const settings = (frappe.listview_settings[doctype] = frappe.listview_settings[doctype] || {});
	const onload = settings.onload;
	settings.onload = function (...args) {
		isnack.quality_hub_operator.prepare(doctype);
		return onload ? onload.apply(this, args) : undefined;
	};

	frappe.ui.form.on(doctype, {
		setup(frm) {
			isnack.quality_hub_operator.prepare(frm.doctype);
			frm.set_query("operator", () => isnack.quality_hub_operator.query());
		},

		before_load(frm) {
			// markup in the value a new record comes with (from the address) is no
			// Employee ID: taken off before anything shows it, as Frappe shows a
			// Link to a doctype the user may not read as it stands, markup and all
			const value = frm.doc.operator;
			if (frm.is_new() && value && /[<>"']/.test(value)) {
				frm.doc.operator = "";
				frappe.show_alert({
					message: __("{0} is not an active Employee: pick the Operator from the list.", [
						frappe.utils.escape_html(value),
					]),
					indicator: "orange",
				});
			}
			// the document's own copy of the field, which Frappe may make before
			// the form's setup: no check here before Frappe checks a link a new
			// record comes with (from a list's filter or the address), which it
			// does once this handler is done, before refresh
			frm.set_df_property("operator", "ignore_link_validation", 1);
			frm.set_df_property("operator", "only_select", 1);
		},

		refresh(frm) {
			if (!frm.fields_dict.operator) return;
			const operators = isnack.quality_hub_operator;
			// as on the doctype's field (prepare), for a document copied before it
			frm.set_df_property("operator", "ignore_link_validation", 1);
			frm.set_df_property("operator", "only_select", 1);
			operators.hide_open_link(frm.fields_dict.operator);
			// a record made before the Operator keeps its typed name, and needs none
			frm.toggle_reqd("operator", !operators.typed_name(frm));
			// a new record with an Operator and no name (a duplicate, or one opened
			// from a list's filter): its name, or taken off if not Active
			if (frm.is_new() && frm.doc.operator && !frm.doc.operator_name) {
				operators.operator_changed(operators.form_record(frm));
			}
		},

		operator(frm) {
			const operators = isnack.quality_hub_operator;
			operators.operator_changed(operators.form_record(frm));
		},
	});
});
