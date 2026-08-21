# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""Single source of truth for "what does this Work Order actually need?".

Background
----------
ERPNext v15.87.2 recomputes ``Work Order.required_items`` from the BOM on every
save (``WorkOrder.validate`` -> ``set_required_items(reset_only_qty=True)``), so
a planner cannot hold a manual quantity. Current ERPNext ``version-15`` added a
Manufacturing Settings switch — *Allow Editing of Items and Quantities in Work
Order* (upstream commit ``b5e6c3e``, refined by ``62d5870`` / ``3c327d5``) —
which skips that reset while the flag is on. iSnack backports the behaviour
without touching ERPNext: see ``isnack.overrides.work_order.CustomWorkOrder``.

Preserving the edited row is only half the job. Most of the iSnack manufacturing
system (Storekeeper Hub staging, Operator Hub loading and closing) derives its
material demand straight from the BOM, so a Work Order edited to 147.910 kg
would still be staged, statused and consumed against the BOM's 155.365 kg. This
module is the one place that reconciles the two: callers keep their existing
BOM-derived *membership* logic — which is what encodes iSnack's deliberate
sub-assembly rules — and overlay the saved Work Order quantities on top of it.

The membership rules that must survive
--------------------------------------
``storekeeper_hub`` stages a parent Work Order against the **direct leaf** rows
of its BOM (``BOM Item`` rows with no ``bom_no``), never against the exploded
tree, so a finished-good Work Order does not claim raw materials that belong to
a separate semi-finished Work Order. ``mes_ops`` threads
``use_multi_level_bom`` through every BOM read for the same reason. Overlaying
quantities does not disturb any of that, because the overlay never *invents*
membership from the Work Order table except for rows the BOM has never heard of
(see ``manual``). An exploded sub-assembly raw material is BOM-known, so it can
never be promoted into a parent's leaf demand by this module.

Everything here is a no-op while the setting is off: callers get their input
back unchanged, and nothing extra is queried.
"""

import frappe
from frappe.utils import flt

SETTINGS_DOCTYPE = "Manufacturing Settings"

#: Fieldname ERPNext uses upstream (present after a future ERPNext upgrade).
UPSTREAM_FIELDNAME = "allow_editing_of_items_and_quantities_in_work_order"

#: Fieldname of the iSnack Custom Field (see isnack/isnack/custom/manufacturing_settings.json).
#: Deliberately prefixed so it can never collide with the upstream column when
#: ERPNext is upgraded past v15.87.2.
ISNACK_FIELDNAME = "custom_allow_editing_of_items_and_quantities_in_work_order"


def allow_editing_items() -> bool:
    """True when Work Order raw materials and quantities may be hand-edited.

    The upstream field is consulted first, so a site that has been upgraded to an
    ERPNext carrying the real setting is driven by the real setting. The iSnack
    Custom Field is the fallback — and it is still honoured when the upstream
    field exists but is off, so an ERPNext upgrade cannot silently switch the
    feature off underneath a site that had deliberately enabled it. Retiring the
    iSnack field after such an upgrade is a one-line patch, not a surprise.

    Missing field, missing doctype or a broken read all resolve to False: the
    default is always "behave exactly like stock v15.87.2".
    """
    try:
        meta = frappe.get_meta(SETTINGS_DOCTYPE)
    except Exception:
        return False

    for fieldname in (UPSTREAM_FIELDNAME, ISNACK_FIELDNAME):
        try:
            if not meta.has_field(fieldname):
                continue
            if frappe.db.get_single_value(SETTINGS_DOCTYPE, fieldname):
                return True
        except Exception:
            continue

    return False


class WorkOrderDemand:
    """Classification of one Work Order's material rows against its BOM.

    Attributes:
        enabled: False when the overlay must not apply at all (setting off, no
            BOM, or an empty ``required_items`` table). Every overlay helper
            short-circuits on this, returning its input untouched.
        required: ``item_code -> required_qty`` summed over the Work Order rows,
            expressed for ``Work Order.qty`` units.
        uoms: ``item_code -> stock uom`` as saved on the Work Order rows.
        covered: the item codes ERPNext itself would have written into
            ``required_items`` for this Work Order (``get_bom_items_as_dict``
            with the Work Order's own ``use_multi_level_bom``). Only these may
            be *removed* by the overlay when the planner deletes a row —
            anything outside this set was never the table's to carry.

            Resolved lazily, because it is the one expensive read here and it is
            only consulted when a caller's BOM-derived row is *missing* from the
            Work Order table. On the hot paths (Storekeeper Hub staging status,
            consolidated remaining) the table covers every row, so the read never
            happens.
        bom_known: every item code the BOM mentions, directly or exploded. Used
            only to decide what counts as manually added.
        manual: rows on the Work Order the BOM has never heard of.
    """

    __slots__ = (
        "enabled",
        "work_order",
        "required",
        "uoms",
        "bom_known",
        "manual",
        "_covered",
        "_covered_loader",
    )

    def __init__(self, enabled=False, work_order=None, covered_loader=None):
        self.enabled = enabled
        self.work_order = work_order
        self.required = {}
        self.uoms = {}
        self.bom_known = set()
        self.manual = set()
        self._covered = None
        self._covered_loader = covered_loader

    @property
    def covered(self):
        if self._covered is None:
            self._covered = self._covered_loader() if self._covered_loader else set()
        return self._covered

    def qty_for(self, item_code, scale=1.0):
        """Planned quantity for ``item_code``, or None when the WO does not say.

        ``scale`` rescales the Work Order requirement, which is stored for
        ``Work Order.qty`` units, to some other production quantity (a partial
        close, for instance).
        """
        if not self.enabled:
            return None
        if item_code in self.required:
            return flt(self.required[item_code]) * flt(scale)
        if item_code in self.covered:
            # Present in the set the table is expected to carry, absent from the
            # table itself: the planner deleted the row, so the demand is gone.
            return 0.0
        return None


def _as_doc(work_order):
    """Accept either a Work Order name or an already-loaded document."""
    if isinstance(work_order, str):
        return frappe.get_doc("Work Order", work_order)
    return work_order


def _covered_item_codes(wo):
    """Item codes ERPNext's own ``set_required_items`` would produce.

    Uses the very function ``WorkOrder.set_required_items`` calls, so "would
    ERPNext have put this row here?" is answered by ERPNext and not by a
    re-implementation of its include/exclude rules. Falls back to the raw BOM
    tables if that call fails for any reason, which keeps a broken read from
    turning into wrongly-deleted demand.
    """
    from erpnext.manufacturing.doctype.bom.bom import get_bom_items_as_dict

    try:
        # Called exactly as WorkOrder.set_required_items calls it — same
        # arguments, same company, same explode flag — so the key set cannot
        # drift from the table ERPNext would have written.
        item_dict = get_bom_items_as_dict(
            wo.bom_no,
            wo.get("company") or frappe.db.get_value("BOM", wo.bom_no, "company"),
            qty=flt(wo.qty) or 1,
            fetch_exploded=1 if wo.get("use_multi_level_bom") else 0,
        )
        return set(item_dict.keys())
    except Exception:
        frappe.log_error(
            title="Work Order Demand: BOM read failed",
            message=f"get_bom_items_as_dict failed for BOM {wo.bom_no}",
        )
        return _raw_bom_item_codes(wo.bom_no, exploded=bool(wo.get("use_multi_level_bom")))


def _raw_bom_item_codes(bom_no, exploded=False):
    doctype = "BOM Explosion Item" if exploded else "BOM Item"
    rows = frappe.get_all(doctype, filters={"parent": bom_no}, fields=["item_code"])
    return {r["item_code"] for r in rows if r.get("item_code")}


def get_demand(work_order) -> WorkOrderDemand:
    """Build the classification described on :class:`WorkOrderDemand`.

    Returns a disabled (inert) instance whenever the overlay must not apply, so
    every caller can use the result unconditionally.
    """
    if not allow_editing_items():
        return WorkOrderDemand(enabled=False)

    wo = _as_doc(work_order)
    if not wo:
        return WorkOrderDemand(enabled=False)

    rows = wo.get("required_items") or []
    if not isinstance(rows, (list, tuple)):
        # A caller handed us a stub/partial document (unit tests do this a lot).
        # Nothing to overlay from, so stay out of the way.
        return WorkOrderDemand(enabled=False, work_order=getattr(wo, "name", None))

    if not rows or not wo.get("bom_no"):
        # An empty table is repopulated from the BOM on the next save (upstream
        # keeps the same escape hatch), so the BOM stays authoritative until it
        # is. Never let an empty table erase a Work Order's demand.
        return WorkOrderDemand(enabled=False, work_order=getattr(wo, "name", None))

    demand = WorkOrderDemand(
        enabled=True,
        work_order=getattr(wo, "name", None),
        covered_loader=lambda: _covered_item_codes(wo),
    )

    for row in rows:
        item_code = row.get("item_code") if isinstance(row, dict) else getattr(row, "item_code", None)
        if not item_code:
            continue
        qty = row.get("required_qty") if isinstance(row, dict) else getattr(row, "required_qty", 0)
        demand.required[item_code] = demand.required.get(item_code, 0.0) + flt(qty)
        uom = row.get("stock_uom") if isinstance(row, dict) else getattr(row, "stock_uom", None)
        if uom and not demand.uoms.get(item_code):
            demand.uoms[item_code] = uom

    # The membership question ("did the BOM ever mention this?") is answered
    # from the raw tables on purpose: the widest possible reading of "BOM-known"
    # is the conservative one, because anything it excludes gets treated as a
    # manual addition and joins the parent Work Order's demand. Both tables are
    # a superset of whatever get_bom_items_as_dict can return, so this needs no
    # help from the lazily-resolved `covered`.
    demand.bom_known = _raw_bom_item_codes(wo.bom_no, exploded=False) | _raw_bom_item_codes(
        wo.bom_no, exploded=True
    )
    demand.manual = {code for code in demand.required if code not in demand.bom_known}

    return demand


def _uom_for(demand, item_code):
    return demand.uoms.get(item_code) or frappe.db.get_value("Item", item_code, "stock_uom") or ""


def overlay_map(work_order, base, scale=1.0, add_manual=True, demand=None):
    """Overlay saved Work Order quantities onto a BOM-derived demand map.

    Args:
        work_order: Work Order name or document.
        base: ``{item_code: {"uom": str, "qty": float}}`` built from the BOM by
            the caller. Its keys define membership and are not second-guessed.
        scale: multiplier when ``base`` is expressed for a production quantity
            other than ``Work Order.qty``.
        add_manual: append rows the planner added that the BOM does not know.
        demand: a pre-built :class:`WorkOrderDemand` (avoids a re-read).

    Returns the same shape as ``base``. Items outside ``demand.covered`` — an
    exploded sub-assembly raw material on a single-level Work Order, say — keep
    their BOM quantity, because the Work Order table was never responsible for
    them.
    """
    demand = demand if demand is not None else get_demand(work_order)
    if not demand.enabled:
        return base

    out = {}
    for item_code, info in (base or {}).items():
        qty = demand.qty_for(item_code, scale)
        if qty is None:
            out[item_code] = info
            continue
        if qty <= 0:
            continue
        row = dict(info)
        row["qty"] = qty
        out[item_code] = row

    if add_manual:
        for item_code in demand.manual:
            if item_code in out:
                continue
            qty = flt(demand.required.get(item_code)) * flt(scale)
            if qty <= 0:
                continue
            out[item_code] = {"uom": _uom_for(demand, item_code), "qty": qty}

    return out


def overlay_rows(work_order, rows, qty_key="qty", uom_key="uom", scale=1.0, add_manual=True, demand=None):
    """``overlay_map`` for the list-of-dicts shape ``mes_ops`` passes around.

    Row dicts are copied, never mutated in place, so a caller that also holds
    the BOM rows keeps an untouched copy.
    """
    demand = demand if demand is not None else get_demand(work_order)
    if not demand.enabled:
        return rows

    out = []
    seen = set()
    for row in rows or []:
        item_code = row.get("item_code")
        if not item_code:
            out.append(row)
            continue
        seen.add(item_code)
        qty = demand.qty_for(item_code, scale)
        if qty is None:
            out.append(row)
            continue
        if qty <= 0:
            continue
        new_row = dict(row)
        new_row[qty_key] = qty
        out.append(new_row)

    if add_manual:
        for item_code in sorted(demand.manual):
            if item_code in seen:
                continue
            qty = flt(demand.required.get(item_code)) * flt(scale)
            if qty <= 0:
                continue
            out.append({"item_code": item_code, qty_key: qty, uom_key: _uom_for(demand, item_code)})

    return out


def required_qty_for(work_order, item_code, scale=1.0, demand=None):
    """Planned quantity of one item for this Work Order, or None.

    None means "the Work Order has nothing to say about this item" — the caller
    must keep whatever BOM-derived figure it already had.
    """
    demand = demand if demand is not None else get_demand(work_order)
    if not demand.enabled:
        return None
    if item_code not in demand.required:
        # A deleted row deliberately does NOT report 0 here. This helper feeds
        # consumption *ceilings* (over-consumption thresholds), where a zero
        # would hard-block the shop floor; those callers fall back to the BOM.
        return None
    return flt(demand.required[item_code]) * flt(scale)


def is_manual_item(work_order, item_code, demand=None):
    """True when the planner added this item to the Work Order themselves.

    Only rows the BOM has never heard of qualify. An exploded sub-assembly raw
    material is BOM-known and therefore never "manual", which is what stops this
    from re-opening the parent/semi-finished separation that iSnack relies on.
    """
    demand = demand if demand is not None else get_demand(work_order)
    if not demand.enabled:
        return False
    return item_code in demand.manual
