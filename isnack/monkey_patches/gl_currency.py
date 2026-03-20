import frappe
from frappe.utils import flt
from erpnext.accounts.report.utils import convert


def custom_convert_to_presentation_currency(gl_entries, currency_info, filters=None):
	converted_gl_list = []
	presentation_currency = currency_info["presentation_currency"]
	company_currency = currency_info["company_currency"]

	exchange_gain_or_loss = False

	if filters and isinstance(filters.get("account"), list):
		account_filter = filters.get("account")
		gain_loss_account = frappe.db.get_value("Company", filters.company, "exchange_gain_loss_account")
		exchange_gain_or_loss = len(account_filter) == 1 and account_filter[0] == gain_loss_account

	# New flag: when True, use native account currency values for matching accounts
	# When False, always back-convert from company currency (standard ERPNext behaviour)
	use_native = True
	if filters:
		# Default to True if not explicitly set
		use_native = filters.get("use_native_account_currency", True)

	for entry in gl_entries:
		debit = flt(entry["debit"])
		credit = flt(entry["credit"])
		debit_in_account_currency = flt(entry["debit_in_account_currency"])
		credit_in_account_currency = flt(entry["credit_in_account_currency"])
		account_currency = entry["account_currency"]

		if (
			use_native
			and account_currency == presentation_currency
			and not exchange_gain_or_loss
		) and not (filters and filters.get("show_amount_in_company_currency")):
			# Option A fix: per-entry check instead of batch-level check
			# Use the native account currency values directly - no conversion needed
			entry["debit"] = debit_in_account_currency
			entry["credit"] = credit_in_account_currency
		else:
			# Convert from company currency using per-entry posting date
			date = entry.get("posting_date") or currency_info["report_date"]
			converted_debit_value = convert(debit, presentation_currency, company_currency, date)
			converted_credit_value = convert(credit, presentation_currency, company_currency, date)

			if entry.get("debit"):
				entry["debit"] = converted_debit_value

			if entry.get("credit"):
				entry["credit"] = converted_credit_value

		converted_gl_list.append(entry)

	return converted_gl_list