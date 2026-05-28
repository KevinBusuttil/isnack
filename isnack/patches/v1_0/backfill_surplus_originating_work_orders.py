import frappe


def execute():
    """Backfill custom_originating_work_orders on existing surplus Stock Entries.

    Older surplus entries only recorded a single custom_originating_work_order. Copy
    that into the new comma-separated custom_originating_work_orders list so that any
    such surplus still sitting in staging can be swept into WIP when that Work Order
    starts. (We only know the one originating WO for historical entries.)
    """
    if not frappe.db.has_column("Stock Entry", "custom_originating_work_orders"):
        return

    rows = frappe.get_all(
        "Stock Entry",
        filters={
            "custom_is_surplus": 1,
            "custom_originating_work_order": ["is", "set"],
            "custom_originating_work_orders": ["in", [None, ""]],
        },
        fields=["name", "custom_originating_work_order"],
    )
    for r in rows:
        frappe.db.set_value(
            "Stock Entry",
            r.name,
            "custom_originating_work_orders",
            r.custom_originating_work_order,
            update_modified=False,
        )
