# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""A tasting's Batch No is a finished good's batch (2026-11) (no database)."""

import json
import os
import shutil
import subprocess
import unittest
from unittest.mock import patch

import frappe

from isnack.isnack.doctype.qc_tasting_record import qc_tasting_record
from isnack.isnack.doctype.qc_tasting_record.qc_tasting_record import (
	finished_good_batches,
	finished_good_made,
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
		self._check(_Record(amended_from="QCF-2026-00000", batch_no="RMB-0201"), records={"QCF-2026-00000": {"batch_no": "RMB-0201"}})
		with self.assertRaises(frappe.ValidationError):
			self._check(_Record(amended_from="QCF-2026-00000", batch_no="RMB-0201"), records={"QCF-2026-00000": {"batch_no": "FGB-0101"}})

	def test_only_the_batch_as_it_is_stored_is_kept(self):
		# Frappe gives a batch there is its own spelling before validate: one
		# spelled otherwise names none (a leading space, a tab), and is refused
		for batch in (" rmb-0201", "RMB-0201\t", " FGB-0101"):
			with self.subTest(batch=batch), self.assertRaisesRegex(frappe.LinkValidationError, "Could not find Batch"):
				self._check(_Record(saved=True, batch_no=batch), records={"QCF-2026-00001": {"batch_no": batch.strip().upper()}})
			with self.subTest(amends=batch), self.assertRaisesRegex(frappe.LinkValidationError, "Could not find Batch"):
				self._check(
					_Record(amended_from="QCF-2026-00000", batch_no=batch),
					records={"QCF-2026-00000": {"batch_no": batch.strip().upper()}},
				)
		# a batch there is not, kept or not, as Frappe refuses a Link to none
		with self.assertRaisesRegex(frappe.LinkValidationError, "Could not find Batch .*GONE-1"):
			self._check(_Record(saved=True, batch_no="GONE-1"), records={"QCF-2026-00001": {"batch_no": "GONE-1"}})

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


class TestTheFinishedGoodMade(unittest.TestCase):
	def _made(self, details):
		with patch.object(qc_tasting_record, "get_work_order_details", return_value=details) as read, patch.object(
			qc_tasting_record, "finished_goods", return_value=["FG-0001", "FG-0002"]
		):
			return finished_good_made("MFG-WO-2026-00090"), read

	def test_the_finished_good_a_work_order_makes(self):
		made, read = self._made({"factory_line": "FRYING", "production_item": "FG-0001"})
		self.assertEqual(made, "FG-0001")
		read.assert_called_once_with("MFG-WO-2026-00090")
		self.assertIn(finished_good_made, frappe.whitelisted)

	def test_none_for_another_item_or_a_work_order_not_read(self):
		# another item: any finished good's batch; none there, or not the user's to pick
		self.assertEqual(self._made({"factory_line": "FRYING", "production_item": "RM-0001"})[0], "")
		self.assertEqual(self._made({})[0], "")


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
			"frappe.get_all", return_value=[("FGB-0101", "FG-0001", "2026-01-15")]
		) as get_all:
			found = finished_good_batches("Batch", txt, "name", 0, 20, filters or {})
		return found, get_all

	def test_the_batches_of_finished_goods_newest_first(self):
		found, get_all = self._search(txt="tst")
		self.assertEqual(found, [("FGB-0101", "FG-0001", "2026-01-15")])
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
		with open(LINES_JS) as fh:
			lines = fh.read()
		self.assertIn(f'query: "{QUERY}"', lines)
		self.assertIn(f'"{qc_tasting_record.__name__}.{finished_good_made.__name__}"', lines)
		for path in (FORM_JS, os.path.join(APP_DIR, "isnack", "page", "quality_hub", "quality_hub.js")):
			with open(path) as fh:
				script = fh.read()
			# the query, and a batch of another product taken off when the Work Order changes
			self.assertIn("lines.tasting_batch_query(", script.replace("isnack.quality_hub_lines.", "lines."), path)
			self.assertIn("lines.tasting_work_order_changed(", script, path)


FORM_JS = os.path.join(APP_DIR, "isnack", "doctype", "qc_tasting_record", "qc_tasting_record.js")
LINES_JS = os.path.join(APP_DIR, "public", "js", "quality_hub_lines.js")


@unittest.skipUnless(shutil.which("node"), "needs node to run the scripts")
class TestTheScripts(unittest.TestCase):
	"""quality_hub_lines.js and the tasting form's script, run on a fake desk:
	the Batch No's search and the note under it, and a batch of another product
	taken off when the Work Order is picked (the Quality Hub's Tasting dialog
	uses the same, through setup_tasting_batch)."""

	def _run(self, body):
		with open(LINES_JS) as fh:
			lines = fh.read()
		with open(FORM_JS) as fh:
			form = fh.read()
		harness = (
			"const __ = (msg, args) => msg.replace(/\\{(\\d)\\}/g, (_m, i) => args[i]);\n"
			"const handlers = {};\n"
			"const calls = [], alerts = [];\n"
			"// the finished good each Work Order makes: '' for a semi-finished one\n"
			"const made = {'WO-A': 'FG-A', 'WO-B': 'FG-B', 'WO-SFG': ''};\n"
			"let failing = [];\n"
			"const frappe = {\n"
			"  provide: (path) => { let o = globalThis; path.split('.').forEach((p) => { o[p] = o[p] || {}; o = o[p]; }); },\n"
			"  xcall: (method, args) => {\n"
			"    const name = method.split('.').pop(); calls.push([name, args && args.work_order]);\n"
			"    if (failing.includes(args && args.work_order)) return Promise.reject(new Error('no'));\n"
			"    if (name === 'finished_good_made') return Promise.resolve(made[args.work_order] || '');\n"
			"    return Promise.resolve({});\n"
			"  },\n"
			"  show_alert: (a) => alerts.push([a.message, a.indicator]),\n"
			"  ui: {form: {on: (doctype, h) => { (handlers[doctype] = handlers[doctype] || []).push(h); }}},\n"
			"  model: {set_value: () => {}},\n"
			"};\n"
			"const flt = Number, locals = {};\n"
			f"{lines}\n"
			f"{form}\n"
			"const lines = isnack.quality_hub_lines;\n"
			"const flush = async () => { for (let i = 0; i < 5; i++) await new Promise((r) => setTimeout(r, 0)); };\n"
			"const record = (values) => ({values, log: [], alive_: true,\n"
			"  get(f) { return values[f]; }, set(f, v) { this.log.push([f, v]); values[f] = v; },\n"
			"  has: (f) => ['work_order', 'batch_no', 'item_code'].includes(f), alive() { return this.alive_; }});\n"
			"(async () => {\n"
			"  const out = {};\n"
			f"{body}\n"
			"  console.log(JSON.stringify(out));\n"
			"})();\n"
		)
		run = subprocess.run(["node", "-e", harness], capture_output=True, text=True)
		self.assertEqual(run.returncode, 0, run.stderr[-2000:])
		return json.loads(run.stdout)

	def test_the_search_and_the_note_under_it(self):
		out = self._run(
			"  const df = {};\n"
			"  out.none = lines.tasting_batch_query('', df); out.none_note = df.filter_description;\n"
			"  // a Work Order not read yet: read now, for the next search\n"
			"  out.unread = lines.tasting_batch_query('WO-A', df); out.unread_note = df.filter_description;\n"
			"  await flush();\n"
			"  out.read = lines.tasting_batch_query('WO-A', df); out.read_note = df.filter_description;\n"
			"  // one making a semi-finished good: every finished good's batches, the server says\n"
			"  lines.tasting_batch_query('WO-SFG', df); await flush();\n"
			"  out.sfg = lines.tasting_batch_query('WO-SFG', df); out.sfg_note = df.filter_description;\n"
			"  out.calls = calls.slice();\n"
		)
		query = f"{qc_tasting_record.__name__}.{finished_good_batches.__name__}"
		self.assertEqual((out["none"], out["none_note"]), ({"query": query, "filters": {}}, "Batches of finished goods"))
		# the server narrows it already; the note says so once the Work Order is read
		self.assertEqual(out["unread"], {"query": query, "filters": {"work_order": "WO-A"}})
		self.assertEqual(out["unread_note"], "Batches of finished goods")
		self.assertEqual(out["read"], out["unread"])
		self.assertEqual(out["read_note"], "Batches of the item Work Order WO-A makes")
		self.assertEqual(out["sfg"], {"query": query, "filters": {"work_order": "WO-SFG"}})
		self.assertEqual(out["sfg_note"], "Batches of finished goods")
		# each Work Order read once
		self.assertEqual(out["calls"], [["finished_good_made", "WO-A"], ["finished_good_made", "WO-SFG"]])

	def test_a_batch_of_another_product_is_taken_off(self):
		out = self._run(
			"  // a batch of FG-A, then a Work Order making FG-B: taken off, and the user told\n"
			"  const other = record({work_order: 'WO-B', batch_no: 'B-1', item_code: 'FG-A'});\n"
			"  await lines.tasting_work_order_changed(other);\n"
			"  // a batch of the finished good it makes: kept\n"
			"  const same = record({work_order: 'WO-A', batch_no: 'B-1', item_code: 'FG-A'});\n"
			"  await lines.tasting_work_order_changed(same);\n"
			"  // a Work Order making a semi-finished good: any finished good's batch, kept\n"
			"  const sfg = record({work_order: 'WO-SFG', batch_no: 'B-1', item_code: 'FG-A'});\n"
			"  await lines.tasting_work_order_changed(sfg);\n"
			"  // the batch or the Work Order picked again before the answer came: left to that pick\n"
			"  const rebatched = record({work_order: 'WO-C', batch_no: 'B-1', item_code: 'FG-A'}); made['WO-C'] = 'FG-C';\n"
			"  const pending = lines.tasting_work_order_changed(rebatched);\n"
			"  rebatched.values.batch_no = 'B-3'; rebatched.values.item_code = 'FG-C'; await pending;\n"
			"  const repicked = record({work_order: 'WO-D', batch_no: 'B-1', item_code: 'FG-A'}); made['WO-D'] = 'FG-D';\n"
			"  const repicking = lines.tasting_work_order_changed(repicked); repicked.values.work_order = 'WO-A'; await repicking;\n"
			"  // a dialog saved and closed meanwhile\n"
			"  const closed = record({work_order: 'WO-E', batch_no: 'B-1', item_code: 'FG-A'}); made['WO-E'] = 'FG-E';\n"
			"  const closing = lines.tasting_work_order_changed(closed); closed.alive_ = false; await closing;\n"
			"  // no batch yet (the Work Order read all the same), no Work Order, one that cannot be read\n"
			"  const empty = record({work_order: 'WO-F', batch_no: '', item_code: ''}); made['WO-F'] = 'FG-F';\n"
			"  await lines.tasting_work_order_changed(empty);\n"
			"  await lines.tasting_work_order_changed(record({work_order: '', batch_no: 'B-1', item_code: 'FG-A'}));\n"
			"  failing = ['WO-SECRET'];\n"
			"  const secret = record({work_order: 'WO-SECRET', batch_no: 'B-1', item_code: 'FG-A'});\n"
			"  await lines.tasting_work_order_changed(secret); await lines.tasting_work_order_changed(secret);\n"
			"  out.set = [other, same, sfg, rebatched, repicked, closed, empty, secret].map((r) => r.log);\n"
			"  out.alerts = alerts;\n"
			"  out.read = calls.map((c) => c[1]);\n"
			"  out.known = lines.finished_goods_made;\n"
		)
		self.assertEqual(out["set"], [[["batch_no", ""], ["item_code", ""]], [], [], [], [], [], [], []])
		self.assertEqual(
			out["alerts"],
			[["Batch B-1 is of FG-A, not of FG-B, which Work Order WO-B makes: pick a batch of it.", "orange"]],
		)
		# each read once; one that could not be, asked again next time
		self.assertEqual(out["read"], ["WO-B", "WO-A", "WO-SFG", "WO-C", "WO-D", "WO-E", "WO-F", "WO-SECRET", "WO-SECRET"])
		self.assertEqual(out["known"]["WO-F"], "FG-F")

	def test_the_form(self):
		out = self._run(
			"  const form = (doc) => {\n"
			"    const fields_dict = {batch_no: {df: {}}, item_code: {df: {}}, work_order: {df: {}}, scores: {$wrapper: {addClass: () => {}}}};\n"
			"    const frm = {doctype: 'QC Tasting Record', doc, queries: {}, set: [], fields_dict, is_new: () => false,\n"
			"      set_query: (f, q) => { frm.queries[f] = q; },\n"
			"      set_value: (f, v) => { frm.set.push([f, v]); frm.doc[f] = v; }};\n"
			"    return frm;\n"
			"  };\n"
			"  // the form script's own handlers (quality_hub_lines.js adds the line's)\n"
			"  const own = handlers['QC Tasting Record'].find((h) => h.refresh);\n"
			"  const saved = form({work_order: 'WO-A', batch_no: 'B-1', item_code: 'FG-A'});\n"
			"  own.setup(saved); own.onload(saved); await flush();\n"
			"  out.query = saved.queries.batch_no(); out.note = saved.fields_dict.batch_no.df.filter_description;\n"
			"  saved.doc.work_order = 'WO-B'; own.work_order(saved); await flush();\n"
			"  out.set = saved.set; out.alerts = alerts;\n"
			"  const fresh = form({}); own.setup(fresh); own.onload(fresh);\n"
			"  out.fresh_note = (fresh.queries.batch_no(), fresh.fields_dict.batch_no.df.filter_description);\n"
			"  out.calls = calls.slice();\n"
		)
		self.assertEqual(out["query"]["filters"], {"work_order": "WO-A"})
		# read on load: the note names the Work Order at the first search
		self.assertEqual(out["note"], "Batches of the item Work Order WO-A makes")
		self.assertEqual(out["set"], [["batch_no", ""], ["item_code", ""]])
		self.assertEqual(len(out["alerts"]), 1)
		self.assertEqual(out["fresh_note"], "Batches of finished goods")
		self.assertEqual(out["calls"], [["finished_good_made", "WO-A"], ["finished_good_made", "WO-B"]])

	def test_a_desk_loaded_before_the_rule(self):
		# the shared script as it was: no tasting helpers; the form still works
		out = self._run(
			"  delete lines.tasting_batch_query;\n"
			"  const frm = {doc: {work_order: 'WO-A', batch_no: 'B-1', item_code: 'FG-B'}, queries: {},\n"
			"    fields_dict: {batch_no: {df: {}}}, set_query: (f, q) => { frm.queries[f] = q; }, set_value: () => {}};\n"
			"  const own = handlers['QC Tasting Record'].find((h) => h.refresh);\n"
			"  own.setup(frm); own.onload(frm); own.work_order(frm); await flush();\n"
			"  out.query = frm.queries.batch_no(); out.calls = calls.slice(); out.alerts = alerts;\n"
		)
		self.assertEqual((out["query"], out["calls"], out["alerts"]), ({}, [], []))
