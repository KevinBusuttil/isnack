import json
from decimal import Decimal, ROUND_CEILING
import frappe
from frappe import _
from frappe.utils import now_datetime, add_to_date, cstr, nowdate, flt, getdate
from frappe.utils.print_format import print_by_server 
from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt
from isnack.utils.printing import get_label_printer 
from erpnext.stock.doctype.batch.batch import get_batch_qty

# --- Helpers -----------------------------------------------------------------


def _default_company():
    return frappe.defaults.get_user_default("company") or frappe.db.get_single_value(
        "Global Defaults", "default_company"
    )

def _wip_for(wo: dict) -> str:
    """Prefer WO's wip_warehouse field."""
    if isinstance(wo, dict):
        wip = wo.get("wip_warehouse")
    else:
        wip = getattr(wo, "wip_warehouse", None)
    return wip or ""

def _wo_line(wo_doc):
    """Resolve Factory Line for a Work Order."""
    if getattr(wo_doc, "custom_factory_line", None):
        return wo_doc.custom_factory_line

    if getattr(wo_doc, "bom_no", None):
        line = frappe.db.get_value("BOM", wo_doc.bom_no, "custom_default_factory_line")
        if line:
            return line

    if getattr(wo_doc, "operations", None):
        try:
            if wo_doc.operations:
                return wo_doc.operations[0].workstation
        except Exception:
            return None
    return None

def _required_map_for_wo(wo_name: str) -> dict:
    """Return required qty per item_code for a WO (BOM Explosion * WO.qty)."""
    wo = frappe.get_doc("Work Order", wo_name)
    rows = frappe.db.sql(
        """
        select bi.item_code, bi.stock_uom, sum(coalesce(bi.qty_consumed_per_unit, 0)) as qty_per_unit
        from `tabBOM Explosion Item` bi
        where bi.parent = %s
        group by bi.item_code, bi.stock_uom
        """,
        (wo.bom_no,),
        as_dict=True,
    )
    req = {}
    for r in rows:
        req[r.item_code] = {
            "uom": r.stock_uom,
            "qty": float(r.qty_per_unit) * float(wo.qty),
        }
    return req

def _required_leaf_map_for_wo(wo_name: str) -> dict:
    """Return required qty per item_code for leaf (non-sub-assembly) BOM items only."""
    wo = frappe.get_doc("Work Order", wo_name)
    rows = frappe.db.sql(
        """
        select
            bi.item_code,
            bi.stock_uom,
            sum(coalesce(bi.qty_consumed_per_unit, bi.qty, 0)) as qty_per_unit
        from `tabBOM Item` bi
        where bi.parent = %s
          and coalesce(bi.bom_no, '') = ''
        group by bi.item_code, bi.stock_uom
        """,
        (wo.bom_no,),
        as_dict=True,
    )
    req = {}
    for r in rows:
        req[r.item_code] = {
            "uom": r.stock_uom,
            "qty": float(r.qty_per_unit) * float(wo.qty),
        }
    return req

def _transferred_map_for_wo(wo_name: str, target_wh: str) -> dict:
    """Return already-transferred qty per item_code into the WIP warehouse for this WO.
    
    Counts both 'Material Transfer for Manufacture' and 'Material Transfer' which move materials to staging/WIP.
    """
    if not target_wh:
        return {}
    rows = frappe.db.sql(
        """
        select sei.item_code, sum(sei.qty) as qty
        from `tabStock Entry` se
        join `tabStock Entry Detail` sei on sei.parent = se.name
        where se.docstatus = 1
          and se.purpose in ('Material Transfer for Manufacture', 'Material Transfer')
          and se.work_order = %s
          and coalesce(sei.t_warehouse, se.to_warehouse) = %s
        group by sei.item_code
        """,
        (wo_name, target_wh),
        as_dict=True,
    )
    return {r.item_code: float(r.qty) for r in rows}


def _staging_for(wo_doc):
    """Return staging warehouse from Factory Settings -> Line Warehouse Map (by Factory Line)."""
    # Child table for Factory Settings line_warehouse_map
    meta = frappe.get_meta("Line Warehouse Map")
    fields = ["factory_line", "staging_warehouse"]
    if meta.has_field("workstation"):
        fields.append("workstation")

    rows = frappe.get_all(
        "Line Warehouse Map",
        fields=fields,
        filters={},
    )
    if not rows:
        return None

    line = _wo_line(wo_doc)
    if not line:
        return None

    for r in rows:
        row_line = r.get("factory_line") or r.get("workstation")
        if row_line == line:
            return r.staging_warehouse or None

    return None


def _remaining_map_for_wo(wo_name: str) -> dict:
    """Remaining qty per item_code for staging (never negative).

    We look at transfers into the WO's staging warehouse (from Factory Settings
    Line Warehouse Map) if configured, otherwise its WIP warehouse.
    """
    wo = frappe.get_doc("Work Order", wo_name)
    target_wh = _staging_for(wo) or _wip_for(wo)
    req = _required_map_for_wo(wo_name)
    have = _transferred_map_for_wo(wo_name, target_wh) if target_wh else {}
    out = {}
    for item, info in req.items():
        rem = max(0.0, float(info["qty"]) - float(have.get(item, 0.0)))
        if rem > 0:
            out[item] = {"uom": info["uom"], "qty": rem}
    return out

def _remaining_leaf_map_for_wo(wo_name: str) -> dict:
    """Remaining qty per item_code for leaf BOM items (never negative)."""
    wo = frappe.get_doc("Work Order", wo_name)
    target_wh = _staging_for(wo) or _wip_for(wo)
    req = _required_leaf_map_for_wo(wo_name)
    have = _transferred_map_for_wo(wo_name, target_wh) if target_wh else {}
    out = {}
    for item, info in req.items():
        rem = max(0.0, float(info["qty"]) - float(have.get(item, 0.0)))
        if rem > 0:
            out[item] = {"uom": info["uom"], "qty": rem}
    return out


def _stage_status(work_order_name: str) -> str:
    """Return 'Not Staged' | 'Partial' | 'Staged' for this WO.

    We consider transfers into the WO's staging warehouse (Factory Settings →
    Line Warehouse Map) if present, otherwise its WIP warehouse.

    Only leaf BOM items (raw materials without their own BOM) are considered
    when determining staged vs. partial to avoid counting sub-assembly rows.
    """
    wo = frappe.get_doc("Work Order", work_order_name)
    target_wh = _staging_for(wo) or _wip_for(wo)
    if not target_wh:
        return "Not Staged"

    rows = frappe.db.sql(
        """
        select sei.item_code, sum(sei.qty) as qty
        from `tabStock Entry` se
        join `tabStock Entry Detail` sei on sei.parent = se.name
        where se.docstatus = 1
          and se.purpose in ('Material Transfer for Manufacture', 'Material Transfer')
          and se.work_order = %s
          and coalesce(sei.t_warehouse, se.to_warehouse) = %s
        group by sei.item_code
        """,
        (work_order_name, target_wh),
        as_dict=True,
    )
    if not rows:
        return "Not Staged"

    req = _required_leaf_map_for_wo(work_order_name)
    have_map = {r.item_code: float(r.qty or 0) for r in rows}
    qty_precision = frappe.get_precision("Stock Entry Detail", "qty") or 3
    partial = any(
        flt(have_map.get(item, 0.0), qty_precision)
        < flt(float(info["qty"]), qty_precision)
        for item, info in req.items()
    )
    return "Partial" if partial else "Staged"


def _order_wos_fifo(wo_names):
    if not wo_names:
        return []
    rows = frappe.get_all(
        "Work Order",
        filters={"name": ["in", wo_names]},
        fields=["name", "planned_start_date", "creation"],
        order_by="planned_start_date asc, creation asc",
    )
    order = [r.name for r in rows]
    for w in wo_names:
        if w not in order:
            order.append(w)
    return order


# --- Factory Line helpers -----------------------------------------------------

def _resolve_line_for_row(row: dict, bom_line_map: dict[str, str | None]) -> str | None:
    """Resolve Factory Line for a WO row, preferring WO fields then BOM default."""
    if not row:
        return None
    if row.get("custom_factory_line"):
        return row.get("custom_factory_line")
    if row.get("bom_no") and bom_line_map.get(row.get("bom_no")):
        return bom_line_map.get(row.get("bom_no"))
    return None

def _normalize_factory_line(value: str | None) -> str | None:
    """Trim and blank-to-None normalization for factory line filter values."""
    line = (cstr(value) or "").strip()
    return line or None

def _filter_wos_by_factory_line(wos, factory_line):
    """Given WO rows with bom_no, filter by Factory Line (WO fields or BOM default)."""
    factory_line = _normalize_factory_line(factory_line)    
    if not factory_line:
        return wos
    bom_nos = list({w["bom_no"] for w in wos if w.get("bom_no")})
    bom_rows = (
        frappe.get_all(
            "BOM",
            filters={"name": ["in", bom_nos]},
            fields=["name", "custom_default_factory_line"],
        )
        if bom_nos
        else []
    )
    bom_map = {b["name"]: b.get("custom_default_factory_line") for b in bom_rows}

    out = []
    for w in wos:
        line = _resolve_line_for_row(w, bom_map)
        if line:
            w["factory_line"] = line
        if line == factory_line:
            out.append(w)
    return out


# --- Page APIs (hub) ---------------------------------------------------------


@frappe.whitelist()
def get_queue(factory_line: str | None = None, posting_date: str | None = None):
    """Work Orders Not Started/In Process; normalized for UI; optional filter by Factory Line
    (WO field or BOM default) and Production Plan posting_date.
    """
    factory_line = _normalize_factory_line(factory_line)
    filters = {"status": ["in", ["Not Started", "In Process"]]}
    company = _default_company()
    if company:
        filters["company"] = company

    # NEW: filter WOs by Production Plan posting_date, if provided
    if posting_date:
        pp_names = frappe.get_all(
            "Production Plan",
            filters={"posting_date": posting_date},
            pluck="name",
        )
        if not pp_names:
            # No Production Plans on that date => no WOs to return
            return []
        filters["production_plan"] = ["in", pp_names]

    wos = frappe.get_all(
        "Work Order",
        filters=filters,
        fields=[
            "name",
            "production_item",
            "item_name",
            "qty",
            "stock_uom",
            "wip_warehouse",
            "planned_start_date",
            "company",
            "bom_no",
            "production_plan",
            "custom_factory_line",
        ],
        order_by="planned_start_date asc, creation asc",
    )

    wos = _filter_wos_by_factory_line(wos, factory_line)

    for w in wos:
        w["item_code"] = w.get("production_item")
        w["uom"] = w.get("stock_uom")
        try:
            w["stage_status"] = _stage_status(w["name"])
        except Exception:
            # Fallback: if anything has ever been transferred, treat as Partial
            w["stage_status"] = (
                "Partial"
                if frappe.db.exists(
                    "Stock Entry",
                    {
                        "work_order": w["name"],
                        "purpose": ["in", ["Material Transfer for Manufacture", "Material Transfer"]],
                        "docstatus": 1,
                    },
                )
                else "Not Staged"
            )
    return wos


@frappe.whitelist()
def get_buckets(factory_line: str | None = None, posting_date: str | None = None):
    """Group open WOs by BOM (same-BOM bucket), optionally filtered by Factory Line and
    Production Plan posting_date.
    """
    factory_line = _normalize_factory_line(factory_line)
    filters = {"status": ["in", ["Not Started", "In Process"]]}
    company = _default_company()
    if company:
        filters["company"] = company

    # NEW: filter WOs by Production Plan posting_date, if provided
    if posting_date:
        pp_names = frappe.get_all(
            "Production Plan",
            filters={"posting_date": posting_date},
            pluck="name",
        )
        if not pp_names:
            return []
        filters["production_plan"] = ["in", pp_names]

    wos = frappe.get_all(
        "Work Order",
        filters=filters,
        fields=[
            "name",
            "production_item",
            "item_name",
            "qty",
            "stock_uom",
            "bom_no",
            "planned_start_date",
            "wip_warehouse",
            "company",
            "production_plan",
            "custom_factory_line",
        ],
        order_by="planned_start_date asc, creation asc",
    )

    wos = _filter_wos_by_factory_line(wos, factory_line)

    buckets = {}
    for w in wos:
        key = w["bom_no"]
        if key not in buckets:
            buckets[key] = {
                "bom_no": w["bom_no"],
                "item_code": w["production_item"],
                "item_name": w["item_name"],
                "uom": w.get("stock_uom"),
                "total_qty": 0.0,
                "wos": [],
            }
        w["item_code"] = w["production_item"]
        w["uom"] = w.get("stock_uom")

        try:
            w["stage_status"] = _stage_status(w["name"])
        except Exception:
            w["stage_status"] = (
                "Partial"
                if frappe.db.exists(
                    "Stock Entry",
                    {
                        "work_order": w["name"],
                        "purpose": ["in", ["Material Transfer for Manufacture", "Material Transfer"]],
                        "docstatus": 1,
                    },
                )
                else "Not Staged"
            )

        buckets[key]["wos"].append(w)
        buckets[key]["total_qty"] += float(w["qty"] or 0)

    return sorted(buckets.values(), key=lambda b: (cstr(b["item_name"]), cstr(b["bom_no"])))


@frappe.whitelist()
def get_available_batches(item_code: str, warehouse: str):
    """Get available batches for an item in a warehouse with their quantities.
    
    Returns: [{'batch_id': str, 'qty': float, 'expiry_date': date, 'manufacturing_date': date}]
    """
    if not item_code or not warehouse:
        frappe.logger().debug(f"get_available_batches: Missing parameters - item_code={item_code}, warehouse={warehouse}")
        return []
    
    frappe.logger().debug(f"Fetching batches for item={item_code}, warehouse={warehouse}")
    
    # Use ERPNext's built-in batch query
    batches = get_batch_qty(
        item_code=item_code,
        warehouse=warehouse,
        for_stock_levels=True
    )
    
    if not batches:
        frappe.logger().debug(f"No batches found for item={item_code} in warehouse={warehouse}")
        return []
    
    # Get additional batch details (expiry_date, manufacturing_date)
    batch_nos = [b.get('batch_no') for b in batches if b.get('batch_no')]
    
    if not batch_nos:
        return []
    
    batch_details = frappe.get_all(
        'Batch',
        filters={
            'name': ['in', batch_nos],
            'disabled': 0
        },
        fields=['name', 'expiry_date', 'manufacturing_date']
    )
    
    # Create a map for quick lookup
    details_map = {b.name: b for b in batch_details}
    
    # Combine qty data with batch details
    result = []
    for batch in batches:
        batch_no = batch.get('batch_no')
        qty = batch.get('qty', 0)
        
        if qty > 0 and batch_no in details_map:
            details = details_map[batch_no]
            result.append({
                'batch_id': batch_no,
                'qty': qty,
                'expiry_date': details.expiry_date,
                'manufacturing_date': details.manufacturing_date
            })
    
    # Sort by expiry date (nulls last) then by creation
    result.sort(key=lambda x: (x['expiry_date'] or '9999-12-31', x['batch_id']))
    
    frappe.logger().debug(f"Found {len(result)} batches with stock for item={item_code} in warehouse={warehouse}")
    
    return result


@frappe.whitelist()
def create_consolidated_transfers(
    pallet_id: str = "",
    source_warehouse: str = "",
    selected_wos=None,
    items=None,
):
    """Option C: fan-out one physical pick into multiple WO-linked Stock Entries."""
    # Parse inputs (may arrive as JSON strings)
    if isinstance(selected_wos, str):
        selected_wos = json.loads(selected_wos or "[]")
    if isinstance(items, str):
        items = json.loads(items or "[]")

    if not selected_wos:
        frappe.throw(_("No Work Orders selected."))
    if not items:
        frappe.throw(_("No items in the cart."))

    if not source_warehouse:
        source_warehouse = frappe.db.get_single_value("Stock Settings", "default_warehouse")
    if not source_warehouse:
        frappe.throw(_("Source Warehouse is required (set Stock Settings: Default Warehouse)."))

    item_codes = [row.get("item_code") for row in (items or []) if isinstance(row, dict) and row.get("item_code")]
    item_meta = {}
    if item_codes:
        item_meta = {
            row.name: row
            for row in frappe.get_all(
                "Item",
                fields=["name", "has_batch_no"],
                filters={"name": ["in", list(set(item_codes))]},
            )
        }
        for row in items or []:
            if not isinstance(row, dict):
                continue
            item_code = row.get("item_code")
            if not item_code:
                continue
            
            # Check if item requires batch
            if item_meta.get(item_code, {}).get("has_batch_no"):
                # Check if batches are assigned (either single or multi-batch)
                has_batches = bool(row.get("batches") and len(row.get("batches")) > 0)
                has_single_batch = bool(row.get("batch_no"))
                
                if not has_batches and not has_single_batch:
                    frappe.throw(_("Batch No is required for item {0}.").format(item_code))

    # Build batch information map: item_code -> list of {batch_no, qty} or single batch_no
    batch_info_map = {}
    for row in items or []:
        if not isinstance(row, dict):
            continue
        item_code = row.get("item_code")
        if not item_code:
            continue
        
        # Check if item has multiple batches assigned
        if row.get("batches") and isinstance(row.get("batches"), list) and len(row.get("batches")) > 0:
            batch_info_map[item_code] = row.get("batches")  # list of {batch_no, qty}
        elif row.get("batch_no"):
            batch_info_map[item_code] = row.get("batch_no")  # single batch string
        else:
            batch_info_map[item_code] = None

    wo_order = _order_wos_fifo(selected_wos)
    remaining = {wo: _remaining_map_for_wo(wo) for wo in wo_order}

    # Allocation: per item -> distribute across WOs until qty exhausted (capped by remaining)
    allocations = {wo: {} for wo in wo_order}
    for row in items or []:
        if not isinstance(row, dict):
            continue
        item = row.get("item_code")
        qty_left = float(row.get("qty") or 0)
        if not item or qty_left <= 0:
            continue
        for wo in wo_order:
            rem = float(remaining.get(wo, {}).get(item, {}).get("qty", 0))
            if rem <= 0:
                continue
            take = min(rem, qty_left)
            if take > 0:
                allocations[wo][item] = allocations[wo].get(item, 0.0) + take
                remaining[wo][item]["qty"] -= take
                qty_left -= take
            if qty_left <= 1e-9:
                break

    created = []
    for wo in wo_order:
        alloc = allocations.get(wo) or {}
        if not alloc:
            continue
        wo_doc = frappe.get_doc("Work Order", wo)

        target_staging = _staging_for(wo_doc)
        target_wip = _wip_for(wo_doc)
        target_wh = target_staging or target_wip

        if not target_wh:
            frappe.throw(_("No Staging or WIP warehouse configured for WO {0}").format(wo))

        se = frappe.new_doc("Stock Entry")
        se.company = wo_doc.company
        se.stock_entry_type = "Material Transfer"  # Changed from "Material Transfer for Manufacture"
        se.purpose = "Material Transfer"  # Explicitly set purpose
        # Note: we still link to work_order for reference tracking in remarks
        se.from_warehouse = source_warehouse
        se.to_warehouse = target_wh

        # Remove BOM-related fields since this is just a staging transfer
        # These should only be used for "Material Transfer for Manufacture"
        # se.from_bom = 1
        # se.bom_no = wo_doc.bom_no
        # se.use_multi_level_bom = wo_doc.use_multi_level_bom
        # se.fg_completed_qty = ...

        # Add WO reference in remarks for tracking
        if pallet_id:
            se.remarks = f"Pallet: {pallet_id} | WO: {wo_doc.name}"
        else:
            se.remarks = f"Staging transfer for WO: {wo_doc.name}"

        for item_code, qty in alloc.items():
            rounded_qty = _round_up_qty(qty, precision=3)
            uom = (
                remaining.get(wo, {}).get(item_code, {}).get("uom")
                or frappe.db.get_value("Item", item_code, "stock_uom")
            )
            
            # Get batch info for this item
            batch_info = batch_info_map.get(item_code)
            
            # Handle multiple batches
            if isinstance(batch_info, list) and len(batch_info) > 0:
                # Multiple batches: create one line per batch, proportionally allocating the WO qty
                total_batch_qty = sum(float(b.get("qty", 0)) for b in batch_info)
                
                if total_batch_qty <= 0:
                    continue
                
                allocated_so_far = 0.0
                for i, batch_item in enumerate(batch_info):
                    batch_no = batch_item.get("batch_no")
                    batch_qty = float(batch_item.get("qty", 0))
                    
                    if batch_qty <= 0:
                        continue
                    
                    # For the last batch, use remaining quantity to avoid rounding errors
                    if i == len(batch_info) - 1:
                        line_qty = max(0.0, rounded_qty - allocated_so_far)
                    else:
                        # Proportional allocation: (batch_qty / total_batch_qty) * allocated_qty_for_this_wo
                        proportion = batch_qty / total_batch_qty
                        line_qty = _round_up_qty(rounded_qty * proportion, precision=3)
                        allocated_so_far += line_qty
                    
                    if line_qty > 0:
                        se.append(
                            "items",
                            {
                                "item_code": item_code,
                                "qty": line_qty,
                                "uom": uom,
                                "s_warehouse": source_warehouse,
                                "t_warehouse": target_wh,
                                "batch_no": batch_no,
                            },
                        )
            else:
                # Single batch or no batch
                batch_no = batch_info if isinstance(batch_info, str) else None
                se.append(
                    "items",
                    {
                        "item_code": item_code,
                        "qty": rounded_qty,
                        "uom": uom,
                        "s_warehouse": source_warehouse,
                        "t_warehouse": target_wh,
                        "batch_no": batch_no,
                    },
                )

        se.insert(ignore_permissions=True)
        se.submit()
        created.append(
            {
                "name": se.name,
                "work_order": wo_doc.name,
                "to_warehouse": target_wh,
                "posting_date": se.posting_date,
                "posting_time": se.posting_time,
            }
        )

    return {"transfers": created}

def _round_up_qty(value, precision=3):
    qty = Decimal(str(value or 0))
    quantum = Decimal("1").scaleb(-precision)
    return float(qty.quantize(quantum, rounding=ROUND_CEILING))

@frappe.whitelist()
def get_recent_transfers(
    factory_line: str | None = None,
    hours: int = 24,
    posting_date: str | None = None,
):
    """Material Transfers for Manufacture.

    If posting_date is given, filter by Work Orders whose Production Plan has that posting_date.
    Otherwise, fallback to "last N hours" based on se.modified.
    """
    factory_line = _normalize_factory_line(factory_line)
    joins = ["left join `tabWork Order` wo on wo.name = se.work_order"]
    conditions = [
        "se.docstatus = 1",
        "se.purpose = 'Material Transfer for Manufacture'",
    ]
    params: list[object] = []

    if factory_line:
        joins.append("left join `tabBOM` bom on bom.name = wo.bom_no")
        conditions.append(
            "(wo.custom_factory_line = %s or bom.custom_default_factory_line = %s)"
        )
        params.extend([factory_line, factory_line])

    if posting_date:
        joins.append("left join `tabProduction Plan` pp on pp.name = wo.production_plan")
        conditions.append("pp.posting_date = %s")
        params.append(posting_date)
    else:
        since = add_to_date(now_datetime(), hours=-int(hours))
        conditions.append("se.modified >= %s")
        params.append(since)

    query = f"""
        select
            se.name,
            se.posting_date,
            se.posting_time,
            se.to_warehouse,
            se.remarks,
            se.work_order
        from `tabStock Entry` se
        {' '.join(joins)}
        where {' and '.join(conditions)}
        order by se.posting_date desc, se.posting_time desc, se.modified desc
        limit 50
    """
    se_list = frappe.db.sql(query, tuple(params), as_dict=True)

    # --- Mark which of these Stock Entries are already in a Picklist ---
    se_names = [d["name"] for d in se_list]
    in_picklist = set()

    if se_names:
        try:
            rows = frappe.db.sql(
                """
                select distinct pt.stock_entry
                from `tabPicklist Transfer` pt
                join `tabPicklist` p on p.name = pt.parent
                where pt.stock_entry in %(names)s
                  and p.docstatus < 2
                """,
                {"names": tuple(se_names)},
                as_dict=True,
            )
            in_picklist = {r["stock_entry"] for r in rows}
        except Exception:
            in_picklist = set()

    for d in se_list:
        d["in_picklist"] = 1 if d["name"] in in_picklist else 0

    return se_list

@frappe.whitelist()
def get_recent_manual_stock_entries(
    source_warehouse: str | None = None,
    hours: int = 24,
    purposes: str | None = None,
):
    """Recent manual Stock Entries (non-WO) for a given warehouse and purposes.

    Defaults to Material Transfer, Material Issue, Material Receipt.
    """
    # parse purposes argument (can be JSON list or comma-separated)
    if isinstance(purposes, str) and purposes:
        try:
            purposes_list = json.loads(purposes)
            if not isinstance(purposes_list, (list, tuple)):
                purposes_list = [cstr(purposes_list)]
        except Exception:
            purposes_list = [p.strip() for p in purposes.split(",") if p.strip()]
    else:
        purposes_list = [
            "Material Transfer",
            "Material Issue",
            "Material Receipt",
        ]

    if not purposes_list:
        return []

    since = add_to_date(now_datetime(), hours=-int(hours))

    conditions = [
        "se.docstatus = 1",
        "se.work_order is null",
        "se.purpose in %(purposes)s",
        "se.modified >= %(since)s",
    ]
    params = {
        "purposes": tuple(purposes_list),
        "since": since,
    }

    if source_warehouse:
        conditions.append(
            "(se.from_warehouse = %(wh)s or se.to_warehouse = %(wh)s)"
        )
        params["wh"] = source_warehouse

    query = f"""
        select
            se.name,
            se.posting_date,
            se.posting_time,
            se.from_warehouse,
            se.to_warehouse,
            se.purpose,
            se.remarks
        from `tabStock Entry` se
        where {' and '.join(conditions)}
        order by se.modified desc
        limit 50
    """

    return frappe.db.sql(query, params, as_dict=True)

@frappe.whitelist()
def get_recent_pallets(factory_line: str | None = None, hours: int = 24):
    """List Material Transfers that include 'Pallet:' in remarks, optionally filtered by Factory Line."""
    factory_line = _normalize_factory_line(factory_line)
    if factory_line:
        q = """
            select se.name, se.posting_date, se.posting_time, se.to_warehouse, se.remarks
            from `tabStock Entry` se
            left join `tabWork Order` wo on wo.name = se.work_order
            left join `tabBOM` bom on bom.name = wo.bom_no
            where se.docstatus=1 and se.purpose='Material Transfer for Manufacture'
              and (wo.custom_factory_line = %s or bom.custom_default_factory_line = %s)
            order by se.modified desc
            limit 100
        """
        rows = frappe.db.sql(q, (factory_line, factory_line), as_dict=True)
    else:
        rows = frappe.get_all(
            "Stock Entry",
            filters={"docstatus": 1, "purpose": "Material Transfer for Manufacture"},
            fields=["name", "posting_date", "posting_time", "to_warehouse", "remarks"],
            order_by="modified desc",
            limit_page_length=100,
        )
    out = []
    for r in rows:
        if r.get("remarks") and "Pallet:" in r["remarks"]:
            text = r["remarks"]
            try:
                pallet = text.split("Pallet:")[1].strip().split()[0]
            except Exception:
                pallet = ""
            out.append(
                {
                    "name": r["name"],
                    "posting_date": r["posting_date"],
                    "posting_time": r["posting_time"],
                    "to_warehouse": r["to_warehouse"],
                    "pallet_id": pallet,
                }
            )
    return out


@frappe.whitelist()
def print_labels(stock_entry: str):
    fmt = "Pallet Label Material Transfer"
    printer_setting = get_label_printer()  # returns the *name* of a Network Printer Settings doc

    if not printer_setting:
        frappe.throw(_("No label printer configured."))

    print_by_server(
        "Stock Entry",
        stock_entry,
        printer_setting=printer_setting,   # name of Network Printer Settings
        print_format=fmt
    )


@frappe.whitelist()
def find_se_by_item_row(rowname: str):
    parent = frappe.db.get_value("Stock Entry Detail", rowname, "parent")
    return parent


# --- NEW: Remaining requirement helpers (for auto-fill) ----------------------


@frappe.whitelist()
def get_consolidated_remaining(selected_wos=None, item_code: str | None = None):
    """Return consolidated remaining requirement for `item_code` across selected WOs.
    Response: {'item_code': str, 'qty': float, 'uom': str}
    """
    if isinstance(selected_wos, str):
        try:
            selected_wos = json.loads(selected_wos or "[]")
        except Exception:
            selected_wos = []
    selected_wos = selected_wos or []
    item_code = (item_code or "").strip()

    if not item_code:
        return {"item_code": "", "qty": 0.0, "uom": ""}

    if not selected_wos:
        # fallback to item stock uom if no WOs selected
        uom = frappe.db.get_value("Item", item_code, "stock_uom")
        return {"item_code": item_code, "qty": 0.0, "uom": uom}

    total = 0.0
    uom = None
    for wo in selected_wos:
        rem = _remaining_map_for_wo(wo).get(item_code)
        if rem:
            total += float(rem.get("qty") or 0)
            uom = uom or rem.get("uom")
    if not uom:
        uom = frappe.db.get_value("Item", item_code, "stock_uom")
    return {"item_code": item_code, "qty": total, "uom": uom}


@frappe.whitelist()
def get_consolidated_remaining_bulk(selected_wos=None, item_codes=None):
    """Bulk version. Returns: [{'item_code':..., 'qty':..., 'uom':...}, ...]"""
    if isinstance(selected_wos, str):
        try:
            selected_wos = json.loads(selected_wos or "[]")
        except Exception:
            selected_wos = []
    if isinstance(item_codes, str):
        try:
            item_codes = json.loads(item_codes or "[]")
        except Exception:
            item_codes = []
    selected_wos = selected_wos or []
    item_codes = [c for c in (item_codes or []) if c]

    out = []
    for code in item_codes:
        out.append(get_consolidated_remaining(selected_wos=selected_wos, item_code=code))
    return out

@frappe.whitelist()
def get_consolidated_remaining_items(selected_wos=None):
    """Return all raw-material items (leaf BOM items) with remaining requirement across selected WOs.

    Response: [{'item_code': str, 'qty': float, 'uom': str}]
    """
    if isinstance(selected_wos, str):
        try:
            selected_wos = json.loads(selected_wos or "[]")
        except Exception:
            selected_wos = []
    selected_wos = selected_wos or []

    totals = {}
    for wo in selected_wos:
        remaining = _remaining_leaf_map_for_wo(wo)
        for item_code, info in remaining.items():
            if not item_code:
                continue
            entry = totals.setdefault(item_code, {"item_code": item_code, "qty": 0.0, "uom": info.get("uom")})
            entry["qty"] += float(info.get("qty") or 0)
            if not entry.get("uom") and info.get("uom"):
                entry["uom"] = info.get("uom")

    item_meta = {}
    if totals:
        item_meta = {
            row.name: row
            for row in frappe.get_all(
                "Item",
                fields=["name", "item_name", "has_batch_no"],
                filters={"name": ["in", list(totals.keys())]},
            )
        }
        for item_code, entry in totals.items():
            meta = item_meta.get(item_code)
            if meta:
                entry["item_name"] = meta.item_name or ""
                entry["has_batch_no"] = meta.has_batch_no

    out = [row for row in totals.values() if row.get("qty", 0) > 0]
    return sorted(out, key=lambda r: r.get("item_code") or "")

@frappe.whitelist()
def batch_link_query(doctype, txt, searchfield, start, page_len, filters=None):
    """Batch Link field query with optional item filter and non-expired filter."""
    filters = filters or {}
    txt = (txt or "").strip()
    item_code = filters.get("item_code")
    has_expired = filters.get("has_expired")
    warehouse = filters.get("warehouse")
    today = nowdate()

    conditions = []
    params = {"today": today, "start": start or 0, "page_len": page_len or 20}

    if item_code:
        conditions.append("b.item = %(item_code)s")
        params["item_code"] = item_code

    if has_expired in (0, "0", False, "false", None):
        conditions.append("(b.expiry_date is null or b.expiry_date >= %(today)s)")

    if txt:
        like_txt = f"%{txt}%"
        conditions.append("(b.name like %(txt)s)")
        params["txt"] = like_txt

    qty_conditions = ["sle.is_cancelled = 0"]
    if item_code:
        qty_conditions.append("sle.item_code = %(item_code)s")
    if warehouse:
        qty_conditions.append("sle.warehouse = %(warehouse)s")
        params["warehouse"] = warehouse
    qty_where = " and ".join(qty_conditions)


    where_clause = " and ".join(conditions) if conditions else "1=1"

    rows = frappe.db.sql(
        f"""
        select
            b.name,
            concat_ws(
                ', ',
                ifnull(format(coalesce(b.batch_qty, 0), 2), ''),
                case when b.manufacturing_date is not null then concat('MFG-', date_format(b.manufacturing_date, '%%Y-%%m-%%d')) end,
                case when b.expiry_date is not null then concat('EXP-', date_format(b.expiry_date, '%%Y-%%m-%%d')) end,
                b.name
            ) as description
        from `tabBatch` b
        where {where_clause}
        order by b.expiry_date asc, b.creation desc
        limit %(start)s, %(page_len)s
        """,
        params,
    )
    return rows

@frappe.whitelist()
def generate_picklist(transfers, group_same_items: int | str | None = 1):
    """Create a Picklist from selected Stock Entries.

    transfers:
        JSON array or comma-separated list of Stock Entry names.
    group_same_items:
        1/True => group by (item + from_warehouse + to_warehouse + batch + uom)
        0/False => one row per Stock Entry Detail line.
    """
    # Normalise transfers
    if isinstance(transfers, str):
        try:
            transfers = json.loads(transfers or "[]")
        except Exception:
            transfers = [t.strip() for t in transfers.split(",") if t.strip()]

    if not transfers:
        frappe.throw(_("No Stock Entries selected."))

    # Determine grouping flag
    if isinstance(group_same_items, str):
        group_same = group_same_items not in ("0", "false", "False")
    else:
        group_same = bool(group_same_items)

    # Fetch Stock Entry headers
    se_list = frappe.get_all(
        "Stock Entry",
        filters={"name": ["in", transfers], "docstatus": 1},
        fields=["name", "company", "from_warehouse", "to_warehouse"],
    )
    if not se_list:
        frappe.throw(_("No submitted Stock Entries found for the selected names."))

    companies = {se.company for se in se_list if se.company}
    if len(companies) > 1:
        frappe.throw(
            _("Selected Stock Entries belong to multiple companies. "
              "Please generate a picklist per company.")
        )
    company = next(iter(companies)) if companies else None

    from_whs = {se.from_warehouse for se in se_list if se.from_warehouse}
    to_whs = {se.to_warehouse for se in se_list if se.to_warehouse}

    params = {"transfers": tuple(se.name for se in se_list)}

    if group_same:
        rows = frappe.db.sql(
            """
            select
                sed.item_code,
                sed.item_name,
                coalesce(sed.s_warehouse, se.from_warehouse) as s_warehouse,
                coalesce(sed.t_warehouse, se.to_warehouse) as t_warehouse,
                sed.uom,
                sed.stock_uom,
                sed.batch_no,
                sum(sed.qty) as qty
            from `tabStock Entry` se
            join `tabStock Entry Detail` sed on sed.parent = se.name
            where se.docstatus = 1
              and se.name in %(transfers)s
            group by
                sed.item_code,
                sed.item_name,
                s_warehouse,
                t_warehouse,
                sed.uom,
                sed.stock_uom,
                sed.batch_no
            order by sed.item_code, sed.batch_no
            """,
            params,
            as_dict=True,
        )
    else:
        rows = frappe.db.sql(
            """
            select
                se.name as stock_entry,
                sed.name as stock_entry_detail,
                sed.item_code,
                sed.item_name,
                coalesce(sed.s_warehouse, se.from_warehouse) as s_warehouse,
                coalesce(sed.t_warehouse, se.to_warehouse) as t_warehouse,
                sed.uom,
                sed.stock_uom,
                sed.batch_no,
                sed.qty
            from `tabStock Entry` se
            join `tabStock Entry Detail` sed on sed.parent = se.name
            where se.docstatus = 1
              and se.name in %(transfers)s
            order by sed.item_code, sed.batch_no, se.name
            """,
            params,
            as_dict=True,
        )

    if not rows:
        frappe.throw(_("No items found in selected Stock Entries."))

    # Create Picklist doc
    pick = frappe.new_doc("Picklist")
    if company:
        pick.company = company
    pick.posting_date = nowdate()
    if len(from_whs) == 1:
        pick.from_warehouse = next(iter(from_whs))
    if len(to_whs) == 1:
        pick.to_warehouse = next(iter(to_whs))

    for se in se_list:
        pick.append("transfers", {"stock_entry": se.name})

    for r in rows:
        pick.append(
            "items",
            {
                "item_code": r.get("item_code"),
                "item_name": r.get("item_name"),
                "from_warehouse": r.get("s_warehouse"),
                "to_warehouse": r.get("t_warehouse"),
                "uom": r.get("uom") or r.get("stock_uom"),
                "qty": float(r.get("qty") or 0),
                "batch_no": r.get("batch_no"),
                "stock_entry": r.get("stock_entry") if not group_same else None,
            },
        )

    pick.insert()
    frappe.msgprint(_("Picklist {0} created.").format(pick.name))
    return {"name": pick.name}

@frappe.whitelist()
def get_open_purchase_orders(doctype, txt, searchfield, start, page_len, filters):
    """Query function used by the Link field to show only POs that still need receipt."""
    conditions = [
        "po.docstatus = 1",
        "po.status in ('To Receive and Bill', 'To Receive')",
        "po.per_received < 100",
    ]

    params = {
        "start": start,
        "page_len": page_len,
    }

    if txt:
        params["txt"] = f"%{txt}%"
        conditions.append("(po.name like %(txt)s or po.supplier like %(txt)s)")

    where_clause = " and ".join(conditions)

    data = frappe.db.sql(
        f"""
        select
            po.name,
            po.supplier,
            po.transaction_date,
            po.per_received
        from `tabPurchase Order` po
        where {where_clause}
        order by po.transaction_date desc, po.name desc
        limit %(start)s, %(page_len)s
        """,
        params,
    )

    return data


@frappe.whitelist()
def get_po_items(purchase_order: str):
    """Return pending items for a Purchase Order.

    Only items with remaining (qty - received_qty) > 0 are returned, along with
    basic header fields.
    """
    po = frappe.get_doc("Purchase Order", purchase_order)

    items = []
    for row in po.items:
        ordered = flt(row.qty)
        received = flt(row.received_qty)
        pending = max(0.0, ordered - received)
        if pending <= 0:
            continue

        item_doc = frappe.get_doc("Item", row.item_code)
        requires_batch = bool(getattr(item_doc, "has_batch_no", False))

        items.append(
            {
                "name": row.name,
                "item_code": row.item_code,
                "item_name": row.item_name,
                "uom": row.uom,
                "qty": ordered,
                "received_qty": received,
                "pending_qty": pending,
                "requires_batch": requires_batch,
                # optional: could be populated from item defaults or PO dates
                "default_expiry_date": None,
            }
        )

    return {
        "company": po.company,
        "supplier": po.supplier,
        "items": items,
    }



@frappe.whitelist()
def post_po_receipt(purchase_order, items=None):
    """Create a Purchase Receipt for the given Purchase Order
    using ERPNext's standard PO -> PR mapper, while overriding
    qty / rejected_qty / batch from the dialog.

    Args:
        purchase_order: PO name (e.g. 'PUR-ORD-2025-00044')
        items: JSON string or list of dicts with:
            - po_detail (Purchase Order Item name)
            - accepted_qty
            - rejected_qty
            - batch_no
            - expiry_date
            plus some read-only helpers (item_code, etc.)
    """

    # 1) Normalise items (JS sends JSON string)
    if isinstance(items, str):
        items = json.loads(items or "[]")

    if not items:
        frappe.throw(_("No items received."))

    # 2) Build a map from PO Item (row.name) -> our dialog row
    # Only keep rows where accepted or rejected > 0
    item_map = {}
    for row in items:
        accepted = flt(row.get("accepted_qty") or 0)
        rejected = flt(row.get("rejected_qty") or 0)
        if accepted <= 0 and rejected <= 0:
            continue

        po_detail = row.get("po_detail")
        if not po_detail:
            # nothing to link to -> skip, or you can frappe.throw here
            continue

        item_map[po_detail] = {
            "row": row,
            "accepted": accepted,
            "rejected": rejected,
        }

    if not item_map:
        frappe.throw(_("No quantities to receive."))

    # 3) Let ERPNext create a standard PR from the PO
    # This ensures rate, taxes, currency, etc. all match the PO.
    pr = make_purchase_receipt(purchase_order)

    # 4) Filter & override PR items based on our dialog rows
    new_items = []
    for pr_item in pr.items:
        data = item_map.get(pr_item.purchase_order_item)
        if not data:
            # This PO line wasn't selected in the dialog -> drop it
            continue

        row = data["row"]
        accepted = data["accepted"]
        rejected = data["rejected"]

        total = accepted + rejected
        if total <= 0:
            continue

        # override quantities
        pr_item.qty = total
        pr_item.rejected_qty = rejected

        # batch handling
        batch_no = (row.get("batch_no") or "").strip()
        expiry_date = row.get("expiry_date")
        if batch_no:
            _ensure_batch(pr_item.item_code, batch_no, expiry_date)
            pr_item.batch_no = batch_no

        new_items.append(pr_item)

    if not new_items:
        frappe.throw(_("Nothing to post: all quantities are zero."))

    # Replace items child table with our filtered/edited rows
    pr.set("items", new_items)

    # 5) Save (and optionally submit)
    pr.flags.ignore_permissions = True
    pr.save()
    # pr.submit()  # enable if you want automatic submission

    return {"purchase_receipt": pr.name}


def _ensure_batch(item_code: str, batch_no: str, expiry_date=None):
    """Create or update a Batch for the given item/batch_no."""
    existing_batch = frappe.db.exists("Batch", {"batch_id": batch_no, "item": item_code})
    if existing_batch:
        if expiry_date:
            batch = frappe.get_doc("Batch", existing_batch)
            batch.expiry_date = getdate(expiry_date)
            batch.save()
        return existing_batch

    batch = frappe.get_doc(
        {
            "doctype": "Batch",
            "item": item_code,
            "batch_id": batch_no,
        }
    )
    if expiry_date:
        batch.expiry_date = getdate(expiry_date)
    batch.insert()
    return batch.name