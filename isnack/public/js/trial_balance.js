// Extend Trial Balance report filters to add the native account currency toggle
document.addEventListener("DOMContentLoaded", function () {
	const REPORT_CHECK_INTERVAL_MS = 500;
	// Wait for the report to be available
	const interval = setInterval(function () {
		if (
			frappe.query_reports &&
			frappe.query_reports["Trial Balance"]
		) {
			clearInterval(interval);
			frappe.query_reports["Trial Balance"].filters.push({
				fieldname: "use_native_account_currency",
				label: __("Use Native Account Currency (where matched)"),
				fieldtype: "Check",
				default: 1,
				depends_on: "eval:doc.presentation_currency",
				description: __(
					"When enabled, accounts already denominated in the presentation currency show their original values instead of back-converting from company currency."
				),
			});
		}
	}, REPORT_CHECK_INTERVAL_MS);
});
