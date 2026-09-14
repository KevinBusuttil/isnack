"""Find Work Orders left with the exploded-BOM flag the hubs cannot handle.

A finished-good Work Order whose BOM carries sub-assembly rows must consume
those sub-assemblies, not their raw materials. ERPNext only clears
``use_multi_level_bom`` when the Production Plan carries sub-assembly rows, so
a plan where the planner skipped "Get Sub Assembly Items" yields an order the
Operator Hub can neither end (without a Production Manager override) nor close.

``apply_line_warehouses_to_work_order`` now prevents new ones. This reports any
that already exist: drafts are corrected in place, and submitted orders are
listed in the Error Log because rebuilding a submitted order's required items
is a decision for a Production Manager, not a migration.

Idempotent: a corrected order no longer matches, and reporting writes nothing
to the orders themselves.
"""

import frappe


def execute():
    if not frappe.db.exists("DocType", "Work Order"):
        return

    stuck = frappe.db.sql(
        """
        SELECT wo.name, wo.docstatus, wo.status, wo.production_item, wo.bom_no
        FROM `tabWork Order` wo
        WHERE wo.use_multi_level_bom = 1
          AND wo.docstatus < 2
          AND EXISTS (
              SELECT 1 FROM `tabBOM Item` bi
              WHERE bi.parent = wo.bom_no AND bi.bom_no IS NOT NULL AND bi.bom_no != ''
          )
        """,
        as_dict=True,
    )
    if not stuck:
        return

    fixed, needs_attention = [], []
    for row in stuck:
        if row.docstatus != 0:
            needs_attention.append(row)
            continue
        try:
            doc = frappe.get_doc("Work Order", row.name)
            doc.use_multi_level_bom = 0
            doc.set_required_items()
            doc.flags.ignore_permissions = True
            doc.save()
            fixed.append(row.name)
        except Exception:
            frappe.log_error(frappe.get_traceback(), f"Could not correct Work Order {row.name}")
            needs_attention.append(row)

    if fixed:
        print(f"Corrected {len(fixed)} draft Work Order(s): {', '.join(fixed)}")

    if needs_attention:
        detail = "\n".join(
            f"{r.name}  {r.production_item}  {r.bom_no}  docstatus={r.docstatus}  {r.status}"
            for r in needs_attention
        )
        message = (
            "These submitted Work Orders carry use_multi_level_bom = 1 on a BOM that has "
            "sub-assembly rows, so their required items are raw materials instead of the "
            "semi-finished goods. The Operator Hub cannot close them. A Production Manager "
            "should cancel and re-create each one from a plan built with "
            '"Get Sub Assembly Items".\n\n' + detail
        )
        frappe.log_error(message, "Work Orders with an exploded BOM the hubs cannot close")
        print(message)
