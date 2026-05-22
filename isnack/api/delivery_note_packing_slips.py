"""Automatic Packing Slip creation from a Delivery Note.

Workflow (ERPNext v15):

    Draft Delivery Note -> user clicks Submit
        -> Delivery Note `before_submit` runs (this module)
            -> one submitted Packing Slip is created per Sales Order group
        -> Delivery Note `db_update` / `update_children`
        -> Delivery Note `on_submit` -> standard `validate_packed_qty` passes

This deliberately runs in `before_submit`, while the Delivery Note is still
`docstatus = 0`, because ERPNext only allows a Packing Slip to be created for a
Draft Delivery Note (`PackingSlip.validate_delivery_note`).

Why we also write `packed_qty` on the in-memory Delivery Note rows:
`before_submit` runs *before* Frappe persists the child tables. Submitting a
Packing Slip updates `Delivery Note Item.packed_qty` directly in the database
(via the Packing Slip `status_updater`), but the in-memory rows are still
stale; `update_children()` would then overwrite the database value back to 0.
So after each Packing Slip is submitted we mirror the packed quantity onto the
in-memory rows, which also lets the standard `validate_packed_qty` check in
`Delivery Note.on_submit` pass correctly.

This module is intentionally specific to Delivery Note -> Packing Slip
automation. Do not refactor it into a generic packing utility.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime

# Deterministic group key for Delivery Note rows that have no Sales Order.
# Used only for the idempotency reference string -- never written into the
# `custom_sales_order` Link field.
NO_SALES_ORDER_KEY = "NO-SALES-ORDER"


def auto_create_packing_slips_before_submit(doc, method=None):
    """Delivery Note `before_submit` hook: auto-create one Packing Slip per Sales Order."""
    if cint(doc.get("is_return")):
        return

    if not _auto_create_enabled():
        return

    groups = _build_groups(doc)
    if not groups:
        return

    expected_keys = {_reference_key(doc.name, group_key) for group_key in groups}

    if _check_existing_packing_slips(doc, expected_keys) == "already_done":
        return

    created = []
    for case_no, (group_key, group) in enumerate(groups.items(), start=1):
        ps_name = _create_and_submit_packing_slip(doc, group_key, group, case_no)
        if ps_name:
            created.append(ps_name)

    if created:
        frappe.msgprint(
            _("Auto-created and submitted {0} Packing Slip(s): {1}").format(
                len(created), ", ".join(created)
            ),
            indicator="green",
            alert=True,
        )


def _auto_create_enabled() -> bool:
    """True when Factory Settings enables auto Packing Slip creation.

    Defaults to disabled, including when the setting field does not exist yet
    (e.g. before the fixture has been migrated).
    """
    try:
        value = frappe.db.get_single_value(
            "Factory Settings", "auto_create_packing_slips_on_delivery_note_submit"
        )
    except Exception:
        return False
    return bool(cint(value))


def _is_product_bundle(item_code: str) -> bool:
    """True when the item is an active Product Bundle (a bundle parent row)."""
    return bool(
        frappe.db.exists("Product Bundle", {"new_item_code": item_code, "disabled": 0})
    )


def _reference_key(delivery_note: str, group_key: str) -> str:
    """Deterministic idempotency key, e.g. ``DN-0001|SO-0001``."""
    return f"{delivery_note}|{group_key}"


def _build_groups(doc) -> dict:
    """Group packable rows of the Delivery Note by their Sales Order.

    Returns an insertion-ordered dict::

        {group_key: {"sales_order": str | None,
                     "dn_items": [Delivery Note Item, ...],
                     "packed_items": [Packed Item, ...]}}

    Product Bundle parent rows are skipped; their components are packed as
    Packed Items (`pi_detail`), consistent with the standard `make_packing_slip`.
    """
    groups: dict = {}

    def _group(key: str, sales_order):
        if key not in groups:
            groups[key] = {"sales_order": sales_order, "dn_items": [], "packed_items": []}
        return groups[key]

    # Sales Order per Delivery Note Item, so Packed Items can inherit the group
    # of their bundle parent row.
    sales_order_by_dn_item: dict = {}

    for item in doc.get("items") or []:
        sales_order = item.get("against_sales_order") or None
        sales_order_by_dn_item[item.name] = sales_order

        if flt(item.get("qty")) <= 0:
            continue
        if _is_product_bundle(item.item_code):
            continue

        _group(sales_order or NO_SALES_ORDER_KEY, sales_order)["dn_items"].append(item)

    for packed_item in doc.get("packed_items") or []:
        if flt(packed_item.get("qty")) <= 0:
            continue
        sales_order = sales_order_by_dn_item.get(
            packed_item.get("parent_detail_docname")
        )
        _group(sales_order or NO_SALES_ORDER_KEY, sales_order)["packed_items"].append(
            packed_item
        )

    return {
        key: group
        for key, group in groups.items()
        if group["dn_items"] or group["packed_items"]
    }


def _check_existing_packing_slips(doc, expected_keys: set) -> str:
    """Decide whether it is safe to auto-create Packing Slips for the Delivery Note.

    Returns ``"create"`` when there are no non-cancelled Packing Slips, or
    ``"already_done"`` when our complete auto-created set already exists (a safe
    `before_submit` retry). Throws otherwise, so partial or manually created
    Packing Slips are never silently built upon.
    """
    existing = frappe.get_all(
        "Packing Slip",
        filters={"delivery_note": doc.name, "docstatus": ["!=", 2]},
        fields=[
            "name",
            "docstatus",
            "custom_auto_created_from_delivery_note",
            "custom_auto_creation_reference",
        ],
    )
    if not existing:
        return "create"

    all_auto = all(
        cint(ps.custom_auto_created_from_delivery_note) for ps in existing
    )
    all_submitted = all(ps.docstatus == 1 for ps in existing)
    existing_keys = {ps.custom_auto_creation_reference for ps in existing}

    if all_auto and all_submitted and existing_keys == expected_keys:
        return "already_done"

    frappe.throw(
        _(
            "Delivery Note {0} already has Packing Slip(s) ({1}). Automatic "
            "Packing Slip creation was skipped to avoid duplicates or partial "
            "coverage. Please cancel or delete the existing Packing Slip(s) and "
            "submit the Delivery Note again."
        ).format(doc.name, ", ".join(ps.name for ps in existing))
    )


def _create_and_submit_packing_slip(doc, group_key: str, group: dict, case_no: int):
    """Create and submit one Packing Slip for a single Sales Order group."""
    sales_order = group["sales_order"]
    reference = _reference_key(doc.name, group_key)
    group_label = sales_order or _("(no Sales Order)")

    ps = frappe.new_doc("Packing Slip")
    ps.delivery_note = doc.name
    ps.from_case_no = case_no
    ps.to_case_no = case_no
    if sales_order:
        ps.custom_sales_order = sales_order
    ps.custom_auto_created_from_delivery_note = 1
    ps.custom_auto_creation_reference = reference
    ps.custom_auto_created_on = now_datetime()
    if doc.get("letter_head"):
        ps.letter_head = doc.letter_head

    for item in group["dn_items"]:
        pack_qty = flt(item.get("qty")) - flt(item.get("packed_qty"))
        if pack_qty <= 0:
            continue
        ps.append(
            "items",
            {
                "item_code": item.item_code,
                "item_name": item.get("item_name"),
                "description": item.get("description"),
                "qty": pack_qty,
                "stock_uom": item.get("uom"),
                "batch_no": item.get("batch_no"),
                "dn_detail": item.name,
                # Pallet fields are Delivery Note specific; copy the snapshot
                # onto the Packing Slip Item row. Coverage is always full here
                # (see _check_existing_packing_slips), so no scaling is needed.
                "custom_pallet_type": item.get("custom_pallet_type"),
                "custom_pallet_qty": item.get("custom_pallet_qty"),
                "custom_pallet_conversion_factor": item.get(
                    "custom_pallet_conversion_factor"
                ),
                "custom_pallet_qty_manual": item.get("custom_pallet_qty_manual"),
            },
        )

    for packed_item in group["packed_items"]:
        pack_qty = flt(packed_item.get("qty")) - flt(packed_item.get("packed_qty"))
        if pack_qty <= 0:
            continue
        # Packed Item (Product Bundle component) rows carry no pallet fields.
        ps.append(
            "items",
            {
                "item_code": packed_item.item_code,
                "item_name": packed_item.get("item_name"),
                "description": packed_item.get("description"),
                "qty": pack_qty,
                "stock_uom": packed_item.get("uom"),
                "batch_no": packed_item.get("batch_no"),
                "pi_detail": packed_item.name,
            },
        )

    if not ps.get("items"):
        return None

    try:
        ps.flags.ignore_permissions = True
        ps.insert()
        ps.submit()
    except Exception as e:
        frappe.log_error(
            title="Auto Packing Slip Creation Failed",
            message=frappe.get_traceback(),
        )
        frappe.throw(
            _(
                "Could not auto-create Packing Slip for Delivery Note {0} / {1}: {2}"
            ).format(doc.name, group_label, str(e))
        )

    # Mirror the packed quantities onto the in-memory Delivery Note rows. See the
    # module docstring for why this is required.
    for item in group["dn_items"]:
        item.packed_qty = flt(item.get("qty"))
    for packed_item in group["packed_items"]:
        packed_item.packed_qty = flt(packed_item.get("qty"))

    return ps.name
