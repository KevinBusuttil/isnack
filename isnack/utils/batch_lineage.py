# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""Batch lineage: from a Work Order to the Stock Entries it booked and on to the
raw-material batches those entries consumed.

Used by the Batch Explorer page to render the "production inputs" level under
each Work Order that produced a batch. The Customs Export Traceability Report
applies the same consumption predicate today and is a candidate to migrate onto
these helpers in a separate change.

Design rules
------------
* Nothing here checks permissions or reads request state. Callers decide which
  Work Orders / Stock Entries the user may see and pass names in. Reads use
  ``frappe.get_all`` (a raw read) and always pass ``parent_doctype`` on child
  tables so the calls stay valid if a caller ever routes them through the
  permission-aware ``frappe.get_list``.
* How a Stock Entry belongs to a Work Order mirrors what the MES itself writes:
    - ``Stock Entry.work_order`` for staging transfers, Material Request
      fulfilment, Material Transfer for Manufacture, every Material
      Consumption for Manufacture, the Manufacture entry and ``return_materials``
      (ERPNext keeps ``work_order`` on a plain Material Transfer);
    - surplus staging entries carry no ``work_order``; they list their
      originating Work Orders in the ``Surplus Originating Work Order`` child
      table (legacy rows: ``custom_originating_work_order`` only);
    - surplus sweeps to WIP carry no ``work_order`` either; the surplus entry
      they emptied is stamped ``custom_surplus_swept_by_work_order`` and
      ``custom_surplus_wip_transfer`` (legacy sweeps: remarks only);
    - end-shift WIP returns reference a line, never a Work Order, and are
      therefore not part of any Work Order's lineage.
* "Consumed" follows the rule ERPNext uses for ``Work Order Item.consumed_qty``
  and the Customs Export Traceability Report already applies: a submitted
  ``Manufacture`` or ``Material Consumption for Manufacture`` entry, a row that
  is neither the finished item nor scrap, with a source warehouse. Note that
  the Operator Hub's own "Consumed" figure counts Material Consumption for
  Manufacture entries only; the BOM remainder booked inside the Manufacture
  entry at Close Production is consumption too and is included here.
* Quantities are stock UOM everywhere: ``transfer_qty`` for rows that carry an
  explicit ``batch_no``; ``abs(Serial and Batch Entry.qty)`` for rows whose
  batches ERPNext auto-picked into a bundle (ERPNext validates that the bundle
  total equals ``transfer_qty``; entry qty is negative for outward bundles).
"""

from __future__ import annotations

from collections import OrderedDict

import frappe
from frappe.utils import cint, flt

CONSUMPTION_PURPOSES = ("Manufacture", "Material Consumption for Manufacture")

# How an entry was linked to the Work Order (see module docstring).
LINK_WORK_ORDER = "work_order"
LINK_SURPLUS_STAGED = "surplus_staged"
LINK_SURPLUS_SWEPT = "surplus_swept"

# Exact remark written by mes_ops._create_surplus_wip_transfer; used only as a
# fallback for sweeps recorded before custom_surplus_wip_transfer was stamped.
SURPLUS_SWEEP_REMARK = "Surplus swept to WIP for WO: {work_order} (from {source})"

# Remark prefixes written by the Storekeeper Hub (display classification only).
STAGING_REMARK_PREFIXES = ("Staging transfer for WO:", "Pallet:")
MR_FULFILMENT_REMARK_PREFIX = "Fulfil Material Request"

# A share of Work Order output this close to 1 counts as "all of it". Ratio
# tolerance, same magnitude as isnack.api.mes_ops.QTY_EPSILON.
SHARE_TOLERANCE = 0.0001

# Stock Entry header fields read for every candidate entry.
ENTRY_FIELDS = [
	"name",
	"work_order",
	"purpose",
	"stock_entry_type",
	"posting_date",
	"posting_time",
	"docstatus",
	"is_return",
	"remarks",
	"owner",
	"from_warehouse",
	"to_warehouse",
]
# Custom fields the MES writes; each is read only when it exists on the site.
OPTIONAL_ENTRY_FIELDS = [
	"custom_is_surplus",
	"custom_originating_work_order",
	"custom_surplus_swept_by_work_order",
	"custom_surplus_wip_transfer",
	"custom_is_end_shift_return",
]
ROW_FIELDS = [
	"name",
	"parent",
	"idx",
	"item_code",
	"item_name",
	"qty",
	"uom",
	"stock_uom",
	"transfer_qty",
	"s_warehouse",
	"t_warehouse",
	"batch_no",
	"serial_and_batch_bundle",
	"is_finished_item",
	"is_scrap_item",
]

# Display classification of an entry inside a Work Order's lineage.
TAG_MANUFACTURE = "manufacture"
TAG_CONSUMPTION = "consumption"
TAG_TO_WIP = "to_wip"
TAG_RETURN_ERPNEXT = "return_erpnext"
TAG_RETURN = "return"
TAG_MR_FULFILMENT = "mr_fulfilment"
TAG_STAGING = "staging"
TAG_SURPLUS_STAGED = "surplus_staged"
TAG_SURPLUS_SWEPT = "surplus_swept"
TAG_TRANSFER = "transfer"


def entry_fields(has_field=None) -> list[str]:
	"""Header fields to read for a Stock Entry, custom ones only when present."""
	if has_field is None:
		has_field = frappe.get_meta("Stock Entry").has_field
	return ENTRY_FIELDS + [f for f in OPTIONAL_ENTRY_FIELDS if has_field(f)]


# ---------------------------------------------------------------------------
# Work Order -> Stock Entries
# ---------------------------------------------------------------------------

def find_work_order_entries(work_orders) -> dict[str, list]:
	"""Return ``{work_order: [entry, ...]}`` for every Stock Entry that belongs to
	one of ``work_orders`` (any docstatus, any purpose).

	Each entry is the Stock Entry header (``entry_fields``) plus ``link`` (one of
	the ``LINK_*`` constants) and ``originating_work_orders`` (all Work Orders a
	surplus entry was staged for; empty otherwise). Not permission-filtered.
	"""
	wos = sorted({w for w in (work_orders or []) if w})
	if not wos:
		return {}

	has_field = frappe.get_meta("Stock Entry").has_field
	fields = entry_fields(has_field)
	result: dict[str, list] = {wo: [] for wo in wos}
	seen: set[tuple[str, str]] = set()

	def add(wo, entry, link, origin=None):
		if wo not in result:
			return
		key = (wo, entry.name)
		if key in seen:
			return
		seen.add(key)
		e = frappe._dict(entry)
		e.link = link
		e.originating_work_orders = list(origin or [])
		result[wo].append(e)

	# A. the direct link the MES writes on almost everything
	for r in frappe.get_all("Stock Entry", filters={"work_order": ["in", wos]}, fields=fields):
		add(r.work_order, r, LINK_WORK_ORDER)

	# B. surplus staged for these Work Orders (child table, legacy header field)
	if has_field("custom_is_surplus"):
		_add_surplus_staged(wos, fields, has_field, add)

	# C. surplus swept into WIP on behalf of these Work Orders
	if has_field("custom_surplus_swept_by_work_order") and has_field("custom_surplus_wip_transfer"):
		_add_surplus_swept(wos, fields, add)

	for wo in result:
		result[wo].sort(key=lambda e: (str(e.get("posting_date") or ""), str(e.get("posting_time") or ""), e.name))
	return result


def _add_surplus_staged(wos, fields, has_field, add):
	child_rows = frappe.get_all(
		"Surplus Originating Work Order",
		filters={"parenttype": "Stock Entry", "work_order": ["in", wos]},
		fields=["parent", "work_order"],
		parent_doctype="Stock Entry",
	)
	legacy = []
	if has_field("custom_originating_work_order"):
		legacy = frappe.get_all(
			"Stock Entry",
			filters={"custom_is_surplus": 1, "custom_originating_work_order": ["in", wos]},
			fields=["name", "custom_originating_work_order"],
		)
	candidates = {r.parent for r in child_rows} | {r.name for r in legacy}
	if not candidates:
		return

	entries = {
		r.name: r
		for r in frappe.get_all(
			"Stock Entry",
			filters={"name": ["in", sorted(candidates)], "custom_is_surplus": 1},
			fields=fields,
		)
	}
	if not entries:
		return

	# every originating Work Order of each surplus entry, for the tag text
	origin_by_entry: dict[str, list[str]] = {}
	for c in frappe.get_all(
		"Surplus Originating Work Order",
		filters={"parenttype": "Stock Entry", "parent": ["in", sorted(entries)]},
		fields=["parent", "work_order"],
		order_by="parent, idx",
		parent_doctype="Stock Entry",
	):
		lst = origin_by_entry.setdefault(c.parent, [])
		if c.work_order and c.work_order not in lst:
			lst.append(c.work_order)

	for c in child_rows:
		if c.parent in entries:
			add(c.work_order, entries[c.parent], LINK_SURPLUS_STAGED, origin_by_entry.get(c.parent))
	# the header field only counts when the entry has no child rows at all
	# (same rule as mes_ops._find_eligible_surplus_ses)
	for r in legacy:
		if r.name in entries and not origin_by_entry.get(r.name):
			add(
				r.custom_originating_work_order,
				entries[r.name],
				LINK_SURPLUS_STAGED,
				[r.custom_originating_work_order],
			)


def _add_surplus_swept(wos, fields, add):
	claimed = frappe.get_all(
		"Stock Entry",
		filters={"custom_surplus_swept_by_work_order": ["in", wos]},
		fields=["name", "custom_surplus_swept_by_work_order", "custom_surplus_wip_transfer"],
	)
	sweep_wo: dict[str, str] = {}
	for r in claimed:
		if r.custom_surplus_wip_transfer:
			sweep_wo[r.custom_surplus_wip_transfer] = r.custom_surplus_swept_by_work_order
			continue
		# legacy sweep: the transfer was never stamped on the source entry, but
		# its remark is written verbatim by mes_ops._create_surplus_wip_transfer
		remark = SURPLUS_SWEEP_REMARK.format(work_order=r.custom_surplus_swept_by_work_order, source=r.name)
		for s in frappe.get_all(
			"Stock Entry",
			filters={
				"purpose": "Material Transfer",
				"work_order": ["is", "not set"],
				"docstatus": 1,
				"remarks": remark,
			},
			fields=["name"],
		):
			sweep_wo[s.name] = r.custom_surplus_swept_by_work_order
	if not sweep_wo:
		return
	for e in frappe.get_all("Stock Entry", filters={"name": ["in", sorted(sweep_wo)]}, fields=fields):
		add(sweep_wo[e.name], e, LINK_SURPLUS_SWEPT)


# ---------------------------------------------------------------------------
# Stock Entry -> rows -> batches
# ---------------------------------------------------------------------------

def fetch_entry_rows(entry_names) -> dict[str, list]:
	"""Return ``{stock_entry: [Stock Entry Detail rows]}`` in row order."""
	names = [n for n in dict.fromkeys(entry_names or []) if n]
	if not names:
		return {}
	rows = frappe.get_all(
		"Stock Entry Detail",
		filters={"parenttype": "Stock Entry", "parent": ["in", names]},
		fields=ROW_FIELDS,
		order_by="parent, idx",
		parent_doctype="Stock Entry",
	)
	by_entry: dict[str, list] = {}
	for r in rows:
		by_entry.setdefault(r.parent, []).append(r)
	return by_entry


def bundle_names(rows_by_entry) -> list[str]:
	"""Bundles of rows that carry no explicit batch_no (ERPNext auto-picked)."""
	out = []
	for rows in (rows_by_entry or {}).values():
		for r in rows:
			if not r.get("batch_no") and r.get("serial_and_batch_bundle"):
				out.append(r.serial_and_batch_bundle)
	return list(dict.fromkeys(out))


def fetch_bundle_batches(bundles) -> dict[str, list[tuple[str, float]]]:
	"""Return ``{bundle: [(batch_no, qty), ...]}`` with qty positive, per batch."""
	names = [b for b in dict.fromkeys(bundles or []) if b]
	if not names:
		return {}
	rows = frappe.get_all(
		"Serial and Batch Entry",
		filters={"parent": ["in", names], "batch_no": ["is", "set"]},
		fields=["parent", "batch_no", "qty"],
		order_by="parent, idx",
		parent_doctype="Serial and Batch Bundle",
	)
	per_bundle: dict[str, OrderedDict] = {}
	for r in rows:
		batches = per_bundle.setdefault(r.parent, OrderedDict())
		batches[r.batch_no] = flt(batches.get(r.batch_no, 0)) + abs(flt(r.qty))
	return {b: list(batches.items()) for b, batches in per_bundle.items()}


def expand_row_batches(row, bundle_map) -> list[dict]:
	"""Split one Stock Entry Detail row into ``[{batch_no, qty, split}]``.

	``qty`` is stock UOM. ``split`` is ``(i, n)`` when the row's bundle held
	several batches, else ``None``. ``batch_no`` is ``None`` for non-batch items.
	"""
	row_qty = flt(row.get("transfer_qty")) or flt(row.get("qty"))
	if row.get("batch_no"):
		return [{"batch_no": row.batch_no, "qty": row_qty, "split": None}]
	entries = (bundle_map or {}).get(row.get("serial_and_batch_bundle")) or []
	if entries:
		n = len(entries)
		return [
			{"batch_no": b, "qty": flt(q), "split": (i + 1, n) if n > 1 else None}
			for i, (b, q) in enumerate(entries)
		]
	return [{"batch_no": None, "qty": row_qty, "split": None}]


def is_consumed_row(entry, row) -> bool:
	"""The consumption rule shared with ERPNext consumed_qty and the customs report."""
	return (
		cint(entry.get("docstatus")) == 1
		and entry.get("purpose") in CONSUMPTION_PURPOSES
		and not cint(row.get("is_finished_item"))
		and not cint(row.get("is_scrap_item"))
		and bool(row.get("s_warehouse"))
	)


def consumed_materials(entries, rows_by_entry, bundle_map) -> list[dict]:
	"""Aggregate consumed rows per ``(item_code, batch_no)`` with per-entry evidence.

	Returns a list sorted by item code then batch, each item::

	    {item_code, item_name, stock_uom, batch_no, qty,
	     lines: [{stock_entry, purpose, posting_date, s_warehouse, qty, split}]}
	"""
	agg: dict[tuple, dict] = {}
	for entry in entries or []:
		for row in (rows_by_entry or {}).get(entry.name, []):
			if not is_consumed_row(entry, row):
				continue
			for part in expand_row_batches(row, bundle_map):
				key = (row.item_code, part["batch_no"])
				m = agg.get(key)
				if m is None:
					m = agg[key] = {
						"item_code": row.item_code,
						"item_name": row.get("item_name"),
						"stock_uom": row.get("stock_uom") or row.get("uom"),
						"batch_no": part["batch_no"],
						"qty": 0.0,
						"lines": [],
					}
				m["qty"] = flt(m["qty"]) + flt(part["qty"])
				m["lines"].append(
					{
						"stock_entry": entry.name,
						"purpose": entry.get("purpose"),
						"posting_date": str(entry.get("posting_date") or "") or None,
						"s_warehouse": row.get("s_warehouse"),
						"qty": flt(part["qty"]),
						"split": part["split"],
					}
				)
	return [agg[k] for k in sorted(agg, key=lambda k: (k[0] or "", k[1] or ""))]


def finished_goods(entries, rows_by_entry, bundle_map) -> list[dict]:
	"""Finished-item and scrap rows of submitted Manufacture entries, per batch.

	Each item: ``{stock_entry, item_code, stock_uom, batch_no, qty, scrap, posting_date}``.
	"""
	out = []
	for entry in entries or []:
		if entry.get("purpose") != "Manufacture" or cint(entry.get("docstatus")) != 1:
			continue
		for row in (rows_by_entry or {}).get(entry.name, []):
			finished = cint(row.get("is_finished_item"))
			scrap = cint(row.get("is_scrap_item"))
			if not finished and not scrap:
				continue
			for part in expand_row_batches(row, bundle_map):
				out.append(
					{
						"stock_entry": entry.name,
						"item_code": row.item_code,
						"stock_uom": row.get("stock_uom") or row.get("uom"),
						"batch_no": part["batch_no"],
						"qty": flt(part["qty"]),
						"scrap": bool(scrap),
						"posting_date": str(entry.get("posting_date") or "") or None,
					}
				)
	return out


def compute_share(fg_rows, batch_no) -> dict:
	"""How much of a Work Order's good output went into ``batch_no``.

	Scrap rows carry the same finished-goods batch and are reported separately;
	they are excluded from both numerator and denominator.
	"""
	this_batch = scrap = total = 0.0
	for r in fg_rows or []:
		if r.get("scrap"):
			if r.get("batch_no") == batch_no:
				scrap += flt(r.get("qty"))
			continue
		total += flt(r.get("qty"))
		if r.get("batch_no") == batch_no:
			this_batch += flt(r.get("qty"))
	share = (this_batch / total) if total > 0 else None
	return {
		"this_batch": this_batch,
		"scrap": scrap,
		"total": total,
		"share": share,
		"shared": share is not None and share < 1 - SHARE_TOLERANCE,
	}


# ---------------------------------------------------------------------------
# Entry classification (display only, never affects quantities)
# ---------------------------------------------------------------------------

def observed_wip_warehouses(entries, rows_by_entry) -> set[str]:
	"""Warehouses the Work Order's own entries treat as WIP.

	Material Transfer for Manufacture delivers into WIP; Material Consumption for
	Manufacture consumes from it. ``Work Order.wip_warehouse`` alone is not
	reliable because the MES resolves WIP from the line map.
	"""
	wip: set[str] = set()
	for entry in entries or []:
		purpose = entry.get("purpose")
		for row in (rows_by_entry or {}).get(entry.name, []):
			if purpose == "Material Transfer for Manufacture" and row.get("t_warehouse"):
				wip.add(row.t_warehouse)
			elif purpose == "Material Consumption for Manufacture" and row.get("s_warehouse"):
				wip.add(row.s_warehouse)
	return wip


def classify_entry(entry, rows=None, wip_warehouses=None) -> str:
	"""Return one of the ``TAG_*`` constants for an entry of a Work Order's lineage."""
	link = entry.get("link")
	if link == LINK_SURPLUS_STAGED:
		return TAG_SURPLUS_STAGED
	if link == LINK_SURPLUS_SWEPT:
		return TAG_SURPLUS_SWEPT

	purpose = entry.get("purpose")
	if purpose == "Manufacture":
		return TAG_MANUFACTURE
	if purpose == "Material Consumption for Manufacture":
		return TAG_CONSUMPTION
	if purpose == "Material Transfer for Manufacture":
		return TAG_RETURN_ERPNEXT if cint(entry.get("is_return")) else TAG_TO_WIP
	if purpose == "Material Transfer":
		remarks = (entry.get("remarks") or "").strip()
		if remarks.startswith(MR_FULFILMENT_REMARK_PREFIX):
			return TAG_MR_FULFILMENT
		if remarks.startswith(STAGING_REMARK_PREFIXES):
			return TAG_STAGING
		# return_materials writes neither header warehouses nor remarks: a plain
		# transfer whose every row leaves WIP is a return to staging
		sources = {r.get("s_warehouse") for r in (rows or []) if r.get("s_warehouse")}
		if sources and wip_warehouses and sources <= set(wip_warehouses):
			return TAG_RETURN
		return TAG_TRANSFER
	return TAG_TRANSFER


def entry_warehouses(entry, rows=None) -> tuple[str | None, str | None]:
	"""``(from, to)`` for display: header fields, else derived from the rows.

	Returns ``"*"`` for a side whose rows disagree.
	"""
	src = entry.get("from_warehouse")
	dst = entry.get("to_warehouse")
	if not src:
		sources = {r.get("s_warehouse") for r in (rows or []) if r.get("s_warehouse")}
		src = next(iter(sources)) if len(sources) == 1 else ("*" if sources else None)
	if not dst:
		targets = {r.get("t_warehouse") for r in (rows or []) if r.get("t_warehouse")}
		dst = next(iter(targets)) if len(targets) == 1 else ("*" if targets else None)
	return src, dst
