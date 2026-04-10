# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import getdate, nowdate, now_datetime


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
		{"label": _("Item Group"), "fieldname": "item_group", "fieldtype": "Link", "options": "Item Group", "width": 120},
		# B. Finished good traceability
		{"label": _("FG Batch No"), "fieldname": "fg_batch_no", "fieldtype": "Link", "options": "Batch", "width": 130},
		{"label": _("Work Order"), "fieldname": "work_order", "fieldtype": "Link", "options": "Work Order", "width": 150},
		{"label": _("WO Item"), "fieldname": "wo_item", "fieldtype": "Link", "options": "Item", "width": 130},
		{"label": _("WO Qty"), "fieldname": "wo_qty", "fieldtype": "Float", "width": 80},
		{"label": _("Manufacturing Date"), "fieldname": "manufacturing_date", "fieldtype": "Date", "width": 110},
		{"label": _("Manufacture Entry"), "fieldname": "manufacture_entry", "fieldtype": "Link", "options": "Stock Entry", "width": 150},
		# C. Raw material consumption
		{"label": _("RM Item Code"), "fieldname": "rm_item_code", "fieldtype": "Link", "options": "Item", "width": 140},
		{"label": _("RM Item Name"), "fieldname": "rm_item_name", "fieldtype": "Data", "width": 160},
		{"label": _("RM Description"), "fieldname": "rm_description", "fieldtype": "Data", "width": 180},
		{"label": _("RM UOM"), "fieldname": "rm_uom", "fieldtype": "Link", "options": "UOM", "width": 80},
		{"label": _("Consumed Qty"), "fieldname": "consumed_qty", "fieldtype": "Float", "width": 100},
		{"label": _("RM Batch No"), "fieldname": "rm_batch_no", "fieldtype": "Link", "options": "Batch", "width": 130},
		# D. Purchase / customs traceability
		{"label": _("Purchase Receipt"), "fieldname": "purchase_receipt", "fieldtype": "Link", "options": "Purchase Receipt", "width": 150},
		{"label": _("PR Date"), "fieldname": "purchase_receipt_date", "fieldtype": "Date", "width": 100},
		{"label": _("Supplier"), "fieldname": "supplier", "fieldtype": "Link", "options": "Supplier", "width": 120},
		{"label": _("Supplier Name"), "fieldname": "supplier_name", "fieldtype": "Data", "width": 160},
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

	# Step 7: Assemble output rows
	rows = []
	for si_row in si_items:
		# Build list of (fg_batch_no, batch_qty_fraction) for this SI item
		fg_batches = _resolve_fg_batches(si_row, bundle_entries)

		for fg_batch_no in fg_batches:
			wo_entries = wo_map.get((si_row.fg_item_code, fg_batch_no)) or [{}]
			for wo_entry in wo_entries:
				work_order = wo_entry.get("work_order")
				rm_list = rm_map.get(work_order) or [{}] if work_order else [{}]
				for rm in rm_list:
					pr_name = rm.get("purchase_receipt")
					pr = pr_details.get(pr_name) or {} if pr_name else {}

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
						item_group=si_row.item_group,
						# B
						fg_batch_no=fg_batch_no or None,
						work_order=work_order,
						wo_item=wo_entry.get("wo_item"),
						wo_qty=wo_entry.get("wo_qty"),
						manufacturing_date=wo_entry.get("manufacturing_date"),
						manufacture_entry=wo_entry.get("stock_entry"),
						# C
						rm_item_code=rm.get("item_code"),
						rm_item_name=rm.get("item_name"),
						rm_description=rm.get("description"),
						rm_uom=rm.get("stock_uom"),
						consumed_qty=rm.get("qty"),
						rm_batch_no=rm.get("batch_no"),
						# D
						purchase_receipt=pr_name,
						purchase_receipt_date=pr.get("posting_date"),
						supplier=pr.get("supplier"),
						supplier_name=pr.get("supplier_name"),
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
	"""Return list of fg_batch_no strings (may be empty string / None if unknown)."""
	if si_row.batch_no:
		return [si_row.batch_no]
	if si_row.serial_and_batch_bundle:
		entries = bundle_entries.get(si_row.serial_and_batch_bundle) or []
		batches = [e["batch_no"] for e in entries if e.get("batch_no")]
		if batches:
			return batches
	return [None]


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

	# Batch filter: either directly on sii.batch_no or via bundle
	if filters.get("batch_no"):
		conditions.append("""(
			sii.batch_no = %(batch_no)s
			OR EXISTS (
				SELECT 1 FROM `tabSerial and Batch Entry` sbe
				WHERE sbe.parent = sii.serial_and_batch_bundle
				AND sbe.batch_no = %(batch_no)s
			)
		)""")
		values["batch_no"] = filters.batch_no

	where_clause = " AND ".join(conditions)

	return frappe.db.sql(
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
			sii.serial_and_batch_bundle
		FROM `tabSales Invoice Item` sii
		JOIN `tabSales Invoice` si ON si.name = sii.parent
		WHERE {where_clause}
		ORDER BY si.posting_date, si.name, sii.idx
		""",
		values,
		as_dict=True,
	)


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
			sed.item_code,
			sed.batch_no
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
			sed.item_code,
			sbe.batch_no
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

	# Bulk fetch Work Order details
	wo_names = list({r.work_order for r in all_se_rows if r.work_order})
	wo_details = {}
	if wo_names:
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

	result = {}
	seen = set()
	for r in all_se_rows:
		key = (r.item_code, r.batch_no)
		if key not in {(ic, b) for ic, b in fg_batch_pairs}:
			continue
		wo = wo_details.get(r.work_order) or {}
		entry = {
			"work_order": r.work_order,
			"stock_entry": r.stock_entry,
			"manufacturing_date": r.manufacturing_date,
			"wo_item": wo.get("production_item"),
			"wo_qty": wo.get("qty"),
		}
		dedup_key = (key, r.stock_entry)
		if dedup_key not in seen:
			seen.add(dedup_key)
			result.setdefault(key, []).append(entry)

	return result


# ---------------------------------------------------------------------------
# Step 4: Resolve consumed raw materials per Work Order
# ---------------------------------------------------------------------------

def _fetch_rm_consumption(work_orders, filters):
	"""
	Return {work_order: [rm_dict]}

	Each rm_dict has: item_code, item_name, description, stock_uom, qty,
	                  batch_no, purchase_receipt
	"""
	if not work_orders:
		return {}

	wo_list = list(work_orders)
	placeholders = ", ".join(["%s"] * len(wo_list))

	# Fetch consumption rows (is_finished_item=0, has a source warehouse)
	raw_rows = frappe.db.sql(
		f"""
		SELECT
			se.work_order,
			sed.item_code,
			sed.item_name,
			sed.description,
			sed.stock_uom,
			sed.qty,
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

	# Apply raw_material_item filter early
	if filters.get("raw_material_item"):
		raw_rows = [r for r in raw_rows if r.item_code == filters.raw_material_item]

	# Expand rows that use serial_and_batch_bundle (no direct batch_no)
	bundle_names_rm = [r.serial_and_batch_bundle for r in raw_rows
					   if r.serial_and_batch_bundle and not r.batch_no]
	rm_bundle_entries = _fetch_bundle_entries(bundle_names_rm)

	result = {}
	for r in raw_rows:
		# Build one or more rm dicts (one per batch when using bundle)
		rm_dicts = []
		if r.batch_no:
			rm_dicts.append({
				"item_code": r.item_code,
				"item_name": r.item_name,
				"description": r.description,
				"stock_uom": r.stock_uom,
				"qty": r.qty,
				"batch_no": r.batch_no,
				"purchase_receipt": r.reference_purchase_receipt or None,
			})
		elif r.serial_and_batch_bundle:
			entries = rm_bundle_entries.get(r.serial_and_batch_bundle) or []
			if entries:
				total_bundle_qty = sum(e["qty"] for e in entries if e["qty"])
				for be in entries:
					qty_fraction = (be["qty"] / total_bundle_qty * r.qty) if total_bundle_qty else r.qty
					rm_dicts.append({
						"item_code": r.item_code,
						"item_name": r.item_name,
						"description": r.description,
						"stock_uom": r.stock_uom,
						"qty": qty_fraction,
						"batch_no": be["batch_no"],
						"purchase_receipt": r.reference_purchase_receipt or None,
					})
			else:
				rm_dicts.append({
					"item_code": r.item_code,
					"item_name": r.item_name,
					"description": r.description,
					"stock_uom": r.stock_uom,
					"qty": r.qty,
					"batch_no": None,
					"purchase_receipt": r.reference_purchase_receipt or None,
				})
		else:
			rm_dicts.append({
				"item_code": r.item_code,
				"item_name": r.item_name,
				"description": r.description,
				"stock_uom": r.stock_uom,
				"qty": r.qty,
				"batch_no": None,
				"purchase_receipt": r.reference_purchase_receipt or None,
			})

		# Fallback: if no purchase_receipt from reference_purchase_receipt, try via batch
		for rm in rm_dicts:
			if not rm["purchase_receipt"] and rm.get("batch_no"):
				rm["purchase_receipt"] = _lookup_pr_via_batch(rm["batch_no"], rm["item_code"])

		for rm in rm_dicts:
			result.setdefault(r.work_order, []).append(rm)

	return result


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
# Print HTML helpers
# ---------------------------------------------------------------------------

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
			customer_address,
			shipping_address_name,
			address_display,
			company_address
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


# ---------------------------------------------------------------------------
# Print HTML (whitelisted method)
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_print_html(filters):
	if isinstance(filters, str):
		import json
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
	invoices = {}
	for row in data:
		si = row.get("sales_invoice") or "\u2014"
		invoices.setdefault(si, []).append(row)

	# Fetch additional SI header details
	real_si_names = [k for k in invoices if k != "\u2014"]
	si_details = _fetch_si_header_details(real_si_names)

	def _v(val):
		if val is None:
			return ""
		return frappe.utils.escape_html(str(val))

	# Two-row column group header
	table_headers = """<thead>
<tr class="col-group-header">
  <th colspan="8" class="col-group-fg">Finished Good</th>
  <th colspan="4" class="col-group-rm">Raw Material</th>
  <th colspan="5" class="col-group-pc">Purchase / Customs</th>
</tr>
<tr>
  <th>#</th>
  <th>FG Item Code</th>
  <th>FG Item Name</th>
  <th class="num-col">Sold Qty</th>
  <th>UOM</th>
  <th>FG Batch No</th>
  <th>Work Order</th>
  <th>Mfg Date</th>
  <th>RM Item Code</th>
  <th>RM Item Name</th>
  <th class="num-col">Consumed Qty</th>
  <th>RM Batch No</th>
  <th>Purchase Receipt</th>
  <th>PR Date</th>
  <th>Supplier</th>
  <th>Supplier Name</th>
  <th>Customs Doc No</th>
</tr>
</thead>"""

	css = """
  body {
    font-family: Arial, Helvetica, sans-serif;
    font-size: 10px;
    color: #222;
    margin: 0;
    padding: 0;
  }
  @page {
    size: A4 landscape;
    margin: 12mm;
    @bottom-center {
      content: "Page " counter(page) " of " counter(pages);
      font-size: 8px;
      color: #555;
    }
  }
  .report-header {
    text-align: center;
    margin-bottom: 14px;
    border-bottom: 2px solid #2c5f8a;
    padding-bottom: 8px;
  }
  .report-header h1 {
    font-size: 17px;
    font-weight: bold;
    margin: 0 0 4px 0;
    color: #1a3d5c;
  }
  .report-header .company-name {
    font-size: 12px;
    font-weight: bold;
    margin: 2px 0;
  }
  .report-header .meta {
    font-size: 9px;
    color: #555;
    margin: 2px 0;
  }
  .filter-summary {
    font-size: 9px;
    color: #444;
    background: #f5f5f5;
    border: 1px solid #ddd;
    padding: 4px 8px;
    margin-bottom: 14px;
    border-radius: 2px;
  }
  .invoice-block {
    margin-bottom: 28px;
    page-break-inside: avoid;
  }
  .invoice-header-block {
    background: #eef3f8;
    border: 1px solid #b0c4d8;
    border-left: 4px solid #2c5f8a;
    padding: 8px 12px;
    margin-bottom: 6px;
  }
  .invoice-header-block .si-title {
    font-size: 13px;
    font-weight: bold;
    color: #1a3d5c;
    margin: 0 0 5px 0;
  }
  .invoice-header-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 4px 16px;
    font-size: 9px;
  }
  .invoice-header-grid .field-pair {
    display: flex;
    flex-direction: column;
  }
  .invoice-header-grid .field-label {
    font-weight: bold;
    color: #555;
    font-size: 8px;
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }
  .invoice-header-grid .field-value {
    color: #222;
  }
  .invoice-header-remarks {
    margin-top: 5px;
    font-size: 9px;
    color: #555;
    font-style: italic;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 9px;
  }
  thead {
    display: table-header-group;
  }
  .col-group-header th {
    text-align: center;
    font-size: 9px;
    padding: 3px 4px;
    border: 1px solid #1e4468;
  }
  .col-group-fg {
    background: #2c5f8a;
    color: #fff;
  }
  .col-group-rm {
    background: #3a7a4a;
    color: #fff;
  }
  .col-group-pc {
    background: #7a5a2a;
    color: #fff;
  }
  thead tr:last-child th {
    background: #3a6b96;
    color: #fff;
    padding: 4px 5px;
    text-align: left;
    white-space: nowrap;
    border: 1px solid #2c5070;
  }
  thead tr:last-child th.num-col {
    text-align: right;
  }
  td {
    border: 1px solid #ddd;
    padding: 3px 5px;
    vertical-align: top;
  }
  tr:nth-child(even) td {
    background: #f7f9fb;
  }
  tr:nth-child(odd) td {
    background: #ffffff;
  }
  td.num-col {
    text-align: right;
  }
  .customs-doc {
    background: #fffbe6 !important;
    font-weight: bold;
    color: #5d3a00;
  }
  .fg-group-start td {
    border-top: 2px solid #2c5f8a;
  }
  .footer-end {
    margin-top: 20px;
    text-align: center;
    font-size: 10px;
    font-weight: bold;
    color: #555;
    border-top: 1px solid #ccc;
    padding-top: 8px;
  }
  .footer-note {
    margin-top: 6px;
    font-size: 8px;
    color: #888;
    text-align: center;
  }
  @media print {
    .invoice-block { page-break-inside: avoid; }
  }
"""

	html_parts = [f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<title>Customs Export Traceability Report</title>
<style>{css}</style>
</head>
<body>
<div class="report-header">
  <h1>Customs Export Traceability Report</h1>
  <p class="company-name">{company}</p>
  <p class="meta">Printed: {print_datetime} &nbsp;&nbsp;|&nbsp;&nbsp; Printed by: {printed_by}</p>
</div>
<div class="filter-summary"><strong>Filters applied:</strong> {filter_summary}</div>
"""]

	for si_name, rows in invoices.items():
		first = rows[0]
		posting_date = _v(first.get("posting_date"))
		customer = _v(first.get("customer"))
		customer_name = _v(first.get("customer_name"))
		currency = _v(first.get("currency"))
		si_company = _v(first.get("company"))

		# Additional header fields from SI
		si_extra = si_details.get(si_name, {})
		po_no = _v(si_extra.get("po_no"))
		territory = _v(si_extra.get("territory"))
		remarks = _v(si_extra.get("remarks"))
		customer_address = _v(si_extra.get("address_display") or si_extra.get("customer_address"))
		company_address = _v(si_extra.get("company_address_display"))

		# Build header grid fields
		header_fields = [
			("Sales Invoice", _v(si_name)),
			("Posting Date", posting_date),
			("Company", si_company),
			("Currency", currency),
			("Customer", customer),
			("Customer Name", customer_name),
		]
		if po_no:
			header_fields.append(("PO Reference", po_no))
		if territory:
			header_fields.append(("Territory", territory))
		if company_address:
			header_fields.append(("Company Address", company_address))
		if customer_address:
			header_fields.append(("Customer Address", customer_address))

		grid_cells = "".join(
			f'<div class="field-pair"><span class="field-label">{lbl}</span>'
			f'<span class="field-value">{val if val else "&mdash;"}</span></div>'
			for lbl, val in header_fields
		)

		remarks_row = (
			f'<div class="invoice-header-remarks"><strong>Remarks:</strong> {remarks}</div>'
			if remarks else ""
		)

		html_parts.append(f"""<div class="invoice-block">
<div class="invoice-header-block">
  <div class="si-title">{_v(si_name)}</div>
  <div class="invoice-header-grid">{grid_cells}</div>
  {remarks_row}
</div>
<table>
{table_headers}
<tbody>
""")

		# Track FG grouping for visual separators
		prev_fg_key = None
		for row in rows:
			fg_key = (row.get("si_item_idx"), row.get("fg_item_code"))
			is_new_fg = fg_key != prev_fg_key
			prev_fg_key = fg_key
			row_class = ' class="fg-group-start"' if is_new_fg else ""

			cdn = _v(row.get("customs_document_no"))
			cdn_cell = f'<td class="customs-doc num-col">{cdn}</td>' if cdn else '<td class="num-col"></td>'

			html_parts.append(f"""<tr{row_class}>
  <td>{_v(row.get("si_item_idx"))}</td>
  <td>{_v(row.get("fg_item_code"))}</td>
  <td>{_v(row.get("fg_item_name"))}</td>
  <td class="num-col">{_v(row.get("sales_qty"))}</td>
  <td>{_v(row.get("sales_uom"))}</td>
  <td>{_v(row.get("fg_batch_no"))}</td>
  <td>{_v(row.get("work_order"))}</td>
  <td>{_v(row.get("manufacturing_date"))}</td>
  <td>{_v(row.get("rm_item_code"))}</td>
  <td>{_v(row.get("rm_item_name"))}</td>
  <td class="num-col">{_v(row.get("consumed_qty"))}</td>
  <td>{_v(row.get("rm_batch_no"))}</td>
  <td>{_v(row.get("purchase_receipt"))}</td>
  <td>{_v(row.get("purchase_receipt_date"))}</td>
  <td>{_v(row.get("supplier"))}</td>
  <td>{_v(row.get("supplier_name"))}</td>
  {cdn_cell}
</tr>
""")
		html_parts.append("""</tbody>
</table>
</div>
""")

	html_parts.append("""<div class="footer-end">&mdash; End of Report &mdash;</div>
<div class="footer-note">
  Blank fields indicate that traceability could not be established from available ERPNext data.
  Only submitted documents (Sales Invoice, Stock Entry, Purchase Receipt) are included.
  Raw material consumption is based on actual Stock Entry records, not BOM explosion.
</div>
</body>
</html>
""")

	return "".join(html_parts)
