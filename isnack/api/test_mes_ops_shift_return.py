# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""What the End Shift Return dialog is worth offering an operator.

Two complaints, two settings. Water is piped and metered: it is never carried
back to stores whatever the quantity, so it is named in Factory Settings —
the same list that keeps it out of what an operator is asked to consume — and
refused outright here. Separately, any BOM ratio that is not exactly representable
at the posting precision leaves a sub-tick remainder in WIP on every close —
water's line is 1/30 per Kg, and a packaging film sits at 0.001 Kg for the same
reason — so a minimum quantity keeps those residues off the screen without
naming each item.

The minimum is a display rule and the exclusion is a semantic one, which is why
only the exclusion is enforced when the return is posted.

The same endpoint also fills the Stock Entry the Material Return Note prints
from, so the last class here covers the note's header rather than the dialog.
"""

import json
import os
import unittest
from unittest.mock import MagicMock, patch

import frappe

import isnack.api.mes_ops as mes_ops
from isnack.api.mes_ops import get_wip_inventory, return_wip_to_staging

LINE = "SLURRY 1"
WIP = "EXT1-WIP - ISN"
STAGING = "EXT1-STAGING - ISN"

# The customer's own WIP, from the 2026-09-14 backup.
WATER = "RM20023"          # 0.001 Litre, the reported row, and the only
                           # raw material that is not batch tracked
FILM = "PM40002"           # 0.001 Kg — the same residue reaching the dialog
                           # through the batch branch instead
SEASONING = "RM20011"      # 184.8 Kg, genuinely worth carrying back


def _factory_settings(metered=(), min_return_qty=0.01):
    fs = MagicMock()
    rows = []
    for item in metered:
        row = MagicMock()
        row.item = item
        rows.append(row)

    def get(field, *a, **kw):
        if field == "metered_items":
            return rows
        if field == "min_return_qty":
            return min_return_qty
        return None

    fs.get.side_effect = get
    return fs


def _item_field(doctype, name, field, *a, **kw):
    values = {
        WATER: {"item_name": "Water", "stock_uom": "Litre", "has_batch_no": 0},
        FILM: {"item_name": "THE FRITZ - Sweet Chilli 40g Film", "stock_uom": "Kg", "has_batch_no": 1},
        SEASONING: {"item_name": "Cheesy Jalapeno Seasoning", "stock_uom": "Kg", "has_batch_no": 1},
    }
    return (values.get(name) or {}).get(field)


def _batch_qty(qty_by_item):
    """erpnext get_batch_qty stand-in: one batch holding the bin's quantity."""
    def get_batch_qty(item_code=None, warehouse=None, **kw):
        qty = qty_by_item.get(item_code)
        return [{"batch_no": "B-%s" % item_code, "qty": qty}] if qty is not None else []
    return get_batch_qty


def _bins(*pairs):
    def get_all(doctype, **kwargs):
        if doctype == "Bin":
            return [frappe._dict(item_code=i, actual_qty=q) for i, q in pairs]
        return []
    return get_all


class TestWipInventoryPolicy(unittest.TestCase):
    """get_wip_inventory decides what the dialog is even allowed to show."""

    def _run(self, bins, settings):
        with patch.object(mes_ops, "_require_roles"), \
                patch.object(mes_ops, "_warehouses_for_line",
                             return_value=(STAGING, WIP, None, None)), \
                patch("frappe.get_cached_doc", return_value=settings), \
                patch("frappe.db.get_value", side_effect=_item_field), \
                patch("erpnext.stock.doctype.batch.batch.get_batch_qty",
                      side_effect=_batch_qty(dict(bins))), \
                patch("frappe.get_all", side_effect=_bins(*bins)):
            return get_wip_inventory(LINE)["items"]

    def test_a_metered_item_is_never_offered(self):
        """Water at any quantity, not just the residue."""
        items = self._run([(WATER, 500.0), (SEASONING, 184.8)],
                          _factory_settings(metered=[WATER], min_return_qty=0))

        self.assertEqual([i["item_code"] for i in items], [SEASONING])

    def test_residues_below_the_minimum_are_left_off(self):
        """The 0.001 rows, on both the reported item and the packaging film."""
        items = self._run([(WATER, 0.001), (FILM, 0.001), (SEASONING, 184.8)],
                          _factory_settings(min_return_qty=0.01))

        self.assertEqual([i["item_code"] for i in items], [SEASONING])

    def test_a_quantity_worth_carrying_back_is_still_offered(self):
        """0.3 Kg of film is a real remainder and must survive the filter."""
        items = self._run([(FILM, 0.3)], _factory_settings(min_return_qty=0.01))

        self.assertEqual([i["item_code"] for i in items], [FILM])
        self.assertEqual(items[0]["qty"], 0.3)

    def test_a_quantity_exactly_on_the_minimum_is_offered(self):
        """The setting is a floor, not a threshold to clear."""
        items = self._run([(FILM, 0.01)], _factory_settings(min_return_qty=0.01))

        self.assertEqual([i["item_code"] for i in items], [FILM])

    def test_a_zero_minimum_shows_every_balance(self):
        """The escape hatch for a site that wants to see everything."""
        items = self._run([(WATER, 0.001), (FILM, 0.001)],
                          _factory_settings(min_return_qty=0))

        self.assertEqual(sorted(i["item_code"] for i in items), sorted([WATER, FILM]))

    def test_an_unsaved_minimum_still_hides_residues(self):
        """A Single returns None for a field never saved.

        Reading that as zero would ship the fix switched off, so the default
        applies until somebody sets the field deliberately.
        """
        items = self._run([(WATER, 0.001), (SEASONING, 184.8)],
                          _factory_settings(min_return_qty=None))

        self.assertEqual([i["item_code"] for i in items], [SEASONING])

    def test_unreadable_settings_do_not_break_the_dialog(self):
        """Losing the settings must not cost the operator their return screen."""
        with patch.object(mes_ops, "_require_roles"), \
                patch.object(mes_ops, "_warehouses_for_line",
                             return_value=(STAGING, WIP, None, None)), \
                patch("frappe.get_cached_doc", side_effect=Exception("db down")), \
                patch("frappe.db.get_value", side_effect=_item_field), \
                patch("frappe.get_all", side_effect=_bins((WATER, 500.0))):
            items = get_wip_inventory(LINE)["items"]

        # No settings means no policy: nothing is excluded and nothing is hidden.
        self.assertEqual([i["item_code"] for i in items], [WATER])


class TestReturnWipRefusesMeteredItems(unittest.TestCase):
    """Hiding the row is not enough — the endpoint is whitelisted."""

    def _post(self, items, settings):
        with patch.object(mes_ops, "_require_roles"), \
                patch.object(mes_ops, "_warehouses_for_line",
                             return_value=(STAGING, WIP, None, None)), \
                patch("frappe.get_cached_doc", return_value=settings), \
                patch("frappe.db.get_value", side_effect=_item_field), \
                patch("frappe.new_doc", return_value=MagicMock()):
            return return_wip_to_staging(LINE, json.dumps(items))

    def test_a_metered_item_is_refused(self):
        with self.assertRaises(frappe.ValidationError) as caught:
            self._post([{"item_code": WATER, "qty": 0.001}],
                       _factory_settings(metered=[WATER]))

        self.assertIn(WATER, str(caught.exception))
        self.assertIn("metered", str(caught.exception))

    def test_one_metered_item_refuses_the_whole_return(self):
        """Posting the rest silently would leave the operator guessing."""
        with self.assertRaises(frappe.ValidationError) as caught:
            self._post(
                [{"item_code": SEASONING, "qty": 10}, {"item_code": WATER, "qty": 0.001}],
                _factory_settings(metered=[WATER]),
            )

        self.assertIn(WATER, str(caught.exception))
        self.assertNotIn(SEASONING, str(caught.exception))

    def test_a_small_quantity_is_not_refused(self):
        """The minimum governs the dialog, not what may be posted.

        A storekeeper deliberately returning 0.001 is doing something valid;
        only the dialog decided it was not worth offering unprompted.
        """
        settings = _factory_settings(metered=[WATER], min_return_qty=0.01)
        with patch.object(mes_ops, "_require_roles"), \
                patch.object(mes_ops, "_warehouses_for_line",
                             return_value=(STAGING, WIP, None, None)), \
                patch("frappe.get_cached_doc", return_value=settings), \
                patch("frappe.db.get_value", side_effect=_item_field), \
                patch("frappe.new_doc") as mock_new_doc, \
                patch("frappe.publish_realtime"):
            se = MagicMock()
            se.items = [MagicMock()]
            mock_new_doc.return_value = se

            return_wip_to_staging(LINE, json.dumps([{"item_code": FILM, "qty": 0.001}]))

            se.submit.assert_called_once()


class TestReturnNoteHeader(unittest.TestCase):
    """What the Material Return Note prints above its item table.

    The note's item table reads the Stock Entry's rows, but its header reads the
    entry's own fields — factory section, from warehouse, to warehouse. Filling
    only the rows left all three blank on every end-shift return ever posted
    (MAT-STE-2026-00419 was the one the client sent back), while the table below
    them printed the warehouses correctly, which is why it went unnoticed.

    Header and rows are set from the same pair of warehouses, so the two halves
    of the note cannot disagree.
    """

    def _post(self, items):
        with patch.object(mes_ops, "_require_roles"), \
                patch.object(mes_ops, "_warehouses_for_line",
                             return_value=(STAGING, WIP, None, None)), \
                patch("frappe.get_cached_doc", return_value=_factory_settings(metered=[WATER])), \
                patch("frappe.db.get_value", side_effect=_item_field), \
                patch("frappe.new_doc") as mock_new_doc, \
                patch("frappe.publish_realtime"):
            se = MagicMock()
            se.items = [MagicMock()]
            mock_new_doc.return_value = se

            return_wip_to_staging(LINE, json.dumps(items))

        return se

    def test_the_header_names_both_warehouses(self):
        """WIP out, staging back — the same pair the rows carry."""
        se = self._post([{"item_code": SEASONING, "qty": 10}])

        self.assertEqual(se.from_warehouse, WIP)
        self.assertEqual(se.to_warehouse, STAGING)

    def test_the_header_names_the_factory_section(self):
        se = self._post([{"item_code": SEASONING, "qty": 10}])

        self.assertEqual(se.custom_factory_line, LINE)

    def test_the_header_agrees_with_every_row(self):
        """A header contradicting the table would be worse than a blank one."""
        se = self._post([{"item_code": SEASONING, "qty": 10},
                         {"item_code": FILM, "qty": 2}])

        rows = [call.args[1] for call in se.append.call_args_list
                if call.args[0] == "items"]

        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row["s_warehouse"], se.from_warehouse)
            self.assertEqual(row["t_warehouse"], se.to_warehouse)


class TestFactorySectionIsAFieldOnStockEntry(unittest.TestCase):
    """The section only survives the save if Stock Entry declares the field.

    Assigning an undeclared fieldname is not an error in Frappe — the value is
    dropped on the way to the table and nothing is raised. The endpoint had been
    setting custom_factory_line all along; the field simply did not exist on
    Stock Entry, only on Work Order. A mock accepts any attribute, so no test
    exercising the endpoint can catch that: the fixture is what has to be checked.
    """

    FIXTURE = os.path.join(os.path.dirname(__file__),
                           "..", "isnack", "custom", "stock_entry.json")

    def setUp(self):
        with open(self.FIXTURE) as f:
            self.fields = {f_["fieldname"]: f_
                           for f_ in json.load(f)["custom_fields"]}

    def _factory_section(self):
        self.assertIn("custom_factory_line", sorted(self.fields),
                      "Stock Entry has no custom_factory_line field — the "
                      "endpoint's assignment will be dropped silently and the "
                      "note's Factory Section will print blank")
        return self.fields["custom_factory_line"]

    def test_stock_entry_declares_the_factory_section(self):
        self._factory_section()

    def test_it_links_to_the_factory_line_the_endpoint_passes(self):
        """A Link, so the printed section is a real line and not free text."""
        field = self._factory_section()

        self.assertEqual(field["fieldtype"], "Link")
        self.assertEqual(field["options"], "Factory Line")

    def test_it_is_not_hidden_from_print(self):
        self.assertFalse(self._factory_section()["print_hide"])


if __name__ == "__main__":
    unittest.main()
