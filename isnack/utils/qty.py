# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""Quantity quantisation against the precision stock is actually posted at.

There is exactly one quantum in this system: **one unit at the precision of the
field the quantity is destined for**, read from the framework at the moment of
use. Any other threshold is a number in no unit at all.

Why this module exists
----------------------
``Stock Entry Detail.qty`` and ``.transfer_qty`` both declare ``precision: null``,
so Frappe resolves them (frappe/model/meta.py) to the site's System Settings
``float_precision`` — 3 by default. ERPNext then rejects any row whose quantity
rounds to zero there::

    # erpnext/stock/doctype/stock_entry/stock_entry.py (version-15)
    item.transfer_qty = flt(flt(item.qty) * flt(item.conversion_factor),
                            self.precision("transfer_qty", item))
    if not flt(item.transfer_qty):
        frappe.throw(_("Row {0}: Qty in Stock UOM can not be zero."),
                     title=_("Zero quantity"))

A hardcoded epsilon cannot model that, because it does not move when the site's
precision does. ISNACK's ``QTY_EPSILON`` (1e-4) is five times *smaller* than the
rounding boundary at precision 3 (5e-4), which is what let quantities that round
to zero reach a Stock Entry and hard-block Work Order closure.

This mirrors ERPNext core, which funnels every material row through
``StockEntry.add_to_stock_entry_detail`` — quantise to
``frappe.get_precision("Stock Entry Detail", "qty")``, drop the row if it is not
positive, store the quantised value — and which names the same idiom
``_qty_tolerance(precision) = 1.0 / (10 ** precision)``.
"""

from decimal import Decimal, ROUND_CEILING, ROUND_DOWN

import frappe
from frappe.utils import flt


def qty_precision() -> int:
    """Decimal places a Stock Entry quantity can actually be posted at.

    Read from the framework on every call rather than cached, so the app follows
    a site that changes System Settings -> Float Precision. The ``or 3`` guards a
    Property Setter of 0, where ``flt(x, 0)`` would integer-round every quantity
    in the app.
    """
    return frappe.get_precision("Stock Entry Detail", "qty") or 3


def qty_tick() -> float:
    """The smallest postable quantity: one unit at ``qty_precision()``."""
    return 1.0 / (10 ** qty_precision())


def truncate_qty(value) -> float:
    """Quantise toward zero at the posting precision.

    Toward zero, not downward: this is applied to derived residuals, which must
    never be inflated in either direction. A shortfall is never rounded up into
    consumption that the BOM did not ask for, and an over-consumption magnitude
    is never reported larger than it was. ``ROUND_DOWN`` is Decimal's
    truncate-toward-zero mode, hence the name — do not read it as ``floor``,
    which would push negatives away from zero.
    """
    quantum = Decimal(1).scaleb(-qty_precision())
    return float(Decimal(str(flt(value))).quantize(quantum, rounding=ROUND_DOWN))


def ceil_qty(value) -> float:
    """Smallest postable quantity not below ``value``."""
    quantum = Decimal(1).scaleb(-qty_precision())
    return float(Decimal(str(flt(value))).quantize(quantum, rounding=ROUND_CEILING))


def postable_qty(value) -> float:
    """Quantise to nearest at the posting precision, or 0.0 if unpostable.

    Uses ``flt`` — the same function ERPNext's zero check uses — so this can
    never disagree with it, whatever rounding method the site is configured for.
    Sign is preserved: callers keep their own positive/negative branch, and a
    negative quantity is *not* made safe by this function.
    """
    return flt(value, qty_precision())
