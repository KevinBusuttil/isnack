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

All per-document reads go through ``frappe.get_all`` so the caller only ever
sees documents they are permitted to read.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

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

_DOCSTATUS_LABEL = {0: "Draft", 1: "Submitted", 2: "Cancelled"}


@frappe.whitelist()
def get_batch_usage(batch_no: str | None = None):
	"""Return ``{batch, groups, summary}`` describing where ``batch_no`` was used."""
	batch_no = (batch_no or "").strip()
	if not batch_no:
		frappe.throw(_("Please select a Batch."))

	if not frappe.has_permission("Batch", "read"):
		raise frappe.PermissionError(_("Not permitted to read Batch."))

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

	# 1) direct stock vouchers from the Stock Ledger
	direct = _direct_vouchers(batch_no)

	# 2) derive related Work Orders / Sales Orders / Purchase Orders
	derived = _derived_vouchers(direct)

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

	return {
		"batch": batch,
		"groups": groups,
		"summary": {
			"transactions": sum(g["count"] for g in groups),
			"doctypes": len(groups),
		},
	}


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

def _derived_vouchers(direct: dict[str, dict]) -> dict[str, set]:
	derived: dict[str, set] = {}

	se_names = list(direct.get("Stock Entry", {}).keys())
	dn_names = list(direct.get("Delivery Note", {}).keys())
	si_names = list(direct.get("Sales Invoice", {}).keys())
	pr_names = list(direct.get("Purchase Receipt", {}).keys())
	pi_names = list(direct.get("Purchase Invoice", {}).keys())

	# Work Orders linked to the Stock Entries (manufacture, transfer, issue ...)
	if se_names:
		work_orders = {
			r.work_order
			for r in frappe.get_all(
				"Stock Entry",
				filters={"name": ["in", se_names], "work_order": ["is", "set"]},
				fields=["work_order"],
			)
			if r.work_order
		}
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
# Step 3 - build display nodes for a doctype (permission-checked)
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
