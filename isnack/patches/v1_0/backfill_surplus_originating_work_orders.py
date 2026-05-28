import frappe


def execute():
    """Backfill the new custom_originating_work_orders child table for legacy surplus.

    Existing surplus Stock Entries only carry the single
    ``custom_originating_work_order`` link. Copy that into one
    ``Surplus Originating Work Order`` child row per surplus SE so the new
    multi-WO sweep path applies to them too. The Operator Hub sweep also has a
    defensive fallback to the single field, so this migration is best-effort and
    never blocks `migrate`.
    """
    try:
        if not frappe.db.exists("DocType", "Surplus Originating Work Order"):
            return
        if not frappe.db.has_column("Stock Entry", "custom_originating_work_order"):
            return

        rows = frappe.db.sql(
            """
            select se.name, se.custom_originating_work_order as work_order,
                   se.custom_originating_planned_start_date as planned_start_date,
                   se.to_warehouse
            from `tabStock Entry` se
            where coalesce(se.custom_is_surplus, 0) = 1
              and se.custom_originating_work_order is not null
              and se.custom_originating_work_order != ''
              and not exists (
                  select 1 from `tabSurplus Originating Work Order` sowo
                  where sowo.parent = se.name and sowo.parenttype = 'Stock Entry'
              )
            """,
            as_dict=True,
        )

        for r in rows:
            child = frappe.new_doc("Surplus Originating Work Order")
            child.parent = r.name
            child.parenttype = "Stock Entry"
            child.parentfield = "custom_originating_work_orders"
            child.work_order = r.work_order
            child.planned_start_date = r.planned_start_date
            child.staging_warehouse = r.to_warehouse
            child.idx = 1
            child.db_insert()

        frappe.db.commit()
    except Exception as exc:
        frappe.logger().warning(
            f"Could not backfill custom_originating_work_orders: {exc}"
        )
