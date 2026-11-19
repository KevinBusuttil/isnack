import frappe


def execute():
    """Quality Hub Settings: the Packing Lines table came off (2026-11).

    For a few hours main gave Quality Hub Settings a Packing Lines table (child
    doctype Quality Hub Packing Line) naming the production lines each packing
    line packs for, whose Work Orders a record on the packing line offered. A
    record's Work Order now offers the Work Orders of its Factory Line alone,
    whatever the tab. A site migrated in between keeps the doctype with no
    files behind it: delete it, as ERPNext deletes the doctypes it drops. A site
    that never had it has nothing to delete.
    """
    frappe.delete_doc("DocType", "Quality Hub Packing Line", ignore_missing=True)
