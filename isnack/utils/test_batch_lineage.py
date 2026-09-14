# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""Unit tests for isnack.utils.batch_lineage (pure mocks, no site needed)."""

import unittest
from unittest.mock import MagicMock, patch

import frappe
from isnack.utils import batch_lineage as bl

ALL_CUSTOM = set(bl.OPTIONAL_ENTRY_FIELDS)


def _meta(fields):
	meta = MagicMock()
	meta.has_field.side_effect = lambda f: f in fields
	return meta


def _entry(name, purpose="Material Transfer", docstatus=1, **kw):
	d = frappe._dict(name=name, purpose=purpose, docstatus=docstatus, posting_date="2026-08-21")
	d.update(kw)
	return d


def _row(item_code, **kw):
	d = frappe._dict(
		name=f"row-{item_code}-{kw.get('batch_no') or 'nb'}",
		item_code=item_code,
		item_name=item_code.lower(),
		qty=kw.pop("qty", 10),
		uom="Kg",
		stock_uom="Kg",
		transfer_qty=None,
		s_warehouse=None,
		t_warehouse=None,
		batch_no=None,
		serial_and_batch_bundle=None,
		is_finished_item=0,
		is_scrap_item=0,
	)
	d.update(kw)
	if d.transfer_qty is None:
		d.transfer_qty = d.qty
	return d


class TestFindWorkOrderEntries(unittest.TestCase):
	def _fake_get_all(self, doctype, filters=None, fields=None, **kwargs):
		f = filters or {}
		if doctype == "Surplus Originating Work Order":
			if "work_order" in f:
				return [frappe._dict(parent="SE-SURPLUS", work_order="WO1")]
			if "parent" in f:
				# SE-SURPLUS lists two originating WOs; SE-LEGACY has no rows
				return [
					frappe._dict(parent="SE-SURPLUS", work_order="WO1"),
					frappe._dict(parent="SE-SURPLUS", work_order="WO2"),
				]
			return []
		if doctype != "Stock Entry":
			return []
		if "remarks" in f:
			return [frappe._dict(name="SE-SWEEP-OLD")]
		if "custom_surplus_swept_by_work_order" in f:
			return [
				frappe._dict(
					name="SE-SURPLUS",
					custom_surplus_swept_by_work_order="WO1",
					custom_surplus_wip_transfer="SE-SWEEP",
				),
				frappe._dict(
					name="SE-OLD",
					custom_surplus_swept_by_work_order="WO1",
					custom_surplus_wip_transfer=None,
				),
			]
		if "custom_originating_work_order" in f:
			return [frappe._dict(name="SE-LEGACY", custom_originating_work_order="WO1")]
		if "name" in f:
			return [_entry(n, posting_date="2026-08-22") for n in f["name"][1]]
		if "work_order" in f:
			return [
				_entry("SE-A", work_order="WO1", posting_date="2026-08-20"),
				_entry("SE-B", purpose="Manufacture", work_order="WO1", posting_date="2026-08-21"),
			]
		return []

	@patch("frappe.get_meta")
	@patch("frappe.get_all")
	def test_direct_surplus_and_sweep_links(self, get_all, get_meta):
		get_meta.return_value = _meta(ALL_CUSTOM)
		get_all.side_effect = self._fake_get_all

		result = bl.find_work_order_entries(["WO1"])

		by_name = {e.name: e for e in result["WO1"]}
		self.assertEqual(
			set(by_name), {"SE-A", "SE-B", "SE-SURPLUS", "SE-LEGACY", "SE-SWEEP", "SE-SWEEP-OLD"}
		)
		self.assertEqual(by_name["SE-A"].link, bl.LINK_WORK_ORDER)
		self.assertEqual(by_name["SE-SURPLUS"].link, bl.LINK_SURPLUS_STAGED)
		self.assertEqual(by_name["SE-SURPLUS"].originating_work_orders, ["WO1", "WO2"])
		self.assertEqual(by_name["SE-LEGACY"].link, bl.LINK_SURPLUS_STAGED)
		self.assertEqual(by_name["SE-LEGACY"].originating_work_orders, ["WO1"])
		self.assertEqual(by_name["SE-SWEEP"].link, bl.LINK_SURPLUS_SWEPT)
		self.assertEqual(by_name["SE-SWEEP-OLD"].link, bl.LINK_SURPLUS_SWEPT)
		# sorted by posting date, then name
		self.assertEqual([e.name for e in result["WO1"]][:2], ["SE-A", "SE-B"])

		# child-table reads always name their parent doctype
		for call in get_all.call_args_list:
			if call.args[0] == "Surplus Originating Work Order":
				self.assertEqual(call.kwargs.get("parent_doctype"), "Stock Entry")

		# the legacy sweep is matched on the exact remark the MES writes
		remark_calls = [
			c for c in get_all.call_args_list
			if c.args[0] == "Stock Entry" and "remarks" in (c.kwargs.get("filters") or {})
		]
		self.assertEqual(len(remark_calls), 1)
		self.assertEqual(
			remark_calls[0].kwargs["filters"]["remarks"],
			"Surplus swept to WIP for WO: WO1 (from SE-OLD)",
		)
		self.assertEqual(remark_calls[0].kwargs["filters"]["work_order"], ["is", "not set"])

	@patch("frappe.get_meta")
	@patch("frappe.get_all")
	def test_custom_branches_skipped_when_fields_missing(self, get_all, get_meta):
		get_meta.return_value = _meta(set())
		get_all.return_value = [_entry("SE-A", work_order="WO1")]

		result = bl.find_work_order_entries(["WO1", "WO9"])

		self.assertEqual([e.name for e in result["WO1"]], ["SE-A"])
		self.assertEqual(result["WO9"], [])
		self.assertEqual(get_all.call_count, 1)
		self.assertEqual(get_all.call_args.args[0], "Stock Entry")
		self.assertNotIn("custom_is_surplus", get_all.call_args.kwargs["fields"])

	@patch("frappe.get_all")
	def test_empty_input_reads_nothing(self, get_all):
		self.assertEqual(bl.find_work_order_entries([]), {})
		self.assertEqual(bl.find_work_order_entries(None), {})
		get_all.assert_not_called()


class TestRowsAndBundles(unittest.TestCase):
	@patch("frappe.get_all")
	def test_fetch_entry_rows_groups_by_parent_with_parent_doctype(self, get_all):
		get_all.return_value = [
			frappe._dict(parent="SE-1", idx=1, item_code="RM1"),
			frappe._dict(parent="SE-1", idx=2, item_code="RM2"),
			frappe._dict(parent="SE-2", idx=1, item_code="RM1"),
		]
		rows = bl.fetch_entry_rows(["SE-1", "SE-2", "SE-1", None])
		self.assertEqual([r.item_code for r in rows["SE-1"]], ["RM1", "RM2"])
		self.assertEqual(len(rows["SE-2"]), 1)
		self.assertEqual(get_all.call_args.args[0], "Stock Entry Detail")
		self.assertEqual(get_all.call_args.kwargs["parent_doctype"], "Stock Entry")
		self.assertEqual(get_all.call_args.kwargs["filters"]["parent"], ["in", ["SE-1", "SE-2"]])

	@patch("frappe.get_all")
	def test_fetch_bundle_batches_uses_absolute_qty(self, get_all):
		get_all.return_value = [
			frappe._dict(parent="B1", batch_no="RB1", qty=-60),
			frappe._dict(parent="B1", batch_no="RB2", qty=-40),
			frappe._dict(parent="B1", batch_no="RB2", qty=-5),
			frappe._dict(parent="B2", batch_no="RB9", qty=12),
		]
		out = bl.fetch_bundle_batches(["B1", "B2"])
		self.assertEqual(out["B1"], [("RB1", 60.0), ("RB2", 45.0)])
		self.assertEqual(out["B2"], [("RB9", 12.0)])
		self.assertEqual(get_all.call_args.args[0], "Serial and Batch Entry")
		self.assertEqual(get_all.call_args.kwargs["parent_doctype"], "Serial and Batch Bundle")

	@patch("frappe.get_all")
	def test_empty_names_read_nothing(self, get_all):
		self.assertEqual(bl.fetch_entry_rows([]), {})
		self.assertEqual(bl.fetch_bundle_batches([None]), {})
		get_all.assert_not_called()

	def test_bundle_names_only_for_rows_without_batch(self):
		rows = {
			"SE-1": [
				_row("RM1", batch_no="RB1", serial_and_batch_bundle="B-direct"),
				_row("RM2", serial_and_batch_bundle="B-auto"),
				_row("RM3"),
			]
		}
		self.assertEqual(bl.bundle_names(rows), ["B-auto"])


class TestExpandRowBatches(unittest.TestCase):
	def test_direct_batch_uses_transfer_qty(self):
		row = _row("RM1", batch_no="RB1", qty=10, transfer_qty=10000, serial_and_batch_bundle="B1")
		self.assertEqual(
			bl.expand_row_batches(row, {"B1": [("RB1", 10000)]}),
			[{"batch_no": "RB1", "qty": 10000.0, "split": None}],
		)

	def test_bundle_only_row_splits_per_batch(self):
		row = _row("RM1", serial_and_batch_bundle="B1", qty=100)
		parts = bl.expand_row_batches(row, {"B1": [("RB1", 60), ("RB2", 40)]})
		self.assertEqual(
			parts,
			[
				{"batch_no": "RB1", "qty": 60.0, "split": (1, 2)},
				{"batch_no": "RB2", "qty": 40.0, "split": (2, 2)},
			],
		)

	def test_single_batch_bundle_has_no_split(self):
		row = _row("RM1", serial_and_batch_bundle="B1", qty=100)
		self.assertEqual(
			bl.expand_row_batches(row, {"B1": [("RB1", 100)]}),
			[{"batch_no": "RB1", "qty": 100.0, "split": None}],
		)

	def test_non_batch_row(self):
		row = _row("SFG1", qty=180)
		self.assertEqual(bl.expand_row_batches(row, {}), [{"batch_no": None, "qty": 180.0, "split": None}])


class TestConsumption(unittest.TestCase):
	def test_is_consumed_row(self):
		mcfm = _entry("SE-C", purpose="Material Consumption for Manufacture")
		mfg = _entry("SE-M", purpose="Manufacture")
		self.assertTrue(bl.is_consumed_row(mcfm, _row("RM1", s_warehouse="WIP")))
		self.assertTrue(bl.is_consumed_row(mfg, _row("RM1", s_warehouse="WIP")))
		self.assertFalse(bl.is_consumed_row(mfg, _row("FG1", t_warehouse="FG", is_finished_item=1)))
		self.assertFalse(bl.is_consumed_row(mfg, _row("FG1", t_warehouse="Scrap", is_scrap_item=1)))
		self.assertFalse(bl.is_consumed_row(mcfm, _row("RM1", t_warehouse="WIP")))
		self.assertFalse(bl.is_consumed_row(_entry("SE-T", purpose="Material Transfer"), _row("RM1", s_warehouse="Stores")))
		self.assertFalse(bl.is_consumed_row(_entry("SE-D", purpose="Manufacture", docstatus=0), _row("RM1", s_warehouse="WIP")))

	def test_consumed_materials_aggregates_per_item_and_batch(self):
		mcfm = _entry("SE-C", purpose="Material Consumption for Manufacture", posting_date="2026-08-21")
		mfg = _entry("SE-M", purpose="Manufacture", posting_date="2026-08-21")
		transfer = _entry("SE-T", purpose="Material Transfer")
		rows = {
			"SE-C": [_row("RM1", batch_no="RB1", qty=120, s_warehouse="WIP")],
			"SE-M": [
				_row("FG1", batch_no="AAO-007", qty=193, t_warehouse="FG", is_finished_item=1),
				_row("RM1", batch_no="RB1", qty=35.365, s_warehouse="WIP"),
				_row("RM2", serial_and_batch_bundle="B1", qty=100, s_warehouse="WIP"),
				_row("SFG1", qty=180, s_warehouse="Semi-finished"),
			],
			"SE-T": [_row("RM1", batch_no="RB1", qty=500, s_warehouse="Stores", t_warehouse="Staging")],
		}
		bundles = {"B1": [("RB2", 60), ("RB3", 40)]}

		materials = bl.consumed_materials([mcfm, mfg, transfer], rows, bundles)

		keys = [(m["item_code"], m["batch_no"]) for m in materials]
		self.assertEqual(keys, [("RM1", "RB1"), ("RM2", "RB2"), ("RM2", "RB3"), ("SFG1", None)])
		rm1 = materials[0]
		self.assertAlmostEqual(rm1["qty"], 155.365)
		self.assertEqual([ln["stock_entry"] for ln in rm1["lines"]], ["SE-C", "SE-M"])
		self.assertEqual(rm1["lines"][0]["purpose"], "Material Consumption for Manufacture")
		self.assertEqual(rm1["lines"][0]["s_warehouse"], "WIP")
		self.assertEqual(materials[1]["lines"][0]["split"], (1, 2))
		self.assertEqual(materials[3]["qty"], 180.0)


class TestFinishedGoodsAndShare(unittest.TestCase):
	def _fixture(self):
		mfg_a = _entry("SE-MA", purpose="Manufacture")
		mfg_b = _entry("SE-MB", purpose="Manufacture")
		mcfm = _entry("SE-C", purpose="Material Consumption for Manufacture")
		rows = {
			"SE-MA": [
				_row("FG1", batch_no="AAO-007", qty=193, t_warehouse="FG", is_finished_item=1),
				_row("FG1", batch_no="AAO-007", qty=7, t_warehouse="Scrap", is_scrap_item=1),
				_row("RM1", batch_no="RB1", qty=1, s_warehouse="WIP"),
			],
			"SE-MB": [_row("FG1", batch_no="AAO-006", qty=100, t_warehouse="FG", is_finished_item=1)],
			"SE-C": [_row("RM1", batch_no="RB1", qty=1, s_warehouse="WIP")],
		}
		return [mfg_a, mfg_b, mcfm], rows

	def test_finished_goods_rows(self):
		entries, rows = self._fixture()
		fg = bl.finished_goods(entries, rows, {})
		self.assertEqual(
			[(r["batch_no"], r["qty"], r["scrap"]) for r in fg],
			[("AAO-007", 193.0, False), ("AAO-007", 7.0, True), ("AAO-006", 100.0, False)],
		)

	def test_share_excludes_scrap_and_flags_shared_output(self):
		entries, rows = self._fixture()
		share = bl.compute_share(bl.finished_goods(entries, rows, {}), "AAO-007")
		self.assertEqual(share["this_batch"], 193.0)
		self.assertEqual(share["scrap"], 7.0)
		self.assertEqual(share["total"], 293.0)
		self.assertAlmostEqual(share["share"], 193 / 293)
		self.assertTrue(share["shared"])

	def test_single_batch_is_not_shared(self):
		fg = [{"batch_no": "AAO-007", "qty": 193, "scrap": False}]
		share = bl.compute_share(fg, "AAO-007")
		self.assertEqual(share["share"], 1.0)
		self.assertFalse(share["shared"])

	def test_no_output_rows(self):
		share = bl.compute_share([], "AAO-007")
		self.assertIsNone(share["share"])
		self.assertFalse(share["shared"])
		self.assertEqual(share["total"], 0.0)


class TestFgBatchResolvers(unittest.TestCase):
	"""The label-facing resolvers. A Work Order has no batch of its own, so every
	label of its output reads the batch back off its submitted Manufacture entry."""

	def _fake_get_all(self, entries=(), rows=(), bundle_entries=()):
		"""A ``frappe.get_all`` stand-in that honours the filters it is handed.

		Filtering the fixtures here, rather than returning canned rows per
		doctype, is what lets a draft entry or a scrap row prove that the
		resolver excluded it. Results are projected to ``fields`` so a resolver
		can only read what it actually asked the database for.
		"""
		tables = {
			"Stock Entry": entries,
			"Stock Entry Detail": rows,
			"Serial and Batch Entry": bundle_entries,
		}

		def matches(doc, filters):
			for field, condition in (filters or {}).items():
				value = doc.get(field)
				if isinstance(condition, (list, tuple)):
					operator, operand = condition
					if operator == "in" and value not in operand:
						return False
					if operator == "is" and bool(value) != (operand == "set"):
						return False
				elif value != condition:
					return False
			return True

		def get_all(doctype, filters=None, fields=None, **kwargs):
			return [
				frappe._dict({f: d.get(f) for f in (fields or d)})
				for d in tables.get(doctype, [])
				if matches(d, filters)
			]

		return get_all

	def _fg_row(self, parent, **kw):
		"""A finished-item Stock Entry Detail row of ``parent``."""
		return _row("FG10011", parent=parent, parenttype="Stock Entry", t_warehouse="FG", is_finished_item=1, **kw)

	def _bundle_entry(self, bundle, batch_no, qty=-27):
		"""A Serial and Batch Entry of ``bundle`` (outward qty is negative)."""
		return frappe._dict(parent=bundle, idx=1, batch_no=batch_no, qty=qty)

	def _two_batch_fixture(self):
		# one Work Order closed twice: the second entry re-books the first
		# entry's batch alongside a new one
		return self._fake_get_all(
			entries=[
				_entry("SE-1", purpose="Manufacture", work_order="WO-1"),
				_entry("SE-2", purpose="Manufacture", work_order="WO-1"),
			],
			rows=[
				self._fg_row("SE-1", batch_no="B-FIRST"),
				self._fg_row("SE-2", batch_no="B-FIRST"),
				self._fg_row("SE-2", batch_no="B-SECOND"),
			],
		)

	@patch("frappe.get_all")
	def test_batch_written_on_the_finished_row_is_used_directly(self, get_all):
		get_all.side_effect = self._fake_get_all(
			entries=[_entry("SE-1", purpose="Manufacture", work_order="WO-1")],
			rows=[self._fg_row("SE-1", batch_no="BBB-111")],
		)
		self.assertEqual(bl.fg_batches_for_work_order("WO-1"), ["BBB-111"])
		self.assertEqual(bl.fg_batch_for_work_order("WO-1"), "BBB-111")

	@patch("frappe.get_all")
	def test_consumed_raw_material_rows_are_not_finished_goods(self, get_all):
		# the Manufacture entry books the BOM remainder as consumption in the same
		# document: a raw-material batch must never end up on a finished-goods label
		get_all.side_effect = self._fake_get_all(
			entries=[_entry("SE-1", purpose="Manufacture", work_order="WO-1")],
			rows=[
				self._fg_row("SE-1", batch_no="BBB-111"),
				_row("RM1", parent="SE-1", parenttype="Stock Entry", batch_no="RB1", s_warehouse="WIP"),
			],
		)
		self.assertEqual(bl.fg_batches_for_work_order("WO-1"), ["BBB-111"])

	@patch("frappe.get_all")
	def test_batch_is_read_from_the_bundle_when_the_row_carries_none(self, get_all):
		"""The ``use_serial_batch_fields = 0`` case: bundle only, no row batch_no.

		This is the regression the whole change exists to prevent. Stock
		Settings.use_serial_batch_fields is 1 today, and that is the only reason
		``Stock Entry Detail.batch_no`` is populated at all; turn it off and
		ERPNext writes the Serial and Batch Bundle alone. The batch must still
		reach the label, so every read here is bundle-aware.
		"""
		get_all.side_effect = self._fake_get_all(
			entries=[_entry("SE-1", purpose="Manufacture", work_order="WO-1")],
			rows=[self._fg_row("SE-1", batch_no=None, serial_and_batch_bundle="1c22f62f08664557bf2f")],
			bundle_entries=[self._bundle_entry("1c22f62f08664557bf2f", "BBB-111")],
		)

		self.assertEqual(bl.fg_batches_for_work_order("WO-1"), ["BBB-111"])
		self.assertEqual(bl.fg_batch_for_work_order("WO-1"), "BBB-111")
		# the batch came off the bundle, which means the bundle was really read
		self.assertIn("Serial and Batch Entry", [c.args[0] for c in get_all.call_args_list])

	@patch("frappe.get_all")
	def test_scrap_rows_are_never_labelled(self, get_all):
		get_all.side_effect = self._fake_get_all(
			entries=[_entry("SE-1", purpose="Manufacture", work_order="WO-1")],
			rows=[
				self._fg_row("SE-1", batch_no="BBB-111"),
				# the shape the MES writes: scrap flag only, no finished flag
				_row("FG10011", parent="SE-1", parenttype="Stock Entry", batch_no="SCRAP-ONLY", is_scrap_item=1),
				# and a row flagged both ways, which is_finished_item=1 lets through
				self._fg_row("SE-1", batch_no="SCRAP-BOTH", is_scrap_item=1),
			],
		)

		self.assertEqual(bl.fg_batches_for_work_order("WO-1"), ["BBB-111"])
		self.assertEqual(bl.fg_batch_for_work_order("WO-1"), "BBB-111")

	@patch("frappe.get_all")
	def test_finished_row_with_an_unwritten_scrap_flag_still_counts(self, get_all):
		# a legacy row whose is_scrap_item was never written is finished goods,
		# not scrap: a SQL "is_scrap_item = 0" filter would drop it silently
		get_all.side_effect = self._fake_get_all(
			entries=[_entry("SE-1", purpose="Manufacture", work_order="WO-1")],
			rows=[self._fg_row("SE-1", batch_no="BBB-111", is_scrap_item=None)],
		)
		self.assertEqual(bl.fg_batches_for_work_order("WO-1"), ["BBB-111"])

	@patch("frappe.get_all")
	def test_work_order_with_no_submitted_manufacture_entry_has_no_batch(self, get_all):
		# production has not been closed yet; the label prints without a batch
		get_all.side_effect = self._fake_get_all(
			entries=[_entry("SE-1", purpose="Material Transfer for Manufacture", work_order="WO-1")],
			rows=[self._fg_row("SE-1", batch_no="BBB-111")],
		)
		self.assertEqual(bl.fg_batches_for_work_order("WO-1"), [])
		self.assertIsNone(bl.fg_batch_for_work_order("WO-1"))

	@patch("frappe.get_all")
	def test_draft_and_cancelled_manufacture_entries_are_ignored(self, get_all):
		get_all.side_effect = self._fake_get_all(
			entries=[
				_entry("SE-DRAFT", purpose="Manufacture", docstatus=0, work_order="WO-1"),
				_entry("SE-CANCELLED", purpose="Manufacture", docstatus=2, work_order="WO-1"),
				_entry("SE-SUBMITTED", purpose="Manufacture", docstatus=1, work_order="WO-2"),
			],
			rows=[
				self._fg_row("SE-DRAFT", batch_no="DRAFT-1"),
				self._fg_row("SE-CANCELLED", batch_no="CANCELLED-1"),
				self._fg_row("SE-SUBMITTED", batch_no="BBB-111"),
			],
		)

		self.assertEqual(bl.fg_batches_for_work_order("WO-1"), [])
		self.assertIsNone(bl.fg_batch_for_work_order("WO-1"))
		# the same fixture still resolves the submitted entry of another WO
		self.assertEqual(bl.fg_batches_for_work_order("WO-2"), ["BBB-111"])

	@patch("frappe.get_all")
	def test_non_batch_tracked_item_resolves_to_no_batch(self, get_all):
		# neither a batch_no nor a bundle: the label must print no batch rather
		# than the string "None"
		get_all.side_effect = self._fake_get_all(
			entries=[_entry("SE-1", purpose="Manufacture", work_order="WO-1")],
			rows=[self._fg_row("SE-1")],
		)
		self.assertEqual(bl.fg_batches_for_work_order("WO-1"), [])
		self.assertIsNone(bl.fg_batch_for_work_order("WO-1"))

	@patch("frappe.get_all")
	def test_several_batches_are_listed_once_each_in_first_seen_order(self, get_all):
		get_all.side_effect = self._two_batch_fixture()
		self.assertEqual(bl.fg_batches_for_work_order("WO-1"), ["B-FIRST", "B-SECOND"])

	@patch("frappe.get_all")
	def test_fg_batch_for_work_order_is_none_when_the_work_order_booked_several_batches(self, get_all):
		# one label carries one batch: no batch at all beats an arbitrary one
		get_all.side_effect = self._two_batch_fixture()
		self.assertIsNone(bl.fg_batch_for_work_order("WO-1"))

	@patch("frappe.get_all")
	def test_fg_batch_for_work_orders_returns_the_batch_every_work_order_shares(self, get_all):
		get_all.side_effect = self._fake_get_all(
			entries=[
				_entry("SE-1", purpose="Manufacture", work_order="WO-1"),
				_entry("SE-2", purpose="Manufacture", work_order="WO-2"),
			],
			rows=[self._fg_row("SE-1", batch_no="BBB-111"), self._fg_row("SE-2", batch_no="BBB-111")],
		)

		self.assertEqual(bl.fg_batch_for_work_orders(["WO-1", "WO-2", "WO-1"]), "BBB-111")
		# the whole pallet costs one read for the entries and one for their rows,
		# however many Work Orders it spans, and the list is de-duped first
		self.assertEqual(get_all.call_count, 2)
		self.assertEqual(get_all.call_args_list[0].kwargs["filters"]["work_order"], ["in", ["WO-1", "WO-2"]])

	@patch("frappe.get_all")
	def test_fg_batch_for_work_orders_is_none_when_the_work_orders_disagree(self, get_all):
		get_all.side_effect = self._fake_get_all(
			entries=[
				_entry("SE-1", purpose="Manufacture", work_order="WO-1"),
				_entry("SE-2", purpose="Manufacture", work_order="WO-2"),
			],
			rows=[self._fg_row("SE-1", batch_no="B-ONE"), self._fg_row("SE-2", batch_no="B-TWO")],
		)
		self.assertIsNone(bl.fg_batch_for_work_orders(["WO-1", "WO-2"]))

	@patch("frappe.get_all")
	def test_fg_batch_for_work_orders_is_none_when_one_work_order_has_no_batch(self, get_all):
		get_all.side_effect = self._fake_get_all(
			entries=[_entry("SE-1", purpose="Manufacture", work_order="WO-1")],
			rows=[self._fg_row("SE-1", batch_no="BBB-111")],
		)
		self.assertIsNone(bl.fg_batch_for_work_orders(["WO-1", "WO-2"]))

	@patch("frappe.get_all")
	def test_fg_batch_for_work_orders_is_none_when_a_work_order_booked_several_batches(self, get_all):
		# WO-2 has no single batch of its own, so the pallet has none to share
		get_all.side_effect = self._fake_get_all(
			entries=[
				_entry("SE-1", purpose="Manufacture", work_order="WO-1"),
				_entry("SE-2", purpose="Manufacture", work_order="WO-2"),
			],
			rows=[
				self._fg_row("SE-1", batch_no="B-ONE"),
				self._fg_row("SE-2", batch_no="B-ONE"),
				self._fg_row("SE-2", batch_no="B-TWO"),
			],
		)
		self.assertIsNone(bl.fg_batch_for_work_orders(["WO-1", "WO-2"]))

	@patch("frappe.get_all")
	def test_fg_batch_for_work_orders_reads_nothing_for_an_empty_list(self, get_all):
		self.assertIsNone(bl.fg_batch_for_work_orders([]))
		self.assertIsNone(bl.fg_batch_for_work_orders(None))
		self.assertIsNone(bl.fg_batch_for_work_orders([None, ""]))
		get_all.assert_not_called()

	@patch("frappe.get_all")
	def test_falsy_work_order_reads_nothing(self, get_all):
		self.assertEqual(bl.fg_batches_for_work_order(None), [])
		self.assertEqual(bl.fg_batches_for_work_order(""), [])
		self.assertIsNone(bl.fg_batch_for_work_order(None))
		get_all.assert_not_called()

	@patch("frappe.get_all")
	def test_a_read_failure_degrades_to_no_batch_instead_of_raising(self, get_all):
		# a print format cannot recover mid-render, so the label loses its batch
		# rather than the render failing
		get_all.side_effect = Exception("Table 'tabStock Entry' doesn't exist")
		self.assertEqual(bl.fg_batches_for_work_order("WO-1"), [])
		self.assertIsNone(bl.fg_batch_for_work_order("WO-1"))
		self.assertIsNone(bl.fg_batch_for_work_orders(["WO-1", "WO-2"]))

	@patch("frappe.get_meta")
	@patch("frappe.get_all")
	def test_only_submitted_manufacture_entries_and_their_finished_rows_are_read(self, get_all, get_meta):
		get_all.side_effect = self._fake_get_all(
			entries=[_entry("SE-1", purpose="Manufacture", work_order="WO-1")],
			rows=[self._fg_row("SE-1", batch_no=None, serial_and_batch_bundle="B-1")],
			bundle_entries=[self._bundle_entry("B-1", "BBB-111")],
		)

		self.assertEqual(bl.fg_batches_for_work_order("WO-1"), ["BBB-111"])

		entries, rows, bundles = get_all.call_args_list
		self.assertEqual(entries.args[0], "Stock Entry")
		self.assertEqual(
			entries.kwargs["filters"],
			{"work_order": ["in", ["WO-1"]], "purpose": "Manufacture", "docstatus": 1},
		)
		# get_all defaults to "modified desc", so "first-seen" needs this spelled out
		self.assertEqual(entries.kwargs["order_by"], "posting_date, posting_time, name")
		self.assertEqual(rows.args[0], "Stock Entry Detail")
		self.assertEqual(rows.kwargs["filters"]["parenttype"], "Stock Entry")
		self.assertEqual(rows.kwargs["filters"]["is_finished_item"], 1)
		self.assertEqual(rows.kwargs["parent_doctype"], "Stock Entry")
		self.assertEqual(rows.kwargs["order_by"], "parent, idx")
		self.assertEqual(bundles.args[0], "Serial and Batch Entry")
		# the surplus lineage find_work_order_entries walks (and the Stock Entry
		# meta read it opens with) is far too heavy for a label render
		get_meta.assert_not_called()


class TestBundleBatchNo(unittest.TestCase):
	"""The Stock Entry label formats' fallback when a row carries no batch of its own."""

	def _entries(self, *pairs):
		def get_all(doctype, **kwargs):
			if doctype != "Serial and Batch Entry":
				return []
			wanted = (kwargs.get("filters") or {}).get("parent", [None, []])[1]
			return [
				frappe._dict(parent=b, batch_no=n, qty=-27)
				for b, n in pairs
				if b in wanted
			]
		return get_all

	@patch("frappe.get_all")
	def test_single_batch_bundle_resolves_to_its_batch(self, get_all):
		get_all.side_effect = self._entries(("B-1", "BBB-111"))
		self.assertEqual(bl.bundle_batch_no("B-1"), "BBB-111")

	@patch("frappe.get_all")
	def test_bundle_holding_several_batches_resolves_to_none(self, get_all):
		"""One label carries one batch, so a mixed bundle prints none rather than the first."""
		get_all.side_effect = self._entries(("B-1", "BBB-111"), ("B-1", "AAA-999"))
		self.assertIsNone(bl.bundle_batch_no("B-1"))

	@patch("frappe.get_all")
	def test_empty_bundle_resolves_to_none(self, get_all):
		get_all.side_effect = self._entries()
		self.assertIsNone(bl.bundle_batch_no("B-1"))

	@patch("frappe.get_all")
	def test_no_bundle_is_not_a_read(self, get_all):
		"""A row with use_serial_batch_fields on has no bundle to fall back to."""
		for empty in (None, ""):
			self.assertIsNone(bl.bundle_batch_no(empty))
		get_all.assert_not_called()

	@patch("frappe.get_all", side_effect=Exception("db down"))
	def test_a_read_failure_degrades_to_no_batch_instead_of_raising(self, get_all):
		"""A print format has no way to recover mid-render, so the label just loses the batch."""
		self.assertIsNone(bl.bundle_batch_no("B-1"))


class TestClassification(unittest.TestCase):
	def test_tags(self):
		self.assertEqual(bl.classify_entry(_entry("x", purpose="Manufacture")), bl.TAG_MANUFACTURE)
		self.assertEqual(
			bl.classify_entry(_entry("x", purpose="Material Consumption for Manufacture")), bl.TAG_CONSUMPTION
		)
		self.assertEqual(
			bl.classify_entry(_entry("x", purpose="Material Transfer for Manufacture")), bl.TAG_TO_WIP
		)
		self.assertEqual(
			bl.classify_entry(_entry("x", purpose="Material Transfer for Manufacture", is_return=1)),
			bl.TAG_RETURN_ERPNEXT,
		)
		self.assertEqual(
			bl.classify_entry(_entry("x", remarks="Staging transfer for WO: WO1")), bl.TAG_STAGING
		)
		self.assertEqual(bl.classify_entry(_entry("x", remarks="Pallet: P1 | WO: WO1")), bl.TAG_STAGING)
		self.assertEqual(
			bl.classify_entry(_entry("x", remarks="Fulfil Material Request MR-1 | WO: WO1")),
			bl.TAG_MR_FULFILMENT,
		)
		self.assertEqual(bl.classify_entry(_entry("x", link=bl.LINK_SURPLUS_STAGED)), bl.TAG_SURPLUS_STAGED)
		self.assertEqual(bl.classify_entry(_entry("x", link=bl.LINK_SURPLUS_SWEPT)), bl.TAG_SURPLUS_SWEPT)
		self.assertEqual(bl.classify_entry(_entry("x")), bl.TAG_TRANSFER)

	def test_return_detected_from_rows_leaving_wip(self):
		entry = _entry("x", purpose="Material Transfer")
		rows = [_row("RM1", s_warehouse="WIP-L1", t_warehouse="Staging-L1")]
		self.assertEqual(bl.classify_entry(entry, rows, {"WIP-L1"}), bl.TAG_RETURN)
		self.assertEqual(bl.classify_entry(entry, rows, {"WIP-L2"}), bl.TAG_TRANSFER)
		self.assertEqual(bl.classify_entry(entry, rows, set()), bl.TAG_TRANSFER)

	def test_observed_wip_warehouses(self):
		mtfm = _entry("SE-1", purpose="Material Transfer for Manufacture")
		mcfm = _entry("SE-2", purpose="Material Consumption for Manufacture")
		rows = {
			"SE-1": [_row("RM1", s_warehouse="Staging", t_warehouse="WIP-L1")],
			"SE-2": [_row("RM1", s_warehouse="WIP-L1", t_warehouse="WIP-L1")],
		}
		self.assertEqual(bl.observed_wip_warehouses([mtfm, mcfm], rows), {"WIP-L1"})

	def test_entry_warehouses(self):
		header = _entry("x", from_warehouse="A", to_warehouse="B")
		self.assertEqual(bl.entry_warehouses(header, []), ("A", "B"))
		rows = [_row("RM1", s_warehouse="WIP", t_warehouse="Staging"), _row("RM2", s_warehouse="WIP", t_warehouse="Stores")]
		self.assertEqual(bl.entry_warehouses(_entry("x"), rows), ("WIP", "*"))
		self.assertEqual(bl.entry_warehouses(_entry("x"), []), (None, None))


if __name__ == "__main__":
	unittest.main()
