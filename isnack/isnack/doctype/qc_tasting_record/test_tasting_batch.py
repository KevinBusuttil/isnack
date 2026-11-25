# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""A tasting's Batch No is a finished good's batch (2026-11) (no database)."""

import os
import unittest
from unittest.mock import patch

import frappe

from isnack.isnack.doctype.qc_tasting_record import qc_tasting_record
from isnack.isnack.doctype.qc_tasting_record.qc_tasting_record import (
	finished_good_batches,
	finished_goods,
	require_finished_good_batch,
)

APP_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..")
QUERY = f"{qc_tasting_record.__name__}.{finished_good_batches.__name__}"

# the batches there are, and their items' groups
BATCHES = {"TST-004": "FG10008", "AAA-004": "FG10008", "AV-900": "RM20014"}
ITEMS = {"FG10008": "Finished Goods", "FG10005": "Snacks", "RM20014": "Raw Materials"}


class _Record(frappe._dict):
	"""A QC Tasting Record as its controller sees it: new, or saved with ``saved``'s batch."""

	def __init__(self, saved=None, **fields):
		super().__init__(doctype="QC Tasting Record", name="QCF-2026-00001", **{"amended_from": None, **fields})
		self._saved = saved

	def is_new(self):
		return self._saved is None


def _get_value(records=None):
	records = records or {}

	def get_value(doctype, name, fieldname=None, as_dict=False):
		if doctype == "Batch":
			return BATCHES.get(name)
		if doctype == "Item":
			return ITEMS.get(name)
		if doctype == "Work Order":
			return {"MFG-WO-2026-00090": "FG10008", "MFG-WO-2026-00091": "RM20014"}.get(name)
		return records.get(name)

	return get_value


class TestABatchOfAFinishedGood(unittest.TestCase):
	def _check(self, doc, records=None):
		with patch("frappe.db.get_value", side_effect=_get_value(records)), patch.object(
			qc_tasting_record, "finished_goods", return_value=["FG10008", "FG10005"]
		):
			require_finished_good_batch(doc)

	def test_a_finished_goods_batch_is_taken(self):
		self._check(_Record(batch_no="TST-004"))

	def test_another_items_batch_is_refused(self):
		with self.assertRaisesRegex(
			frappe.ValidationError, r"Batch .*AV-900.* is of .*RM20014.* \(Raw Materials\), not of a finished good: pick the batch of the product tasted"
		):
			self._check(_Record(batch_no="AV-900"))
		# picked instead of the record's own
		with self.assertRaisesRegex(frappe.ValidationError, "not of a finished good"):
			self._check(_Record(saved="TST-004", batch_no="AV-900"), records={"QCF-2026-00001": "TST-004"})

	def test_a_record_keeps_the_batch_it_has(self):
		# saved before the rule, or an amendment of one
		self._check(_Record(saved="AV-900", batch_no="AV-900"), records={"QCF-2026-00001": "AV-900"})
		self._check(_Record(amended_from="QCF-2026-00000", batch_no=" av-900"), records={"QCF-2026-00000": "AV-900"})
		with self.assertRaises(frappe.ValidationError):
			self._check(_Record(amended_from="QCF-2026-00000", batch_no="AV-900"), records={"QCF-2026-00000": "TST-004"})

	def test_nothing_to_check(self):
		# no batch (mandatory, refused for it), or one there is not (Frappe's link check)
		self._check(_Record(batch_no=" "))
		self._check(_Record(batch_no="NO-SUCH"))


class TestTheFinishedGoods(unittest.TestCase):
	def test_the_group_and_those_under_it(self):
		def get_all(doctype, filters=None, pluck=None):
			if doctype == "Item Group":
				self.assertEqual(filters, {"lft": [">=", 8], "rgt": ["<=", 13]})
				return ["Finished Goods", "Snacks"]
			self.assertEqual((doctype, filters), ("Item", {"item_group": ["in", ["Finished Goods", "Snacks"]]}))
			return ["FG10008", "FG10005"]

		with patch("frappe.db.get_value", return_value=frappe._dict(lft=8, rgt=13)), patch("frappe.get_all", side_effect=get_all):
			self.assertEqual(finished_goods(), ["FG10008", "FG10005"])
		with patch("frappe.db.get_value", return_value=None):
			self.assertEqual(finished_goods(), [])


class TestTheSearch(unittest.TestCase):
	def _search(self, filters=None, txt="", may=True):
		with patch("frappe.db.exists", return_value=True), patch("frappe.has_permission", return_value=may), patch(
			"frappe.db.get_value", side_effect=_get_value()
		), patch.object(qc_tasting_record, "finished_goods", return_value=["FG10008", "FG10005"]), patch(
			"frappe.get_all", return_value=[("TST-004", "FG10008", "2026-11-18")]
		) as get_all:
			found = finished_good_batches("Batch", txt, "name", 0, 20, filters or {})
		return found, get_all

	def test_the_batches_of_finished_goods_newest_first(self):
		found, get_all = self._search(txt="tst")
		self.assertEqual(found, [("TST-004", "FG10008", "2026-11-18")])
		get_all.assert_called_once_with(
			"Batch",
			filters={"item": ["in", ["FG10008", "FG10005"]], "disabled": 0},
			or_filters={"name": ["like", "%tst%"], "item": ["like", "%tst%"]},
			fields=["name", "item", "manufacturing_date"],
			order_by="manufacturing_date desc, creation desc",
			limit_start=0,
			limit_page_length=20,
			as_list=True,
		)

	def test_the_item_the_work_order_makes(self):
		_found, get_all = self._search({"work_order": "MFG-WO-2026-00090"})
		self.assertEqual(get_all.call_args.kwargs["filters"]["item"], ["in", ["FG10008"]])
		# a Work Order making no finished good: every finished good
		_found, get_all = self._search('{"work_order": "MFG-WO-2026-00091"}')
		self.assertEqual(get_all.call_args.kwargs["filters"]["item"], ["in", ["FG10008", "FG10005"]])

	def test_none_for_who_records_no_tasting(self):
		found, get_all = self._search(may=False)
		self.assertEqual(found, [])
		get_all.assert_not_called()

	def test_the_form_and_the_quality_hub_use_it(self):
		self.assertIn(finished_good_batches, frappe.whitelisted)
		for path in (
			os.path.join(APP_DIR, "isnack", "doctype", "qc_tasting_record", "qc_tasting_record.js"),
			os.path.join(APP_DIR, "isnack", "page", "quality_hub", "quality_hub.js"),
		):
			with open(path) as fh:
				script = fh.read()
			self.assertIn(f'query: "{QUERY}"', script, path)
			self.assertIn("work_order", script[script.index(QUERY) :][:200], path)
