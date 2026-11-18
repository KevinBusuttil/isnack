# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""The metal detector log with its detector picked from the Metal Detectors
used on its factory line, without a calibration certificate, a corrective
action or each test's sensitivity setting and remarks, its detector and each
test's time and test piece mandatory (2026-11), and the logs made before, which
keep what they recorded (no database)."""

import datetime
import json
import os
import shutil
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import call, patch

import frappe
from frappe.model.base_document import BaseDocument
from isnack.isnack.doctype.qc_metal_detector_log.qc_metal_detector_log import (
	RETIRED_FIELDS,
	RETIRED_TEST_FIELDS,
	QCMetalDetectorLog,
	belongs_to_earlier_layout,
)
from isnack.isnack.doctype.qc_metal_detector_test.qc_metal_detector_test import QCMetalDetectorTest
from isnack.patches.v1_0 import metal_detector_lines_from_qc_logs as lines_module
from isnack.patches.v1_0 import metal_detectors_from_qc_logs as seed_module
from isnack.patches.v1_0 import qc_metal_detector_log_corrective_action as corrective_module
from isnack.patches.v1_0 import qc_metal_detector_log_earlier_layout as patch_module
from isnack.utils import earlier_layout

DOCTYPE_DIR = os.path.join(os.path.dirname(__file__), "..")


def _doctype(name):
	folder = name.lower().replace(" ", "_")
	with open(os.path.join(DOCTYPE_DIR, folder, f"{folder}.json")) as fh:
		return json.load(fh)


def _fields(doc):
	return {f["fieldname"]: f for f in doc["fields"]}


class _Row(frappe._dict):
	def set(self, fieldname, value):
		self[fieldname] = value


class _Log(_Row):
	"""A metal detector log as the controller sees it."""

	meta = SimpleNamespace(has_field=lambda fieldname: True)
	validate = QCMetalDetectorLog.validate
	refuse_retired_values = QCMetalDetectorLog.refuse_retired_values
	check_metal_detector = QCMetalDetectorLog.check_metal_detector
	check_detector_on_line = QCMetalDetectorLog.check_detector_on_line
	keep_details_verified_under = QCMetalDetectorLog.keep_details_verified_under
	require_detector_and_tests = QCMetalDetectorLog.require_detector_and_tests
	before_submit = QCMetalDetectorLog.before_submit
	on_trash = QCMetalDetectorLog.on_trash

	def is_new(self):
		return not self.saved

	def get_doc_before_save(self):
		return self.saved


class _BeforeMigrate(_Log):
	"""Before the migrate adds the mark: the doctype has no earlier_layout."""

	meta = SimpleNamespace(has_field=lambda fieldname: fieldname != "earlier_layout")


def _test(detected=1, **values):
	return _Row({"test_time": "08:00", "test_piece_type": "Fe", "test_piece_size_mm": 0.2, "sensitivity_setting": None, "test_remarks": None, **values}, detected=detected)


def _log(*tests, cls=_Log, **values):
	doc = cls(doctype="QC Metal Detector Log", tests=list(tests), calibration_certificate=None, corrective_action=None, earlier_layout=0, amended_from=None, saved=None)
	doc.update(values)
	return doc


class TestTheLog(unittest.TestCase):
	@patch("frappe.db.exists", return_value=True)
	def test_all_tests_passed_when_each_test_piece_was_detected(self, _exists):
		doc = _log(_test(1), _test(1, test_piece_type="Non-Fe"), metal_detector_id="MD-1")
		doc.validate()
		self.assertEqual(doc.all_tests_passed, 1)

		doc = _log(_test(1), _test(0, test_piece_type="Stainless"), metal_detector_id="MD-1")
		doc.validate()
		self.assertEqual(doc.all_tests_passed, 0)

		doc = _log(metal_detector_id="MD-1")
		doc.validate()
		self.assertEqual(doc.all_tests_passed, 0)

	def test_a_form_from_before_the_change_is_told_to_reload(self):
		# a desk form or a Quality Hub page loaded before the change still
		# offers the certificate, the corrective action and each test's
		# sensitivity setting and remarks: a new log would keep them out of sight
		for doc in (
			_log(_test(), calibration_certificate="/files/cert.pdf"),
			_log(_test(0), corrective_action="line stopped, product held"),
			_log(_test(sensitivity_setting="Fe 1.5")),
			_log(_test(), _test(test_remarks="belt stopped")),
		):
			with self.assertRaisesRegex(frappe.ValidationError, "This page is out of date"):
				doc.validate()

	@patch("frappe.db.exists", return_value=True)
	def test_nothing_said_is_nothing_kept_out_of_sight(self, _exists):
		# a stray space or line break: no value, and none kept
		doc = _log(_test(sensitivity_setting=" ", test_remarks="\n"), calibration_certificate=" ", corrective_action=" \n", metal_detector_id="MD-1")
		doc.validate()
		self.assertEqual(
			(doc.calibration_certificate, doc.corrective_action, doc.tests[0].sensitivity_setting, doc.tests[0].test_remarks),
			(None, None, None, None),
		)
		self.assertEqual(doc.all_tests_passed, 1)

	def test_a_log_made_before_keeps_them(self):
		doc = _log(_test(sensitivity_setting="Fe 1.5", test_remarks="ok"), earlier_layout=1, calibration_certificate="/files/cert.pdf", corrective_action="re-screened")
		doc.validate()
		self.assertEqual((doc.calibration_certificate, doc.corrective_action), ("/files/cert.pdf", "re-screened"))
		self.assertEqual((doc.tests[0].sensitivity_setting, doc.tests[0].test_remarks), ("Fe 1.5", "ok"))

	def test_before_the_migrate_every_log_is_one_made_before(self):
		doc = _log(_test(sensitivity_setting="Fe 1.5"), cls=_BeforeMigrate, calibration_certificate="/files/cert.pdf")
		del doc["earlier_layout"]
		doc.validate()
		self.assertEqual(doc.calibration_certificate, "/files/cert.pdf")
		self.assertNotIn("earlier_layout", doc)


@patch("frappe.db.exists", side_effect=lambda doctype, name: name.strip().upper() if name.strip().upper() in ("MD-1", "MD-2") else None)
class TestTheDetector(unittest.TestCase):
	"""Frappe does not check a Link that fields are fetched from (v15): the
	log checks its Metal Detector ID names a Metal Detector."""

	def test_a_detector_there_is(self, exists):
		doc = _log(_test(), metal_detector_id="MD-1")
		doc.validate()
		exists.assert_called_once_with("Metal Detector", "MD-1")
		# spelled otherwise, as the database matches it
		_log(_test(), metal_detector_id="md-2 ").validate()

	def test_a_detector_there_is_not(self, exists):
		# a page from before the change, the API, a draft whose ID was not made a detector
		for doc in (_log(_test(), metal_detector_id="MD-3", detector_make_model="typed"), _log(_test(), earlier_layout=1, metal_detector_id="<MD-8>")):
			with self.assertRaisesRegex(frappe.LinkValidationError, "Could not find Metal Detector"):
				doc.validate()

	def test_no_detector(self, exists):
		# mandatory on a log made since (TestDetectorAndTestsMandatory); one
		# made before, without one, is not looked for
		_log(_test(), metal_detector_id=None, earlier_layout=1).validate()
		_log(_test(), metal_detector_id=None, factory_line="FRYING", earlier_layout=1).validate()
		exists.assert_not_called()


class TestDetectorAndTestsMandatory(unittest.TestCase):
	"""Since 2026-11 the Metal Detector ID, and each test's Test Time and Test
	Piece Type, are mandatory; a log made before keeps what it recorded."""

	@patch("frappe.db.exists", return_value=True)
	def test_a_log_made_since_names_its_detector(self, exists):
		for detector in (None, "", "  "):
			with self.subTest(detector=detector), self.assertRaisesRegex(frappe.ValidationError, r"Metal Detector ID is required\."):
				_log(_test(), metal_detector_id=detector).validate()
		exists.assert_not_called()

	@patch("frappe.db.exists", return_value=True)
	def test_each_test_has_its_time_and_test_piece(self, _exists):
		doc = _log(_test(idx=1), _test(test_time=None, idx=2), _test(test_time="", idx=3), metal_detector_id="MD-1")
		with self.assertRaisesRegex(frappe.ValidationError, r"Test Time is required in Tests \(row 2, 3\)\."):
			doc.validate()
		doc = _log(_test(idx=1), _test(test_piece_type="", idx=2), _test(test_piece_type=None, idx=3), metal_detector_id="MD-1")
		with self.assertRaisesRegex(frappe.ValidationError, r"Test Piece Type is required in Tests \(row 2, 3\)\."):
			doc.validate()

	@patch("frappe.db.exists", return_value=True)
	def test_a_test_at_midnight_has_a_time(self, _exists):
		# a Time reads as a timedelta, and 00:00 is a time
		_log(_test(test_time=datetime.timedelta(0)), metal_detector_id="MD-1").validate()

	@patch("frappe.db.exists")
	def test_not_on_a_log_made_before(self, exists):
		doc = _log(_test(test_time=None, test_piece_type=""), earlier_layout=1, metal_detector_id=None)
		doc.validate()
		exists.assert_not_called()
		self.assertEqual(doc.all_tests_passed, 1)


class TestSubmitted(unittest.TestCase):
	def test_not_without_a_test(self):
		# the Quality Hub asks for one before it saves; the desk form, before it submits
		for earlier in (0, 1):
			with self.subTest(earlier=earlier), self.assertRaisesRegex(
				frappe.ValidationError, r"Add at least one row in Tests to submit the log\."
			):
				_log(earlier_layout=earlier, metal_detector_id="MD-1").before_submit()
		_log(_test(), metal_detector_id="MD-1").before_submit()


class TestATestAsSent(unittest.TestCase):
	def test_frappe_fills_in_neither_its_time_nor_its_test_piece(self):
		# saving a log, Frappe gives a new test what it was not sent from a new
		# test's defaults (a Time the time of saving, a Select its first option):
		# not these two, which the log asks for instead
		defaults = {"test_time": "16:13:00", "test_piece_type": "Fe", "test_piece_size_mm": 0.2}
		with patch.object(QCMetalDetectorTest, "_get_table_fields", return_value=()), patch(
			"frappe.get_meta", side_effect=AssertionError("no meta")
		):
			test = QCMetalDetectorTest.__new__(QCMetalDetectorTest)
			BaseDocument.__init__(test, {"doctype": "QC Metal Detector Test", "parentfield": "tests"})
			test.update_if_missing(defaults)
			self.assertEqual([test.get(f) for f in defaults], [None, None, 0.2])
			# what Frappe gives any other row
			test.dont_update_if_missing = []
			test.update_if_missing(defaults)
			self.assertEqual([test.get(f) for f in defaults], ["16:13:00", "Fe", 0.2])


class TestDeleted(unittest.TestCase):
	def test_a_draft_from_before_a_restore_could_not_finish_keeps_the_earlier_layout(self):
		# a restore is saved as a new log made since, which cannot fill in what
		# is missing: the snapshot keeps the earlier layout
		for doc in (
			_log(_test(), saved=_log(), metal_detector_id=None),
			_log(_test(test_time=None), saved=_log(), metal_detector_id="MD-1"),
			_log(_test(test_piece_type=""), saved=_log(), metal_detector_id="MD-1"),
		):
			doc.on_trash()
			self.assertEqual(doc.earlier_layout, 1)

	def test_a_log_made_since_is_deleted_as_it_is(self):
		for doc in (_log(_test(), saved=_log(), metal_detector_id="MD-1"), _log(saved=_log(), metal_detector_id="MD-1")):
			doc.on_trash()
			self.assertEqual(doc.earlier_layout, 0)


_ON_LINES = {"MD-1": ("CORN EXTRUSION", "FRYING"), "MD-2": ("RICE EXTRUSION",)}


def _exists(doctype, name):
	"""The database: Metal Detectors MD-1 and MD-2 and their Factory Lines
	(matched, as the database does, whatever their case or trailing spaces)."""
	same = lambda one, other: one.rstrip(" ").upper() == other.upper()
	if doctype == "Metal Detector":
		return next((d for d in _ON_LINES if same(name, d)), None)
	assert doctype == "Metal Detector Factory Line"
	assert (name["parenttype"], name["parentfield"]) == ("Metal Detector", "factory_lines")
	return next(
		(f"row-{d}-{line}" for d, lines in _ON_LINES.items() for line in lines if same(name["parent"], d) and same(name["factory_line"], line)),
		None,
	)


@patch("frappe.db.exists", side_effect=_exists)
class TestTheLine(unittest.TestCase):
	"""A log picks a Metal Detector used on its factory line (its Factory
	Lines): the Quality Hub and the form offer only those, but a Link takes
	any detector typed in full."""

	def test_a_detector_used_on_the_line(self, exists):
		for line in ("CORN EXTRUSION", "frying "):
			_log(_test(), metal_detector_id="MD-1", factory_line=line).validate()
		self.assertIn(
			call("Metal Detector Factory Line", {"parenttype": "Metal Detector", "parentfield": "factory_lines", "parent": "MD-1", "factory_line": "CORN EXTRUSION"}),
			exists.call_args_list,
		)
		# spelled otherwise, as the database matches it
		_log(_test(), metal_detector_id="md-2 ", factory_line="Rice Extrusion").validate()

	@patch("frappe.db.get_value")
	def test_a_detector_not_used_on_the_line(self, get_value, _exists):
		for doc in (
			_log(_test(), metal_detector_id="MD-2", factory_line="CORN EXTRUSION"),
			_log(_test(), metal_detector_id="MD-1", factory_line="RICE EXTRUSION", saved=_log()),
			# a log made before is refused one too
			_log(_test(), metal_detector_id="MD-1", factory_line="PACKING LINE 1", earlier_layout=1),
		):
			with self.assertRaisesRegex(frappe.ValidationError, r"Metal Detector .*MD-\d.* is not used on .*\. Pick a metal detector on that line"):
				doc.validate()
		get_value.assert_not_called()

	def test_no_line(self, exists):
		_log(_test(), metal_detector_id="MD-2", factory_line=None).validate()
		self.assertEqual([c.args[0] for c in exists.call_args_list], ["Metal Detector"])

	@patch("frappe.db.get_value", side_effect=lambda doctype, name, fields, **kw: frappe._dict(metal_detector_id="md-2 ", factory_line="corn extrusion") if fields == ["metal_detector_id", "factory_line"] else 0)
	def test_an_amendment_keeps_its_detector_on_its_line(self, get_value, _exists):
		# MD-2 was on CORN EXTRUSION when the log it amends was verified, and
		# has moved since
		doc = _log(_test(), amended_from="QCH-2026-00020", metal_detector_id="MD-2", factory_line="CORN EXTRUSION")
		doc.validate()
		self.assertIn(call("QC Metal Detector Log", "QCH-2026-00020", ["metal_detector_id", "factory_line"], as_dict=True), get_value.call_args_list)
		# saved again, too
		_log(_test(), amended_from="QCH-2026-00020", metal_detector_id="MD-2", factory_line="CORN EXTRUSION", saved=_log(amended_from="QCH-2026-00020")).validate()

	@patch("frappe.db.get_value", side_effect=lambda doctype, name, fields, **kw: frappe._dict(metal_detector_id="MD-2", factory_line="CORN EXTRUSION") if fields == ["metal_detector_id", "factory_line"] else 0)
	def test_an_amendment_on_another_line_or_detector_is_not_kept(self, _get_value, _exists):
		for detector, line in (("MD-2", "FRYING"), ("MD-1", "PACKING LINE 1")):
			with self.assertRaisesRegex(frappe.ValidationError, "is not used on"):
				_log(_test(), amended_from="QCH-2026-00020", metal_detector_id=detector, factory_line=line).validate()

	@patch("frappe.db.get_value", side_effect=lambda doctype, name, fields, **kw: frappe._dict(metal_detector_id="MD-2", factory_line="PACKING LINE 1") if fields == ["metal_detector_id", "factory_line"] else 0)
	def test_an_amendment_of_another_detector_on_the_same_line_is_not_kept(self, _get_value, _exists):
		# the line kept, the detector changed: MD-1 is not used on PACKING LINE 1
		with self.assertRaisesRegex(frappe.ValidationError, "MD-1.* is not used on .*PACKING LINE 1"):
			_log(_test(), amended_from="QCH-2026-00021", metal_detector_id="MD-1", factory_line="PACKING LINE 1").validate()
		# the amended log's own detector there is kept
		_log(_test(), amended_from="QCH-2026-00021", metal_detector_id="MD-2", factory_line="PACKING LINE 1").validate()

	@patch("frappe.db.get_value", return_value=None)
	def test_an_amendment_of_a_log_there_is_not(self, _get_value, _exists):
		with self.assertRaisesRegex(frappe.ValidationError, "is not used on"):
			_log(_test(), amended_from="QCH-2026-00099", metal_detector_id="MD-2", factory_line="FRYING").validate()


_VERIFIED = {"metal_detector_id": "md-1 ", "detector_make_model": "Loma IQ3", "last_calibration_date": "2026-05-01", "next_calibration_date": "2026-11-30"}
_NOW = {"detector_make_model": "Loma IQ4", "last_calibration_date": "2026-11-30", "next_calibration_date": "2027-05-30"}


@patch("frappe.db.exists", side_effect=lambda doctype, name: name)
class TestAnAmendment(unittest.TestCase):
	"""Frappe fetches the detector's details into a new record: an amendment of
	the same detector keeps those the log it amends was verified under."""

	@patch("frappe.db.get_value", side_effect=lambda doctype, name, fields, **kw: frappe._dict(_VERIFIED) if isinstance(fields, list) else 0)
	def test_of_the_same_detector_keeps_them(self, get_value, _exists):
		doc = _log(_test(), amended_from="QCH-2026-00010", metal_detector_id="MD-1", **_NOW)
		doc.validate()
		self.assertIn(
			call("QC Metal Detector Log", "QCH-2026-00010", ["metal_detector_id", "detector_make_model", "last_calibration_date", "next_calibration_date"], as_dict=True),
			get_value.call_args_list,
		)
		self.assertEqual(
			(doc.detector_make_model, doc.last_calibration_date, doc.next_calibration_date), ("Loma IQ3", "2026-05-01", "2026-11-30")
		)

	@patch("frappe.db.get_value", side_effect=lambda doctype, name, fields, **kw: frappe._dict(_VERIFIED) if isinstance(fields, list) else 0)
	def test_saved_again_and_submitted_it_keeps_them(self, _get_value, _exists):
		# Frappe fetches again on each save of a draft, the amendment's too
		doc = _log(_test(), amended_from="QCH-2026-00010", metal_detector_id="MD-1", saved=_log(amended_from="QCH-2026-00010"), **_NOW)
		doc.validate()
		self.assertEqual((doc.last_calibration_date, doc.next_calibration_date), ("2026-05-01", "2026-11-30"))

	@patch("frappe.db.get_value", side_effect=lambda doctype, name, fields, **kw: frappe._dict(_VERIFIED) if isinstance(fields, list) else 0)
	def test_of_another_detector_takes_its(self, _get_value, _exists):
		doc = _log(_test(), amended_from="QCH-2026-00010", metal_detector_id="MD-2", **_NOW)
		doc.validate()
		self.assertEqual(doc.detector_make_model, "Loma IQ4")

	@patch("frappe.db.get_value")
	def test_a_log_saved_again_or_new_takes_the_detectors(self, get_value, _exists):
		for doc in (_log(_test(), metal_detector_id="MD-1", saved=_log(), **_NOW), _log(_test(), metal_detector_id="MD-1", **_NOW)):
			doc.validate()
			self.assertEqual(doc.last_calibration_date, "2026-11-30")
		get_value.assert_not_called()


class TestTheMarkStays(unittest.TestCase):
	"""earlier_layout is set by the patch and carried by Amend; a form loaded
	before the migrate does not know it and sends none."""

	def test_a_log_made_before_saved_from_a_form_loaded_before_the_migrate(self):
		doc = _log(_test(test_remarks="ok"), saved=_log(earlier_layout=1), earlier_layout=None)
		doc.validate()
		self.assertEqual((doc.earlier_layout, doc.tests[0].test_remarks), (1, "ok"))

	@patch("frappe.db.get_value", return_value=1)
	def test_an_amendment_of_a_log_made_before(self, get_value):
		doc = _log(_test(sensitivity_setting="Fe 1.5"), amended_from="QCH-2026-00003", earlier_layout=None, calibration_certificate="/files/cert.pdf")
		doc.validate()
		get_value.assert_called_once_with("QC Metal Detector Log", "QCH-2026-00003", "earlier_layout")
		self.assertEqual((doc.earlier_layout, doc.calibration_certificate), (1, "/files/cert.pdf"))

	@patch("frappe.db.exists", return_value=True)
	@patch("frappe.db.get_value", return_value=0)
	def test_an_amendment_of_a_log_made_since(self, _get_value, _exists):
		doc = _log(_test(), amended_from="QCH-2026-00009", metal_detector_id="MD-1")
		doc.validate()
		self.assertEqual(doc.earlier_layout, 0)
		with self.assertRaisesRegex(frappe.ValidationError, "This page is out of date"):
			_log(_test(test_remarks="ok"), amended_from="QCH-2026-00009", metal_detector_id="MD-1").validate()


class TestWhichLogsKeepTheEarlierLayout(unittest.TestCase):
	def test_submitted_and_cancelled_logs_keep_it(self):
		for docstatus in (1, 2):
			self.assertTrue(belongs_to_earlier_layout({"docstatus": docstatus}))

	def test_a_draft_keeps_it_when_it_holds_any_of_them(self):
		self.assertTrue(belongs_to_earlier_layout({"docstatus": 0, "calibration_certificate": "/files/cert.pdf"}))
		self.assertTrue(belongs_to_earlier_layout({"docstatus": 0, "corrective_action": "re-screened"}))
		for test in ({"sensitivity_setting": "Fe 1.5"}, {"test_remarks": "ok"}):
			self.assertTrue(belongs_to_earlier_layout({"docstatus": 0}, [{}, test]), test)

	def test_a_draft_with_none_of_them_is_finished_the_new_way(self):
		blank = {"docstatus": 0, "calibration_certificate": " ", "corrective_action": "\n", "metal_detector_id": "MD-1", "detector_make_model": "Loma IQ4"}
		tests = [{"sensitivity_setting": None, "test_remarks": "\n", "test_piece_size_mm": 2.0}]
		self.assertFalse(belongs_to_earlier_layout(blank, tests))
		self.assertFalse(belongs_to_earlier_layout({"docstatus": 0}))


def _record(name, docstatus=0, **values):
	return frappe._dict(name=name, docstatus=docstatus, **values)


@patch("isnack.utils.earlier_layout.forget_grid_columns")
@patch("frappe.db.set_value")
@patch("frappe.db.sql")
@patch("frappe.get_all")
@patch("frappe.db.has_column", return_value=True)
class TestEarlierLayoutPatch(unittest.TestCase):
	def test_the_logs_made_before_are_marked(self, _has, get_all, sql, set_value, forget):
		get_all.side_effect = lambda doctype, **kw: {
			"QC Metal Detector Test": [
				frappe._dict(parent="QCH-4", sensitivity_setting="Fe 1.5", test_remarks=None),
				frappe._dict(parent="QCH-5", sensitivity_setting=None, test_remarks=None),
				frappe._dict(parent="QCH-6", sensitivity_setting="", test_remarks="belt stopped"),
			],
			"QC Metal Detector Log": [
				_record("QCH-1", 1),  # submitted: keeps what it recorded
				_record("QCH-2", 2),  # cancelled: an amendment carries it on
				_record("QCH-3", calibration_certificate="/files/cert.pdf"),  # a draft holding a certificate
				_record("QCH-4"),  # a draft whose test has a sensitivity setting
				_record("QCH-5", calibration_certificate=""),  # a blank draft
				_record("QCH-6"),  # a draft whose test has remarks
			],
			"Deleted Document": [],
		}[doctype]

		patch_module.execute()

		self.assertEqual(
			get_all.call_args_list[0],
			call("QC Metal Detector Test", filters={"parenttype": "QC Metal Detector Log"}, fields=["parent", *RETIRED_TEST_FIELDS]),
		)
		self.assertEqual(get_all.call_args_list[1].kwargs["fields"], ["name", "docstatus", *RETIRED_FIELDS])
		sql.assert_called_once_with(
			"update `tabQC Metal Detector Log` set earlier_layout = 1 where name in %(names)s",
			{"names": ("QCH-1", "QCH-2", "QCH-3", "QCH-4", "QCH-6")},
		)
		set_value.assert_not_called()
		# a user who chose to see them in the Tests grid
		forget.assert_called_once_with("QC Metal Detector Log", "QC Metal Detector Test", RETIRED_TEST_FIELDS)

	def test_a_log_deleted_before_is_restored_as_it_was(self, _has, get_all, sql, set_value, _forget):
		def log(name, tests, docstatus=0, **values):
			return {"doctype": "QC Metal Detector Log", "name": name, "docstatus": docstatus, "metal_detector_id": "MD-1", "tests": tests, **values}

		done = {"detected": 1, "test_time": "08:00:00", "test_piece_type": "Fe"}
		with_remarks = log("QCH-7", [{**done, "test_remarks": "ok"}])
		submitted = log("QCH-9", [], docstatus=2)
		# what a log made since must have and a restore could not fill in
		no_detector = log("QCH-10", [done], metal_detector_id=None)
		no_type = log("QCH-11", [{**done, "test_piece_type": ""}])
		# all a log made since must be: restored as it is
		blank = log("QCH-8", [done])
		no_tests = log("QCH-12", [])
		deleted = (with_remarks, submitted, no_detector, no_type, blank, no_tests)
		get_all.side_effect = lambda doctype, **kw: {
			"QC Metal Detector Test": [],
			"QC Metal Detector Log": [],
			"Deleted Document": [_record(f"DD-{i}", data=json.dumps(d)) for i, d in enumerate(deleted, 1)],
		}[doctype]

		patch_module.execute()

		self.assertEqual(get_all.call_args.kwargs["filters"], {"deleted_doctype": "QC Metal Detector Log", "restored": 0})
		sql.assert_not_called()
		self.assertEqual([c.args[1] for c in set_value.call_args_list], ["DD-1", "DD-2", "DD-3", "DD-4"])
		self.assertEqual(json.loads(set_value.call_args_list[0].args[3]), {**with_remarks, "earlier_layout": 1})
		self.assertEqual(set_value.call_args_list[0].kwargs, {"update_modified": False})

	def test_before_the_column_exists(self, has_column, get_all, sql, set_value, forget):
		has_column.return_value = False
		patch_module.execute()
		get_all.assert_not_called()
		sql.assert_not_called()
		forget.assert_not_called()


@patch("frappe.db.set_value")
@patch("frappe.db.sql")
@patch("frappe.get_all")
@patch("frappe.db.has_column", return_value=True)
class TestCorrectiveActionPatch(unittest.TestCase):
	"""The Corrective Action comes off the log after the Metal Detector change:
	the logs holding one keep it, those made since that change too."""

	def test_the_logs_holding_one_are_marked(self, _has, get_all, sql, set_value):
		holding = {"doctype": "QC Metal Detector Log", "name": "QCH-7", "docstatus": 1, "corrective_action": "held and re-screened"}
		blank = {"doctype": "QC Metal Detector Log", "name": "QCH-8", "docstatus": 1, "corrective_action": " "}
		get_all.side_effect = lambda doctype, **kw: {
			"QC Metal Detector Log": [
				_record("QCH-1", 1, corrective_action="held and re-screened"),  # submitted since the Metal Detector change
				_record("QCH-2", 2, corrective_action="line stopped"),  # cancelled: an amendment carries it on
				_record("QCH-3", corrective_action="re-tested"),  # a draft
				_record("QCH-4", corrective_action=" \n"),  # nothing said
			],
			"Deleted Document": [_record(f"DD-{i}", data=json.dumps(d)) for i, d in enumerate((holding, blank), 1)],
		}[doctype]

		corrective_module.execute()

		self.assertEqual(
			get_all.call_args_list[0],
			call("QC Metal Detector Log", filters={"corrective_action": ["is", "set"]}, fields=["name", "corrective_action"]),
		)
		sql.assert_called_once_with(
			"update `tabQC Metal Detector Log` set earlier_layout = 1 where name in %(names)s",
			{"names": ("QCH-1", "QCH-2", "QCH-3")},
		)
		# deleted before: restored as it was
		self.assertEqual([c.args[1] for c in set_value.call_args_list], ["DD-1"])
		self.assertEqual(json.loads(set_value.call_args.args[3]), {**holding, "earlier_layout": 1})
		self.assertEqual(set_value.call_args.kwargs, {"update_modified": False})

	def test_none_holding_one(self, _has, get_all, sql, set_value):
		get_all.side_effect = lambda doctype, **kw: []
		corrective_module.execute()
		sql.assert_not_called()
		set_value.assert_not_called()

	def test_before_the_column_exists(self, has_column, get_all, sql, _set_value):
		has_column.return_value = False
		corrective_module.execute()
		get_all.assert_not_called()
		sql.assert_not_called()


class _Rows(list):
	"""The Metal Detector Factory Lines the patch inserts, by their values."""

	def get_doc(self, values):
		rows = self

		class _Row:
			def db_insert(self):
				rows.append(values)

		return _Row()


_DETECTORS = ("MD-1", "MD-2", "MD-3")
_LINES = ("CORN EXTRUSION", "FRYING", "RICE EXTRUSION")


def _named(doctype, name):
	"""The database: what a name matches, whatever its case or trailing spaces."""
	return next((n for n in {"Metal Detector": _DETECTORS, "Factory Line": _LINES}[doctype] if n.upper() == name.rstrip(" ").upper()), None)


@patch("frappe.db.exists", side_effect=_named)
@patch("frappe.get_all")
@patch("frappe.db.table_exists", return_value=True)
class TestLinesFromTheLogs(unittest.TestCase):
	def _run(self, get_all, logs, deleted=(), with_lines=()):
		get_all.side_effect = lambda doctype, **kw: {
			"QC Metal Detector Log": [frappe._dict(metal_detector_id=d, factory_line=line) for d, line in logs],
			"Deleted Document": [frappe._dict(data=json.dumps(d)) for d in deleted],
			"Metal Detector Factory Line": list(with_lines),
		}[doctype]
		rows = _Rows()
		with patch("frappe.get_doc", rows.get_doc):
			lines_module.execute()
		return rows

	def test_each_detector_is_given_the_lines_of_its_logs(self, _table, get_all, _exists):
		rows = self._run(
			get_all,
			[("MD-2", "FRYING"), ("MD-1", "FRYING"), ("MD-1", "CORN EXTRUSION"), ("md-1 ", "corn extrusion"), (" MD-2", "FRYING ")],
		)
		self.assertEqual(
			get_all.call_args_list[0],
			call(
				"QC Metal Detector Log",
				# not a cancelled log: one cancelled for its line or detector would
				# put the detector on a line it was logged on by mistake
				filters={"metal_detector_id": ["is", "set"], "factory_line": ["is", "set"], "docstatus": ["!=", 2]},
				fields=["metal_detector_id", "factory_line"],
				distinct=True,
			),
		)
		self.assertEqual(get_all.call_args_list[1].kwargs["filters"], {"deleted_doctype": "QC Metal Detector Log", "restored": 0})
		self.assertEqual(
			get_all.call_args_list[2],
			call(
				"Metal Detector Factory Line",
				filters={"parenttype": "Metal Detector", "parentfield": "factory_lines"},
				pluck="parent",
				distinct=True,
			),
		)
		# each line once, as the line spells it, in order
		self.assertEqual(
			rows,
			[
				{"doctype": "Metal Detector Factory Line", "parent": "MD-1", "parenttype": "Metal Detector", "parentfield": "factory_lines", "idx": 1, "factory_line": "CORN EXTRUSION"},
				{"doctype": "Metal Detector Factory Line", "parent": "MD-1", "parenttype": "Metal Detector", "parentfield": "factory_lines", "idx": 2, "factory_line": "FRYING"},
				{"doctype": "Metal Detector Factory Line", "parent": "MD-2", "parenttype": "Metal Detector", "parentfield": "factory_lines", "idx": 1, "factory_line": "FRYING"},
			],
		)

	def test_a_log_deleted_before_gives_its_line(self, _table, get_all, _exists):
		# a restore needs it
		deleted = [
			{"doctype": "QC Metal Detector Log", "name": "QCH-9", "metal_detector_id": "MD-3", "factory_line": "RICE EXTRUSION"},
			{"doctype": "QC Metal Detector Log", "name": "QCH-10", "metal_detector_id": None, "factory_line": "FRYING"},
			{"doctype": "QC Metal Detector Log", "name": "QCH-11", "metal_detector_id": "MD-3"},
		]
		rows = self._run(get_all, [], deleted=deleted)
		self.assertEqual([(r["parent"], r["factory_line"]) for r in rows], [("MD-3", "RICE EXTRUSION")])

	def test_a_detector_or_line_there_is_not_is_left_out(self, _table, get_all, _exists):
		rows = self._run(get_all, [("MD-9", "FRYING"), ("MD-1", "OLD LINE"), ("MD-1", "FRYING")])
		self.assertEqual([(r["parent"], r["factory_line"]) for r in rows], [("MD-1", "FRYING")])

	def test_a_detector_given_its_lines_already_is_left_as_it_is(self, _table, get_all, _exists):
		rows = self._run(get_all, [("MD-1", "FRYING"), ("MD-2", "FRYING")], with_lines=["MD-1"])
		self.assertEqual([(r["parent"], r["factory_line"]) for r in rows], [("MD-2", "FRYING")])

	def test_before_the_doctype_exists(self, table_exists, get_all, _exists):
		table_exists.return_value = False
		lines_module.execute()
		get_all.assert_not_called()


@patch("frappe.cache")
@patch("frappe.model.utils.user_settings.sync_user_settings")
@patch("frappe.db.sql")
class TestForgetTheColumnsTakenOff(unittest.TestCase):
	def test_only_a_choice_showing_one_of_them_is_forgotten(self, sql, sync, cache):
		showing = {"GridView": {"QC Metal Detector Test": [{"fieldname": "test_time"}, {"fieldname": "test_remarks"}]}, "List": {}}
		not_showing = {"GridView": {"QC Metal Detector Test": [{"fieldname": "test_time"}, {"fieldname": "detected"}]}}
		sql.side_effect = [
			[frappe._dict(user="a@x", data=json.dumps(showing)), frappe._dict(user="b@x", data=json.dumps(not_showing))],
			None,
		]

		earlier_layout.forget_grid_columns("QC Metal Detector Log", "QC Metal Detector Test", RETIRED_TEST_FIELDS)

		sync.assert_called_once()
		updates = sql.call_args_list[1:]
		self.assertEqual([c.args[1][1:] for c in updates], [("a@x", "QC Metal Detector Log")])
		self.assertEqual(json.loads(updates[0].args[1][0]), {"List": {}})
		self.assertEqual([c.args for c in cache.hdel.call_args_list], [("_user_settings", "QC Metal Detector Log::a@x")])


class _Inserted(list):
	"""The Metal Detectors the seed inserts, by their values; ``refuse`` names
	an ID whose insert fails as an invalid name would."""

	def __init__(self, refuse=()):
		super().__init__()
		self.refuse = refuse

	def get_doc(self, values):
		inserted = self

		class _Doc:
			def insert(self, ignore_permissions=False, ignore_mandatory=False):
				if values["metal_detector_id"] in inserted.refuse:
					raise frappe.NameError("Name cannot contain special characters like < >")
				# its Factory Lines come next, from the logs
				assert ignore_permissions and ignore_mandatory
				inserted.append(values)

		return _Doc()


def _log_row(detector_id, docstatus=1, name=None, **values):
	row = dict.fromkeys(seed_module.LOG_FIELDS)
	row.update(values)
	return frappe._dict(name=name or f"QCH-{detector_id}", metal_detector_id=detector_id, docstatus=docstatus, **row)


@patch("frappe.db.sql")
@patch("frappe.clear_last_message")
@patch("frappe.db.rollback")
@patch("frappe.db.savepoint")
@patch("frappe.db.exists", return_value=None)
@patch("frappe.get_all")
@patch("frappe.db.table_exists", return_value=True)
class TestDetectorsFromTheLogs(unittest.TestCase):
	def _seed(self, get_all, logs, refuse=(), deleted=()):
		get_all.side_effect = lambda doctype, **kw: {
			"QC Metal Detector Log": logs,
			"Deleted Document": [frappe._dict(name=f"DD-{i}", data=json.dumps(d)) for i, d in enumerate(deleted)],
		}[doctype]
		inserted = _Inserted(refuse)
		with patch("frappe.get_doc", inserted.get_doc):
			seed_module.execute()
		return inserted

	def test_each_id_the_logs_name_is_a_detector_with_its_newest_details(self, _table, get_all, _exists, *_db):
		d = datetime.date
		logs = [  # newest first, as asked for
			_log_row("MD-1", detector_make_model="Loma IQ4", last_calibration_date=d(2026, 10, 1), next_calibration_date=d(2027, 4, 1)),
			_log_row("MD-2", docstatus=0, detector_make_model="  "),
			_log_row("MD-1", detector_make_model="Loma IQ3", last_calibration_date=d(2026, 4, 1), next_calibration_date=d(2026, 10, 1), calibration_certificate="/files/md1.pdf"),
			_log_row("MD-2", detector_make_model="Mettler Profile", next_calibration_date=d(2027, 1, 15)),
			_log_row("MD-1", detector_make_model="Loma IQ2", calibration_certificate="/files/md1-2025.pdf"),
		]

		inserted = self._seed(get_all, logs)

		self.assertEqual(
			get_all.call_args_list[0],
			call(
				"QC Metal Detector Log",
				filters={"metal_detector_id": ["is", "set"]},
				fields=["name", "metal_detector_id", "docstatus", *seed_module.LOG_FIELDS],
				order_by="record_date desc, modified desc",
			),
		)
		self.assertEqual(
			inserted,
			[
				{
					"doctype": "Metal Detector",
					"metal_detector_id": "MD-1",
					"make_model": "Loma IQ4",
					"last_calibration_date": d(2026, 10, 1),
					"next_calibration_date": d(2027, 4, 1),
					# the newest certificate a log holds
					"calibration_certificate": "/files/md1.pdf",
				},
				{
					"doctype": "Metal Detector",
					"metal_detector_id": "MD-2",
					"make_model": "Mettler Profile",
					# the two dates together, from one log
					"last_calibration_date": None,
					"next_calibration_date": d(2027, 1, 15),
				},
			],
		)

	def test_an_id_differing_in_case_or_spaces_is_the_same_detector(self, _table, get_all, *_db):
		inserted = self._seed(get_all, [_log_row(" md-3 ", detector_make_model="A"), _log_row("MD-3", detector_make_model="B"), _log_row("   ")])
		self.assertEqual(inserted, [{"doctype": "Metal Detector", "metal_detector_id": "md-3", "make_model": "A"}])

	def test_a_log_deleted_before_gives_its_detector_and_details_only_when_no_log_there_is_does(self, _table, get_all, *_db):
		# a restore needs its detector
		deleted = [
			{"doctype": "QC Metal Detector Log", "name": "QCH-20", "metal_detector_id": "MD-10", "detector_make_model": "Deleted", "record_date": "2026-11-01", "modified": "2026-11-01 08:00:00"},
			{"doctype": "QC Metal Detector Log", "name": "QCH-21", "metal_detector_id": "MD-11", "detector_make_model": "Older", "record_date": "2026-10-01", "modified": "2026-10-01 08:00:00"},
			{"doctype": "QC Metal Detector Log", "name": "QCH-22", "metal_detector_id": "MD-11", "detector_make_model": "Newer", "last_calibration_date": "2026-09-01", "record_date": "2026-10-20", "modified": "2026-10-20 08:00:00"},
			{"doctype": "QC Metal Detector Log", "name": "QCH-23", "metal_detector_id": None},
		]
		inserted = self._seed(get_all, [_log_row("MD-10", detector_make_model="Live")], deleted=deleted)
		self.assertEqual(get_all.call_args_list[1].kwargs["filters"], {"deleted_doctype": "QC Metal Detector Log", "restored": 0})
		self.assertEqual(
			inserted,
			[
				{"doctype": "Metal Detector", "metal_detector_id": "MD-10", "make_model": "Live"},
				{"doctype": "Metal Detector", "metal_detector_id": "MD-11", "make_model": "Newer", "last_calibration_date": "2026-09-01", "next_calibration_date": None},
			],
		)

	def test_a_log_whose_id_the_database_does_not_match_is_given_the_detectors_name(self, _table, get_all, exists, _savepoint, _rollback, _clear, sql):
		# the database ignores case and trailing spaces, not a leading space,
		# a tab or a line break
		made = {"MD-12": "MD-12"}
		exists.side_effect = lambda doctype, name: made.get(name.rstrip(" ").upper()) if not name.startswith((" ", "\t")) and not name.endswith(("\t", "\n")) else None
		logs = [
			_log_row("MD-12", name="QCH-30"),
			_log_row("md-12 ", name="QCH-31"),  # matched as it is
			_log_row(" MD-12", name="QCH-32"),
			_log_row("MD-12\t", name="QCH-33"),
			_log_row(" <MD-13>", name="QCH-34"),  # no detector made of it
		]
		with patch("builtins.print"):
			self._seed(get_all, logs, refuse=("<MD-13>",))
		self.assertEqual(
			[c.args for c in sql.call_args_list],
			[
				("update `tabQC Metal Detector Log` set metal_detector_id = %s where name = %s", ("MD-12", "QCH-32")),
				("update `tabQC Metal Detector Log` set metal_detector_id = %s where name = %s", ("MD-12", "QCH-33")),
			],
		)

	def test_a_log_deleted_before_whose_id_the_database_does_not_match_is_given_the_detectors_name(self, _table, get_all, exists, *_db):
		# so a restore leads to its detector
		exists.side_effect = lambda doctype, name: "MD-14" if name.upper() == "MD-14" else None
		deleted = [
			{"doctype": "QC Metal Detector Log", "name": "QCH-40", "metal_detector_id": " md-14", "record_date": "2026-11-02", "earlier_layout": 1},
			{"doctype": "QC Metal Detector Log", "name": "QCH-41", "metal_detector_id": "MD-14", "record_date": "2026-11-01"},
		]
		with patch("frappe.db.set_value") as set_value:
			inserted = self._seed(get_all, [], deleted=deleted)
		self.assertEqual(inserted, [])  # (exists says MD-14 is there)
		self.assertEqual(get_all.call_args_list[1].kwargs["fields"], ["name", "data"])
		self.assertEqual(len(set_value.call_args_list), 1)
		args, kwargs = set_value.call_args
		self.assertEqual(args[:3], ("Deleted Document", "DD-0", "data"))
		self.assertEqual(json.loads(args[3]), {**deleted[0], "metal_detector_id": "MD-14"})
		self.assertEqual(kwargs, {"update_modified": False})

	def test_a_cancelled_log_gives_details_only_when_no_other_does(self, _table, get_all, *_db):
		logs = [
			_log_row("MD-4", docstatus=2, detector_make_model="As cancelled", calibration_certificate="/files/md4.pdf"),
			_log_row("MD-4", detector_make_model="As submitted"),
			_log_row("MD-5", docstatus=2, detector_make_model="Only"),
		]
		inserted = self._seed(get_all, logs)
		self.assertEqual(
			inserted,
			[
				{"doctype": "Metal Detector", "metal_detector_id": "MD-4", "make_model": "As submitted", "calibration_certificate": "/files/md4.pdf"},
				{"doctype": "Metal Detector", "metal_detector_id": "MD-5", "make_model": "Only"},
			],
		)

	def test_a_detector_there_already_is_left_as_it_is(self, _table, get_all, exists, *_db):
		exists.side_effect = lambda doctype, name: name if name == "MD-6" else None
		inserted = self._seed(get_all, [_log_row("MD-6"), _log_row("MD-7")])
		self.assertEqual([d["metal_detector_id"] for d in inserted], ["MD-7"])

	def test_an_id_that_cannot_name_a_record_is_reported_and_left_out(self, _table, get_all, _exists, savepoint, rollback, clear, _sql):
		with patch("builtins.print") as printed:
			inserted = self._seed(get_all, [_log_row("<MD-8>"), _log_row("MD-9")], refuse=("<MD-8>",))
		self.assertEqual([d["metal_detector_id"] for d in inserted], ["MD-9"])
		rollback.assert_called_once_with(save_point="metal_detector_from_logs")
		self.assertEqual(savepoint.call_count, 2)
		clear.assert_called_once()
		self.assertIn("'<MD-8>'", printed.call_args.args[0])

	def test_before_the_doctype_exists(self, table_exists, get_all, *_db):
		table_exists.return_value = False
		seed_module.execute()
		get_all.assert_not_called()


@unittest.skipUnless(shutil.which("node"), "needs node to run the form's code")
class TestTheForm(unittest.TestCase):
	"""The desk form offers the Metal Detectors used on the log's Factory Line,
	and takes off one picked that is not used on a line picked afterwards."""

	def test_the_detectors_offered_and_one_taken_off(self):
		with open(os.path.join(os.path.dirname(__file__), "qc_metal_detector_log.js")) as fh:
			form_script = fh.read()
		script = (
			"const __ = (msg, args) => msg.replace(/\\{(\\d)\\}/g, (_m, i) => args[i]);\n"
			"const lines = {'MD-1': ['CORN EXTRUSION', 'FRYING'], 'MD-2': ['RICE EXTRUSION']};\n"
			"const asked = [], alerts = [], queries = {};\n"
			"let handlers;\n"
			"const frappe = {show_alert: (a) => alerts.push(a.message), ui: {form: {on: (doctype, h) => { handlers = [doctype, h]; }}},\n"
			"  db: {get_list: (doctype, args) => {\n"
			"    asked.push([doctype, args]);\n"
			"    const [[, , name], [, , , line]] = args.filters;\n"
			"    return Promise.resolve((lines[name] || []).includes(line) ? [{name}] : []);\n"
			"  }}};\n"
			f"{form_script}\n"
			"const frm = {doc: {factory_line: '', metal_detector_id: ''}, set_query: (f, q) => { queries[f] = q; }, set_value: (f, v) => { frm.doc[f] = v; }};\n"
			"const flush = () => new Promise((r) => setTimeout(r, 0));\n"
			"(async () => {\n"
			"  const [doctype, h] = handlers;\n"
			"  const out = {doctype};\n"
			"  h.setup(frm);\n"
			"  out.no_line = queries.metal_detector_id();\n"
			"  frm.doc.factory_line = 'FRYING';\n"
			"  out.frying = queries.metal_detector_id();\n"
			"  h.factory_line(frm);\n"
			"  out.asked_without_detector = asked.length;\n"
			"  frm.doc.metal_detector_id = 'MD-1'; frm.doc.factory_line = 'CORN EXTRUSION';\n"
			"  h.factory_line(frm); await flush();\n"
			"  out.kept = frm.doc.metal_detector_id; out.asked = asked[0];\n"
			"  frm.doc.factory_line = 'RICE EXTRUSION';\n"
			"  h.factory_line(frm); await flush();\n"
			"  out.taken_off = frm.doc.metal_detector_id; out.alerts = alerts.slice();\n"
			"  frm.doc.metal_detector_id = 'MD-2'; frm.doc.factory_line = 'FRYING';\n"
			"  h.factory_line(frm); frm.doc.metal_detector_id = 'MD-1'; await flush();\n"
			"  out.changed_again = frm.doc.metal_detector_id;\n"
			"  console.log(JSON.stringify(out));\n"
			"})();\n"
		)
		out = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
		self.assertEqual(out["doctype"], "QC Metal Detector Log")
		# every detector before a line is picked (no filter: no empty "Filters
		# applied for" under them); then those used on it
		self.assertEqual(out["no_line"], {})
		self.assertEqual(out["frying"], {"filters": [["Metal Detector Factory Line", "factory_line", "=", "FRYING"]]})
		self.assertEqual(out["asked_without_detector"], 0)
		self.assertEqual(
			out["asked"],
			["Metal Detector", {"filters": [["name", "=", "MD-1"], ["Metal Detector Factory Line", "factory_line", "=", "CORN EXTRUSION"]], "limit": 1}],
		)
		self.assertEqual(out["kept"], "MD-1")
		self.assertEqual(out["taken_off"], "")
		self.assertEqual(out["alerts"], ["MD-1 is not used on RICE EXTRUSION: pick a metal detector on that line."])
		# the detector changed again before the answer came: left to that change
		self.assertEqual(out["changed_again"], "MD-1")


class TestTheFormMarksThem(unittest.TestCase):
	"""The form marks the Metal Detector ID and the tests' time and test piece
	required on a log made since, not on one made before."""

	@unittest.skipUnless(shutil.which("node"), "needs node to run the form script")
	def test_on_a_log_made_since_only(self):
		with open(os.path.join(os.path.dirname(__file__), "qc_metal_detector_log.js")) as fh:
			form_script = fh.read()
		script = (
			"let handlers;\n"
			"const frappe = {ui: {form: {on: (doctype, h) => { handlers = h; }}}};\n"
			f"{form_script}\n"
			"const run = (earlier, drawn) => {\n"
			"  const calls = [];\n"
			"  const grid = {visible_columns: drawn.map(([fieldname, reqd]) => [{fieldname, reqd}, 2]),\n"
			"    toggle_reqd: (f, on) => calls.push(['grid', f, on]), reset_grid: () => calls.push(['reset'])};\n"
			"  const frm = {doc: {earlier_layout: earlier}, fields_dict: {tests: {grid}}, toggle_reqd: (f, on) => calls.push(['form', f, on])};\n"
			"  handlers.refresh(frm);\n"
			"  return calls;\n"
			"};\n"
			"const unmarked = [['test_time', 0], ['test_piece_type', 0], ['detected', 0]];\n"
			"const marked = [['test_time', 1], ['test_piece_type', 1], ['detected', 0]];\n"
			"console.log(JSON.stringify({since_drawn_unmarked: run(0, unmarked), since_drawn_marked: run(0, marked),\n"
			"  before_drawn_marked: run(1, marked), before_drawn_unmarked: run(1, unmarked), nothing_drawn: run(0, [])}));\n"
		)
		out = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
		since = [["form", "metal_detector_id", True], ["grid", "test_time", True], ["grid", "test_piece_type", True]]
		before = [["form", "metal_detector_id", False], ["grid", "test_time", False], ["grid", "test_piece_type", False]]
		# marked on a log made since, not on one made before; the header drawn
		# again only when its marks are the other log's
		self.assertEqual(out["since_drawn_unmarked"], since + [["reset"]])
		self.assertEqual(out["since_drawn_marked"], since)
		self.assertEqual(out["before_drawn_marked"], before + [["reset"]])
		self.assertEqual(out["before_drawn_unmarked"], before)
		self.assertEqual(out["nothing_drawn"], since)


class TestTheDoctypes(unittest.TestCase):
	def test_the_metal_detector(self):
		doc = _doctype("Metal Detector")
		fields = _fields(doc)
		self.assertEqual(doc["field_order"], [f["fieldname"] for f in doc["fields"]])
		self.assertEqual((doc["autoname"], doc["naming_rule"]), ("field:metal_detector_id", "By fieldname"))
		self.assertEqual(
			{f: (fields[f]["fieldtype"], fields[f]["label"]) for f in ("metal_detector_id", "make_model", "last_calibration_date", "next_calibration_date", "calibration_certificate")},
			{
				"metal_detector_id": ("Data", "Metal Detector ID"),
				"make_model": ("Data", "Make/Model"),
				"last_calibration_date": ("Date", "Last Calibration Date"),
				"next_calibration_date": ("Date", "Next Calibration Date"),
				"calibration_certificate": ("Attach", "Calibration Certificate"),
			},
		)
		self.assertEqual(fields["metal_detector_id"].get("reqd"), 1)
		# the lines it is used on: one at least
		lines = fields["factory_lines"]
		self.assertEqual(
			(lines["fieldtype"], lines["label"], lines["options"], lines.get("reqd")),
			("Table MultiSelect", "Factory Lines", "Metal Detector Factory Line", 1),
		)
		self.assertEqual(doc["field_order"].index("factory_lines"), doc["field_order"].index("make_model") + 1)
		# made from the log's Metal Detector ID without leaving it
		self.assertEqual(doc.get("quick_entry"), 1)
		for fieldname in ("make_model", "factory_lines", "last_calibration_date", "next_calibration_date", "calibration_certificate"):
			self.assertEqual(fields[fieldname].get("allow_in_quick_entry"), 1, fieldname)
		# whoever records a log can pick a detector and read its details
		log_roles = {p["role"] for p in _doctype("QC Metal Detector Log")["permissions"] if p.get("read")}
		self.assertTrue(log_roles <= {p["role"] for p in doc["permissions"] if p.get("read")})

	def test_a_detectors_factory_line(self):
		doc = _doctype("Metal Detector Factory Line")
		self.assertEqual(doc.get("istable"), 1)
		# a Table MultiSelect picks its rows by their one Link
		self.assertEqual(
			[(f["fieldname"], f["fieldtype"], f.get("options"), f.get("reqd"), f.get("in_list_view")) for f in doc["fields"]],
			[("factory_line", "Link", "Factory Line", 1, 1)],
		)

	def test_the_log_takes_the_detectors_details(self):
		doc = _doctype("QC Metal Detector Log")
		fields = _fields(doc)
		order = doc["field_order"]
		self.assertEqual(order, [f["fieldname"] for f in doc["fields"]])
		detector = fields["metal_detector_id"]
		self.assertEqual((detector["fieldtype"], detector["options"], detector["label"]), ("Link", "Metal Detector", "Metal Detector ID"))
		for fieldname, source in (
			("detector_make_model", "make_model"),
			("last_calibration_date", "last_calibration_date"),
			("next_calibration_date", "next_calibration_date"),
		):
			self.assertEqual(fields[fieldname].get("fetch_from"), f"metal_detector_id.{source}", fieldname)
			self.assertEqual(fields[fieldname].get("read_only"), 1, fieldname)
			# kept as it was when the log was saved
			self.assertIsNone(fields[fieldname].get("fetch_if_empty"), fieldname)
		# together, after the detector
		start = order.index("metal_detector_id")
		self.assertEqual(order[start : start + 4], ["metal_detector_id", "detector_make_model", "last_calibration_date", "next_calibration_date"])

	def test_the_logs_earlier_layout(self):
		doc = _doctype("QC Metal Detector Log")
		fields = _fields(doc)
		order = doc["field_order"]
		section = fields["earlier_layout_section"]
		self.assertEqual((section["fieldtype"], section.get("depends_on")), ("Section Break", "eval:doc.earlier_layout"))
		for fieldname in ("metal_detector_id", "tests", "all_tests_passed", "remarks"):
			self.assertLess(order.index(fieldname), order.index("earlier_layout_section"), fieldname)
		self.assertEqual(RETIRED_FIELDS, ("calibration_certificate", "corrective_action"))
		for fieldname in RETIRED_FIELDS:
			self.assertGreater(order.index(fieldname), order.index("earlier_layout_section"), fieldname)
			self.assertEqual(fields[fieldname].get("no_copy"), 1, fieldname)
		# asked for by nothing since: a log made before is not made to give one
		self.assertNotIn("mandatory_depends_on", fields["corrective_action"])
		marker = fields["earlier_layout"]
		self.assertEqual(
			(marker["fieldtype"], marker.get("hidden"), marker.get("read_only"), marker.get("no_copy"), marker.get("print_hide")),
			("Check", 1, 1, 1, 1),
		)

	def test_the_tests(self):
		doc = _doctype("QC Metal Detector Test")
		fields = _fields(doc)
		order = doc["field_order"]
		self.assertEqual(order, [f["fieldname"] for f in doc["fields"]])
		self.assertEqual(
			[f["fieldname"] for f in doc["fields"] if f.get("in_list_view")],
			["test_time", "test_piece_type", "test_piece_size_mm", "detected"],
		)
		self.assertEqual(fields["test_piece_size_mm"].get("default"), "0.2")
		section = fields["earlier_layout_section"]
		self.assertEqual(section.get("depends_on"), "eval:parent.earlier_layout")
		for fieldname in RETIRED_TEST_FIELDS:
			f = fields[fieldname]
			self.assertGreater(order.index(fieldname), order.index("earlier_layout_section"), fieldname)
			# out of the grid, of a Duplicate, and of a print without them
			self.assertEqual((f.get("in_list_view"), f.get("no_copy"), f.get("print_hide_if_no_value")), (None, 1, 1), fieldname)

	def test_mandatory_on_a_log_made_since_only(self):
		# not reqd on the doctypes: a log made before keeps what it recorded (a
		# draft, an amendment, a restore); the form marks them on a log made since
		self.assertIsNone(_fields(_doctype("QC Metal Detector Log"))["metal_detector_id"].get("reqd"))
		tests = _fields(_doctype("QC Metal Detector Test"))
		for fieldname in ("test_time", "test_piece_type"):
			self.assertIsNone(tests[fieldname].get("reqd"), fieldname)
		# and the test piece starts blank: a Select starts at its first option
		self.assertEqual(tests["test_piece_type"]["options"], "\nFe\nNon-Fe\nStainless")
		self.assertNotIn("default", tests["test_piece_type"])

	def test_the_patches_run_in_order(self):
		with open(os.path.join(DOCTYPE_DIR, "..", "..", "patches.txt")) as fh:
			patches = fh.read().split("[post_model_sync]")[1].split()
		# after the model sync makes the Metal Detector, its lines and the mark;
		# the detectors before their lines
		ours = [
			"isnack.patches.v1_0.metal_detectors_from_qc_logs",
			"isnack.patches.v1_0.qc_metal_detector_log_earlier_layout",
			"isnack.patches.v1_0.metal_detector_lines_from_qc_logs",
			"isnack.patches.v1_0.qc_metal_detector_log_corrective_action",
		]
		self.assertEqual([p for p in patches if p in ours], ours)
