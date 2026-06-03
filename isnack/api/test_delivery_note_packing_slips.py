# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import types
import unittest
from unittest.mock import patch

from isnack.api import delivery_note_packing_slips as dnps


class _Row:
    """Minimal stand-in for a Delivery Note Item / Packed Item child document."""

    def __init__(self, **values):
        self.__dict__.update(values)

    def get(self, key, default=None):
        return self.__dict__.get(key, default)


class _FakeDN:
    """Minimal stand-in for a Delivery Note document."""

    def __init__(self, name="DN-0001", items=None, packed_items=None,
                 is_return=0, letter_head=None):
        self.name = name
        self.items = items or []
        self.packed_items = packed_items or []
        self.is_return = is_return
        self.letter_head = letter_head

    def get(self, key, default=None):
        return getattr(self, key, default)


class _FakePackingSlip:
    """Minimal stand-in for a new Packing Slip document."""

    def __init__(self):
        self.items = []
        self.flags = types.SimpleNamespace()
        self.name = "MAT-PAC-2026-00001"
        self.submitted = False

    def append(self, table, values):
        row = _Row(**values)
        getattr(self, table).append(row)
        return row

    def get(self, key, default=None):
        return getattr(self, key, default)

    def insert(self):
        pass

    def submit(self):
        self.submitted = True


def _dn_item(name, item_code, qty, sales_order=None, **extra):
    base = dict(
        name=name,
        item_code=item_code,
        item_name=item_code,
        description=item_code,
        qty=qty,
        packed_qty=0,
        uom="Carton",
        against_sales_order=sales_order,
        batch_no=None,
    )
    base.update(extra)
    return _Row(**base)


def _stock_item_lookup(*_args, **_kwargs):
    """Default frappe.db.get_value stub treating every Item as a stock item."""
    return {"is_stock_item": 1, "item_group": "Finished Goods"}


class TestBuildGroups(unittest.TestCase):
    """Grouping of Delivery Note rows by Sales Order."""

    @patch("isnack.api.delivery_note_packing_slips.frappe.db.get_value",
           side_effect=_stock_item_lookup)
    @patch.object(dnps, "_is_product_bundle", return_value=False)
    def test_two_sales_orders_two_groups(self, _bundle, _get_value):
        dn = _FakeDN(items=[
            _dn_item("r1", "A", 10, "SO-0001"),
            _dn_item("r2", "B", 5, "SO-0001"),
            _dn_item("r3", "C", 7, "SO-0002"),
        ])
        groups = dnps._build_groups(dn)
        self.assertEqual(list(groups.keys()), ["SO-0001", "SO-0002"])
        self.assertEqual(len(groups["SO-0001"]["dn_items"]), 2)
        self.assertEqual(len(groups["SO-0002"]["dn_items"]), 1)

    @patch("isnack.api.delivery_note_packing_slips.frappe.db.get_value",
           side_effect=_stock_item_lookup)
    @patch.object(dnps, "_is_product_bundle", return_value=False)
    def test_rows_without_sales_order_use_fallback_key(self, _bundle, _get_value):
        dn = _FakeDN(items=[_dn_item("r1", "A", 10, None)])
        groups = dnps._build_groups(dn)
        self.assertEqual(list(groups.keys()), [dnps.NO_SALES_ORDER_KEY])
        # The fallback group carries no Sales Order link value.
        self.assertIsNone(groups[dnps.NO_SALES_ORDER_KEY]["sales_order"])

    @patch.object(dnps, "_is_product_bundle", return_value=False)
    def test_zero_qty_rows_are_skipped(self, _bundle):
        dn = _FakeDN(items=[
            _dn_item("r1", "A", 0, "SO-0001"),
            _dn_item("r2", "B", -3, "SO-0001"),
        ])
        self.assertEqual(dnps._build_groups(dn), {})

    def test_product_bundle_parent_is_skipped(self):
        dn = _FakeDN(items=[_dn_item("r1", "BUNDLE", 10, "SO-0001")])
        with patch.object(dnps, "_is_product_bundle", return_value=True):
            self.assertEqual(dnps._build_groups(dn), {})

    @patch("isnack.api.delivery_note_packing_slips.frappe.db.get_value",
           side_effect=_stock_item_lookup)
    @patch.object(dnps, "_is_product_bundle", return_value=False)
    def test_packed_items_inherit_parent_sales_order(self, _bundle, _get_value):
        dn = _FakeDN(
            items=[_dn_item("r1", "BUNDLE", 1, "SO-0009")],
            packed_items=[
                _Row(name="p1", item_code="COMP-A", qty=4,
                     packed_qty=0, uom="Nos", parent_detail_docname="r1"),
            ],
        )
        # The bundle parent itself is skipped, but its component is grouped
        # under the parent row's Sales Order.
        with patch.object(dnps, "_is_product_bundle",
                          side_effect=lambda code: code == "BUNDLE"):
            groups = dnps._build_groups(dn)
        self.assertEqual(list(groups.keys()), ["SO-0009"])
        self.assertEqual(len(groups["SO-0009"]["packed_items"]), 1)


class TestIsPackableDnItem(unittest.TestCase):
    """Filter that keeps services / non-stock rows out of Packing Slips."""

    @patch("isnack.api.delivery_note_packing_slips.frappe.db.get_value")
    @patch.object(dnps, "_is_product_bundle", return_value=False)
    def test_stock_finished_good_is_packable(self, _bundle, mock_get_value):
        mock_get_value.return_value = {
            "is_stock_item": 1,
            "item_group": "Finished Goods",
        }
        item = _dn_item("r1", "FG10005", 10, "SO-0001")
        self.assertTrue(dnps._is_packable_dn_item(item))

    @patch("isnack.api.delivery_note_packing_slips.frappe.db.get_value")
    @patch.object(dnps, "_is_product_bundle", return_value=False)
    def test_non_stock_service_row_is_excluded(self, _bundle, mock_get_value):
        mock_get_value.return_value = {
            "is_stock_item": 0,
            "item_group": "Services",
        }
        item = _dn_item("r1", "Delivery Charges", 1, "SO-0001")
        self.assertFalse(dnps._is_packable_dn_item(item))

    @patch("isnack.api.delivery_note_packing_slips.frappe.db.get_value")
    @patch.object(dnps, "_is_product_bundle", return_value=False)
    def test_stock_item_in_services_group_is_excluded(self, _bundle, mock_get_value):
        # Defensive: even a misconfigured stock item filed under Services must
        # be kept out of the Packing Slip.
        mock_get_value.return_value = {
            "is_stock_item": 1,
            "item_group": "Services",
        }
        item = _dn_item("r1", "ODD", 1, "SO-0001")
        self.assertFalse(dnps._is_packable_dn_item(item))

    @patch("isnack.api.delivery_note_packing_slips.frappe.db.get_value")
    @patch.object(dnps, "_is_product_bundle", return_value=False)
    def test_promotional_marketing_services_group_is_excluded(
        self, _bundle, mock_get_value
    ):
        mock_get_value.return_value = {
            "is_stock_item": 1,
            "item_group": "Promotional & Marketing Services",
        }
        item = _dn_item("r1", "PMS10001", 1, "SO-0001")
        self.assertFalse(dnps._is_packable_dn_item(item))

    @patch("isnack.api.delivery_note_packing_slips.frappe.db.get_value",
           return_value=None)
    @patch.object(dnps, "_is_product_bundle", return_value=False)
    def test_missing_item_record_is_excluded(self, _bundle, _get_value):
        item = _dn_item("r1", "GHOST", 1, "SO-0001")
        self.assertFalse(dnps._is_packable_dn_item(item))

    @patch("isnack.api.delivery_note_packing_slips.frappe.db.get_value",
           side_effect=_stock_item_lookup)
    def test_product_bundle_parent_is_not_packable(self, _get_value):
        item = _dn_item("r1", "BUNDLE", 1, "SO-0001")
        with patch.object(dnps, "_is_product_bundle", return_value=True):
            self.assertFalse(dnps._is_packable_dn_item(item))


class TestBuildGroupsExcludesServices(unittest.TestCase):
    """Service rows must never reach the Packing Slip via _build_groups."""

    def test_mixed_stock_and_service_rows(self):
        dn = _FakeDN(items=[
            _dn_item("r1", "FG10005", 10, "SO-0001"),
            _dn_item("r2", "Delivery Charges", 1, "SO-0001"),
        ])

        lookups = {
            "FG10005": {"is_stock_item": 1, "item_group": "Finished Goods"},
            "Delivery Charges": {"is_stock_item": 0, "item_group": "Services"},
        }

        with patch.object(dnps, "_is_product_bundle", return_value=False), \
             patch("isnack.api.delivery_note_packing_slips.frappe.db.get_value",
                   side_effect=lambda _dt, code, *a, **kw: lookups.get(code)):
            groups = dnps._build_groups(dn)

        self.assertEqual(list(groups.keys()), ["SO-0001"])
        codes = [r.item_code for r in groups["SO-0001"]["dn_items"]]
        self.assertEqual(codes, ["FG10005"])
        self.assertNotIn("Delivery Charges", codes)

    def test_service_only_delivery_note_yields_no_groups(self):
        dn = _FakeDN(items=[
            _dn_item("r1", "Delivery Charges", 1, "SO-0001"),
        ])
        with patch.object(dnps, "_is_product_bundle", return_value=False), \
             patch("isnack.api.delivery_note_packing_slips.frappe.db.get_value",
                   return_value={"is_stock_item": 0, "item_group": "Services"}):
            self.assertEqual(dnps._build_groups(dn), {})

    @patch.object(dnps, "_create_and_submit_packing_slip")
    @patch.object(dnps, "_check_existing_packing_slips", return_value="create")
    @patch.object(dnps, "_auto_create_enabled", return_value=True)
    def test_service_only_dn_creates_no_packing_slip(
        self, _enabled, _check, mock_create
    ):
        dn = _FakeDN(items=[_dn_item("r1", "Delivery Charges", 1, "SO-0001")])
        with patch.object(dnps, "_is_product_bundle", return_value=False), \
             patch("isnack.api.delivery_note_packing_slips.frappe.db.get_value",
                   return_value={"is_stock_item": 0, "item_group": "Services"}):
            dnps.auto_create_packing_slips_before_submit(dn)
        mock_create.assert_not_called()


class TestCheckExistingPackingSlips(unittest.TestCase):
    """Idempotency / duplicate-protection logic."""

    @patch("isnack.api.delivery_note_packing_slips.frappe.get_all")
    def test_no_existing_returns_create(self, mock_get_all):
        mock_get_all.return_value = []
        dn = _FakeDN()
        self.assertEqual(
            dnps._check_existing_packing_slips(dn, {"DN-0001|SO-0001"}), "create"
        )

    @patch("isnack.api.delivery_note_packing_slips.frappe.get_all")
    def test_complete_auto_set_returns_already_done(self, mock_get_all):
        mock_get_all.return_value = [
            _Row(name="PS-1", docstatus=1,
                 custom_auto_created_from_delivery_note=1,
                 custom_auto_creation_reference="DN-0001|SO-0001"),
            _Row(name="PS-2", docstatus=1,
                 custom_auto_created_from_delivery_note=1,
                 custom_auto_creation_reference="DN-0001|SO-0002"),
        ]
        dn = _FakeDN()
        result = dnps._check_existing_packing_slips(
            dn, {"DN-0001|SO-0001", "DN-0001|SO-0002"}
        )
        self.assertEqual(result, "already_done")

    @patch("isnack.api.delivery_note_packing_slips.frappe.throw",
           side_effect=Exception("thrown"))
    @patch("isnack.api.delivery_note_packing_slips.frappe.get_all")
    def test_manual_packing_slip_blocks_creation(self, mock_get_all, _throw):
        mock_get_all.return_value = [
            _Row(name="PS-MANUAL", docstatus=1,
                 custom_auto_created_from_delivery_note=0,
                 custom_auto_creation_reference=None),
        ]
        dn = _FakeDN()
        with self.assertRaises(Exception):
            dnps._check_existing_packing_slips(dn, {"DN-0001|SO-0001"})

    @patch("isnack.api.delivery_note_packing_slips.frappe.throw",
           side_effect=Exception("thrown"))
    @patch("isnack.api.delivery_note_packing_slips.frappe.get_all")
    def test_partial_auto_set_blocks_creation(self, mock_get_all, _throw):
        mock_get_all.return_value = [
            _Row(name="PS-1", docstatus=1,
                 custom_auto_created_from_delivery_note=1,
                 custom_auto_creation_reference="DN-0001|SO-0001"),
        ]
        dn = _FakeDN()
        # Two groups expected, only one Packing Slip exists -> unsafe.
        with self.assertRaises(Exception):
            dnps._check_existing_packing_slips(
                dn, {"DN-0001|SO-0001", "DN-0001|SO-0002"}
            )


class TestCreateAndSubmitPackingSlip(unittest.TestCase):
    """Per-group Packing Slip creation, field mapping and packed_qty mirroring."""

    @patch.object(dnps, "enqueue_doc_print")
    @patch("isnack.api.delivery_note_packing_slips.now_datetime",
           return_value="2026-05-22 10:00:00")
    @patch("isnack.api.delivery_note_packing_slips.frappe.new_doc")
    def test_pallet_fields_copied_and_packed_qty_mirrored(
        self, mock_new_doc, _now, mock_enqueue
    ):
        ps = _FakePackingSlip()
        mock_new_doc.return_value = ps

        dn_item = _dn_item(
            "r1", "FG10005", 2000, "SO-0001",
            custom_pallet_type="EURO 1",
            custom_pallet_qty=20,
            custom_pallet_conversion_factor=100,
            custom_pallet_qty_manual=0,
        )
        dn = _FakeDN(items=[dn_item])
        group = {"sales_order": "SO-0001", "dn_items": [dn_item], "packed_items": []}

        name = dnps._create_and_submit_packing_slip(dn, "SO-0001", group, 1)

        self.assertEqual(name, ps.name)
        self.assertTrue(ps.submitted)
        self.assertEqual(ps.delivery_note, "DN-0001")
        self.assertEqual(ps.custom_sales_order, "SO-0001")
        self.assertEqual(ps.custom_auto_created_from_delivery_note, 1)
        self.assertEqual(ps.custom_auto_creation_reference, "DN-0001|SO-0001")
        self.assertEqual(ps.from_case_no, 1)
        self.assertEqual(ps.to_case_no, 1)

        row = ps.items[0]
        self.assertEqual(row.dn_detail, "r1")
        self.assertEqual(row.qty, 2000)
        self.assertEqual(row.custom_pallet_type, "EURO 1")
        self.assertEqual(row.custom_pallet_qty, 20)
        self.assertEqual(row.custom_pallet_conversion_factor, 100)

        # packed_qty must be mirrored onto the in-memory Delivery Note row so it
        # is persisted and the standard validate_packed_qty check passes.
        self.assertEqual(dn_item.packed_qty, 2000)

        # The submitted Packing Slip is dispatched to the A4 printer.
        mock_enqueue.assert_called_once_with("Packing Slip", ps.name)

    @patch.object(dnps, "enqueue_doc_print")
    @patch("isnack.api.delivery_note_packing_slips.now_datetime",
           return_value="2026-05-22 10:00:00")
    @patch("isnack.api.delivery_note_packing_slips.frappe.new_doc")
    def test_no_sales_order_group_leaves_link_blank(self, mock_new_doc, _now, _enqueue):
        ps = _FakePackingSlip()
        mock_new_doc.return_value = ps

        dn_item = _dn_item("r1", "FG10005", 100, None)
        dn = _FakeDN(items=[dn_item])
        group = {"sales_order": None, "dn_items": [dn_item], "packed_items": []}

        dnps._create_and_submit_packing_slip(
            dn, dnps.NO_SALES_ORDER_KEY, group, 1
        )

        # The deterministic group key is only used for the reference string.
        self.assertFalse(hasattr(ps, "custom_sales_order"))
        self.assertEqual(
            ps.custom_auto_creation_reference, "DN-0001|NO-SALES-ORDER"
        )

    @patch("isnack.api.delivery_note_packing_slips.frappe.log_error")
    @patch.object(dnps, "enqueue_doc_print",
                  side_effect=RuntimeError("printer module missing"))
    @patch("isnack.api.delivery_note_packing_slips.now_datetime",
           return_value="2026-05-22 10:00:00")
    @patch("isnack.api.delivery_note_packing_slips.frappe.new_doc")
    def test_print_enqueue_failure_does_not_break_submission(
        self, mock_new_doc, _now, _enqueue, mock_log_error
    ):
        ps = _FakePackingSlip()
        mock_new_doc.return_value = ps

        dn_item = _dn_item("r1", "FG10005", 5, "SO-0001")
        dn = _FakeDN(items=[dn_item])
        group = {"sales_order": "SO-0001", "dn_items": [dn_item], "packed_items": []}

        # The Packing Slip is still returned and packed_qty mirrored even though
        # the print enqueue blew up; the failure is just logged.
        name = dnps._create_and_submit_packing_slip(dn, "SO-0001", group, 1)
        self.assertEqual(name, ps.name)
        self.assertTrue(ps.submitted)
        self.assertEqual(dn_item.packed_qty, 5)
        mock_log_error.assert_called_once()

    @patch.object(dnps, "enqueue_doc_print")
    @patch("isnack.api.delivery_note_packing_slips.now_datetime",
           return_value="2026-05-22 10:00:00")
    @patch("isnack.api.delivery_note_packing_slips.frappe.new_doc")
    def test_packed_item_row_uses_pi_detail(self, mock_new_doc, _now, _enqueue):
        ps = _FakePackingSlip()
        mock_new_doc.return_value = ps

        packed = _Row(name="p1", item_code="COMP-A", item_name="COMP-A",
                      description="COMP-A", qty=4, packed_qty=0, uom="Nos",
                      batch_no=None, parent_detail_docname="r1")
        dn = _FakeDN(packed_items=[packed])
        group = {"sales_order": "SO-0001", "dn_items": [], "packed_items": [packed]}

        dnps._create_and_submit_packing_slip(dn, "SO-0001", group, 2)

        row = ps.items[0]
        self.assertEqual(row.pi_detail, "p1")
        self.assertFalse(hasattr(row, "dn_detail"))
        self.assertEqual(packed.packed_qty, 4)


class TestAutoCreateOrchestration(unittest.TestCase):
    """Top-level before_submit behaviour."""

    @patch.object(dnps, "_create_and_submit_packing_slip")
    @patch.object(dnps, "_auto_create_enabled", return_value=True)
    def test_return_delivery_note_is_skipped(self, _enabled, mock_create):
        dn = _FakeDN(is_return=1, items=[_dn_item("r1", "A", 10, "SO-0001")])
        dnps.auto_create_packing_slips_before_submit(dn)
        mock_create.assert_not_called()

    @patch.object(dnps, "_create_and_submit_packing_slip")
    @patch.object(dnps, "_auto_create_enabled", return_value=False)
    def test_disabled_setting_skips_creation(self, _enabled, mock_create):
        dn = _FakeDN(items=[_dn_item("r1", "A", 10, "SO-0001")])
        dnps.auto_create_packing_slips_before_submit(dn)
        mock_create.assert_not_called()

    @patch.object(dnps, "frappe")
    @patch.object(dnps, "_check_existing_packing_slips", return_value="create")
    @patch.object(dnps, "_is_product_bundle", return_value=False)
    @patch.object(dnps, "_auto_create_enabled", return_value=True)
    def test_one_packing_slip_per_sales_order(
        self, _enabled, _bundle, _check, mock_frappe
    ):
        mock_frappe.db.get_value.side_effect = _stock_item_lookup

        created = []

        def fake_create(doc, group_key, group, case_no):
            created.append((group_key, case_no))
            return f"PS-{case_no}"

        dn = _FakeDN(items=[
            _dn_item("r1", "A", 10, "SO-0001"),
            _dn_item("r2", "B", 7, "SO-0002"),
        ])
        with patch.object(dnps, "_create_and_submit_packing_slip",
                          side_effect=fake_create):
            dnps.auto_create_packing_slips_before_submit(dn)

        self.assertEqual(created, [("SO-0001", 1), ("SO-0002", 2)])

    @patch.object(dnps, "_create_and_submit_packing_slip")
    @patch.object(dnps, "_check_existing_packing_slips", return_value="already_done")
    @patch.object(dnps, "_is_product_bundle", return_value=False)
    @patch.object(dnps, "_auto_create_enabled", return_value=True)
    def test_already_done_does_not_recreate(
        self, _enabled, _bundle, _check, mock_create
    ):
        dn = _FakeDN(items=[_dn_item("r1", "A", 10, "SO-0001")])
        dnps.auto_create_packing_slips_before_submit(dn)
        mock_create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
