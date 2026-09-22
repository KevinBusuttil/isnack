# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""Unit tests for the apportioning columns of the Customs Export Traceability
Report (pure mocks, no site).

The report lists the whole consumption of every Work Order that fed a
finished-goods batch. The apportioned figures scale that consumption to the
cartons of the batch actually sold on the invoice line, so their total agrees
with the cost-of-sales posting of the delivery.
"""

import base64
import unittest
from io import BytesIO
from unittest.mock import patch

import frappe

import isnack.isnack.report.customs_export_traceability_report.customs_export_traceability_report as report

FILTERS = frappe._dict(company="Isnack", from_date="2026-08-01", to_date="2026-08-31")


def _si_row(idx, item_code, stock_qty, bundle=None, batch_no=None):
	return frappe._dict(
		sales_invoice="SINV-1",
		company="Isnack",
		posting_date="2026-08-27",
		customer="C",
		customer_name="Customer",
		currency="EUR",
		idx=idx,
		fg_item_code=item_code,
		fg_item_name=item_code.lower(),
		fg_description=item_code,
		qty=stock_qty,
		uom="Carton",
		stock_qty=stock_qty,
		item_group="Finished Goods",
		batch_no=batch_no,
		serial_and_batch_bundle=bundle,
	)


def _wo_entry(work_order, stock_entry, fg_qty, wo_fg_qty=None):
	return {
		"work_order": work_order,
		"stock_entry": stock_entry,
		"manufacturing_date": "2026-08-21",
		"wo_item": "FG10005",
		"wo_qty": fg_qty,
		"fg_qty": fg_qty,
		"wo_fg_qty": wo_fg_qty if wo_fg_qty is not None else fg_qty,
	}


def _rm(item_code, qty, rate, batch_no="RMB-1"):
	return {
		"item_code": item_code,
		"item_name": item_code.lower(),
		"description": item_code,
		"stock_uom": "Kg",
		"qty": qty,
		"consumed_cost": qty * rate,
		"batch_no": batch_no,
		"purchase_receipt": None,
	}


class TestResolveFgBatches(unittest.TestCase):
	def test_direct_batch_takes_the_line_stock_qty(self):
		row = _si_row(1, "FG10005", 449, batch_no="AAO-007")
		self.assertEqual(report._resolve_fg_batches(row, {}), [("AAO-007", 449.0)])

	def test_bundle_splits_the_line_per_batch(self):
		row = _si_row(4, "FG10008", 409, bundle="B1")
		bundles = {"B1": [{"batch_no": "OAA-009", "qty": -405}, {"batch_no": "AAA-004", "qty": -4}]}
		self.assertEqual(
			report._resolve_fg_batches(row, bundles),
			[("OAA-009", 405.0), ("AAA-004", 4.0)],
		)

	def test_delivery_note_bundle_is_scaled_to_the_invoiced_qty(self):
		# The invoice bills 200 of a 449-carton delivery: the DN bundle carries
		# the delivered qty, so the sold qty is scaled to what this line bills.
		row = _si_row(1, "FG10005", 200, bundle="DN-B1")
		bundles = {"DN-B1": [{"batch_no": "AAO-007", "qty": -449}]}
		self.assertEqual(report._resolve_fg_batches(row, bundles), [("AAO-007", 200.0)])

	def test_same_batch_twice_in_a_bundle_is_one_batch(self):
		row = _si_row(1, "FG10005", 10, bundle="B2")
		bundles = {"B2": [{"batch_no": "AAO-007", "qty": -6}, {"batch_no": "AAO-007", "qty": -4}]}
		self.assertEqual(report._resolve_fg_batches(row, bundles), [("AAO-007", 10.0)])

	def test_no_batch_information(self):
		self.assertEqual(report._resolve_fg_batches(_si_row(1, "FG10005", 10), {}), [(None, None)])
		row = _si_row(1, "FG10005", 10, bundle="EMPTY")
		self.assertEqual(report._resolve_fg_batches(row, {"EMPTY": []}), [(None, None)])


class TestApportionmentFactor(unittest.TestCase):
	def test_sold_share_of_the_batch(self):
		self.assertAlmostEqual(report._apportionment_factor(449, 460, 193, 193), 449 / 460)

	def test_fully_sold_batch_is_one(self):
		self.assertAlmostEqual(report._apportionment_factor(407, 407, 407, 407), 1.0)

	def test_work_order_output_split_over_two_batches(self):
		# 300 of the order's 400 cartons went into this batch, all 300 were sold
		self.assertAlmostEqual(report._apportionment_factor(300, 300, 300, 400), 0.75)

	def test_unknown_quantities_give_none(self):
		self.assertIsNone(report._apportionment_factor(None, 460, 193, 193))
		self.assertIsNone(report._apportionment_factor(449, None, 193, 193))
		self.assertIsNone(report._apportionment_factor(449, 0, 193, 193))

	def test_missing_work_order_output_falls_back_to_the_batch_share(self):
		self.assertAlmostEqual(report._apportionment_factor(449, 460, None, None), 449 / 460)

	def test_apportion_keeps_unknowns_blank(self):
		self.assertIsNone(report._apportion(None, 0.5))
		self.assertIsNone(report._apportion(10, None))
		self.assertAlmostEqual(report._apportion(10, 0.5), 5.0)


class GetDataHarness(unittest.TestCase):
	"""Runs get_data with every database read replaced."""

	def run_report(self, si_items, bundles, wo_map, produced, rm_map):
		with patch.object(report, "_fetch_si_items", return_value=si_items), patch.object(
			report, "_fetch_bundle_entries", return_value=bundles
		), patch.object(report, "_fetch_manufacture_entries", return_value=wo_map), patch.object(
			report, "_fetch_batch_produced_qty", return_value=produced
		), patch.object(report, "_fetch_rm_consumption", return_value=rm_map), patch.object(
			report, "_fetch_pr_details", return_value={}
		), patch.object(report, "_fetch_pr_item_qty", return_value={}), patch.object(
			report, "_fetch_batch_balance", return_value={}
		):
			return report.get_data(FILTERS)


class TestApportionedRows(GetDataHarness):
	def test_batch_made_by_two_work_orders_and_partly_sold(self):
		# AAO-007: 193 + 267 = 460 produced, 449 sold on the line
		rows = self.run_report(
			si_items=[_si_row(1, "FG10005", 449, bundle="B1")],
			bundles={"B1": [{"batch_no": "AAO-007", "qty": -449}]},
			wo_map={("FG10005", "AAO-007"): [_wo_entry("WO-27", "SE-170", 193), _wo_entry("WO-28", "SE-177", 267)]},
			produced={("FG10005", "AAO-007"): 460.0},
			rm_map={
				"WO-27": [_rm("RM20003", 147.91, 13.0), _rm("RM20001", 20, 7.5)],
				"WO-28": [_rm("RM20003", 187, 12.0)],
			},
		)
		self.assertEqual(len(rows), 3)  # one row per raw-material line, as before
		share = 449 / 460
		for r in rows:
			self.assertEqual(r.batch_sold_qty, 449.0)
			self.assertEqual(r.batch_produced_qty, 460.0)
			self.assertAlmostEqual(r.apportioned_qty, r.consumed_qty * share)
			self.assertAlmostEqual(r.apportioned_cost, r.consumed_cost * share)
		# the apportioned total is what the delivery was valued at: sold qty at
		# the batch's average cost per carton
		whole = sum(r.consumed_cost for r in rows)
		self.assertAlmostEqual(sum(r.apportioned_cost for r in rows), 449 * whole / 460)

	def test_line_drawn_from_two_batches(self):
		# 409 cartons: 405 from OAA-009 (fully sold) and 4 from AAA-004 (380 made)
		rows = self.run_report(
			si_items=[_si_row(4, "FG10008", 409, bundle="B4")],
			bundles={"B4": [{"batch_no": "OAA-009", "qty": -405}, {"batch_no": "AAA-004", "qty": -4}]},
			wo_map={
				("FG10008", "OAA-009"): [_wo_entry("WO-13", "SE-103", 405)],
				("FG10008", "AAA-004"): [_wo_entry("WO-04", "SE-030", 380)],
			},
			produced={("FG10008", "OAA-009"): 405.0, ("FG10008", "AAA-004"): 380.0},
			rm_map={"WO-13": [_rm("RM20006", 144, 13.5)], "WO-04": [_rm("RM20006", 128.44, 13.5)]},
		)
		by_batch = {r.fg_batch_no: r for r in rows}
		self.assertEqual(by_batch["OAA-009"].batch_sold_qty, 405.0)
		self.assertAlmostEqual(by_batch["OAA-009"].apportioned_cost, by_batch["OAA-009"].consumed_cost)
		self.assertEqual(by_batch["AAA-004"].batch_sold_qty, 4.0)
		self.assertAlmostEqual(by_batch["AAA-004"].apportioned_qty, 128.44 * 4 / 380)
		self.assertAlmostEqual(by_batch["AAA-004"].apportioned_cost, 128.44 * 13.5 * 4 / 380)
		# the line's own Sales Qty is untouched
		self.assertTrue(all(r.sales_qty == 409 for r in rows))

	def test_work_order_that_booked_into_two_batches(self):
		# WO-9 made 400: 300 into batch X (sold 300) and 100 into batch Y (not on this invoice)
		rows = self.run_report(
			si_items=[_si_row(1, "FG10005", 300, bundle="B1")],
			bundles={"B1": [{"batch_no": "X", "qty": -300}]},
			wo_map={("FG10005", "X"): [_wo_entry("WO-9", "SE-9", 300, wo_fg_qty=400)]},
			produced={("FG10005", "X"): 300.0},
			rm_map={"WO-9": [_rm("RM1", 100, 2.0)]},
		)
		self.assertEqual(len(rows), 1)
		self.assertAlmostEqual(rows[0].apportioned_qty, 75.0)
		self.assertAlmostEqual(rows[0].apportioned_cost, 150.0)

	def test_two_manufacture_entries_into_one_batch_do_not_double_count(self):
		# WO-5 closed twice into the same batch (200 + 100); the report lists its
		# consumption once per entry, the apportioned figures add up to one share.
		rows = self.run_report(
			si_items=[_si_row(1, "FG10005", 300, bundle="B1")],
			bundles={"B1": [{"batch_no": "X", "qty": -300}]},
			wo_map={
				("FG10005", "X"): [
					_wo_entry("WO-5", "SE-A", 200, wo_fg_qty=300),
					_wo_entry("WO-5", "SE-B", 100, wo_fg_qty=300),
				]
			},
			produced={("FG10005", "X"): 300.0},
			rm_map={"WO-5": [_rm("RM1", 90, 1.0)]},
		)
		self.assertEqual(len(rows), 2)
		self.assertAlmostEqual(sum(r.apportioned_qty for r in rows), 90.0)
		self.assertAlmostEqual(sum(r.consumed_qty for r in rows), 180.0)

	def test_batch_without_a_manufacture_entry_stays_blank(self):
		rows = self.run_report(
			si_items=[_si_row(1, "FG10005", 10, bundle="B1")],
			bundles={"B1": [{"batch_no": "BOUGHT-IN", "qty": -10}]},
			wo_map={},
			produced={},
			rm_map={},
		)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].batch_sold_qty, 10.0)
		self.assertIsNone(rows[0].batch_produced_qty)
		self.assertIsNone(rows[0].apportioned_qty)
		self.assertIsNone(rows[0].apportioned_cost)

	def test_line_without_a_batch_stays_blank(self):
		rows = self.run_report(si_items=[_si_row(1, "FG10005", 10)], bundles={}, wo_map={}, produced={}, rm_map={})
		self.assertEqual(len(rows), 1)
		self.assertIsNone(rows[0].fg_batch_no)
		self.assertIsNone(rows[0].batch_sold_qty)
		self.assertIsNone(rows[0].apportioned_qty)


class TestColumns(unittest.TestCase):
	def test_new_columns_sit_next_to_the_figures_they_qualify(self):
		names = [c["fieldname"] for c in report.get_columns()]
		self.assertEqual(
			names[names.index("fg_batch_no"):names.index("fg_batch_no") + 4],
			["fg_batch_no", "batch_sold_qty", "batch_produced_qty", "work_order"],
		)
		self.assertEqual(
			names[names.index("consumed_qty"):names.index("consumed_qty") + 5],
			["consumed_qty", "consumed_cost", "apportioned_qty", "apportioned_cost", "rm_batch_no"],
		)

	def test_no_existing_column_was_removed(self):
		names = [c["fieldname"] for c in report.get_columns()]
		for expected in (
			"company", "sales_invoice", "posting_date", "customer", "customer_name", "currency",
			"si_item_idx", "fg_item_code", "fg_item_name", "fg_description", "sales_qty", "sales_uom",
			"stock_qty", "fg_net_weight", "fg_gross_weight", "fg_weight_uom", "fg_total_volume",
			"fg_volume_uom", "item_group", "fg_batch_no", "work_order", "wo_item", "wo_qty",
			"manufacturing_date", "manufacture_entry", "rm_item_code", "rm_item_name", "rm_description",
			"rm_uom", "consumed_qty", "consumed_cost", "rm_batch_no", "purchase_receipt",
			"purchase_receipt_date", "supplier_name", "pr_qty", "balance_stock", "customs_document_no",
		):
			self.assertIn(expected, names)


def _report_row(**kw):
	row = frappe._dict(
		company="Isnack",
		sales_invoice="SINV-1",
		posting_date="2026-08-27",
		customer="C",
		customer_name="Customer",
		currency="EUR",
		si_item_idx=1,
		fg_item_code="FG10005",
		fg_item_name="Lentil Squares",
		sales_qty=449.0,
		sales_uom="Carton",
		fg_batch_no="AAO-007",
		batch_sold_qty=449.0,
		batch_produced_qty=460.0,
		work_order="WO-27",
		manufacturing_date="2026-08-21",
		rm_item_code="RM20003",
		rm_item_name="Pellets",
		consumed_qty=147.91,
		consumed_cost=1924.99,
		apportioned_qty=144.373,
		apportioned_cost=1878.958,
		rm_batch_no="512806015",
		purchase_receipt="PR-1",
		purchase_receipt_date="2026-03-19",
		supplier_name="Snack Creations",
		pr_qty=420.0,
		balance_stock=None,
		customs_document_no="SA 651180",
	)
	row.update(kw)
	return row


class TestPrintAndExcelCarryTheColumns(unittest.TestCase):
	def test_print_context_has_the_new_fields(self):
		captured = {}

		def render(template, context):
			captured.update(context)
			return "<html></html>"

		with patch.object(report, "get_data", return_value=[_report_row()]), patch.object(
			report, "_fetch_si_header_details", return_value={}
		), patch("frappe.render_template", side_effect=render):
			report.get_print_html(FILTERS)

		fg = captured["invoices"][0]["fg_items"][0]
		self.assertEqual(fg["batch_sold_qty"], "449.0")
		self.assertEqual(fg["batch_produced_qty"], "460.0")
		row = captured["invoices"][0]["rows"][0]
		self.assertEqual(row["consumed_qty"], "147.91")
		self.assertEqual(row["apportioned_qty"], "144.37")

	def test_print_template_lists_the_new_headings(self):
		import os

		path = os.path.join(os.path.dirname(report.__file__), "customs_export_traceability_report_print.html")
		with open(path) as f:
			template = f.read()
		for heading in ("Batch Sold Qty", "Batch Produced Qty", "Apportioned Qty"):
			self.assertIn(heading, template)
		self.assertIn('<th colspan="5" class="col-group-rm">', template)

	def test_excel_export_adds_the_columns_without_dropping_any(self):
		from openpyxl import load_workbook

		with patch.object(report, "get_data", return_value=[_report_row()]), patch.object(
			report, "_fetch_si_header_details", return_value={}
		):
			out = report.get_export_excel(FILTERS)

		ws = load_workbook(BytesIO(base64.b64decode(out["file_content"]))).active
		headers = [[c.value for c in r] for r in ws.iter_rows()]
		fg_header = next(h for h in headers if h[0] == "#")
		rm_header = next(h for h in headers if h[0] == "RM Item Code")
		self.assertEqual(
			fg_header[:15],
			["#", "FG Item Code", "FG Item Name", "Sold Qty", "UOM", "Net Weight", "Gross Weight",
			 "Weight UOM", "Total Volume", "Volume UOM", "FG Batch No", "Batch Sold Qty",
			 "Batch Produced Qty", "Work Order", "Mfg Date"],
		)
		self.assertEqual(
			rm_header[:11],
			["RM Item Code", "RM Item Name", "Consumed Qty", "Apportioned Qty", "RM Batch No",
			 "Purchase Receipt", "PR Date", "Supplier Name", "PR Qty", "Balance Stock", "Customs Doc No"],
		)
		fg_row = next(h for h in headers if h[0] == 1)
		self.assertEqual(fg_row[10:13], ["AAO-007", 449.0, 460.0])
		rm_row = next(h for h in headers if h[0] == "RM20003")
		self.assertEqual(rm_row[2], 147.91)
		self.assertAlmostEqual(rm_row[3], 144.373)
		self.assertEqual(rm_row[4], "512806015")


if __name__ == "__main__":
	unittest.main()
