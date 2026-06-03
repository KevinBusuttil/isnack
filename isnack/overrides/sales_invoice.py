from frappe.utils import flt


# Currency fields on Sales Invoice Item that ERPNext's calculate_item_values
# (erpnext/controllers/taxes_and_totals.py) writes via raw subtraction without
# flt(..., precision) — e.g. `item.discount_amount = price_list_rate - rate`.
# On submitted-doc updates, Frappe's _validate_update_after_submit compares
# old vs new with raw `!=`, so the sub-cent FP drift from those subtractions
# trips "Not allowed to change ... after submission" even when the value is
# unchanged at currency precision. Re-quantising after ERPNext's validate
# snaps each field back to its precision so the diff check passes.
_ITEM_FIELDS_TO_QUANTISE = (
    "discount_amount",
    "base_discount_amount",
    "rate",
    "base_rate",
)


def quantise_item_currency_fields(doc, method=None):
    for item in doc.get("items") or []:
        for fieldname in _ITEM_FIELDS_TO_QUANTISE:
            value = item.get(fieldname)
            if value is None:
                continue
            item.set(fieldname, flt(value, item.precision(fieldname)))
