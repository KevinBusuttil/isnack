// Copyright (c) 2026, Busuttil Technologies Limited and contributors
// For license information, please see license.txt

frappe.query_reports["Customs Export Traceability Report"] = {
	"filters": [
		{
			"fieldname": "company",
			"label": __("Company"),
			"fieldtype": "Link",
			"options": "Company",
			"reqd": 1,
			"default": frappe.defaults.get_default("company")
		},
		{
			"fieldname": "from_date",
			"label": __("From Date"),
			"fieldtype": "Date",
			"reqd": 1,
			"default": frappe.datetime.add_months(frappe.datetime.get_today(), -1)
		},
		{
			"fieldname": "to_date",
			"label": __("To Date"),
			"fieldtype": "Date",
			"reqd": 1,
			"default": frappe.datetime.get_today()
		},
		{
			"fieldname": "sales_invoice",
			"label": __("Sales Invoice"),
			"fieldtype": "Link",
			"options": "Sales Invoice",
			"get_query": function() {
				const company = frappe.query_report.get_filter_value("company");
				const filters = { "docstatus": 1 };
				if (company) filters["company"] = company;
				return { filters };
			}
		},
		{
			"fieldname": "customer",
			"label": __("Customer"),
			"fieldtype": "Link",
			"options": "Customer"
		},
		{
			"fieldname": "item_code",
			"label": __("Finished Good Item"),
			"fieldtype": "Link",
			"options": "Item"
		},
		{
			"fieldname": "item_group",
			"label": __("Item Group"),
			"fieldtype": "Link",
			"options": "Item Group"
		},
		{
			"fieldname": "batch_no",
			"label": __("FG Batch No"),
			"fieldtype": "Link",
			"options": "Batch"
		},
		{
			"fieldname": "work_order",
			"label": __("Work Order"),
			"fieldtype": "Link",
			"options": "Work Order"
		},
		{
			"fieldname": "raw_material_item",
			"label": __("Raw Material Item"),
			"fieldtype": "Link",
			"options": "Item"
		},
		{
			"fieldname": "purchase_receipt",
			"label": __("Purchase Receipt"),
			"fieldtype": "Link",
			"options": "Purchase Receipt"
		},
		{
			"fieldname": "customs_document_no",
			"label": __("Customs Document No"),
			"fieldtype": "Data"
		}
	],

	formatter: function(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "customs_document_no" && value) {
			value = `<span style="font-weight:bold; color:#8B0000;">${value}</span>`;
		}
		return value;
	},

	onload: function(report) {
		report.page.add_inner_button(__("Print Traceability Report"), function() {
			const filters = report.get_values();
			frappe.call({
				method: "isnack.isnack.report.customs_export_traceability_report.customs_export_traceability_report.get_print_html",
				args: { filters: filters },
				callback: function(r) {
					if (r.message) {
						const w = window.open();
						w.document.write(r.message);
						w.document.close();
						w.focus();
						setTimeout(function() { w.print(); }, 500);
					}
				}
			});
		});
	}
};
