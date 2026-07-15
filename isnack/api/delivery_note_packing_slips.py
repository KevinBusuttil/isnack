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

from isnack.utils.printing import enqueue_doc_print

# Deterministic group key for Delivery Note rows that have no Sales Order.
# Used only for the idempotency reference string -- never written into the
# `custom_sales_order` Link field.
NO_SALES_ORDER_KEY = "NO-SALES-ORDER"

# Item groups whose rows are services / non-physical and must never appear on
# an auto-created Packing Slip. Including them would mix UOMs (e.g. blank
# weight_uom vs Kg) and break the Packing Slip net-weight validation.
_NON_PACKABLE_ITEM_GROUPS = {
    "Services",
}


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

    allocations_by_group = _resolve_group_allocations(doc, groups)
    bundle_quantities = _dn_bundle_quantities(groups)

    created = []
    for case_no, (group_key, group) in enumerate(groups.items(), start=1):
        ps_name = _create_and_submit_packing_slip(
            doc,
            group_key,
            group,
            case_no,
            allocations_by_group.get(group_key) or [],
            bundle_quantities,
        )
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


def _is_packable_dn_item(item) -> bool:
    """True when a Delivery Note Item should be included in an auto Packing Slip.

    Non-stock items and service-type item groups are excluded so the resulting
    Packing Slip only contains physically packable rows with a consistent
    weight UOM.
    """
    if flt(item.get("qty")) <= 0:
        return False

    if _is_product_bundle(item.item_code):
        return False

    item_data = frappe.db.get_value(
        "Item",
        item.item_code,
        ["is_stock_item", "item_group"],
        as_dict=True,
    )

    if not item_data:
        return False

    if not cint(item_data.get("is_stock_item")):
        return False

    if (item_data.get("item_group") or "").strip() in _NON_PACKABLE_ITEM_GROUPS:
        return False

    return True


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

        if not _is_packable_dn_item(item):
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


def _resolve_group_allocations(doc, groups: dict) -> dict:
    """Decide which pallet-manifest rows each group's Packing Slip carries.

    With a single group, the whole manifest goes onto its Packing Slip. With
    several groups, each allocation row follows its item (+ batch, falling
    back to item only) to the group containing that Delivery Note row;
    allocations matching no group are attached to the first group so every
    manifest row appears on exactly one slip. A mixed pallet holding items of
    different Sales Orders is thereby split across those slips, each carrying
    its own items.
    """
    allocations = doc.get("custom_pallets") or []
    if not allocations:
        return {group_key: [] for group_key in groups}

    if len(groups) == 1:
        only_key = next(iter(groups))
        return {only_key: list(allocations)}

    group_by_key: dict = {}
    for group_key, group in groups.items():
        for item in group["dn_items"]:
            group_by_key.setdefault(
                (item.get("item_code"), item.get("batch_no") or ""), group_key
            )
            group_by_key.setdefault((item.get("item_code"), None), group_key)

    first_group_key = next(iter(groups))
    allocations_by_group: dict = {group_key: [] for group_key in groups}
    for allocation in allocations:
        item_code = allocation.get("item_code")
        target = group_by_key.get(
            (item_code, allocation.get("batch_no") or "")
        ) or group_by_key.get((item_code, None)) or first_group_key
        allocations_by_group[target].append(allocation)

    return allocations_by_group


def _dn_bundle_quantities(groups: dict) -> dict:
    """Per-batch stock quantities of every Serial and Batch Bundle in the groups."""
    from isnack.api.delivery_note_pallets import _get_bundle_batch_quantities

    bundles = {
        item.get("serial_and_batch_bundle")
        for group in groups.values()
        for item in group["dn_items"]
        if item.get("serial_and_batch_bundle")
    }
    return _get_bundle_batch_quantities(bundles)


def _dn_item_batch_splits(item, pack_qty: float, bundle_quantities: dict) -> list:
    """Packing Slip lines for one Delivery Note row: ``[(batch_no, qty), ...]``.

    A row whose batches live in a Serial and Batch Bundle is split into one
    line per batch, so the Packing Slip shows each batch with its own
    quantity (Packing Slip Item.batch_no is single-valued). Bundle entry
    quantities are stock-UOM and converted to the row UOM; they are scaled
    to pack_qty and the last line absorbs rounding residue so the lines sum
    to pack_qty exactly (the v15 status updater sums lines per dn_detail, so
    the Delivery Note packed-qty check still balances). Rows without a
    bundle stay one line, carrying the row's own batch_no (possibly None).
    """
    entries = [
        (batch_no, flt(stock_qty))
        for batch_no, stock_qty in bundle_quantities.get(
            item.get("serial_and_batch_bundle")
        ) or []
        if flt(stock_qty) > 0
    ]
    if not entries:
        return [(item.get("batch_no"), pack_qty)]

    conversion = flt(item.get("conversion_factor")) or 1.0
    row_qty = flt(item.get("qty"))
    scale = (pack_qty / row_qty) if row_qty else 1.0
    splits = [
        [batch_no, flt(stock_qty / conversion * scale, 4)]
        for batch_no, stock_qty in entries
    ]
    residue = flt(pack_qty - sum(qty for _batch, qty in splits), 4)
    if residue:
        splits[-1][1] = flt(splits[-1][1] + residue, 4)
    return [(batch_no, qty) for batch_no, qty in splits if qty > 0]


def _create_and_submit_packing_slip(
    doc,
    group_key: str,
    group: dict,
    case_no: int,
    pallet_allocations: list,
    bundle_quantities: dict,
):
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
        # One Packing Slip line per batch (bundle rows are split), so the
        # print shows each batch with its own quantity and expiry.
        for batch_no, split_qty in _dn_item_batch_splits(item, pack_qty, bundle_quantities):
            fraction = (split_qty / pack_qty) if pack_qty else 0
            ps.append(
                "items",
                {
                    "item_code": item.item_code,
                    "item_name": item.get("item_name"),
                    "description": item.get("description"),
                    "qty": split_qty,
                    "stock_uom": item.get("uom"),
                    "batch_no": batch_no,
                    "dn_detail": item.name,
                    # Pallet fields are Delivery Note specific; copy the
                    # snapshot onto the Packing Slip Item row, scaling the
                    # estimated Pallet Qty to this line's share so per-line
                    # figures stay proportional across batch splits.
                    "custom_pallet_type": item.get("custom_pallet_type"),
                    "custom_pallet_qty": (
                        flt(item.get("custom_pallet_qty")) * fraction
                        if item.get("custom_pallet_qty")
                        else item.get("custom_pallet_qty")
                    ),
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

    # Copy the pallet-manifest rows this slip covers. Guarded by a meta check
    # so Delivery Notes keep submitting before the custom_pallets field has
    # been migrated onto Packing Slip.
    if pallet_allocations and ps.meta.get_field("custom_pallets"):
        for allocation in sorted(
            pallet_allocations, key=lambda a: cint(a.get("pallet_no"))
        ):
            ps.append(
                "custom_pallets",
                {
                    "pallet_no": allocation.get("pallet_no"),
                    "pallet_type": allocation.get("pallet_type"),
                    "item_code": allocation.get("item_code"),
                    "batch_no": allocation.get("batch_no"),
                    "qty": allocation.get("qty"),
                    "uom": allocation.get("uom"),
                    "remarks": allocation.get("remarks"),
                },
            )

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

    # Send the submitted Packing Slip to the configured A4 Network Printer.
    # Printing failures must never break Delivery Note submission, so the call
    # is best-effort and only logs on error.
    try:
        enqueue_doc_print("Packing Slip", ps.name)
    except Exception:
        frappe.log_error(
            title="Auto Packing Slip Print Enqueue Failed",
            message=frappe.get_traceback(),
        )

    return ps.name
