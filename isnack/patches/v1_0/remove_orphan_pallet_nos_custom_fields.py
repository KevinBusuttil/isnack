import frappe


def execute():
    """Delete the leftover Pallet No(s) custom fields from the range-based pallet design.

    The pallet model moved from per-item-row Pallet No(s) ranges to the
    allocation manifest (custom_pallets table), and the two custom fields were
    removed from the fixtures. Fixture sync only upserts, so any site migrated
    while the old design was live still carries them as orphans — visible as a
    dead "Pallet No(s)" grid column. Safe no-op on sites that never had them.
    """
    for name in (
        "Delivery Note Item-custom_pallet_nos",
        "Packing Slip Item-custom_pallet_nos",
    ):
        frappe.delete_doc_if_exists("Custom Field", name)
