# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""Unit tests for the Batch Explorer production-inputs level (pure mocks)."""

import unittest
from unittest.mock import patch

import frappe
from isnack.isnack.page.batch_explorer import batch_explorer as be
from isnack.utils import batch_lineage as bl

BATCH = frappe._dict(name="AAO-007", item="FG10005", stock_uom="Carton")


def _entry(name, purpose, docstatus=1, **kw):
	d = frappe._dict(
		name=name,
		purpose=purpose,
		stock_entry_type=purpose,
		docstatus=docstatus,
		posting_date="2026-08-21",
		link=bl.LINK_WORK_ORDER,
		originating_work_orders=[],
	)
	d.update(kw)
	return d


def _row(item_code, **kw):
	d = frappe._dict(
		item_code=item_code,
		item_name=item_code.lower(),
		qty=kw.pop("qty", 10),
		uom="Kg",
		stock_uom="Kg",
		s_warehouse=None,
		t_warehouse=None,
		batch_no=None,
		serial_and_batch_bundle=None,
		is_finished_item=0,
		is_scrap_item=0,
	)
	d.update(kw)
	d.transfer_qty = d.qty
	return d


def _plain_nodes(doctype, names_qty):
	"""Stand-in for _build_nodes: one bare node per name, in name order."""
	return [
		{
			"doctype": doctype,
			"name": n,
			"qty": None,
			"direction": None,
			"date": (names_qty[n] or {}).get("date"),
			"owner": "u@x",
			"owner_name": "U",
			"docstatus": 1,
			"status": "Submitted",
			"party": None,
			"extra": None,
		}
		for n in sorted(names_qty)
	]


class TestBatchRoles(unittest.TestCase):
	@patch("frappe.get_all")
	@patch("frappe.db.sql")
	def test_roles_from_rows_and_legacy_fallback(self, sql, get_all):
		se_info = {
			"SE-M": frappe._dict(name="SE-M", work_order="WO-PROD", purpose="Manufacture"),
			"SE-C": frappe._dict(name="SE-C", work_order="WO-CONS", purpose="Material Consumption for Manufacture"),
			"SE-T": frappe._dict(name="SE-T", work_order="WO-HAND", purpose="Material Transfer"),
			"SE-L": frappe._dict(name="SE-L", work_order="WO-LEGACY", purpose="Manufacture"),
			"SE-X": frappe._dict(name="SE-X", work_order=None, purpose="Material Transfer"),
		}
		sql.return_value = [
			frappe._dict(parent="SE-M", is_finished_item=1, is_scrap_item=0, s_warehouse=None),
			frappe._dict(parent="SE-M", is_finished_item=0, is_scrap_item=1, s_warehouse=None),
			frappe._dict(parent="SE-C", is_finished_item=0, is_scrap_item=0, s_warehouse="WIP"),
			# a transfer into WIP has a source warehouse too, but is not consumption
			frappe._dict(parent="SE-T", is_finished_item=0, is_scrap_item=0, s_warehouse="Staging"),
		]
		get_all.return_value = [frappe._dict(name="WO-LEGACY")]

		roles = be._batch_roles("AAO-007", "FG10005", se_info)

		self.assertEqual(
			roles,
			{
				"WO-PROD": be.ROLE_PRODUCER,
				"WO-CONS": be.ROLE_CONSUMER,
				"WO-HAND": be.ROLE_HANDLER,
				"WO-LEGACY": be.ROLE_PRODUCER,
			},
		)
		params = sql.call_args.args[1]
		self.assertEqual(set(params["parents"]), {"SE-M", "SE-C", "SE-T", "SE-L"})
		self.assertEqual(params["b"], "AAO-007")
		self.assertEqual(get_all.call_args.args[0], "Work Order")
		self.assertEqual(get_all.call_args.kwargs["filters"]["production_item"], "FG10005")

	@patch("frappe.get_all", return_value=[])
	@patch("frappe.db.sql")
	def test_transfer_and_return_never_make_a_consumer(self, sql, _get_all):
		se_info = {
			"SE-MTFM": frappe._dict(name="SE-MTFM", work_order="WO-A", purpose="Material Transfer for Manufacture"),
			"SE-RET": frappe._dict(name="SE-RET", work_order="WO-B", purpose="Material Transfer"),
			"SE-C": frappe._dict(name="SE-C", work_order="WO-C", purpose="Material Consumption for Manufacture"),
		}
		sql.return_value = [
			frappe._dict(parent="SE-MTFM", is_finished_item=0, is_scrap_item=0, s_warehouse="Staging"),
			frappe._dict(parent="SE-RET", is_finished_item=0, is_scrap_item=0, s_warehouse="WIP"),
			frappe._dict(parent="SE-C", is_finished_item=0, is_scrap_item=0, s_warehouse="WIP"),
		]
		roles = be._batch_roles("RB1", "RM1", se_info)
		self.assertEqual(
			roles, {"WO-A": be.ROLE_HANDLER, "WO-B": be.ROLE_HANDLER, "WO-C": be.ROLE_CONSUMER}
		)

	@patch("frappe.db.sql")
	def test_no_linked_entries(self, sql):
		self.assertEqual(be._batch_roles("AAO-007", "FG10005", {"SE-X": frappe._dict(work_order=None)}), {})
		sql.assert_not_called()


class TestAttachProductionInputs(unittest.TestCase):
	def _groups(self):
		return [
			{"doctype": "Stock Entry", "nodes": [{"name": "SE-M"}], "count": 1, "total_qty": 193.0},
			{
				"doctype": "Work Order",
				"nodes": [{"name": "WO-A"}, {"name": "WO-B"}, {"name": "WO-C"}, {"name": "WO-D"}],
				"count": 4,
				"total_qty": None,
			},
		]

	@patch.object(be, "_batch_roles")
	@patch("frappe.has_permission", return_value=False)
	def test_without_stock_entry_permission_nothing_is_attached(self, has_permission, roles):
		groups = self._groups()
		be._attach_production_inputs(groups, BATCH, {})
		roles.assert_not_called()
		self.assertEqual(groups[1]["nodes"], [{"name": "WO-A"}, {"name": "WO-B"}, {"name": "WO-C"}, {"name": "WO-D"}])
		has_permission.assert_called_with("Stock Entry", "read")

	@patch.object(be, "MAX_EAGER_INPUT_WOS", 1)
	@patch.object(be, "_work_order_outputs", return_value={"children": ["produced"]})
	@patch.object(be, "_work_order_inputs", return_value={"children": ["inputs"], "tags": [], "lineage": {}})
	@patch.object(be, "_batch_roles")
	@patch("frappe.has_permission", return_value=True)
	def test_roles_drive_children_and_deferral(self, _perm, roles, inputs, outputs):
		roles.return_value = {
			"WO-A": be.ROLE_PRODUCER,
			"WO-B": be.ROLE_CONSUMER,
			"WO-C": be.ROLE_HANDLER,
			"WO-D": be.ROLE_PRODUCER,
		}
		groups = self._groups()
		be._attach_production_inputs(groups, BATCH, {"SE-M": frappe._dict(work_order="WO-A")})

		a, b, c, d = groups[1]["nodes"]
		self.assertEqual(a["children"], ["inputs"])
		self.assertEqual(a["role"], be.ROLE_PRODUCER)
		self.assertEqual(b["children"], ["produced"])
		self.assertEqual(b["role"], be.ROLE_CONSUMER)
		self.assertNotIn("children", c)
		self.assertNotIn("role", c)
		# second producer is beyond the eager cap
		self.assertTrue(d["inputs_deferred"])
		self.assertNotIn("children", d)
		inputs.assert_called_once_with("WO-A", BATCH)
		outputs.assert_called_once_with("WO-B", BATCH)
		# top-level totals are untouched
		self.assertEqual(groups[0]["total_qty"], 193.0)
		self.assertEqual(groups[1]["count"], 4)


class TestWorkOrderInputs(unittest.TestCase):
	"""Synthetic AAO-007: one Work Order, the full MES entry chain, one hidden and
	one cancelled entry."""

	def setUp(self):
		self.entries = [
			_entry("SE-STG", "Material Transfer", remarks="Staging transfer for WO: WO-A", posting_date="2026-08-20"),
			_entry("SE-SUR", "Material Transfer", link=bl.LINK_SURPLUS_STAGED, originating_work_orders=["WO-A", "WO-B"], posting_date="2026-08-20"),
			_entry("SE-MTFM", "Material Transfer for Manufacture"),
			_entry("SE-MCFM", "Material Consumption for Manufacture"),
			_entry("SE-RET", "Material Transfer"),
			_entry("SE-MFG", "Manufacture"),
			_entry("SE-CANCEL", "Material Consumption for Manufacture", docstatus=2),
			_entry("SE-HIDDEN", "Material Consumption for Manufacture"),
		]
		self.rows = {
			"SE-STG": [_row("RM1", batch_no="RB1", qty=125, s_warehouse="Stores", t_warehouse="Staging-L1")],
			"SE-SUR": [_row("RM2", batch_no="RB2", qty=10, s_warehouse="Stores", t_warehouse="Staging-L1")],
			"SE-MTFM": [_row("RM1", batch_no="RB1", qty=125, s_warehouse="Staging-L1", t_warehouse="WIP-L1")],
			"SE-MCFM": [_row("RM1", batch_no="RB1", qty=120, s_warehouse="WIP-L1", t_warehouse="WIP-L1")],
			"SE-RET": [_row("RM1", batch_no="RB1", qty=5, s_warehouse="WIP-L1", t_warehouse="Staging-L1")],
			"SE-MFG": [
				_row("FG10005", batch_no="AAO-007", qty=193, t_warehouse="FG", is_finished_item=1, stock_uom="Carton"),
				_row("FG10005", batch_no="AAO-007", qty=7, t_warehouse="Scrap", is_scrap_item=1, stock_uom="Carton"),
				_row("RM2", serial_and_batch_bundle="B1", qty=35.365, s_warehouse="WIP-L1"),
				_row("SFG1", qty=180, s_warehouse="Semi-finished"),
			],
		}
		self.bundles = {"B1": [("RB2", 35.365)]}

	def _run(self):
		def get_list(doctype, filters=None, fields=None, pluck=None, **kw):
			if doctype == "Stock Entry":
				return [n for n in filters["name"][1] if n != "SE-HIDDEN"]
			if doctype == "Batch":
				# RB1 readable and expired, RB2 not readable
				return [frappe._dict(name="RB1", expiry_date="2020-01-01", disabled=0)]
			raise AssertionError(doctype)

		with patch.object(bl, "find_work_order_entries", return_value={"WO-A": self.entries}), patch.object(
			bl, "fetch_entry_rows", return_value=self.rows
		), patch.object(bl, "fetch_bundle_batches", return_value=self.bundles), patch.object(
			be, "_build_nodes", side_effect=_plain_nodes
		), patch("frappe.get_list", side_effect=get_list) as gl, patch("frappe.get_all", return_value=[]), patch(
			"frappe.db.get_value",
			return_value=frappe._dict(name="WO-A", production_item="FG10005", wip_warehouse="WIP-L1", use_multi_level_bom=0),
		):
			result = be._work_order_inputs("WO-A", BATCH)
		self.get_list = gl
		return result

	def test_groups_lineage_and_tags(self):
		result = self._run()

		self.assertEqual([g["key"] for g in result["children"]], ["materials", "entries", "ineffective"])
		self.assertTrue(all(g["sub"] and g["total_qty"] is None for g in result["children"]))

		lineage = result["lineage"]
		self.assertEqual(lineage["this_batch"], 193.0)
		self.assertEqual(lineage["scrap"], 7.0)
		self.assertEqual(lineage["total"], 193.0)
		self.assertFalse(lineage["shared"])
		self.assertEqual(lineage["uom"], "Carton")
		self.assertEqual(lineage["hidden_entries"], 1)
		self.assertEqual(result["tags"], [])

	def test_material_leaves(self):
		result = self._run()
		materials = result["children"][0]
		self.assertEqual(materials["count"], 3)
		by_key = {(n["item_code"], n["name"]): n for n in materials["nodes"]}

		rb1 = by_key[("RM1", "RB1")]
		self.assertEqual(rb1["doctype"], "Batch")
		self.assertEqual(rb1["qty"], 120.0)  # transfers and the return are not consumption
		self.assertEqual(rb1["uom"], "Kg")
		self.assertTrue(rb1["neutral"])
		self.assertEqual(rb1["route"], ["batch-explorer", "RB1"])
		self.assertEqual(rb1["tags"], ["consumed", "expired"])
		self.assertEqual([ln["stock_entry"] for ln in rb1["lines"]], ["SE-MCFM"])
		self.assertIsNone(rb1["owner"])

		rb2 = by_key[("RM2", "RB2")]
		self.assertAlmostEqual(rb2["qty"], 35.365)
		self.assertIsNone(rb2["route"])  # Batch not readable -> plain text
		self.assertEqual(rb2["lines"][0]["purpose"], "Manufacture")

		sfg = by_key[("SFG1", "SFG1")]
		self.assertEqual(sfg["doctype"], "Item")
		self.assertEqual(sfg["route"], ["Form", "Item", "SFG1"])
		self.assertEqual(sfg["tags"], ["consumed", "no_batch"])

	def test_entry_leaves_are_tagged_and_qty_less(self):
		result = self._run()
		entries = result["children"][1]
		self.assertEqual(entries["hint"], "1 hidden by permissions")
		tags = {n["name"]: n["tags"] for n in entries["nodes"]}
		self.assertEqual(
			tags,
			{
				"SE-STG": [bl.TAG_STAGING],
				"SE-SUR": [bl.TAG_SURPLUS_STAGED],
				"SE-MTFM": [bl.TAG_TO_WIP],
				"SE-MCFM": [bl.TAG_CONSUMPTION],
				"SE-RET": [bl.TAG_RETURN],
				"SE-MFG": [bl.TAG_MANUFACTURE],
			},
		)
		by_name = {n["name"]: n for n in entries["nodes"]}
		self.assertTrue(all(n["qty"] is None for n in entries["nodes"]))
		self.assertEqual(by_name["SE-SUR"]["tag_detail"], "WO-A, WO-B")
		self.assertEqual(by_name["SE-RET"]["extra"], "Material Transfer · WIP-L1 → Staging-L1")

		ineffective = result["children"][2]
		self.assertEqual([n["name"] for n in ineffective["nodes"]], ["SE-CANCEL"])
		self.assertEqual(ineffective["nodes"][0]["tags"], [bl.TAG_CONSUMPTION])

	def test_permission_pass_uses_get_list(self):
		self._run()
		doctypes = [c.args[0] for c in self.get_list.call_args_list]
		self.assertIn("Stock Entry", doctypes)
		self.assertIn("Batch", doctypes)
		se_call = next(c for c in self.get_list.call_args_list if c.args[0] == "Stock Entry")
		self.assertEqual(se_call.kwargs["pluck"], "name")
		self.assertIn("SE-HIDDEN", se_call.kwargs["filters"]["name"][1])
		# every candidate is checked, never just the first page
		for c in self.get_list.call_args_list:
			self.assertEqual(c.kwargs.get("limit_page_length"), 0, c.args[0])


class TestSharedOutput(unittest.TestCase):
	@patch("frappe.db.get_value", return_value=frappe._dict(name="WO-A", use_multi_level_bom=1))
	@patch("frappe.get_all", return_value=[])
	@patch("frappe.get_list")
	def test_two_batches_from_one_work_order(self, get_list, _get_all, _wo):
		entries = [_entry("SE-M1", "Manufacture"), _entry("SE-M2", "Manufacture")]
		rows = {
			"SE-M1": [_row("FG10005", batch_no="AAO-007", qty=193, t_warehouse="FG", is_finished_item=1)],
			"SE-M2": [_row("FG10005", batch_no="AAO-008", qty=100, t_warehouse="FG", is_finished_item=1)],
		}
		get_list.side_effect = lambda doctype, filters=None, **kw: (
			filters["name"][1] if doctype == "Stock Entry" else []
		)
		with patch.object(bl, "find_work_order_entries", return_value={"WO-A": entries}), patch.object(
			bl, "fetch_entry_rows", return_value=rows
		), patch.object(bl, "fetch_bundle_batches", return_value={}), patch.object(
			be, "_build_nodes", side_effect=_plain_nodes
		):
			result = be._work_order_inputs("WO-A", BATCH)

		self.assertTrue(result["lineage"]["shared"])
		self.assertAlmostEqual(result["lineage"]["share"], 193 / 293)
		self.assertEqual(result["tags"], ["shared_output", "multi_level_bom"])
		self.assertIn("not apportioned", result["children"][0]["hint"])


class TestWorkOrderOutputs(unittest.TestCase):
	@patch("frappe.get_all", return_value=[frappe._dict(name="FG10005", item_name="Lentil Squares")])
	@patch("frappe.get_list")
	def test_consumer_work_order_lists_produced_batches(self, get_list, _get_all):
		entries = [
			_entry("SE-M", "Manufacture"),
			_entry("SE-C", "Material Consumption for Manufacture"),
		]
		rows = {
			"SE-M": [
				_row("FG10005", batch_no="AAO-007", qty=193, t_warehouse="FG", is_finished_item=1, stock_uom="Carton"),
				_row("FG10005", batch_no="AAO-007", qty=7, t_warehouse="Scrap", is_scrap_item=1, stock_uom="Carton"),
			]
		}
		get_list.side_effect = lambda doctype, filters=None, **kw: (
			filters["name"][1] if doctype == "Stock Entry" else [frappe._dict(name="AAO-007", expiry_date=None, disabled=0)]
		)
		with patch.object(bl, "find_work_order_entries", return_value={"WO-A": entries}), patch.object(
			bl, "fetch_entry_rows", return_value=rows
		) as fetch_rows, patch.object(bl, "fetch_bundle_batches", return_value={}):
			result = be._work_order_outputs("WO-A", frappe._dict(name="RB1", item="RM1", stock_uom="Kg"))

		# only the Manufacture entry is read
		self.assertEqual(fetch_rows.call_args.args[0], ["SE-M"])
		produced = result["children"][0]
		self.assertEqual(produced["key"], "produced")
		node = produced["nodes"][0]
		self.assertEqual(node["name"], "AAO-007")
		self.assertEqual(node["qty"], 193.0)  # scrap excluded
		self.assertEqual(node["uom"], "Carton")
		self.assertEqual(node["tags"], ["produced"])
		self.assertEqual(node["route"], ["batch-explorer", "AAO-007"])
		self.assertEqual(node["extra"], "FG10005 · Lentil Squares")

	@patch("frappe.get_list", return_value=[])
	def test_nothing_when_no_manufacture_entries(self, _get_list):
		with patch.object(bl, "find_work_order_entries", return_value={"WO-A": [_entry("SE-C", "Material Consumption for Manufacture")]}):
			self.assertEqual(be._work_order_outputs("WO-A", BATCH), {})


class TestMaterialNodes(unittest.TestCase):
	@patch("frappe.get_all", return_value=[])
	@patch("frappe.get_list", return_value=[frappe._dict(name="AAO-007", expiry_date=None, disabled=1)])
	def test_this_batch_is_not_linked(self, _gl, _ga):
		nodes = be._material_nodes(
			[{"item_code": "FG10005", "item_name": "x", "stock_uom": "Carton", "batch_no": "AAO-007", "qty": 1, "lines": []}],
			"AAO-007",
		)
		self.assertIsNone(nodes[0]["route"])
		self.assertEqual(nodes[0]["tags"], ["consumed", "this_batch", "disabled"])

	def test_empty(self):
		self.assertEqual(be._material_nodes([], "AAO-007"), [])


class TestGetWorkOrderInputs(unittest.TestCase):
	@patch("frappe.has_permission")
	def test_requires_work_order_read(self, has_permission):
		has_permission.side_effect = lambda doctype, ptype="read", doc=None: doctype != "Work Order"
		with self.assertRaises(frappe.PermissionError):
			be.get_work_order_inputs("WO-A", "AAO-007")
		has_permission.assert_any_call("Work Order", "read", doc="WO-A")

	@patch("frappe.has_permission", return_value=False)
	def test_requires_stock_entry_read(self, _perm):
		with self.assertRaises(frappe.PermissionError):
			be.get_work_order_inputs("WO-A", "AAO-007")

	@patch.object(be, "_work_order_inputs", return_value={"children": []})
	@patch.object(be, "_load_batch", return_value=BATCH)
	@patch("frappe.has_permission", return_value=True)
	def test_delegates_to_eager_builder(self, _perm, _load, inputs):
		self.assertEqual(be.get_work_order_inputs(" WO-A ", "AAO-007"), {"children": []})
		inputs.assert_called_once_with("WO-A", BATCH)


class TestDerivedVouchersUnchanged(unittest.TestCase):
	@patch.object(be, "_child_links", return_value=set())
	def test_work_orders_from_stock_entry_info(self, _links):
		direct = {"Stock Entry": {"SE-1": {}, "SE-2": {}}}
		se_info = {
			"SE-1": frappe._dict(name="SE-1", work_order="WO-1", purpose="Manufacture"),
			"SE-2": frappe._dict(name="SE-2", work_order=None, purpose="Material Transfer"),
		}
		self.assertEqual(be._derived_vouchers(direct, se_info), {"Work Order": {"WO-1"}})


if __name__ == "__main__":
	unittest.main()
