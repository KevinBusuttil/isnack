"""Quality Explorer backend.

Given a Batch or a Work Order, list every QC record (QCA-QCI) that belongs to
it, say how each one does, and show which record types are missing.

What belongs to what
--------------------
A QC record names a batch (``batch_no``: receiving, tasting, weight checks), a
Work Order (``work_order``: every record type but receiving), or both. The
explorer collects the batches and Work Orders the subject stands for, then
reads every record that names one of them:

* Batch: the batch itself, the Work Orders that produced it (read off the
  stock ledger by the Batch Explorer's rules, ``batch_explorer._batch_roles``)
  and any Work Order the batch's own QC records name. A Work Order that has not
  booked its Manufacture entry yet is not on the ledger, but its weight and
  tasting records still name it.
* Work Order: the Work Order itself and the finished-goods batches its
  Manufacture entries made.
* Ingredients, for both: the raw-material batches those Work Orders consumed,
  whose receiving records belong to the product too, and the runs that made a
  semi-finished item they consumed (a corn mix), whose process records do. The
  trace follows ``batch_lineage`` like the Batch Explorer's production inputs,
  down to ``batch_explorer.MAX_SFG_DEPTH`` semi-finished levels.

Every record carries the relations that brought it in (``relations``), so a
record reached by two routes names both.

Permissions
-----------
A Batch needs read on that Batch and a Work Order read on that Work Order,
document-level so User Permissions apply; the Batch Explorer's raw reads then
resolve the Work Orders and batches. A QC
doctype the user may not read is left out and its code listed in
``summary.hidden``. Within a doctype, records are filtered the way the Batch
Explorer filters its production inputs: read raw, then kept only when
``frappe.get_list`` lets the user see them. The ones a User Permission keeps
from the user (on a line, an item, a supplier) are counted, so the page says
"hidden" where it would otherwise claim a record is missing. The ingredient
trace needs Stock Entry read, like the Batch Explorer's production inputs;
without it, or when some Stock Entries are hidden, the summary says so.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint

from isnack.isnack.page.batch_explorer import batch_explorer as be
from isnack.isnack.page.quality_hub.quality_hub import QC_DOCTYPES, RETIRED_QC_CODES
from isnack.utils import batch_lineage
from isnack.utils.qty import qty_tick

# Display metadata per QC record type, keyed by code.
QC_META = {
	"QCA": {"label": "Receiving", "color": "#2e7fff"},
	"QCB": {"label": "Puffs Extruder", "color": "#26a65b"},
	"QCC": {"label": "Rice Extruder", "color": "#26a65b"},
	"QCD": {"label": "Frying Line", "color": "#26a65b"},
	# retired: oven readings are on the extruder records now; old records still show
	"QCE": {"label": "Oven", "color": "#26a65b"},
	"QCF": {"label": "Tasting", "color": "#ab47bc"},
	"QCG": {"label": "Packaging", "color": "#26a69a"},
	"QCH": {"label": "Metal Detector", "color": "#fb8c00"},
	"QCI": {"label": "Weight", "color": "#26a69a"},
}

# Groups that show what the records were found through, after the records.
TRACE_META = {
	"work_orders": {"label": "Work Orders", "color": "#7c4dff"},
	"ingredients": {"label": "Ingredient batches", "color": "#8d6e63"},
	"outputs": {"label": "Batches produced", "color": "#66bb6a"},
}

# Producing Work Orders whose ingredients are traced, at most.
MAX_TRACED_WORK_ORDERS = be.MAX_EAGER_INPUT_WOS

# How a record relates to the subject.
REL_THIS_BATCH = "this_batch"
REL_OUTPUT_BATCH = "output_batch"
REL_WORK_ORDER = "work_order"
REL_THIS_WORK_ORDER = "this_work_order"
REL_INGREDIENT = "ingredient"
REL_SEMI_FINISHED = "semi_finished"

# Why a Work Order is in scope.
WO_PRODUCED = "produced"
WO_NAMED = "named_on_record"
WO_SUBJECT = "subject"

# Fields read off a record when its doctype has them.
_RECORD_FIELDS = [
	"record_date",
	"shift",
	"factory_line",
	"work_order",
	"batch_no",
	"item_code",
	"item_name",
	"product_item",
	"product_name",
	"supplier",
	"operator_name",
	"qc_inspector",
	"overall_status",
	"all_tests_passed",
	"variance_acceptable",
]

_RESULT_LEVEL = {
	"Pass": "pass",
	"Accepted": "pass",
	"Marginal": "warn",
	"Conditionally Accepted": "warn",
	"Fail": "fail",
	"Rejected": "fail",
}


@frappe.whitelist()
def get_quality_records(batch_no: str | None = None, work_order: str | None = None):
	"""Return ``{subject, groups, coverage, summary}`` for a Batch or a Work Order.

	Exactly one of ``batch_no`` and ``work_order`` is given.
	"""
	batch_no = (batch_no or "").strip()
	work_order = (work_order or "").strip()
	if bool(batch_no) == bool(work_order):
		frappe.throw(_("Please select a Batch or a Work Order."))

	subject, scope = _batch_scope(batch_no) if batch_no else _work_order_scope(work_order)
	trace = _ingredient_trace(sorted(scope["work_orders"]))

	batches = list(scope["batches"]) + [b for b in trace["batches"] if b not in scope["batches"]]
	work_orders = list(scope["work_orders"]) + [w for w in trace["runs"] if w not in scope["work_orders"]]
	records, hidden, withheld = _read_records(batches, work_orders)

	inspectors = be._user_names({r.get("qc_inspector") for rows in records.values() for r in rows})
	groups = []
	for code, rows in records.items():
		if not rows:
			continue
		nodes = [_record_node(code, r, _relations(r, scope, trace), inspectors) for r in rows]
		groups.append(
			{
				"key": code,
				"doctype": QC_DOCTYPES[code],
				"code": code,
				"label": "{0} ({1})".format(_(QC_META[code]["label"]), code),
				"color": QC_META[code]["color"],
				"count": len(nodes),
				"nodes": nodes,
			}
		)

	groups += _trace_groups(subject, scope, trace, records, hidden, withheld)

	nodes = [n for g in groups if g.get("code") for n in g["nodes"]]
	return {
		"subject": subject,
		"groups": groups,
		"coverage": _coverage(records, hidden, withheld),
		"summary": {
			"records": len(nodes),
			"submitted": sum(1 for n in nodes if n["docstatus"] == 1),
			"drafts": sum(1 for n in nodes if n["docstatus"] == 0),
			"failed": sum(1 for n in nodes if n["result_level"] == "fail"),
			"work_orders": sum(1 for w in work_orders if scope["work_order_roles"].get(w) != WO_SUBJECT),
			"ingredients": len(trace["batches"]),
			"hidden": hidden,
			"withheld": sum(len(rows) for rows in withheld.values()),
			"trace_hint": trace["hint"],
		},
	}


# ---------------------------------------------------------------------------
# Scope: the batches and Work Orders the subject stands for
# ---------------------------------------------------------------------------

def _batch_scope(batch_no: str) -> tuple[dict, dict]:
	if not frappe.has_permission("Batch", "read"):
		raise frappe.PermissionError(_("Not permitted to read Batch."))

	batch = be._load_batch(batch_no)
	# the picker applies User Permissions, a direct call or a shared link does not
	if not frappe.has_permission("Batch", "read", doc=batch.name):
		raise frappe.PermissionError(_("Not permitted to read Batch {0}.").format(batch.name))
	se_info = be._stock_entry_info(be._direct_vouchers(batch.name))
	roles = be._batch_roles(batch.name, batch.item, se_info)

	work_orders = {wo: WO_PRODUCED for wo, role in roles.items() if role == be.ROLE_PRODUCER}
	for wo in sorted(_work_orders_named_on_records(batch.name)):
		work_orders.setdefault(wo, WO_NAMED)

	subject = dict(batch, kind="Batch")
	return subject, {
		"batches": {batch.name: REL_THIS_BATCH},
		"work_orders": {wo: REL_WORK_ORDER for wo in work_orders},
		"work_order_roles": work_orders,
		"outputs": [],
	}


def _work_orders_named_on_records(batch_no: str) -> set[str]:
	"""Work Orders that the batch's own QC records name.

	Read raw, like the records themselves (``_read_records``): a Work Order
	named only on a record a User Permission keeps from the user still brings
	its other records into scope, where they are withheld rather than missing.
	A doctype the user may not read at all is skipped.
	"""
	named = set()
	for doctype in QC_DOCTYPES.values():
		meta = frappe.get_meta(doctype)
		if not (meta.has_field("batch_no") and meta.has_field("work_order")):
			continue
		if not frappe.has_permission(doctype, "read"):
			continue
		named.update(
			frappe.get_all(
				doctype,
				filters={"batch_no": batch_no, "docstatus": ["<", 2], "work_order": ["is", "set"]},
				pluck="work_order",
			)
		)
	return {wo for wo in named if wo}


def _work_order_scope(work_order: str) -> tuple[dict, dict]:
	if not frappe.has_permission("Work Order", "read"):
		raise frappe.PermissionError(_("Not permitted to read Work Order."))

	fields = [
		"name",
		"production_item",
		"item_name",
		"status",
		"docstatus",
		"qty",
		"produced_qty",
		"stock_uom",
		"planned_start_date",
		"actual_start_date",
		"actual_end_date",
		"owner",
	]
	if frappe.get_meta("Work Order").has_field("custom_factory_line"):
		fields.append("custom_factory_line")
	wo = frappe.db.get_value("Work Order", work_order, fields, as_dict=True)
	if not wo:
		frappe.throw(_("Work Order {0} not found.").format(frappe.bold(work_order)))
	if not frappe.has_permission("Work Order", "read", doc=wo.name):
		raise frappe.PermissionError(_("Not permitted to read Work Order {0}.").format(wo.name))

	outputs = batch_lineage.fg_batch_quantities_by_work_order([wo.name]).get(wo.name) or []
	subject = dict(
		wo,
		kind="Work Order",
		item=wo.production_item,
		line=wo.get("custom_factory_line"),
		owner_name=be._user_name(wo.owner),
	)
	return subject, {
		"batches": {b: REL_OUTPUT_BATCH for b, _qty in outputs},
		"work_orders": {wo.name: REL_THIS_WORK_ORDER},
		"work_order_roles": {wo.name: WO_SUBJECT},
		"outputs": [{"batch_no": b, "qty": qty, "uom": wo.stock_uom} for b, qty in outputs],
	}


# ---------------------------------------------------------------------------
# Ingredients: consumed batches and semi-finished runs below the Work Orders
# ---------------------------------------------------------------------------

def _ingredient_trace(work_orders: list[str]) -> dict:
	"""``{batches, runs, hint}`` below ``work_orders``.

	* ``batches`` -- ``{batch_no: {item_code, item_name, work_orders}}``: the
	  raw-material batches consumed, each with the Work Orders that consumed it;
	* ``runs`` -- ``{work_order: {item_code, for_work_order}}``: the Work Orders
	  that made a semi-finished item one of them consumed;
	* ``hint`` -- why the trace is partial or missing, else ``None``.
	"""
	out = {"batches": {}, "runs": {}, "hint": None}
	if not work_orders:
		return out
	if not frappe.has_permission("Stock Entry", "read"):
		out["hint"] = _("Ingredients not traced: you may not read Stock Entries.")
		return out

	hints = []
	traced = work_orders[:MAX_TRACED_WORK_ORDERS]
	if len(traced) < len(work_orders):
		hints.append(
			_("Ingredients traced for the first {0} of {1} Work Orders.").format(len(traced), len(work_orders))
		)

	seen = set(work_orders)
	hidden_entries = 0
	level = [(wo, (wo,)) for wo in traced]
	while level:
		below = []
		for wo, path in level:
			read = be._read_work_order(wo)
			hidden_entries += read["hidden"]
			materials = batch_lineage.consumed_materials(
				read["submitted"], read["rows_by_entry"], read["bundle_map"]
			)
			for m in materials:
				if not m.get("batch_no"):
					continue
				batch = out["batches"].setdefault(
					m["batch_no"],
					{"item_code": m["item_code"], "item_name": m.get("item_name"), "work_orders": []},
				)
				if wo not in batch["work_orders"]:
					batch["work_orders"].append(wo)

			# same depth cap as the Batch Explorer's "Made by" groups
			if len(path) > be.MAX_SFG_DEPTH:
				continue
			for run, item_code in _semi_finished_runs(materials):
				if run in seen:
					continue
				seen.add(run)
				out["runs"][run] = {"item_code": item_code, "for_work_order": wo}
				below.append((run, path + (run,)))
		level = below

	if hidden_entries:
		# a dossier must not look complete when it is not
		hints.append(
			_("Ingredients may be incomplete: {0} Stock Entries are hidden by your permissions.").format(
				hidden_entries
			)
		)
	out["hint"] = " ".join(hints) or None
	return out


def _semi_finished_runs(materials: list[dict]) -> list[tuple[str, str]]:
	"""``[(work_order, item_code)]``: the runs that made the semi-finished items among ``materials``.

	The Batch Explorer's rule: a consumed item without a batch that some Work
	Order manufactures came out of a shared pool, and the runs booked into that
	pool since it was last empty are where it came from.
	"""
	batchless = [m for m in materials if not m.get("batch_no")]
	made = batch_lineage.manufactured_items({m["item_code"] for m in batchless})
	batchless = [m for m in batchless if m["item_code"] in made]
	if not batchless:
		return []

	sources = batch_lineage.pool_sources([ln.get("row") for m in batchless for ln in m["lines"]], qty_tick())
	runs = []
	for m in batchless:
		for ln in m["lines"]:
			for w in (sources.get(ln.get("row")) or {}).get("work_orders", []):
				pair = (w["work_order"], m["item_code"])
				if pair not in runs:
					runs.append(pair)
	return runs


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------

def _read_records(
	batches: list[str], work_orders: list[str]
) -> tuple[dict[str, list], list[str], dict[str, list]]:
	"""``(records, hidden, withheld)``: the live records naming a batch or Work Order.

	``records`` -- ``{code: [row, ...]}``, the ones the user may read. Drafts
	are included, cancelled records are not.
	``hidden`` -- the codes the user may not read at all (absent from both dicts).
	``withheld`` -- ``{code: [row, ...]}``, the rows the user's User Permissions
	filter out; only their existence is used, never shown.
	"""
	records, hidden, withheld = {}, [], {}
	for code, doctype in QC_DOCTYPES.items():
		if not frappe.has_permission(doctype, "read"):
			hidden.append(code)
			continue
		records[code], withheld[code] = [], []
		meta = frappe.get_meta(doctype)
		or_filters = []
		if batches and meta.has_field("batch_no"):
			or_filters.append(["batch_no", "in", batches])
		if work_orders and meta.has_field("work_order"):
			or_filters.append(["work_order", "in", work_orders])
		if not or_filters:
			continue
		rows = frappe.get_all(
			doctype,
			filters={"docstatus": ["<", 2]},
			or_filters=or_filters,
			fields=["name", "docstatus"] + [f for f in _RECORD_FIELDS if meta.has_field(f)],
			order_by="record_date asc, modified asc",
		)
		permitted, _count = be._permitted_names(doctype, [r.name for r in rows])
		for r in rows:
			(records if r.name in permitted else withheld)[code].append(r)
	return records, hidden, withheld


def _result(row) -> tuple[str | None, str | None]:
	"""The record's outcome and how it reads: ``pass``, ``warn`` or ``fail``.

	Metal detector logs and packaging checks have no Overall Status; their
	computed pass flags stand in for it.
	"""
	if row.get("overall_status"):
		return row.overall_status, _RESULT_LEVEL.get(row.overall_status, "warn")
	if "all_tests_passed" in row:
		if cint(row.all_tests_passed):
			return _("All tests passed"), "pass"
		return _("Not all tests passed"), "fail"
	if "variance_acceptable" in row:
		if cint(row.variance_acceptable):
			return _("Variance acceptable"), "pass"
		return _("Variance out of tolerance"), "fail"
	return None, None


def _relations(row, scope: dict, trace: dict) -> list[dict]:
	"""``[{key, detail}]``: every route by which ``row`` belongs to the subject."""
	rel = []
	batch_no, work_order = row.get("batch_no"), row.get("work_order")
	if batch_no in scope["batches"]:
		rel.append({"key": scope["batches"][batch_no], "detail": batch_no})
	if work_order in scope["work_orders"]:
		rel.append({"key": scope["work_orders"][work_order], "detail": work_order})
	if batch_no in trace["batches"]:
		ing = trace["batches"][batch_no]
		rel.append(
			{
				"key": REL_INGREDIENT,
				"detail": _("{0} consumed by {1}").format(ing["item_code"], ", ".join(ing["work_orders"])),
			}
		)
	if work_order in trace["runs"]:
		run = trace["runs"][work_order]
		rel.append(
			{
				"key": REL_SEMI_FINISHED,
				"detail": _("{0} made {1} for {2}").format(work_order, run["item_code"], run["for_work_order"]),
			}
		)
	return rel


def _record_node(code: str, row, relations: list[dict], inspectors: dict[str, str]) -> dict:
	result, level = _result(row)
	item = row.get("item_code") or row.get("product_item")
	item_name = row.get("item_name") or row.get("product_name")
	return {
		"doctype": QC_DOCTYPES[code],
		"code": code,
		"name": row.name,
		"date": str(row.record_date) if row.get("record_date") else None,
		"shift": row.get("shift"),
		"line": row.get("factory_line"),
		"work_order": row.get("work_order"),
		"batch_no": row.get("batch_no"),
		"item": " · ".join(dict.fromkeys(x for x in (item, item_name) if x)) or None,
		"supplier": row.get("supplier"),
		"operator": row.get("operator_name"),
		"inspector": row.get("qc_inspector"),
		"inspector_name": inspectors.get(row.get("qc_inspector")),
		"docstatus": row.docstatus,
		"status": be._DOCSTATUS_LABEL.get(row.docstatus, ""),
		"result": result,
		"result_level": level,
		"relations": relations,
	}


def _coverage(records: dict[str, list], hidden: list[str], withheld: dict[str, list]) -> list[dict]:
	"""One entry per record type, in code order, with its counts and ``state``.

	``state`` is ``hidden`` (may not read the type, or every record of it is
	withheld from the user), ``missing`` (no record), ``failed`` (a record
	failed), ``submitted`` or ``draft`` (drafts only). ``withheld`` counts the
	records the user's permissions keep from them. A retired record type is
	only listed when it has records: none is expected any more.
	"""
	out = []
	for code, doctype in QC_DOCTYPES.items():
		rows = records.get(code) or []
		kept_back = len(withheld.get(code) or [])
		if code in RETIRED_QC_CODES and not rows and not kept_back:
			continue
		submitted = sum(1 for r in rows if r.docstatus == 1)
		failed = sum(1 for r in rows if _result(r)[1] == "fail")
		if code in hidden or (kept_back and not rows):
			state = "hidden"
		elif not rows:
			state = "missing"
		elif failed:
			state = "failed"
		elif submitted:
			state = "submitted"
		else:
			state = "draft"
		out.append(
			{
				"code": code,
				"doctype": doctype,
				"label": _(QC_META[code]["label"]),
				"count": len(rows),
				"submitted": submitted,
				"drafts": len(rows) - submitted,
				"failed": failed,
				"withheld": kept_back,
				"state": state,
			}
		)
	return out


# ---------------------------------------------------------------------------
# Trace groups: what the records were found through
# ---------------------------------------------------------------------------

def _trace_groups(
	subject: dict, scope: dict, trace: dict, records: dict, hidden: list[str], withheld: dict[str, list]
) -> list[dict]:
	# a receiving record the user may not see still counts as on file
	unseen_receiving = {r.get("batch_no") for r in withheld.get("QCA") or []}
	by_work_order, by_batch = _counts_by_link(records)
	withheld_by_work_order, withheld_by_batch = _counts_by_link(withheld)

	groups = []
	wo_names = list(scope["work_order_roles"]) + [w for w in trace["runs"] if w not in scope["work_order_roles"]]
	# the subject Work Order is the page's own header, not a route to it
	wo_names = [w for w in wo_names if scope["work_order_roles"].get(w) != WO_SUBJECT]
	if wo_names:
		nodes = be._build_nodes("Work Order", {w: {"qty": None, "date": None} for w in wo_names})
		for node in nodes:
			wo = node["name"]
			role = scope["work_order_roles"].get(wo)
			if role:
				node["tags"] = [role]
			else:
				run = trace["runs"][wo]
				node["tags"] = [REL_SEMI_FINISHED]
				node["tag_detail"] = _("made {0} for {1}").format(run["item_code"], run["for_work_order"])
			node["qc_count"] = by_work_order.get(wo, 0)
			node["qc_withheld"] = withheld_by_work_order.get(wo, 0)
			node["route"] = ["quality-explorer", "Work Order", wo]
		groups.append(_trace_group("work_orders", nodes))

	if trace["batches"]:
		nodes = []
		for batch_no in sorted(trace["batches"]):
			ing = trace["batches"][batch_no]
			receiving = by_batch.get(("QCA", batch_no), 0)
			tags = [REL_INGREDIENT]
			if not receiving and "QCA" not in hidden and batch_no not in unseen_receiving:
				tags.append("no_receiving_record")
			nodes.append(
				_batch_node(
					batch_no,
					extra=" · ".join(dict.fromkeys(x for x in (ing["item_code"], ing.get("item_name")) if x)),
					tags=tags,
					tag_detail=_("consumed by {0}").format(", ".join(ing["work_orders"])),
					qc_count=_batch_count(by_batch, batch_no),
					qc_withheld=_batch_count(withheld_by_batch, batch_no),
				)
			)
		groups.append(_trace_group("ingredients", nodes, hint=trace["hint"]))
	elif trace["hint"]:
		groups.append(_trace_group("ingredients", [], hint=trace["hint"]))

	if scope["outputs"]:
		nodes = [
			_batch_node(
				o["batch_no"],
				extra=subject.get("item"),
				tags=[REL_OUTPUT_BATCH],
				qty=o["qty"],
				uom=o["uom"],
				qc_count=_batch_count(by_batch, o["batch_no"]),
				qc_withheld=_batch_count(withheld_by_batch, o["batch_no"]),
			)
			for o in scope["outputs"]
		]
		groups.append(_trace_group("outputs", nodes))
	return groups


def _counts_by_link(records: dict[str, list]) -> tuple[dict[str, int], dict[tuple[str, str], int]]:
	"""``({work_order: n}, {(code, batch_no): n})`` over the rows of ``records``."""
	by_work_order: dict[str, int] = {}
	by_batch: dict[tuple[str, str], int] = {}
	for code, rows in records.items():
		for r in rows:
			if r.get("work_order"):
				by_work_order[r.work_order] = by_work_order.get(r.work_order, 0) + 1
			if r.get("batch_no"):
				key = (code, r.batch_no)
				by_batch[key] = by_batch.get(key, 0) + 1
	return by_work_order, by_batch


def _batch_count(by_batch: dict[tuple[str, str], int], batch_no: str) -> int:
	return sum(n for (_code, b), n in by_batch.items() if b == batch_no)


def _batch_node(
	batch_no: str, extra=None, tags=None, tag_detail=None, qty=None, uom=None, qc_count=0, qc_withheld=0
) -> dict:
	return {
		"doctype": "Batch",
		"name": batch_no,
		"qty": qty,
		"uom": uom,
		"date": None,
		"owner": None,
		"owner_name": None,
		"docstatus": None,
		"status": "",
		"extra": extra,
		"tags": tags or [],
		"tag_detail": tag_detail,
		"qc_count": qc_count,
		"qc_withheld": qc_withheld,
		"route": ["quality-explorer", "Batch", batch_no],
	}


def _trace_group(key: str, nodes: list[dict], hint: str | None = None) -> dict:
	meta = TRACE_META[key]
	return {
		"key": key,
		"doctype": None,
		"code": None,
		"label": _(meta["label"]),
		"color": meta["color"],
		"count": len(nodes),
		"nodes": nodes,
		"trace": True,
		"hint": hint,
	}
