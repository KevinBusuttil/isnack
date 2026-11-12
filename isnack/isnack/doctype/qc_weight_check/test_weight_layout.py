# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""The weight check judged sample by sample (2026-11), and the checks made
before, which keep their TU limits, tare, Overall Status and Remarks (no
database)."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from isnack.isnack.doctype.qc_weight_check.qc_weight_check import (
	EARLIER_FIELDS,
	EARLIER_SAMPLE_FIELDS,
	QCWeightCheck,
	belongs_to_earlier_layout,
	sample_result,
)
from isnack.patches.v1_0 import qc_weight_check_earlier_layout as patch_module
from isnack.utils import earlier_layout


class _Row(frappe._dict):
	def set(self, fieldname, value):
		self[fieldname] = value


class _Check(_Row):
	"""A weight check as the controller sees it: a blank number reads None."""

	meta = SimpleNamespace(has_field=lambda fieldname: True)
	validate = QCWeightCheck.validate
	before_print = QCWeightCheck.before_print
	refuse_retired_values = QCWeightCheck.refuse_retired_values
	require_sample_status = QCWeightCheck.require_sample_status

	def is_new(self):
		return not self.saved

	def get_doc_before_save(self):
		return self.saved


class _BeforeMigrate(_Check):
	meta = SimpleNamespace(has_field=lambda fieldname: fieldname != "earlier_layout")


def _sample(gross=None, status=None, tare=None, **other):
	return _Row({"remarks": None, **other}, gross_weight=gross, status=status, tare_weight=tare)


def _check(*samples, cls=_Check, **values):
	doc = cls(dict.fromkeys(EARLIER_FIELDS), doctype="QC Weight Check", samples=list(samples), earlier_layout=0, amended_from=None, saved=None)
	doc.update(values)
	return doc


class TestJudgedSampleBySample(unittest.TestCase):
	def test_the_result_is_a_fail_when_any_sample_failed(self):
		doc = _check(_sample(101, "Pass"), _sample(97, "Fail", remarks="seal open"), _sample(103, "Pass"))
		doc.validate()
		self.assertEqual(doc.overall_status, "Fail")

		doc = _check(_sample(101, "Pass"), _sample(103, "Pass"))
		doc.validate()
		self.assertEqual(doc.overall_status, "Pass")

	def test_no_samples_no_result(self):
		doc = _check()
		doc.validate()
		self.assertEqual((doc.overall_status, doc.sample_count), ("", 0))
		self.assertEqual(sample_result([_sample(100, "Pass"), _sample(99, None)]), "")

	def test_the_figures_are_of_the_gross_weights(self):
		doc = _check(_sample(100, "Pass"), _sample(104, "Pass"), _sample(96, "Fail"))
		doc.validate()
		self.assertEqual([s.net_weight for s in doc.samples], [100, 104, 96])
		self.assertEqual((doc.sample_count, doc.average_weight, doc.min_weight, doc.max_weight), (3, 100, 96, 104))
		self.assertAlmostEqual(doc.std_deviation, (32 / 3) ** 0.5)
		# no TU limits: nothing counted against them, no sample "in range"
		self.assertEqual((doc.tu1_failures, doc.tu2_failures), (0, 0))
		self.assertEqual([s.in_range for s in doc.samples], [0, 0, 0])

	def test_a_form_from_before_the_change_is_told_to_reload(self):
		# a desk form, a Duplicate or a Quality Hub page loaded before the change
		# still offers the TU limits, the record's Remarks and the tare
		for values in ({"tu1_limit": 95}, {"tu2_limit": 91}, {"remarks": "all fine"}):
			with self.assertRaisesRegex(frappe.ValidationError, "This page is out of date"):
				_check(_sample(100, "Pass"), **values).validate()
		with self.assertRaisesRegex(frappe.ValidationError, "This page is out of date"):
			_check(_sample(100, "Pass", tare=2)).validate()

	def test_each_sample_needs_a_status(self):
		doc = _check(_sample(100, "Pass", idx=1), _sample(99, None, idx=2), _sample(98, "", idx=3))
		with self.assertRaisesRegex(frappe.ValidationError, r"Status is required in Samples \(row 2, 3\)"):
			doc.validate()

	def test_an_entered_overall_status_gives_way_to_the_samples(self):
		# a page from before the change sends the Overall Status it offered
		doc = _check(_sample(100, "Fail"), overall_status="Pass")
		doc.validate()
		self.assertEqual(doc.overall_status, "Fail")


class TestTheChecksMadeBefore(unittest.TestCase):
	def test_reckoned_as_before(self):
		doc = _check(
			_sample(102, tare=2), _sample(96, tare=2), _sample(92, tare=2),
			earlier_layout=1, tu1_limit=95, tu2_limit=91, overall_status="Marginal", remarks="one light pack",
		)
		doc.validate()
		self.assertEqual([s.net_weight for s in doc.samples], [100, 94, 90])
		self.assertEqual([s.in_range for s in doc.samples], [1, 1, 0])
		self.assertEqual((doc.tu1_failures, doc.tu2_failures), (2, 1))
		self.assertEqual((doc.average_weight, doc.min_weight, doc.max_weight), (94.66666666666667, 90, 100))
		# the Overall Status entered stands
		self.assertEqual((doc.overall_status, doc.remarks), ("Marginal", "one light pack"))

	def test_its_samples_need_no_status(self):
		# a draft finished now, an amendment or a restore keeps the Overall Status it was given
		doc = _check(_sample(100, tare=2), _sample(99, "Fail"), earlier_layout=1, overall_status="Pass")
		doc.validate()
		self.assertEqual(doc.overall_status, "Pass")

	def test_saved_from_a_form_loaded_before_the_migrate(self):
		doc = _check(_sample(100, tare=2), saved=_check(earlier_layout=1), earlier_layout=None, tu2_limit=99, overall_status="Pass")
		doc.validate()
		self.assertEqual((doc.earlier_layout, doc.tu2_failures, doc.overall_status), (1, 1, "Pass"))

	@patch("frappe.db.get_value", return_value=1)
	def test_an_amendment_made_from_a_form_loaded_before_the_migrate(self, get_value):
		doc = _check(_sample(100, "Pass", tare=2), amended_from="QCI-2026-00003", earlier_layout=None, overall_status="Pass")
		doc.validate()
		get_value.assert_called_once_with("QC Weight Check", "QCI-2026-00003", "earlier_layout")
		self.assertEqual((doc.earlier_layout, doc.overall_status, doc.samples[0].net_weight), (1, "Pass", 98))

	def test_before_the_migrate_every_check_is_one_made_before(self):
		doc = _check(_sample(100, tare=2), cls=_BeforeMigrate, tu1_limit=99, overall_status="Pass", remarks="ok")
		del doc["earlier_layout"]
		doc.validate()
		self.assertEqual((doc.tu1_failures, doc.overall_status, doc.samples[0].in_range), (1, "Pass", 1))
		self.assertNotIn("earlier_layout", doc)


class TestPrint(unittest.TestCase):
	def test_a_check_made_since_prints_no_earlier_layout(self):
		# saved, its numbers read 0 (a blank number is saved as 0), its result worked out
		doc = _check(_sample(100, "Pass", tare=0, net_weight=100, in_range=0), tu1_limit=0, tu2_limit=0, tu1_failures=0, tu2_failures=0, overall_status="Pass")
		doc.before_print()
		self.assertEqual([doc[f] for f in EARLIER_FIELDS], [None] * len(EARLIER_FIELDS))
		self.assertEqual([doc.samples[0][f] for f in EARLIER_SAMPLE_FIELDS], [None] * len(EARLIER_SAMPLE_FIELDS))
		self.assertEqual((doc.samples[0].gross_weight, doc.samples[0].status), (100, "Pass"))

	def test_one_made_before_prints_as_it_was(self):
		values = dict(tu1_limit=95, tu2_limit=91, tu1_failures=1, tu2_failures=0, overall_status="Pass", remarks="ok")
		doc = _check(_sample(96, tare=2, net_weight=94, in_range=1), earlier_layout=1, **values)
		doc.before_print()
		self.assertEqual({f: doc[f] for f in values}, values)
		self.assertEqual((doc.samples[0].tare_weight, doc.samples[0].net_weight, doc.samples[0].in_range), (2, 94, 1))


class TestWhichChecksKeepTheEarlierLayout(unittest.TestCase):
	def test_submitted_and_cancelled_checks_keep_their_result(self):
		for docstatus in (1, 2):
			self.assertTrue(belongs_to_earlier_layout({"docstatus": docstatus}))

	def test_a_draft_keeps_it_when_it_holds_any_of_it(self):
		for value in ({"tu1_limit": 95}, {"tu2_limit": 91}, {"overall_status": "Pass"}, {"remarks": "light"}):
			self.assertTrue(belongs_to_earlier_layout({"docstatus": 0, **value}), value)
		self.assertTrue(belongs_to_earlier_layout({"docstatus": 0}, [{"tare_weight": 0}, {"tare_weight": 2.5}]))

	def test_a_draft_with_none_of_it_is_finished_the_new_way(self):
		blank = {"docstatus": 0, "tu1_limit": 0, "tu2_limit": 0.0, "overall_status": "", "remarks": " ", "nominal_weight": 100}
		self.assertFalse(belongs_to_earlier_layout(blank, [{"tare_weight": 0, "gross_weight": 101}]))


def _row(name, docstatus=0, **values):
	return frappe._dict(name=name, docstatus=docstatus, **values)


@patch("frappe.db.set_value")
@patch("frappe.db.sql")
@patch("frappe.get_all")
@patch("frappe.db.has_column", return_value=True)
class TestPatch(unittest.TestCase):
	def test_the_checks_made_before_are_marked(self, _has, get_all, sql, set_value):
		get_all.side_effect = lambda doctype, **kw: {
			"QC Weight Sample": [frappe._dict(parent="QCI-6", tare_weight=2.0)],
			"QC Weight Check": [
				_row("QCI-1", 1),  # submitted: keeps its result, whatever it holds
				_row("QCI-2", 2),  # cancelled: an amendment carries it on
				_row("QCI-3", tu2_limit=91),  # a draft holding a limit
				_row("QCI-4", overall_status="Fail"),  # a draft judged overall
				_row("QCI-5", tu1_limit=0, tu2_limit=0, overall_status="", remarks=None),  # a blank draft
				_row("QCI-6"),  # a draft whose sample has a tare
			],
			"Deleted Document": [],
		}[doctype]

		patch_module.execute()

		self.assertEqual(
			get_all.call_args_list[0].kwargs["filters"], {"parenttype": "QC Weight Check", "tare_weight": ["!=", 0]}
		)
		sql.assert_called_once_with(
			"update `tabQC Weight Check` set earlier_layout = 1 where name in %(names)s",
			{"names": ("QCI-1", "QCI-2", "QCI-3", "QCI-4", "QCI-6")},
		)
		set_value.assert_not_called()

	def test_a_check_deleted_before_is_restored_as_it_was(self, _has, get_all, sql, set_value):
		with_tare = {"doctype": "QC Weight Check", "name": "QCI-7", "docstatus": 0, "samples": [{"gross_weight": 100, "tare_weight": 2}]}
		blank = {"doctype": "QC Weight Check", "name": "QCI-8", "docstatus": 0, "samples": [{"gross_weight": 100, "tare_weight": 0}]}
		get_all.side_effect = lambda doctype, **kw: {
			"QC Weight Sample": [],
			"QC Weight Check": [],
			"Deleted Document": [_row("DD-1", data=json.dumps(with_tare)), _row("DD-2", data=json.dumps(blank))],
		}[doctype]

		patch_module.execute()

		self.assertEqual(get_all.call_args.kwargs["filters"], {"deleted_doctype": "QC Weight Check", "restored": 0})
		sql.assert_not_called()
		set_value.assert_called_once()
		args, kwargs = set_value.call_args
		self.assertEqual(args[:3], ("Deleted Document", "DD-1", "data"))
		self.assertEqual(json.loads(args[3]), {**with_tare, "earlier_layout": 1})
		self.assertEqual(kwargs, {"update_modified": False})

	def test_before_the_column_exists(self, has_column, get_all, sql, set_value):
		has_column.return_value = False
		patch_module.execute()
		get_all.assert_not_called()
		sql.assert_not_called()


class TestMarkRecords(unittest.TestCase):
	@patch("frappe.db.sql")
	def test_nothing_to_mark(self, sql):
		earlier_layout.mark_records("QC Weight Check", [])
		sql.assert_not_called()
