# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""Unit tests for the QC record schema the FSSC 22000 changes rely on (no database)."""

import json
import os
import unittest
from unittest.mock import patch

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
	def test_every_record_type_after_receiving(self):
		for code, doctype in QC_DOCTYPES.items():
			if code == "QCA":
				continue
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
