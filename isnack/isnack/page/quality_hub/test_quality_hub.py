# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""Unit tests for the QC record schema the FSSC 22000 changes rely on (no database)."""

import json
import os
import unittest
from unittest.mock import MagicMock, patch

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


class TestFryingReadings(unittest.TestCase):
	def test_oil_pv_and_anv_replace_product_temperature(self):
		doc = _doctype("QC Frying Reading")
		fields = _fields(doc)
		order = doc["field_order"]
		self.assertEqual(order, [f["fieldname"] for f in doc["fields"]])
		self.assertNotIn("product_temperature", fields)
		for fieldname, label in (("oil_pv", "Oil (PV)"), ("oil_anv", "Oil (ANV)")):
			self.assertEqual((fields[fieldname]["fieldtype"], fields[fieldname]["label"]), ("Float", label))
		self.assertEqual(order[order.index("oil_tpm") + 1 : order.index("oil_tpm") + 3], ["oil_pv", "oil_anv"])

	def test_moisture_reads_moisture_content(self):
		self.assertEqual(_fields(_doctype("QC Frying Reading"))["product_moisture"]["label"], "Moisture Content (%)")
		self.assertEqual(
			_fields(_doctype("QC Frying Line Record"))["avg_product_moisture"]["label"], "Avg Moisture Content (%)"
		)


class TestOvenReadingsOnTheExtruders(unittest.TestCase):
	EXTRUDERS = ("QC Puffs Extruder Record", "QC Rice Extruder Record")

	def test_an_oven_readings_section_under_the_readings(self):
		for doctype in self.EXTRUDERS:
			doc = _doctype(doctype)
			fields = _fields(doc)
			order = doc["field_order"]
			self.assertEqual(order, [f["fieldname"] for f in doc["fields"]], doctype)
			section = fields["oven_readings_section"]
			self.assertEqual((section["fieldtype"], section["label"]), ("Section Break", "Oven Readings"), doctype)
			table = fields["oven_readings"]
			self.assertEqual((table["fieldtype"], table["options"]), ("Table", "QC Oven Reading"), doctype)
			# the extruder's own readings and their averages, then the oven's
			self.assertLess(order.index("out_of_range_count"), order.index("oven_readings_section"), doctype)
			self.assertEqual(order.index("oven_readings"), order.index("oven_readings_section") + 1, doctype)
			for fieldname in ("avg_oven_zone1_temp", "avg_oven_zone2_temp", "avg_oven_moisture"):
				self.assertEqual(fields[fieldname].get("read_only"), 1, f"{doctype}.{fieldname}")
				self.assertLess(order.index("oven_readings"), order.index(fieldname), f"{doctype}.{fieldname}")
			self.assertLess(order.index("avg_oven_moisture"), order.index("overall_status"), doctype)

	def test_the_dialog_takes_them_and_no_longer_makes_oven_records(self):
		for doctype in self.EXTRUDERS:
			self.assertEqual(
				qh.QC_DIALOG_CONFIG[doctype]["optional_child_tables"], {"oven_readings": "QC Oven Reading"}
			)
		self.assertNotIn("QC Oven Record", qh.QC_DIALOG_CONFIG)


class TestOverallStatusStartsBlank(unittest.TestCase):
	def test_a_new_record_has_no_result_until_someone_sets_one(self):
		# a Select without a blank first option defaults to that option, so a
		# fresh draft read "Pass" (or "Accepted") before anyone judged it
		for code, doctype in QC_DOCTYPES.items():
			field = _fields(_doctype(doctype)).get("overall_status")
			if not field or doctype == "QC Tasting Record":  # set by validate() on every save
				continue
			self.assertTrue(field["options"].startswith("\n"), doctype)


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

	@patch("frappe.get_all")
	@patch("frappe.db.count")
	@patch("frappe.get_list")
	@patch("frappe.db.table_exists", return_value=True)
	@patch("frappe.has_permission")
	def test_summary_and_matrix_count_what_the_user_may_read(self, perm, table_exists, get_list, count, get_all):
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
		# oven readings are on the extruder records: no Oven record is expected
		self.assertNotIn("QCE", summary)
		self.assertNotIn("QCE", qh.get_completion_matrix("2026-10-25")["doctypes"])
		self.assertTrue(all("QCE" not in matrix[s] for s in matrix))
		# counted through get_list, which applies the user's User Permissions
		count.assert_not_called()
		get_all.assert_not_called()
		for call in get_list.call_args_list:
			self.assertEqual(call.kwargs["filters"], {"record_date": "2026-10-25"})
			self.assertFalse(call.kwargs.get("ignore_permissions"))
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


class TestCreateRecordFromDialog(unittest.TestCase):
	@staticmethod
	def _meta(fieldnames, selects=()):
		meta = MagicMock()
		meta.fields = [frappe._dict(fieldname=f, fieldtype="Float") for f in fieldnames]
		meta.fields += [frappe._dict(fieldname=f, fieldtype="Select") for f in selects]
		meta.get_label.return_value = "Readings"
		return meta

	@patch("frappe.get_doc")
	@patch("frappe.get_meta")
	def test_blank_cells_are_left_unset(self, get_meta, get_doc):
		get_meta.side_effect = lambda doctype: (
			self._meta(["record_date", "shift", "work_order", "overall_status"])
			if doctype == "QC Puffs Extruder Record"
			else self._meta(["time_slot", "moisture_content", "product_density"])
		)
		doc = MagicMock(docstatus=0)
		get_doc.return_value = doc

		qh.create_qc_record(
			"QC Puffs Extruder Record",
			payload={
				"record_date": "2026-10-25",
				"shift": "Night",
				"work_order": "",
				"overall_status": "",
				"readings": [
					{"time_slot": "22:00", "moisture_content": 12.1, "product_density": ""},
					{"time_slot": "", "moisture_content": "", "product_density": ""},
				],
			},
		)

		# the controllers average reading columns: "" would be summed with numbers
		self.assertEqual(
			get_doc.call_args.args[0],
			{"doctype": "QC Puffs Extruder Record", "record_date": "2026-10-25", "shift": "Night", "status": "Draft"},
		)
		doc.append.assert_called_once_with("readings", {"time_slot": "22:00", "moisture_content": 12.1})
		doc.insert.assert_called_once()

	@patch("frappe.get_doc")
	@patch("frappe.get_meta")
	def test_oven_readings_go_in_their_own_table(self, get_meta, get_doc):
		get_meta.side_effect = lambda doctype: {
			"QC Puffs Extruder Record": self._meta(["record_date"]),
			"QC Extruder Reading": self._meta(["time_slot", "moisture_content"]),
			"QC Oven Reading": self._meta(["time_slot", "zone_1_temp", "moisture"]),
		}[doctype]
		doc = get_doc.return_value = MagicMock(docstatus=0)

		qh.create_qc_record(
			"QC Puffs Extruder Record",
			payload={
				"record_date": "2026-10-26",
				"readings": [{"time_slot": "08:00", "moisture_content": 12.0}],
				"oven_readings": [
					{"time_slot": "08:30", "zone_1_temp": 180.0, "moisture": ""},
					{"time_slot": "", "zone_1_temp": "", "moisture": ""},
				],
			},
		)

		self.assertNotIn("oven_readings", get_doc.call_args.args[0])
		self.assertEqual(
			[c.args for c in doc.append.call_args_list],
			[
				("readings", {"time_slot": "08:00", "moisture_content": 12.0}),
				("oven_readings", {"time_slot": "08:30", "zone_1_temp": 180.0}),
			],
		)

	@patch("frappe.get_doc")
	@patch("frappe.get_meta")
	def test_oven_readings_are_optional_but_readings_are_not(self, get_meta, get_doc):
		get_meta.side_effect = lambda doctype: self._meta(["record_date", "time_slot", "zone_1_temp"])
		doc = get_doc.return_value = MagicMock(docstatus=0)

		qh.create_qc_record(
			"QC Rice Extruder Record",
			payload={"record_date": "2026-10-26", "readings": [{"time_slot": "08:00"}], "oven_readings": []},
		)
		doc.insert.assert_called_once()

		doc.reset_mock()
		with self.assertRaises(frappe.ValidationError):
			qh.create_qc_record(
				"QC Rice Extruder Record",
				payload={"record_date": "2026-10-26", "readings": [], "oven_readings": [{"zone_1_temp": 180.0}]},
			)
		doc.insert.assert_not_called()

	@patch("frappe.get_doc")
	@patch("frappe.get_meta")
	def test_a_blank_select_stays_blank(self, get_meta, get_doc):
		# Test Piece Type is "Fe\nNon-Fe\nStainless": left unset, Frappe would
		# record an Fe test piece nobody picked
		get_meta.side_effect = lambda doctype: (
			self._meta(["record_date"], selects=["shift"])
			if doctype == "QC Metal Detector Log"
			else self._meta(["test_time", "detected"], selects=["test_piece_type"])
		)
		doc = MagicMock(docstatus=0)
		get_doc.return_value = doc

		qh.create_qc_record(
			"QC Metal Detector Log",
			payload={
				"record_date": "2026-10-25",
				"shift": "",
				"tests": [{"test_time": "10:00", "test_piece_type": "", "detected": 1}],
			},
		)

		self.assertEqual(get_doc.call_args.args[0]["shift"], "")
		doc.append.assert_called_once_with("tests", {"test_time": "10:00", "test_piece_type": "", "detected": 1})
