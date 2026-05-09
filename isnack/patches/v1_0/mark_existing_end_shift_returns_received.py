import frappe


def execute():
    """Backfill the new storekeeper acknowledgement flag for legacy end-shift returns."""
    try:
        if not frappe.db.exists("DocType", "Stock Entry"):
            return
        if not frappe.db.has_column("Stock Entry", "custom_return_received_by_storekeeper"):
            return

        frappe.db.sql(
            """
            update `tabStock Entry`
            set custom_return_received_by_storekeeper = 1
            where docstatus = 1
              and coalesce(custom_is_end_shift_return, 0) = 1
              and coalesce(custom_return_received_by_storekeeper, 0) = 0
            """
        )
        frappe.db.commit()
    except Exception as exc:
        frappe.logger().warning(
            f"Could not backfill custom_return_received_by_storekeeper: {exc}"
        )
