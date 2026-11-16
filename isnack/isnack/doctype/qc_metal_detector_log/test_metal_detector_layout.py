# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""The metal detector log with its detector picked from the Metal Detectors,
without a calibration certificate or each test's sensitivity setting and
remarks (2026-11), and the logs made before, which keep them (no database)."""

import datetime
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import call, patch

import frappe
from isnack.isnack.doctype.qc_metal_detector_log.qc_metal_detector_log import (
	RETIRED_FIELDS,
	RETIRED_TEST_FIELDS,
	QCMetalDetectorLog,
	belongs_to_earlier_layout,
)
from isnack.patches.v1_0 import metal_detectors_from_qc_logs as seed_module
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
	keep_details_verified_under = QCMetalDetectorLog.keep_details_verified_under

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
	doc = cls(doctype="QC Metal Detector Log", tests=list(tests), calibration_certificate=None, earlier_layout=0, amended_from=None, saved=None)
	doc.update(values)
	return doc


class TestTheLog(unittest.TestCase):
	def test_all_tests_passed_when_each_test_piece_was_detected(self):
		doc = _log(_test(1), _test(1, test_piece_type="Non-Fe"))
		doc.validate()
		self.assertEqual(doc.all_tests_passed, 1)

		doc = _log(_test(1), _test(0, test_piece_type="Stainless"))
		doc.validate()
		self.assertEqual(doc.all_tests_passed, 0)

		doc = _log()
		doc.validate()
		self.assertEqual(doc.all_tests_passed, 0)

	def test_a_form_from_before_the_change_is_told_to_reload(self):
		# a desk form or a Quality Hub page loaded before the change still
		# offers the certificate and each test's sensitivity setting and
		# remarks: a new log would keep them out of sight
		for doc in (
			_log(_test(), calibration_certificate="/files/cert.pdf"),
			_log(_test(sensitivity_setting="Fe 1.5")),
			_log(_test(), _test(test_remarks="belt stopped")),
		):
			with self.assertRaisesRegex(frappe.ValidationError, "This page is out of date"):
				doc.validate()

	def test_nothing_said_is_nothing_kept_out_of_sight(self):
		# a stray space or line break: no value, and none kept
		doc = _log(_test(sensitivity_setting=" ", test_remarks="\n"), calibration_certificate=" ")
		doc.validate()
		self.assertEqual(
			(doc.calibration_certificate, doc.tests[0].sensitivity_setting, doc.tests[0].test_remarks), (None, None, None)
		)
		self.assertEqual(doc.all_tests_passed, 1)

	def test_a_log_made_before_keeps_them(self):
		doc = _log(_test(sensitivity_setting="Fe 1.5", test_remarks="ok"), earlier_layout=1, calibration_certificate="/files/cert.pdf")
		doc.validate()
		self.assertEqual(doc.calibration_certificate, "/files/cert.pdf")
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
		_log(_test(), metal_detector_id=None).validate()
		exists.assert_not_called()


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

	@patch("frappe.db.get_value", return_value=0)
	def test_an_amendment_of_a_log_made_since(self, _get_value):
		doc = _log(_test(), amended_from="QCH-2026-00009")
		doc.validate()
		self.assertEqual(doc.earlier_layout, 0)
		with self.assertRaisesRegex(frappe.ValidationError, "This page is out of date"):
			_log(_test(test_remarks="ok"), amended_from="QCH-2026-00009").validate()


class TestWhichLogsKeepTheEarlierLayout(unittest.TestCase):
	def test_submitted_and_cancelled_logs_keep_it(self):
		for docstatus in (1, 2):
			self.assertTrue(belongs_to_earlier_layout({"docstatus": docstatus}))

	def test_a_draft_keeps_it_when_it_holds_any_of_them(self):
		self.assertTrue(belongs_to_earlier_layout({"docstatus": 0, "calibration_certificate": "/files/cert.pdf"}))
		for test in ({"sensitivity_setting": "Fe 1.5"}, {"test_remarks": "ok"}):
			self.assertTrue(belongs_to_earlier_layout({"docstatus": 0}, [{}, test]), test)

	def test_a_draft_with_none_of_them_is_finished_the_new_way(self):
		blank = {"docstatus": 0, "calibration_certificate": " ", "metal_detector_id": "MD-1", "detector_make_model": "Loma IQ4"}
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
		with_remarks = {"doctype": "QC Metal Detector Log", "name": "QCH-7", "docstatus": 0, "tests": [{"detected": 1, "test_remarks": "ok"}]}
		blank = {"doctype": "QC Metal Detector Log", "name": "QCH-8", "docstatus": 0, "tests": [{"detected": 1}]}
		submitted = {"doctype": "QC Metal Detector Log", "name": "QCH-9", "docstatus": 2, "tests": []}
		get_all.side_effect = lambda doctype, **kw: {
			"QC Metal Detector Test": [],
			"QC Metal Detector Log": [],
			"Deleted Document": [_record(f"DD-{i}", data=json.dumps(d)) for i, d in enumerate((with_remarks, blank, submitted), 1)],
		}[doctype]

		patch_module.execute()

		self.assertEqual(get_all.call_args.kwargs["filters"], {"deleted_doctype": "QC Metal Detector Log", "restored": 0})
		sql.assert_not_called()
		self.assertEqual([c.args[1] for c in set_value.call_args_list], ["DD-1", "DD-3"])
		self.assertEqual(json.loads(set_value.call_args_list[0].args[3]), {**with_remarks, "earlier_layout": 1})
		self.assertEqual(set_value.call_args_list[0].kwargs, {"update_modified": False})

	def test_before_the_column_exists(self, has_column, get_all, sql, set_value, forget):
		has_column.return_value = False
		patch_module.execute()
		get_all.assert_not_called()
		sql.assert_not_called()
		forget.assert_not_called()


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
			def insert(self, ignore_permissions=False):
				if values["metal_detector_id"] in inserted.refuse:
					raise frappe.NameError("Name cannot contain special characters like < >")
				assert ignore_permissions
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
			"Deleted Document": [frappe._dict(data=json.dumps(d)) for d in deleted],
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
		# made from the log's Metal Detector ID without leaving it
		self.assertEqual(doc.get("quick_entry"), 1)
		for fieldname in ("make_model", "last_calibration_date", "next_calibration_date", "calibration_certificate"):
			self.assertEqual(fields[fieldname].get("allow_in_quick_entry"), 1, fieldname)
		# whoever records a log can pick a detector and read its details
		log_roles = {p["role"] for p in _doctype("QC Metal Detector Log")["permissions"] if p.get("read")}
		self.assertTrue(log_roles <= {p["role"] for p in doc["permissions"] if p.get("read")})

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
		for fieldname in ("metal_detector_id", "tests", "all_tests_passed", "corrective_action", "remarks"):
			self.assertLess(order.index(fieldname), order.index("earlier_layout_section"), fieldname)
		for fieldname in RETIRED_FIELDS:
			self.assertGreater(order.index(fieldname), order.index("earlier_layout_section"), fieldname)
			self.assertEqual(fields[fieldname].get("no_copy"), 1, fieldname)
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

	def test_the_patches_run_in_order(self):
		with open(os.path.join(DOCTYPE_DIR, "..", "..", "patches.txt")) as fh:
			patches = fh.read().split("[post_model_sync]")[1].split()
		# after the model sync makes the Metal Detector and the mark
		self.assertIn("isnack.patches.v1_0.metal_detectors_from_qc_logs", patches)
		self.assertIn("isnack.patches.v1_0.qc_metal_detector_log_earlier_layout", patches)
