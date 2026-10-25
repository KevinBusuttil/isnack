import frappe
from frappe.model.utils.rename_field import rename_field

DOCTYPE = "QC Receiving Record"

# the checks that were tick boxes before they became blank / Yes / No
FORMER_CHECKS = ("packaging_intact", "labelling_correct", "foreign_body_check", "appearance_acceptable")


def execute():
    """Carry the QC Receiving Record tick boxes over to the Yes / No answers that replaced them.

    FSSC 22000 wants every receiving check recorded as passed or failed, and a
    tick box cannot tell a failed check from one nobody did. The checks are now
    Selects (blank / Yes / No), and "Colour Acceptable" became "Appearance
    Acceptable" under a fieldname of its own.

    The model sync has already turned the int columns into varchar ones holding
    "1" and "0". A ticked box becomes "Yes". An empty one becomes blank rather
    than "No": the old form recorded no answer there, and the record must not
    claim a failed check it never had.
    """
    if not frappe.db.table_exists(DOCTYPE):
        return

    if frappe.db.has_column(DOCTYPE, "colour_acceptable"):
        rename_field(DOCTYPE, "colour_acceptable", "appearance_acceptable")

    for fieldname in FORMER_CHECKS:
        frappe.db.sql(
            f"""
            UPDATE `tab{DOCTYPE}`
            SET `{fieldname}` = CASE WHEN `{fieldname}` = '1' THEN 'Yes' ELSE NULL END
            WHERE `{fieldname}` IN ('0', '1')
            """
        )
