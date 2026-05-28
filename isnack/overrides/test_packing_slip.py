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

    def test_net_weight_uses_custom_net_weight_per_unit(self):
        slip = self._make_slip(
            [{"item_code": "FG10002", "qty": 250, "net_weight": None, "weight_uom": None}]
        )
        with patch("isnack.overrides.packing_slip.frappe.db.get_value", _fake_get_value):
            slip.set_missing_values()
            slip.calculate_net_total_pkg()

        self.assertEqual(slip.items[0].net_weight, 0.840)
        self.assertEqual(slip.net_weight_pkg, 210.00)
        self.assertEqual(slip.gross_weight_pkg, 292.50)

    def test_gross_always_recomputed_from_weight_per_unit(self):
        slip = self._make_slip(
            [{"item_code": "FG10002", "qty": 250, "net_weight": 0.840, "weight_uom": "Kg"}]
        )
        slip.gross_weight_pkg = 999.0
        with patch("isnack.overrides.packing_slip.frappe.db.get_value", _fake_get_value):
            slip.calculate_net_total_pkg()

        self.assertEqual(slip.gross_weight_pkg, 292.50)


if __name__ == "__main__":
    unittest.main()
