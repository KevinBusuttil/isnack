# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""Unit tests for the QC record schema the FSSC 22000 changes rely on (no database)."""

import json
import os
import unittest
from unittest.mock import patch

import frappe
from isnack.isnack.page.quality_hub import quality_hub as qh
from isnack.isnack.page.quality_hub.quality_hub import QC_DOCTYPES
from isnack.patches.v1_0 import qc_receiving_yes_no_checks as patch_module

DOCTYPE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "doctype")


def _doctype(name):
	folder = name.lower().replace(" ", "_")
	with open(os.path.join(DOCTYPE_DIR, folder, f"{folder}.json")) as fh:
		return json.load(fh)


def _fields(doc):
	return {f["fieldname"]: f for f in doc["fields"]}


class TestReceivingRecordSchema(unittest.TestCase):
	def setUp(self):
		self.doc = _doctype("QC Receiving Record")
		self.fields = _fields(self.doc)

	def test_no_line_or_work_order(self):
		# a delivery is inspected before any line or Work Order touches it
		for fieldname in ("factory_line", "work_order"):
			self.assertNotIn(fieldname, self.fields)
			self.assertNotIn(fieldname, self.doc["field_order"])

	def test_supplier_and_item_section_is_mandatory(self):
		for fieldname in ("supplier", "purchase_receipt", "item_code", "batch_no", "qty_received"):
			self.assertEqual(self.fields[fieldname].get("reqd"), 1, fieldname)

	def test_quality_checks_are_blank_yes_no(self):
		expected = {
			"packaging_intact": "Packaging Intact",
			"labelling_correct": "Labelling Correct",
			"foreign_body_check": "Foreign Body Check",
			"appearance_acceptable": "Appearance Acceptable",
			"dimensions_acceptable": "Dimensions Acceptable",
			"weight_acceptable": "Weight Acceptable",
		}
		for fieldname, label in expected.items():
			field = self.fields[fieldname]
			self.assertEqual((field["fieldtype"], field["label"]), ("Select", label), fieldname)
			self.assertEqual(field["options"], "\nYes\nNo", fieldname)
		self.assertNotIn("colour_acceptable", self.fields)

	def test_field_order_matches_fields(self):
		self.assertEqual(self.doc["field_order"], [f["fieldname"] for f in self.doc["fields"]])


class TestOperatorAndInspectorMandatory(unittest.TestCase):
	def test_every_record_type(self):
		for doctype in QC_DOCTYPES.values():
			fields = _fields(_doctype(doctype))
			for fieldname in ("operator_name", "qc_inspector"):
				self.assertEqual(fields[fieldname].get("reqd"), 1, f"{doctype}.{fieldname}")


class TestReceivingChecksPatch(unittest.TestCase):
	@patch.object(patch_module, "rename_field")
	@patch("frappe.db.sql")
	@patch("frappe.db.has_column", return_value=True)
	@patch("frappe.db.table_exists", return_value=True)
	def test_ticked_becomes_yes_and_unticked_blank(self, _exists, _has_column, sql, rename):
		patch_module.execute()

		rename.assert_called_once_with("QC Receiving Record", "colour_acceptable", "appearance_acceptable")
		queries = [" ".join(c.args[0].split()) for c in sql.call_args_list]
		self.assertEqual(len(queries), 4)
		for fieldname, query in zip(patch_module.FORMER_CHECKS, queries):
			self.assertIn(f"SET `{fieldname}` = CASE WHEN `{fieldname}` = '1' THEN 'Yes' ELSE NULL END", query)
			self.assertIn(f"WHERE `{fieldname}` IN ('0', '1')", query)

	@patch.object(patch_module, "rename_field")
	@patch("frappe.db.sql")
	@patch("frappe.db.has_column", return_value=False)
	@patch("frappe.db.table_exists", return_value=True)
	def test_new_site_has_nothing_to_rename(self, _exists, _has_column, sql, rename):
		patch_module.execute()
		rename.assert_not_called()
		self.assertEqual(sql.call_count, 4)


class TestRecordLists(unittest.TestCase):
	@patch("frappe.get_all")
	@patch("frappe.get_list", return_value=[])
	@patch("frappe.get_meta")
	@patch("frappe.db.table_exists", return_value=True)
	@patch("frappe.has_permission", return_value=True)
	def test_lists_read_the_doctype_with_the_users_permissions(self, _perm, table_exists, get_meta, get_list, get_all):
		get_meta.return_value.fields = [frappe._dict(fieldname=f) for f in ("record_date", "supplier", "batch_no")]

		qh.get_qc_records("QC Receiving Record")

		# Database.table_exists adds the "tab" prefix itself
		table_exists.assert_called_once_with("QC Receiving Record")
		# get_list applies the user's User Permissions; get_all would not
		get_all.assert_not_called()
		self.assertFalse(get_list.call_args.kwargs.get("ignore_permissions"))
		self.assertEqual(get_list.call_args.args[0], "QC Receiving Record")
		self.assertIn("supplier", get_list.call_args.kwargs["fields"])
		self.assertIn("batch_no", get_list.call_args.kwargs["fields"])

	@patch("frappe.get_list")
	@patch("frappe.has_permission", return_value=False)
	def test_lists_need_read_permission(self, _perm, get_list):
		with self.assertRaises(frappe.PermissionError):
			qh.get_qc_records("QC Receiving Record")
		get_list.assert_not_called()

	@patch("frappe.db.count")
	@patch("frappe.get_list")
	@patch("frappe.db.table_exists", return_value=True)
	@patch("frappe.has_permission")
	def test_summary_and_matrix_count_what_the_user_may_read(self, perm, table_exists, get_list, count):
		perm.side_effect = lambda doctype, ptype: doctype != "QC Tasting Record"
		day = {
			"QC Receiving Record": [
				frappe._dict(shift="Morning", docstatus=1),
				frappe._dict(shift="Morning", docstatus=0),
				frappe._dict(shift="Night", docstatus=0),
			],
		}
		get_list.side_effect = lambda doctype, **_kw: day.get(doctype, [])

		summary = qh.get_qc_record_summary("2026-10-25")
		matrix = qh.get_completion_matrix("2026-10-25")["matrix"]

		self.assertEqual(
			{k: summary["QCA"][k] for k in ("total", "submitted", "draft", "hidden")},
			{"total": 3, "submitted": 1, "draft": 2, "hidden": False},
		)
		self.assertEqual((summary["QCF"]["total"], summary["QCF"]["hidden"]), (0, True))
		self.assertEqual(
			(matrix["Morning"]["QCA"], matrix["Night"]["QCA"], matrix["Afternoon"]["QCA"]),
			("submitted", "draft", "not_started"),
		)
		self.assertEqual({matrix[s]["QCF"] for s in matrix}, {"hidden"})
		# counted through get_list, which applies the user's User Permissions
		count.assert_not_called()
		for call in get_list.call_args_list:
			self.assertEqual(call.kwargs["filters"], {"record_date": "2026-10-25"})
		# Database.table_exists adds the "tab" prefix itself
		for call in table_exists.call_args_list:
			self.assertIn(call.args[0], QC_DOCTYPES.values())


class TestReceivingBatchPicker(unittest.TestCase):
	@patch("frappe.db.sql", return_value=[])
	def test_finds_batches_on_the_row_and_in_its_bundle(self, sql):
		qh.get_batches_for_receiving("Batch", "", "name", 0, 20, {"purchase_receipt": "PR-1", "item_code": "RM1"})

		query = " ".join(sql.call_args.args[0].split())
		self.assertIn("pri.batch_no = b.name", query)
		# v15 keeps a received batch in the row's Serial and Batch Bundle, a
		# rejected one in the row's rejected bundle
		self.assertIn(
			"JOIN `tabSerial and Batch Entry` sbe"
			" ON sbe.parent IN (pri.serial_and_batch_bundle, pri.rejected_serial_and_batch_bundle)",
			query,
		)
		self.assertIn("sbe.batch_no = b.name", query)
		self.assertEqual(sql.call_args.args[1]["purchase_receipt"], "PR-1")
