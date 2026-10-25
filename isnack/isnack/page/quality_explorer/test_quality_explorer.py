# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""Unit tests for the Quality Explorer (pure mocks)."""

import unittest
from unittest.mock import patch

import frappe
from isnack.isnack.page.quality_explorer import quality_explorer as qe

# fields each QC doctype has that decide how a record is found
LINK_FIELDS = {
	"QC Receiving Record": {"batch_no", "item_code", "supplier", "overall_status"},
	"QC Puffs Extruder Record": {"work_order", "product_item", "overall_status"},
	"QC Rice Extruder Record": {"work_order", "product_item", "overall_status"},
	"QC Frying Line Record": {"work_order", "product_item", "overall_status"},
	"QC Oven Record": {"work_order", "product_item", "overall_status"},
	"QC Tasting Record": {"work_order", "batch_no", "item_code", "overall_status"},
	"QC Packaging Check": {"work_order", "variance_acceptable"},
	"QC Metal Detector Log": {"work_order", "all_tests_passed"},
	"QC Weight Check": {"work_order", "batch_no", "item_code", "overall_status"},
}


class _Meta:
	def __init__(self, fields):
		self.fields = set(fields) | {"record_date", "shift", "operator_name", "qc_inspector"}

	def has_field(self, fieldname):
		return fieldname in self.fields


def _meta(doctype):
	return _Meta(LINK_FIELDS.get(doctype, ()))


def _rec(name, docstatus=1, **kw):
	d = frappe._dict(name=name, docstatus=docstatus, record_date="2026-10-20", shift="Morning")
	d.update(kw)
	return d


def _material(item_code, batch_no=None, rows=("R1",)):
	return {
		"item_code": item_code,
		"item_name": item_code.lower(),
		"batch_no": batch_no,
		"lines": [{"row": r} for r in rows],
	}


def _read(wo):
	return {"submitted": [wo], "rows_by_entry": {}, "bundle_map": {}, "hidden": 0, "entries": []}


EMPTY_TRACE = {"batches": {}, "runs": {}, "hint": None}


class TestResult(unittest.TestCase):
	def test_overall_status_levels(self):
		self.assertEqual(qe._result(_rec("A", overall_status="Pass")), ("Pass", "pass"))
		self.assertEqual(qe._result(_rec("A", overall_status="Accepted")), ("Accepted", "pass"))
		self.assertEqual(qe._result(_rec("A", overall_status="Marginal")), ("Marginal", "warn"))
		self.assertEqual(
			qe._result(_rec("A", overall_status="Conditionally Accepted")), ("Conditionally Accepted", "warn")
		)
		self.assertEqual(qe._result(_rec("A", overall_status="Rejected")), ("Rejected", "fail"))
		self.assertEqual(qe._result(_rec("A", overall_status="Fail")), ("Fail", "fail"))

	def test_pass_flags_stand_in_for_overall_status(self):
		self.assertEqual(qe._result(_rec("H", all_tests_passed=1))[1], "pass")
		self.assertEqual(qe._result(_rec("H", all_tests_passed=0))[1], "fail")
		self.assertEqual(qe._result(_rec("G", variance_acceptable=1))[1], "pass")
		self.assertEqual(qe._result(_rec("G", variance_acceptable=0))[1], "fail")

	def test_no_result_yet(self):
		# a process record whose Overall Status nobody set has no result, not a pass
		self.assertEqual(qe._result(_rec("B", overall_status="")), (None, None))
		self.assertEqual(qe._result(_rec("B")), (None, None))


class TestRelations(unittest.TestCase):
	SCOPE = {
		"batches": {"FG-1": qe.REL_THIS_BATCH},
		"work_orders": {"WO-1": qe.REL_WORK_ORDER},
	}
	TRACE = {
		"batches": {"RM-B1": {"item_code": "RM1", "item_name": "Corn", "work_orders": ["WO-1", "WO-S"]}},
		"runs": {"WO-S": {"item_code": "SFG1", "for_work_order": "WO-1"}},
		"hint": None,
	}

	def test_every_route_is_named(self):
		rel = qe._relations(_rec("QCI-1", batch_no="FG-1", work_order="WO-1"), self.SCOPE, self.TRACE)
		self.assertEqual(
			rel,
			[
				{"key": qe.REL_THIS_BATCH, "detail": "FG-1"},
				{"key": qe.REL_WORK_ORDER, "detail": "WO-1"},
			],
		)

	def test_ingredient_and_semi_finished_routes(self):
		rel = qe._relations(_rec("QCA-1", batch_no="RM-B1"), self.SCOPE, self.TRACE)
		self.assertEqual([r["key"] for r in rel], [qe.REL_INGREDIENT])
		self.assertIn("WO-1, WO-S", rel[0]["detail"])

		rel = qe._relations(_rec("QCB-1", work_order="WO-S"), self.SCOPE, self.TRACE)
		self.assertEqual([r["key"] for r in rel], [qe.REL_SEMI_FINISHED])
		self.assertIn("SFG1", rel[0]["detail"])

	def test_unlinked_fields_relate_to_nothing(self):
		self.assertEqual(qe._relations(_rec("QCH-1", work_order=None), self.SCOPE, self.TRACE), [])


class TestIngredientTrace(unittest.TestCase):
	@patch("frappe.has_permission", return_value=False)
	def test_no_stock_entry_read_skips_the_trace(self, _perm):
		out = qe._ingredient_trace(["WO-1"])
		self.assertEqual((out["batches"], out["runs"]), ({}, {}))
		self.assertTrue(out["hint"])

	def test_no_work_orders_no_hint(self):
		self.assertEqual(qe._ingredient_trace([]), EMPTY_TRACE)

	@patch("isnack.isnack.page.quality_explorer.quality_explorer.qty_tick", return_value=0.001)
	@patch("isnack.utils.batch_lineage.pool_sources")
	@patch("isnack.utils.batch_lineage.manufactured_items")
	@patch("isnack.utils.batch_lineage.consumed_materials")
	@patch("isnack.isnack.page.batch_explorer.batch_explorer._read_work_order", side_effect=_read)
	@patch("frappe.has_permission", return_value=True)
	def test_batches_and_semi_finished_runs(self, _perm, read_wo, consumed, made, sources, _tick):
		materials = {
			"WO-1": [
				_material("RM1", "RM-B1"),
				_material("SFG1", rows=("R-SFG",)),
				_material("WATER", rows=("R-W",)),
			],
			# the corn mix run consumed corn, and also the same oil batch as WO-1
			"WO-S": [_material("RM2", "RM-B2"), _material("RM1", "RM-B1")],
		}
		consumed.side_effect = lambda submitted, *_a: materials.get(submitted[0], [])
		made.side_effect = lambda codes: {"SFG1"} & set(codes)
		sources.side_effect = lambda rows, _tick: (
			{"R-SFG": {"work_orders": [{"work_order": "WO-S", "qty": 5}], "other": []}} if "R-SFG" in rows else {}
		)

		out = qe._ingredient_trace(["WO-1"])

		self.assertEqual(sorted(out["batches"]), ["RM-B1", "RM-B2"])
		self.assertEqual(out["batches"]["RM-B1"]["work_orders"], ["WO-1", "WO-S"])
		self.assertEqual(out["batches"]["RM-B2"]["work_orders"], ["WO-S"])
		self.assertEqual(out["runs"], {"WO-S": {"item_code": "SFG1", "for_work_order": "WO-1"}})
		self.assertIsNone(out["hint"])
		# water is not made by any Work Order: the trace ends there
		self.assertEqual(sources.call_args_list[0].args[0], ["R-SFG"])

	@patch("isnack.isnack.page.quality_explorer.quality_explorer.qty_tick", return_value=0.001)
	@patch("isnack.utils.batch_lineage.pool_sources")
	@patch("isnack.utils.batch_lineage.manufactured_items", side_effect=lambda codes: set(codes))
	@patch("isnack.utils.batch_lineage.consumed_materials")
	@patch("isnack.isnack.page.batch_explorer.batch_explorer._read_work_order", side_effect=_read)
	@patch("frappe.has_permission", return_value=True)
	def test_depth_cap_and_cycle_guard(self, _perm, _read_wo, consumed, _made, sources, _tick):
		# WO-1 <- S1 <- S2 <- S3 <- S4, and S2 also claims WO-1 as a source
		chain = {"WO-1": "S1", "S1": "S2", "S2": "S3", "S3": "S4", "S4": "S5"}
		consumed.side_effect = lambda submitted, *_a: [_material("SFG", rows=(f"R-{submitted[0]}",))]

		def pools(rows, _tick):
			wo = rows[0][2:]
			runs = [{"work_order": chain[wo], "qty": 1}]
			if wo == "S2":
				runs.append({"work_order": "WO-1", "qty": 1})
			return {rows[0]: {"work_orders": runs, "other": []}}

		sources.side_effect = pools

		out = qe._ingredient_trace(["WO-1"])

		self.assertEqual(list(out["runs"]), ["S1", "S2", "S3"])
		self.assertEqual(out["runs"]["S3"]["for_work_order"], "S2")

	@patch("isnack.utils.batch_lineage.consumed_materials", return_value=[])
	@patch("isnack.isnack.page.batch_explorer.batch_explorer._read_work_order", side_effect=_read)
	@patch("frappe.has_permission", return_value=True)
	def test_traced_work_orders_are_capped(self, _perm, read_wo, _consumed):
		wos = [f"WO-{i:02d}" for i in range(qe.MAX_TRACED_WORK_ORDERS + 2)]
		out = qe._ingredient_trace(wos)
		self.assertEqual(read_wo.call_count, qe.MAX_TRACED_WORK_ORDERS)
		self.assertIn(str(len(wos)), out["hint"])


class TestReadRecords(unittest.TestCase):
	@patch("frappe.get_list")
	@patch("frappe.get_meta", side_effect=_meta)
	@patch("frappe.has_permission")
	def test_filters_follow_each_doctypes_link_fields(self, perm, _get_meta, get_list):
		perm.side_effect = lambda doctype, ptype: doctype != "QC Tasting Record"
		get_list.return_value = []

		records, hidden = qe._read_records(["FG-1", "RM-B1"], ["WO-1"])

		self.assertEqual(hidden, ["QCF"])
		self.assertNotIn("QCF", records)
		calls = {c.args[0]: c.kwargs for c in get_list.call_args_list}
		# receiving records name a batch only
		self.assertEqual(calls["QC Receiving Record"]["or_filters"], [["batch_no", "in", ["FG-1", "RM-B1"]]])
		self.assertEqual(calls["QC Puffs Extruder Record"]["or_filters"], [["work_order", "in", ["WO-1"]]])
		self.assertEqual(
			calls["QC Weight Check"]["or_filters"],
			[["batch_no", "in", ["FG-1", "RM-B1"]], ["work_order", "in", ["WO-1"]]],
		)
		for kwargs in calls.values():
			self.assertEqual(kwargs["filters"], {"docstatus": ["<", 2]})
			self.assertEqual(kwargs["limit_page_length"], 0)
		self.assertIn("overall_status", calls["QC Receiving Record"]["fields"])
		self.assertNotIn("work_order", calls["QC Receiving Record"]["fields"])
		self.assertIn("all_tests_passed", calls["QC Metal Detector Log"]["fields"])

	@patch("frappe.get_list")
	@patch("frappe.get_meta", side_effect=_meta)
	@patch("frappe.has_permission", return_value=True)
	def test_no_work_orders_reads_batch_records_only(self, _perm, _get_meta, get_list):
		get_list.return_value = []
		records, _hidden = qe._read_records(["RM-B1"], [])
		read = [c.args[0] for c in get_list.call_args_list]
		self.assertEqual(read, ["QC Receiving Record", "QC Tasting Record", "QC Weight Check"])
		self.assertEqual(records["QCB"], [])


class TestScopes(unittest.TestCase):
	@patch.object(qe, "_work_orders_named_on_records", return_value={"WO-NAMED", "WO-P"})
	@patch("isnack.isnack.page.batch_explorer.batch_explorer._batch_roles")
	@patch("isnack.isnack.page.batch_explorer.batch_explorer._stock_entry_info", return_value={})
	@patch("isnack.isnack.page.batch_explorer.batch_explorer._direct_vouchers", return_value={})
	@patch("isnack.isnack.page.batch_explorer.batch_explorer._load_batch")
	@patch("frappe.has_permission", return_value=True)
	def test_batch_scope_takes_producers_and_named_work_orders(self, _perm, load, _dv, _sei, roles, _named):
		load.return_value = frappe._dict(name="FG-1", item="FG10005")
		roles.return_value = {"WO-P": "producer", "WO-C": "consumer", "WO-H": "handler"}

		subject, scope = qe._batch_scope("FG-1")

		self.assertEqual(subject["kind"], "Batch")
		self.assertEqual(scope["batches"], {"FG-1": qe.REL_THIS_BATCH})
		# a consumer is downstream of the batch, a handler only moved it
		self.assertEqual(scope["work_order_roles"], {"WO-P": qe.WO_PRODUCED, "WO-NAMED": qe.WO_NAMED})
		self.assertEqual(set(scope["work_orders"].values()), {qe.REL_WORK_ORDER})

	@patch("frappe.has_permission", return_value=False)
	def test_batch_scope_needs_batch_read(self, _perm):
		with self.assertRaises(frappe.PermissionError):
			qe._batch_scope("FG-1")

	@patch("isnack.utils.batch_lineage.fg_batch_quantities_by_work_order")
	@patch("frappe.db.get_value")
	@patch("frappe.get_meta", return_value=_Meta({"custom_factory_line"}))
	@patch("frappe.has_permission", return_value=True)
	@patch("isnack.isnack.page.batch_explorer.batch_explorer._user_name", return_value="Jo")
	def test_work_order_scope_takes_its_output_batches(self, _user, _perm, _meta_, get_value, fg):
		get_value.return_value = frappe._dict(
			name="WO-1", production_item="FG1", item_name="Crisps", stock_uom="Carton",
			owner="jo@x", custom_factory_line="Line 2",
		)
		fg.return_value = {"WO-1": [("FG-1", 40.0), ("FG-2", 10.0)]}

		subject, scope = qe._work_order_scope("WO-1")

		self.assertEqual((subject["kind"], subject["item"], subject["line"]), ("Work Order", "FG1", "Line 2"))
		self.assertEqual(scope["batches"], {"FG-1": qe.REL_OUTPUT_BATCH, "FG-2": qe.REL_OUTPUT_BATCH})
		self.assertEqual(scope["work_orders"], {"WO-1": qe.REL_THIS_WORK_ORDER})
		self.assertEqual(scope["outputs"][0], {"batch_no": "FG-1", "qty": 40.0, "uom": "Carton"})


class TestGetQualityRecords(unittest.TestCase):
	def test_needs_exactly_one_subject(self):
		with self.assertRaises(frappe.ValidationError):
			qe.get_quality_records()
		with self.assertRaises(frappe.ValidationError):
			qe.get_quality_records(batch_no="FG-1", work_order="WO-1")

	@patch("isnack.isnack.page.batch_explorer.batch_explorer._build_nodes")
	@patch("isnack.isnack.page.batch_explorer.batch_explorer._user_names", return_value={"qa@x": "Quality Ann"})
	@patch.object(qe, "_read_records")
	@patch.object(qe, "_ingredient_trace")
	@patch.object(qe, "_batch_scope")
	def test_batch_dossier(self, scope, trace, read, _names, build_nodes):
		scope.return_value = (
			{"kind": "Batch", "name": "FG-1", "item": "FG10005"},
			{
				"batches": {"FG-1": qe.REL_THIS_BATCH},
				"work_orders": {"WO-1": qe.REL_WORK_ORDER},
				"work_order_roles": {"WO-1": qe.WO_PRODUCED},
				"outputs": [],
			},
		)
		trace.return_value = {
			"batches": {
				"RM-B1": {"item_code": "RM1", "item_name": "Corn", "work_orders": ["WO-1"]},
				"RM-B2": {"item_code": "RM2", "item_name": "Oil", "work_orders": ["WO-1"]},
			},
			"runs": {"WO-S": {"item_code": "SFG1", "for_work_order": "WO-1"}},
			"hint": None,
		}
		read.return_value = (
			{
				"QCA": [_rec("QCA-1", batch_no="RM-B1", overall_status="Accepted", qc_inspector="qa@x")],
				"QCB": [
					_rec("QCB-1", work_order="WO-1", product_item="FG10005", overall_status="Pass"),
					_rec("QCB-2", docstatus=0, work_order="WO-S", product_item="SFG1"),
				],
				"QCI": [_rec("QCI-1", batch_no="FG-1", work_order="WO-1", overall_status="Fail")],
				"QCH": [],
			},
			["QCF"],
		)
		build_nodes.side_effect = lambda _dt, names: [{"name": n, "status": "Completed"} for n in names]

		out = qe.get_quality_records(batch_no=" FG-1 ")

		scope.assert_called_once_with("FG-1")
		trace.assert_called_once_with(["WO-1"])
		batches, work_orders = read.call_args.args
		self.assertEqual(batches, ["FG-1", "RM-B1", "RM-B2"])
		self.assertEqual(work_orders, ["WO-1", "WO-S"])

		record_groups = [g for g in out["groups"] if g["code"]]
		self.assertEqual([g["code"] for g in record_groups], ["QCA", "QCB", "QCI"])
		qca = record_groups[0]["nodes"][0]
		self.assertEqual((qca["result_level"], qca["inspector_name"]), ("pass", "Quality Ann"))
		self.assertEqual([r["key"] for r in qca["relations"]], [qe.REL_INGREDIENT])
		qci = record_groups[2]["nodes"][0]
		self.assertEqual([r["key"] for r in qci["relations"]], [qe.REL_THIS_BATCH, qe.REL_WORK_ORDER])

		trace_groups = {g["key"]: g for g in out["groups"] if g.get("trace")}
		self.assertEqual(sorted(trace_groups), ["ingredients", "work_orders"])
		wo_nodes = {n["name"]: n for n in trace_groups["work_orders"]["nodes"]}
		self.assertEqual(wo_nodes["WO-1"]["tags"], [qe.WO_PRODUCED])
		self.assertEqual(wo_nodes["WO-1"]["qc_count"], 2)
		self.assertEqual(wo_nodes["WO-S"]["tags"], [qe.REL_SEMI_FINISHED])
		ing = {n["name"]: n for n in trace_groups["ingredients"]["nodes"]}
		self.assertEqual(ing["RM-B1"]["tags"], [qe.REL_INGREDIENT])
		# the oil batch went into the product with no receiving inspection on file
		self.assertEqual(ing["RM-B2"]["tags"], [qe.REL_INGREDIENT, "no_receiving_record"])

		coverage = {c["code"]: c["state"] for c in out["coverage"]}
		self.assertEqual(coverage["QCA"], "submitted")
		self.assertEqual(coverage["QCB"], "submitted")
		self.assertEqual(coverage["QCI"], "failed")
		self.assertEqual(coverage["QCF"], "hidden")
		self.assertEqual(coverage["QCH"], "missing")

		self.assertEqual(
			{k: out["summary"][k] for k in ("records", "submitted", "drafts", "failed", "work_orders", "ingredients")},
			{"records": 4, "submitted": 3, "drafts": 1, "failed": 1, "work_orders": 2, "ingredients": 2},
		)
		self.assertEqual(out["summary"]["hidden"], ["QCF"])

	@patch("isnack.isnack.page.batch_explorer.batch_explorer._build_nodes", return_value=[])
	@patch("isnack.isnack.page.batch_explorer.batch_explorer._user_names", return_value={})
	@patch.object(qe, "_read_records", return_value=({}, []))
	@patch.object(qe, "_ingredient_trace", return_value=EMPTY_TRACE)
	@patch.object(qe, "_work_order_scope")
	def test_work_order_dossier_lists_its_batches_not_itself(self, scope, _trace, _read, _names, build_nodes):
		scope.return_value = (
			{"kind": "Work Order", "name": "WO-1", "item": "FG1"},
			{
				"batches": {"FG-1": qe.REL_OUTPUT_BATCH},
				"work_orders": {"WO-1": qe.REL_THIS_WORK_ORDER},
				"work_order_roles": {"WO-1": qe.WO_SUBJECT},
				"outputs": [{"batch_no": "FG-1", "qty": 40.0, "uom": "Carton"}],
			},
		)

		out = qe.get_quality_records(work_order="WO-1")

		build_nodes.assert_not_called()
		self.assertEqual([g["key"] for g in out["groups"]], ["outputs"])
		node = out["groups"][0]["nodes"][0]
		self.assertEqual((node["name"], node["qty"], node["route"]), ("FG-1", 40.0, ["quality-explorer", "Batch", "FG-1"]))
		self.assertEqual(out["summary"]["work_orders"], 0)
		self.assertTrue(all(c["state"] == "missing" for c in out["coverage"]))
