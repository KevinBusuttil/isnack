// Copyright (c) 2025, Busuttil Technologies Limited and contributors
// For license information, please see license.txt

frappe.query_reports["Document Attachments"] = {
	"filters": [
		{
			"fieldname": "from_date",
			"label": __("From Date"),
			"fieldtype": "Date",
			"width": 80,
			"reqd": 0,
			"default": frappe.datetime.get_today()
		},
		{
			"fieldname": "to_date",
			"label": __("To Date"),
			"fieldtype": "Date",
			"width": 80,
			"reqd": 0,
			"default": frappe.datetime.get_today()
		},
		{
			"fieldname": "source",
			"label": __("Source"),
			"fieldtype": "Select",
			"width": 200,
			"reqd": 0,
			"options": "\nJournal Entry\nLanded Cost Voucher\nPurchase Invoice\nService Invoice"
		}
	]
};
