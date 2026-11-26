# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""The packaging check without its film and material reconciliation (2026-11),
and the checks made before, which keep them (no database)."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from isnack.isnack.doctype.qc_packaging_check.qc_packaging_check import (
	CHECKS,
	EARLIER_FIELDS,
	QCPackagingCheck,
	belongs_to_earlier_layout,
	checks_result,
)
from isnack.patches.v1_0 import qc_packaging_check_earlier_layout as patch_module
from isnack.patches.v1_0 import qc_packaging_check_overall_status as status_patch


class _Check(frappe._dict):
	"""A packaging check as the controller sees it: a blank number reads None."""

	meta = SimpleNamespace(has_field=lambda fieldname: True)
	validate = QCPackagingCheck.validate
	before_print = QCPackagingCheck.before_print
	keep_earlier_layout = QCPackagingCheck.keep_earlier_layout
	in_earlier_layout = QCPackagingCheck.in_earlier_layout

	def set(self, fieldname, value):
		self[fieldname] = value

	def is_new(self):
		return not self.saved

	def get_doc_before_save(self):
		return self.saved


class _BeforeMigrate(_Check):
	"""Before the migrate adds the mark: the doctype has no earlier_layout."""

	meta = SimpleNamespace(has_field=lambda fieldname: fieldname != "earlier_layout")


def _check(cls=_Check, **values):
	doc = cls(dict.fromkeys(EARLIER_FIELDS), doctype="QC Packaging Check", qty_wasted=None, earlier_layout=0, amended_from=None, saved=None)
	doc.update(values)
	return doc


class TestVariance(unittest.TestCase):
	def test_a_check_made_before_is_reconciled_as_before(self):
		doc = _check(earlier_layout=1, qty_issued=100, qty_used=90, qty_wasted=5, qty_returned=5)
		doc.validate()
		self.assertEqual((doc.variance, doc.variance_acceptable), (0, 1))

		doc = _check(earlier_layout=1, qty_issued=100, qty_used=90, qty_wasted=5, qty_returned=4)
		doc.validate()
		self.assertEqual((doc.variance, doc.variance_acceptable), (1, 0))

		# half a unit either way is acceptable
		doc = _check(earlier_layout=1, qty_issued=100, qty_used=90, qty_wasted=10.5)
		doc.validate()
		self.assertEqual((doc.variance, doc.variance_acceptable), (-0.5, 1))

	def test_one_made_before_with_nothing_reconciled_keeps_its_result(self):
		# submitted before the change: marked, its result as it was
		doc = _check(earlier_layout=1, qty_wasted=0)
		doc.validate()
		self.assertEqual((doc.variance, doc.variance_acceptable), (0, 1))

	def test_a_check_made_since_has_no_variance(self):
		doc = _check(qty_wasted=12, qty_issued=0, qty_used=0, qty_returned=0, film_type="")
		doc.validate()
		self.assertEqual((doc.variance, doc.variance_acceptable, doc.earlier_layout), (0, 0, 0))

	def test_a_form_from_before_the_change_is_told_to_reload(self):
		# a desk form, a Duplicate or a Quality Hub page loaded before the change
		# still offers the film and the reconciliation: a new check would keep
		# them out of sight
		for retired in ({"film_batch": "F-12"}, {"film_type": "PET"}, {"qty_issued": 100.0}, {"qty_returned": 0.5}):
			with self.assertRaisesRegex(frappe.ValidationError, "This page is out of date"):
				_check(qty_wasted=3, **retired).validate()

	def test_a_stray_space_is_nothing_said(self):
		# (an XLSX cell, or a form, holding a space or a line break): none kept out of sight
		doc = _check(qty_wasted=3, film_type=" ", film_batch="\n")
		doc.validate()
		self.assertEqual((doc.film_type, doc.film_batch, doc.variance), (None, None, 0))

	def test_before_the_migrate_every_check_is_one_made_before(self):
		doc = _check(_BeforeMigrate, film_type="PET", qty_issued=100, qty_used=90, qty_wasted=5, qty_returned=4)
		del doc["earlier_layout"]
		doc.validate()
		self.assertEqual((doc.variance, doc.variance_acceptable), (1, 0))
		self.assertNotIn("earlier_layout", doc)


ALL_TICKED = dict.fromkeys(CHECKS, 1)


class TestOverallStatus(unittest.TestCase):
	"""A check made since passes only when its four checks are all ticked (2026-11)."""

	def test_all_four_ticked_is_a_pass(self):
		doc = _check(qty_wasted=3, **ALL_TICKED)
		doc.validate()
		self.assertEqual(doc.overall_status, "Pass")

	def test_any_unticked_is_a_fail(self):
		for unticked in CHECKS:
			doc = _check(qty_wasted=3, **{**ALL_TICKED, unticked: 0})
			doc.validate()
			self.assertEqual(doc.overall_status, "Fail", unticked)
		doc = _check(qty_wasted=3)
		doc.validate()
		self.assertEqual(doc.overall_status, "Fail")

	def test_worked_out_not_entered(self):
		# an import, the API or a form loaded before cannot set it
		doc = _check(qty_wasted=3, overall_status="Pass", **{**ALL_TICKED, "seal_integrity_ok": 0})
		doc.validate()
		self.assertEqual(doc.overall_status, "Fail")
		# ticked again, on a draft saved before
		doc = _check(saved=_check(), qty_wasted=3, overall_status="Fail", **ALL_TICKED)
		doc.validate()
		self.assertEqual(doc.overall_status, "Pass")

	def test_a_check_made_before_keeps_its_variance_result(self):
		doc = _check(earlier_layout=1, overall_status="Pass", qty_issued=100, qty_used=90, qty_wasted=5, qty_returned=4, **ALL_TICKED)
		doc.validate()
		self.assertEqual((doc.overall_status, doc.variance_acceptable), (None, 0))

	def test_a_row_or_a_dict(self):
		self.assertEqual(checks_result(frappe._dict(ALL_TICKED)), "Pass")
		self.assertEqual(checks_result({**ALL_TICKED, "label_correct": None}), "Fail")

	def test_printed_on_a_check_made_since(self):
		doc = _check(qty_wasted=3, overall_status="Pass", **ALL_TICKED)
		doc.before_print()
		self.assertEqual(doc.overall_status, "Pass")


class TestTheMarkStays(unittest.TestCase):
	"""earlier_layout is set by the patch and carried by Amend; a form loaded
	before the migrate does not know it and sends none."""

	def test_a_check_made_before_saved_from_a_form_loaded_before_the_migrate(self):
		doc = _check(saved=_check(earlier_layout=1), earlier_layout=None, film_type="PET", qty_issued=100, qty_used=90, qty_wasted=5, qty_returned=5)
		doc.validate()
		self.assertEqual((doc.earlier_layout, doc.variance, doc.variance_acceptable), (1, 0, 1))

	@patch("frappe.db.get_value", return_value=1)
	def test_an_amendment_made_from_a_form_loaded_before_the_migrate(self, get_value):
		doc = _check(amended_from="QCG-2026-00003", earlier_layout=None, qty_issued=10, qty_used=8, qty_wasted=2)
		doc.validate()
		get_value.assert_called_once_with("QC Packaging Check", "QCG-2026-00003", "earlier_layout")
		self.assertEqual((doc.earlier_layout, doc.variance, doc.variance_acceptable), (1, 0, 1))

	@patch("frappe.db.get_value", return_value=0)
	def test_an_amendment_of_a_check_made_since(self, _get_value):
		doc = _check(amended_from="QCG-2026-00009", qty_wasted=2)
		doc.validate()
		self.assertEqual((doc.earlier_layout, doc.variance), (0, 0))

	def test_a_check_made_since_stays_one(self):
		doc = _check(saved=_check(), qty_wasted=2)
		doc.validate()
		self.assertEqual((doc.earlier_layout, doc.variance), (0, 0))


class TestPrint(unittest.TestCase):
	def test_a_check_made_since_prints_no_earlier_layout(self):
		# saved, its reconciliation reads 0 (a blank number is saved as 0)
		doc = _check(qty_wasted=12, qty_issued=0, qty_used=0, qty_returned=0, variance=0, variance_acceptable=0)
		doc.before_print()
		self.assertEqual([doc[f] for f in EARLIER_FIELDS], [None] * len(EARLIER_FIELDS))
		self.assertEqual(doc.qty_wasted, 12)

	def test_one_made_before_prints_as_it_was(self):
		values = dict(film_type="PET", film_batch="F-12", qty_issued=100, qty_used=90, qty_returned=5, variance=0, variance_acceptable=1)
		doc = _check(earlier_layout=1, qty_wasted=5, **values)
		doc.before_print()
		self.assertEqual({f: doc[f] for f in values}, values)


class TestWhichChecksKeepTheEarlierLayout(unittest.TestCase):
	def test_submitted_and_cancelled_checks_keep_their_result(self):
		for docstatus in (1, 2):
			self.assertTrue(belongs_to_earlier_layout({"docstatus": docstatus}))

	def test_a_draft_keeps_it_when_it_holds_film_or_reconciliation(self):
		for value in ({"film_type": "PET"}, {"film_batch": "F-7"}, {"qty_issued": 10}, {"qty_used": 8}, {"qty_returned": 0.5}):
			self.assertTrue(belongs_to_earlier_layout({"docstatus": 0, **value}), value)

	def test_a_draft_with_none_of_it_is_finished_the_new_way(self):
		blank = {"docstatus": 0, "film_type": " ", "film_batch": None, "qty_issued": 0, "qty_used": 0.0, "qty_returned": None}
		self.assertFalse(belongs_to_earlier_layout(blank))
		self.assertFalse(belongs_to_earlier_layout({"docstatus": 0, "qty_wasted": 12}))


def _row(name, docstatus=0, **values):
	return frappe._dict(name=name, docstatus=docstatus, **values)


@patch("frappe.db.set_value")
@patch("frappe.db.sql")
@patch("frappe.get_all")
@patch("frappe.db.has_column", return_value=True)
class TestPatch(unittest.TestCase):
	def test_the_checks_made_before_are_marked(self, _has, get_all, sql, set_value):
		get_all.side_effect = lambda doctype, **kw: {
			"QC Packaging Check": [
				_row("QCG-1", 1),  # submitted: keeps its result, whatever it holds
				_row("QCG-2", 2),  # cancelled: an amendment carries it on
				_row("QCG-3", film_batch="F-7"),  # a draft holding film
				_row("QCG-4", qty_issued=0, qty_used=0, qty_returned=0, film_type=""),  # a blank draft
			],
			"Deleted Document": [],
		}[doctype]

		patch_module.execute()

		sql.assert_called_once_with(
			"update `tabQC Packaging Check` set earlier_layout = 1 where name in %(names)s",
			{"names": ("QCG-1", "QCG-2", "QCG-3")},
		)
		set_value.assert_not_called()

	def test_a_check_deleted_before_is_restored_as_it_was(self, _has, get_all, sql, set_value):
		cancelled = {"doctype": "QC Packaging Check", "name": "QCG-5", "docstatus": 2, "qty_issued": 10.0}
		blank = {"doctype": "QC Packaging Check", "name": "QCG-6", "docstatus": 0, "qty_issued": 0.0}
		get_all.side_effect = lambda doctype, **kw: {
			"QC Packaging Check": [],
			"Deleted Document": [_row("DD-1", data=json.dumps(cancelled)), _row("DD-2", data=json.dumps(blank))],
		}[doctype]

		patch_module.execute()

		self.assertEqual(
			get_all.call_args.kwargs["filters"], {"deleted_doctype": "QC Packaging Check", "restored": 0}
		)
		sql.assert_not_called()
		set_value.assert_called_once()
		args, kwargs = set_value.call_args
		self.assertEqual(args[:3], ("Deleted Document", "DD-1", "data"))
		self.assertEqual(json.loads(args[3]), {**cancelled, "earlier_layout": 1})
		self.assertEqual(kwargs, {"update_modified": False})

	def test_before_the_column_exists(self, has_column, get_all, sql, set_value):
		has_column.return_value = False
		patch_module.execute()
		get_all.assert_not_called()
		sql.assert_not_called()


@patch("frappe.db.sql")
@patch("frappe.get_all")
@patch("frappe.db.has_column", return_value=True)
class TestOverallStatusPatch(unittest.TestCase):
	def test_the_checks_made_since_are_given_theirs(self, _has, get_all, sql):
		get_all.return_value = [
			_row("QCG-7", 1, **ALL_TICKED),  # submitted: a save cannot reach it
			_row("QCG-8", 0, **{**ALL_TICKED, "artwork_matches": 0}),
			_row("QCG-9", 2),
		]

		status_patch.execute()

		get_all.assert_called_once_with("QC Packaging Check", filters={"earlier_layout": 0}, fields=["name", *CHECKS])
		self.assertEqual(
			[c.args for c in sql.call_args_list],
			[
				("update `tabQC Packaging Check` set overall_status = %(result)s where name in %(names)s", {"result": "Pass", "names": ("QCG-7",)}),
				("update `tabQC Packaging Check` set overall_status = %(result)s where name in %(names)s", {"result": "Fail", "names": ("QCG-8", "QCG-9")}),
			],
		)

	def test_none_to_give(self, _has, get_all, sql):
		get_all.return_value = [_row("QCG-7", 1, **ALL_TICKED)]
		status_patch.execute()
		self.assertEqual(sql.call_count, 1)
		get_all.return_value = []
		sql.reset_mock()
		status_patch.execute()
		sql.assert_not_called()

	def test_before_the_columns_exist(self, has_column, get_all, sql):
		has_column.return_value = False
		status_patch.execute()
		get_all.assert_not_called()
		sql.assert_not_called()
