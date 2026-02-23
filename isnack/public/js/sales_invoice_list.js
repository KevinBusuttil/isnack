const original_onload = (frappe.listview_settings["Sales Invoice"] || {}).onload;
frappe.listview_settings["Sales Invoice"] = frappe.listview_settings["Sales Invoice"] || {};
frappe.listview_settings["Sales Invoice"].onload = function(listview) {
	if (original_onload) {
		original_onload(listview);
	}
	listview.page.add_action_item(__("Multi-Print"), function() {
		const checked = listview.get_checked_items();
		if (!checked.length) {
			frappe.msgprint(__("Please select at least one invoice to print."));
			return;
		}

		const print_format =
			(frappe.get_meta("Sales Invoice") || {}).default_print_format || "Standard";
		const letterhead = frappe.defaults.get_default("letter_head") || "";

		const promises = checked.map(function(invoice) {
			return new Promise(function(resolve, reject) {
				frappe.call({
					method: "frappe.www.printview.get_html_and_style",
					args: {
						doc: "Sales Invoice",
						name: invoice.name,
						print_format: print_format,
						letterhead: letterhead,
					},
					callback: function(r) {
						if (r.message) {
							resolve({ name: invoice.name, result: r.message });
						} else {
							reject(new Error("No response for " + invoice.name));
						}
					},
				});
			});
		});

		Promise.all(promises).then(function(results) {
			let combined_html = "";
			let combined_style = "";

			results.forEach(function(item) {
				const html = item.result.html || "";
				const style = item.result.style || "";
				if (style && !combined_style.includes(style)) {
					combined_style += style;
				}

				combined_html +=
					'<div style="text-align:right;font-weight:bold;margin-bottom:4px;">' +
					__("ORIGINAL") +
					"</div>" +
					html +
					'<div class="page-break"></div>' +
					'<div style="text-align:right;font-weight:bold;margin-bottom:4px;">' +
					__("DUPLICATE") +
					"</div>" +
					html +
					'<div class="page-break"></div>';
			});

			const print_window = window.open("", "_blank");
			if (!print_window) {
				frappe.msgprint(__("Please allow popups for this site and try again."));
				return;
			}
			print_window.document.write(
				"<!DOCTYPE html><html><head><meta charset='utf-8'>" +
					"<style>" +
					"@media print { .page-break { page-break-after: always; } }" +
					"body { margin: 0; padding: 0; }" +
					combined_style +
					"</style></head>" +
					'<body onload="window.print()">' +
					combined_html +
					"</body></html>"
			);
			print_window.document.close();
		}).catch(function(err) {
			frappe.msgprint(__("Failed to fetch invoice data: ") + (err.message || err));
		});
	});
};
