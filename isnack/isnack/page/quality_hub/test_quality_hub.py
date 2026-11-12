# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""Unit tests for the QC record schema the FSSC 22000 changes rely on (no database)."""

import json
import os
import re
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

	def test_quality_checks_are_blank_yes_no_or_not_applicable(self):
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
			self.assertEqual(field["options"], "\nYes\nNo\nNot applicable", fieldname)
		self.assertNotIn("colour_acceptable", self.fields)

	def test_no_acceptable_range(self):
		# the arrival temperature is recorded as read; nothing left to compute a Temperature Pass from
		for fieldname in ("acceptable_range_min", "acceptable_range_max", "temp_pass"):
			self.assertNotIn(fieldname, self.fields)
			self.assertNotIn(fieldname, self.doc["field_order"])
		self.assertIn("arrival_temperature", self.fields)

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

	def test_oil_readings_name_the_measure_in_brackets(self):
		fields = _fields(_doctype("QC Frying Reading"))
		self.assertEqual(
			[fields[f]["label"] for f in ("oil_ffa", "oil_tpm", "oil_pv", "oil_anv")],
			["Oil (FFA)", "Oil (TPM)", "Oil (PV)", "Oil (ANV)"],
		)

	def test_moisture_reads_moisture_content(self):
		self.assertEqual(_fields(_doctype("QC Frying Reading"))["product_moisture"]["label"], "Moisture Content (%)")
		self.assertEqual(
			_fields(_doctype("QC Frying Line Record"))["avg_product_moisture"]["label"], "Avg Moisture Content (%)"
		)

	def test_remarks_on_the_record_not_on_each_reading(self):
		self.assertNotIn("reading_remarks", _fields(_doctype("QC Frying Reading")))
		self.assertEqual(_fields(_doctype("QC Frying Line Record"))["remarks"]["fieldtype"], "Small Text")
		# the Quality Hub dialog: Remarks under Product & Outcome, none in the readings
		with open(os.path.join(os.path.dirname(__file__), "quality_hub.js")) as fh:
			script = fh.read()
		start = script.index('"QC Frying Line Record": {')
		block = script[start : script.index('"QC Tasting Record": {', start)]
		parent, child = block.split("child_fields: [")
		self.assertIn('{ fieldname: "remarks", fieldtype: "Small Text", label: __("Remarks") }', parent)
		self.assertLess(parent.index('label: __("Product & Outcome")'), parent.index('fieldname: "remarks"'))
		self.assertNotIn("remarks", child)


class TestExtruderReadings(unittest.TestCase):
	"""Puffs and Rice have their own readings since 2026-11; their earlier ones are kept."""

	READINGS = [
		("time_slot", "Time", "Time Slot"),
		("moisture_corn_content", "Float", "Moisture Corn Content (%)"),
		("start_temp", "Float", "Start Temp (°C)"),
		("motor_speed", "Float", "Motor Speed (Hz)"),
		("feed_motor", "Float", "Feed Motor (Hz)"),
		("cutter_speed", "Float", "Cutter Speed (Hz)"),
	]
	PUFFS_OVEN = [
		("time_slot", "Time", "Time Slot"),
		("oven_temp", "Float", "Oven Temp (°C)"),
		("belt_speed", "Float", "Belt Speed (Hz)"),
		("moisture", "Float", "Moisture (%)"),
	]
	RICE_OVEN = PUFFS_OVEN + [
		("tank_temp", "Float", "Tank Temp (°C)"),
		("motor_speed", "Float", "Motor Speed (Hz)"),
		("flavour_speed", "Float", "Flavour Speed (Hz)"),
	]
	# record: (its readings table and child doctype, its oven table, child doctype and
	# label, its oven moisture average, its form script)
	RECORDS = {
		"QC Puffs Extruder Record": (
			("puffs_readings", "QC Puffs Extruder Reading"),
			("puffs_oven_readings", "QC Puffs Oven Reading", "Oven Readings"),
			"avg_puffs_oven_moisture",
			"qc_puffs_extruder_record",
		),
		"QC Rice Extruder Record": (
			("rice_readings", "QC Rice Extruder Reading"),
			("rice_oven_readings", "QC Rice Oven Reading", "Oven / Slurry Readings"),
			"avg_rice_oven_moisture",
			"qc_rice_extruder_record",
		),
	}

	def test_the_reading_columns(self):
		for child, expected in (
			("QC Puffs Extruder Reading", self.READINGS),
			("QC Puffs Oven Reading", self.PUFFS_OVEN),
			("QC Rice Extruder Reading", self.READINGS),
			("QC Rice Oven Reading", self.RICE_OVEN),
		):
			doc = _doctype(child)
			self.assertEqual(doc["istable"], 1, child)
			self.assertEqual(doc["field_order"], [f["fieldname"] for f in doc["fields"]], child)
			self.assertEqual([(f["fieldname"], f["fieldtype"], f["label"]) for f in doc["fields"]], expected, child)
			# every column shows in the desk form's grid: Frappe keeps 2 of its 12
			# units for the row number and a spare, and drops the columns past 10
			self.assertTrue(all(f.get("in_list_view") for f in doc["fields"]), child)
			self.assertLessEqual(sum(f.get("columns") or 2 for f in doc["fields"]), 10, child)

	def test_the_record_takes_them_in_its_readings_and_oven_readings(self):
		for doctype, ((table, child), (oven_table, oven_child, oven_label), oven_moisture, _script) in self.RECORDS.items():
			doc = _doctype(doctype)
			fields = _fields(doc)
			order = doc["field_order"]
			self.assertEqual(order, [f["fieldname"] for f in doc["fields"]], doctype)
			for fieldname, label, options in ((table, "Readings", child), (oven_table, oven_label, oven_child)):
				t = fields[fieldname]
				self.assertEqual((t["fieldtype"], t["label"], t["options"]), ("Table", label, options), doctype)
				self.assertFalse(t.get("read_only") or t.get("depends_on"), (doctype, fieldname))
			section = fields["oven_readings_section"]
			self.assertEqual((section["fieldtype"], section["label"]), ("Section Break", oven_label), doctype)
			# the readings and their average, then the oven section
			self.assertLess(order.index(table), order.index("avg_moisture_corn_content"), doctype)
			self.assertLess(order.index("avg_moisture_corn_content"), order.index("oven_readings_section"), doctype)
			self.assertEqual(order.index(oven_table), order.index("oven_readings_section") + 1, doctype)
			for fieldname, shown_by in (
				("avg_moisture_corn_content", table),
				("avg_oven_temp", oven_table),
				(oven_moisture, oven_table),
			):
				self.assertEqual(fields[fieldname].get("read_only"), 1, (doctype, fieldname))
				# no 0 average on a record without such readings (an earlier one);
				# in print, before_print does the same
				self.assertEqual(fields[fieldname]["depends_on"], f"eval:(doc.{shown_by} || []).length", (doctype, fieldname))
			self.assertLess(order.index(oven_moisture), order.index("earlier_readings_section"), doctype)

	def test_earlier_readings_are_kept(self):
		for doctype in self.RECORDS:
			doc = _doctype(doctype)
			fields = _fields(doc)
			order = doc["field_order"]
			# never pointed at the new tables: their rows would no longer show
			self.assertEqual(fields["readings"]["options"], "QC Extruder Reading", doctype)
			self.assertEqual(fields["oven_readings"]["options"], "QC Oven Reading", doctype)
			section = fields["earlier_readings_section"]
			self.assertEqual(section["fieldtype"], "Section Break", doctype)
			self.assertIn("doc.readings", section["depends_on"], doctype)
			self.assertIn("doc.oven_readings", section["depends_on"], doctype)
			earlier = {
				"readings": ("readings", "avg_moisture", "avg_density", "out_of_range_count"),
				"oven_readings": ("oven_readings", "avg_oven_zone1_temp", "avg_oven_zone2_temp", "avg_oven_moisture"),
			}
			for table, fieldnames in earlier.items():
				# corrected on a draft or an amendment; a duplicate starts without them
				self.assertFalse(fields[table].get("read_only"), (doctype, table))
				self.assertEqual(fields[table].get("no_copy"), 1, (doctype, table))
				for fieldname in fieldnames:
					# shown only on a record that has rows in them
					self.assertEqual(fields[fieldname]["depends_on"], f"eval:(doc.{table} || []).length", (doctype, fieldname))
					self.assertLess(order.index("earlier_readings_section"), order.index(fieldname), (doctype, fieldname))
					self.assertLess(order.index(fieldname), order.index("result_section"), (doctype, fieldname))

	def test_print_leaves_out_what_the_form_hides(self):
		# before_print blanks each table's summary (SUMMARIES) as depends_on hides it
		import importlib

		for doctype, (*_tables, script) in self.RECORDS.items():
			shown_by = {}
			for f in _doctype(doctype)["fields"]:
				m = re.fullmatch(r"eval:\(doc\.(\w+) \|\| \[\]\)\.length", f.get("depends_on") or "")
				if m and f["fieldtype"] not in ("Table", "Section Break"):
					shown_by.setdefault(m.group(1), set()).add(f["fieldname"])
			module = importlib.import_module(f"isnack.isnack.doctype.{script}.{script}")
			self.assertEqual({t: set(f) for t, f in module.SUMMARIES.items()}, shown_by, doctype)

	def test_no_new_rows_in_the_earlier_tables(self):
		for doctype, (*_tables, script) in self.RECORDS.items():
			with open(os.path.join(DOCTYPE_DIR, script, f"{script}.js")) as fh:
				code = fh.read()
			self.assertIn(f'frappe.ui.form.on("{doctype}"', code)
			self.assertIn('for (const fieldname of ["readings", "oven_readings"])', code)
			self.assertIn('frm.set_df_property(fieldname, "cannot_add_rows", 1)', code)

	def test_labels_tell_the_layouts_apart(self):
		# as report columns, filters and print lines name them
		for doctype in self.RECORDS:
			labels = [
				f["label"]
				for f in _doctype(doctype)["fields"]
				if f.get("label") and f["fieldtype"] not in ("Section Break", "Column Break")
			]
			self.assertEqual(len(labels), len(set(labels)), (doctype, [l for l in labels if labels.count(l) > 1]))

	def test_the_shared_readings_keep_their_columns(self):
		# the earlier tables, and the retired Oven record (QCE)
		self.assertIn("screw_speed_rpm", _fields(_doctype("QC Extruder Reading")))
		self.assertIn("zone_1_temp", _fields(_doctype("QC Oven Reading")))
		self.assertEqual(_fields(_doctype("QC Oven Record"))["readings"]["options"], "QC Oven Reading")

	def test_the_dialog_takes_the_new_tables(self):
		for doctype, ((table, child), (oven_table, oven_child, _label), *_rest) in self.RECORDS.items():
			config = qh.QC_DIALOG_CONFIG[doctype]
			self.assertEqual((config["child_table_field"], config["child_doctype"]), (table, child), doctype)
			self.assertEqual(config["optional_child_tables"], {oven_table: oven_child}, doctype)
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


class TestLineAndWorkOrderMandatory(unittest.TestCase):
	def test_every_record_type_but_receiving(self):
		for code, doctype in QC_DOCTYPES.items():
			# receiving has neither (a delivery comes before any line); the Oven record is retired
			if code == "QCA" or code in qh.RETIRED_QC_CODES:
				continue
			fields = _fields(_doctype(doctype))
			for fieldname in ("factory_line", "work_order"):
				self.assertEqual(fields[fieldname].get("reqd"), 1, f"{doctype}.{fieldname}")


class TestFinishedGoodsProducts(unittest.TestCase):
	def test_product_item_lists_finished_goods_only(self):
		for doctype in ("QC Puffs Extruder Record", "QC Rice Extruder Record", "QC Frying Line Record"):
			field = _fields(_doctype(doctype))["product_item"]
			self.assertEqual(
				json.loads(field["link_filters"]), [["Item", "item_group", "=", "Finished Goods"]], doctype
			)


class TestTastingRecordSchema(unittest.TestCase):
	def setUp(self):
		self.doc = _doctype("QC Tasting Record")
		self.fields = _fields(self.doc)

	def test_no_pass_threshold(self):
		self.assertNotIn("pass_threshold", self.fields)
		self.assertNotIn("pass_threshold", self.doc["field_order"])

	def test_item_code_follows_the_batch(self):
		order = self.doc["field_order"]
		self.assertLess(order.index("batch_no"), order.index("item_code"))
		item = self.fields["item_code"]
		self.assertEqual((item.get("read_only"), item.get("fetch_from")), (1, "batch_no.item"))
		self.assertEqual(order, [f["fieldname"] for f in self.doc["fields"]])

	def test_batch_no_is_mandatory(self):
		self.assertEqual(self.fields["batch_no"].get("reqd"), 1)

	def test_overall_percent_worked_out_for_each_taster(self):
		score = _doctype("QC Tasting Score")
		fields = _fields(score)
		order = score["field_order"]
		self.assertEqual(order, [f["fieldname"] for f in score["fields"]])
		overall = fields["overall_percent"]
		# whole stars on five scores: a whole percentage, shown as one ("80%")
		self.assertEqual(
			(overall["fieldtype"], overall["label"], overall.get("read_only"), overall.get("in_list_view"), overall.get("precision")),
			("Percent", "Overall %", 1, 1, "0"),
		)
		self.assertEqual(order.index("overall_percent"), order.index("texture_score") + 1)
		# the taster's own rating, before 2026-11: kept, out of sight, out of print and of copies
		old = fields["overall_score"]
		self.assertEqual(
			(old["fieldtype"], old.get("hidden"), old.get("in_list_view"), old.get("print_hide"), old.get("no_copy")),
			("Rating", 1, None, 1, 1),
		)
		# every score the Overall % is made of shows in the desk grid beside it,
		# within the grid's 10 units for columns
		listed = [f["fieldname"] for f in score["fields"] if f.get("in_list_view")]
		self.assertEqual(
			listed,
			["taster_name", "appearance_score", "colour_score", "aroma_score", "taste_score", "texture_score", "overall_percent"],
		)
		self.assertLessEqual(sum(f.get("columns") or 2 for f in score["fields"] if f.get("in_list_view")), 10)
		# the record's figures read in % too
		for fieldname, label in (("avg_overall", "Avg Overall %"), ("min_score", "Min Overall %")):
			f = self.fields[fieldname]
			self.assertEqual((f["fieldtype"], f["label"], f.get("read_only"), f.get("precision")), ("Percent", label, 1, "1"))

	def _dialog(self):
		with open(os.path.join(os.path.dirname(__file__), "quality_hub.js")) as fh:
			script = fh.read()
		start = script.index('"QC Tasting Record": {')
		return script[start : script.index('"QC Packaging Check": {', start)]

	def test_the_dialog(self):
		block = self._dialog()
		self.assertIn('{ fieldname: "sb_product", fieldtype: "Section Break", label: __("Product") }', block)
		self.assertNotIn("Product & Scoring", block)
		self.assertIn('{ fieldname: "batch_no", fieldtype: "Link", label: __("Batch No"), options: "Batch", reqd: 1 }', block)
		# Overall % worked out, not entered; the taster's own Overall rating gone
		self.assertIn(
			'{ fieldname: "overall_percent", fieldtype: "Percent", label: __("Overall %"), read_only: 1, '
			"compute: isnack.quality_hub.tasting_overall_percent }",
			block,
		)
		self.assertNotIn("overall_score", block)
		# what the stars mean, in the Scores toolbar
		legend = re.findall(r'\[(\d), __\("([^"]+)"\)\]', block[block.index("child_legend") :])
		self.assertEqual(legend[:5], [("1", "Poor"), ("2", "Fair"), ("3", "Good"), ("4", "Very good"), ("5", "Excellent")])

	def test_the_desk_form_works_it_out_as_scores_are_given(self):
		with open(os.path.join(DOCTYPE_DIR, "qc_tasting_record", "qc_tasting_record.js")) as fh:
			script = fh.read()
		self.assertIn('frappe.ui.form.on("QC Tasting Score"', script)
		self.assertIn('["appearance_score", "colour_score", "aroma_score", "taste_score", "texture_score"]', script)
		self.assertIn('frappe.model.set_value(cdt, cdn, "overall_percent"', script)
		# five star scores side by side, one grid unit each: smaller stars, in this grid only
		self.assertIn('frm.fields_dict.scores.$wrapper.addClass("qc-tasting-scores")', script)
		with open(os.path.join(DOCTYPE_DIR, "..", "..", "public", "css", "isnack.css")) as fh:
			css = fh.read()
		self.assertIn(".qc-tasting-scores .grid-row .rating svg.icon {", css)


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
			else self._meta(["time_slot", "moisture_corn_content", "start_temp"])
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
				"puffs_readings": [
					{"time_slot": "22:00", "moisture_corn_content": 12.1, "start_temp": ""},
					{"time_slot": "", "moisture_corn_content": "", "start_temp": ""},
				],
			},
		)

		# the controllers average reading columns: "" would be summed with numbers
		self.assertEqual(
			get_doc.call_args.args[0],
			{"doctype": "QC Puffs Extruder Record", "record_date": "2026-10-25", "shift": "Night", "status": "Draft"},
		)
		doc.append.assert_called_once_with("puffs_readings", {"time_slot": "22:00", "moisture_corn_content": 12.1})
		doc.insert.assert_called_once()

	@patch("frappe.get_doc")
	@patch("frappe.get_meta")
	def test_oven_readings_go_in_their_own_table(self, get_meta, get_doc):
		get_meta.side_effect = lambda doctype: {
			"QC Puffs Extruder Record": self._meta(["record_date"]),
			"QC Puffs Extruder Reading": self._meta(["time_slot", "moisture_corn_content"]),
			"QC Puffs Oven Reading": self._meta(["time_slot", "oven_temp", "moisture"]),
		}[doctype]
		doc = get_doc.return_value = MagicMock(docstatus=0)

		qh.create_qc_record(
			"QC Puffs Extruder Record",
			payload={
				"record_date": "2026-10-26",
				"puffs_readings": [{"time_slot": "08:00", "moisture_corn_content": 12.0}],
				"puffs_oven_readings": [
					{"time_slot": "08:30", "oven_temp": 180.0, "moisture": ""},
					{"time_slot": "", "oven_temp": "", "moisture": ""},
				],
			},
		)

		self.assertNotIn("puffs_oven_readings", get_doc.call_args.args[0])
		self.assertEqual(
			[c.args for c in doc.append.call_args_list],
			[
				("puffs_readings", {"time_slot": "08:00", "moisture_corn_content": 12.0}),
				("puffs_oven_readings", {"time_slot": "08:30", "oven_temp": 180.0}),
			],
		)

	@patch("frappe.get_doc")
	@patch("frappe.get_meta")
	def test_a_page_from_before_the_puffs_change_is_told_to_reload(self, get_meta, get_doc):
		# a page loaded before the change sends the earlier tables
		meta = self._meta(["record_date", "time_slot", "moisture_content"])
		meta.fields += [frappe._dict(fieldname=f, fieldtype="Table") for f in ("puffs_readings", "readings")]
		get_meta.return_value = meta
		doc = get_doc.return_value = MagicMock(docstatus=0)

		with self.assertRaisesRegex(frappe.ValidationError, "This page is out of date"):
			qh.create_qc_record(
				"QC Puffs Extruder Record",
				payload={"record_date": "2026-11-10", "readings": [{"time_slot": "08:00", "moisture_content": 12.0}]},
			)
		doc.append.assert_not_called()
		doc.insert.assert_not_called()

		# an empty earlier table is no sign of an old page
		qh.create_qc_record(
			"QC Puffs Extruder Record",
			payload={"record_date": "2026-11-10", "readings": [], "puffs_readings": [{"time_slot": "08:00"}]},
		)
		doc.insert.assert_called_once()

	@patch("frappe.get_doc")
	@patch("frappe.get_meta")
	def test_oven_readings_are_optional_but_readings_are_not(self, get_meta, get_doc):
		get_meta.side_effect = lambda doctype: self._meta(["record_date", "time_slot", "oven_temp", "tank_temp"])
		doc = get_doc.return_value = MagicMock(docstatus=0)

		qh.create_qc_record(
			"QC Rice Extruder Record",
			payload={"record_date": "2026-10-26", "rice_readings": [{"time_slot": "08:00"}], "rice_oven_readings": []},
		)
		doc.insert.assert_called_once()
		doc.append.assert_called_once_with("rice_readings", {"time_slot": "08:00"})

		doc.reset_mock()
		with self.assertRaises(frappe.ValidationError):
			qh.create_qc_record(
				"QC Rice Extruder Record",
				payload={"record_date": "2026-10-26", "rice_readings": [], "rice_oven_readings": [{"tank_temp": 65.0}]},
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
