# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""A batch that yields more than planned must still be closeable.

Reproduces the 17 September outage on a replica of the three Work Orders that
caused it, built from the production export:

    MFG-WO-2026-00072   80 Kg CORN MIX 1        (BOM-SFG10001-001)
    MFG-WO-2026-00073   60 Kg PUFFS CHEESY SLURRY (BOM-SFG10002-001)
    MFG-WO-2026-00071  150 Carton PUFFS SUPER CHEESY 21PKT x 40G
                       (BOM-FG10011-002, fed by the two above)

The line made 153 cartons off a charge planned for 150 — food yields move with
expansion and humidity — and Close Production refused it:

    1.599 units of Item SFG10001: CORN MIX 1 needed in Warehouse
    Semi-finished - ISN to complete this transaction.

That figure is the whole diagnosis. The close scales the recipe by actual
output and asks for the difference::

    80 x 153/150 - 80 == 1.5999999999999943   ->  1.599 at the posting precision

There was no such corn mix. The 153 cartons came out of the same 80 Kg, which
is what a yield gain is; Semi-finished held 0.000 and the recipe was asking for
material that was never made and never staged. Manufacturing Settings allows
10% over-production, so the output itself was sanctioned — only the material
arithmetic vetoed it. The manager's way out was to type 150, which left three
cartons of real product off the books.

The ledger below is the real one, entry for entry, so the numbers these tests
assert are the numbers the site produced.
"""

import unittest
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import frappe

import isnack.api.mes_ops as mes_ops

STORES = "Stores - ISN"
STAGING = "EXT1-STAGING - ISN"
WIP = "EXT1-WIP - ISN"
SEMI = "Semi-finished - ISN"
FG_WH = "Finished Goods - ISN"

FG_WO = "MFG-WO-2026-00071"
CORN_WO = "MFG-WO-2026-00072"
SLURRY_WO = "MFG-WO-2026-00073"

# (item_group, stock_uom, has_batch_no)
ITEMS = {
    "RM20011": ("Raw Materials", "Kg", 1),
    "RM20021": ("Raw Materials", "Kg", 1),
    "RM20022": ("Raw Materials", "Kg", 1),
    "RM20023": ("Raw Materials", "Litre", 0),
    "SFG10001": ("Semi-Finished Goods", "Kg", 0),
    "SFG10002": ("Semi-Finished Goods", "Kg", 0),
    "PM40011": ("Packaging Materials", "Kg", 1),
    "CR30003": ("Cartons", "Carton", 1),
    "FG10011": ("Finished Goods", "Carton", 1),
}
PACKAGING_GROUPS = {"packaging materials", "cartons"}

# BOM name -> (quantity produced, produced item, [(component, qty, uom), ...])
BOMS = {
    "BOM-SFG10001-001": (150.0, "SFG10001",
                         [("RM20022", 150.0, "Kg"), ("RM20023", 5.0, "Litre")]),
    "BOM-SFG10002-001": (125.0, "SFG10002",
                         [("RM20021", 80.0, "Kg"), ("RM20011", 45.0, "Kg")]),
    "BOM-FG10011-002": (300.0, "FG10011",
                        [("SFG10001", 160.0, "Kg"), ("SFG10002", 120.0, "Kg"),
                         ("PM40011", 21.0, "Kg"), ("CR30003", 300.0, "Carton")]),
}
SFG_CODES = {"SFG10001", "SFG10002"}       # the components with a BOM of their own


class InsufficientStock(frappe.ValidationError):
    """ERPNext's negative-stock refusal, in its own words.

    ``StockController.validate_negative_stock`` reports the resulting negative
    balance, which is why the operator saw 1.599 rather than the 1.6 the
    arithmetic suggests.
    """


class Ledger:
    """Submitted stock, replayed from the entries the site actually posted."""

    def __init__(self):
        self.entries = []          # {"purpose", "work_order", "fg_qty", "rows"}

    # -- posting ---------------------------------------------------------
    def post(self, purpose, work_order, rows, fg_qty=0.0, allow_negative=False):
        """rows: [{"item_code", "qty", "s_warehouse", "t_warehouse", ...}]"""
        if not allow_negative:
            for row in rows:
                src = row.get("s_warehouse")
                if not src:
                    continue
                after = self.balance(row["item_code"], src) - float(row["qty"])
                if after < -1e-9:
                    raise InsufficientStock(
                        f"{abs(round(after, 3))} units of Item {row['item_code']} "
                        f"needed in Warehouse {src} to complete this transaction."
                    )
        self.entries.append({
            "purpose": purpose, "work_order": work_order,
            "fg_qty": float(fg_qty), "rows": [dict(r) for r in rows],
        })

    def seed(self, warehouse, **quantities):
        self.post("Stock Reconciliation", None, [
            {"item_code": item, "qty": qty, "s_warehouse": None,
             "t_warehouse": warehouse}
            for item, qty in quantities.items()
        ])

    # -- reading ---------------------------------------------------------
    def balance(self, item_code, warehouse):
        total = 0.0
        for entry in self.entries:
            for row in entry["rows"]:
                if row["item_code"] != item_code:
                    continue
                if row.get("t_warehouse") == warehouse:
                    total += float(row["qty"])
                if row.get("s_warehouse") == warehouse:
                    total -= float(row["qty"])
        return round(total, 9)

    def inflow(self, work_order, warehouse):
        """Everything that arrived in `warehouse` under this Work Order's name."""
        out = {}
        for entry in self.entries:
            if entry["work_order"] != work_order:
                continue
            for row in entry["rows"]:
                if row.get("t_warehouse") == warehouse:
                    out[row["item_code"]] = out.get(row["item_code"], 0.0) + float(row["qty"])
        return out

    def consumed(self, work_order):
        out = {}
        for entry in self.entries:
            if entry["work_order"] != work_order:
                continue
            if entry["purpose"] != "Material Consumption for Manufacture":
                continue
            for row in entry["rows"]:
                if row.get("is_finished_item"):
                    continue
                out[row["item_code"]] = out.get(row["item_code"], 0.0) + float(row["qty"])
        return out

    def transfers_out(self, work_order, warehouse):
        """What this order moved back out of `warehouse` other than by
        consuming it — a return to staging, in practice."""
        out = {}
        for entry in self.entries:
            if entry["work_order"] != work_order:
                continue
            if entry["purpose"] in ("Material Consumption for Manufacture", "Manufacture"):
                continue
            for row in entry["rows"]:
                if row.get("s_warehouse") == warehouse:
                    out[row["item_code"]] = out.get(row["item_code"], 0.0) + float(row["qty"])
        return out

    def consumed_by_batch(self, work_order, item_code):
        out = {}
        for entry in self.entries:
            if entry["work_order"] != work_order:
                continue
            if entry["purpose"] != "Material Consumption for Manufacture":
                continue
            for row in entry["rows"]:
                if row["item_code"] == item_code:
                    key = row.get("batch_no") or ""
                    out[key] = out.get(key, 0.0) + float(row["qty"])
        return out

    def manufactured(self, work_order):
        total = 0.0
        for entry in self.entries:
            if entry["work_order"] == work_order and entry["purpose"] == "Manufacture":
                for row in entry["rows"]:
                    if row.get("is_finished_item"):
                        total += float(row["qty"])
        return total


class WorkOrder:
    """Enough of a Work Order doc for the close path, with its stored
    Required Items — this site has "Allow Editing of Items and Quantities in
    Work Order" on, so those, not the raw BOM, are what gets scaled."""

    def __init__(self, name, production_item, bom_no, qty, fg_warehouse, required):
        self.name = name
        self.production_item = production_item
        self.bom_no = bom_no
        self.qty = qty
        self.company = "Isnack"
        self.use_multi_level_bom = 0
        self.wip_warehouse = WIP
        self.fg_warehouse = fg_warehouse
        self.actual_end_date = None
        self.required = required          # {item_code: required_qty at self.qty}
        self.comments = []
        self.flags = MagicMock()

    def get(self, field, default=None):
        return getattr(self, field, default)

    def db_set(self, *a, **k):
        pass

    def reload(self):
        pass

    def save(self):
        pass

    def add_comment(self, _kind, text):
        self.comments.append(text)


WORK_ORDERS = {
    CORN_WO: WorkOrder(CORN_WO, "SFG10001", "BOM-SFG10001-001", 80.0, SEMI,
                       {"RM20022": 80.0, "RM20023": 2.666666667}),
    SLURRY_WO: WorkOrder(SLURRY_WO, "SFG10002", "BOM-SFG10002-001", 60.0, SEMI,
                         {"RM20021": 38.4, "RM20011": 21.6}),
    FG_WO: WorkOrder(FG_WO, "FG10011", "BOM-FG10011-002", 150.0, FG_WH,
                     {"SFG10001": 80.0, "SFG10002": 60.0,
                      "PM40011": 10.5, "CR30003": 150.0}),
}


def _fresh_work_orders():
    return {
        name: WorkOrder(wo.name, wo.production_item, wo.bom_no, wo.qty,
                        wo.fg_warehouse, dict(wo.required))
        for name, wo in WORK_ORDERS.items()
    }


def production_day():
    """The 17 September run, entry for entry, up to the point of close.

    MAT-STE-2026-00401/00406/00408/00409/00410 (corn mix),
    -00405/00411/00412/00413/00414 (slurry),
    -00403/00415/00417 (the finished product's packaging and its End WO
    semi-finished consumption).
    """
    led = Ledger()
    led.seed(STORES, RM20011=500.0, RM20021=500.0, RM20022=500.0, RM20023=900.0,
             PM40011=200.0, CR30003=2000.0)
    # The line's WIP is a shared pool and carried a little packaging over from
    # an earlier order — which is how 155 cartons could be consumed against 150
    # transferred, exactly as the real close did.
    led.seed(WIP, CR30003=5.0, PM40011=1.5)

    # --- MFG-WO-2026-00072: 80 Kg CORN MIX 1 -------------------------------
    led.post("Material Transfer", CORN_WO, [
        {"item_code": "RM20022", "qty": 80.0, "s_warehouse": STORES, "t_warehouse": STAGING},
        {"item_code": "RM20023", "qty": 2.667, "s_warehouse": STORES, "t_warehouse": STAGING},
    ])
    led.post("Material Transfer for Manufacture", CORN_WO, [
        {"item_code": "RM20022", "qty": 80.0, "s_warehouse": STAGING, "t_warehouse": WIP},
        {"item_code": "RM20023", "qty": 2.667, "s_warehouse": STAGING, "t_warehouse": WIP},
    ], fg_qty=80.0)
    led.post("Material Consumption for Manufacture", CORN_WO, [
        {"item_code": "RM20022", "qty": 80.0, "s_warehouse": WIP, "t_warehouse": None},
    ], fg_qty=80.0)
    led.post("Material Consumption for Manufacture", CORN_WO, [
        {"item_code": "RM20023", "qty": 2.667, "s_warehouse": WIP, "t_warehouse": None},
    ], fg_qty=80.0)
    led.post("Manufacture", CORN_WO, [
        {"item_code": "SFG10001", "qty": 80.0, "s_warehouse": None,
         "t_warehouse": SEMI, "is_finished_item": 1},
    ], fg_qty=80.0)

    # --- MFG-WO-2026-00073: 60 Kg SLURRY -----------------------------------
    led.post("Material Transfer", SLURRY_WO, [
        {"item_code": "RM20011", "qty": 21.6, "s_warehouse": STORES, "t_warehouse": STAGING},
        {"item_code": "RM20021", "qty": 38.4, "s_warehouse": STORES, "t_warehouse": STAGING},
    ])
    led.post("Material Transfer for Manufacture", SLURRY_WO, [
        {"item_code": "RM20011", "qty": 21.6, "s_warehouse": STAGING, "t_warehouse": WIP},
        {"item_code": "RM20021", "qty": 38.4, "s_warehouse": STAGING, "t_warehouse": WIP},
    ], fg_qty=60.0)
    led.post("Material Consumption for Manufacture", SLURRY_WO, [
        {"item_code": "RM20021", "qty": 38.4, "s_warehouse": WIP, "t_warehouse": None},
    ], fg_qty=60.0)
    led.post("Material Consumption for Manufacture", SLURRY_WO, [
        {"item_code": "RM20011", "qty": 21.6, "s_warehouse": WIP, "t_warehouse": None},
    ], fg_qty=60.0)
    led.post("Manufacture", SLURRY_WO, [
        {"item_code": "SFG10002", "qty": 60.0, "s_warehouse": None,
         "t_warehouse": SEMI, "is_finished_item": 1},
    ], fg_qty=60.0)

    # --- MFG-WO-2026-00071: packaging staged, then End WO ------------------
    led.post("Material Transfer", FG_WO, [
        {"item_code": "CR30003", "qty": 150.0, "s_warehouse": STORES,
         "t_warehouse": SEMI, "batch_no": "CRT100626"},
        {"item_code": "PM40011", "qty": 10.5, "s_warehouse": STORES,
         "t_warehouse": SEMI, "batch_no": "Cog100626"},
    ])
    led.post("Material Transfer for Manufacture", FG_WO, [
        {"item_code": "CR30003", "qty": 150.0, "s_warehouse": SEMI,
         "t_warehouse": WIP, "batch_no": "CRT100626"},
        {"item_code": "PM40011", "qty": 10.5, "s_warehouse": SEMI,
         "t_warehouse": WIP, "batch_no": "Cog100626"},
    ], fg_qty=150.0)
    # End WO consumed the semi-finished per the plan of 150, emptying
    # Semi-finished of both: this is why nothing was left for the recipe to
    # scale into.
    led.post("Material Consumption for Manufacture", FG_WO, [
        {"item_code": "SFG10001", "qty": 80.0, "s_warehouse": SEMI, "t_warehouse": None},
        {"item_code": "SFG10002", "qty": 60.0, "s_warehouse": SEMI, "t_warehouse": None},
    ], fg_qty=150.0)
    return led


class Factory:
    """Binds the ledger and the fixture documents into mes_ops."""

    def __init__(self, ledger=None, work_orders=None, metered=()):
        self.ledger = ledger or production_day()
        self.work_orders = work_orders or _fresh_work_orders()
        self.metered = set(metered)
        self.logged = []

    # -- the things mes_ops asks the framework for ------------------------
    def planned_items(self, wo, qty):
        scale = float(qty) / float(wo.qty) if wo.qty else 1.0
        order = [c for c, _q, _u in BOMS[wo.bom_no][2]]
        return [
            {"item_code": code,
             "qty": wo.required[code] * scale,
             "uom": ITEMS[code][1]}
            for code in order if code in wo.required
        ]

    def sfg_components(self, wo_name):
        wo = self.work_orders[wo_name]
        return {"items": [
            {"item_code": code}
            for code, _q, _u in BOMS[wo.bom_no][2]
            if code in SFG_CODES
        ]}

    def db_get_value(self, doctype, name, field=None, *a, **k):
        if doctype == "Item":
            group, uom, has_batch = ITEMS[name]
            return {"stock_uom": uom, "has_batch_no": has_batch,
                    "item_group": group, "item_name": name}.get(field)
        if doctype == "Work Order":
            wo = self.work_orders.get(name)
            return getattr(wo, field, None) if wo else None
        return None

    def db_get_single_value(self, doctype, fieldname, *a, **k):
        if doctype == "Manufacturing Settings":
            # The live setting: 10% over-production is allowed, so 153 against
            # a plan of 150 is sanctioned output.
            return 10 if fieldname == "overproduction_percentage_for_work_order" else 0
        if doctype == "Stock Settings":
            return STORES
        return None

    def new_stock_entry(self):
        entry = FakeStockEntry(self.ledger)
        self.posted = entry
        return entry

    def patches(self):
        led = self.ledger
        return [
            patch.object(mes_ops.frappe, "get_doc",
                         side_effect=lambda dt, name, *a, **k: self.work_orders[name]),
            patch.object(mes_ops.frappe, "new_doc",
                         side_effect=lambda *a, **k: self.new_stock_entry()),
            patch.object(mes_ops.frappe, "get_precision", return_value=3),
            patch.object(mes_ops.frappe, "log_error",
                         side_effect=lambda **kw: self.logged.append(kw)),
            patch.object(mes_ops.frappe.utils, "now_datetime",
                         return_value="2026-09-17 08:35:00"),
            patch.object(mes_ops.frappe.db, "get_value", side_effect=self.db_get_value),
            patch.object(mes_ops.frappe.db, "get_single_value",
                         side_effect=self.db_get_single_value),
            patch.object(mes_ops.frappe.db, "set_value"),
            patch.object(mes_ops, "_require_roles"),
            patch.object(mes_ops, "_planned_items_for_wo", side_effect=self.planned_items),
            patch.object(mes_ops, "get_sfg_components_for_wo", side_effect=self.sfg_components),
            patch.object(mes_ops, "_default_sfg_source", return_value=SEMI),
            patch.object(mes_ops, "_default_line_wip", return_value=WIP),
            patch.object(mes_ops, "_default_line_staging", return_value=STAGING),
            patch.object(mes_ops, "_default_line_target", return_value=FG_WH),
            patch.object(mes_ops, "_default_line_scrap", return_value="Scrap - ISN"),
            patch.object(mes_ops, "_packaging_groups_global", return_value=PACKAGING_GROUPS),
            patch.object(mes_ops, "_get_item_group",
                         side_effect=lambda code: ITEMS[code][0]),
            patch.object(mes_ops, "_metered_items", return_value=set(self.metered)),
            patch.object(mes_ops, "_sweep_surplus_to_wip", return_value=[]),
            patch.object(mes_ops, "_ensure_batch"),
            patch.object(mes_ops, "_apply_pre_consumed_cost_to_finished_item"),
            patch.object(mes_ops, "_submitted_mtfm_qty",
                         side_effect=lambda wo: self.work_orders[wo].qty),
            patch.object(mes_ops, "_submitted_manufacture_qty",
                         side_effect=led.manufactured),
            patch.object(mes_ops, "_get_consumed_materials_from_load",
                         side_effect=led.consumed),
            patch.object(mes_ops, "_wip_inflow_by_item",
                         side_effect=lambda wo, wh: led.inflow(wo, wh)),
            patch.object(mes_ops, "_wip_transfers_out_by_item",
                         side_effect=lambda wo, wh: led.transfers_out(wo, wh)),
            patch.object(mes_ops, "_warehouse_qty",
                         side_effect=lambda item, wh: led.balance(item, wh)),
            patch.object(mes_ops, "_consumed_qty_by_batch",
                         side_effect=lambda wos, item: led.consumed_by_batch(wos[0], item)),
            patch.object(mes_ops.frappe, "get_all", side_effect=self.get_all),
        ]

    def get_all(self, doctype, filters=None, fields=None, **k):
        if doctype != "Work Order":
            return []
        names = (filters or {}).get("name", ["in", []])[1]
        return [{"name": n, "qty": self.work_orders[n].qty}
                for n in names if n in self.work_orders]


class FakeStockEntry:
    """Posts into the ledger on submit, so the negative-stock refusal that
    blocked the real close is reproduced rather than assumed."""

    def __init__(self, ledger):
        self.ledger = ledger
        self.items = []
        self.flags = MagicMock()
        self.name = "MAT-STE-NEW"
        self.purpose = None
        self.work_order = None
        self.fg_completed_qty = 0.0

    def append(self, _table, row):
        self.items.append(row)

    def insert(self):
        pass

    def submit(self):
        self.ledger.post(self.purpose, self.work_order, [
            dict(row, t_warehouse=row.get("t_warehouse")) for row in self.items
        ], fg_qty=self.fg_completed_qty)


def close_at(factory, good, reject=0.0, packaging=None, wo_name=FG_WO, batch="BBB-114"):
    """Run Close Production for one order at the declared output."""
    if packaging is None:
        packaging = [
            {"item_code": "CR30003", "qty": 155.0, "batch_no": "CRT100626"},
            {"item_code": "PM40011", "qty": 12.0, "batch_no": "Cog100626"},
        ]
    with ExitStack() as stack:
        for p in factory.patches():
            stack.enter_context(p)
        mes_ops._close_single_wo(
            {"name": wo_name},
            {"good": good, "reject": reject, "packaging": packaging},
            batch,
        )
    return factory.posted


def complete_at(factory, good, reject=0.0, wo_name=CORN_WO):
    """Run End WO's own close — ``complete_work_order``, the second copy of the
    remainder loop — for one order at the declared output."""
    with ExitStack() as stack:
        for p in factory.patches():
            stack.enter_context(p)
        mes_ops.complete_work_order(wo_name, good, reject)
    return factory.posted


def materials(entry):
    return {
        row["item_code"]: row["qty"]
        for row in entry.items
        if not row.get("is_finished_item") and not row.get("is_scrap_item")
    }


def finished(entry):
    return sum(row["qty"] for row in entry.items if row.get("is_finished_item"))


def coverage(factory, work_orders, good, reject=0.0):
    with ExitStack() as stack:
        for p in factory.patches():
            stack.enter_context(p)
        return mes_ops.get_close_production_coverage(
            work_orders, good, reject
        )


def without_the_ceiling():
    """mes_ops as it behaved before this change: the recipe is taken literally."""
    return patch.object(mes_ops, "_drawable_qty", return_value=None)


class TestTheSeptemberSeventeenthOutage(unittest.TestCase):
    """The reported failure, on a replica of the orders that produced it."""

    def test_the_run_reproduces_before_the_close(self):
        """The fixture is the real day, not an approximation: both
        semi-finished items are at zero when Close Production opens, because
        End WO consumed the whole charge against the plan of 150."""
        led = Factory().ledger

        self.assertEqual(led.balance("SFG10001", SEMI), 0.0)
        self.assertEqual(led.balance("SFG10002", SEMI), 0.0)
        self.assertEqual(led.consumed(FG_WO), {"SFG10001": 80.0, "SFG10002": 60.0})
        self.assertEqual(led.inflow(FG_WO, WIP), {"CR30003": 150.0, "PM40011": 10.5})

    def test_closing_at_153_used_to_be_refused_in_those_exact_words(self):
        """The screenshot, reproduced. 1.599 and not 1.6 because the shortfall
        is 80 x 153/150 - 80 == 1.5999999999999943 at the posting precision —
        which is how we know the demand came from rescaling the recipe."""
        self.assertEqual(
            mes_ops.truncate_qty(80.0 * 153.0 / 150.0 - 80.0), 1.599
        )

        with without_the_ceiling(), self.assertRaises(InsufficientStock) as caught:
            close_at(Factory(), 153.0)

        self.assertIn("1.599", str(caught.exception))
        self.assertIn("SFG10001", str(caught.exception))
        self.assertIn(SEMI, str(caught.exception))

    def test_closing_at_153_now_books_the_three_extra_cartons(self):
        """The whole point: the product that was made reaches stock. It comes
        out of the input that was actually used, so unit cost falls — which is
        what a yield gain is."""
        factory = Factory()
        entry = close_at(factory, 153.0)

        self.assertEqual(finished(entry), 153.0)
        self.assertEqual(factory.ledger.balance("FG10011", FG_WH), 153.0)
        # Exactly the real consumption: packaging as entered, and no
        # semi-finished row, because End WO already took the whole charge.
        self.assertEqual(materials(entry), {"CR30003": 155.0, "PM40011": 12.0})

    def test_the_shortfall_is_recorded_on_the_work_order_as_a_yield_gain(self):
        factory = Factory()
        close_at(factory, 153.0)

        comments = factory.work_orders[FG_WO].comments
        corn = next(c for c in comments if c.startswith("SFG10001"))
        self.assertIn("recipe 81.6 Kg", corn)
        self.assertIn("already consumed 80", corn)
        self.assertIn("short 1.599", corn)
        self.assertIn("yield gain", corn)
        self.assertIn("2.0%", corn)
        # Both semi-finished components are short, not only the one ERPNext
        # happened to reach first.
        self.assertTrue(any(c.startswith("SFG10002") and "short 1.2" in c
                            for c in comments))
        self.assertEqual(
            [log["title"] for log in factory.logged],
            ["Material Yield Variance", "Material Yield Variance"],
        )

    def test_the_workaround_still_behaves_exactly_as_it_did(self):
        """Closing at 150 is what the manager fell back to. Nothing about it
        changes, and nothing is reported, because nothing is short."""
        factory = Factory()
        entry = close_at(factory, 150.0)

        self.assertEqual(finished(entry), 150.0)
        self.assertEqual(materials(entry), {"CR30003": 155.0, "PM40011": 12.0})
        self.assertEqual(factory.logged, [])
        self.assertEqual(factory.work_orders[FG_WO].comments,
                         ["Production closed: Good=150.00, Rejects=0.00"])

    def test_150_closes_identically_with_and_without_the_ceiling(self):
        """Regression fence for every ordinary close on the site: when the
        material is there, the ceiling is not what decides anything."""
        with_ceiling = materials(close_at(Factory(), 150.0))
        with without_the_ceiling():
            without = materials(close_at(Factory(), 150.0))

        self.assertEqual(with_ceiling, without)


    def test_rejects_count_toward_the_material_the_close_must_cover(self):
        """148 good plus 5 rejected is still 153 units' worth of input, so the
        recipe is scaled by the throughput and the note names that figure —
        not the good quantity, which on its own is under the plan."""
        factory = Factory()
        entry = close_at(factory, 148.0, reject=5.0)

        self.assertEqual(finished(entry), 148.0)
        corn = next(c for c in factory.work_orders[FG_WO].comments
                    if c.startswith("SFG10001"))
        self.assertIn("recipe 81.6 Kg", corn)
        self.assertIn("short 1.599", corn)
        self.assertIn("Output of 153", corn)

    def test_every_short_material_is_reported_not_just_the_first(self):
        """ERPNext stopped at whichever row it reached first, which is why the
        manager only ever saw CORN MIX 1. Both were short."""
        factory = Factory()
        close_at(factory, 153.0)

        reported = [c.split(":")[0] for c in factory.work_orders[FG_WO].comments
                    if ": recipe " in c]
        self.assertEqual(sorted(reported), ["SFG10001", "SFG10002"])


class TestTheDialogWarnsFirst(unittest.TestCase):
    """The operator should learn this before pressing the button, not after."""

    def test_the_preview_names_both_shortfalls_and_the_over_run(self):
        data = coverage(Factory(), [FG_WO], 153.0)

        self.assertEqual(data["planned_qty"], 150.0)
        self.assertEqual(data["output_qty"], 153.0)
        self.assertEqual(data["over_qty"], 3.0)
        self.assertEqual(data["refused"], [])

        short = {row["item_code"]: row["short_qty"] for row in data["short"]}
        self.assertEqual(sorted(short), ["SFG10001", "SFG10002"])
        self.assertEqual(short["SFG10001"], 1.599)
        self.assertEqual(short["SFG10002"], 1.2)
        self.assertEqual(data["short"][0]["source_warehouse"], SEMI)

    def test_the_preview_cannot_disagree_with_the_close(self):
        """Both read the same plan. A warning that differed from the outcome
        would be worse than no warning at all."""
        previewed = {row["item_code"]: row["short_qty"]
                     for row in coverage(Factory(), [FG_WO], 153.0)["short"]}

        factory = Factory()
        close_at(factory, 153.0)
        recorded = {}
        for comment in factory.work_orders[FG_WO].comments:
            if ": recipe " not in comment:
                continue
            item = comment.split(":")[0]
            recorded[item] = float(comment.split("short ")[1].split(" ")[0])

        self.assertEqual(previewed, recorded)

    def test_nothing_is_said_when_the_output_fits(self):
        data = coverage(Factory(), [FG_WO], 150.0)

        self.assertEqual(data["short"], [])
        self.assertEqual(data["over_qty"], 0.0)

    def test_an_over_run_the_material_covers_is_reported_without_a_shortfall(self):
        """A quantity over the plan is not a problem in itself — the dialog
        only has something to explain when the material is not there."""
        led = production_day()
        led.seed(SEMI, SFG10001=50.0, SFG10002=50.0)   # plenty left over

        data = coverage(Factory(ledger=led), [FG_WO], 153.0)
        self.assertEqual(data["short"], [])
        self.assertEqual(data["over_qty"], 3.0)

    def test_output_beyond_the_allowance_is_named_rather_than_priced(self):
        """166 is past 150 + 10%. The close would refuse the output outright,
        so reporting material for it would be answering the wrong question."""
        data = coverage(Factory(), [FG_WO], 166.0)

        self.assertEqual(data["refused"], [FG_WO])
        self.assertEqual(data["short"], [])

    def test_the_preview_is_silent_on_an_empty_or_zero_entry(self):
        factory = Factory()
        self.assertEqual(coverage(factory, [], 153.0)["rows"], [])
        self.assertEqual(coverage(factory, [FG_WO], 0.0)["rows"], [])


class TestTheSemiFinishedOrdersToo(unittest.TestCase):
    """The same arithmetic sits on the raw-material side of an SFG order, where
    the shortfall is drawn from WIP instead of Semi-finished."""

    def _corn_ready_to_close(self):
        """MFG-WO-2026-00072 up to End WO: 80 Kg of corn transferred and
        consumed, water likewise, nothing left in WIP."""
        led = Ledger()
        led.seed(STORES, RM20022=500.0, RM20023=900.0)
        led.post("Material Transfer for Manufacture", CORN_WO, [
            {"item_code": "RM20022", "qty": 80.0, "s_warehouse": STORES, "t_warehouse": WIP},
            {"item_code": "RM20023", "qty": 2.667, "s_warehouse": STORES, "t_warehouse": WIP},
        ], fg_qty=80.0)
        led.post("Material Consumption for Manufacture", CORN_WO, [
            {"item_code": "RM20022", "qty": 80.0, "s_warehouse": WIP, "t_warehouse": None},
            {"item_code": "RM20023", "qty": 2.667, "s_warehouse": WIP, "t_warehouse": None},
        ], fg_qty=80.0)
        return led

    def test_corn_mix_over_yield_used_to_demand_corn_that_was_gone(self):
        with without_the_ceiling(), self.assertRaises(InsufficientStock) as caught:
            close_at(Factory(ledger=self._corn_ready_to_close()), 82.0,
                     packaging=[], wo_name=CORN_WO, batch=None)

        self.assertIn("RM20022", str(caught.exception))
        self.assertIn(WIP, str(caught.exception))

    def test_corn_mix_over_yield_now_closes_on_what_was_used(self):
        factory = Factory(ledger=self._corn_ready_to_close())
        entry = close_at(factory, 82.0, packaging=[], wo_name=CORN_WO, batch=None)

        self.assertEqual(finished(entry), 82.0)
        self.assertEqual(materials(entry), {})
        corn = next(c for c in factory.work_orders[CORN_WO].comments
                    if c.startswith("RM20022"))
        self.assertIn("short 2", corn)
        self.assertIn("yield gain", corn)

    def test_an_order_may_still_draw_what_it_did_bring_into_wip(self):
        """The ceiling is what this order has, not zero: material transferred
        and not yet scanned is still consumed at close, as it always was."""
        led = Ledger()
        led.seed(STORES, RM20022=500.0, RM20023=900.0)
        led.post("Material Transfer for Manufacture", CORN_WO, [
            {"item_code": "RM20022", "qty": 80.0, "s_warehouse": STORES, "t_warehouse": WIP},
            {"item_code": "RM20023", "qty": 2.667, "s_warehouse": STORES, "t_warehouse": WIP},
        ], fg_qty=80.0)

        factory = Factory(ledger=led)
        entry = close_at(factory, 80.0, packaging=[], wo_name=CORN_WO, batch=None)

        self.assertEqual(materials(entry)["RM20022"], 80.0)
        self.assertEqual(factory.logged, [])

    def test_one_order_cannot_close_onto_another_orders_material(self):
        """WIP is shared. The slurry order's material is sitting in the same
        warehouse, and the corn order's close must not reach for it."""
        led = Ledger()
        led.seed(STORES, RM20022=500.0, RM20023=900.0)
        led.post("Material Transfer for Manufacture", CORN_WO, [
            {"item_code": "RM20022", "qty": 30.0, "s_warehouse": STORES, "t_warehouse": WIP},
            {"item_code": "RM20023", "qty": 2.667, "s_warehouse": STORES, "t_warehouse": WIP},
        ], fg_qty=80.0)
        led.post("Material Transfer for Manufacture", SLURRY_WO, [
            {"item_code": "RM20022", "qty": 50.0, "s_warehouse": STORES, "t_warehouse": WIP},
        ], fg_qty=60.0)

        factory = Factory(ledger=led)
        entry = close_at(factory, 80.0, packaging=[], wo_name=CORN_WO, batch=None)

        self.assertEqual(materials(entry)["RM20022"], 30.0)
        self.assertEqual(factory.ledger.balance("RM20022", WIP), 50.0)
        corn = next(c for c in factory.work_orders[CORN_WO].comments
                    if c.startswith("RM20022"))
        self.assertIn("short 50", corn)


class TestMaterialTheOrderGaveBack(unittest.TestCase):
    """A return leaves the order with less than it brought in, and the ceiling
    has to know that — otherwise it licenses the close to take the difference
    out of whatever else is sitting in the shared WIP."""

    def _returned_thirty(self):
        led = Ledger()
        led.seed(STORES, RM20022=500.0, RM20023=900.0)
        led.post("Material Transfer for Manufacture", CORN_WO, [
            {"item_code": "RM20022", "qty": 80.0, "s_warehouse": STORES, "t_warehouse": WIP},
            {"item_code": "RM20023", "qty": 2.667, "s_warehouse": STORES, "t_warehouse": WIP},
        ], fg_qty=80.0)
        # The operator sent 30 Kg back to staging (return_materials posts a
        # Material Transfer out of WIP under this Work Order's name).
        led.post("Material Transfer", CORN_WO, [
            {"item_code": "RM20022", "qty": 30.0, "s_warehouse": WIP, "t_warehouse": STAGING},
        ])
        # Another order then staged its own 30 Kg into the same WIP.
        led.post("Material Transfer for Manufacture", SLURRY_WO, [
            {"item_code": "RM20022", "qty": 30.0, "s_warehouse": STORES, "t_warehouse": WIP},
        ], fg_qty=60.0)
        return led

    def test_a_return_comes_off_the_ceiling(self):
        """80 in, 30 back, nothing consumed: this order is entitled to 50, not
        to the 80 the warehouse happens to hold."""
        led = self._returned_thirty()
        self.assertEqual(led.balance("RM20022", WIP), 80.0)

        factory = Factory(ledger=led)
        entry = close_at(factory, 80.0, packaging=[], wo_name=CORN_WO, batch=None)

        self.assertEqual(materials(entry)["RM20022"], 50.0)
        # The other order's 30 Kg is still there.
        self.assertEqual(factory.ledger.balance("RM20022", WIP), 30.0)

    def test_a_consumption_is_not_counted_twice_alongside_a_return(self):
        """Consumption reaches the ceiling through Material Consumption for
        Manufacture and the return through the transfer out; counting the
        consumption in both would leave the order entitled to less than it
        has."""
        led = Ledger()
        led.seed(STORES, RM20022=500.0, RM20023=900.0)
        led.post("Material Transfer for Manufacture", CORN_WO, [
            {"item_code": "RM20022", "qty": 80.0, "s_warehouse": STORES, "t_warehouse": WIP},
            {"item_code": "RM20023", "qty": 2.667, "s_warehouse": STORES, "t_warehouse": WIP},
        ], fg_qty=80.0)
        led.post("Material Consumption for Manufacture", CORN_WO, [
            {"item_code": "RM20022", "qty": 20.0, "s_warehouse": WIP, "t_warehouse": None},
        ], fg_qty=80.0)
        led.post("Material Transfer", CORN_WO, [
            {"item_code": "RM20022", "qty": 30.0, "s_warehouse": WIP, "t_warehouse": STAGING},
        ])

        factory = Factory(ledger=led)
        entry = close_at(factory, 80.0, packaging=[], wo_name=CORN_WO, batch=None)

        # 80 in, 20 consumed, 30 returned: 30 left, and the recipe still wants
        # the 60 that was never consumed.
        self.assertEqual(materials(entry)["RM20022"], 30.0)
        corn = next(c for c in factory.work_orders[CORN_WO].comments
                    if c.startswith("RM20022"))
        self.assertIn("short 30", corn)

    def test_end_wo_applies_the_same_ceiling(self):
        """complete_work_order runs its own copy of the remainder loop. The two
        must not drift, least of all on which material an order may claim."""
        factory = Factory(ledger=self._returned_thirty())
        entry = complete_at(factory, 80.0)

        self.assertEqual(materials(entry)["RM20022"], 50.0)
        self.assertEqual(factory.ledger.balance("RM20022", WIP), 30.0)
        corn = next(c for c in factory.work_orders[CORN_WO].comments
                    if c.startswith("RM20022"))
        self.assertIn("short 30", corn)

    def test_the_returned_quantity_is_reported_as_short(self):
        factory = Factory(ledger=self._returned_thirty())
        close_at(factory, 80.0, packaging=[], wo_name=CORN_WO, batch=None)

        corn = next(c for c in factory.work_orders[CORN_WO].comments
                    if c.startswith("RM20022"))
        self.assertIn("short 30", corn)


class TestPreviewingSeveralOrdersAtOnce(unittest.TestCase):
    """Close Production closes the orders one after another, each posting
    before the next is planned. The dialog previews them all against a single
    snapshot, so it has to do that decrementing itself or it promises the same
    kilo twice."""

    def _two_orders_one_charge(self):
        """Two 150-carton orders of the same product, with only one order's
        worth of semi-finished in the warehouse."""
        led = Ledger()
        led.seed(STORES, CR30003=2000.0, PM40011=200.0)
        led.seed(SEMI, SFG10001=80.0, SFG10002=60.0)
        work_orders = _fresh_work_orders()
        work_orders["MFG-WO-2026-00074"] = WorkOrder(
            "MFG-WO-2026-00074", "FG10011", "BOM-FG10011-002", 150.0, FG_WH,
            {"SFG10001": 80.0, "SFG10002": 60.0, "PM40011": 10.5, "CR30003": 150.0},
        )
        return Factory(ledger=led, work_orders=work_orders)

    def test_the_second_order_is_not_promised_the_first_orders_material(self):
        factory = self._two_orders_one_charge()
        data = coverage(factory, [FG_WO, "MFG-WO-2026-00074"], 300.0)

        short = {row["item_code"]: row["short_qty"] for row in data["short"]}
        # 160 Kg of corn mix is wanted across the two orders and 80 is there.
        self.assertEqual(short.get("SFG10001"), 80.0)
        self.assertEqual(short.get("SFG10002"), 60.0)

    def test_one_order_on_its_own_is_still_fully_covered(self):
        """The running deduction must not invent a shortage that is not there."""
        factory = self._two_orders_one_charge()
        data = coverage(factory, [FG_WO], 150.0)

        self.assertEqual(data["short"], [])


class TestWhenTheOutputDidNotExceedThePlan(unittest.TestCase):
    """A shortfall with no over-run is a different story and says so."""

    def test_it_is_reported_as_a_ledger_gap_not_a_yield_gain(self):
        led = Ledger()
        led.seed(STORES, RM20022=500.0, RM20023=900.0)
        led.post("Material Transfer for Manufacture", CORN_WO, [
            {"item_code": "RM20022", "qty": 60.0, "s_warehouse": STORES, "t_warehouse": WIP},
            {"item_code": "RM20023", "qty": 2.667, "s_warehouse": STORES, "t_warehouse": WIP},
        ], fg_qty=80.0)

        factory = Factory(ledger=led)
        close_at(factory, 80.0, packaging=[], wo_name=CORN_WO, batch=None)

        corn = next(c for c in factory.work_orders[CORN_WO].comments
                    if c.startswith("RM20022"))
        self.assertIn("short 20", corn)
        self.assertNotIn("yield gain", corn)
        self.assertIn("worth checking", corn)

    def test_the_close_still_goes_through(self):
        """Stranding a finished batch on the line over a stock discrepancy
        helps nobody; the discrepancy is recorded instead."""
        led = Ledger()
        led.seed(STORES, RM20022=500.0, RM20023=900.0)
        led.post("Material Transfer for Manufacture", CORN_WO, [
            {"item_code": "RM20022", "qty": 60.0, "s_warehouse": STORES, "t_warehouse": WIP},
            {"item_code": "RM20023", "qty": 2.667, "s_warehouse": STORES, "t_warehouse": WIP},
        ], fg_qty=80.0)

        factory = Factory(ledger=led)
        entry = close_at(factory, 80.0, packaging=[], wo_name=CORN_WO, batch=None)

        self.assertEqual(finished(entry), 80.0)
        self.assertEqual(materials(entry)["RM20022"], 60.0)


if __name__ == "__main__":
    unittest.main()
