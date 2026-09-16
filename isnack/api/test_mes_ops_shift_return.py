# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""What the End Shift Return dialog is worth offering an operator.

Two complaints, two settings. Water is piped and metered: it is never carried
back to stores whatever the quantity, so it is named in Factory Settings and
refused outright. Separately, any BOM ratio that is not exactly representable
at the posting precision leaves a sub-tick remainder in WIP on every close —
water's line is 1/30 per Kg, and a packaging film sits at 0.001 Kg for the same
reason — so a minimum quantity keeps those residues off the screen without
naming each item.

The minimum is a display rule and the exclusion is a semantic one, which is why
only the exclusion is enforced when the return is posted.
"""

import json
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


def _factory_settings(non_returnable=(), min_return_qty=0.01):
    fs = MagicMock()
    rows = []
    for item in non_returnable:
        row = MagicMock()
        row.item = item
        rows.append(row)

    def get(field, *a, **kw):
        if field == "non_returnable_items":
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

    def test_a_non_returnable_item_is_never_offered(self):
        """Water at any quantity, not just the residue."""
        items = self._run([(WATER, 500.0), (SEASONING, 184.8)],
                          _factory_settings(non_returnable=[WATER], min_return_qty=0))

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


class TestReturnWipRefusesNonReturnable(unittest.TestCase):
    """Hiding the row is not enough — the endpoint is whitelisted."""

    def _post(self, items, settings):
        with patch.object(mes_ops, "_require_roles"), \
                patch.object(mes_ops, "_warehouses_for_line",
                             return_value=(STAGING, WIP, None, None)), \
                patch("frappe.get_cached_doc", return_value=settings), \
                patch("frappe.db.get_value", side_effect=_item_field), \
                patch("frappe.new_doc", return_value=MagicMock()):
            return return_wip_to_staging(LINE, json.dumps(items))

    def test_a_non_returnable_item_is_refused(self):
        with self.assertRaises(frappe.ValidationError) as caught:
            self._post([{"item_code": WATER, "qty": 0.001}],
                       _factory_settings(non_returnable=[WATER]))

        self.assertIn(WATER, str(caught.exception))
        self.assertIn("non-returnable", str(caught.exception))

    def test_one_non_returnable_item_refuses_the_whole_return(self):
        """Posting the rest silently would leave the operator guessing."""
        with self.assertRaises(frappe.ValidationError) as caught:
            self._post(
                [{"item_code": SEASONING, "qty": 10}, {"item_code": WATER, "qty": 0.001}],
                _factory_settings(non_returnable=[WATER]),
            )

        self.assertIn(WATER, str(caught.exception))
        self.assertNotIn(SEASONING, str(caught.exception))

    def test_a_small_quantity_is_not_refused(self):
        """The minimum governs the dialog, not what may be posted.

        A storekeeper deliberately returning 0.001 is doing something valid;
        only the dialog decided it was not worth offering unprompted.
        """
        settings = _factory_settings(non_returnable=[WATER], min_return_qty=0.01)
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


if __name__ == "__main__":
    unittest.main()
