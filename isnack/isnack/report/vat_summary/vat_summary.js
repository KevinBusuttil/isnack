// Copyright (c) 2025, Busuttil Technologies Limited and contributors
// For license information, please see license.txt

frappe.query_reports["VAT Summary"] = {
	"filters": [
		{
			"fieldname": "company",
			"label": __("Company"),
			"fieldtype": "Link",
			"width": "80",
			"options": "Company",
			"default": frappe.defaults.get_default("company")
		},
		{
			"fieldname": "vat_code",
			"label": __("VAT Code"),
			"fieldtype": "Link",
			"options": "Item Tax Template",
			"width": 200,
			"reqd": 0
		},
		{
			"fieldname": "from",
			"label": __("From Date"),
			"fieldtype": "Date",
			"width": 80,
			"reqd": 0,
			"default": frappe.datetime.get_today()
		},
		{
			"fieldname": "to",
			"label": __("To Date"),
			"fieldtype": "Date",
			"width": 80,
			"reqd": 0,
			"default": frappe.datetime.get_today()
		}
	]
};
