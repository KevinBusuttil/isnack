import frappe


def execute():
    """Carry a site that already migrated the Non Returnable Item list onto Metered Item.

    The list shipped as "Non-Returnable (Metered) Items" and immediately grew a
    second job: a metered input is not only never carried back, it is never
    counted by an operator either — it is consumed straight from the BOM at Close
    Production. One list now drives both, so it is named for the property rather
    than for one of its consequences.

    The window between the two releases is short, so most sites will never have
    had the old doctype and this is a no-op. A site that did migrate keeps its
    rows: renaming the DocType moves the table, and the child rows still carry
    the old parentfield until it is rewritten here.
    """
    if frappe.db.exists("DocType", "Non Returnable Item") and not frappe.db.exists(
        "DocType", "Metered Item"
    ):
        frappe.rename_doc("DocType", "Non Returnable Item", "Metered Item", force=True)

    if not frappe.db.exists("DocType", "Metered Item"):
        # Neither name present: the field never reached this site, and the
        # doctype will be created by the normal sync.
        return

    # The rows survive the DocType rename but still point at the old fieldname,
    # so Factory Settings would load an empty list and the operator would quietly
    # lose the exclusion.
    frappe.db.sql(
        """
        UPDATE `tabMetered Item`
        SET parentfield = 'metered_items'
        WHERE parentfield = 'non_returnable_items'
        """
    )

    frappe.clear_cache(doctype="Factory Settings")
