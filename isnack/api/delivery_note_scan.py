# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""Delivery Note "Scan Barcode" backend that understands iSnack label QRs.

The Delivery Note form points its BarcodeScanner at
:func:`scan_delivery_note_code` (see ``public/js/delivery_note.js``).
Payloads that parse as a production label — ``ITEM_CODE|BATCH_NO|QTY``
(pipe- or tilde-separated) or a GS1 string whose GTIN is on file — are
validated here and answered in the shape ERPNext's stock BarcodeScanner
expects, plus ``isnack_*`` extras only the Delivery Note scanner subclass
reads. Everything else falls through to ``erpnext.stock.utils.scan_barcode``,
so plain item barcodes, bare batch numbers and warehouse scans keep behaving
exactly as stock ERPNext.

Feature-flagged by Factory Settings ("Enable Delivery Note Label Scanning");
while disabled this endpoint is a transparent proxy to the stock lookup.
"""

from __future__ import annotations

import inspect

import frappe
from frappe import _
from frappe.utils import cint, flt

from erpnext.stock.doctype.batch.batch import get_batch_qty
from erpnext.stock.utils import scan_barcode as _erpnext_scan_barcode

from isnack.utils.scan import parse_gs1_or_basic

QTY_MODES = ("Increment by Label Qty", "Increment by 1", "Assign Batch Only")
DEFAULT_QTY_MODE = "Increment by Label Qty"


def get_dn_scan_settings() -> dict:
    """Delivery Note label-scanning Factory Settings, with safe defaults."""
    try:
        fs = frappe.get_cached_doc("Factory Settings")
    except Exception:
        return {
            "enabled": 0,
            "qty_mode": DEFAULT_QTY_MODE,
            "restrict_to_existing_items": 1,
        }

    qty_mode = fs.get("dn_scan_qty_mode") or DEFAULT_QTY_MODE
    if qty_mode not in QTY_MODES:
        qty_mode = DEFAULT_QTY_MODE

    # A Single doc returns None for fields never saved, so an unset checkbox
    # must fall back to the recommended default (on), not to off.
    restrict = fs.get("dn_scan_restrict_to_existing_items")
    return {
        "enabled": cint(fs.get("dn_scan_enabled") or 0),
        "qty_mode": qty_mode,
        "restrict_to_existing_items": 1 if restrict is None else cint(restrict),
    }


def _core_scan(search_value: str, ctx=None):
    """Delegate to ERPNext's stock scan lookup.

    Newer v15 releases accept a ``ctx`` argument, older ones do not — pass it
    only when the installed signature has it.
    """
    kwargs = {"search_value": search_value}
    if ctx is not None:
        try:
            if "ctx" in inspect.signature(_erpnext_scan_barcode).parameters:
                kwargs["ctx"] = ctx
        except (TypeError, ValueError):
            pass
    return _erpnext_scan_barcode(**kwargs) or {}


def _stock_warning(item_code: str, batch_no: str, ctx) -> str | None:
    """Orange-alert text when the scanned batch has no stock in the source
    warehouse; None when stock exists or the check cannot be made."""
    try:
        if isinstance(ctx, str):
            ctx = frappe.parse_json(ctx)
        warehouse = (ctx or {}).get("set_warehouse")
        if not warehouse:
            return None
        available = flt(
            get_batch_qty(batch_no=batch_no, warehouse=warehouse, item_code=item_code)
        )
        if available > 0:
            return None
        return _("Batch {0} has no available stock in {1}.").format(batch_no, warehouse)
    except Exception:
        # The warning is advisory only — never let it break scanning.
        return None


@frappe.whitelist()
def scan_delivery_note_code(search_value: str, ctx=None):
    """Scan endpoint for the Delivery Note form (BarcodeScanner ``scan_api``)."""
    raw = search_value or ""
    settings = get_dn_scan_settings()
    if not settings["enabled"]:
        return _core_scan(raw, ctx)

    stripped = raw.strip()
    parsed = parse_gs1_or_basic(stripped) if stripped else {}
    item_code = (parsed.get("item_code") or "").strip()
    batch_no = (parsed.get("batch_no") or "").strip()

    # Treat the scan as a label only when the payload is structurally one: a
    # pipe/tilde-separated string, or a GS1 string. Bare tokens (item
    # barcodes, batch numbers, serials) belong to the stock lookup, which
    # already resolves them.
    has_separator = "|" in stripped or "~" in stripped
    if not item_code or not (has_separator or parsed.get("gtin")):
        return _core_scan(raw, ctx)

    if not frappe.db.exists("Item", item_code):
        if has_separator:
            # A pipe/tilde payload is certainly one of our labels, so an
            # unknown item deserves a specific error — the stock lookup could
            # never match the composite string anyway.
            frappe.throw(
                _("Scanned label refers to Item {0}, which does not exist.").format(
                    frappe.bold(item_code)
                )
            )
        # A GS1 whose GTIN is not on file is somebody else's barcode: the
        # parser fell back to the raw string as "item_code", so hand the scan
        # to the stock lookup instead of claiming it.
        return _core_scan(raw, ctx)

    if batch_no:
        batch_item = frappe.db.get_value("Batch", batch_no, "item")
        if not batch_item:
            frappe.throw(
                _("Scanned label refers to Batch {0}, which does not exist.").format(
                    frappe.bold(batch_no)
                )
            )
        if batch_item != item_code:
            frappe.throw(
                _(
                    "Scanned label is inconsistent: Batch {0} belongs to Item {1}, "
                    "not {2}."
                ).format(
                    frappe.bold(batch_no),
                    frappe.bold(batch_item),
                    frappe.bold(item_code),
                )
            )

    item = frappe.get_cached_value(
        "Item", item_code, ["has_batch_no", "has_serial_no", "stock_uom"], as_dict=True
    )
    if cint(item.has_serial_no):
        frappe.throw(
            _(
                "Item {0} is serialised; scan its serial numbers instead of a label."
            ).format(frappe.bold(item_code))
        )

    response = {
        "item_code": item_code,
        "has_batch_no": cint(item.has_batch_no),
        "has_serial_no": 0,
        # isnack extras consumed by the Delivery Note scanner subclass; the
        # stock BarcodeScanner ignores unknown keys.
        "isnack_label_scan": 1,
        "isnack_scanned_qty": flt(parsed.get("qty") or 0),
        "isnack_stock_uom": item.stock_uom,
        "isnack_qty_mode": settings["qty_mode"],
        "isnack_restrict_to_existing_items": settings["restrict_to_existing_items"],
    }
    if batch_no:
        response["batch_no"] = batch_no
        warning = _stock_warning(item_code, batch_no, ctx)
        if warning:
            response["isnack_stock_warning"] = warning
    return response
