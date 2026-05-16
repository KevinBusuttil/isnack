import unittest
from unittest.mock import MagicMock

from isnack.overrides.item import sync_weight_per_unit


class TestSyncWeightPerUnit(unittest.TestCase):
    def _make_doc(
        self,
        *,
        is_new,
        net_weight,
        tare_weight,
        previous_net_weight=None,
        previous_tare_weight=None,
        weight_per_unit=None,
    ):
        doc = MagicMock()
        values = {
            "custom_net_weight_per_unit": net_weight,
            "custom_tare_weight_per_unit": tare_weight,
        }
        previous_values = {
            "custom_net_weight_per_unit": previous_net_weight,
            "custom_tare_weight_per_unit": previous_tare_weight,
        }

        doc.get.side_effect = lambda key: values.get(key)
        doc.is_new.return_value = is_new
        doc.weight_per_unit = weight_per_unit

        if is_new:
            doc.get_doc_before_save.return_value = None
        else:
            previous_doc = MagicMock()
            previous_doc.get.side_effect = lambda key: previous_values.get(key)
            doc.get_doc_before_save.return_value = previous_doc

        return doc

    def test_new_item_syncs_weight_when_net_or_tare_is_set(self):
        doc = self._make_doc(is_new=True, net_weight=10.5, tare_weight=1.25)
        sync_weight_per_unit(doc)
        self.assertEqual(doc.weight_per_unit, 11.75)

    def test_existing_item_syncs_weight_when_net_changes(self):
        doc = self._make_doc(
            is_new=False,
            net_weight=9.0,
            tare_weight=1.0,
            previous_net_weight=8.0,
            previous_tare_weight=1.0,
            weight_per_unit=99.0,
        )
        sync_weight_per_unit(doc)
        self.assertEqual(doc.weight_per_unit, 10.0)

    def test_existing_item_syncs_weight_when_tare_changes(self):
        doc = self._make_doc(
            is_new=False,
            net_weight=9.0,
            tare_weight=2.0,
            previous_net_weight=9.0,
            previous_tare_weight=1.0,
            weight_per_unit=99.0,
        )
        sync_weight_per_unit(doc)
        self.assertEqual(doc.weight_per_unit, 11.0)

    def test_existing_item_does_not_sync_when_components_unchanged(self):
        doc = self._make_doc(
            is_new=False,
            net_weight=9.0,
            tare_weight=1.0,
            previous_net_weight=9.0,
            previous_tare_weight=1.0,
            weight_per_unit=123.45,
        )
        sync_weight_per_unit(doc)
        self.assertEqual(doc.weight_per_unit, 123.45)


if __name__ == "__main__":
    unittest.main()
