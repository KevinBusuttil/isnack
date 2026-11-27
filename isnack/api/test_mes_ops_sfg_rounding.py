# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""A finished-good order must not be refused over a gram that was never made.

On 2026-11-27 MFG-WO-2026-00036 (500 cartons of FG10019) could not be ended.
Its Production Plan had split the 266.666666667 Kg of CORN MIX 1 it needs into
two Work Orders, 160 and 106.666666667 Kg. A Work Order's output is received
truncated to the posting precision, because with no over-production allowance
ERPNext refuses anything above the order, so 160 + 106.666 = 266.666 Kg was
made — while the Work Order showed the requirement as 266.667. The operator
typed that, and End WO answered:

    Insufficient semi-finished stock:
    Corn Mix 1 (SFG10001): 266.667 entered, 266.666 available in Semi-finished - ISN.

Getting the figure past that guard would not have helped: ERPNext refuses the
row for the same gram ("0.001 units of Item SFG10001: Corn Mix 1 needed in
Warehouse Semi-finished - ISN to complete this transaction."). So a figure no
more than one posting tick above the balance now consumes what is there, the
Work Order is told, and the dialog stops calling that tick a shortage. Anything
short by more is refused exactly as before.

(The stock was also in the wrong warehouse that day. That was a line set on the
BOM and is not what these tests are about.)
"""

import json
import math
import random
import unittest
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import frappe

import isnack.api.mes_ops as mes_ops
from isnack.api.mes_ops import _sfg_qty_within_stock
from isnack.utils.qty import postable_qty, qty_tick, truncate_qty

WO = "MFG-WO-2026-00036"
CORN_MIX = "SFG10001"
SLURRY = "SFG10002"
SFG_WH = "Semi-finished - ISN"
WIP = "EXT1-WIP - ISN"

# MFG-WO-2026-00036, from the production export.
REQUIRED = 266.666666667
ENTERED = 266.667          # REQUIRED as the Work Order shows it (the dialog: 266.6667)
MADE = 266.666             # 160 + 106.666, what the two Work Orders received

_real_system_settings = frappe.get_system_settings


def setUpModule():
    # bench run-tests clears the cache first; load these before any patch is
    # active so nothing below ever has to read them through one.
    frappe.get_meta("Stock Entry Detail")
    frappe.get_system_settings("rounding_method")


def at_precision(precision):
    return patch.object(frappe, "get_precision", return_value=precision)


def rounding(method):
    """Pin System Settings' rounding method, which flt reads on every call."""
    return patch.object(
        frappe, "get_system_settings",
        side_effect=lambda key, *a, **k: method if key == "rounding_method" else _real_system_settings(key, *a, **k),
    )


class TestSfgQtyWithinStock(unittest.TestCase):
    """The rule on its own: one tick above the balance takes the balance."""

    def test_the_reported_figure_takes_what_was_made(self):
        with at_precision(3):
            self.assertEqual(_sfg_qty_within_stock(ENTERED, MADE), MADE)

    def test_stock_that_covers_the_figure_leaves_it_alone(self):
        with at_precision(3):
            for available in (ENTERED, 266.668, 300.0, 1e6):
                self.assertEqual(_sfg_qty_within_stock(ENTERED, available), ENTERED)

    def test_two_ticks_short_is_a_shortage_and_comes_back_as_asked(self):
        """The caller refuses it; this only decides what a tick is."""
        with at_precision(3):
            self.assertEqual(_sfg_qty_within_stock(ENTERED, 266.665), ENTERED)
            self.assertEqual(_sfg_qty_within_stock(ENTERED, 0.0), ENTERED)

    def test_float_noise_does_not_turn_one_tick_into_two(self):
        """0.3 - 0.299 is 0.0010000000000000009, which is more than 0.001 to a
        float and exactly one tick to the ledger."""
        self.assertGreater(0.3 - 0.299, 0.001)
        with at_precision(3):
            self.assertEqual(_sfg_qty_within_stock(0.3, 0.299), 0.299)
            for n in range(0, 5000):
                available = n / 1000
                one_up, two_up = (n + 1) / 1000, (n + 2) / 1000
                self.assertEqual(_sfg_qty_within_stock(one_up, available), available, (one_up, available))
                self.assertEqual(_sfg_qty_within_stock(two_up, available), two_up, (two_up, available))

    def test_one_tick_asked_of_an_empty_warehouse_consumes_nothing(self):
        """An order ended at 266.666, reopened and ended again at 266.667 asks
        for 0.001 that is not there."""
        with at_precision(3):
            self.assertEqual(_sfg_qty_within_stock(0.001, 0.0), 0.0)

    def test_a_balance_below_the_posting_precision_is_not_stock(self):
        """Only whole ticks can be posted, so only whole ticks are taken."""
        with at_precision(3):
            self.assertEqual(_sfg_qty_within_stock(0.001, 0.0004), 0.0)
            self.assertEqual(_sfg_qty_within_stock(5.0, 4.9995), 4.999)
            self.assertEqual(_sfg_qty_within_stock(ENTERED, 266.6664), MADE)

    def test_a_negative_balance_is_a_real_shortage_and_never_a_negative_quantity(self):
        with at_precision(3):
            self.assertEqual(_sfg_qty_within_stock(0.001, -5.0), 0.001)
            self.assertEqual(_sfg_qty_within_stock(ENTERED, -MADE), ENTERED)
            self.assertEqual(_sfg_qty_within_stock(0.0, -0.001), 0.0)

    def test_what_the_guard_already_let_through_is_not_touched(self):
        """A balance within QTY_EPSILON of the figure passed before and is
        posted as entered, as before."""
        with at_precision(3):
            self.assertEqual(_sfg_qty_within_stock(ENTERED, 266.66695), ENTERED)

    def test_a_figure_typed_past_the_precision_is_read_as_erpnext_posts_it(self):
        """266.6667 is posted as 266.667 — one tick over; 266.6676 as 266.668 —
        two. At a half tick the site's rounding decides: under Banker's
        rounding 10.0005 is posted as 10.0, one tick over 9.999, and 394.4355 as
        394.436, two over 394.434."""
        with at_precision(3):
            self.assertEqual(_sfg_qty_within_stock(266.6667, MADE), MADE)
            self.assertEqual(_sfg_qty_within_stock(266.6676, MADE), 266.6676)
            with rounding("Banker's Rounding"):
                self.assertEqual(_sfg_qty_within_stock(10.0005, 9.999), 9.999)
                self.assertEqual(_sfg_qty_within_stock(394.4355, 394.4349), 394.4355)

    def test_the_tick_follows_the_site_precision(self):
        with at_precision(2):
            self.assertEqual(_sfg_qty_within_stock(10.01, 10.0), 10.0)
            self.assertEqual(_sfg_qty_within_stock(10.02, 10.0), 10.02)
        with at_precision(6):
            # A gram is a thousand ticks at six places: a shortage, not rounding.
            self.assertEqual(_sfg_qty_within_stock(ENTERED, MADE), ENTERED)

    def test_at_four_places_it_takes_the_ticks_float_noise_put_past_the_guard(self):
        """A tick equals QTY_EPSILON there, so whether the guard lets a one-tick
        figure through is float noise. 10.0001 against 10.0 passes and is left
        as typed (ERPNext's own 0.0001 tolerance posts it); 266.6603 against
        266.6602 used to be refused, and is now taken down to the balance."""
        with at_precision(4):
            self.assertEqual(_sfg_qty_within_stock(10.0001, 10.0), 10.0001)
            self.assertEqual(_sfg_qty_within_stock(266.6603, 266.6602), 266.6602)

    def test_from_five_places_up_the_guard_already_lets_a_tick_through(self):
        """A tick is then a tenth of QTY_EPSILON or less, so the figure is left
        as it is, as it always was there."""
        with at_precision(5):
            self.assertEqual(_sfg_qty_within_stock(266.66603, 266.66602), 266.66603)
        with at_precision(6):
            self.assertEqual(_sfg_qty_within_stock(10.000001, 10.0), 10.000001)

    def test_it_takes_only_a_tick_never_more_and_never_more_than_is_there(self):
        rng = random.Random(36)
        with at_precision(3):
            for _ in range(20000):
                qty = round(rng.uniform(0.001, 400), rng.choice((3, 3, 3, 4, 6)))
                available = round(qty + rng.uniform(-0.004, 0.004), rng.choice((3, 3, 3, 4, 6)))
                take = _sfg_qty_within_stock(qty, available)
                case = (qty, available)
                self.assertLessEqual(take, qty, case)
                if take != qty:
                    self.assertGreaterEqual(take, 0.0, case)
                    self.assertLessEqual(take, max(available, 0.0), case)
                    # The figure ERPNext would post is at most one tick above
                    # what the warehouse can give, measured on the posting grid.
                    self.assertLessEqual(postable_qty(postable_qty(qty) - truncate_qty(available)),
                                         qty_tick(), case)

    def test_a_figure_that_is_not_a_finite_number_is_not_a_tick(self):
        """Under Banker's rounding flt answers 0.0 for these at the posting
        precision; read as a gap of nothing they would have taken the whole
        balance."""
        with at_precision(3):
            for junk in (float("inf"), 1e306, 1e308):
                self.assertEqual(_sfg_qty_within_stock(junk, MADE), junk, junk)
            self.assertTrue(math.isnan(_sfg_qty_within_stock(float("nan"), MADE)))

    def test_a_balance_that_could_not_be_read_rounds_nothing(self):
        with at_precision(3):
            self.assertEqual(_sfg_qty_within_stock(0.001, None), 0.001)
            self.assertEqual(_sfg_qty_within_stock(ENTERED, None), ENTERED)
            for junk in (float("nan"), float("-inf")):
                self.assertEqual(_sfg_qty_within_stock(0.001, junk), 0.001, junk)

    def test_qty_epsilon_is_not_what_was_widened(self):
        """It serves as a float-comparison tolerance in eighteen other places in
        mes_ops, several of them guards."""
        self.assertEqual(mes_ops.QTY_EPSILON, 0.0001)


UNREADABLE = object()


def ledger(stock):
    """erpnext.stock.utils.get_stock_balance over ``stock`` ({item_code:
    balance}), all of it held in the semi-finished warehouse; UNREADABLE makes
    the read fail the way a permission check does.

    Patched there rather than replacing _sfg_available_qty, so the real reader
    runs in every test below, with the warehouse it is asked for."""

    def get_stock_balance(item_code, warehouse, *args, **kwargs):
        balance = stock.get(item_code, 0.0) if warehouse == SFG_WH else 0.0
        if balance is UNREADABLE:
            raise frappe.PermissionError("No permission for Item")
        return balance

    return get_stock_balance


def holding(stock):
    return patch("erpnext.stock.utils.get_stock_balance", side_effect=ledger(stock))


class TestReadingTheBalance(unittest.TestCase):
    """How the reader answers when there is nothing to read decides whether
    the rounding may act."""

    def read(self, stock, warehouse=SFG_WH, **kwargs):
        with holding(stock):
            return mes_ops._sfg_available_qty(CORN_MIX, warehouse, **kwargs)

    def test_a_balance_is_read(self):
        self.assertEqual(self.read({CORN_MIX: MADE}), MADE)
        self.assertEqual(self.read({CORN_MIX: MADE}, unreadable=None), MADE)

    def test_a_failed_read_is_an_empty_warehouse_to_the_guard_and_the_dialog(self):
        """As it always was."""
        self.assertEqual(self.read({CORN_MIX: UNREADABLE}), 0.0)

    def test_a_failed_read_is_nothing_to_round_against(self):
        self.assertIsNone(self.read({CORN_MIX: UNREADABLE}, unreadable=None))

    def test_no_warehouse_is_the_same(self):
        self.assertEqual(self.read({CORN_MIX: MADE}, warehouse=None), 0.0)
        self.assertIsNone(self.read({CORN_MIX: MADE}, warehouse=None, unreadable=None))


class FakeStockEntry:
    def __init__(self):
        self.items = []
        self.flags = MagicMock()
        self.inserted = self.submitted = False

    def append(self, _table, row):
        self.items.append(row)

    def insert(self):
        self.inserted = True

    def submit(self):
        self.submitted = True


class WorkOrderStub:
    def __init__(self):
        self.name = WO
        self.status = "In Process"
        self.custom_production_ended = 0
        self.qty = 500.0
        self.production_item = "FG10019"
        self.company = "Isnack"
        self.bom_no = "BOM-FG10019-001"
        self.comments = []
        self.db_set = MagicMock()

    def get(self, field, default=None):
        return getattr(self, field, default)

    def add_comment(self, _kind, text):
        self.comments.append(text)


def item_lookup(doctype, name=None, fieldname="name", *args, **kwargs):
    if doctype == "Item" and fieldname == "stock_uom":
        return "Kg"
    if doctype == "Item" and fieldname == "item_name":
        return {CORN_MIX: "Corn Mix 1", SLURRY: "SMOKEY SLURRY"}.get(name, name)
    if doctype == "Work Order" and fieldname == "actual_start_date":
        return "2026-11-27 13:46:01"
    raise AssertionError(f"unexpected lookup {doctype} {name} {fieldname}")


def post(rows, stock, in_bom=True, wo=None, sfg_warehouse=SFG_WH):
    """Run _post_sfg_consumption against ``stock`` ({item_code: balance}).

    Returns (the Stock Entry it built, the Work Order, the exception it raised
    or None)."""
    wo, se = wo or WorkOrderStub(), FakeStockEntry()
    with patch.object(mes_ops, "_default_line_wip", return_value=WIP), \
            patch.object(mes_ops, "_default_sfg_source", return_value=sfg_warehouse), \
            holding(stock), \
            patch.object(mes_ops, "_pending_sfg_work_orders", return_value=[]), \
            patch.object(mes_ops, "_validate_item_in_bom",
                         return_value=(in_bom, "OK" if in_bom else "Item not in BOM")), \
            patch.object(mes_ops.frappe.db, "get_value", side_effect=item_lookup), \
            patch.object(mes_ops.frappe, "new_doc", return_value=se), \
            at_precision(3):
        try:
            mes_ops._post_sfg_consumption(wo, rows, 500.0)
            raised = None
        except Exception as e:
            raised = e
    return se, wo, raised


class TestEndWoConsumesWhatIsThere(unittest.TestCase):
    def test_the_reported_order_is_no_longer_refused(self):
        se, wo, raised = post([{"item_code": CORN_MIX, "qty": ENTERED}], {CORN_MIX: MADE})

        self.assertIsNone(raised)
        self.assertEqual([(r["item_code"], r["qty"], r["s_warehouse"], r["t_warehouse"]) for r in se.items],
                         [(CORN_MIX, MADE, SFG_WH, WIP)])
        self.assertTrue(se.inserted and se.submitted)

    def test_the_work_order_is_told_what_was_entered_and_what_was_consumed(self):
        _se, wo, _raised = post([{"item_code": CORN_MIX, "qty": ENTERED}], {CORN_MIX: MADE})

        self.assertEqual(len(wo.comments), 1)
        self.assertTrue(wo.comments[0].startswith("Semi-finished usage rounded to stock"))
        self.assertIn("SFG10001: 266.667 to consume, 266.666 in Semi-finished - ISN, 266.666 consumed",
                      wo.comments[0])
        self.assertIn("one posting unit (0.001)", wo.comments[0])

    def test_the_note_shows_the_tick_on_a_quantity_in_the_thousands(self):
        """``:g`` keeps six significant digits and would print 1266.667 and
        1266.666 alike — the one difference the note is there to record."""
        cases = (
            (1266.667, 1266.666, "1266.667 to consume, 1266.666 in Semi-finished - ISN, 1266.666 consumed"),
            (12000.001, 12000.0, "12000.001 to consume, 12000 in Semi-finished - ISN, 12000 consumed"),
            (1234567.891, 1234567.89, "1234567.891 to consume, 1234567.89 in Semi-finished - ISN, 1234567.89 consumed"),
        )
        for asked, held, shown in cases:
            _se, wo, _raised = post([{"item_code": CORN_MIX, "qty": asked}], {CORN_MIX: held})

            self.assertIn("SFG10001: " + shown, wo.comments[0])

    def test_the_note_shows_the_balance_the_rule_used(self):
        """A balance off the posting grid is shown as what can be posted of it,
        so the note does not read as if stock covered the request."""
        _se, wo, _raised = post([{"item_code": CORN_MIX, "qty": 5.0}], {CORN_MIX: 4.9995})

        self.assertIn("SFG10001: 5 to consume, 4.999 in Semi-finished - ISN, 4.999 consumed", wo.comments[0])

    def test_two_items_rounded_together_are_both_noted(self):
        se, wo, raised = post([{"item_code": CORN_MIX, "qty": ENTERED}, {"item_code": SLURRY, "qty": 200.001}],
                              {CORN_MIX: MADE, SLURRY: 200.0})

        self.assertIsNone(raised)
        self.assertEqual([(r["item_code"], r["qty"]) for r in se.items], [(CORN_MIX, MADE), (SLURRY, 200.0)])
        self.assertEqual(len(wo.comments), 1)
        self.assertIn("SFG10001: 266.667 to consume, 266.666 in Semi-finished - ISN, 266.666 consumed",
                      wo.comments[0])
        self.assertIn("SFG10002: 200.001 to consume, 200 in Semi-finished - ISN, 200 consumed", wo.comments[0])

    def test_a_note_that_cannot_be_written_does_not_stop_the_consumption_entry(self):
        wo = WorkOrderStub()
        wo.add_comment = MagicMock(side_effect=RuntimeError("comment table is locked"))
        se, _wo, raised = post([{"item_code": CORN_MIX, "qty": ENTERED}], {CORN_MIX: MADE}, wo=wo)

        self.assertIsNone(raised)
        self.assertEqual([r["qty"] for r in se.items], [MADE])
        self.assertTrue(se.submitted)

    def test_a_deadlock_writing_the_note_is_not_swallowed(self):
        """The database has rolled the transaction back by then; posting on
        would book the consumption without what the request did before it."""
        wo = WorkOrderStub()
        wo.add_comment = MagicMock(side_effect=frappe.QueryDeadlockError("Deadlock found"))
        se, _wo, raised = post([{"item_code": CORN_MIX, "qty": ENTERED}], {CORN_MIX: MADE}, wo=wo)

        self.assertIsInstance(raised, frappe.QueryDeadlockError)
        self.assertFalse(se.inserted or se.submitted)

    def test_a_figure_typed_past_the_precision_is_noted_as_typed(self):
        """Only a direct call can send one; End WO rounds what it hands over."""
        se, wo, raised = post([{"item_code": CORN_MIX, "qty": 266.6664}], {CORN_MIX: MADE})

        self.assertIsNone(raised)
        self.assertEqual([r["qty"] for r in se.items], [MADE])
        self.assertIn("SFG10001: 266.6664 to consume, 266.666 in Semi-finished - ISN, 266.666 consumed",
                      wo.comments[0])

    def test_a_figure_that_is_not_a_finite_number_is_refused_and_nothing_is_posted(self):
        """What it was before: the guard refuses it. It must not be read as a
        tick and take the whole balance."""
        for junk in ("inf", "Infinity", 1e306):
            se, wo, raised = post([{"item_code": CORN_MIX, "qty": junk}], {CORN_MIX: MADE})

            self.assertIsInstance(raised, frappe.ValidationError, junk)
            self.assertIn("Insufficient semi-finished stock:", str(raised))
            self.assertEqual((se.items, se.inserted, wo.comments), ([], False, []), junk)

    def test_a_balance_that_could_not_be_read_is_refused_as_before(self):
        """The read used to answer 0.0 and the guard refused; one tick asked of
        a balance nobody saw must not now pass with nothing consumed."""
        se, wo, raised = post([{"item_code": CORN_MIX, "qty": 0.001}], {CORN_MIX: UNREADABLE})

        self.assertIsInstance(raised, frappe.ValidationError)
        self.assertIn("Corn Mix 1 (SFG10001): 0.001 entered, 0.0 available in Semi-finished - ISN.", str(raised))
        self.assertEqual((se.inserted, wo.comments), (False, []))

    def test_no_semi_finished_warehouse_to_read_is_refused_as_before(self):
        se, wo, raised = post([{"item_code": CORN_MIX, "qty": 0.001}], {CORN_MIX: MADE}, sfg_warehouse=None)

        self.assertIsInstance(raised, frappe.ValidationError)
        self.assertIn("0.001 entered, 0.0 available", str(raised))
        self.assertEqual((se.inserted, wo.comments), (False, []))

    def test_an_item_off_the_bom_is_refused_even_with_nothing_left_to_consume(self):
        se, wo, raised = post([{"item_code": CORN_MIX, "qty": 0.001}], {CORN_MIX: 0.0}, in_bom=False)

        self.assertIsInstance(raised, frappe.ValidationError)
        self.assertIn("Item not in BOM", str(raised))
        self.assertEqual((se.inserted, wo.comments), (False, []))

    def test_two_ticks_short_is_refused_in_the_words_it_always_was(self):
        se, wo, raised = post([{"item_code": CORN_MIX, "qty": ENTERED}], {CORN_MIX: 266.665})

        self.assertIsInstance(raised, frappe.ValidationError)
        self.assertIn("Insufficient semi-finished stock:", str(raised))
        self.assertIn("Corn Mix 1 (SFG10001): 266.667 entered, 266.665 available in Semi-finished - ISN.",
                      str(raised))
        self.assertFalse(se.inserted or se.submitted)
        self.assertEqual(wo.comments, [])

    def test_stock_that_covers_the_figure_is_consumed_as_entered_and_nothing_is_said(self):
        se, wo, raised = post([{"item_code": CORN_MIX, "qty": ENTERED}], {CORN_MIX: 300.0})

        self.assertIsNone(raised)
        self.assertEqual([r["qty"] for r in se.items], [ENTERED])
        self.assertEqual(wo.comments, [])

    def test_the_tick_alone_from_an_empty_warehouse_posts_no_entry(self):
        """Ended at 266.666, undone, ended again at 266.667: the 0.001 left to
        consume is not there and never was. Nothing is posted and nothing is
        thrown — an entry with no rows would be refused by ERPNext."""
        se, wo, raised = post([{"item_code": CORN_MIX, "qty": 0.001}], {CORN_MIX: 0.0})

        self.assertIsNone(raised)
        self.assertEqual(se.items, [])
        self.assertFalse(se.inserted or se.submitted)
        self.assertIn("SFG10001: 0.001 to consume, 0 in Semi-finished - ISN, 0 consumed", wo.comments[0])

    def test_one_item_is_rounded_and_the_other_left_alone(self):
        se, wo, raised = post([{"item_code": CORN_MIX, "qty": ENTERED}, {"item_code": SLURRY, "qty": 200}],
                              {CORN_MIX: MADE, SLURRY: 200.0})

        self.assertIsNone(raised)
        self.assertEqual([(r["item_code"], r["qty"]) for r in se.items], [(CORN_MIX, MADE), (SLURRY, 200.0)])
        self.assertNotIn(SLURRY, wo.comments[0])

    def test_a_real_shortage_beside_a_rounding_tick_still_refuses_and_names_only_the_shortage(self):
        se, wo, raised = post([{"item_code": CORN_MIX, "qty": ENTERED}, {"item_code": SLURRY, "qty": 200}],
                              {CORN_MIX: MADE, SLURRY: 120.0})

        self.assertIsInstance(raised, frappe.ValidationError)
        self.assertIn("SMOKEY SLURRY (SFG10002): 200.0 entered, 120.0 available", str(raised))
        self.assertNotIn(CORN_MIX, str(raised))
        self.assertFalse(se.inserted)
        self.assertEqual(wo.comments, [], "the rounding is only noted when the entry goes ahead")

    def test_repeated_rows_for_one_item_are_one_figure(self):
        """Checked against stock as a total, so posted as one too: 160 and
        106.667 are 266.667 between them, one tick over what was made."""
        se, _wo, raised = post([{"item_code": CORN_MIX, "qty": 160}, {"item_code": CORN_MIX, "qty": 106.667}],
                               {CORN_MIX: MADE})

        self.assertIsNone(raised)
        self.assertEqual([(r["item_code"], r["qty"]) for r in se.items], [(CORN_MIX, MADE)])

    def test_blank_zero_and_unreadable_rows_are_still_ignored(self):
        se, wo, raised = post([{"item_code": "", "qty": 5}, {"item_code": CORN_MIX, "qty": 0},
                               {"item_code": SLURRY, "qty": "x"}, {"item_code": CORN_MIX, "qty": -3}],
                              {CORN_MIX: MADE})

        self.assertIsNone(raised)
        self.assertEqual((se.items, se.inserted, wo.comments), ([], False, []))

    def test_an_item_off_the_bom_is_still_refused(self):
        se, _wo, raised = post([{"item_code": CORN_MIX, "qty": ENTERED}], {CORN_MIX: MADE}, in_bom=False)

        self.assertIsInstance(raised, frappe.ValidationError)
        self.assertIn("Item not in BOM", str(raised))
        self.assertFalse(se.inserted)


def end(wo, sfg_usage, stock, consumed=None):
    """end_work_order on a started finished-good order, with the netting and
    the posting both real. Returns (result or the ValidationError raised, the
    Stock Entry it built)."""
    se = FakeStockEntry()
    with ExitStack() as stack:
        for p in (
            patch.object(mes_ops, "_require_roles"),
            patch.object(mes_ops.frappe, "get_doc", return_value=wo),
            patch.object(mes_ops.frappe.db, "get_value", side_effect=item_lookup),
            patch.object(mes_ops, "_get_consumed_materials_from_load", return_value=consumed or {}),
            patch.object(mes_ops, "_end_wo_consumption_summary",
                         return_value={"can_end": True, "items": [], "shortfalls": 0, "tolerance_pct": 5}),
            patch.object(mes_ops, "_wo_closes_at_end", return_value=False),
            patch.object(mes_ops, "_default_line_wip", return_value=WIP),
            patch.object(mes_ops, "_default_sfg_source", return_value=SFG_WH),
            holding(stock),
            patch.object(mes_ops, "_pending_sfg_work_orders", return_value=[]),
            patch.object(mes_ops, "_validate_item_in_bom", return_value=(True, "OK")),
            patch.object(mes_ops.frappe, "new_doc", return_value=se),
            at_precision(3),
        ):
            stack.enter_context(p)
        try:
            result = mes_ops.end_work_order(WO, sfg_usage=json.dumps(sfg_usage))
        except frappe.ValidationError as e:
            result = e
    return result, se


class TestEndWorkOrder(unittest.TestCase):
    def test_the_reported_order_ends(self):
        wo = WorkOrderStub()
        result, se = end(wo, [{"item_code": CORN_MIX, "qty": ENTERED}], {CORN_MIX: MADE})

        self.assertTrue(result["success"])
        self.assertEqual([(r["item_code"], r["qty"]) for r in se.items], [(CORN_MIX, MADE)])
        self.assertTrue(se.submitted)
        wo.db_set.assert_called_once_with("custom_production_ended", 1, commit=True)

    def test_entering_what_was_made_still_works(self):
        """What operators had to do until now, and may go on doing."""
        wo = WorkOrderStub()
        result, se = end(wo, [{"item_code": CORN_MIX, "qty": MADE}], {CORN_MIX: MADE})

        self.assertTrue(result["success"])
        self.assertEqual([r["qty"] for r in se.items], [MADE])
        self.assertFalse(any(c.startswith("Semi-finished usage rounded") for c in wo.comments))

    def test_ending_again_after_an_undo_is_not_refused_over_the_tick(self):
        """Before, the second End WO stopped on "0.001 entered, 0.0 available"
        and only typing 266.666 got past it."""
        wo = WorkOrderStub()
        result, se = end(wo, [{"item_code": CORN_MIX, "qty": ENTERED}], {CORN_MIX: 0.0},
                         consumed={CORN_MIX: MADE})

        self.assertTrue(result["success"])
        self.assertFalse(se.inserted)
        self.assertTrue(any(c.startswith("Semi-finished usage rounded to stock") and "0 consumed" in c
                            for c in wo.comments))
        wo.db_set.assert_called_once_with("custom_production_ended", 1, commit=True)

    def test_a_real_shortage_still_stops_the_order_from_ending(self):
        wo = WorkOrderStub()
        outcome, se = end(wo, [{"item_code": CORN_MIX, "qty": ENTERED}], {CORN_MIX: 160.0})

        self.assertIsInstance(outcome, frappe.ValidationError)
        self.assertIn("266.667 entered, 160.0 available", str(outcome))
        self.assertFalse(se.inserted)
        wo.db_set.assert_not_called()


class TestCloseProductionAfterwards(unittest.TestCase):
    """Close Production already draws a semi-finished remainder truncated and
    capped at the balance. After End WO has taken what was there, the two must
    not add up to anything: nothing more to draw, nothing to report."""

    def plan(self, consumed, output=500.0, in_semi_finished=0.0):
        wo = MagicMock()
        wo.name, wo.bom_no, wo.wip_warehouse, wo.qty = WO, "BOM-FG10019-001", WIP, 500.0
        recipe = [{"item_code": CORN_MIX, "qty": REQUIRED * output / 500.0, "uom": "Kg"}]
        with patch.object(mes_ops, "get_sfg_components_for_wo",
                          return_value={"items": [{"item_code": CORN_MIX}]}), \
                patch.object(mes_ops, "_default_sfg_source", return_value=SFG_WH), \
                patch.object(mes_ops, "_packaging_groups_global", return_value=set()), \
                patch.object(mes_ops, "_get_consumed_materials_from_load", return_value={CORN_MIX: consumed}), \
                patch.object(mes_ops, "_metered_items", return_value=set()), \
                patch.object(mes_ops, "_wip_inflow_by_item", return_value={}), \
                patch.object(mes_ops, "_wip_transfers_out_by_item", return_value={}), \
                patch.object(mes_ops, "_planned_items_for_wo", return_value=recipe), \
                patch.object(mes_ops, "_get_item_group", return_value="Semi-Finished Goods"), \
                patch.object(mes_ops, "_warehouse_qty", return_value=in_semi_finished), \
                at_precision(3):
            return mes_ops._bom_consumption_plan(wo, output)[0]

    def test_the_part_of_a_tick_end_wo_left_is_nothing_to_the_close(self):
        row = self.plan(consumed=MADE)

        self.assertEqual((row["source_warehouse"], row["already_consumed"]), (SFG_WH, MADE))
        self.assertAlmostEqual(row["remaining_qty"], 0.000666667, places=9)
        self.assertEqual((row["post_qty"], row["short_qty"]), (0.0, 0.0))

    def test_an_order_that_consumed_nothing_at_end_wo_still_draws_only_what_is_there(self):
        """End WO now does for a one-tick gap what the close does for any gap:
        the operator who left the field at 0 got 266.666 drawn here, not a
        refusal."""
        row = self.plan(consumed=0.0, in_semi_finished=MADE)

        self.assertEqual((row["post_qty"], row["short_qty"]), (MADE, 0.0))


class TestTheDialogAgreesWithTheButton(unittest.TestCase):
    """The dialog prints "Available stock is below the planned requirement"
    when still_needed_qty is more than available_qty. A warning about a tick
    End WO then accepts would send the operator looking for stock that is not
    missing."""

    def row(self, available, consumed=0.0, required=REQUIRED):
        sfg = {"items": [{"item_code": CORN_MIX, "qty": 160}], "bom_quantity": 300}
        with patch.object(mes_ops, "_require_roles"), \
                patch.object(mes_ops, "_end_wo_consumption_summary",
                             return_value={"items": [], "shortfalls": 0, "can_end": True}), \
                patch.object(mes_ops, "get_sfg_components_for_wo", return_value=sfg), \
                patch.object(mes_ops.frappe, "get_roles", return_value=[]), \
                patch.object(mes_ops.frappe.db, "get_value",
                             return_value=frappe._dict(production_item="FG10019", qty=500.0)), \
                patch.object(mes_ops, "_is_fg", return_value=True), \
                patch.object(mes_ops, "_wo_closes_at_end", return_value=False), \
                patch.object(mes_ops, "_default_sfg_source", return_value=SFG_WH), \
                holding({CORN_MIX: available}), \
                patch.object(mes_ops, "_planned_required_qty", return_value=required), \
                patch.object(mes_ops, "_pending_sfg_work_orders", return_value=[]), \
                patch.object(mes_ops, "_get_consumed_materials_from_load",
                             return_value={CORN_MIX: consumed} if consumed else {}), \
                at_precision(3):
            return mes_ops.get_end_wo_summary(WO)["sfg_items"][0]

    @staticmethod
    def shown_as_short(row):
        """operator_hub.js: stillNeeded > row.available_qty."""
        return row["still_needed_qty"] > row["available_qty"]

    def test_the_reported_order_is_not_called_short(self):
        row = self.row(available=MADE)

        self.assertEqual((row["required_qty"], row["available_qty"], row["still_needed_qty"]),
                         (266.6667, MADE, MADE))
        self.assertFalse(self.shown_as_short(row))

    def test_two_ticks_short_is_still_called_short(self):
        row = self.row(available=266.665)

        self.assertEqual(row["still_needed_qty"], ENTERED)
        self.assertTrue(self.shown_as_short(row))

    def test_stock_that_covers_the_requirement_changes_nothing(self):
        row = self.row(available=300.0)

        self.assertEqual(row["still_needed_qty"], ENTERED)
        self.assertFalse(self.shown_as_short(row))

    def test_a_balance_that_could_not_be_read_is_still_called_short(self):
        """End WO refuses the tick then, so the dialog must not wave it through."""
        row = self.row(available=UNREADABLE, consumed=MADE)

        self.assertEqual((row["available_qty"], row["still_needed_qty"]), (0.0, 0.001))
        self.assertTrue(self.shown_as_short(row))

    def test_a_reopened_order_with_only_the_tick_left_is_not_called_short(self):
        row = self.row(available=0.0, consumed=MADE)

        self.assertEqual((row["already_consumed"], row["still_needed_qty"]), (MADE, 0.0))
        self.assertFalse(self.shown_as_short(row))

    def test_the_dialog_and_end_wo_decide_alike_on_the_planned_figure(self):
        """The operator types the dialog's Planned figure, which reaches the
        server on the posting grid. When something is already recorded and the
        four-place requirement ends in 5, subtracting before rounding lands a
        tick away from what End WO nets: 419.0335 planned with 266.679
        recorded is 152.354 that way and 152.355 at End WO."""
        cases = (
            # (requirement, already recorded, in stock)
            (REQUIRED, 0.0, MADE),          # the incident
            (REQUIRED, 0.0, 266.665),       # two ticks short
            (REQUIRED, MADE, 0.0),          # ended again after Undo
            (419.0335, 266.679, 152.353),   # two ticks short at End WO
            (212.9685, 23.021, 189.946),    # one tick, taken down at End WO
        )
        for required, consumed, available in cases:
            row = self.row(available=available, consumed=consumed, required=required)
            with at_precision(3):
                typed = postable_qty(row["required_qty"])
            outcome, _se = end(WorkOrderStub(), [{"item_code": CORN_MIX, "qty": typed}],
                               {CORN_MIX: available}, consumed={CORN_MIX: consumed} if consumed else None)

            self.assertEqual(self.shown_as_short(row), isinstance(outcome, frappe.ValidationError),
                             (required, consumed, available, row["still_needed_qty"], str(outcome)))


if __name__ == "__main__":
    unittest.main()
