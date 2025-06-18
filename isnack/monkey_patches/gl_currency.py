from frappe.utils import flt
from erpnext.accounts.report.utils import convert

def custom_convert_to_presentation_currency(gl_entries, currency_info):
    converted_gl_list = []
    presentation_currency = currency_info["presentation_currency"]
    company_currency = currency_info["company_currency"]

    account_currencies = list(set(entry["account_currency"] for entry in gl_entries))

    for entry in gl_entries:
        debit = flt(entry["debit"])
        credit = flt(entry["credit"])
        debit_in_account_currency = flt(entry["debit_in_account_currency"])
        credit_in_account_currency = flt(entry["credit_in_account_currency"])
        account_currency = entry["account_currency"]

        if len(account_currencies) == 1 and account_currency == presentation_currency:
            entry["debit"] = debit_in_account_currency
            entry["credit"] = credit_in_account_currency
        else:
            # Use each entry's posting date for conversion
            date = entry.get("posting_date") or currency_info["report_date"]
            converted_debit_value = convert(debit, presentation_currency, company_currency, date)
            converted_credit_value = convert(credit, presentation_currency, company_currency, date)

            if entry.get("debit"):
                entry["debit"] = converted_debit_value
            if entry.get("credit"):
                entry["credit"] = converted_credit_value

        converted_gl_list.append(entry)

    return converted_gl_list
