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

	// each Employee's name and status, by ID, once read (a promise)
	_operators: {},

	/** The Operator's query: the Active Employees, by ID or name. */
	query() {
		return { query: "isnack.utils.qc_operator.search_operators" };
	},

	/** An Employee's {employee, employee_name, status}, read once; {} when
	 *  there is no such Employee or it cannot be read. */
	details(employee) {
		if (!employee) return Promise.resolve({});
		if (!this._operators[employee]) {
			this._operators[employee] = frappe
				.xcall("isnack.utils.qc_operator.get_operator", { employee })
				.then((details) => details || {})
				.catch(() => {
					// asked again next time
					delete this._operators[employee];
					return {};
				});
		}
		return this._operators[employee];
	},

	/** Whether ``doc`` was made before the Operator came: no Operator, a name
	 *  typed in Operator Name (a new record only as an amendment of one). */
	made_before(doc) {
		return !doc.operator && !!doc.operator_name && (!doc.__islocal || !!doc.amended_from);
	},

	/** The record's Operator changed: Operator Name shows the Employee's name,
	 *  or, emptied, the name the record had typed on it, if any. An Employee who
	 *  is not Active, typed in full, is taken off. ``record`` reads and sets the
	 *  fields of a form or a dialog. */
	operator_changed(record) {
		const employee = record.get("operator");
		if (!employee) {
			record.set("operator_name", record.typed || "");
			return Promise.resolve();
		}
		return this.details(employee).then((details) => {
			// picked again meanwhile, or the dialog closed
			if (!record.alive() || record.get("operator") !== employee) return;
			if (details.status === "Active") {
				record.set("operator_name", details.employee_name || employee);
				return;
			}
			record.set("operator", "");
			record.set("operator_name", record.typed || "");
			frappe.show_alert({
				message: __("{0} is not an active Employee: pick the Operator from the list.", [employee]),
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
			typed: frm.__typed_operator_name || "",
		};
	},
});

isnack.quality_hub_operator.OPERATOR_DOCTYPES.forEach((doctype) => {
	frappe.ui.form.on(doctype, {
		setup(frm) {
			frm.set_query("operator", () => isnack.quality_hub_operator.query());
		},

		refresh(frm) {
			if (!frm.fields_dict.operator) return;
			const operators = isnack.quality_hub_operator;
			// the Link is checked on the server: Frappe's check needs Employee
			// permission, which quality users do not hold (and no "Create a new")
			frm.set_df_property("operator", "ignore_link_validation", 1);
			frm.set_df_property("operator", "only_select", 1);
			// a record made before the Operator keeps its typed name, and needs none
			const before = operators.made_before(frm.doc);
			frm.__typed_operator_name = before ? frm.doc.operator_name : "";
			frm.toggle_reqd("operator", !before);
		},

		operator(frm) {
			const operators = isnack.quality_hub_operator;
			operators.operator_changed(operators.form_record(frm));
		},
	});
});
