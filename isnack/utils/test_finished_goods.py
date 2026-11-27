# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""The finished goods: the Finished Goods item group and those under it (no database)."""

import unittest
from unittest.mock import patch

import frappe
from isnack.utils.finished_goods import FINISHED_GOODS, finished_good_groups, finished_goods


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
			# the Batch Explorer's and the Quality Explorer's Batch pickers offer these groups' batches
			self.assertEqual(finished_good_groups(), ["Finished Goods", "Snacks"])
		with patch("frappe.db.get_value", return_value=None), patch("frappe.get_all") as get_all_:
			self.assertEqual(finished_goods(), [])
			self.assertEqual(finished_good_groups(), [])
			get_all_.assert_not_called()

	def test_the_group_looked_up(self):
		with patch("frappe.db.get_value", return_value=None) as get_value:
			finished_good_groups()
		get_value.assert_called_once_with("Item Group", FINISHED_GOODS, ["lft", "rgt"], as_dict=True)
		self.assertEqual(FINISHED_GOODS, "Finished Goods")
