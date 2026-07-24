# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""Shared parsing for scanned label payloads.

The canonical payload printed inside every iSnack label QR (carton, pallet,
collective) is pipe-separated: "ITEM_CODE|BATCH_NO|QUANTITY". Some USB
scanners on a different keyboard layout emit a tilde ("~") instead of the
pipe, so "~" is accepted as an alias. GS1 Application Identifier strings —
(01) GTIN, (10) batch, (17) expiry, (30)/(37) quantity — are recognised
first; the basic pipe format is the fallback.

Both the Operator Hub material-consumption scans (isnack.api.mes_ops) and
the Delivery Note label scans (isnack.api.delivery_note_scan) must accept
the exact same payloads, so the parser lives here and nowhere else.
"""

import frappe


def parse_gs1_or_basic(code: str) -> dict:
    """Parse a scanned code into {item_code, batch_no, qty, gtin, expiry}.

    Keys are only present when the payload carries them; qty is dropped when
    it is not numeric. A GS1 GTIN is resolved to an item via Item Barcode.
    """
    # Lazy import: the batch-space normalisation lives in the Storekeeper Hub
    # page module, which must not be dragged in just by importing this util.
    from isnack.isnack.page.storekeeper_hub.storekeeper_hub import _process_batch_spaces

    out: dict = {}
    s = code or ""
    if s.startswith(("]d2", "]C1", "]Q3")):
        s = s[3:]

    def grab(ai, ln=None):
        idx = s.find(ai)
        if idx < 0:
            return None
        val = s[idx + len(ai):]
        if ln:
            return val[:ln]
        end = val.find("(")
        return val if end < 0 else val[:end]

    gtin = grab("(01)", 14)
    if gtin: out["gtin"] = gtin
    batch = grab("(10)")
    if batch: out["batch_no"] = _process_batch_spaces(batch)
    exp = grab("(17)", 6)
    if exp: out["expiry"] = exp
    qty = grab("(30)") or grab("(37)")
    if qty:
        try: out["qty"] = float(qty)
        except Exception: pass

    if "gtin" in out:
        item = frappe.db.get_value("Item Barcode", {"barcode": out["gtin"]}, "parent")
        if item: out["item_code"] = item

    if "item_code" not in out:
        # Basic "ITEM|BATCH|QTY" fallback. Some USB scanners on a different
        # keyboard layout emit "~" instead of "|", so treat "~" as an alias for
        # "|" here (the canonical printed payload stays pipe-separated).
        parts = s.replace("~", "|").split("|")
        if len(parts) >= 1: out["item_code"] = parts[0]
        if len(parts) >= 2: out["batch_no"] = _process_batch_spaces(parts[1])
        if len(parts) >= 3:
            try: out["qty"] = float(parts[2])
            except Exception: pass
    return out
