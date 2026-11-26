# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""Unit tests for the QC record schema the FSSC 22000 changes rely on (no database)."""

import datetime
import json
import os
import re
import shutil
import subprocess
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

	PUFFS_READINGS = [
		("time_slot", "Time", "Time Slot"),
		("moisture_corn_content", "Float", "Moisture Corn Content (%)"),
		("start_temp", "Float", "Start Temp (°C)"),
		("motor_speed", "Float", "Motor Speed (Hz)"),
		("feed_motor", "Float", "Feed Motor (Hz)"),
		("cutter_speed", "Float", "Cutter Speed (Hz)"),
	]
	# the rice's moisture (2026-11; Moisture Corn Content until then), under
	# the same fieldname, so the readings recorded stay where they are
	RICE_READINGS = [
		PUFFS_READINGS[0],
		("moisture_corn_content", "Float", "Moisture Rice Content (%)"),
		*PUFFS_READINGS[2:],
	]
	# the same on both since 2026-11: the oven, and the slurry's tank, mixer
	# and flavour (the Puffs had the oven's alone; the Rice read Tank Temp and
	# Motor Speed); the extruder's own Motor Speed, in its readings, keeps its label
	OVEN_SLURRY = [
		("time_slot", "Time", "Time Slot"),
		("oven_temp", "Float", "Oven Temp (°C)"),
		("belt_speed", "Float", "Belt Speed (Hz)"),
		("moisture", "Float", "Moisture (%)"),
		("tank_temp", "Float", "Slurry Tank Temp (°C)"),
		("motor_speed", "Float", "Mixer Speed (Hz)"),
		("flavour_speed", "Float", "Flavour Speed (Hz)"),
	]
	# record: (its readings table and child doctype, its oven table, child doctype and
	# label, its oven moisture average, its form script)
	RECORDS = {
		"QC Puffs Extruder Record": (
			("puffs_readings", "QC Puffs Extruder Reading"),
			("puffs_oven_readings", "QC Puffs Oven Reading", "Oven / Slurry Readings"),
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
			("QC Puffs Extruder Reading", self.PUFFS_READINGS),
			("QC Puffs Oven Reading", self.OVEN_SLURRY),
			("QC Rice Extruder Reading", self.RICE_READINGS),
			("QC Rice Oven Reading", self.OVEN_SLURRY),
		):
			doc = _doctype(child)
			self.assertEqual(doc["istable"], 1, child)
			self.assertEqual(doc["field_order"], [f["fieldname"] for f in doc["fields"]], child)
			self.assertEqual([(f["fieldname"], f["fieldtype"], f["label"]) for f in doc["fields"]], expected, child)
			# every column shows in the desk form's grid: Frappe keeps 2 of its 12
			# units for the row number and a spare, and drops the columns past 10
			self.assertTrue(all(f.get("in_list_view") for f in doc["fields"]), child)
			self.assertLessEqual(sum(f.get("columns") or 2 for f in doc["fields"]), 10, child)

	def test_the_puffs_takes_its_oven_and_slurry_readings_as_the_rice_does(self):
		# the same columns, widths and labels (2026-11; the Puffs had the oven's alone)
		puffs, rice = _doctype("QC Puffs Oven Reading"), _doctype("QC Rice Oven Reading")
		self.assertEqual(puffs["field_order"], rice["field_order"])
		self.assertEqual(puffs["fields"], rice["fields"])

	def test_the_rice_records_its_rice_moisture(self):
		# Moisture Rice Content on the Rice, as its average (2026-11; Moisture Corn
		# Content until then); the Puffs keeps its corn
		for doctype, grain in (("QC Puffs Extruder Record", "Corn"), ("QC Rice Extruder Record", "Rice")):
			label = _fields(_doctype(doctype))["avg_moisture_corn_content"]["label"]
			self.assertEqual(label, f"Avg Moisture {grain} Content (%)", doctype)

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
			self.assertIn("new readings go in Readings and Oven / Slurry Readings above.", section["description"], doctype)
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

	def test_the_dialog_reads_as_the_doctypes(self):
		# the Quality Hub dialog's columns, as the desk form's: the oven (or
		# slurry) readings, then the extruder's own
		with open(os.path.join(os.path.dirname(__file__), "quality_hub.js"), encoding="utf-8") as fh:
			script = fh.read()
		column = re.compile(r'\{ fieldname: "(\w+)", fieldtype: "(\w+)", label: __\("([^"]+)"\) \}')
		for doctype, after, readings in (
			("QC Puffs Extruder Record", "QC Rice Extruder Record", self.PUFFS_READINGS),
			("QC Rice Extruder Record", "QC Frying Line Record", self.RICE_READINGS),
		):
			start = script.index(f'"{doctype}": {{')
			block = script[start : script.index(f'"{after}": {{', start)]
			extra, parent = block.split("parent_fields: [")
			oven = extra[extra.index("extra_child_tables: [") :]
			own = parent.split("child_fields: [")[1]
			self.assertEqual(column.findall(oven), self.OVEN_SLURRY, doctype)
			self.assertEqual(column.findall(own), readings, doctype)
			label = re.search(r'child_label: __\("([^"]+)"\)', oven).group(1)
			self.assertEqual(label, "Oven / Slurry Readings", doctype)

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


class TestShiftStartsBlank(unittest.TestCase):
	def test_a_new_record_names_no_shift_until_someone_picks_one(self):
		# a Select without a blank first option starts at that option, so every
		# new record on the desk read Morning (until 2026-11); Shift is mandatory,
		# so it is picked
		for code, doctype in QC_DOCTYPES.items():
			field = _fields(_doctype(doctype))["shift"]
			self.assertEqual(field["options"], "\nMorning\nAfternoon\nNight", doctype)
			self.assertEqual(field.get("reqd"), 1, doctype)
			self.assertNotIn("default", field, doctype)

	def test_as_in_the_quality_hub(self):
		with open(os.path.join(os.path.dirname(__file__), "quality_hub.js"), encoding="utf-8") as fh:
			script = fh.read()
		shifts = re.findall(r'\{ fieldname: "shift", fieldtype: "Select", label: __\("Shift"\), reqd: 1, options: "([^"]*)" \}', script)
		self.assertEqual(len(shifts), len(qh.QC_DIALOG_CONFIG))
		self.assertEqual(set(shifts), {"\\nMorning\\nAfternoon\\nNight"})


class TestDataImport(unittest.TestCase):
	def test_every_record_type_may_be_imported(self):
		# records kept on paper are entered in bulk, with Data Import, which
		# Frappe gives System Manager alone (a System Manager may import any type
		# allowing it; Import records that). The retired Oven record too, for its
		# records from before; the readings come in with their record.
		for code, doctype in QC_DOCTYPES.items():
			doc = _doctype(doctype)
			self.assertEqual(doc.get("allow_import"), 1, doctype)
			importers = [perm["role"] for perm in doc["permissions"] if perm.get("import")]
			self.assertEqual(importers, ["System Manager"], doctype)


class TestLineAndWorkOrderMandatory(unittest.TestCase):
	def test_every_record_type_but_receiving(self):
		for code, doctype in QC_DOCTYPES.items():
			# receiving has neither (a delivery comes before any line); the Oven record is retired
			if code == "QCA" or code in qh.RETIRED_QC_CODES:
				continue
			fields = _fields(_doctype(doctype))
			for fieldname in ("factory_line", "work_order"):
				self.assertEqual(fields[fieldname].get("reqd"), 1, f"{doctype}.{fieldname}")


class TestTheProductItem(unittest.TestCase):
	"""A Process record's Product Item offers the item its Work Order makes,
	which picking the Work Order fills in, and Finished Goods items without a
	Work Order (2026-11): a query quality_hub_lines.js sets on the forms and the
	Quality Hub's dialogs (the settings' TestTheWorkOrders runs it)."""

	def test_no_fixed_filter_on_it(self):
		# Frappe puts a field's link_filters in place of any query set on it
		for doctype in ("QC Puffs Extruder Record", "QC Rice Extruder Record", "QC Frying Line Record"):
			field = _fields(_doctype(doctype))["product_item"]
			self.assertEqual((field["fieldtype"], field["options"]), ("Link", "Item"), doctype)
			self.assertNotIn("link_filters", field, doctype)
		with open(os.path.join(os.path.dirname(__file__), "quality_hub.js")) as fh:
			script = fh.read()
		self.assertEqual(
			script.count('{ fieldname: "product_item", fieldtype: "Link", label: __("Product Item"), options: "Item" },'), 3
		)
		self.assertNotIn("link_filters", script)


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


class TestPackagingCheckSchema(unittest.TestCase):
	"""Film Type, Film Batch and Qty Issued, Used and Returned came off the check
	in 2026-11; the checks made before keep them, in an Earlier Layout."""

	RETIRED = ("film_type", "film_batch", "qty_issued", "qty_used", "qty_returned")

	def setUp(self):
		self.doc = _doctype("QC Packaging Check")
		self.fields = _fields(self.doc)
		self.order = self.doc["field_order"]

	def test_the_check(self):
		self.assertEqual(self.order, [f["fieldname"] for f in self.doc["fields"]])
		self.assertEqual(self.fields["label_correct"]["label"], "Packet Label Correct (Best Before / Batch Ref)")
		wasted = self.fields["qty_wasted"]
		self.assertEqual((wasted["fieldtype"], wasted["label"], wasted.get("reqd")), ("Float", "Qty Wasted", 1))
		# what a check records now comes before the earlier layout
		section = self.order.index("earlier_layout_section")
		for fieldname in ("print_quality_ok", "seal_integrity_ok", "label_correct", "artwork_matches", "qty_wasted", "remarks"):
			self.assertLess(self.order.index(fieldname), section, fieldname)

	def test_the_earlier_layout(self):
		from isnack.isnack.doctype.qc_packaging_check.qc_packaging_check import EARLIER_FIELDS, RETIRED_FIELDS

		section = self.fields["earlier_layout_section"]
		self.assertEqual((section["fieldtype"], section.get("depends_on")), ("Section Break", "eval:doc.earlier_layout"))
		start = self.order.index("earlier_layout_section")
		for fieldname in EARLIER_FIELDS:
			# shown on the checks made before, and never carried into a new one by Duplicate
			self.assertGreater(self.order.index(fieldname), start, fieldname)
			self.assertEqual(self.fields[fieldname].get("no_copy"), 1, fieldname)
			self.assertFalse(self.fields[fieldname].get("reqd"), fieldname)
		self.assertEqual(RETIRED_FIELDS, self.RETIRED)
		self.assertEqual(set(EARLIER_FIELDS), set(self.RETIRED) | {"variance", "variance_acceptable"})
		# the variance still worked out, not entered
		for fieldname in ("variance", "variance_acceptable"):
			self.assertEqual(self.fields[fieldname].get("read_only"), 1, fieldname)
		marker = self.fields["earlier_layout"]
		self.assertEqual(
			(marker["fieldtype"], marker.get("hidden"), marker.get("read_only"), marker.get("no_copy"), marker.get("print_hide")),
			("Check", 1, 1, 1, 1),
		)

	def test_the_dialog(self):
		with open(os.path.join(os.path.dirname(__file__), "quality_hub.js")) as fh:
			script = fh.read()
		start = script.index('"QC Packaging Check": {')
		block = script[start : script.index('"QC Metal Detector Log": {', start)]
		for fieldname in self.RETIRED:
			self.assertNotIn(f'fieldname: "{fieldname}"', block)
		self.assertIn(
			'{ fieldname: "label_correct", fieldtype: "Check", label: __("Packet Label Correct (Best Before / Batch Ref)") }',
			block,
		)
		self.assertIn('{ fieldname: "qty_wasted", fieldtype: "Float", label: __("Qty Wasted"), reqd: 1 }', block)
		self.assertLess(block.index('label: __("Usage & Outcome")'), block.index('fieldname: "qty_wasted"'))


class TestPackagingOverallStatus(unittest.TestCase):
	"""A packaging check made since 2026-11 has an Overall Status, worked out
	from its four checks: Pass only when all are ticked, otherwise Fail."""

	def setUp(self):
		self.doc = _doctype("QC Packaging Check")
		self.fields = _fields(self.doc)
		self.order = self.doc["field_order"]
		with open(os.path.join(os.path.dirname(__file__), "quality_hub.js")) as fh:
			self.script = fh.read()

	def _method(self, signature):
		start = self.script.index(f"    {signature} {{")
		return self.script[start : self.script.index("\n    }\n", start) + 6]

	def _helpers(self):
		start = self.script.index("// A packaging check's Overall Status")
		return self.script[start : self.script.index("// The Metal Detectors used on a factory line", start)]

	def test_the_field(self):
		field = self.fields["overall_status"]
		self.assertEqual((field["fieldtype"], field["label"], field["options"]), ("Select", "Overall Status", "\nPass\nFail"))
		# worked out, never entered or carried by Duplicate; not shown (nor printed) on a check made before
		self.assertEqual((field.get("read_only"), field.get("no_copy"), field.get("print_hide_if_no_value")), (1, 1, 1))
		self.assertEqual(field.get("depends_on"), "eval:!doc.earlier_layout")
		self.assertLess(self.order.index("artwork_matches"), self.order.index("overall_status"))
		self.assertLess(self.order.index("overall_status"), self.order.index("earlier_layout_section"))

	def test_the_same_four_checks_everywhere(self):
		from isnack.isnack.doctype.qc_packaging_check.qc_packaging_check import CHECKS

		self.assertEqual(CHECKS, ("print_quality_ok", "seal_integrity_ok", "label_correct", "artwork_matches"))
		for fieldname in CHECKS:
			self.assertEqual(self.fields[fieldname]["fieldtype"], "Check", fieldname)
		listed = json.dumps(list(CHECKS))
		self.assertIn(f"isnack.quality_hub.PACKAGING_CHECKS = {listed};", self.script)
		form = os.path.join(DOCTYPE_DIR, "qc_packaging_check", "qc_packaging_check.js")
		with open(form) as fh:
			self.assertIn(f"const CHECKS = {listed};", fh.read())

	def test_the_dialog_shows_it(self):
		start = self.script.index('"QC Packaging Check": {')
		block = self.script[start : self.script.index('"QC Metal Detector Log": {', start)]
		field = block[block.index('fieldname: "overall_status"') :]
		field = field[: field.index("},")]
		self.assertIn("read_only: 1", field)
		self.assertIn("compute: isnack.quality_hub.packaging_overall_status", field)
		self.assertIn("compute_from: isnack.quality_hub.PACKAGING_CHECKS", field)
		self.assertLess(block.index('fieldname: "qty_wasted"'), block.index('fieldname: "overall_status"'))
		# both forms set it up
		for method in ("open_new_record(doctype)", "open_packaging_and_weight()"):
			self.assertIn("this.setup_computed_fields(dialog);", self._method(method), method)

	@unittest.skipUnless(shutil.which("node"), "needs node to run the dialog's code")
	def test_shown_as_the_checks_are_ticked_and_not_sent(self):
		# the dialog's own code, on a dialog holding the packaging check's fields
		script = (
			"const __ = (msg) => msg;\n"
			"const frappe = {provide: () => {}};\n"
			"const isnack = {quality_hub: {}};\n"
			f"{self._helpers()}\n"
			f"class Hub {{\n{self._method('setup_computed_fields(dialog)')}\n"
			f"{self._method('handle_dialog_save(dialog, doctype, submit, values)')}\n"
			"    read_dialog_values(dialog, values) { return values; }\n"
			"    add_child_rows() { return true; }\n"
			"    save_dialog_record(args) { this.saved = args.payload; }\n}\n"
			"const fields = [...isnack.quality_hub.PACKAGING_CHECKS.map((fieldname) => ({fieldname, fieldtype: 'Check'})),\n"
			"  {fieldname: 'overall_status', fieldtype: 'Data', read_only: 1, compute: isnack.quality_hub.packaging_overall_status, compute_from: isnack.quality_hub.PACKAGING_CHECKS}];\n"
			"const values = {};\n"
			"const controls = Object.fromEntries(fields.map((df) => [df.fieldname, {df}]));\n"
			"let seen = 0;\n"
			"controls.label_correct.df.onchange = () => { seen += 1; };\n"
			"const dialog = {fields, get_field: (f) => controls[f], get_value: (f) => values[f] ?? null,\n"
			"  set_value: (f, v) => { values[f] = v; }};\n"
			"const tick = (fieldname, value) => { values[fieldname] = value; controls[fieldname].df.onchange(); };\n"
			"const hub = new Hub();\n"
			"hub.setup_computed_fields(dialog);\n"
			"const out = {opened: values.overall_status};\n"
			"isnack.quality_hub.PACKAGING_CHECKS.forEach((f) => tick(f, 1));\n"
			"out.all_ticked = values.overall_status;\n"
			"tick('label_correct', 0);\n"
			"out.one_unticked = values.overall_status;\n"
			"out.own_onchange_kept = seen;\n"
			"hub.handle_dialog_save(dialog, 'QC Packaging Check', false, {...values});\n"
			"out.sent = Object.keys(hub.saved).sort();\n"
			"console.log(JSON.stringify(out));\n"
		)
		out = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
		self.assertEqual(
			out,
			{
				"opened": "Fail",
				"all_ticked": "Pass",
				"one_unticked": "Fail",
				"own_onchange_kept": 2,
				# the check works it out on save
				"sent": ["artwork_matches", "label_correct", "print_quality_ok", "seal_integrity_ok"],
			},
		)

	def test_the_packaging_and_weight_form_does_not_send_it(self):
		method = self._method("handle_combined_save(dialog, records, submit, values)")
		self.assertIn("if (df.fieldname in values && !df.compute) picked[df.fieldname] = values[df.fieldname];", method)


class TestWeightCheckSchema(unittest.TestCase):
	"""Since 2026-11 each sample has a Status and Remarks; the TU limits, the tare
	and the Outcome section (Overall Status, Remarks) came off the check. The
	checks made before keep them, in an Earlier Layout."""

	def setUp(self):
		self.doc = _doctype("QC Weight Check")
		self.fields = _fields(self.doc)
		self.order = self.doc["field_order"]
		self.sample = _doctype("QC Weight Sample")
		self.sample_fields = _fields(self.sample)

	def test_each_sample_has_a_status_and_remarks(self):
		self.assertEqual(self.sample["field_order"], [f["fieldname"] for f in self.sample["fields"]])
		order = self.sample["field_order"]
		# the Status next to the Gross Weight, then the Remarks
		self.assertEqual(order[:4], ["sample_no", "gross_weight", "status", "remarks"])
		status = self.sample_fields["status"]
		self.assertEqual((status["fieldtype"], status["label"], status["options"]), ("Select", "Status", "\nPass\nFail"))
		# mandatory on a check made since, not on one made before (a draft, an
		# amendment, a restore): the check and the form see to it, not the doctype
		self.assertIsNone(status.get("reqd"))
		with open(os.path.join(DOCTYPE_DIR, "qc_weight_check", "qc_weight_check.js")) as fh:
			script = fh.read()
		self.assertIn('grid.toggle_reqd("status", !earlier)', script)
		# a check made before keeps the samples' columns it was made with
		self.assertIn("const columns = { remarks: !earlier, status: !earlier, tare_weight: earlier, net_weight: earlier, in_range: earlier };", script)
		for fieldname in ("remarks", "status"):
			self.assertEqual(self.sample_fields[fieldname].get("depends_on"), "eval:!parent.earlier_layout", fieldname)
		self.assertEqual((self.sample_fields["remarks"]["fieldtype"], self.sample_fields["remarks"]["label"]), ("Small Text", "Remarks"))
		# the desk grid: those four, within its 10 units for columns
		listed = [f for f in self.sample["fields"] if f.get("in_list_view")]
		self.assertEqual([f["fieldname"] for f in listed], ["sample_no", "gross_weight", "status", "remarks"])
		self.assertLessEqual(sum(f.get("columns") or 2 for f in listed), 10)

	def test_each_sample_is_numbered_and_weighed(self):
		# mandatory on every check (a blank is saved as 0, which a check made
		# before keeps); the check refuses 0 or less on one made since
		for fieldname, fieldtype in (("sample_no", "Int"), ("gross_weight", "Float")):
			f = self.sample_fields[fieldname]
			self.assertEqual((f["fieldtype"], f.get("reqd"), f.get("in_list_view")), (fieldtype, 1, 1), fieldname)
		self.assertEqual(self.sample_fields["sample_no"].get("description"), "1 or more.")

	def test_a_samples_earlier_layout(self):
		from isnack.isnack.doctype.qc_weight_check.qc_weight_check import EARLIER_SAMPLE_FIELDS

		order = self.sample["field_order"]
		section = self.sample_fields["earlier_layout_section"]
		self.assertEqual(section.get("depends_on"), "eval:parent.earlier_layout")
		for fieldname in EARLIER_SAMPLE_FIELDS:
			f = self.sample_fields[fieldname]
			self.assertGreater(order.index(fieldname), order.index("earlier_layout_section"), fieldname)
			# out of the grid, of a Duplicate, and of a print without them
			self.assertEqual((f.get("in_list_view"), f.get("no_copy"), f.get("print_hide_if_no_value")), (None, 1, 1), fieldname)
		for fieldname in ("net_weight", "in_range"):
			self.assertEqual(self.sample_fields[fieldname].get("read_only"), 1, fieldname)

	def test_the_check(self):
		from isnack.isnack.doctype.qc_weight_check.qc_weight_check import EARLIER_FIELDS

		self.assertEqual(self.order, [f["fieldname"] for f in self.doc["fields"]])
		section = self.fields["earlier_layout_section"]
		self.assertEqual((section["fieldtype"], section.get("depends_on")), ("Section Break", "eval:doc.earlier_layout"))
		start = self.order.index("earlier_layout_section")
		for fieldname in ("item_code", "batch_no", "nominal_weight", "samples", "sample_count", "average_weight", "std_deviation", "min_weight", "max_weight"):
			self.assertLess(self.order.index(fieldname), start, fieldname)
		for fieldname in EARLIER_FIELDS:
			self.assertGreater(self.order.index(fieldname), start, fieldname)
			self.assertEqual(self.fields[fieldname].get("no_copy"), 1, fieldname)
		marker = self.fields["earlier_layout"]
		self.assertEqual(
			(marker["fieldtype"], marker.get("hidden"), marker.get("read_only"), marker.get("no_copy"), marker.get("print_hide")),
			("Check", 1, 1, 1, 1),
		)

	def test_the_nominal_weight_is_mandatory(self):
		self.assertEqual(self.fields["nominal_weight"].get("reqd"), 1)

	def test_no_item_or_batch_on_a_check_made_since(self):
		# read-only, so shown only on a check that holds them (one made
		# before, or an amendment of one); out of a Duplicate
		for fieldname in ("item_code", "batch_no"):
			f = self.fields[fieldname]
			self.assertEqual((f.get("read_only"), f.get("no_copy"), f.get("reqd")), (1, 1, None), fieldname)
			self.assertIn("checks made before 2026-11", f["description"], fieldname)
		self.assertEqual((self.fields["item_name"].get("read_only"), self.fields["item_name"].get("no_copy")), (1, 1))

	def _dialog(self):
		with open(os.path.join(os.path.dirname(__file__), "quality_hub.js")) as fh:
			script = fh.read()
		start = script.index('"QC Weight Check": {')
		return script[start : script.index("\n};", start)]

	def test_the_dialog(self):
		block = self._dialog()
		parent, child = block.split("child_fields: [")
		for fieldname in ("tu1_limit", "tu2_limit", "overall_status", "remarks", "sb_outcome"):
			self.assertNotIn(f'fieldname: "{fieldname}"', parent)
		self.assertNotIn('label: __("Outcome")', parent)
		# no limits left in it: the section reads Product, and holds the
		# Nominal Weight alone (no Item Code or Batch No since 2026-11)
		self.assertIn('{ fieldname: "sb_product", fieldtype: "Section Break", label: __("Product") }', parent)
		for fieldname in ("item_code", "batch_no", "cb_product"):
			self.assertNotIn(f'fieldname: "{fieldname}"', parent)
		self.assertEqual(re.findall(r'fieldname: "(\w+)"', parent)[-2:], ["sb_product", "nominal_weight"])
		self.assertIn('{ fieldname: "nominal_weight", fieldtype: "Float", label: __("Nominal Weight (g)"), reqd: 1 }', parent)
		self.assertNotIn("tare_weight", child)
		self.assertEqual(
			re.findall(r'fieldname: "(\w+)"', child), ["sample_no", "gross_weight", "status", "remarks"]
		)
		self.assertIn('{ fieldname: "sample_no", fieldtype: "Int", label: __("Sample No"), reqd: 1, positive: 1 }', child)
		self.assertIn('{ fieldname: "gross_weight", fieldtype: "Float", label: __("Gross Weight (g)"), reqd: 1, positive: 1 }', child)
		self.assertIn('{ fieldname: "remarks", fieldtype: "Small Text", label: __("Remarks") }', child)
		self.assertIn('{ fieldname: "status", fieldtype: "Select", label: __("Status"), options: "\\nPass\\nFail", reqd: 1 }', child)

	def test_the_dialog_asks_for_a_required_column(self):
		with open(os.path.join(os.path.dirname(__file__), "quality_hub.js")) as fh:
			script = fh.read()
		self.assertIn("missing_child_values(dialog, table)", script)
		self.assertIn('class="qh-child-reqd"', script)
		with open(os.path.join(os.path.dirname(__file__), "quality_hub.css")) as fh:
			self.assertIn(".qh-child-reqd {", fh.read())


class TestSamplesNumberedAndWeighed(unittest.TestCase):
	"""Since 2026-11 each weight sample needs a Sample No and a Gross Weight, both
	more than 0; the dialog says which row before the server is asked."""

	def setUp(self):
		with open(os.path.join(os.path.dirname(__file__), "quality_hub.js")) as fh:
			self.script = fh.read()

	def _method(self, signature):
		start = self.script.index(f"    {signature} {{")
		return self.script[start : self.script.index("\n    }\n", start) + 6]

	def _weight_block(self):
		start = self.script.index('"QC Weight Check": {')
		return self.script[start : self.script.index("\n};", start)]

	def _sample_columns(self):
		columns = self._weight_block().split("child_fields: [", 1)[1]
		return columns[: columns.index("\n        ],")]

	@unittest.skipUnless(shutil.which("node"), "needs node to run the dialog's code")
	def test_a_number_is_drawn_as_it_is(self):
		# the dialog's own code, with Frappe's escape_html (which draws any
		# falsy value as nothing): a 0 is drawn as 0, so a redraw (Add Row,
		# Duplicate, Delete) does not hide one; a Sample No starts at 1
		script = (
			"const __ = (msg) => msg;\n"
			"const frappe = {utils: {escape_html: (txt) => (!txt ? '' : String(txt).replace(/&/g, '&amp;').replace(/\"/g, '&quot;'))}};\n"
			f"class Hub {{\n{self._method('format_computed(field, value)')}\n{self._method('render_child_input(field, value, row_index)')}\n}}\n"
			f"const [sample_no, gross_weight] = [{self._sample_columns()}];\n"
			"const hub = new Hub();\n"
			"const value = (html) => (html.match(/value=\"([^\"]*)\"/) || [])[1];\n"
			"const min = (html) => (html.match(/min=\"([^\"]*)\"/) || [])[1] || null;\n"
			"console.log(JSON.stringify({\n"
			"  zero: value(hub.render_child_input(sample_no, 0, 0)), minus_zero: value(hub.render_child_input(gross_weight, -0, 0)),\n"
			"  blank: value(hub.render_child_input(sample_no, '', 0)), unset: value(hub.render_child_input(sample_no, null, 0)),\n"
			"  twelve: value(hub.render_child_input(sample_no, 12, 0)),\n"
			"  sample_min: min(hub.render_child_input(sample_no, '', 0)), gross_min: min(hub.render_child_input(gross_weight, '', 0)),\n"
			"}));\n"
		)
		out = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
		self.assertEqual(
			out,
			{"zero": "0", "minus_zero": "0", "blank": "", "unset": "", "twelve": "12", "sample_min": "1", "gross_min": None},
		)

	def _min_rows(self):
		# the weight check's own: a save needs a sample
		return int(re.search(r"\n        min_rows: (\d+),", self._weight_block()).group(1))

	@unittest.skipUnless(shutil.which("node"), "needs node to run the dialog's code")
	def test_the_samples_a_save_takes(self):
		# the dialog's own code, run on the Samples' own columns
		methods = "\n".join(
			self._method(m)
			for m in (
				"add_child_rows(dialog, config, payload)",
				"get_non_empty_child_rows(dialog, table)",
				"missing_child_values(dialog, table)",
				"not_positive_child_values(dialog, table)",
				"child_row_entered(row, fields)",
				"child_row_has_values(row, fields)",
			)
		)
		script = (
			"const __ = (msg, args) => (args ? msg.replace(/\\{(\\d)\\}/g, (_m, i) => args[i]) : msg);\n"
			"const messages = [];\n"
			"const frappe = {msgprint: (message) => messages.push(message)};\n"
			f"class Hub {{\n    child_tables(config) {{ return [config]; }}\n{methods}\n}}\n"
			f"const table = {{child_table_field: 'samples', child_label: 'Samples', min_rows: {self._min_rows()}, child_fields: [{self._sample_columns()}]}};\n"
			"const run = (rows) => {\n"
			"  messages.length = 0;\n"
			"  const payload = {};\n"
			"  const saved = new Hub().add_child_rows({__child_rows: {samples: rows}}, table, payload);\n"
			"  return {saved, messages: messages.slice(), samples: payload.samples || null};\n"
			"};\n"
			"const blank = {sample_no: '', gross_weight: '', status: '', remarks: ''};\n"
			"console.log(JSON.stringify({\n"
			"  good: run([{...blank, sample_no: 1, gross_weight: 40.6, status: 'Pass'}, blank]),\n"
			"  unnumbered: run([{...blank, gross_weight: 40.6, status: 'Pass'}, {...blank, sample_no: 2, status: 'Pass'}]),\n"
			"  zero: run([blank, {...blank, sample_no: 0, gross_weight: 40.6, status: 'Pass'}, {...blank, sample_no: 3, gross_weight: -1, status: 'Fail'}]),\n"
			"  none: run([blank]),\n"
			"}));\n"
		)
		out = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
		# numbered and weighed: saved, the empty row left out
		self.assertEqual(out["good"], {"saved": True, "messages": [], "samples": [{"sample_no": 1, "gross_weight": 40.6, "status": "Pass", "remarks": ""}]})
		# left blank: required, row by row as the editor numbers them
		self.assertEqual(out["unnumbered"]["messages"], ["Sample No is required in Samples (row 1).<br>Gross Weight (g) is required in Samples (row 2)."])
		# 0 or less: more than 0 (the empty first row still counts in the numbering)
		self.assertEqual(out["zero"]["messages"], ["Sample No must be more than 0 in Samples (row 2).<br>Gross Weight (g) must be more than 0 in Samples (row 3)."])
		# no sample: not saved, Save Draft or Save & Submit
		self.assertEqual(out["none"]["messages"], ["Add at least one row in Samples."])
		for case in ("unnumbered", "zero", "none"):
			self.assertEqual((out[case]["saved"], out[case]["samples"]), (False, None), case)


class TestMetalDetectorLogDialog(unittest.TestCase):
	"""Since 2026-11 the log picks its detector from the Metal Detectors used
	on its factory line and takes its Make/Model and calibration dates; the
	Calibration Certificate is kept on the Metal Detector, and the Corrective
	Action and each test's Sensitivity Setting and Remarks came off. Test Piece
	Size starts at 0.2 mm."""

	def setUp(self):
		with open(os.path.join(os.path.dirname(__file__), "quality_hub.js")) as fh:
			self.script = fh.read()
		start = self.script.index('"QC Metal Detector Log": {')
		self.parent, self.child = self.script[start : self.script.index("\n    },\n", start)].split("child_fields: [")

	def test_the_detector_is_picked_and_its_details_filled_in(self):
		# mandatory (2026-11)
		self.assertIn('{ fieldname: "metal_detector_id", fieldtype: "Link", label: __("Metal Detector ID"), options: "Metal Detector", reqd: 1 }', self.parent)
		for fieldname, fieldtype, label, source in (
			("detector_make_model", "Data", "Make/Model", "make_model"),
			("last_calibration_date", "Date", "Last Calibration Date", "last_calibration_date"),
			("next_calibration_date", "Date", "Next Calibration Date", "next_calibration_date"),
		):
			self.assertIn(
				f'{{ fieldname: "{fieldname}", fieldtype: "{fieldtype}", label: __("{label}"), read_only: 1, fetch_from: "metal_detector_id.{source}" }}',
				self.parent,
			)
		self.assertNotIn('fieldname: "calibration_certificate"', self.parent)
		self.assertNotIn('fieldname: "corrective_action"', self.parent)
		self.assertEqual(
			re.findall(r'fieldname: "(\w+)"', self.parent)[-7:],
			["sb_equipment", "metal_detector_id", "detector_make_model", "last_calibration_date", "next_calibration_date", "cb_equipment", "remarks"],
		)

	def test_the_tests(self):
		self.assertEqual(re.findall(r'fieldname: "(\w+)"', self.child), ["test_time", "test_piece_type", "test_piece_size_mm", "detected"])
		self.assertIn('{ fieldname: "test_piece_size_mm", fieldtype: "Float", label: __("Test Piece Size (mm)"), default: 0.2 }', self.child)
		# each test's time and test piece are mandatory (2026-11): the header is
		# marked and a save names the rows without them (missing_child_values)
		self.assertIn('{ fieldname: "test_time", fieldtype: "Time", label: __("Test Time"), reqd: 1 }', self.child)
		self.assertIn('{ fieldname: "test_piece_type", fieldtype: "Select", label: __("Test Piece Type"), options: "\\nFe\\nNon-Fe\\nStainless", reqd: 1 }', self.child)

	def _method(self, signature):
		start = self.script.index(f"    {signature} {{")
		return self.script[start : self.script.index("\n    }\n", start) + 6]

	def test_a_row_holding_only_its_defaults_is_not_a_test(self):
		# rows saved and rows asked for a required value: those entered, not
		# those holding only a column's default
		self.assertIn(".filter((row) => this.child_row_entered(row, entered))", self._method("get_non_empty_child_rows(dialog, table)"))
		self.assertIn(
			"this.child_row_entered(row, entered) && !this.child_row_has_values(row, [field])",
			self._method("missing_child_values(dialog, table)"),
		)
		self.assertEqual(
			self._method("child_row_entered(row, fields)"),
			"""    child_row_entered(row, fields) {
        return this.child_row_has_values(row, fields.filter((field) => {
            if (field.default === undefined) return true;
            const value = typeof field.default === "function" ? field.default() : field.default;
            return row[field.fieldname] !== value;
        }));
    }""",
		)

	@unittest.skipUnless(shutil.which("node"), "needs node to run the dialog's code")
	def test_which_rows_are_tests(self):
		# the dialog's own code, run on the Tests' columns
		methods = "\n".join(self._method(m) for m in ("child_row_entered(row, fields)", "child_row_has_values(row, fields)"))
		script = (
			f"class Editor {{\n{methods}\n}}\n"
			"const editor = new Editor();\n"
			"const fields = [{fieldname: 'test_time', fieldtype: 'Time'}, {fieldname: 'test_piece_type', fieldtype: 'Select'},"
			" {fieldname: 'test_piece_size_mm', fieldtype: 'Float', default: 0.2}, {fieldname: 'detected', fieldtype: 'Check'},"
			" {fieldname: 'size_from_a_function', fieldtype: 'Float', default: () => 1}];\n"
			"const blank = {test_time: '', test_piece_type: '', test_piece_size_mm: 0.2, detected: 0, size_from_a_function: 1};\n"
			"const rows = [blank, {...blank, test_time: '08:00'}, {...blank, test_piece_type: 'Fe'}, {...blank, detected: 1},"
			" {...blank, test_piece_size_mm: 0.3}, {...blank, test_piece_size_mm: ''}, {...blank, size_from_a_function: 2}];\n"
			"console.log(JSON.stringify(rows.map((row) => editor.child_row_entered(row, fields))));\n"
		)
		out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout
		# only the defaults, then a time, a type, Detected, another size; a size
		# cleared is no value; a default from a function is a default
		self.assertEqual(json.loads(out), [False, True, True, True, True, False, True])

	def test_a_detector_emptied_by_hand_empties_its_details(self):
		# a dialog's Link misses being emptied after a first pick (Frappe v15):
		# the dialog sets it empty, which empties the fields fetched from it
		self.assertIn("this.empty_cleared_links(dialog);", self._method("open_new_record(doctype)"))
		self.assertEqual(
			self._method("empty_cleared_links(dialog)"),
			"""    empty_cleared_links(dialog) {
        const sources = new Set(dialog.fields.filter((df) => df.fetch_from).map((df) => df.fetch_from.split(".")[0]));
        sources.forEach((fieldname) => {
            const field = dialog.get_field(fieldname);
            if (!field || !field.$input) return;
            field.$input.on("blur", () => {
                if (!field.$input.val()) field.set_value("");
            });
        });
    }""",
		)

	def test_the_detectors_are_a_quick_link(self):
		self.assertIn('data-doctype="Metal Detector">${__("Metal Detectors")}</a>', self.script)

	def test_the_detectors_are_those_used_on_the_line(self):
		self.assertIn(
			'if (doctype === "QC Metal Detector Log") this.setup_metal_detector_dialog(dialog);',
			self._method("setup_dialog_specific_behaviour(dialog, doctype)"),
		)

	@unittest.skipUnless(shutil.which("node"), "needs node to run the dialog's code")
	def test_the_detectors_offered_and_one_taken_off(self):
		# the dialog's own code, on a dialog and a database of detectors and lines
		start = self.script.index("isnack.quality_hub.metal_detectors_on_line =")
		on_line = self.script[start : self.script.index(";\n", start) + 2]
		methods = "\n".join(self._method(m) for m in ("setup_metal_detector_dialog(dialog)", "drop_detector_off_line(dialog)"))
		script = (
			"const isnack = {quality_hub: {}};\n"
			"const __ = (msg, args) => msg.replace(/\\{(\\d)\\}/g, (_m, i) => args[i]);\n"
			"const lines = {'MD-1': ['CORN EXTRUSION', 'FRYING'], 'MD-2': ['RICE EXTRUSION']};\n"
			"const asked = [], alerts = [];\n"
			"const frappe = {show_alert: (a) => alerts.push(a.message), db: {get_list: (doctype, args) => {\n"
			"  asked.push([doctype, args]);\n"
			"  const [[, , name], [, , , line]] = args.filters;\n"
			"  return Promise.resolve((lines[name] || []).includes(line) ? [{name}] : []);\n"
			"}}};\n"
			f"{on_line}\n"
			f"class Hub {{\n{methods}\n}}\n"
			"const make_dialog = (values) => {\n"
			"  const fields = {factory_line: {df: {onchange: () => values.line_onchange = (values.line_onchange || 0) + 1}}, metal_detector_id: {df: {}}};\n"
			"  return {get_field: (f) => fields[f], get_value: (f) => values[f], set_value: (f, v) => { values[f] = v; }, fields};\n"
			"};\n"
			"const flush = () => new Promise((r) => setTimeout(r, 0));\n"
			"(async () => {\n"
			"  const out = {};\n"
			"  const values = {factory_line: '', metal_detector_id: ''};\n"
			"  const dialog = make_dialog(values);\n"
			"  new Hub().setup_metal_detector_dialog(dialog);\n"
			"  const query = dialog.fields.metal_detector_id.get_query;\n"
			"  out.no_line = query();\n"
			"  values.factory_line = 'FRYING';\n"
			"  out.frying = query();\n"
			"  dialog.fields.factory_line.df.onchange();\n"  # no detector yet: nothing asked
			"  out.asked_without_detector = asked.length;\n"
			"  values.metal_detector_id = 'MD-1'; values.factory_line = 'CORN EXTRUSION';\n"
			"  dialog.fields.factory_line.df.onchange(); await flush();\n"
			"  out.kept = values.metal_detector_id; out.asked = asked[0];\n"
			"  values.factory_line = 'RICE EXTRUSION';\n"
			"  dialog.fields.factory_line.df.onchange(); await flush();\n"
			"  out.taken_off = values.metal_detector_id; out.alerts = alerts.slice();\n"
			"  values.metal_detector_id = 'MD-2'; values.factory_line = 'FRYING';\n"
			"  dialog.fields.factory_line.df.onchange(); values.factory_line = 'RICE EXTRUSION'; await flush();\n"
			"  out.changed_again = values.metal_detector_id;\n"
			"  out.line_onchange = values.line_onchange;\n"
			"  console.log(JSON.stringify(out));\n"
			"})();\n"
		)
		out = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
		# every detector before a line is picked (no filter: no empty "Filters
		# applied for" under them); then those used on it
		self.assertEqual(out["no_line"], {})
		self.assertEqual(out["frying"], {"filters": [["Metal Detector Factory Line", "factory_line", "=", "FRYING"]]})
		self.assertEqual(out["asked_without_detector"], 0)
		self.assertEqual(
			out["asked"],
			["Metal Detector", {"filters": [["name", "=", "MD-1"], ["Metal Detector Factory Line", "factory_line", "=", "CORN EXTRUSION"]], "limit": 1}],
		)
		# used on the new line: kept; not: taken off, and the user told
		self.assertEqual(out["kept"], "MD-1")
		self.assertEqual(out["taken_off"], "")
		self.assertEqual(out["alerts"], ["MD-1 is not used on RICE EXTRUSION: pick a metal detector on that line."])
		# the line changed again before the answer came: left to that change
		self.assertEqual(out["changed_again"], "MD-2")
		# the line's own onchange still runs
		self.assertEqual(out["line_onchange"], 4)


class TestFactoryLinesByTab(unittest.TestCase):
    """Since 2026-11 each tab's dialog offers the factory lines Quality Hub
    Settings gives the tab (quality_hub_lines.js, which the records' forms use
    too), and takes the only one when there is just one."""

    def setUp(self):
        with open(os.path.join(os.path.dirname(__file__), "quality_hub.js")) as fh:
            self.script = fh.read()

    def _method(self, signature):
        start = self.script.index(f"    {signature} {{")
        return self.script[start : self.script.index("\n    }\n", start) + 6]

    def test_each_dialog_is_restricted(self):
        self.assertIn("this.restrict_factory_line(dialog, [doctype]);", self._method("open_new_record(doctype)"))
        # the Packaging and Weight form: a line both checks may be on
        self.assertIn(
            "this.restrict_factory_line(dialog, records.map((record) => record.doctype));",
            self._method("open_packaging_and_weight()"),
        )
        # loaded as the hub opens, ready for its dialogs
        self.assertIn("if (isnack.quality_hub_lines) isnack.quality_hub_lines.load();", self._method("constructor(wrapper)"))

    def test_the_settings_are_a_quick_link(self):
        self.assertIn(
            '${frappe.model.can_read("Quality Hub Settings") ? `<a class="btn btn-sm btn-default qh-quick-link" href="#" data-form="Quality Hub Settings">${__("Quality Hub Settings")}</a>` : ""}',
            self.script,
        )
        self.assertIn('frappe.set_route("Form", form);', self.script)

    @unittest.skipUnless(shutil.which("node"), "needs node to run the dialog's code")
    def test_the_lines_offered_and_the_only_line(self):
        method = self._method("restrict_factory_line(dialog, doctypes)")
        script = (
            f"class Hub {{\n{method}\n}}\n"
            "const isnack = {};\n"
            "const make_lines = (given) => ({\n"
            "  asked: [],\n"
            "  load() { return Promise.resolve(given); },\n"
            "  query(doctypes, df) { this.asked.push([doctypes, !!df]); return {filters: [['Factory Line', 'name', 'in', given]]}; },\n"
            "  only_line(doctypes) { return given.length === 1 ? given[0] : null; },\n"
            "});\n"
            "const make_dialog = (values, fields = ['factory_line']) => {\n"
            "  const dict = {}; fields.forEach((f) => { dict[f] = {df: {}}; });\n"
            "  return {values, set: [], get_field: (f) => dict[f], get_value: (f) => values[f],\n"
            "    set_value(f, v) { this.set.push([f, v]); values[f] = v; }, dict};\n"
            "};\n"
            "const flush = () => new Promise((r) => setTimeout(r, 0));\n"
            "(async () => {\n"
            "  const out = {};\n"
            "  const hub = new Hub();\n"
            "  // a desk loaded before the settings came: nothing to do\n"
            "  const early = make_dialog({});\n"
            "  hub.restrict_factory_line(early, ['QC Tasting Record']); await flush();\n"
            "  out.early = [early.dict.factory_line.get_query === undefined, early.set];\n"
            "  isnack.quality_hub_lines = make_lines(['CORN EXTRUSION']);\n"
            "  const one = make_dialog({});\n"
            "  hub.restrict_factory_line(one, ['QC Puffs Extruder Record']); await flush(); await flush();\n"
            "  out.query = one.dict.factory_line.get_query();\n"
            "  out.asked = isnack.quality_hub_lines.asked;\n"
            "  out.one = one.set;\n"
            "  // a line there already, a tab of two lines, a dialog with no line: left as they are\n"
            "  const picked = make_dialog({factory_line: 'CORN MIX'});\n"
            "  hub.restrict_factory_line(picked, ['QC Puffs Extruder Record']); await flush(); await flush();\n"
            "  isnack.quality_hub_lines = make_lines(['PACKING LINE 1', 'PACKING LINE 2']);\n"
            "  const two = make_dialog({});\n"
            "  hub.restrict_factory_line(two, ['QC Packaging Check', 'QC Weight Check']); await flush(); await flush();\n"
            "  const none = make_dialog({}, ['supplier']);\n"
            "  hub.restrict_factory_line(none, ['QC Receiving Record']); await flush(); await flush();\n"
            "  out.left = [picked.set, two.set, none.set];\n"
            "  console.log(JSON.stringify(out));\n"
            "})();\n"
        )
        out = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
        self.assertEqual(out["early"], [True, []])
        self.assertEqual(out["query"], {"filters": [["Factory Line", "name", "in", ["CORN EXTRUSION"]]]})
        # asked with the field's df, for the note under the lines
        self.assertEqual(out["asked"], [[["QC Puffs Extruder Record"], True]])
        self.assertEqual(out["one"], [["factory_line", "CORN EXTRUSION"]])
        self.assertEqual(out["left"], [[], [], []])


class TestWorkOrderByLine(unittest.TestCase):
    """Since 2026-11 each dialog's Work Order offers the Work Orders on the
    Factory Line picked, whatever the tab; one on another line is taken off. A
    Process dialog's Product Item offers the item the Work Order makes, which
    picking it fills in. The same logic as the records' forms
    (quality_hub_lines.js, run by the settings' TestTheWorkOrders)."""

    def setUp(self):
        with open(os.path.join(os.path.dirname(__file__), "quality_hub.js")) as fh:
            self.script = fh.read()

    def _method(self, signature):
        start = self.script.index(f"    {signature} {{")
        return self.script[start : self.script.index("\n    }\n", start) + 6]

    def test_each_dialog_restricts_its_work_order(self):
        call = re.compile(r"^ {8}this\.restrict_work_order\(dialog\);$", re.M)
        body = self._method("open_new_record(doctype)")
        # once its line is restricted; before the metal detector's, which wraps the line's onchange too
        self.assertLess(body.index("this.restrict_factory_line(dialog, [doctype]);"), call.search(body).start())
        self.assertLess(call.search(body).start(), body.index("this.setup_dialog_specific_behaviour(dialog, doctype);"))
        # the Packaging and Weight form: the Work Order both checks share
        self.assertTrue(call.search(self._method("open_packaging_and_weight()")))

    @unittest.skipUnless(shutil.which("node"), "needs node to run the dialog's code")
    def test_the_dialog_uses_the_lines(self):
        method = self._method("restrict_work_order(dialog)")
        script = (
            f"class Hub {{\n{method}\n}}\n"
            "const isnack = {};\n"
            "const asked = [];\n"
            "const make_lines = () => ({\n"
            "  work_order_query(line, df) { asked.push(['work_order_query', line, !!df]); return {filters: ['wo', line]}; },\n"
            "  product_query(work_order, df) { asked.push(['product_query', work_order, !!df]); return {filters: ['item', work_order]}; },\n"
            "  line_changed(record) { asked.push(['line_changed', record.get('factory_line'), record.get('work_order'), record.has('product_item'), record.alive()]); record.set('work_order', ''); },\n"
            "  work_order_changed(record) { asked.push(['work_order_changed', record.get('work_order'), record.alive()]); record.set('product_item', 'FG10001'); },\n"
            "});\n"
            "// a Frappe dialog's Link: value as last set (set_input keeps the one before in last_value); the box's text apart\n"
            "const make_dialog = (fields) => {\n"
            "  const dict = {}; fields.forEach((f) => { dict[f] = {df: {}, value: '', last_value: undefined, typed: ''}; });\n"
            "  if (dict.factory_line) dict.factory_line.df.onchange = () => { dict.factory_line.own = (dict.factory_line.own || 0) + 1; };\n"
            "  const set_input = (f, v) => { dict[f].last_value = dict[f].value; dict[f].value = v; dict[f].typed = v; };\n"
            "  return {display: true, set: [], dict, set_input, get_field: (f) => dict[f], get_value: (f) => dict[f] && dict[f].typed,\n"
            "    set_value(f, v) { this.set.push([f, v]); set_input(f, v); }};\n"
            "};\n"
            "const out = {};\n"
            "const hub = new Hub();\n"
            "// a desk loaded before the Work Order rule came: nothing to do\n"
            "isnack.quality_hub_lines = {query() {}};\n"
            "const early = make_dialog(['factory_line', 'work_order']);\n"
            "const early_onchange = early.dict.factory_line.df.onchange;\n"
            "hub.restrict_work_order(early);\n"
            "out.early = [early.dict.work_order.get_query === undefined, early.dict.factory_line.df.onchange === early_onchange,\n"
            "  early.dict.work_order.df.onchange === undefined];\n"
            "isnack.quality_hub_lines = make_lines();\n"
            "// a Process dialog, set up before its line is filled in\n"
            "const puffs = make_dialog(['factory_line', 'work_order', 'product_item']);\n"
            "hub.restrict_work_order(puffs);\n"
            "puffs.set_input('factory_line', 'FRYING'); puffs.set_input('work_order', 'WO-1');\n"
            "// a line half typed in the box: the queries read the values set\n"
            "puffs.dict.factory_line.typed = 'PACK';\n"
            "out.queries = [puffs.dict.work_order.get_query(), puffs.dict.product_item.get_query()];\n"
            "puffs.dict.work_order.df.onchange();\n"
            "// the Work Order's box left as it was: Frappe runs its onchange again for the same value\n"
            "puffs.set_input('work_order', 'WO-1'); puffs.dict.work_order.df.onchange();\n"
            "puffs.dict.factory_line.df.onchange();\n"
            "puffs.set_input('factory_line', 'FRYING'); puffs.dict.factory_line.df.onchange();\n"
            "out.puffs = puffs.set.slice(); out.line_onchange = puffs.dict.factory_line.own;\n"
            "// saved and closed: the lines are told it is gone\n"
            "puffs.display = false; puffs.set_input('work_order', 'WO-2'); puffs.dict.work_order.df.onchange();\n"
            "// a dialog with no Product Item, and one with no Work Order (receiving)\n"
            "const check = make_dialog(['factory_line', 'work_order']);\n"
            "hub.restrict_work_order(check);\n"
            "out.check = [check.dict.work_order.get_query !== undefined, !!check.dict.work_order.df.onchange];\n"
            "const receiving = make_dialog(['supplier']);\n"
            "hub.restrict_work_order(receiving);\n"
            "out.asked = asked;\n"
            "console.log(JSON.stringify(out));\n"
        )
        run = subprocess.run(["node", "-e", script], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr[-2000:])
        out = json.loads(run.stdout)
        self.assertEqual(out["early"], [True, True, True])
        # the queries read the dialog's line and Work Order as set, when the user searches
        self.assertEqual(out["queries"], [{"filters": ["wo", "FRYING"]}, {"filters": ["item", "WO-1"]}])
        # the dialog's fields, read and set through the record the lines are given
        self.assertEqual(out["puffs"], [["product_item", "FG10001"], ["work_order", ""]])
        # the line's own onchange still runs, each time
        self.assertEqual(out["line_onchange"], 2)
        self.assertEqual(out["check"], [True, True])
        self.assertEqual(
            out["asked"],
            [
                ["work_order_query", "FRYING", True],
                ["product_query", "WO-1", True],
                # once for the pick, not again for the same Work Order or line
                ["work_order_changed", "WO-1", True],
                ["line_changed", "FRYING", "WO-1", True, True],
                ["work_order_changed", "WO-2", False],
            ],
        )


class TestOperatorAndInspectorMandatory(unittest.TestCase):
	def test_every_record_type(self):
		for doctype in QC_DOCTYPES.values():
			fields = _fields(_doctype(doctype))
			self.assertEqual(fields["qc_inspector"].get("reqd"), 1, doctype)
			if "operator" in fields:
				# an Employee since 2026-11, required on the records made since
				# (check_operator: isnack/utils/test_qc_operator.py); its name read-only
				self.assertEqual(fields["operator_name"].get("read_only"), 1, doctype)
				self.assertFalse(fields["operator_name"].get("reqd"), doctype)
			else:
				# the retired Oven record keeps its typed Operator Name
				self.assertEqual(fields["operator_name"].get("reqd"), 1, doctype)


class TestTheOperatorInTheDialogs(unittest.TestCase):
    """Since 2026-11 each dialog's Operator is an Employee, picked by ID or name
    among the Active ones, as on the records' forms (quality_hub_operator.js,
    run by isnack/utils/test_qc_operator.py); Operator Name shows its name."""

    OPERATOR = (
        '{ fieldname: "operator", fieldtype: "Link", label: __("Operator"), options: "Employee", reqd: 1, '
        "ignore_user_permissions: 1, ignore_link_validation: 1, only_select: 1 },\n"
        '            { fieldname: "operator_name", fieldtype: "Data", label: __("Operator Name"), read_only: 1 },'
    )

    def setUp(self):
        with open(os.path.join(os.path.dirname(__file__), "quality_hub.js")) as fh:
            self.script = fh.read()

    def _method(self, signature):
        start = self.script.index(f"    {signature} {{")
        return self.script[start : self.script.index("\n    }\n", start) + 6]

    def test_each_dialog_asks_for_an_employee(self):
        # in the Record Details of each of the eight dialogs, the Operator, then its name
        config = self.script[self.script.index("DIALOG_RECORD_CONFIG = {") : self.script.index("isnack.quality_hub.PACKAGING_AND_WEIGHT")]
        self.assertEqual(config.count(self.OPERATOR), 8)
        self.assertEqual(config.count('fieldname: "operator_name"'), 8)
        # a typed Operator Name no more
        self.assertNotIn('label: __("Operator Name"), reqd: 1', config)

    def test_each_dialog_looks_up_its_operator(self):
        call = re.compile(r"^ {8}this\.restrict_operator\(dialog\);$", re.M)
        body = self._method("open_new_record(doctype)")
        self.assertLess(body.index("this.restrict_work_order(dialog);"), call.search(body).start())
        self.assertLess(call.search(body).start(), body.index("this.setup_dialog_specific_behaviour(dialog, doctype);"))
        # the Packaging and Weight form: the Operator both checks share
        self.assertTrue(call.search(self._method("open_packaging_and_weight()")))

    @unittest.skipUnless(shutil.which("node"), "needs node to run the dialog's code")
    def test_the_dialog_uses_the_operator_script(self):
        method = self._method("restrict_operator(dialog)")
        script = (
            f"class Hub {{\n{method}\n}}\n"
            "const isnack = {};\n"
            "const asked = [];\n"
            "const operators = {\n"
            "  query() { asked.push(['query']); return {query: 'search_operators'}; },\n"
            "  hide_open_link(field) { asked.push(['hide_open_link', field === dialog.fields.operator]); },\n"
            "  operator_changed(record) { asked.push(['changed', record.get('operator'), record.typed, record.alive()]); record.set('operator_name', 'J. Borg'); },\n"
            "};\n"
            "// a Frappe dialog's Link: value as last set (set_input keeps the one before in last_value); the box's text apart\n"
            "const make_dialog = () => {\n"
            "  const blur = [];\n"
            "  const box = {text: '', on(event, fn) { if (event === 'blur') blur.push(fn); }, val() { return this.text; }};\n"
            "  const operator = {df: {onchange() { asked.push(['own onchange']); }}, value: '', last_value: undefined, $input: box,\n"
            "    set_value(value) { asked.push(['set_value', value]); this.last_value = this.value; this.value = value; return this.df.onchange(); }};\n"
            "  const name = {df: {}, value: ''};\n"
            "  const dialog = {display: true, fields: {operator, operator_name: name}, blur,\n"
            "    get_field(f) { return this.fields[f]; },\n"
            "    set_value(f, v) { this.fields[f].value = v; }};\n"
            "  return dialog;\n"
            "};\n"
            "const out = {};\n"
            "// a desk loaded before the Operator came: nothing to look up\n"
            "let dialog = make_dialog();\n"
            "new Hub().restrict_operator(dialog);\n"
            "out.before = dialog.fields.operator.get_query === undefined;\n"
            "isnack.quality_hub_operator = operators;\n"
            "dialog = make_dialog();\n"
            "new Hub().restrict_operator(dialog);\n"
            "const field = dialog.fields.operator;\n"
            "out.query = field.get_query();\n"
            "// picked: the Employee picked, its name shown\n"
            "field.last_value = ''; field.value = 'HR-EMP-00001'; field.$input.text = 'HR-EMP-00001';\n"
            "field.df.onchange();\n"
            "out.name = dialog.fields.operator_name.value;\n"
            "// the box left, the value unchanged: no change\n"
            "field.last_value = 'HR-EMP-00001';\n"
            "field.df.onchange();\n"
            "// emptied by hand after the pick: set empty, a change\n"
            "field.$input.text = '';\n"
            "dialog.blur.forEach((fn) => fn());\n"
            "// left empty again: nothing more\n"
            "dialog.blur.forEach((fn) => fn());\n"
            "// typed and left: with no link check the Link holds it already when onchange runs\n"
            "field.last_value = 'Jim'; field.value = 'Jim';\n"
            "field.df.onchange();\n"
            "// a dialog saved and closed\n"
            "dialog.display = false;\n"
            "field.last_value = ''; field.value = 'HR-EMP-00002';\n"
            "field.df.onchange();\n"
            "out.asked = asked;\n"
            "console.log(JSON.stringify(out));\n"
        )
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        out = json.loads(result.stdout)
        self.assertTrue(out["before"])
        self.assertEqual(out["query"], {"query": "search_operators"})
        self.assertEqual(out["name"], "J. Borg")
        self.assertEqual(
            out["asked"],
            [
                ["hide_open_link", True],
                ["query"],
                # the dialog's own onchange first, kept; the committed value, no typed name
                ["own onchange"],
                ["changed", "HR-EMP-00001", "", True],
                ["own onchange"],
                ["set_value", ""],
                ["own onchange"],
                ["changed", "", "", True],
                # a value typed: looked up (and taken off if no Active Employee), though last_value holds it too
                ["own onchange"],
                ["changed", "Jim", "", True],
                ["own onchange"],
                ["changed", "HR-EMP-00002", "", False],
            ],
        )


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
	def test_a_page_from_before_the_operator_is_told_to_reload(self, get_meta, get_doc):
		# its Operator Name typed, with no Operator (an Employee since 2026-11)
		get_meta.side_effect = lambda doctype: self._meta(["record_date", "operator", "operator_name", "time_slot"])
		doc = get_doc.return_value = MagicMock(docstatus=0)
		with self.assertRaisesRegex(frappe.ValidationError, "This page is out of date"):
			qh.create_qc_record(
				"QC Puffs Extruder Record",
				payload={"record_date": "2026-11-24", "operator_name": "J. Borg", "puffs_readings": [{"time_slot": "08:00"}]},
			)
		doc.insert.assert_not_called()

		# with its Operator, the name shown with it goes along (the server sets it again)
		qh.create_qc_record(
			"QC Puffs Extruder Record",
			payload={
				"record_date": "2026-11-24",
				"operator": "HR-EMP-00001",
				"operator_name": "J. Borg",
				"puffs_readings": [{"time_slot": "08:00"}],
			},
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
		# a Select left unset takes its first option when Frappe saves the record
		# (Shift's was Morning until 2026-11), which nobody picked: a blank one is
		# sent as blank, for the record to ask for it
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


class TestPackagingAndWeightForm(unittest.TestCase):
	"""The Packaging and Weight tab's form records a packaging check and a weight
	check together, the Record Details they share asked for once."""

	DETAILS = {
		"record_date": "2026-11-13",
		"shift": "Morning",
		"factory_line": "PACKING LINE 2",
		"work_order": "MFG-WO-2026-00412",
		"operator": "HR-EMP-00001",
		"operator_name": "J. Borg",
		"qc_inspector": "qc@example.com",
	}

	@staticmethod
	def _meta(fieldnames):
		meta = MagicMock()
		meta.fields = [frappe._dict(fieldname=f, fieldtype="Data") for f in fieldnames]
		meta.get_label.return_value = "Samples"
		return meta

	def _metas(self, doctype):
		return {
			"QC Packaging Check": self._meta([*self.DETAILS, "print_quality_ok", "qty_wasted", "remarks", "status"]),
			"QC Weight Check": self._meta([*self.DETAILS, "item_code", "batch_no", "nominal_weight", "remarks", "status"]),
			"QC Weight Sample": self._meta(["sample_no", "gross_weight", "remarks", "status"]),
		}[doctype]

	def _records(self):
		return [
			{"doctype": "QC Packaging Check", "payload": {"print_quality_ok": 1, "qty_wasted": 0.8, "remarks": "Film changed"}},
			{
				"doctype": "QC Weight Check",
				"payload": {"nominal_weight": 40, "samples": [{"sample_no": 1, "gross_weight": 40.6, "status": "Pass"}]},
			},
		]

	def _docs(self, get_doc):
		"""A doc per doctype, recording the order of their inserts and submits."""
		calls = []
		docs = {}
		for doctype, code in (("QC Packaging Check", "QCG"), ("QC Weight Check", "QCI")):
			doc = MagicMock(docstatus=0, doctype=doctype)
			doc.name = f"{code}-2026-00001"
			doc.insert.side_effect = lambda code=code: calls.append(f"insert {code}")
			doc.submit.side_effect = lambda code=code: calls.append(f"submit {code}")
			docs[doctype] = doc
		get_doc.side_effect = lambda data: docs[data["doctype"]]
		return docs, calls

	@patch("frappe.get_doc")
	@patch("frappe.get_meta")
	def test_both_inserted_before_either_is_submitted(self, get_meta, get_doc):
		get_meta.side_effect = self._metas
		docs, calls = self._docs(get_doc)

		with patch.object(frappe.local, "db", MagicMock()):
			result = qh.create_qc_records(details=self.DETAILS, records=self._records(), submit=1)

		self.assertEqual(calls, ["insert QCG", "insert QCI", "submit QCG", "submit QCI"])
		self.assertEqual([r["name"] for r in result], ["QCG-2026-00001", "QCI-2026-00001"])
		# the Record Details on each, and each record's own fields on it alone
		packaging, weight = (c.args[0] for c in get_doc.call_args_list)
		for data in (packaging, weight):
			self.assertEqual({k: data[k] for k in self.DETAILS}, self.DETAILS)
		self.assertEqual(packaging["remarks"], "Film changed")
		self.assertNotIn("remarks", weight)
		self.assertNotIn("nominal_weight", packaging)
		docs["QC Weight Check"].append.assert_called_once_with("samples", {"sample_no": 1, "gross_weight": 40.6, "status": "Pass"})
		docs["QC Packaging Check"].append.assert_not_called()

	@patch("frappe.get_doc")
	@patch("frappe.get_meta")
	def test_drafts_are_not_submitted(self, get_meta, get_doc):
		get_meta.side_effect = self._metas
		_docs, calls = self._docs(get_doc)

		with patch.object(frappe.local, "db", MagicMock()):
			qh.create_qc_records(details=json.dumps(self.DETAILS), records=json.dumps(self._records()), submit=0)

		self.assertEqual(calls, ["insert QCG", "insert QCI"])
		self.assertEqual([c.args[0]["status"] for c in get_doc.call_args_list], ["Draft", "Draft"])

	@patch("frappe.get_doc")
	@patch("frappe.get_meta")
	def test_the_details_are_the_same_on_both(self, get_meta, get_doc):
		get_meta.side_effect = self._metas
		self._docs(get_doc)
		records = self._records()
		records[1]["payload"]["shift"] = "Night"

		with patch.object(frappe.local, "db", MagicMock()):
			qh.create_qc_records(details=self.DETAILS, records=records)

		self.assertEqual([c.args[0]["shift"] for c in get_doc.call_args_list], ["Morning", "Morning"])

	@patch("frappe.get_doc")
	@patch("frappe.get_meta")
	def test_one_failing_keeps_neither(self, get_meta, get_doc):
		get_meta.side_effect = self._metas
		docs, calls = self._docs(get_doc)
		docs["QC Weight Check"].insert.side_effect = frappe.ValidationError("Status is required in Samples (row 1).")

		with patch.object(frappe.local, "db", MagicMock()) as db, self.assertRaises(frappe.ValidationError):
			qh.create_qc_records(details=self.DETAILS, records=self._records(), submit=1)

		self.assertEqual(calls, ["insert QCG"])
		db.savepoint.assert_called_once_with("create_qc_records")
		db.rollback.assert_called_once_with(save_point="create_qc_records")

	@patch("frappe.get_doc")
	@patch("frappe.get_meta")
	def test_either_on_its_own(self, get_meta, get_doc):
		get_meta.side_effect = self._metas
		_docs, calls = self._docs(get_doc)

		with patch.object(frappe.local, "db", MagicMock()):
			qh.create_qc_records(details=self.DETAILS, records=self._records()[1:], submit=1)

		self.assertEqual(calls, ["insert QCI", "submit QCI"])

	@patch("frappe.get_doc")
	def test_only_a_packaging_check_and_a_weight_check(self, get_doc):
		for records in (
			[],
			[{"doctype": "QC Tasting Record", "payload": {}}],
			[{"doctype": "QC Weight Check", "payload": {}}, {"doctype": "QC Weight Check", "payload": {}}],
			["QC Weight Check"],
		):
			with self.subTest(records=records), self.assertRaises(frappe.ValidationError):
				qh.create_qc_records(details=self.DETAILS, records=records)
		get_doc.assert_not_called()

	def test_no_item_from_the_work_order(self):
		# the weight check names no item since 2026-11: nothing fills one in
		self.assertFalse(hasattr(qh, "get_work_order_product"))
		script = self._script()
		for gone in ("get_work_order_product", "setup_packaging_and_weight", "item_code_was"):
			self.assertNotIn(gone, script)

	@staticmethod
	def _script():
		with open(os.path.join(os.path.dirname(__file__), "quality_hub.js")) as fh:
			return fh.read()

	def _dialog_fields(self, doctype, next_block):
		script = self._script()
		start = script.index(f'"{doctype}": {{')
		block = script[start : script.index(next_block, start)]
		parent = block.split("child_fields: [")[0]
		return re.findall(r'fieldname: "(\w+)"', parent)

	def test_the_two_dialogs_share_their_record_details(self):
		packaging = self._dialog_fields("QC Packaging Check", '"QC Metal Detector Log": {')
		weight = self._dialog_fields("QC Weight Check", "\n};")
		details = packaging[: packaging.index("sb_packaging")]
		# asked for once, so they must be the same fields on both
		self.assertEqual(details, weight[: weight.index("sb_product")])
		self.assertEqual(
			[f for f in details if not f.startswith(("sb_", "cb_"))],
			list(self.DETAILS),
		)
		# and the rest of each record's fields can sit in one form
		self.assertFalse(set(packaging[len(details) :]) & set(weight[len(details) :]))

	def test_the_tab_opens_the_form(self):
		script = self._script()
		self.assertIn('data-tab="pkg_weight">${__("Packaging and Weight Checks (QCG/QCI)")}', script)
		tab = script[script.index('<!-- TAB: Packaging & Weight -->') : script.index("<!-- TAB: CCP & Metal Detector -->")]
		self.assertIn('class="btn btn-sm btn-primary qh-new-packaging-and-weight"', tab)
		self.assertIn('__("New Packaging and Weight Check")', tab)
		self.assertNotIn("qh-new-record", tab)
		form = script[script.index("isnack.quality_hub.PACKAGING_AND_WEIGHT = {") :]
		form = form[: form.index("\n};")]
		self.assertEqual(re.findall(r'doctype: "([^"]+)"', form), ["QC Packaging Check", "QC Weight Check"])
		self.assertIn("isnack.isnack.page.quality_hub.quality_hub.create_qc_records", script)

	@patch("frappe.get_doc")
	@patch("frappe.get_meta")
	def test_a_payload_cannot_change_the_record_type(self, get_meta, get_doc):
		get_meta.side_effect = self._metas
		self._docs(get_doc)
		records = self._records()
		records[0]["payload"]["doctype"] = "ToDo"

		with patch.object(frappe.local, "db", MagicMock()):
			qh.create_qc_records(details={**self.DETAILS, "doctype": "Note"}, records=records)

		self.assertEqual([c.args[0]["doctype"] for c in get_doc.call_args_list], ["QC Packaging Check", "QC Weight Check"])

	def test_a_zero_survives_the_dialog(self):
		# a dialog draws a field it has no document for as `value || null`: a
		# Qty Wasted of 0 is read once, and drawn again where it would be lost
		script = self._script()
		self.assertIn("primary_action: (values) => this.handle_combined_save(dialog, records, false, values),", script)
		self.assertIn("primary_action: (values) => this.handle_dialog_save(dialog, doctype, false, values),", script)
		self.assertIn('this.set_dialog_df_property(dialog, df.fieldname, "reqd", on ? 1 : 0);', script)
		self.assertEqual(script.count("dialog.get_values()"), 1)


class TestPackagingAndWeightList(unittest.TestCase):
	"""The Packaging and Weight tab lists the packaging checks and the weight
	checks in one list: a Check column says which each is, and a Check filter
	lists one alone, as the two pills the tab had did."""

	ROWS = {
		"QC Packaging Check": [
			{"name": "QCG-2026-00003", "record_date": datetime.date(2026, 11, 14), "modified": datetime.datetime(2026, 11, 14, 9, 0)},
			{"name": "QCG-2026-00002", "record_date": datetime.date(2026, 11, 13), "modified": datetime.datetime(2026, 11, 14, 8, 0)},
		],
		"QC Weight Check": [
			{"name": "QCI-2026-00007", "record_date": datetime.date(2026, 11, 14), "modified": datetime.datetime(2026, 11, 14, 9, 5)},
			# changed last, but of an earlier day
			{"name": "QCI-2026-00006", "record_date": datetime.date(2026, 11, 12), "modified": datetime.datetime(2026, 11, 14, 10, 0)},
		],
	}

	def setUp(self):
		meta = MagicMock()
		meta.fields = [frappe._dict(fieldname=f) for f in ("record_date", "shift", "factory_line", "work_order", "overall_status")]
		for target, value in (
			("frappe.get_meta", meta),
			("frappe.db.table_exists", True),
			("frappe.has_permission", True),
		):
			patcher = patch(target, return_value=value)
			self.addCleanup(patcher.stop)
			setattr(self, target.rsplit(".", 1)[1], patcher.start())
		patcher = patch("frappe.get_list", side_effect=lambda doctype, **kw: [frappe._dict(r) for r in self.ROWS[doctype]][: kw["limit"]])
		self.addCleanup(patcher.stop)
		self.get_list = patcher.start()

	def test_both_in_one_list_newest_first(self):
		records = qh.get_packaging_and_weight_records(limit=50)

		# by date, then by when changed, as each list is ordered
		self.assertEqual(
			[(r.name, r.doctype) for r in records],
			[
				("QCI-2026-00007", "QC Weight Check"),
				("QCG-2026-00003", "QC Packaging Check"),
				("QCG-2026-00002", "QC Packaging Check"),
				("QCI-2026-00006", "QC Weight Check"),
			],
		)
		self.assertEqual([c.args[0] for c in self.get_list.call_args_list], list(qh.COMBINED_DOCTYPES))
		for call in self.get_list.call_args_list:
			self.assertEqual(call.kwargs["order_by"], "record_date desc, modified desc")
			self.assertFalse(call.kwargs.get("ignore_permissions"))

	def test_the_newest_of_both_up_to_the_limit(self):
		records = qh.get_packaging_and_weight_records(limit="3")

		self.assertEqual([r.name for r in records], ["QCI-2026-00007", "QCG-2026-00003", "QCG-2026-00002"])
		self.assertEqual({c.kwargs["limit"] for c in self.get_list.call_args_list}, {3})

	def test_the_check_filter_lists_one_alone(self):
		filters = {"check": "QC Weight Check", "work_order": "MFG-WO-2026-00412", "docstatus": "1"}

		records = qh.get_packaging_and_weight_records(filters=json.dumps(filters), limit=50)

		self.assertEqual([r.name for r in records], ["QCI-2026-00007", "QCI-2026-00006"])
		self.get_list.assert_called_once()
		self.assertEqual(self.get_list.call_args.args[0], "QC Weight Check")
		# the other filters are the list's own; Check is not a field
		self.assertEqual(self.get_list.call_args.kwargs["filters"], {"work_order": "MFG-WO-2026-00412", "docstatus": "1"})

	def test_only_a_packaging_or_a_weight_check(self):
		for check in ("QC Tasting Record", "ToDo", ["QC Weight Check"]):
			with self.subTest(check=check), self.assertRaises(frappe.ValidationError):
				qh.get_packaging_and_weight_records(filters={"check": check})
		with self.assertRaises(frappe.ValidationError):
			qh.get_packaging_and_weight_records(filters='["QC Weight Check"]')
		self.get_list.assert_not_called()

	def test_a_check_the_user_may_not_read_is_left_out(self):
		self.has_permission.side_effect = lambda doctype, ptype: doctype == "QC Packaging Check"

		records = qh.get_packaging_and_weight_records(limit=50)

		self.assertEqual({r.doctype for r in records}, {"QC Packaging Check"})
		self.assertEqual([c.args[0] for c in self.get_list.call_args_list], ["QC Packaging Check"])
		# asked for alone, it is refused, as its own list was
		with self.assertRaises(frappe.PermissionError):
			qh.get_packaging_and_weight_records(filters={"check": "QC Weight Check"})

	def test_the_list_needs_a_check_the_user_may_read(self):
		self.has_permission.return_value = False

		with self.assertRaises(frappe.PermissionError):
			qh.get_packaging_and_weight_records()
		self.get_list.assert_not_called()

	def test_the_tab_has_one_list(self):
		script = TestPackagingAndWeightForm._script()
		tab = script[script.index("<!-- TAB: Packaging & Weight -->") : script.index("<!-- TAB: CCP & Metal Detector -->")]
		# no pills: one list, and a Check filter in the filter bar
		self.assertNotIn("qh-sub-nav", tab)
		self.assertNotIn("qh-pill-nav", tab)
		self.assertEqual(
			re.findall(r'<option value="([^"]*)">', tab[tab.index('data-filter="check"') :].split("</select>")[0]),
			["", *qh.COMBINED_DOCTYPES],
		)
		# the tab's list is read with the endpoint for both
		load = script[script.index("    load_records(tab, filters) {") : script.index("    render_record_list(tab, doctype, records) {")]
		pkg_branch = load[: load.index("const dtmap")]
		self.assertIn('if (tab === "pkg_weight") {', pkg_branch)
		self.assertIn("isnack.isnack.page.quality_hub.quality_hub.get_packaging_and_weight_records", pkg_branch)
		self.assertNotIn("active_pkg_sub", script)
		# each row opens its own record; a v1 "#Form/..." link opened "Page #Form not found"
		self.assertIn("frappe.utils.get_form_link(row_doctype, val)", script)
		self.assertNotIn('<a href="#Form/${', script)
		self.assertIn('data-doctype="${frappe.utils.escape_html(row_doctype)}"', script)
		self.assertIn('frappe.set_route("Form", $(e.currentTarget).attr("data-doctype"), name);', script)
		# a Check column, after Name, on this tab
		render = script[script.index("    render_record_list(tab, doctype, records) {") :]
		self.assertIn('const check_cols = tab === "pkg_weight" ? [{ key: "doctype", label: __("Check") }] : [];', render)
		cols = render[render.index("const cols = [") :]
		cols = cols[: cols.index("];")]
		self.assertLess(cols.index('{ key: "name"'), cols.index("...check_cols,"))
		self.assertIn("check_labels[val]", render)
		# coming back to the tab, the list is the one its filter bar shows
		show_tab = script[script.index("    show_tab(tab) {") : script.index("    load_records(tab, filters) {")]
		self.assertIn('this.load_records("pkg_weight", this.get_filters("pkg_weight"));', show_tab)


class TestLiveMonitor(unittest.TestCase):
	def test_an_out_of_range_reading_opens_its_inspection(self):
		script = TestPackagingAndWeightForm._script()
		# Frappe v15 routes an href starting "#" as a page: "#Form/..." opened "Page #Form not found"
		self.assertNotIn('href="#Form/', script)
		table = script[script.index("render_out_of_range_table(rows) {") :]
		self.assertIn(
			'frappe.utils.get_form_link("Quality Inspection", r.quality_inspection)',
			table,
		)
		self.assertIn("const inspection = r.quality_inspection", table)
		self.assertIn("<td>${inspection}</td>", table)
