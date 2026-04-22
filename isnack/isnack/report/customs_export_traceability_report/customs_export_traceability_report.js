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
			"label": __("Customs Import Declaration No"),
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
		const btn = report.page.add_inner_button(__("Print Traceability Report"), function() {
			const filters = report.get_values();
			if (btn) btn.prop("disabled", true).text(__("Generating…"));
			frappe.call({
				method: "isnack.isnack.report.customs_export_traceability_report.customs_export_traceability_report.get_print_html",
				args: { filters: filters },
				callback: function(r) {
					if (btn) btn.prop("disabled", false).text(__("Print Traceability Report"));
					if (r.message) {
						const w = window.open();
						w.document.write(r.message);
						w.document.close();
						w.focus();
						setTimeout(function() { w.print(); }, 500);
					}
				},
				error: function() {
					if (btn) btn.prop("disabled", false).text(__("Print Traceability Report"));
				}
			});
		});

		const exportBtn = report.page.add_inner_button(__("Export Traceability Report"), function() {
			const filters = report.get_values();
			if (exportBtn) exportBtn.prop("disabled", true).text(__("Exporting…"));
			frappe.call({
				method: "isnack.isnack.report.customs_export_traceability_report.customs_export_traceability_report.get_export_excel",
				args: { filters: filters },
				callback: function(r) {
					if (exportBtn) exportBtn.prop("disabled", false).text(__("Export Traceability Report"));
					if (r.message) {
						const { file_content, file_name } = r.message;
						const byteChars = atob(file_content);
						const byteNumbers = new Array(byteChars.length);
						for (let i = 0; i < byteChars.length; i++) {
							byteNumbers[i] = byteChars.charCodeAt(i);
						}
						const byteArray = new Uint8Array(byteNumbers);
						const blob = new Blob([byteArray], {
							type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
						});
						const url = URL.createObjectURL(blob);
						const a = document.createElement("a");
						a.href = url;
						a.download = file_name;
						document.body.appendChild(a);
						a.click();
						document.body.removeChild(a);
						URL.revokeObjectURL(url);
					}
				},
				error: function() {
					if (exportBtn) exportBtn.prop("disabled", false).text(__("Export Traceability Report"));
				}
			});
		});
	}
};
