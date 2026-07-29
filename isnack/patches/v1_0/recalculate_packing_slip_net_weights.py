import frappe


def execute():
    """Apply the packaging Net Weight exclusion to Packing Slips saved before it.

    Weights are stored on the document, and ERPNext will not validate a Packing
    Slip whose Delivery Note has left Draft, so existing slips cannot pick the
    rule up by being re-saved or amended.

    No-ops when no Item Groups are listed under General Settings → Packing,
    which is the case on a site that migrates before configuring them. Re-run it
    by hand once they are set, or after changing them::

        bench --site <site> execute \\
            isnack.overrides.packing_slip.recalculate_stored_weights
    """
    try:
        from isnack.overrides.packing_slip import recalculate_stored_weights

        changed = recalculate_stored_weights()
        if changed:
            frappe.logger().info(
                f"Recalculated Net Weight on {len(changed)} Packing Slip(s)"
            )
    except Exception as exc:
        frappe.logger().warning(
            f"Could not recalculate Packing Slip Net Weights: {exc}"
        )
