"""Batch Explorer backend.

Given a Batch, resolve every transaction the batch participated in and return a
tree-friendly structure for the Batch Explorer desk page.

Resolution strategy
--------------------
1. Stock Ledger Entry (SLE) is the canonical record of every stock movement.
   For the batch we collect the distinct ``(voucher_type, voucher_no)`` pairs,
   handling both the legacy ``batch_no`` column and the v15
   ``serial_and_batch_bundle`` -> ``Serial and Batch Entry`` link.
2. From the stock vouchers we *derive* the upstream/related documents that do
   not themselves carry stock (and therefore have no SLE):
       - Work Orders        (from Stock Entries linked to a Work Order)
       - Sales Orders       (from Sales Invoice / Delivery Note items)
       - Purchase Orders    (from Purchase Receipt / Purchase Invoice items)
3. Each node is enriched with the creating user, status and a signed quantity.
4. Production inputs. For every Work Order that *produced* the batch, the Stock
   Entries the MES booked against that Work Order (staging transfers, transfer
   for manufacture, consumption, the Manufacture entry itself, returns,
   surplus) are attached under the Work Order node as nested groups, together
   with the raw materials and raw-material batches they consumed. Work Orders
   that *consumed* the batch get a nested "Produced" group listing the
   finished-goods batches they made. The rules live in
   ``isnack.utils.batch_lineage``.

Quantity semantics
------------------
Top-level nodes: ``qty`` is the signed movement of *this* batch in that voucher
(``SUM(sle.actual_qty)``), group totals and the transaction count derive from
those nodes only. Nested material nodes: ``qty`` is the positive consumed
quantity in the material's stock UOM for the *whole* Work Order; it is never
apportioned to the batch, and a Work Order that produced more than this batch is
tagged ``shared_output`` instead.

Permissions
-----------
The page is gated on ``Batch`` read. Top-level nodes are read with
``frappe.get_all`` (a raw read that does not apply user permissions). The nested
production-inputs level is gated on ``Stock Entry`` read and filters its Stock
Entries and Batches with ``frappe.get_list`` before reading any detail rows.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

from isnack.utils import batch_lineage

# Display metadata per doctype: colour + logical ordering for the tree.
DOCTYPE_META = {
	"Work Order": {"color": "#7c4dff", "order": 1, "category": "Manufacturing"},
	"Stock Entry": {"color": "#607d8b", "order": 2, "category": "Stock"},
	"Stock Reconciliation": {"color": "#90a4ae", "order": 3, "category": "Stock"},
	"Purchase Order": {"color": "#fb8c00", "order": 4, "category": "Purchasing"},
	"Purchase Receipt": {"color": "#8d6e63", "order": 5, "category": "Purchasing"},
	"Purchase Invoice": {"color": "#ef5350", "order": 6, "category": "Purchasing"},
	"Sales Order": {"color": "#42a5f5", "order": 7, "category": "Sales"},
	"Delivery Note": {"color": "#26a69a", "order": 8, "category": "Sales"},
	"Sales Invoice": {"color": "#66bb6a", "order": 9, "category": "Sales"},
	"Packing Slip": {"color": "#5c6bc0", "order": 10, "category": "Sales"},
	"Pick List": {"color": "#26c6da", "order": 11, "category": "Sales"},
}

# Nested groups attached under a Work Order node (labels in ``_nested_label``).
NESTED_META = {
	"materials": {"color": "#8d6e63"},
	"entries": {"color": "#607d8b"},
	"ineffective": {"color": "#9e9e9e"},
	"produced": {"color": "#66bb6a"},
}

# Producing Work Orders beyond this many get their inputs loaded on demand
# (``get_work_order_inputs``) instead of eagerly with the page.
MAX_EAGER_INPUT_WOS = 10

ROLE_PRODUCER = "producer"
ROLE_CONSUMER = "consumer"
ROLE_HANDLER = "handler"
_ROLE_RANK = {ROLE_PRODUCER: 3, ROLE_CONSUMER: 2, ROLE_HANDLER: 1}

_DOCSTATUS_LABEL = {0: "Draft", 1: "Submitted", 2: "Cancelled"}


@frappe.whitelist()
def get_batch_usage(batch_no: str | None = None):
	"""Return ``{batch, groups, summary}`` describing where ``batch_no`` was used."""
	batch_no = (batch_no or "").strip()
	if not batch_no:
		frappe.throw(_("Please select a Batch."))

	if not frappe.has_permission("Batch", "read"):
		raise frappe.PermissionError(_("Not permitted to read Batch."))

	batch = _load_batch(batch_no)

	# 1) direct stock vouchers from the Stock Ledger
	direct = _direct_vouchers(batch_no)

	# 2) derive related Work Orders / Sales Orders / Purchase Orders
	se_info = _stock_entry_info(direct)
	derived = _derived_vouchers(direct, se_info)

	# 3) build the grouped node tree
	groups = []
	for doctype in set(list(direct.keys()) + list(derived.keys())):
		names_qty = dict(direct.get(doctype, {}))
		for name in derived.get(doctype, set()):
			names_qty.setdefault(name, {"qty": None, "date": None})

		nodes = _build_nodes(doctype, names_qty)
		if not nodes:
			continue
		qtys = [flt(n["qty"]) for n in nodes if n["qty"] is not None]
		meta = DOCTYPE_META.get(doctype, {})
		groups.append(
			{
				"doctype": doctype,
				"label": _(doctype),
				"color": meta.get("color", "#9e9e9e"),
				"category": meta.get("category", "Other"),
				"count": len(nodes),
				"total_qty": sum(qtys) if qtys else None,
				"nodes": nodes,
			}
		)

	groups.sort(key=lambda g: (DOCTYPE_META.get(g["doctype"], {}).get("order", 99), g["doctype"]))

	# 4) production inputs under the Work Orders (never changes the totals above)
	_attach_production_inputs(groups, batch, se_info)

	return {
		"batch": batch,
		"groups": groups,
		"summary": {
			"transactions": sum(g["count"] for g in groups),
			"doctypes": len(groups),
		},
	}


@frappe.whitelist()
def get_work_order_inputs(work_order: str | None = None, batch_no: str | None = None):
	"""Production inputs of one Work Order for ``batch_no`` (deferred load).

	Used by the page when a batch was produced by more than
	``MAX_EAGER_INPUT_WOS`` Work Orders. Returns the same keys the eager path
	puts on the Work Order node: ``lineage``, ``tags``, ``children``.
	"""
	work_order = (work_order or "").strip()
	batch_no = (batch_no or "").strip()
	if not work_order or not batch_no:
		frappe.throw(_("Work Order and Batch are required."))

	if not frappe.has_permission("Batch", "read"):
		raise frappe.PermissionError(_("Not permitted to read Batch."))
	if not frappe.has_permission("Stock Entry", "read"):
		raise frappe.PermissionError(_("Not permitted to read Stock Entry."))
	if not frappe.has_permission("Work Order", "read", doc=work_order):
		raise frappe.PermissionError(_("Not permitted to read Work Order {0}.").format(work_order))

	batch = _load_batch(batch_no)
	return _work_order_inputs(work_order, batch)


def _load_batch(batch_no: str):
	batch = frappe.db.get_value(
		"Batch",
		batch_no,
		["name", "item", "batch_qty", "manufacturing_date", "expiry_date", "disabled", "owner", "creation"],
		as_dict=True,
	)
	if not batch:
		frappe.throw(_("Batch {0} not found.").format(frappe.bold(batch_no)))

	item_info = (
		frappe.db.get_value("Item", batch.item, ["item_name", "stock_uom"], as_dict=True) or frappe._dict()
	)
	batch.item_name = item_info.get("item_name")
	batch.stock_uom = item_info.get("stock_uom")
	batch.owner_name = _user_name(batch.owner)
	batch.expired = bool(batch.expiry_date and getdate(batch.expiry_date) < getdate(nowdate()))
	return batch


# ---------------------------------------------------------------------------
# Step 1 - direct stock vouchers via Stock Ledger Entry
# ---------------------------------------------------------------------------

def _direct_vouchers(batch_no: str) -> dict[str, dict]:
	"""Return {doctype: {voucher_no: {qty, date}}} from the Stock Ledger."""
	rows = frappe.db.sql(
		"""
		SELECT
			sle.voucher_type            AS voucher_type,
			sle.voucher_no              AS voucher_no,
			SUM(sle.actual_qty)         AS qty,
			MIN(sle.posting_date)       AS posting_date
		FROM `tabStock Ledger Entry` sle
		WHERE sle.is_cancelled = 0
		  AND (
			sle.batch_no = %(b)s
			OR EXISTS (
				SELECT 1 FROM `tabSerial and Batch Entry` sbe
				WHERE sbe.parent = sle.serial_and_batch_bundle
				  AND sbe.batch_no = %(b)s
			)
		  )
		GROUP BY sle.voucher_type, sle.voucher_no
		ORDER BY MIN(sle.posting_date), sle.voucher_no
		""",
		{"b": batch_no},
		as_dict=True,
	)

	direct: dict[str, dict] = {}
	for r in rows:
		if not r.voucher_type or not r.voucher_no:
			continue
		direct.setdefault(r.voucher_type, {})[r.voucher_no] = {
			"qty": flt(r.qty),
			"date": r.posting_date,
		}
	return direct


# ---------------------------------------------------------------------------
# Step 2 - derive related documents that carry no stock of their own
# ---------------------------------------------------------------------------

def _stock_entry_info(direct: dict[str, dict]) -> dict[str, dict]:
	"""Return {stock_entry: {name, work_order, purpose}} for the direct Stock Entries."""
	se_names = list(direct.get("Stock Entry", {}).keys())
	if not se_names:
		return {}
	return {
		r.name: r
		for r in frappe.get_all(
			"Stock Entry",
			filters={"name": ["in", se_names]},
			fields=["name", "work_order", "purpose"],
		)
	}


def _derived_vouchers(direct: dict[str, dict], se_info: dict[str, dict] | None = None) -> dict[str, set]:
	derived: dict[str, set] = {}

	dn_names = list(direct.get("Delivery Note", {}).keys())
	si_names = list(direct.get("Sales Invoice", {}).keys())
	pr_names = list(direct.get("Purchase Receipt", {}).keys())
	pi_names = list(direct.get("Purchase Invoice", {}).keys())

	# Work Orders linked to the Stock Entries (manufacture, transfer, issue ...)
	if se_info is None:
		se_info = _stock_entry_info(direct)
	work_orders = {info.get("work_order") for info in se_info.values() if info.get("work_order")}
	if work_orders:
		derived["Work Order"] = work_orders

	# Sales Orders behind the Sales Invoices / Delivery Notes
	sales_orders: set[str] = set()
	sales_orders |= _child_links("Sales Invoice Item", si_names, "sales_order")
	sales_orders |= _child_links("Delivery Note Item", dn_names, "against_sales_order")
	if sales_orders:
		derived["Sales Order"] = sales_orders

	# Purchase Orders behind the Purchase Receipts / Purchase Invoices
	purchase_orders: set[str] = set()
	purchase_orders |= _child_links("Purchase Receipt Item", pr_names, "purchase_order")
	purchase_orders |= _child_links("Purchase Invoice Item", pi_names, "purchase_order")
	if purchase_orders:
		derived["Purchase Order"] = purchase_orders

	return derived


def _child_links(child_doctype: str, parents: list[str], fieldname: str) -> set[str]:
	"""Return the distinct non-empty ``fieldname`` values from child rows."""
	if not parents:
		return set()
	rows = frappe.get_all(
		child_doctype,
		filters={"parent": ["in", parents], fieldname: ["is", "set"]},
		fields=[fieldname],
		distinct=True,
	)
	return {r.get(fieldname) for r in rows if r.get(fieldname)}


# ---------------------------------------------------------------------------
# Step 3 - build display nodes for a doctype
# ---------------------------------------------------------------------------

# candidate detail fields per doctype, used only when the field actually exists
_OPTIONAL_FIELDS = [
	"status",
	"posting_date",
	"transaction_date",
	"customer",
	"customer_name",
	"supplier",
	"supplier_name",
	"production_item",
	"item_name",
	"qty",
	"purpose",
	"stock_entry_type",
]


def _build_nodes(doctype: str, names_qty: dict[str, dict]) -> list[dict]:
	if not names_qty:
		return []

	meta = frappe.get_meta(doctype)
	fields = ["name", "owner", "creation", "docstatus"]
	fields += [f for f in _OPTIONAL_FIELDS if meta.has_field(f)]
	fields = list(dict.fromkeys(fields))

	rows = frappe.get_all(doctype, filters={"name": ["in", list(names_qty.keys())]}, fields=fields)
	if not rows:
		return []

	owner_names = _user_names({r.owner for r in rows})

	nodes = []
	for r in rows:
		qd = names_qty.get(r.name, {})
		qty = qd.get("qty")
		date = qd.get("date") or r.get("posting_date") or r.get("transaction_date")
		if not date and r.get("creation"):
			date = getdate(r.creation)

		party = (
			r.get("customer_name")
			or r.get("customer")
			or r.get("supplier_name")
			or r.get("supplier")
		)
		extra = r.get("stock_entry_type") or r.get("purpose") or r.get("production_item")

		nodes.append(
			{
				"doctype": doctype,
				"name": r.name,
				"qty": flt(qty) if qty is not None else None,
				"direction": _direction(qty),
				"date": str(date) if date else None,
				"owner": r.owner,
				"owner_name": owner_names.get(r.owner, r.owner),
				"docstatus": r.docstatus,
				"status": r.get("status") or _DOCSTATUS_LABEL.get(r.docstatus, ""),
				"party": party,
				"extra": extra,
			}
		)

	nodes.sort(key=lambda n: (n["date"] or "", n["name"]))
	return nodes


def _direction(qty) -> str | None:
	q = flt(qty)
	if qty is None or q == 0:
		return None
	return "in" if q > 0 else "out"


# ---------------------------------------------------------------------------
# Step 4 - production inputs under the Work Order nodes
# ---------------------------------------------------------------------------

def _attach_production_inputs(groups: list[dict], batch, se_info: dict[str, dict]) -> None:
	"""Attach ``lineage`` / ``tags`` / ``children`` to the Work Order nodes in place."""
	wo_group = next((g for g in groups if g["doctype"] == "Work Order"), None)
	if not wo_group or not wo_group["nodes"]:
		return
	if not frappe.has_permission("Stock Entry", "read"):
		return

	roles = _batch_roles(batch.name, batch.item, se_info)
	eager = 0
	for node in wo_group["nodes"]:
		role = roles.get(node["name"])
		if not role or role == ROLE_HANDLER:
			continue
		node["role"] = role
		if role == ROLE_CONSUMER:
			node.update(_work_order_outputs(node["name"], batch))
			continue
		if eager >= MAX_EAGER_INPUT_WOS:
			node["inputs_deferred"] = True
			continue
		eager += 1
		node.update(_work_order_inputs(node["name"], batch))


def _batch_roles(batch_no: str, batch_item: str | None, se_info: dict[str, dict]) -> dict[str, str]:
	"""Classify each linked Work Order as producer / consumer / handler of the batch.

	Decided from the rows of the batch's own Stock Entries that carry the batch:
	a finished-item row makes the Work Order a producer, a consumed row a
	consumer, anything else (a transfer of the batch) a handler. The production
	item is only a fallback for legacy rows that lost their batch link.
	"""
	linked = {se: info.get("work_order") for se, info in se_info.items() if info.get("work_order")}
	if not linked:
		return {}

	rows = frappe.db.sql(
		"""
		SELECT sed.parent, sed.is_finished_item, sed.is_scrap_item, sed.s_warehouse
		FROM `tabStock Entry Detail` sed
		WHERE sed.parent IN %(parents)s
		  AND (
			sed.batch_no = %(b)s
			OR EXISTS (
				SELECT 1 FROM `tabSerial and Batch Entry` sbe
				WHERE sbe.parent = sed.serial_and_batch_bundle
				  AND sbe.batch_no = %(b)s
			)
		  )
		""",
		{"parents": tuple(linked.keys()), "b": batch_no},
		as_dict=True,
	)

	roles: dict[str, str] = {}

	def put(wo, role):
		if _ROLE_RANK[role] > _ROLE_RANK.get(roles.get(wo), 0):
			roles[wo] = role

	for r in rows:
		wo = linked.get(r.parent)
		if not wo:
			continue
		purpose = (se_info.get(r.parent) or {}).get("purpose")
		if cint(r.is_finished_item):
			put(wo, ROLE_PRODUCER)
		elif (
			purpose in batch_lineage.CONSUMPTION_PURPOSES
			and r.s_warehouse
			and not cint(r.is_scrap_item)
		):
			# same rule as batch_lineage.is_consumed_row: a transfer into or
			# out of WIP also has a source warehouse but is not consumption
			put(wo, ROLE_CONSUMER)
		else:
			put(wo, ROLE_HANDLER)

	unresolved = {
		wo
		for se, wo in linked.items()
		if wo not in roles and (se_info.get(se) or {}).get("purpose") == "Manufacture"
	}
	if unresolved and batch_item:
		for r in frappe.get_all(
			"Work Order",
			filters={"name": ["in", sorted(unresolved)], "production_item": batch_item},
			fields=["name"],
		):
			put(r.name, ROLE_PRODUCER)
	return roles


def _permitted_names(doctype: str, names) -> tuple[set[str], int]:
	"""Names the current user may read, and how many were hidden."""
	names = [n for n in dict.fromkeys(names or []) if n]
	if not names:
		return set(), 0
	# limit_page_length=0: every candidate, not the first page only
	permitted = set(
		frappe.get_list(doctype, filters={"name": ["in", names]}, pluck="name", limit_page_length=0)
	)
	return permitted, len(names) - len(permitted)


def _work_order_inputs(work_order: str, batch) -> dict:
	"""``{lineage, tags, children}`` for a Work Order that produced ``batch``."""
	batch_no = batch.name
	wo = (
		frappe.db.get_value(
			"Work Order",
			work_order,
			["name", "production_item", "wip_warehouse", "use_multi_level_bom"],
			as_dict=True,
		)
		or frappe._dict()
	)

	entries = batch_lineage.find_work_order_entries([work_order]).get(work_order, [])
	permitted, hidden = _permitted_names("Stock Entry", [e.name for e in entries])
	entries = [e for e in entries if e.name in permitted]
	submitted = [e for e in entries if cint(e.docstatus) == 1]
	ineffective = [e for e in entries if cint(e.docstatus) != 1]

	rows_by_entry = batch_lineage.fetch_entry_rows([e.name for e in submitted])
	bundle_map = batch_lineage.fetch_bundle_batches(batch_lineage.bundle_names(rows_by_entry))

	materials = batch_lineage.consumed_materials(submitted, rows_by_entry, bundle_map)
	share = batch_lineage.compute_share(
		batch_lineage.finished_goods(submitted, rows_by_entry, bundle_map), batch_no
	)
	wip = batch_lineage.observed_wip_warehouses(submitted, rows_by_entry)
	if wo.get("wip_warehouse"):
		wip.add(wo.wip_warehouse)

	materials_hint = (
		_("Stock UOM · whole Work Order, not apportioned to this batch")
		if share["shared"]
		else _("Stock UOM · whole Work Order")
	)
	children = [_nested_group("materials", _material_nodes(materials, batch_no), hint=materials_hint)]

	entry_nodes = _entry_nodes(submitted, rows_by_entry, wip)
	if entry_nodes or hidden:
		hint = _("{0} hidden by permissions").format(hidden) if hidden else None
		children.append(_nested_group("entries", entry_nodes, hint=hint))

	ineffective_nodes = _entry_nodes(ineffective, {}, wip)
	if ineffective_nodes:
		children.append(_nested_group("ineffective", ineffective_nodes))

	tags = []
	if share["shared"]:
		tags.append("shared_output")
	if cint(wo.get("use_multi_level_bom")):
		tags.append("multi_level_bom")

	return {
		"lineage": {
			"this_batch": share["this_batch"],
			"scrap": share["scrap"],
			"total": share["total"],
			"share": share["share"],
			"shared": share["shared"],
			"uom": batch.get("stock_uom"),
			"multi_level_bom": bool(cint(wo.get("use_multi_level_bom"))),
			"hidden_entries": hidden,
		},
		"tags": tags,
		"children": children,
	}


def _work_order_outputs(work_order: str, batch) -> dict:
	"""``{children}`` for a Work Order that consumed ``batch``: what it produced."""
	entries = [
		e
		for e in batch_lineage.find_work_order_entries([work_order]).get(work_order, [])
		if e.get("purpose") == "Manufacture" and cint(e.docstatus) == 1
	]
	permitted, _hidden = _permitted_names("Stock Entry", [e.name for e in entries])
	entries = [e for e in entries if e.name in permitted]
	if not entries:
		return {}

	rows_by_entry = batch_lineage.fetch_entry_rows([e.name for e in entries])
	bundle_map = batch_lineage.fetch_bundle_batches(batch_lineage.bundle_names(rows_by_entry))
	fg_rows = [
		r for r in batch_lineage.finished_goods(entries, rows_by_entry, bundle_map) if not r["scrap"]
	]
	if not fg_rows:
		return {}

	produced: dict[tuple, dict] = {}
	for r in fg_rows:
		key = (r["item_code"], r["batch_no"])
		m = produced.setdefault(
			key,
			{
				"item_code": r["item_code"],
				"item_name": None,
				"stock_uom": r["stock_uom"],
				"batch_no": r["batch_no"],
				"qty": 0.0,
				"lines": [],
			},
		)
		m["qty"] = flt(m["qty"]) + flt(r["qty"])
		m["lines"].append(
			{
				"stock_entry": r["stock_entry"],
				"purpose": "Manufacture",
				"posting_date": r["posting_date"],
				"s_warehouse": None,
				"qty": flt(r["qty"]),
				"split": None,
			}
		)
	nodes = _material_nodes(
		[produced[k] for k in sorted(produced, key=lambda k: (k[0] or "", k[1] or ""))],
		batch.name,
		tag="produced",
	)
	return {"children": [_nested_group("produced", nodes)]}


def _material_nodes(materials: list[dict], batch_no: str, tag: str = "consumed") -> list[dict]:
	"""Leaf nodes for consumed (or produced) materials, one per item + batch."""
	if not materials:
		return []

	batch_names = [m["batch_no"] for m in materials if m.get("batch_no")]
	batch_meta = {}
	if batch_names:
		batch_meta = {
			r.name: r
			for r in frappe.get_list(
				"Batch",
				filters={"name": ["in", list(dict.fromkeys(batch_names))]},
				fields=["name", "expiry_date", "disabled"],
				limit_page_length=0,
			)
		}
	today = getdate(nowdate())

	item_codes = list(dict.fromkeys(m["item_code"] for m in materials if not m.get("item_name")))
	item_names = {}
	if item_codes:
		item_names = {
			r.name: r.item_name
			for r in frappe.get_all("Item", filters={"name": ["in", item_codes]}, fields=["name", "item_name"])
		}

	nodes = []
	for m in materials:
		is_batch = bool(m.get("batch_no"))
		item_name = m.get("item_name") or item_names.get(m["item_code"])
		tags = [tag]
		route = None
		if is_batch:
			meta = batch_meta.get(m["batch_no"])
			if m["batch_no"] == batch_no:
				tags.append("this_batch")
			elif meta is not None:
				route = ["batch-explorer", m["batch_no"]]
			if meta is not None:
				if meta.get("expiry_date") and getdate(meta.expiry_date) < today:
					tags.append("expired")
				if cint(meta.get("disabled")):
					tags.append("disabled")
		else:
			tags.append("no_batch")
			route = ["Form", "Item", m["item_code"]]

		nodes.append(
			{
				"doctype": "Batch" if is_batch else "Item",
				"name": m["batch_no"] if is_batch else m["item_code"],
				"qty": flt(m["qty"]),
				"uom": m.get("stock_uom"),
				"neutral": True,
				"direction": None,
				"date": None,
				"owner": None,
				"owner_name": None,
				"docstatus": None,
				"status": "",
				"party": None,
				"extra": " · ".join(x for x in ([m["item_code"], item_name] if is_batch else [item_name]) if x),
				"item_code": m["item_code"],
				"tags": tags,
				"route": route,
				"lines": [
					{
						"stock_entry": ln["stock_entry"],
						"purpose": ln["purpose"],
						"date": ln.get("posting_date"),
						"warehouse": ln.get("s_warehouse"),
						"qty": flt(ln["qty"]),
						"split": "{0}/{1}".format(*ln["split"]) if ln.get("split") else None,
					}
					for ln in m.get("lines", [])
				],
			}
		)
	return nodes


def _entry_nodes(entries: list, rows_by_entry: dict[str, list], wip: set[str]) -> list[dict]:
	"""Quantity-less Stock Entry nodes tagged by their role in the Work Order."""
	if not entries:
		return []
	by_name = {e.name: e for e in entries}
	names_qty = {e.name: {"qty": None, "date": e.get("posting_date")} for e in entries}
	nodes = _build_nodes("Stock Entry", names_qty)
	for node in nodes:
		e = by_name.get(node["name"])
		if e is None:
			continue
		rows = rows_by_entry.get(e.name, [])
		tag = batch_lineage.classify_entry(e, rows, wip)
		node["tags"] = [tag]
		if tag == batch_lineage.TAG_SURPLUS_STAGED and e.get("originating_work_orders"):
			node["tag_detail"] = ", ".join(e.originating_work_orders)
		src, dst = batch_lineage.entry_warehouses(e, rows)
		purpose = e.get("stock_entry_type") or e.get("purpose")
		route = " → ".join(x for x in (src, dst) if x) if (src or dst) else None
		node["extra"] = " · ".join(x for x in (purpose, route) if x)
	return nodes


def _nested_label(key: str) -> str:
	return {
		"materials": _("Materials consumed"),
		"entries": _("Work Order stock entries"),
		"ineffective": _("Not effective"),
		"produced": _("Produced"),
	}[key]


def _nested_group(key: str, nodes: list[dict], hint: str | None = None) -> dict:
	meta = NESTED_META[key]
	return {
		"key": key,
		"doctype": None,
		"label": _nested_label(key),
		"color": meta["color"],
		"category": "Production",
		"count": len(nodes),
		"total_qty": None,
		"nodes": nodes,
		"sub": True,
		"hint": hint,
	}


# ---------------------------------------------------------------------------
# user-name helpers
# ---------------------------------------------------------------------------

def _user_name(user: str | None) -> str | None:
	if not user:
		return None
	return frappe.db.get_value("User", user, "full_name") or user


def _user_names(users: set[str]) -> dict[str, str]:
	users = {u for u in users if u}
	if not users:
		return {}
	rows = frappe.get_all("User", filters={"name": ["in", list(users)]}, fields=["name", "full_name"])
	return {r.name: (r.full_name or r.name) for r in rows}
