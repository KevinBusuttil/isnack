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
BATCHES = {"FGB-0101": "FG-0001", "FGB-0102": "FG-0001", "RMB-0201": "RM-0001"}
ITEMS = {"FG-0001": "Finished Goods", "FG-0002": "Snacks", "RM-0001": "Raw Materials"}


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
			return {"MFG-WO-2026-00090": "FG-0001", "MFG-WO-2026-00091": "RM-0001", "MFG-WO-2026-00092": "FG-0002"}.get(name)
		row = records.get(name)
		return frappe._dict(row) if row else None

	return get_value


class TestABatchOfAFinishedGood(unittest.TestCase):
	def _check(self, doc, records=None):
		with patch("frappe.db.get_value", side_effect=_get_value(records)), patch.object(
			qc_tasting_record, "finished_goods", return_value=["FG-0001", "FG-0002"]
		):
			require_finished_good_batch(doc)

	def test_a_finished_goods_batch_is_taken(self):
		self._check(_Record(batch_no="FGB-0101"))

	def test_another_items_batch_is_refused(self):
		with self.assertRaisesRegex(
			frappe.ValidationError, r"Batch .*RMB-0201.* is of .*RM-0001.* \(Raw Materials\), not of a finished good: pick the batch of the product tasted"
		):
			self._check(_Record(batch_no="RMB-0201"))
		# picked instead of the record's own
		with self.assertRaisesRegex(frappe.ValidationError, "not of a finished good"):
			self._check(_Record(saved="FGB-0101", batch_no="RMB-0201"), records={"QCF-2026-00001": {"batch_no": "FGB-0101"}})

	def test_a_record_keeps_the_batch_it_has(self):
		# saved before the rule, or an amendment of one
		self._check(_Record(saved="RMB-0201", batch_no="RMB-0201"), records={"QCF-2026-00001": {"batch_no": "RMB-0201"}})
		self._check(_Record(amended_from="QCF-2026-00000", batch_no=" rmb-0201"), records={"QCF-2026-00000": {"batch_no": "RMB-0201"}})
		with self.assertRaises(frappe.ValidationError):
			self._check(_Record(amended_from="QCF-2026-00000", batch_no="RMB-0201"), records={"QCF-2026-00000": {"batch_no": "FGB-0101"}})

	def test_a_batch_there_is_not_is_refused(self):
		# Frappe does not check a Link that fields are fetched from (Item Code)
		with self.assertRaisesRegex(frappe.LinkValidationError, r"Could not find Batch .*NO-SUCH"):
			self._check(_Record(batch_no="NO-SUCH"))
		# the value as given: a stray space names no batch
		with self.assertRaisesRegex(frappe.LinkValidationError, "Could not find Batch"):
			self._check(_Record(batch_no=" FGB-0101"))
		# no batch at all: mandatory, refused for it later
		self._check(_Record(batch_no=" "))

	def test_the_batch_of_the_item_the_work_order_makes(self):
		self._check(_Record(batch_no="FGB-0101", work_order="MFG-WO-2026-00090"))
		with self.assertRaisesRegex(
			frappe.ValidationError, r"Batch .*FGB-0101.* is of .*FG-0001.*, but Work Order .*MFG-WO-2026-00092.* makes .*FG-0002"
		):
			self._check(_Record(batch_no="FGB-0101", work_order="MFG-WO-2026-00092"))
		# a Work Order making no finished good: the batch is only a finished good's
		self._check(_Record(batch_no="FGB-0101", work_order="MFG-WO-2026-00091"))
		# kept with its Work Order; kept but the Work Order changed to another product's
		saved = {"QCF-2026-00001": {"batch_no": "FGB-0101", "work_order": "MFG-WO-2026-00092"}}
		self._check(_Record(saved=True, batch_no="FGB-0101", work_order="MFG-WO-2026-00092"), records=saved)
		with self.assertRaisesRegex(frappe.ValidationError, "but Work Order"):
			saved = {"QCF-2026-00001": {"batch_no": "FGB-0101", "work_order": "MFG-WO-2026-00090"}}
			self._check(_Record(saved=True, batch_no="FGB-0101", work_order="MFG-WO-2026-00092"), records=saved)


class TestTheFinishedGoods(unittest.TestCase):
	def test_the_group_and_those_under_it(self):
		def get_all(doctype, filters=None, pluck=None):
			if doctype == "Item Group":
				self.assertEqual(filters, {"lft": [">=", 8], "rgt": ["<=", 13]})
				return ["Finished Goods", "Snacks"]
			self.assertEqual((doctype, filters), ("Item", {"item_group": ["in", ["Finished Goods", "Snacks"]]}))
			return ["FG-0001", "FG-0002"]

		with patch("frappe.db.get_value", return_value=frappe._dict(lft=8, rgt=13)), patch("frappe.get_all", side_effect=get_all):
			self.assertEqual(finished_goods(), ["FG-0001", "FG-0002"])
		with patch("frappe.db.get_value", return_value=None):
			self.assertEqual(finished_goods(), [])


class TestTheSearch(unittest.TestCase):
	def _search(self, filters=None, txt="", may=True):
		with patch("frappe.db.exists", return_value=True), patch("frappe.has_permission", return_value=may), patch(
			"frappe.db.get_value", side_effect=_get_value()
		), patch.object(qc_tasting_record, "finished_goods", return_value=["FG-0001", "FG-0002"]), patch(
			"frappe.get_all", return_value=[("FGB-0101", "FG-0001", "2026-11-18")]
		) as get_all:
			found = finished_good_batches("Batch", txt, "name", 0, 20, filters or {})
		return found, get_all

	def test_the_batches_of_finished_goods_newest_first(self):
		found, get_all = self._search(txt="tst")
		self.assertEqual(found, [("FGB-0101", "FG-0001", "2026-11-18")])
		get_all.assert_called_once_with(
			"Batch",
			filters={"item": ["in", ["FG-0001", "FG-0002"]], "disabled": 0},
			or_filters={"name": ["like", "%tst%"], "item": ["like", "%tst%"], "item_name": ["like", "%tst%"]},
			fields=["name", "item", "item_name", "manufacturing_date"],
			order_by="manufacturing_date desc, creation desc",
			limit_start=0,
			limit_page_length=20,
			as_list=True,
		)

	def test_the_item_the_work_order_makes(self):
		_found, get_all = self._search({"work_order": "MFG-WO-2026-00090"})
		self.assertEqual(get_all.call_args.kwargs["filters"]["item"], ["in", ["FG-0001"]])
		# a Work Order making no finished good: every finished good
		_found, get_all = self._search('{"work_order": "MFG-WO-2026-00091"}')
		self.assertEqual(get_all.call_args.kwargs["filters"]["item"], ["in", ["FG-0001", "FG-0002"]])

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
			# a batch of another product is taken off when the Work Order changes
			self.assertIn("which Work Order {3} makes: pick a batch of it.", script, path)
			self.assertIn("Batches of finished goods", script, path)
