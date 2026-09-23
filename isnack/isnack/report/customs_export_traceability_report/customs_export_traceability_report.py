# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import base64
import json
import os
import re
from collections import OrderedDict
from html import unescape
from io import BytesIO

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate, now_datetime

from isnack.utils import batch_lineage
from isnack.utils.qty import qty_tick

# Semi-finished levels followed below a finished-goods Work Order, at most.
MAX_SFG_DEPTH = 3


def execute(filters=None):
	filters = frappe._dict(filters or {})
	validate_filters(filters)
	columns = get_columns()
	data = get_data(filters)
	return columns, data


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_filters(filters):
	for fld in ("company", "from_date", "to_date"):
		if not filters.get(fld):
			frappe.throw(_("Filter {0} is required").format(fld))
	if getdate(filters.from_date) > getdate(filters.to_date):
		frappe.throw(_("From Date must be on or before To Date"))


# ---------------------------------------------------------------------------
# Columns
# ---------------------------------------------------------------------------

def get_columns():
	return [
		# A. Sales Invoice context
		{"label": _("Company"), "fieldname": "company", "fieldtype": "Link", "options": "Company", "width": 120},
		{"label": _("Sales Invoice"), "fieldname": "sales_invoice", "fieldtype": "Link", "options": "Sales Invoice", "width": 150},
		{"label": _("Posting Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 100},
		{"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 120},
		{"label": _("Customer Name"), "fieldname": "customer_name", "fieldtype": "Data", "width": 160},
		{"label": _("Currency"), "fieldname": "currency", "fieldtype": "Link", "options": "Currency", "width": 80},
		{"label": _("Row #"), "fieldname": "si_item_idx", "fieldtype": "Int", "width": 60},
		{"label": _("FG Item Code"), "fieldname": "fg_item_code", "fieldtype": "Link", "options": "Item", "width": 140},
		{"label": _("FG Item Name"), "fieldname": "fg_item_name", "fieldtype": "Data", "width": 160},
		{"label": _("FG Description"), "fieldname": "fg_description", "fieldtype": "Data", "width": 180},
		{"label": _("Sales Qty"), "fieldname": "sales_qty", "fieldtype": "Float", "width": 90},
		{"label": _("Sales UOM"), "fieldname": "sales_uom", "fieldtype": "Link", "options": "UOM", "width": 80},
		{"label": _("Stock Qty"), "fieldname": "stock_qty", "fieldtype": "Float", "width": 90},
		{"label": _("FG Net Weight"), "fieldname": "fg_net_weight", "fieldtype": "Float", "precision": 3, "width": 110},
		{"label": _("FG Gross Weight"), "fieldname": "fg_gross_weight", "fieldtype": "Float", "precision": 3, "width": 110},
		{"label": _("FG Weight UOM"), "fieldname": "fg_weight_uom", "fieldtype": "Link", "options": "UOM", "width": 100},
		{"label": _("FG Total Volume"), "fieldname": "fg_total_volume", "fieldtype": "Float", "precision": 3, "width": 120},
		{"label": _("FG Volume UOM"), "fieldname": "fg_volume_uom", "fieldtype": "Link", "options": "UOM", "width": 100},
		{"label": _("Item Group"), "fieldname": "item_group", "fieldtype": "Link", "options": "Item Group", "width": 120},
		# B. Finished good traceability
		{"label": _("FG Batch No"), "fieldname": "fg_batch_no", "fieldtype": "Link", "options": "Batch", "width": 130},
		{"label": _("Batch Sold Qty"), "fieldname": "batch_sold_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Batch Produced Qty"), "fieldname": "batch_produced_qty", "fieldtype": "Float", "width": 110},
		{"label": _("Work Order"), "fieldname": "work_order", "fieldtype": "Link", "options": "Work Order", "width": 150},
		{"label": _("WO Item"), "fieldname": "wo_item", "fieldtype": "Link", "options": "Item", "width": 130},
		{"label": _("WO Qty"), "fieldname": "wo_qty", "fieldtype": "Float", "width": 80},
		{"label": _("Manufacturing Date"), "fieldname": "manufacturing_date", "fieldtype": "Date", "width": 110},
		{"label": _("Manufacture Entry"), "fieldname": "manufacture_entry", "fieldtype": "Link", "options": "Stock Entry", "width": 150},
		# C. Raw material consumption
		{"label": _("RM Item Code"), "fieldname": "rm_item_code", "fieldtype": "Link", "options": "Item", "width": 140},
		{"label": _("RM Item Name"), "fieldname": "rm_item_name", "fieldtype": "Data", "width": 160},
		{"label": _("RM Description"), "fieldname": "rm_description", "fieldtype": "Data", "width": 180},
		{"label": _("Via Semi-Finished"), "fieldname": "via_sfg", "fieldtype": "Data", "width": 220},
		{"label": _("SFG Attribution"), "fieldname": "sfg_attribution", "fieldtype": "Data", "width": 200},
		{"label": _("RM UOM"), "fieldname": "rm_uom", "fieldtype": "Link", "options": "UOM", "width": 80},
		{"label": _("Consumed Qty"), "fieldname": "consumed_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Consumed Cost"), "fieldname": "consumed_cost", "fieldtype": "Currency", "options": "Company:company:default_currency", "width": 110},
		{"label": _("Apportioned Qty"), "fieldname": "apportioned_qty", "fieldtype": "Float", "width": 110},
		{"label": _("Apportioned Cost"), "fieldname": "apportioned_cost", "fieldtype": "Currency", "options": "Company:company:default_currency", "width": 120},
		{"label": _("RM Batch No"), "fieldname": "rm_batch_no", "fieldtype": "Link", "options": "Batch", "width": 130},
		# D. Purchase / customs traceability
		{"label": _("Purchase Receipt"), "fieldname": "purchase_receipt", "fieldtype": "Link", "options": "Purchase Receipt", "width": 150},
		{"label": _("PR Date"), "fieldname": "purchase_receipt_date", "fieldtype": "Date", "width": 100},
		{"label": _("Supplier Name"), "fieldname": "supplier_name", "fieldtype": "Data", "width": 160},
		{"label": _("PR Qty"), "fieldname": "pr_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Balance Stock"), "fieldname": "balance_stock", "fieldtype": "Float", "width": 110},
		{"label": _("Customs Document No"), "fieldname": "customs_document_no", "fieldtype": "Data", "width": 180},
	]


# ---------------------------------------------------------------------------
# Data assembly
# ---------------------------------------------------------------------------

def get_data(filters):
	# Step 1: Fetch SI items
	si_items = _fetch_si_items(filters)
	if not si_items:
		return []

	# Step 2: Resolve FG batches per SI item (direct + via bundle)
	bundle_names = [r.serial_and_batch_bundle for r in si_items if r.serial_and_batch_bundle and not r.batch_no]
	bundle_entries = _fetch_bundle_entries(bundle_names)  # {bundle_name: [{batch_no, qty}]}

	# Step 3: Collect all FG (item_code, batch_no) pairs to find Work Orders
	fg_batch_pairs = set()
	for row in si_items:
		if row.batch_no:
			fg_batch_pairs.add((row.fg_item_code, row.batch_no))
		elif row.serial_and_batch_bundle and bundle_entries.get(row.serial_and_batch_bundle):
			for be in bundle_entries[row.serial_and_batch_bundle]:
				if be["batch_no"]:
					fg_batch_pairs.add((row.fg_item_code, be["batch_no"]))

	# Step 4: Resolve Work Orders for FG batches
	wo_map = _fetch_manufacture_entries(fg_batch_pairs)  # {(item_code, batch_no): [{work_order, ...}]}

	# Step 4b: Finished-goods qty booked into each FG batch by every submitted
	# Manufacture entry, with or without a Work Order. This is the denominator
	# of the apportioning: what share of the batch this invoice line took.
	batch_produced_map = _fetch_batch_produced_qty(fg_batch_pairs)  # {(item_code, batch_no): qty}

	# Step 5: Collect all work orders → resolve consumed raw materials
	all_work_orders = set()
	for entries in wo_map.values():
		for e in entries:
			if e.get("work_order"):
				all_work_orders.add(e["work_order"])

	rm_map = _fetch_rm_consumption(all_work_orders, filters)  # {work_order: [rm_dict]}

	# Step 6: Collect all PR names → resolve PR details (incl. customs doc no)
	pr_names = set()
	for rm_list in rm_map.values():
		for rm in rm_list:
			if rm.get("purchase_receipt"):
				pr_names.add(rm["purchase_receipt"])
	pr_details = _fetch_pr_details(pr_names)  # {pr_name: {...}}

	# Step 6b: Fetch PR item quantities for (pr_name, item_code, batch_no) combos
	pr_batch_keys = set()
	for rm_list in rm_map.values():
		for rm in rm_list:
			if rm.get("purchase_receipt") and rm.get("item_code") and rm.get("batch_no"):
				pr_batch_keys.add((rm["purchase_receipt"], rm["item_code"], rm["batch_no"]))
	pr_item_qty_map = _fetch_pr_item_qty(pr_batch_keys)  # {(pr_name, item_code, batch_no): qty}

	# Step 6c: Fetch balance stock for (item_code, batch_no) pairs
	batch_item_pairs = set()
	for rm_list in rm_map.values():
		for rm in rm_list:
			if rm.get("item_code") and rm.get("batch_no"):
				batch_item_pairs.add((rm["item_code"], rm["batch_no"]))
	batch_balance_map = _fetch_batch_balance(batch_item_pairs)  # {(item_code, batch_no): qty}

	# Step 7: Assemble output rows
	rows = []
	for si_row in si_items:
		# Build list of (fg_batch_no, batch_sold_qty) for this SI item
		fg_batches = _resolve_fg_batches(si_row, bundle_entries)

		for fg_batch_no, batch_sold_qty in fg_batches:
			batch_produced_qty = (
				batch_produced_map.get((si_row.fg_item_code, fg_batch_no)) if fg_batch_no else None
			)
			wo_entries = _one_entry_per_work_order(wo_map.get((si_row.fg_item_code, fg_batch_no)) or [{}])
			for wo_entry in wo_entries:
				work_order = wo_entry.get("work_order")
				rm_list = rm_map.get(work_order) or [{}] if work_order else [{}]
				# Share of this Work Order's consumption that belongs to the
				# cartons of this batch sold on this invoice line (None when
				# it cannot be established).
				factor = (
					_apportionment_factor(
						batch_sold_qty,
						batch_produced_qty,
						wo_entry.get("fg_qty"),
						wo_entry.get("wo_fg_qty"),
					)
					if work_order
					else None
				)
				for rm in rm_list:
					pr_name = rm.get("purchase_receipt")
					pr = pr_details.get(pr_name) or {} if pr_name else {}

					# Calculate FG net/gross weight and volume (based on sales qty).
					# Item.weight_per_unit is the GROSS weight (net + tare); the net
					# weight per unit is stored on custom_net_weight_per_unit.
					_sales_qty = frappe.utils.flt(si_row.qty)
					_gross_weight_per_unit = frappe.utils.flt(si_row.get("weight_per_unit"))
					_net_weight_per_unit = frappe.utils.flt(si_row.get("custom_net_weight_per_unit"))
					_volume_per_unit = frappe.utils.flt(si_row.get("custom_volume_per_unit"))
					_fg_net_weight = frappe.utils.flt(_sales_qty * _net_weight_per_unit, 3) if (_sales_qty and _net_weight_per_unit) else None
					_fg_gross_weight = frappe.utils.flt(_sales_qty * _gross_weight_per_unit, 3) if (_sales_qty and _gross_weight_per_unit) else None
					_fg_total_volume = frappe.utils.flt(_sales_qty * _volume_per_unit, 3) if (_sales_qty and _volume_per_unit) else None

					row = frappe._dict(
						# A
						company=si_row.company,
						sales_invoice=si_row.sales_invoice,
						posting_date=si_row.posting_date,
						customer=si_row.customer,
						customer_name=si_row.customer_name,
						currency=si_row.currency,
						si_item_idx=si_row.idx,
						fg_item_code=si_row.fg_item_code,
						fg_item_name=si_row.fg_item_name,
						fg_description=si_row.fg_description,
						sales_qty=si_row.qty,
						sales_uom=si_row.uom,
						stock_qty=si_row.stock_qty,
						fg_net_weight=_fg_net_weight,
						fg_gross_weight=_fg_gross_weight,
						fg_weight_uom=si_row.get("weight_uom") or None,
						fg_total_volume=_fg_total_volume,
						fg_volume_uom=si_row.get("custom_volume_uom") or None,
						item_group=si_row.item_group,
						# B
						fg_batch_no=fg_batch_no or None,
						batch_sold_qty=batch_sold_qty,
						batch_produced_qty=batch_produced_qty,
						work_order=work_order,
						wo_item=wo_entry.get("wo_item"),
						wo_qty=wo_entry.get("wo_qty"),
						manufacturing_date=wo_entry.get("manufacturing_date"),
						manufacture_entry=wo_entry.get("stock_entry"),
						# C
						rm_item_code=rm.get("item_code"),
						rm_item_name=rm.get("item_name"),
						rm_description=rm.get("description"),
						via_sfg=rm.get("via_sfg"),
						sfg_attribution=rm.get("sfg_attribution"),
						rm_uom=rm.get("stock_uom"),
						consumed_qty=rm.get("qty"),
						consumed_cost=rm.get("consumed_cost"),
						apportioned_qty=_apportion(rm.get("qty"), factor),
						apportioned_cost=_apportion(rm.get("consumed_cost"), factor),
						rm_batch_no=rm.get("batch_no"),
						# D
						purchase_receipt=pr_name,
						purchase_receipt_date=pr.get("posting_date"),
						supplier=pr.get("supplier"),
						supplier_name=pr.get("supplier_name"),
						pr_qty=pr_item_qty_map.get((pr_name, rm.get("item_code"), rm.get("batch_no")), 0) or None,
						balance_stock=batch_balance_map.get((rm.get("item_code"), rm.get("batch_no")), 0) or None,
						customs_document_no=pr.get("custom_customs_document_no"),
					)

					if passes_post_filters(row, filters):
						rows.append(row)

	return rows


# ---------------------------------------------------------------------------
# Post-filter (for filters that can't be pushed to initial SQL)
# ---------------------------------------------------------------------------

def passes_post_filters(row, filters):
	if filters.get("work_order") and row.get("work_order") != filters.work_order:
		return False
	if filters.get("purchase_receipt") and row.get("purchase_receipt") != filters.purchase_receipt:
		return False
	if filters.get("customs_document_no"):
		cdn = (row.get("customs_document_no") or "").lower()
		if filters.customs_document_no.lower() not in cdn:
			return False
	return True


# ---------------------------------------------------------------------------
# Helper: resolve FG batch list for a single SI item row
# ---------------------------------------------------------------------------

def _resolve_fg_batches(si_row, bundle_entries):
	"""Return a list of ``(fg_batch_no, batch_sold_qty)`` for one SI item row.

	``batch_sold_qty`` is the stock qty of that batch billed on the line: the
	line's stock qty for a direct batch, else each batch's qty in the Serial and
	Batch Bundle. An invoice billed from a Delivery Note resolves through the
	DN's bundle, which carries the delivered qty; that is scaled to the invoiced
	stock qty so a partially invoiced delivery apportions only what this line
	bills. Bundle quantities are unsigned, so the sign comes from the invoiced
	stock qty as well: a return (credit note) reverses the sold and apportioned
	figures the way the direct-batch path does. ``[(None, None)]`` when no
	batch can be established.
	"""
	stock_qty = flt(si_row.stock_qty)
	if si_row.batch_no:
		return [(si_row.batch_no, stock_qty)]
	if si_row.serial_and_batch_bundle:
		per_batch = OrderedDict()
		for e in bundle_entries.get(si_row.serial_and_batch_bundle) or []:
			if e.get("batch_no"):
				per_batch[e["batch_no"]] = flt(per_batch.get(e["batch_no"])) + abs(flt(e.get("qty")))
		if per_batch:
			bundle_qty = sum(per_batch.values())
			scale = stock_qty / bundle_qty if (bundle_qty > 0 and stock_qty) else 1.0
			return [(batch_no, qty * scale) for batch_no, qty in per_batch.items()]
	return [(None, None)]


def _apportionment_factor(batch_sold_qty, batch_produced_qty, entry_fg_qty, wo_fg_qty):
	"""Fraction of a Work Order's consumption embodied in the cartons of one FG
	batch sold on one invoice line.

	``batch_sold_qty / batch_produced_qty`` is the share of the batch this line
	took; every Work Order that fed the batch is scaled by it, which mirrors the
	batch-wise moving average ERPNext values the delivery at. When the Work
	Order's Manufacture entry booked only part of the order's output into this
	batch (``entry_fg_qty`` of ``wo_fg_qty``), that part is scaled as well.
	Returns ``None`` when the sold or produced qty is unknown.
	"""
	if batch_sold_qty is None or batch_produced_qty is None:
		return None
	produced = flt(batch_produced_qty)
	if produced <= 0:
		return None
	wo_share = 1.0
	if entry_fg_qty is not None and flt(wo_fg_qty) > 0:
		wo_share = flt(entry_fg_qty) / flt(wo_fg_qty)
	return wo_share * flt(batch_sold_qty) / produced


def _apportion(value, factor):
	"""``value * factor``; ``None`` when either side is unknown."""
	if value is None or factor is None:
		return None
	return flt(value) * factor


def _one_entry_per_work_order(entries):
	"""Merge a Work Order's Manufacture entries into one batch into one entry.

	The rows under an entry carry the Work Order's whole consumption, so a Work
	Order that booked the batch in two entries would list it twice. Its entries'
	finished qty is summed for the apportioning; the first entry names the row.
	"""
	merged = OrderedDict()
	for i, e in enumerate(entries):
		wo = e.get("work_order")
		if not wo:
			merged[("no work order", i)] = e
			continue
		m = merged.get(wo)
		if m is None:
			merged[wo] = dict(e)
		elif m.get("fg_qty") is not None or e.get("fg_qty") is not None:
			m["fg_qty"] = flt(m.get("fg_qty")) + flt(e.get("fg_qty"))
	return list(merged.values())


# ---------------------------------------------------------------------------
# Step 1: Fetch Sales Invoice Items
# ---------------------------------------------------------------------------

def _fetch_si_items(filters):
	conditions = [
		"si.docstatus = 1",
		"si.company = %(company)s",
		"si.posting_date BETWEEN %(from_date)s AND %(to_date)s",
	]
	values = {
		"company": filters.company,
		"from_date": filters.from_date,
		"to_date": filters.to_date,
	}

	if filters.get("sales_invoice"):
		conditions.append("si.name = %(sales_invoice)s")
		values["sales_invoice"] = filters.sales_invoice

	if filters.get("customer"):
		conditions.append("si.customer = %(customer)s")
		values["customer"] = filters.customer

	if filters.get("item_code"):
		conditions.append("sii.item_code = %(item_code)s")
		values["item_code"] = filters.item_code

	if filters.get("item_group"):
		conditions.append("sii.item_group = %(item_group)s")
		values["item_group"] = filters.item_group

	# Batch filter: directly on sii.batch_no, via the SI item's bundle, or —
	# for invoices billed from a Delivery Note that carry no batch data of
	# their own — via the linked Delivery Note Item's batch_no / bundle.
	if filters.get("batch_no"):
		conditions.append("""(
			sii.batch_no = %(batch_no)s
			OR EXISTS (
				SELECT 1 FROM `tabSerial and Batch Entry` sbe
				WHERE sbe.parent = sii.serial_and_batch_bundle
				AND sbe.batch_no = %(batch_no)s
			)
			OR dni.batch_no = %(batch_no)s
			OR EXISTS (
				SELECT 1 FROM `tabSerial and Batch Entry` dn_sbe
				WHERE dn_sbe.parent = dni.serial_and_batch_bundle
				AND dn_sbe.batch_no = %(batch_no)s
			)
		)""")
		values["batch_no"] = filters.batch_no

	where_clause = " AND ".join(conditions)

	rows = frappe.db.sql(
		f"""
		SELECT
			si.name          AS sales_invoice,
			si.company,
			si.posting_date,
			si.customer,
			si.customer_name,
			si.currency,
			sii.idx,
			sii.item_code    AS fg_item_code,
			sii.item_name    AS fg_item_name,
			sii.description  AS fg_description,
			sii.qty,
			sii.uom,
			sii.stock_qty,
			sii.item_group,
			sii.batch_no,
			sii.serial_and_batch_bundle,
			dni.batch_no     AS dn_batch_no,
			dni.serial_and_batch_bundle AS dn_serial_and_batch_bundle,
			item.weight_per_unit,
			item.custom_net_weight_per_unit,
			item.weight_uom,
			item.custom_volume_per_unit,
			item.custom_volume_uom
		FROM `tabSales Invoice Item` sii
		JOIN `tabSales Invoice` si ON si.name = sii.parent
		LEFT JOIN `tabDelivery Note Item` dni
			ON dni.name = sii.dn_detail AND dni.docstatus = 1
		LEFT JOIN `tabItem` item ON item.name = sii.item_code
		WHERE {where_clause}
		ORDER BY si.posting_date, si.name, sii.idx
		""",
		values,
		as_dict=True,
	)

	# Fallback: an invoice billed from a Delivery Note (update_stock = 0)
	# usually carries no batch data of its own. When the DN row used the
	# legacy batch_no field it is copied onto the SI item, but batches picked
	# via a Serial and Batch Bundle stay on the DN — the bundle is bound to
	# the DN voucher and cannot be copied to the invoice. Resolve those rows
	# through the linked Delivery Note Item so traceability still works.
	for row in rows:
		if not row.batch_no and not row.serial_and_batch_bundle:
			row.batch_no = row.dn_batch_no
			row.serial_and_batch_bundle = row.dn_serial_and_batch_bundle

	return rows


# ---------------------------------------------------------------------------
# Step 2: Batch-fetch Serial and Batch Bundle entries
# ---------------------------------------------------------------------------

def _fetch_bundle_entries(bundle_names):
	"""Return {bundle_name: [{batch_no, qty}]}"""
	if not bundle_names:
		return {}
	placeholders = ", ".join(["%s"] * len(bundle_names))
	rows = frappe.db.sql(
		f"""
		SELECT parent, batch_no, qty
		FROM `tabSerial and Batch Entry`
		WHERE parent IN ({placeholders})
		AND batch_no IS NOT NULL AND batch_no != ''
		""",
		tuple(bundle_names),
		as_dict=True,
	)
	result = {}
	for r in rows:
		result.setdefault(r.parent, []).append({"batch_no": r.batch_no, "qty": r.qty})
	return result


# ---------------------------------------------------------------------------
# Step 3: Resolve Work Orders from FG (item_code, batch_no) pairs
# ---------------------------------------------------------------------------

def _fetch_manufacture_entries(fg_batch_pairs):
	"""
	Return {(item_code, batch_no): [{work_order, stock_entry, manufacturing_date, wo_item, wo_qty}]}

	Strategy:
	  a. Direct batch_no on Stock Entry Detail (is_finished_item=1)
	  b. Via serial_and_batch_bundle on Stock Entry Detail → Serial and Batch Entry
	"""
	if not fg_batch_pairs:
		return {}

	batch_nos = list({b for _, b in fg_batch_pairs if b})
	if not batch_nos:
		return {}

	placeholders = ", ".join(["%s"] * len(batch_nos))

	# Strategy a: direct batch_no on the finished-item detail row
	direct_rows = frappe.db.sql(
		f"""
		SELECT
			se.name          AS stock_entry,
			se.work_order,
			se.posting_date  AS manufacturing_date,
			sed.name         AS sed_name,
			sed.item_code,
			sed.batch_no,
			sed.is_scrap_item,
			CASE WHEN IFNULL(sed.transfer_qty, 0) > 0 THEN sed.transfer_qty ELSE sed.qty END AS fg_qty
		FROM `tabStock Entry Detail` sed
		JOIN `tabStock Entry` se ON se.name = sed.parent
		WHERE se.purpose = 'Manufacture'
		  AND se.docstatus = 1
		  AND se.work_order IS NOT NULL AND se.work_order != ''
		  AND sed.is_finished_item = 1
		  AND sed.batch_no IN ({placeholders})
		""",
		tuple(batch_nos),
		as_dict=True,
	)

	# Strategy b: batch_no via serial_and_batch_bundle on finished-item detail row
	bundle_rows = frappe.db.sql(
		f"""
		SELECT
			se.name          AS stock_entry,
			se.work_order,
			se.posting_date  AS manufacturing_date,
			sed.name         AS sed_name,
			sed.item_code,
			sbe.batch_no,
			sed.is_scrap_item,
			ABS(sbe.qty)     AS fg_qty
		FROM `tabStock Entry Detail` sed
		JOIN `tabStock Entry` se ON se.name = sed.parent
		JOIN `tabSerial and Batch Entry` sbe ON sbe.parent = sed.serial_and_batch_bundle
		WHERE se.purpose = 'Manufacture'
		  AND se.docstatus = 1
		  AND se.work_order IS NOT NULL AND se.work_order != ''
		  AND sed.is_finished_item = 1
		  AND sed.serial_and_batch_bundle IS NOT NULL
		  AND sbe.batch_no IN ({placeholders})
		""",
		tuple(batch_nos),
		as_dict=True,
	)

	all_se_rows = direct_rows + bundle_rows
	wanted = set(fg_batch_pairs)

	# Bulk fetch Work Order details and each order's total finished output
	wo_names = list({r.work_order for r in all_se_rows if r.work_order})
	wo_details = {}
	wo_fg_totals = {}
	if wo_names:
		wo_fg_totals = _fetch_wo_finished_qty(wo_names)
		wo_placeholders = ", ".join(["%s"] * len(wo_names))
		for wo in frappe.db.sql(
			f"""
			SELECT name, production_item, qty, actual_start_date
			FROM `tabWork Order`
			WHERE name IN ({wo_placeholders})
			""",
			tuple(wo_names),
			as_dict=True,
		):
			wo_details[wo.name] = wo

	# Finished qty each Manufacture entry booked into the batch; scrap rows
	# book nothing.
	stock_entry_of_row = {r.sed_name: r.stock_entry for r in all_se_rows}
	fg_qty_by_row = _finished_qty_per_detail_row(
		[r for r in direct_rows if not cint(r.is_scrap_item)],
		[r for r in bundle_rows if not cint(r.is_scrap_item)],
		wanted,
	)
	fg_qty_by_entry = {}
	for (sed_name, item_code, batch_no), fg_qty in fg_qty_by_row.items():
		entry_key = ((item_code, batch_no), stock_entry_of_row[sed_name])
		fg_qty_by_entry[entry_key] = flt(fg_qty_by_entry.get(entry_key)) + fg_qty

	result = {}
	seen = set()
	for r in all_se_rows:
		key = (r.item_code, r.batch_no)
		if key not in wanted:
			continue
		wo = wo_details.get(r.work_order) or {}
		entry = {
			"work_order": r.work_order,
			"stock_entry": r.stock_entry,
			"manufacturing_date": r.manufacturing_date,
			"wo_item": wo.get("production_item"),
			"wo_qty": wo.get("qty"),
			# finished qty this entry booked into the batch / the order's total
			"fg_qty": fg_qty_by_entry.get((key, r.stock_entry)),
			"wo_fg_qty": wo_fg_totals.get(r.work_order),
		}
		dedup_key = (key, r.stock_entry)
		if dedup_key not in seen:
			seen.add(dedup_key)
			result.setdefault(key, []).append(entry)

	return result


def _finished_qty_per_detail_row(direct_rows, bundle_rows, wanted):
	"""Return ``{(sed_name, item_code, batch_no): fg_qty}`` from the rows of the
	two manufacture lookups, restricted to the ``wanted`` (item_code, batch_no)
	pairs.

	A bundle holds one Serial and Batch Entry per serial number, so a batch can
	appear on several bundle rows of one detail row; they are summed. A detail
	row that carries both a batch_no and a bundle matches both lookups; ERPNext
	keeps its bundle total equal to its transfer qty, so the direct row is taken
	and its bundle rows are skipped rather than added.
	"""
	qty = {}
	direct_keys = set()
	for r in direct_rows:
		if (r.item_code, r.batch_no) not in wanted:
			continue
		key = (r.sed_name, r.item_code, r.batch_no)
		direct_keys.add(key)
		qty[key] = flt(r.fg_qty)
	for r in bundle_rows:
		if (r.item_code, r.batch_no) not in wanted:
			continue
		key = (r.sed_name, r.item_code, r.batch_no)
		if key in direct_keys:
			continue
		qty[key] = flt(qty.get(key)) + flt(r.fg_qty)
	return qty


def _fetch_wo_finished_qty(wo_names):
	"""Return {work_order: finished stock qty} over every submitted Manufacture
	entry of the Work Order, all batches together, scrap rows excluded."""
	if not wo_names:
		return {}
	placeholders = ", ".join(["%s"] * len(wo_names))
	rows = frappe.db.sql(
		f"""
		SELECT
			se.work_order,
			SUM(CASE WHEN IFNULL(sed.transfer_qty, 0) > 0 THEN sed.transfer_qty ELSE sed.qty END) AS fg_qty
		FROM `tabStock Entry Detail` sed
		JOIN `tabStock Entry` se ON se.name = sed.parent
		WHERE se.purpose = 'Manufacture'
		  AND se.docstatus = 1
		  AND se.work_order IN ({placeholders})
		  AND sed.is_finished_item = 1
		  AND IFNULL(sed.is_scrap_item, 0) = 0
		GROUP BY se.work_order
		""",
		tuple(wo_names),
		as_dict=True,
	)
	return {r.work_order: flt(r.fg_qty) for r in rows}


# ---------------------------------------------------------------------------
# Step 4b: Finished qty produced into each FG batch (apportioning denominator)
# ---------------------------------------------------------------------------

def _fetch_batch_produced_qty(fg_batch_pairs):
	"""Return {(item_code, batch_no): finished stock qty} booked into each FG
	batch by every submitted Manufacture entry, with or without a Work Order.

	Only manufactured output counts: stock that entered the batch through a
	return or a reconciliation is not consumption to apportion. Scrap rows are
	excluded; bundle rows are summed per detail row and batch, and a finished
	row carrying both a batch_no and a bundle is counted once.
	"""
	if not fg_batch_pairs:
		return {}

	batch_nos = list({b for _, b in fg_batch_pairs if b})
	if not batch_nos:
		return {}

	placeholders = ", ".join(["%s"] * len(batch_nos))

	direct_rows = frappe.db.sql(
		f"""
		SELECT
			sed.name         AS sed_name,
			sed.item_code,
			sed.batch_no,
			CASE WHEN IFNULL(sed.transfer_qty, 0) > 0 THEN sed.transfer_qty ELSE sed.qty END AS fg_qty
		FROM `tabStock Entry Detail` sed
		JOIN `tabStock Entry` se ON se.name = sed.parent
		WHERE se.purpose = 'Manufacture'
		  AND se.docstatus = 1
		  AND sed.is_finished_item = 1
		  AND IFNULL(sed.is_scrap_item, 0) = 0
		  AND sed.batch_no IN ({placeholders})
		""",
		tuple(batch_nos),
		as_dict=True,
	)

	bundle_rows = frappe.db.sql(
		f"""
		SELECT
			sed.name         AS sed_name,
			sed.item_code,
			sbe.batch_no,
			ABS(sbe.qty)     AS fg_qty
		FROM `tabStock Entry Detail` sed
		JOIN `tabStock Entry` se ON se.name = sed.parent
		JOIN `tabSerial and Batch Entry` sbe ON sbe.parent = sed.serial_and_batch_bundle
		WHERE se.purpose = 'Manufacture'
		  AND se.docstatus = 1
		  AND sed.is_finished_item = 1
		  AND IFNULL(sed.is_scrap_item, 0) = 0
		  AND sed.serial_and_batch_bundle IS NOT NULL
		  AND sbe.batch_no IN ({placeholders})
		""",
		tuple(batch_nos),
		as_dict=True,
	)

	result = {}
	for (_sed_name, item_code, batch_no), fg_qty in _finished_qty_per_detail_row(
		direct_rows, bundle_rows, set(fg_batch_pairs)
	).items():
		key = (item_code, batch_no)
		result[key] = flt(result.get(key)) + fg_qty

	return result


# ---------------------------------------------------------------------------
# Step 4: Resolve consumed raw materials per Work Order
# ---------------------------------------------------------------------------

def _fetch_rm_consumption(work_orders, filters):
	"""
	Return {work_order: [rm_dict]}

	Each rm_dict has: item_code, item_name, description, stock_uom, qty,
	                  consumed_cost, batch_no, purchase_receipt, via_sfg,
	                  sfg_attribution

	A consumed semi-finished item is replaced by the raw materials that went
	into it (``_expand_semi_finished``), so the raw-material filter applies
	after that step: filtering on corn grits finds the grits inside a corn mix.
	"""
	if not work_orders:
		return {}
	result = _expand_semi_finished(_consumption_rows(work_orders))

	# Apply raw_material_item filter
	if filters.get("raw_material_item"):
		result = {
			wo: [rm for rm in rms if rm["item_code"] == filters.raw_material_item]
			for wo, rms in result.items()
		}

	# Fallback: if no purchase_receipt from reference_purchase_receipt, try via batch
	for rms in result.values():
		for rm in rms:
			if not rm["purchase_receipt"] and rm.get("batch_no"):
				rm["purchase_receipt"] = _lookup_pr_via_batch(rm["batch_no"], rm["item_code"])
	return result


def _consumption_rows(work_orders):
	"""Return {work_order: [rm_dict]}: every consumed row, one dict per batch.

	``qty`` is stock UOM (``transfer_qty``): the unit ``stock_uom`` names and
	``basic_rate`` prices, so Consumed Qty and Consumed Cost match their label
	whatever unit the row was entered in. ``row`` is the Stock Entry Detail the
	dict came from.
	"""
	wo_list = list(work_orders or [])
	if not wo_list:
		return {}
	placeholders = ", ".join(["%s"] * len(wo_list))

	# Fetch consumption rows (is_finished_item=0, has a source warehouse)
	raw_rows = frappe.db.sql(
		f"""
		SELECT
			se.work_order,
			sed.name AS sed_name,
			sed.item_code,
			sed.item_name,
			sed.description,
			sed.stock_uom,
			CASE WHEN IFNULL(sed.transfer_qty, 0) > 0 THEN sed.transfer_qty ELSE sed.qty END AS qty,
			sed.basic_rate,
			sed.batch_no,
			sed.serial_and_batch_bundle,
			sed.reference_purchase_receipt
		FROM `tabStock Entry Detail` sed
		JOIN `tabStock Entry` se ON se.name = sed.parent
		WHERE se.docstatus = 1
		  AND se.work_order IN ({placeholders})
		  AND se.purpose IN ('Manufacture', 'Material Consumption for Manufacture')
		  AND sed.is_finished_item = 0
		  AND sed.s_warehouse IS NOT NULL AND sed.s_warehouse != ''
		""",
		tuple(wo_list),
		as_dict=True,
	)

	# Expand rows that use serial_and_batch_bundle (no direct batch_no)
	bundle_names_rm = [r.serial_and_batch_bundle for r in raw_rows
					   if r.serial_and_batch_bundle and not r.batch_no]
	rm_bundle_entries = _fetch_bundle_entries(bundle_names_rm)

	result = {}
	for r in raw_rows:
		row_qty = flt(r.qty)
		# One (batch_no, qty) part per batch when the row uses a bundle
		parts = [(r.batch_no, row_qty)] if r.batch_no else []
		if not parts and r.serial_and_batch_bundle:
			entries = rm_bundle_entries.get(r.serial_and_batch_bundle) or []
			total_bundle_qty = sum(flt(e["qty"]) for e in entries)
			parts = [
				(be["batch_no"], (flt(be["qty"]) / total_bundle_qty * row_qty) if total_bundle_qty else row_qty)
				for be in entries
			]
		if not parts:
			parts = [(None, row_qty)]

		for batch_no, qty in parts:
			result.setdefault(r.work_order, []).append({
				"item_code": r.item_code,
				"item_name": r.item_name,
				"description": r.description,
				"stock_uom": r.stock_uom,
				"qty": qty,
				# consumed cost follows the consumed qty at the entry's valuation
				# rate, so bundle-split rows carry their proportional share
				"consumed_cost": flt(qty) * flt(r.basic_rate),
				"batch_no": batch_no,
				"purchase_receipt": r.reference_purchase_receipt or None,
				"row": r.sed_name,
				"via_sfg": None,
				"sfg_attribution": None,
			})
	return result


# ---------------------------------------------------------------------------
# Semi-finished items: from a consumed mix to the raw materials inside it
# ---------------------------------------------------------------------------

# How sure a row reached through a semi-finished item is, weakest last.
SFG_SINGLE = "single"
SFG_PRO_RATA = "pro_rata"
SFG_NOT_RECORDED = "not_recorded"
SFG_NO_SOURCE = "no_source"
_SFG_RANK = {SFG_SINGLE: 0, SFG_PRO_RATA: 1, SFG_NOT_RECORDED: 2, SFG_NO_SOURCE: 2}


def _sfg_label(basis, sources=0):
	return {
		SFG_SINGLE: _("Single run"),
		SFG_PRO_RATA: _("Pro-rata over {0} sources (estimated)").format(sources),
		SFG_NOT_RECORDED: _("Origin not recorded"),
		SFG_NO_SOURCE: _("Semi-finished, no source found"),
	}[basis]


def _expand_semi_finished(rm_map, depth=1):
	"""Replace each consumed semi-finished row by what went into it.

	A consumed row without a batch whose item some Work Order makes is a
	semi-finished item drawn from a shared, batchless pool. The runs it came
	from are read off the pool's stock ledger (``batch_lineage.pool_sources``):
	what was booked into the pool since it was last empty. The draw is split
	over those receipts pro rata to what each booked, and a run's share of the
	draw over the run's whole output scales the run's own consumption.

	* one run: plain arithmetic on booked figures, labelled "Single run";
	* several receipts: the split is not recorded, so it is pro rata and
	  labelled estimated;
	* a receipt that is not a Work Order's output (a Stock Reconciliation, a
	  Material Receipt, a transfer in) keeps its share as a row of the
	  semi-finished item itself, labelled "Origin not recorded";
	* no receipt at all: the row stays, labelled.

	Quantities below keep the finished-goods Work Order's basis (what its draw
	embodied), so the apportioning downstream applies unchanged.
	"""
	if depth > MAX_SFG_DEPTH:
		return rm_map
	candidates = [rm for rms in rm_map.values() for rm in rms if not rm.get("batch_no") and rm.get("row")]
	made = batch_lineage.manufactured_items({rm["item_code"] for rm in candidates})
	draws = {id(rm): rm for rm in candidates if rm["item_code"] in made}
	if not draws:
		return rm_map

	pool = batch_lineage.pool_sources([rm["row"] for rm in draws.values()], qty_tick())
	runs = sorted(
		{w["work_order"] for rm in draws.values() for w in (pool.get(rm["row"]) or {}).get("work_orders", [])}
	)
	run_rows = _expand_semi_finished(_consumption_rows(runs), depth + 1) if runs else {}
	run_output = _fetch_wo_finished_qty(runs) if runs else {}

	return {
		wo: [
			part
			for rm in rms
			for part in (
				_draw_parts(rm, pool.get(rm["row"]), run_rows, run_output) if id(rm) in draws else [rm]
			)
		]
		for wo, rms in rm_map.items()
	}


def _draw_parts(rm, source, run_rows, run_output):
	"""The rows that stand for the semi-finished draw ``rm``."""
	receipts = []
	if source:
		receipts = [("run", w["work_order"], flt(w["qty"])) for w in source["work_orders"]]
		receipts += [("other", o, flt(o["qty"])) for o in source["other"]]
	total = sum(q for _kind, _src, q in receipts)
	if total <= 0:
		return [dict(rm, sfg_attribution=_sfg_label(SFG_NO_SOURCE), _sfg_basis=SFG_NO_SOURCE)]

	basis = SFG_SINGLE if len(receipts) == 1 else SFG_PRO_RATA
	parts = []
	for kind, src, booked in receipts:
		share = booked / total
		if kind == "other":
			parts.append(
				dict(
					rm,
					qty=flt(rm["qty"]) * share,
					consumed_cost=flt(rm["consumed_cost"]) * share,
					via_sfg=f"{rm['item_code']} ← {src['voucher_type']} {src['voucher_no']}",
					sfg_attribution=_sfg_label(SFG_NOT_RECORDED),
					_sfg_basis=SFG_NOT_RECORDED,
				)
			)
			continue

		via = f"{rm['item_code']} ← {src}"
		output = flt(run_output.get(src))
		# the run's share of the draw, over everything the run made
		ratio = flt(rm["qty"]) * share / output if output > 0 else None
		constituents = run_rows.get(src) or []
		if not constituents:
			# the run booked no consumption: its share stays on the mix itself
			parts.append(
				dict(
					rm,
					qty=flt(rm["qty"]) * share,
					consumed_cost=flt(rm["consumed_cost"]) * share,
					via_sfg=via,
					sfg_attribution=_sfg_label(basis, len(receipts)),
					_sfg_basis=basis,
				)
			)
			continue
		for c in constituents:
			inner = c.get("_sfg_basis")
			weaker = inner if inner and _SFG_RANK[inner] > _SFG_RANK[basis] else None
			parts.append(
				dict(
					c,
					qty=flt(c["qty"]) * ratio if ratio is not None else None,
					consumed_cost=flt(c["consumed_cost"]) * ratio if ratio is not None else None,
					via_sfg=f"{via} · {c['via_sfg']}" if c.get("via_sfg") else via,
					sfg_attribution=c["sfg_attribution"] if weaker else _sfg_label(basis, len(receipts)),
					_sfg_basis=weaker or basis,
				)
			)
	return parts


def _lookup_pr_via_batch(batch_no, item_code):
	"""Fallback: find a Purchase Receipt for a given batch_no + item_code."""
	# Try via Purchase Receipt Item directly
	pr = frappe.db.get_value(
		"Purchase Receipt Item",
		{"batch_no": batch_no, "item_code": item_code, "docstatus": 1},
		"parent",
	)
	if pr:
		return pr

	# Try via Serial and Batch Bundle on Purchase Receipt
	result = frappe.db.sql(
		"""
		SELECT sbb.voucher_no
		FROM `tabSerial and Batch Entry` sbe
		JOIN `tabSerial and Batch Bundle` sbb ON sbb.name = sbe.parent
		WHERE sbe.batch_no = %s
		  AND sbb.voucher_type = 'Purchase Receipt'
		  AND sbb.docstatus = 1
		LIMIT 1
		""",
		(batch_no,),
	)
	return result[0][0] if result else None


# ---------------------------------------------------------------------------
# Step 5: Fetch Purchase Receipt details in bulk
# ---------------------------------------------------------------------------

def _fetch_pr_details(pr_names):
	"""Return {pr_name: {posting_date, supplier, supplier_name, custom_customs_document_no}}"""
	if not pr_names:
		return {}
	placeholders = ", ".join(["%s"] * len(pr_names))
	rows = frappe.db.sql(
		f"""
		SELECT
			name,
			posting_date,
			supplier,
			supplier_name,
			custom_customs_document_no
		FROM `tabPurchase Receipt`
		WHERE name IN ({placeholders})
		  AND docstatus = 1
		""",
		tuple(pr_names),
		as_dict=True,
	)
	return {r.name: r for r in rows}


# ---------------------------------------------------------------------------
# Step 6b: Fetch Purchase Receipt Item qty for (pr_name, item_code, batch_no)
# ---------------------------------------------------------------------------

def _fetch_pr_item_qty(pr_batch_keys):
	"""Return {(pr_name, item_code, batch_no): received_qty_in_stock_uom}"""
	if not pr_batch_keys:
		return {}

	result = {}
	for pr_name, item_code, batch_no in pr_batch_keys:
		if not (pr_name and item_code and batch_no):
			continue

		# Strategy a: direct batch_no on Purchase Receipt Item.
		# Use stock_qty so PR Qty is in the stock UOM (matches Consumed Qty /
		# Balance Stock), not the purchase/transaction UOM.
		direct_qty = frappe.db.sql(
			"""
			SELECT IFNULL(SUM(pri.stock_qty), 0)
			FROM `tabPurchase Receipt Item` pri
			WHERE pri.parent = %s
			  AND pri.item_code = %s
			  AND pri.batch_no = %s
			  AND pri.docstatus = 1
			""",
			(pr_name, item_code, batch_no),
		)
		qty = direct_qty[0][0] if direct_qty else 0

		# Strategy b: via serial_and_batch_bundle
		if not qty:
			bundle_qty = frappe.db.sql(
				"""
				SELECT IFNULL(SUM(ABS(sbe.qty)), 0)
				FROM `tabPurchase Receipt Item` pri
				JOIN `tabSerial and Batch Entry` sbe ON sbe.parent = pri.serial_and_batch_bundle
				WHERE pri.parent = %s
				  AND pri.item_code = %s
				  AND sbe.batch_no = %s
				  AND pri.docstatus = 1
				  AND pri.serial_and_batch_bundle IS NOT NULL
				""",
				(pr_name, item_code, batch_no),
			)
			qty = bundle_qty[0][0] if bundle_qty else 0

		if qty:
			result[(pr_name, item_code, batch_no)] = qty

	return result


# ---------------------------------------------------------------------------
# Step 6c: Fetch current batch balance stock across all warehouses
# ---------------------------------------------------------------------------

def _fetch_batch_balance(batch_item_pairs):
	"""Return {(item_code, batch_no): total_balance_qty} across all warehouses."""
	if not batch_item_pairs:
		return {}

	from erpnext.stock.doctype.batch.batch import get_batch_qty

	result = {}
	for item_code, batch_no in batch_item_pairs:
		if not batch_no:
			continue
		try:
			batches = get_batch_qty(
				batch_no=batch_no,
				item_code=item_code,
				for_stock_levels=True,
				consider_negative_batches=True
			)
			total = sum(b.get("qty", 0) for b in (batches or []))
			result[(item_code, batch_no)] = total
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"_fetch_batch_balance failed for item {item_code}, batch {batch_no}")
			result[(item_code, batch_no)] = 0

	return result


# ---------------------------------------------------------------------------
# Print HTML helpers
# ---------------------------------------------------------------------------

def _apportioned_cost_label(company):
	"""Column label for the apportioned cost on the print and the Excel export.

	The cost is in company currency while the invoice header shows the
	invoice currency, so the label names the currency to keep the two apart.
	"""
	currency = ""
	try:
		currency = frappe.get_cached_value("Company", company, "default_currency") or ""
	except Exception:
		currency = ""
	return f"Apportioned Cost ({currency})" if currency else "Apportioned Cost"


def _fetch_si_header_details(si_names):
	"""Bulk-fetch additional Sales Invoice fields not present in the report columns."""
	if not si_names:
		return {}
	placeholders = ", ".join(["%s"] * len(si_names))
	rows = frappe.db.sql(
		f"""
		SELECT
			name,
			po_no,
			territory,
			remarks,
			custom_customs_document_no,
			customer_address,
			shipping_address_name,
			address_display,
			company_address,
			grand_total,
			rounded_total
		FROM `tabSales Invoice`
		WHERE name IN ({placeholders})
		""",
		tuple(si_names),
		as_dict=True,
	)
	result = {}
	for r in rows:
		# Attempt to get company address display
		company_addr = ""
		if r.get("company_address"):
			try:
				addr_doc = frappe.get_cached_doc("Address", r.company_address)
				company_addr = addr_doc.get("address_line1") or ""
				if addr_doc.get("city"):
					company_addr += f", {addr_doc.city}"
				if addr_doc.get("country"):
					company_addr += f", {addr_doc.country}"
			except Exception:
				pass
		r["company_address_display"] = company_addr
		result[r.name] = r
	return result


def _build_filter_summary(filters):
	"""Return a concise human-readable summary of non-empty filters applied."""
	parts = []
	label_map = [
		("sales_invoice", "Sales Invoice"),
		("customer", "Customer"),
		("item_code", "FG Item"),
		("item_group", "Item Group"),
		("batch_no", "FG Batch"),
		("work_order", "Work Order"),
		("raw_material_item", "RM Item"),
		("purchase_receipt", "Purchase Receipt"),
		("customs_document_no", "Customs Doc No"),
	]
	from_date = filters.get("from_date", "")
	to_date = filters.get("to_date", "")
	if from_date or to_date:
		parts.append(f"Period: {from_date} to {to_date}")
	for key, label in label_map:
		val = filters.get(key)
		if val:
			parts.append(f"{label}: {val}")
	return " \u2502 ".join(parts) if parts else "No additional filters applied"


def _format_address_display(addr_html):
	"""Flatten an HTML address display (<br>-separated lines) to one comma-separated line."""
	if not addr_html:
		return ""
	text = re.sub(r"<br\s*/?>", "\n", str(addr_html), flags=re.IGNORECASE)
	text = unescape(frappe.utils.strip_html(text))
	parts = [p.strip(" ,") for p in text.splitlines()]
	return ", ".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# Print HTML (whitelisted method)
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_print_html(filters):
	if isinstance(filters, str):
		filters = json.loads(filters)
	filters = frappe._dict(filters or {})

	try:
		validate_filters(filters)
	except frappe.ValidationError as e:
		frappe.throw(str(e))

	data = get_data(filters)

	company = frappe.utils.escape_html(filters.get("company", ""))
	print_datetime = frappe.utils.escape_html(str(now_datetime()))
	try:
		printed_by = frappe.utils.escape_html(
			frappe.utils.get_fullname(frappe.session.user) or frappe.session.user
		)
	except Exception:
		printed_by = frappe.utils.escape_html(frappe.session.user or "")
	filter_summary = frappe.utils.escape_html(_build_filter_summary(filters))

	# Group rows by sales invoice, preserving insertion order
	invoices_grouped = {}
	for row in data:
		si = row.get("sales_invoice") or "\u2014"
		invoices_grouped.setdefault(si, []).append(row)

	# Fetch additional SI header details
	real_si_names = [k for k in invoices_grouped if k != "\u2014"]
	si_details = _fetch_si_header_details(real_si_names)

	def _v(val):
		if val is None:
			return ""
		return frappe.utils.escape_html(str(val))

	def _num2(val):
		"""Format numeric quantities to 2 decimal places; blank if empty/None."""
		if val is None or val == "":
			return ""
		try:
			return f"{float(val):.2f}"
		except (TypeError, ValueError):
			return _v(val)

	def _num3(val):
		"""Format numeric weights/volumes to 3 decimal places; blank if empty/None."""
		if val is None or val == "":
			return ""
		try:
			return f"{float(val):.3f}"
		except (TypeError, ValueError):
			return _v(val)

	# Build structured context for the template
	invoices_list = []
	for si_name, rows in invoices_grouped.items():
		first = rows[0]
		si_extra = si_details.get(si_name, {})

		# Build deduplicated FG items list for the header sub-table
		seen_fg_keys = set()
		fg_items = []
		for row in rows:
			fg_key = (
				row.get("si_item_idx"),
				row.get("fg_item_code"),
				row.get("fg_batch_no"),
				row.get("work_order"),
			)
			if fg_key not in seen_fg_keys:
				seen_fg_keys.add(fg_key)
				fg_items.append({
					"si_item_idx": _v(row.get("si_item_idx")),
					"fg_item_code": _v(row.get("fg_item_code")),
					"fg_item_name": _v(row.get("fg_item_name")),
					"sales_qty": _v(row.get("sales_qty")),
					"sales_uom": _v(row.get("sales_uom")),
					"fg_net_weight": _v(row.get("fg_net_weight")),
					"fg_gross_weight": _v(row.get("fg_gross_weight")),
					"fg_weight_uom": _v(row.get("fg_weight_uom")),
					"fg_total_volume": _v(row.get("fg_total_volume")),
					"fg_volume_uom": _v(row.get("fg_volume_uom")),
					"fg_batch_no": _v(row.get("fg_batch_no")),
					"batch_sold_qty": _v(row.get("batch_sold_qty")),
					"batch_produced_qty": _v(row.get("batch_produced_qty")),
					"work_order": _v(row.get("work_order")),
					"manufacturing_date": _v(row.get("manufacturing_date")),
				})

		# Build rows (RM / Purchase / Customs only — FG data moved to header)
		row_list = []
		for row in rows:
			row_list.append({
				"rm_item_code": _v(row.get("rm_item_code")),
				"rm_item_name": _v(row.get("rm_item_name")),
				"via_sfg": _v(row.get("via_sfg")),
				"sfg_attribution": _v(row.get("sfg_attribution")),
				"consumed_qty": _num2(row.get("consumed_qty")),
				"apportioned_qty": _num2(row.get("apportioned_qty")),
				"apportioned_cost": _num2(row.get("apportioned_cost")),
				"rm_batch_no": _v(row.get("rm_batch_no")),
				"purchase_receipt": _v(row.get("purchase_receipt")),
				"purchase_receipt_date": _v(row.get("purchase_receipt_date")),
				"supplier_name": _v(row.get("supplier_name")),
				"pr_qty": _num2(row.get("pr_qty")),
				"balance_stock": _num2(row.get("balance_stock")),
				"customs_document_no": _v(row.get("customs_document_no")),
			})

		# --- Header totals: net/gross weight and volume (one row per SI line) ---
		_seen_total_idx = set()
		_tot_net = _tot_gross = _tot_vol = 0.0
		_wt_uom = _vol_uom = ""
		for _r in rows:
			_li = _r.get("si_item_idx")
			if _li in _seen_total_idx:
				continue
			_seen_total_idx.add(_li)
			_tot_net += frappe.utils.flt(_r.get("fg_net_weight"))
			_tot_gross += frappe.utils.flt(_r.get("fg_gross_weight"))
			_tot_vol += frappe.utils.flt(_r.get("fg_total_volume"))
			if not _wt_uom and _r.get("fg_weight_uom"):
				_wt_uom = _r.get("fg_weight_uom")
			if not _vol_uom and _r.get("fg_volume_uom"):
				_vol_uom = _r.get("fg_volume_uom")

		invoices_list.append({
			"si_name": _v(si_name),
			"posting_date": _v(first.get("posting_date")),
			"customer": _v(first.get("customer")),
			"customer_name": _v(first.get("customer_name")),
			"currency": _v(first.get("currency")),
			"company": _v(first.get("company")),
			"po_no": _v(si_extra.get("po_no")),
			"territory": _v(si_extra.get("territory")),
			"customs_export_declaration_no": _v(si_extra.get("custom_customs_document_no")),
			"remarks": _v(si_extra.get("remarks")),
			"customer_address": _v(_format_address_display(si_extra.get("address_display")) or si_extra.get("customer_address")),
			"company_address": _v(si_extra.get("company_address_display")),
			"total_amount": _v(si_extra.get("rounded_total") or si_extra.get("grand_total")),
			"total_net_weight": _num3(_tot_net) if _tot_net else "",
			"total_gross_weight": _num3(_tot_gross) if _tot_gross else "",
			"total_volume": _num3(_tot_vol) if _tot_vol else "",
			"net_weight_uom": _v(_wt_uom),
			"gross_weight_uom": _v(_wt_uom),
			"volume_uom": _v(_vol_uom),
			"fg_items": fg_items,
			"rows": row_list,
		})

	context = {
		"company": company,
		"print_datetime": print_datetime,
		"printed_by": printed_by,
		"filter_summary": filter_summary,
		"apportioned_cost_label": frappe.utils.escape_html(_apportioned_cost_label(filters.get("company"))),
		"invoices": invoices_list,
	}

	template_path = os.path.join(
		os.path.dirname(__file__),
		"customs_export_traceability_report_print.html",
	)
	try:
		with open(template_path, "r") as f:
			template = f.read()
	except OSError as e:
		frappe.throw(f"Could not load print template: {e}")

	return frappe.render_template(template, context)


# ---------------------------------------------------------------------------
# Excel Export (whitelisted method)
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_export_excel(filters):
	try:
		from openpyxl import Workbook
		from openpyxl.styles import Alignment, Font, PatternFill
		from openpyxl.utils import get_column_letter
	except ImportError:
		frappe.throw("openpyxl is required to export Excel files. Please install it.")

	if isinstance(filters, str):
		filters = json.loads(filters)
	filters = frappe._dict(filters or {})

	try:
		validate_filters(filters)
	except frappe.ValidationError as e:
		frappe.throw(str(e))

	data = get_data(filters)

	company = filters.get("company", "")
	export_datetime = str(now_datetime())
	try:
		exported_by = frappe.utils.get_fullname(frappe.session.user) or frappe.session.user
	except Exception:
		exported_by = frappe.session.user or ""
	filter_summary = _build_filter_summary(filters)

	# Group rows by sales invoice, preserving insertion order
	invoices_grouped = {}
	for row in data:
		si = row.get("sales_invoice") or "\u2014"
		invoices_grouped.setdefault(si, []).append(row)

	# Fetch additional SI header details
	real_si_names = [k for k in invoices_grouped if k != "\u2014"]
	si_details = _fetch_si_header_details(real_si_names)

	# ---------------------------------------------------------------------------
	# Style helpers
	# ---------------------------------------------------------------------------
	def _make_fill(hex_color):
		return PatternFill(fill_type="solid", fgColor=hex_color)

	def _bold_font(color="000000", size=10):
		return Font(bold=True, color=color, size=size)

	def _normal_font(size=10):
		return Font(size=size)

	ALIGN_LEFT = Alignment(horizontal="left", vertical="center", wrap_text=True)
	ALIGN_CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
	ALIGN_RIGHT = Alignment(horizontal="right", vertical="center")

	# FG table: 15 cols; RM table: 12 cols → use 15 as total width
	TOTAL_COLS = 15

	wb = Workbook()
	ws = wb.active
	ws.title = "Traceability Report"

	# ---------------------------------------------------------------------------
	# Helper: write a merged row spanning all columns
	# ---------------------------------------------------------------------------
	def _write_merged_row(text, font=None, fill=None, align=None):
		row_idx = ws.max_row + 1
		ws.append([""] * TOTAL_COLS)
		cell = ws.cell(row=row_idx, column=1)
		cell.value = text
		if font:
			cell.font = font
		if fill:
			cell.fill = fill
		cell.alignment = align or ALIGN_LEFT
		ws.merge_cells(
			start_row=row_idx, start_column=1,
			end_row=row_idx, end_column=TOTAL_COLS,
		)
		return row_idx

	def _write_blank_row():
		ws.append([""] * TOTAL_COLS)

	# ---------------------------------------------------------------------------
	# A) Report header (written once)
	# ---------------------------------------------------------------------------
	_write_merged_row(
		"Consumption Form / Fiche de Côsommation",
		font=_bold_font(size=14),
		align=ALIGN_CENTER,
	)
	_write_merged_row(company, font=_bold_font(size=11), align=ALIGN_CENTER)
	_write_merged_row(
		f"Exported: {export_datetime} | Exported by: {exported_by}",
		font=_normal_font(size=9),
		align=ALIGN_CENTER,
	)
	_write_merged_row(
		f"Filters applied: {filter_summary}",
		font=_normal_font(size=9),
		align=ALIGN_CENTER,
	)
	_write_blank_row()

	# ---------------------------------------------------------------------------
	# B) Per-invoice sections
	# ---------------------------------------------------------------------------
	FILL_INV_HEADER = _make_fill("EEF3F8")
	FILL_FG_HEADER = _make_fill("2C5F8A")
	FILL_RM_GROUP = _make_fill("3A7A4A")
	FILL_PR_GROUP = _make_fill("7A5A2A")
	FILL_COL_HEADER = _make_fill("3A6B96")
	WHITE_BOLD = _bold_font(color="FFFFFF")

	FG_HEADERS = [
		"#",
		"FG Item Code",
		"FG Item Name",
		"Sold Qty",
		"UOM",
		"Net Weight",
		"Gross Weight",
		"Weight UOM",
		"Total Volume",
		"Volume UOM",
		"FG Batch No",
		"Batch Sold Qty",
		"Batch Produced Qty",
		"Work Order",
		"Mfg Date",
	]
	APPORTIONED_COST_HEADER = _apportioned_cost_label(company)
	RM_HEADERS = [
		"RM Item Code", "RM Item Name", "Consumed Qty", "Apportioned Qty", APPORTIONED_COST_HEADER,
		"RM Batch No", "Purchase Receipt", "PR Date", "Supplier Name",
		"PR Qty", "Balance Stock", "Customs Doc No",
		"Via Semi-Finished", "SFG Attribution",
	]
	FG_DATE_COL = FG_HEADERS.index("Mfg Date") + 1
	RM_GROUP_END = RM_HEADERS.index("RM Batch No") + 1
	PR_GROUP_END = RM_HEADERS.index("Customs Doc No") + 1
	RM_DATE_COL = RM_HEADERS.index("PR Date") + 1
	RM_QTY_COLS = tuple(
		RM_HEADERS.index(h) + 1 for h in ("Consumed Qty", "Apportioned Qty", "PR Qty", "Balance Stock")
	)
	RM_COST_COL = RM_HEADERS.index(APPORTIONED_COST_HEADER) + 1

	for si_name, rows in invoices_grouped.items():
		first = rows[0]
		si_extra = si_details.get(si_name, {})

		# — Invoice header row —
		posting_date = first.get("posting_date") or ""
		customer_name = first.get("customer_name") or ""
		currency = first.get("currency") or ""
		total_amount = si_extra.get("rounded_total") or si_extra.get("grand_total") or ""
		inv_header_text = (
			f"Sales Invoice: {si_name} | Posting Date: {posting_date} | "
			f"Customer: {customer_name} | Currency: {currency} | Total: {total_amount}"
		)
		_write_merged_row(
			inv_header_text,
			font=_bold_font(size=10),
			fill=FILL_INV_HEADER,
		)

		# Optional extra detail rows
		po_no = si_extra.get("po_no") or ""
		territory = si_extra.get("territory") or ""
		remarks = si_extra.get("remarks") or ""
		customs_export_declaration_no = si_extra.get("custom_customs_document_no") or ""

		if po_no or territory or customs_export_declaration_no:
			extra_parts = []
			if po_no:
				extra_parts.append(f"PO Ref: {po_no}")
			if territory:
				extra_parts.append(f"Territory: {territory}")
			if customs_export_declaration_no:
				extra_parts.append(f"Customs Export Declaration No: {customs_export_declaration_no}")
			_write_merged_row(
				" | ".join(extra_parts),
				font=_normal_font(size=9),
				fill=FILL_INV_HEADER,
			)
		if remarks:
			_write_merged_row(
				f"Remarks: {remarks}",
				font=_normal_font(size=9),
				fill=FILL_INV_HEADER,
			)

		# — FG sub-header row —
		fg_header_row_idx = ws.max_row + 1
		ws.append(FG_HEADERS + [""] * (TOTAL_COLS - len(FG_HEADERS)))
		for col_idx in range(1, len(FG_HEADERS) + 1):
			cell = ws.cell(row=fg_header_row_idx, column=col_idx)
			cell.font = WHITE_BOLD
			cell.fill = FILL_FG_HEADER
			cell.alignment = ALIGN_CENTER

		# — FG data rows —
		seen_fg_keys = set()
		for row in rows:
			fg_key = (
				row.get("si_item_idx"),
				row.get("fg_item_code"),
				row.get("fg_batch_no"),
				row.get("work_order"),
			)
			if fg_key in seen_fg_keys:
				continue
			seen_fg_keys.add(fg_key)

			mfg_date = row.get("manufacturing_date")
			sales_qty = row.get("sales_qty")
			try:
				sales_qty = float(sales_qty) if sales_qty is not None else ""
			except (TypeError, ValueError):
				sales_qty = str(sales_qty) if sales_qty is not None else ""

			fg_net_weight = row.get("fg_net_weight")
			try:
				fg_net_weight = float(fg_net_weight) if fg_net_weight is not None else ""
			except (TypeError, ValueError):
				fg_net_weight = str(fg_net_weight) if fg_net_weight is not None else ""

			fg_gross_weight = row.get("fg_gross_weight")
			try:
				fg_gross_weight = float(fg_gross_weight) if fg_gross_weight is not None else ""
			except (TypeError, ValueError):
				fg_gross_weight = str(fg_gross_weight) if fg_gross_weight is not None else ""

			fg_total_volume = row.get("fg_total_volume")
			try:
				fg_total_volume = float(fg_total_volume) if fg_total_volume is not None else ""
			except (TypeError, ValueError):
				fg_total_volume = str(fg_total_volume) if fg_total_volume is not None else ""

			batch_sold_qty = row.get("batch_sold_qty")
			try:
				batch_sold_qty = float(batch_sold_qty) if batch_sold_qty is not None else ""
			except (TypeError, ValueError):
				batch_sold_qty = str(batch_sold_qty) if batch_sold_qty is not None else ""

			batch_produced_qty = row.get("batch_produced_qty")
			try:
				batch_produced_qty = float(batch_produced_qty) if batch_produced_qty is not None else ""
			except (TypeError, ValueError):
				batch_produced_qty = str(batch_produced_qty) if batch_produced_qty is not None else ""

			fg_row = [
				row.get("si_item_idx") or "",
				row.get("fg_item_code") or "",
				row.get("fg_item_name") or "",
				sales_qty,
				row.get("sales_uom") or "",
				fg_net_weight,
				fg_gross_weight,
				row.get("fg_weight_uom") or "",
				fg_total_volume,
				row.get("fg_volume_uom") or "",
				row.get("fg_batch_no") or "",
				batch_sold_qty,
				batch_produced_qty,
				row.get("work_order") or "",
				mfg_date if mfg_date else "",
			]
			data_row_idx = ws.max_row + 1
			ws.append(fg_row + [""] * (TOTAL_COLS - len(fg_row)))
			# Format date cell (Mfg Date)
			if mfg_date:
				date_cell = ws.cell(row=data_row_idx, column=FG_DATE_COL)
				date_cell.number_format = "YYYY-MM-DD"

		# — FG totals: net / gross weight and volume (one row per SI line) —
		_seen_total_idx = set()
		_tot_net = _tot_gross = _tot_vol = 0.0
		_wt_uom = _vol_uom = ""
		for _r in rows:
			_li = _r.get("si_item_idx")
			if _li in _seen_total_idx:
				continue
			_seen_total_idx.add(_li)
			_tot_net += frappe.utils.flt(_r.get("fg_net_weight"))
			_tot_gross += frappe.utils.flt(_r.get("fg_gross_weight"))
			_tot_vol += frappe.utils.flt(_r.get("fg_total_volume"))
			if not _wt_uom and _r.get("fg_weight_uom"):
				_wt_uom = _r.get("fg_weight_uom")
			if not _vol_uom and _r.get("fg_volume_uom"):
				_vol_uom = _r.get("fg_volume_uom")
		_totals_text = (
			f"Total Net Weight: {_tot_net:.3f} {_wt_uom}".rstrip()
			+ "    |    " + f"Total Gross Weight: {_tot_gross:.3f} {_wt_uom}".rstrip()
			+ "    |    " + f"Total Volume: {_tot_vol:.3f} {_vol_uom}".rstrip()
		)
		_write_merged_row(_totals_text, font=_bold_font(size=9), fill=FILL_INV_HEADER)

		_write_blank_row()

		# — RM/Purchase/Customs group header row —
		grp_row_idx = ws.max_row + 1
		ws.append([""] * TOTAL_COLS)
		# "Raw Material" spans the columns up to RM Batch No
		rm_group_cell = ws.cell(row=grp_row_idx, column=1)
		rm_group_cell.value = "Raw Material Consumed"
		rm_group_cell.font = WHITE_BOLD
		rm_group_cell.fill = FILL_RM_GROUP
		rm_group_cell.alignment = ALIGN_CENTER
		ws.merge_cells(start_row=grp_row_idx, start_column=1, end_row=grp_row_idx, end_column=RM_GROUP_END)
		# "Purchase / Customs" spans the columns up to Customs Doc No
		pr_group_cell = ws.cell(row=grp_row_idx, column=RM_GROUP_END + 1)
		pr_group_cell.value = "Purchase / Customs"
		pr_group_cell.font = WHITE_BOLD
		pr_group_cell.fill = FILL_PR_GROUP
		pr_group_cell.alignment = ALIGN_CENTER
		ws.merge_cells(
			start_row=grp_row_idx, start_column=RM_GROUP_END + 1,
			end_row=grp_row_idx, end_column=PR_GROUP_END,
		)
		# "Semi-Finished Trace" spans the route columns after it
		sfg_group_cell = ws.cell(row=grp_row_idx, column=PR_GROUP_END + 1)
		sfg_group_cell.value = "Semi-Finished Trace"
		sfg_group_cell.font = WHITE_BOLD
		sfg_group_cell.fill = FILL_RM_GROUP
		sfg_group_cell.alignment = ALIGN_CENTER
		ws.merge_cells(
			start_row=grp_row_idx, start_column=PR_GROUP_END + 1,
			end_row=grp_row_idx, end_column=len(RM_HEADERS),
		)

		# — RM column header row —
		rm_col_row_idx = ws.max_row + 1
		ws.append(RM_HEADERS)
		for col_idx in range(1, len(RM_HEADERS) + 1):
			cell = ws.cell(row=rm_col_row_idx, column=col_idx)
			cell.font = WHITE_BOLD
			cell.fill = FILL_COL_HEADER
			cell.alignment = ALIGN_CENTER

		# — RM data rows —
		for row in rows:
			pr_date = row.get("purchase_receipt_date")
			consumed_qty = row.get("consumed_qty")
			apportioned_qty = row.get("apportioned_qty")
			apportioned_cost = row.get("apportioned_cost")
			pr_qty = row.get("pr_qty")
			balance_stock = row.get("balance_stock")

			try:
				consumed_qty = float(consumed_qty) if consumed_qty is not None else ""
			except (TypeError, ValueError):
				consumed_qty = str(consumed_qty) if consumed_qty is not None else ""
			try:
				apportioned_qty = float(apportioned_qty) if apportioned_qty is not None else ""
			except (TypeError, ValueError):
				apportioned_qty = str(apportioned_qty) if apportioned_qty is not None else ""
			try:
				apportioned_cost = float(apportioned_cost) if apportioned_cost is not None else ""
			except (TypeError, ValueError):
				apportioned_cost = str(apportioned_cost) if apportioned_cost is not None else ""
			try:
				pr_qty = float(pr_qty) if pr_qty is not None else ""
			except (TypeError, ValueError):
				pr_qty = str(pr_qty) if pr_qty is not None else ""
			try:
				balance_stock = float(balance_stock) if balance_stock is not None else ""
			except (TypeError, ValueError):
				balance_stock = str(balance_stock) if balance_stock is not None else ""

			rm_row = [
				row.get("rm_item_code") or "",
				row.get("rm_item_name") or "",
				consumed_qty,
				apportioned_qty,
				apportioned_cost,
				row.get("rm_batch_no") or "",
				row.get("purchase_receipt") or "",
				pr_date if pr_date else "",
				row.get("supplier_name") or "",
				pr_qty,
				balance_stock,
				row.get("customs_document_no") or "",
				row.get("via_sfg") or "",
				row.get("sfg_attribution") or "",
			]
			data_row_idx = ws.max_row + 1
			ws.append(rm_row)
			# Format date cell (PR Date)
			if pr_date:
				date_cell = ws.cell(row=data_row_idx, column=RM_DATE_COL)
				date_cell.number_format = "YYYY-MM-DD"
			# Show qty columns to 2 decimal places: Consumed / Apportioned Qty, PR Qty, Balance Stock
			for qty_col in RM_QTY_COLS:
				qty_cell = ws.cell(row=data_row_idx, column=qty_col)
				if isinstance(qty_cell.value, float):
					qty_cell.number_format = "0.00"
			cost_cell = ws.cell(row=data_row_idx, column=RM_COST_COL)
			if isinstance(cost_cell.value, float):
				cost_cell.number_format = "#,##0.00"

		_write_blank_row()

	# ---------------------------------------------------------------------------
	# C) Footer
	# ---------------------------------------------------------------------------
	_write_merged_row(
		"\u2014 End of Report \u2014",
		font=_bold_font(size=10),
		align=ALIGN_CENTER,
	)
	_write_merged_row(
		"Blank fields indicate that traceability could not be established from available ERPNext data. "
		"Only submitted documents (Sales Invoice, Stock Entry, Purchase Receipt) are included. "
		"Raw material consumption is based on actual Stock Entry records, not BOM explosion. "
		"Consumed Qty is the whole Work Order; Apportioned Qty and Apportioned Cost are the part embodied in "
		"the cartons of the FG batch sold on this invoice (Consumed Qty × Batch Sold Qty ÷ Batch Produced Qty). "
		"Apportioned Cost is in company currency at the valuation of the consumption entries. "
		"A semi-finished item is replaced by the raw materials of the run that made it, read off the "
		"semi-finished stock ledger (Via Semi-Finished); where several runs could have supplied it, the "
		"quantities are split pro rata to what each run booked and marked estimated (SFG Attribution).",
		font=_normal_font(size=8),
		align=ALIGN_CENTER,
	)
	_write_blank_row()
	_write_merged_row(
		"Je dis bien que le produit indiqué sur la présente facture ne fait l'objet d'aucune saisie ni jugement",
		font=_bold_font(size=14),
		align=ALIGN_CENTER,
	)

	# ---------------------------------------------------------------------------
	# Column widths (reasonable fixed widths)
	# ---------------------------------------------------------------------------
	col_widths = [6, 20, 30, 10, 10, 14, 14, 12, 14, 12, 22, 14, 16, 25, 15]
	for i, width in enumerate(col_widths, start=1):
		ws.column_dimensions[get_column_letter(i)].width = width

	# Freeze first 5 header rows
	ws.freeze_panes = "A6"

	# ---------------------------------------------------------------------------
	# Serialize to base64
	# ---------------------------------------------------------------------------
	buf = BytesIO()
	wb.save(buf)
	buf.seek(0)
	file_content = base64.b64encode(buf.read()).decode("utf-8")

	timestamp = now_datetime().strftime("%Y%m%d_%H%M%S")
	file_name = f"Consumption_Form_{timestamp}.xlsx"

	return {"file_content": file_content, "file_name": file_name}
