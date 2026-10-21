# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import unittest
from unittest.mock import MagicMock, patch

import frappe
from isnack.api.mes_ops import (
    _find_eligible_surplus_ses,
    _claim_surplus_for_sweep,
    _sweep_surplus_to_wip,
    _create_surplus_wip_transfer,
)


class TestFindEligibleSurplus(unittest.TestCase):
    @patch("frappe.db.sql")
    def test_query_filters_surplus_unswept_and_staging_match(self, mock_sql):
        mock_sql.return_value = [{"name": "SE-SURPLUS-1"}]

        result = _find_eligible_surplus_ses("WO1", "Stage-A")

        self.assertEqual(result, ["SE-SURPLUS-1"])
        query = mock_sql.call_args[0][0]
        params = mock_sql.call_args[0][1]
        # Only surplus, only unswept, only matching staging warehouse.
        self.assertIn("coalesce(se.custom_is_surplus, 0) = 1", query)
        self.assertIn("coalesce(se.custom_surplus_swept_to_wip, 0) = 0", query)
        self.assertIn("se.to_warehouse = %(staging_wh)s", query)
        # Membership via the new child table.
        self.assertIn("`tabSurplus Originating Work Order`", query)
        # Legacy fallback to the single originating WO field.
        self.assertIn("se.custom_originating_work_order = %(work_order)s", query)
        self.assertEqual(params["work_order"], "WO1")
        self.assertEqual(params["staging_wh"], "Stage-A")

    @patch("frappe.db.sql")
    def test_no_staging_returns_empty_without_query(self, mock_sql):
        self.assertEqual(_find_eligible_surplus_ses("WO1", None), [])
        mock_sql.assert_not_called()


class TestClaimSurplusForSweep(unittest.TestCase):
    @patch("frappe.utils.now_datetime", return_value="2026-05-28 10:00:00")
    @patch("frappe.db")
    def test_claim_succeeds_when_one_row_affected(self, mock_db, _now):
        mock_db._cursor.rowcount = 1

        self.assertTrue(_claim_surplus_for_sweep("SE-1", "WO1"))
        mock_db.sql.assert_called_once()
        query = mock_db.sql.call_args[0][0]
        # Conditional update guards against double-sweep.
        self.assertIn("set custom_surplus_swept_to_wip = 1", query)
        self.assertIn("where name = %(name)s", query)
        self.assertIn("coalesce(custom_surplus_swept_to_wip, 0) = 0", query)

    @patch("frappe.utils.now_datetime", return_value="2026-05-28 10:00:00")
    @patch("frappe.db")
    def test_claim_fails_when_no_row_affected(self, mock_db, _now):
        mock_db._cursor.rowcount = 0
        self.assertFalse(_claim_surplus_for_sweep("SE-1", "WO1"))


class TestSweepSurplusToWip(unittest.TestCase):
    @patch("isnack.api.mes_ops._create_surplus_wip_transfer", return_value="MAT-STE-NEW")
    @patch("isnack.api.mes_ops._claim_surplus_for_sweep", return_value=True)
    @patch("isnack.api.mes_ops._find_eligible_surplus_ses", return_value=["SE-SURPLUS-1"])
    @patch("frappe.db.set_value")
    def test_sweeps_and_links_transfer_when_claim_won(
        self, mock_set_value, _find, mock_claim, mock_create
    ):
        wo = MagicMock()
        wo.company = "Test Co"

        created = _sweep_surplus_to_wip("WO1", "Stage-A", "WIP-A", wo)

        self.assertEqual(created, ["MAT-STE-NEW"])
        mock_claim.assert_called_once_with("SE-SURPLUS-1", "WO1")
        mock_create.assert_called_once()
        mock_set_value.assert_called_once_with(
            "Stock Entry", "SE-SURPLUS-1", "custom_surplus_wip_transfer", "MAT-STE-NEW",
            update_modified=False,
        )

    @patch("isnack.api.mes_ops._create_surplus_wip_transfer")
    @patch("isnack.api.mes_ops._claim_surplus_for_sweep", return_value=False)
    @patch("isnack.api.mes_ops._find_eligible_surplus_ses", return_value=["SE-SURPLUS-1"])
    def test_does_not_sweep_when_claim_lost(self, _find, mock_claim, mock_create):
        """Scenario C: surplus already swept by an earlier WO start is not moved again."""
        wo = MagicMock()
        wo.company = "Test Co"

        created = _sweep_surplus_to_wip("WO2", "Stage-A", "WIP-A", wo)

        self.assertEqual(created, [])
        mock_create.assert_not_called()

    @patch("isnack.api.mes_ops._find_eligible_surplus_ses")
    def test_no_warehouses_returns_empty(self, mock_find):
        wo = MagicMock()
        self.assertEqual(_sweep_surplus_to_wip("WO1", None, "WIP-A", wo), [])
        self.assertEqual(_sweep_surplus_to_wip("WO1", "Stage-A", None, wo), [])
        mock_find.assert_not_called()

    @patch("isnack.api.mes_ops.frappe.log_error")
    @patch("isnack.api.mes_ops._create_surplus_wip_transfer", side_effect=Exception("boom"))
    @patch("isnack.api.mes_ops._claim_surplus_for_sweep", return_value=True)
    @patch("isnack.api.mes_ops._find_eligible_surplus_ses", return_value=["SE-SURPLUS-1"])
    @patch("frappe.db.set_value")
    def test_failed_transfer_rolls_back_claim(
        self, mock_set_value, _find, _claim, _create, mock_log
    ):
        """A transfer can fail part-way through submit, after some ledger rows
        are written. Rolling back to a savepoint taken before the claim undoes
        the claim and every partial row together, so the surplus can be retried
        and nothing half-posted is committed with the rest of the request."""
        wo = MagicMock()
        wo.company = "Test Co"
        with patch("isnack.api.mes_ops.frappe.db.savepoint") as mock_savepoint, \
                patch("isnack.api.mes_ops.frappe.db.rollback") as mock_rollback, \
                patch("isnack.api.mes_ops.frappe.db.release_savepoint") as mock_release:
            created = _sweep_surplus_to_wip("WO1", "Stage-A", "WIP-A", wo)

        self.assertEqual(created, [])
        save_point = mock_savepoint.call_args[0][0]
        mock_rollback.assert_called_once_with(save_point=save_point)
        mock_release.assert_not_called()
        # The savepoint takes the claim back; no separate reset is written.
        mock_set_value.assert_not_called()
        mock_log.assert_called_once()

    @patch("isnack.api.mes_ops.frappe.log_error")
    @patch("isnack.api.mes_ops._claim_surplus_for_sweep", return_value=True)
    @patch("isnack.api.mes_ops._find_eligible_surplus_ses", return_value=["SE-SURPLUS-1"])
    def test_failed_transfer_does_not_leave_its_popup_on_the_response(self, _find, _claim, _log):
        """The failed submit queued "Batch No … has negative stock" for the
        client. With nothing of it left in the ledger, a successful close must
        not show it."""
        wo = MagicMock()
        wo.company = "Test Co"
        frappe.local.message_log = ["earlier message"]

        def fail(*_a, **_k):
            frappe.local.message_log.append("Batch No jimm0709 has negative stock")
            raise frappe.ValidationError("negative stock")

        try:
            with patch("isnack.api.mes_ops._create_surplus_wip_transfer", side_effect=fail), \
                    patch("isnack.api.mes_ops.frappe.db.savepoint"), \
                    patch("isnack.api.mes_ops.frappe.db.rollback"), \
                    patch("isnack.api.mes_ops.frappe.db.release_savepoint"):
                _sweep_surplus_to_wip("WO1", "Stage-A", "WIP-A", wo)
            self.assertEqual(frappe.local.message_log, ["earlier message"])
        finally:
            frappe.local.message_log = []

    @patch("isnack.api.mes_ops._create_surplus_wip_transfer", return_value="MAT-STE-NEW")
    @patch("isnack.api.mes_ops._find_eligible_surplus_ses", return_value=["SE-A", "SE-B"])
    @patch("frappe.db.set_value")
    def test_each_surplus_gets_its_own_savepoint(self, _set_value, _find, _create):
        """A lost claim and a successful transfer both release their savepoint;
        neither rolls anything back."""
        wo = MagicMock()
        wo.company = "Test Co"
        with patch("isnack.api.mes_ops._claim_surplus_for_sweep", side_effect=[False, True]), \
                patch("isnack.api.mes_ops.frappe.db.savepoint") as mock_savepoint, \
                patch("isnack.api.mes_ops.frappe.db.rollback") as mock_rollback, \
                patch("isnack.api.mes_ops.frappe.db.release_savepoint") as mock_release:
            created = _sweep_surplus_to_wip("WO1", "Stage-A", "WIP-A", wo)

        self.assertEqual(created, ["MAT-STE-NEW"])
        taken = [c[0][0] for c in mock_savepoint.call_args_list]
        self.assertEqual(len(set(taken)), 2)
        self.assertEqual([c[0][0] for c in mock_release.call_args_list], taken)
        mock_rollback.assert_not_called()


class TestCreateSurplusWipTransfer(unittest.TestCase):
    @patch("frappe.new_doc")
    @patch("frappe.db.sql")
    def test_builds_plain_material_transfer_with_batches(self, mock_sql, mock_new_doc):
        # frappe.db.sql(as_dict=True) returns frappe._dict rows, read by attribute.
        mock_sql.return_value = [
            frappe._dict({"item_code": "ITEM-X", "batch_no": "B1", "uom": "Kg", "qty": 12.65}),
        ]
        se = MagicMock()
        se.name = "MAT-STE-NEW"
        se.items = []
        se.append = lambda table, d: se.items.append(d)
        mock_new_doc.return_value = se

        result = _create_surplus_wip_transfer(
            "SE-SURPLUS-1", "WO1", "Stage-A", "WIP-A", "Test Co"
        )

        self.assertEqual(result, "MAT-STE-NEW")
        # Plain Material Transfer, NOT Material Transfer for Manufacture.
        self.assertEqual(se.purpose, "Material Transfer")
        self.assertEqual(se.stock_entry_type, "Material Transfer")
        self.assertEqual(se.from_warehouse, "Stage-A")
        self.assertEqual(se.to_warehouse, "WIP-A")
        self.assertEqual(len(se.items), 1)
        row = se.items[0]
        self.assertEqual(row["item_code"], "ITEM-X")
        self.assertEqual(row["qty"], 12.65)
        self.assertEqual(row["s_warehouse"], "Stage-A")
        self.assertEqual(row["t_warehouse"], "WIP-A")
        self.assertEqual(row["batch_no"], "B1")
        self.assertEqual(row["use_serial_batch_fields"], 1)
        se.insert.assert_called_once()
        se.submit.assert_called_once()

    @patch("frappe.new_doc")
    @patch("frappe.db.sql", return_value=[])
    def test_returns_none_when_no_rows(self, _sql, mock_new_doc):
        self.assertIsNone(
            _create_surplus_wip_transfer("SE-1", "WO1", "Stage-A", "WIP-A", "Test Co")
        )
        mock_new_doc.assert_not_called()


if __name__ == "__main__":
    unittest.main()
