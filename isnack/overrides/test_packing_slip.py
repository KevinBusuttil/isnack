import unittest
from types import SimpleNamespace
from unittest.mock import patch

from isnack.overrides.packing_slip import CustomPackingSlip


# Item master weight values keyed by item_code, mirroring the synced
# weight_per_unit (= net + tare) maintained by isnack.overrides.item.
ITEM_WEIGHTS = {
    "FG10002": {
        "custom_net_weight_per_unit": 0.840,
        "weight_per_unit": 1.170,
        "weight_uom": "Kg",
        "item_group": "Finished Goods",
    },
    # A pallet: all of its weight is tare, so it has no net weight of its own.
    "PM40020": {
        "custom_net_weight_per_unit": 0,
        "weight_per_unit": 25.0,
        "weight_uom": "Kg",
        "item_group": "Packaging Materials",
    },
}


def _fake_get_value(doctype, item_code, fields):
    data = ITEM_WEIGHTS[item_code]
    if isinstance(fields, str):
        return data[fields]
    return [data[f] for f in fields]


class TestPackingSlipWeights(unittest.TestCase):
    def _make_slip(self, items):
        slip = CustomPackingSlip.__new__(CustomPackingSlip)
        slip.items = [SimpleNamespace(**item) for item in items]
        slip.from_case_no = 1
        return slip

    def _calculate(self, slip, packaging_groups=frozenset()):
        with patch("isnack.overrides.packing_slip.frappe.db.get_value", _fake_get_value), patch(
            "isnack.overrides.packing_slip.get_packaging_item_groups",
            return_value=set(packaging_groups),
        ):
            slip.calculate_net_total_pkg()

    def test_net_weight_uses_custom_net_weight_per_unit(self):
        slip = self._make_slip(
            [{"item_code": "FG10002", "qty": 250, "net_weight": None, "weight_uom": None}]
        )
        with patch("isnack.overrides.packing_slip.frappe.db.get_value", _fake_get_value):
            slip.set_missing_values()
        self._calculate(slip)

        self.assertEqual(slip.items[0].net_weight, 0.840)
        self.assertEqual(slip.net_weight_pkg, 210.00)
        self.assertEqual(slip.gross_weight_pkg, 292.50)

    def test_gross_always_recomputed_from_weight_per_unit(self):
        slip = self._make_slip(
            [{"item_code": "FG10002", "qty": 250, "net_weight": 0.840, "weight_uom": "Kg"}]
        )
        slip.gross_weight_pkg = 999.0
        self._calculate(slip)

        self.assertEqual(slip.gross_weight_pkg, 292.50)

    def test_zero_net_weight_is_not_replaced_by_the_gross_weight(self):
        """An explicit 0 must survive; only an unset net weight falls back."""
        slip = self._make_slip(
            [{"item_code": "PM40020", "qty": 27, "net_weight": None, "weight_uom": None}]
        )
        with patch("isnack.overrides.packing_slip.frappe.db.get_value", _fake_get_value):
            slip.set_missing_values()

        self.assertEqual(slip.items[0].net_weight, None)

    def test_packaging_group_excluded_from_net_but_kept_in_gross(self):
        slip = self._make_slip(
            [
                {"item_code": "FG10002", "qty": 250, "net_weight": 0.840, "weight_uom": "Kg"},
                {"item_code": "PM40020", "qty": 27, "net_weight": 25.0, "weight_uom": "Kg"},
            ]
        )
        self._calculate(slip, packaging_groups={"Packaging Materials"})

        # The pallet row is zeroed so the printed per-row column still sums to
        # the printed total.
        self.assertEqual(slip.items[1].net_weight, 0)
        self.assertEqual(slip.net_weight_pkg, 210.00)
        self.assertEqual(slip.gross_weight_pkg, 292.50 + 675.00)

    def test_packaging_counts_towards_net_when_no_groups_configured(self):
        """Empty setting keeps the previous behaviour."""
        slip = self._make_slip(
            [
                {"item_code": "FG10002", "qty": 250, "net_weight": 0.840, "weight_uom": "Kg"},
                {"item_code": "PM40020", "qty": 27, "net_weight": 25.0, "weight_uom": "Kg"},
            ]
        )
        self._calculate(slip)

        self.assertEqual(slip.items[1].net_weight, 25.0)
        self.assertEqual(slip.net_weight_pkg, 210.00 + 675.00)
        self.assertEqual(slip.gross_weight_pkg, 292.50 + 675.00)


if __name__ == "__main__":
    unittest.main()
