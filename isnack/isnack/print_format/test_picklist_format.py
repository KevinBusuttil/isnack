# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""Rendering tests for the Picklist print format's header.

The picklist carries only the materials to pick, so the item being produced is
nowhere on the document itself -- it is reached through the work orders behind
the picklist's transfers, which is what the format's one SQL query is for.

A picklist is normally raised for a single finished good, but its transfers pull
in the semi-finished runs that feed it: PKL-260917-0741, the one the client sent
back, resolves to three produced items and only FG10011 is a finished good. The
header has to pick that one out, and say nothing when the choice is not clear.

Not every transfer names its work order directly, either -- a surplus entry
records the order it was left over from on a child table instead, and a picklist
can be made of nothing but those.

The template is Jinja stored inside the Print Format JSON, so the only way to
test what it prints is to render it -- here through a jinja2 environment
configured like frappe's (``SandboxedEnvironment``, ``DebugUndefined``,
autoescape off -- see ``frappe.utils.jinja.get_jenv``), with stand-ins for
``doc`` and ``frappe``, so no site or database is needed. The sandbox is not a
detail: the header counts produced items by mutating a dict, and a stricter
environment would refuse that outright.
"""

import json
import os
import re
import unittest
from datetime import date

from jinja2 import DebugUndefined
from jinja2.sandbox import SandboxedEnvironment

PRINT_FORMAT_DIR = os.path.dirname(os.path.abspath(__file__))

# The site's own items, from the 2026-09-17 backup. One finished good, and the
# two semi-finished runs whose work orders feed it.
PUFFS = ("FG10011", "PUFFS - Super Cheesy 21pkt x 40g")
MIX = ("SFG10001", "CORN MIX 1")
SLURRY = ("SFG10002", "PUFFS CHEESY SLURRY")
# A second finished good, so "more than one" can be told apart from "more than
# one work order".
WELLIX = ("FG10006", "WELLIX - Pro Snack Pea Olive & Herbs 21pkt x 45g")

FINISHED = "Finished Goods"
SEMI = "Semi-Finished Goods"


class _Doc:
    """Stand-in for a frappe document: attribute access plus ``get()``."""

    def __init__(self, **values):
        self.__dict__.update(values)

    def get(self, key, default=None):
        return self.__dict__.get(key, default)

    def __getattr__(self, key):
        return None


class _FrappeStub:
    """The subset of ``frappe`` the Picklist format reaches for.

    ``db.sql`` stands in for the work-order lookup and counts its own calls, so
    a format that resolved the produced item separately from the Work Orders
    table -- querying twice for one page -- fails the test.
    """

    def __init__(self, work_orders=None):
        self.work_orders = work_orders or []
        self.queries = []
        self.utils = _Doc(
            formatdate=lambda v, *a, **k: v.strftime("%d-%m-%Y") if v else "",
            format_datetime=lambda v, *a, **k: "17-09-2026 08:15:00",
            now=lambda: "2026-09-17 08:15:00",
        )

    @property
    def db(self):
        return self

    def sql(self, query, params=None, as_dict=False):
        self.queries.append((query, params))
        return list(self.work_orders)


def _wo(produced, item_group=FINISHED, work_order="MFG-WO-2026-00071"):
    """A row as the format's query returns it."""
    item_code, item_name = produced
    return _Doc(
        work_order=work_order,
        item_code=item_code,
        item_name=item_name,
        item_group=item_group,
    )


def _item(item_code="RM20023", **overrides):
    values = dict(
        item_code=item_code,
        item_name="Water",
        from_warehouse="Stores - ISN",
        to_warehouse="EXT1-STAGING - ISN",
        uom="Litre",
        qty=2.668,
        batch_no=None,
    )
    values.update(overrides)
    return _Doc(**values)


def _picklist(transfers=("MAT-STE-2026-00403",), **overrides):
    values = dict(
        name="PKL-260917-0741",
        company="Isnack",
        posting_date=date(2026, 9, 17),
        from_warehouse="Stores - ISN",
        to_warehouse=None,
        transfers=[_Doc(stock_entry=t) for t in transfers],
        items=[_item()],
    )
    values.update(overrides)
    return _Doc(**values)


def _render(doc, work_orders=None):
    """Render the stored format, returning ``(html, frappe_stub)``."""
    path = os.path.join(PRINT_FORMAT_DIR, "picklist", "picklist.json")
    with open(path, encoding="utf-8") as f:
        template = json.load(f)["html"]

    frappe = _FrappeStub(work_orders=work_orders)
    env = SandboxedEnvironment(undefined=DebugUndefined, autoescape=False)
    return env.from_string(template).render(doc=doc, frappe=frappe), frappe


def _header(html, label):
    """The value printed beside a header label, whitespace collapsed.

    The first row's cells carry width styles and the later ones do not, so the
    attributes are matched loosely.
    """
    match = re.search(
        r"<td[^>]*><b>%s</b></td>\s*<td[^>]*>(.*?)</td>" % re.escape(label),
        html,
        re.S,
    )
    return re.sub(r"\s+", " ", match.group(1)).strip() if match else None


class TestProducedItemInTheHeader(unittest.TestCase):
    """Which of the picklist's produced items the header names."""

    def assertRendered(self, html):
        """No DebugUndefined leftovers, i.e. the stub covered the template."""
        self.assertNotIn("{{", html)

    def test_the_one_finished_good_among_several_produced_items(self):
        """PKL-260917-0741: three produced items, one of them finished."""
        html, _ = _render(
            _picklist(),
            [
                _wo(PUFFS, FINISHED, "MFG-WO-2026-00071"),
                _wo(MIX, SEMI, "MFG-WO-2026-00072"),
                _wo(SLURRY, SEMI, "MFG-WO-2026-00073"),
            ],
        )

        self.assertRendered(html)
        self.assertEqual(
            _header(html, "Produced Item:"),
            "FG10011 &mdash; PUFFS - Super Cheesy 21pkt x 40g",
        )

    def test_both_the_code_and_the_name_are_printed(self):
        html, _ = _render(_picklist(), [_wo(PUFFS)])
        printed = _header(html, "Produced Item:")

        self.assertIn(PUFFS[0], printed)
        self.assertIn(PUFFS[1], printed)

    def test_a_semi_finished_run_falls_back_to_its_own_item(self):
        """Twelve of the site's picklists produce no finished good at all.

        They are raised for a corn mix or a slurry, and a picker is better
        served by the item that run makes than by an empty line.
        """
        html, _ = _render(_picklist(), [_wo(MIX, SEMI)])

        self.assertEqual(_header(html, "Produced Item:"), "SFG10001 &mdash; CORN MIX 1")

    def test_two_work_orders_for_the_same_item_are_still_one_item(self):
        """Counting rows rather than items would call this ambiguous."""
        html, _ = _render(
            _picklist(transfers=("MAT-STE-2026-00403", "MAT-STE-2026-00404")),
            [
                _wo(PUFFS, FINISHED, "MFG-WO-2026-00071"),
                _wo(PUFFS, FINISHED, "MFG-WO-2026-00068"),
            ],
        )

        self.assertEqual(
            _header(html, "Produced Item:"),
            "FG10011 &mdash; PUFFS - Super Cheesy 21pkt x 40g",
        )

    def test_two_different_finished_goods_name_neither(self):
        """Naming one of them would be a guess; the table below lists both."""
        html, _ = _render(
            _picklist(transfers=("MAT-STE-2026-00403", "MAT-STE-2026-00404")),
            [
                _wo(PUFFS, FINISHED, "MFG-WO-2026-00071"),
                _wo(WELLIX, FINISHED, "MFG-WO-2026-00001"),
            ],
        )

        self.assertEqual(_header(html, "Produced Item:"), "")
        self.assertIn(WELLIX[0], html)
        self.assertIn(PUFFS[0], html)

    def test_a_picklist_with_no_transfers_asks_no_question_of_the_database(self):
        html, frappe = _render(_picklist(transfers=()))

        self.assertRendered(html)
        self.assertEqual(_header(html, "Produced Item:"), "")
        self.assertEqual(frappe.queries, [])

    def test_a_transfer_row_without_a_stock_entry_is_not_looked_up(self):
        html, frappe = _render(_picklist(transfers=(None,)))

        self.assertEqual(_header(html, "Produced Item:"), "")
        self.assertEqual(frappe.queries, [])


class TestSurplusEntriesStillNameTheirWorkOrder(unittest.TestCase):
    """A surplus entry has no work_order of its own.

    It is the remainder of picking for one -- opening a 50 kg reel for a 37 kg
    order -- so ``se.work_order`` is unset and the origin is recorded on the
    ``custom_originating_work_orders`` child table, with the older single
    ``custom_originating_work_order`` for rows predating it. The storekeeper
    hub offers these entries for picking alongside the work-order-linked ones
    and lets each be chosen on its own, so a picklist can hold nothing else.

    Following only ``se.work_order`` left those picklists with an empty header.
    What the query returns is stubbed here; that it returns the right rows was
    checked by running this template's own SQL against the 2026-09-17 backup.
    """

    def test_a_surplus_only_picklist_names_the_originating_item(self):
        html, _ = _render(_picklist(transfers=("MAT-STE-2026-00264",)), [_wo(PUFFS)])

        self.assertEqual(
            _header(html, "Produced Item:"),
            "FG10011 &mdash; PUFFS - Super Cheesy 21pkt x 40g",
        )

    def test_the_query_follows_all_three_routes_to_a_work_order(self):
        """The direct link, the child table, and the legacy single link."""
        _, frappe = _render(_picklist(), [_wo(PUFFS)])
        query, _params = frappe.queries[0]

        self.assertIn("se.work_order", query)
        self.assertIn("custom_originating_work_orders", query)
        self.assertIn("se.custom_originating_work_order", query)

    def test_the_child_table_rows_are_read_as_stock_entry_children(self):
        """Its parentfield is shared with other doctypes' tables."""
        _, frappe = _render(_picklist(), [_wo(PUFFS)])
        query, _params = frappe.queries[0]

        self.assertIn("Surplus Originating Work Order", query)
        self.assertIn("sow.parenttype = 'Stock Entry'", query)

    def test_a_surplus_entry_beside_a_semi_finished_run_names_the_finished_good(self):
        """Seven picklists in the backup are this shape.

        The surplus carries FG10011's own carton and film, so the picklist is
        serving that order as much as the corn mix beside it.
        """
        html, _ = _render(
            _picklist(transfers=("MAT-STE-2026-00264", "MAT-STE-2026-00261")),
            [
                _wo(PUFFS, FINISHED, "MFG-WO-2026-00047"),
                _wo(MIX, SEMI, "MFG-WO-2026-00049"),
            ],
        )

        self.assertEqual(
            _header(html, "Produced Item:"),
            "FG10011 &mdash; PUFFS - Super Cheesy 21pkt x 40g",
        )


class TestTheHeaderCostsOneQuery(unittest.TestCase):
    """The header and the Work Orders table read the same resolved rows."""

    def test_the_work_orders_are_looked_up_once_for_the_page(self):
        _, frappe = _render(_picklist(), [_wo(PUFFS)])

        self.assertEqual(len(frappe.queries), 1)

    def test_the_query_asks_for_the_item_group_the_header_needs(self):
        """Without it every produced item looks finished."""
        _, frappe = _render(_picklist(), [_wo(PUFFS)])
        query, _params = frappe.queries[0]

        self.assertIn("item_group", query)

    def test_the_work_orders_table_still_lists_every_produced_item(self):
        html, _ = _render(
            _picklist(),
            [
                _wo(PUFFS, FINISHED, "MFG-WO-2026-00071"),
                _wo(MIX, SEMI, "MFG-WO-2026-00072"),
                _wo(SLURRY, SEMI, "MFG-WO-2026-00073"),
            ],
        )

        self.assertIn("Work Orders", html)
        for code, name in (PUFFS, MIX, SLURRY):
            self.assertIn(code, html)
            self.assertIn(name, html)


class TestCompanyIsGone(unittest.TestCase):
    """One company exists on this site and every picklist carries it.

    The row said the same thing on all 46 picklists, so it was spending a
    header slot the produced item now uses.
    """

    def test_the_format_no_longer_prints_the_company(self):
        html, _ = _render(_picklist(company="Isnack"), [_wo(PUFFS)])

        self.assertNotIn("Company", html)
        self.assertNotIn("Isnack", html)

    def test_the_rest_of_the_header_is_untouched(self):
        html, _ = _render(_picklist(), [_wo(PUFFS)])

        self.assertEqual(_header(html, "Picklist No:"), "PKL-260917-0741")
        self.assertEqual(_header(html, "Date:"), "17-09-2026")
        self.assertEqual(_header(html, "From Warehouse:"), "Stores - ISN")
        self.assertIsNotNone(_header(html, "To Warehouse:"))

    def test_the_items_to_pick_are_untouched(self):
        html, _ = _render(_picklist(), [_wo(PUFFS)])

        self.assertIn("Items to Pick", html)
        self.assertIn("RM20023", html)
        self.assertIn("2.67", html)


if __name__ == "__main__":
    unittest.main()
