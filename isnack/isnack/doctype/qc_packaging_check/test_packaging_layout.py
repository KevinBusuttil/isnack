# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""The packaging check without its film and material reconciliation (2026-11),
and the checks made before, which keep them (no database)."""

import unittest
from unittest.mock import patch

import frappe
from isnack.isnack.doctype.qc_packaging_check.qc_packaging_check import EARLIER_FIELDS, QCPackagingCheck
from isnack.patches.v1_0 import qc_packaging_check_earlier_layout as patch_module


def _check(**values):
	"""A packaging check as the controller sees it: a blank number reads None."""
	doc = frappe._dict(dict.fromkeys(EARLIER_FIELDS), qty_wasted=None, earlier_layout=0)
	doc.update(values)
	doc.set = doc.__setitem__
	return doc


class TestVariance(unittest.TestCase):
	def test_a_check_made_before_is_reconciled_as_before(self):
		doc = _check(earlier_layout=1, qty_issued=100, qty_used=90, qty_wasted=5, qty_returned=5)
		QCPackagingCheck.validate(doc)
		self.assertEqual((doc.variance, doc.variance_acceptable), (0, 1))

		doc = _check(earlier_layout=1, qty_issued=100, qty_used=90, qty_wasted=5, qty_returned=4)
		QCPackagingCheck.validate(doc)
		self.assertEqual((doc.variance, doc.variance_acceptable), (1, 0))

		# half a unit either way is acceptable
		doc = _check(earlier_layout=1, qty_issued=100, qty_used=90, qty_wasted=10.5)
		QCPackagingCheck.validate(doc)
		self.assertEqual((doc.variance, doc.variance_acceptable), (-0.5, 1))

	def test_one_made_before_with_nothing_reconciled_keeps_its_result(self):
		doc = _check(earlier_layout=1)
		QCPackagingCheck.validate(doc)
		self.assertEqual((doc.variance, doc.variance_acceptable), (0, 1))

	def test_a_check_made_since_has_no_variance(self):
		doc = _check(qty_wasted=12)
		QCPackagingCheck.validate(doc)
		self.assertEqual((doc.variance, doc.variance_acceptable), (0, 0))


class TestPrint(unittest.TestCase):
	def test_a_check_made_since_prints_no_earlier_layout(self):
		# saved, its reconciliation reads 0 (a blank number is saved as 0)
		doc = _check(qty_wasted=12, qty_issued=0, qty_used=0, qty_returned=0, variance=0, variance_acceptable=0)
		QCPackagingCheck.before_print(doc)
		self.assertEqual([doc[f] for f in EARLIER_FIELDS], [None] * len(EARLIER_FIELDS))
		self.assertEqual(doc.qty_wasted, 12)

	def test_one_made_before_prints_as_it_was(self):
		values = dict(film_type="PET", film_batch="F-12", qty_issued=100, qty_used=90, qty_returned=5, variance=0, variance_acceptable=1)
		doc = _check(earlier_layout=1, qty_wasted=5, **values)
		QCPackagingCheck.before_print(doc)
		self.assertEqual({f: doc[f] for f in values}, values)


@patch("frappe.db.sql")
@patch("frappe.db.has_column", return_value=True)
class TestPatch(unittest.TestCase):
	def test_every_check_made_before_is_marked(self, _has, sql):
		patch_module.execute()
		sql.assert_called_once_with("update `tabQC Packaging Check` set earlier_layout = 1")

	def test_before_the_column_exists(self, has_column, sql):
		has_column.return_value = False
		patch_module.execute()
		sql.assert_not_called()
