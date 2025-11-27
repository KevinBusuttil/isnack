import json
import frappe
from frappe import _
from frappe.utils import now_datetime, add_to_date, cstr
from frappe.utils.print_format import print_by_server 

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


def _transferred_map_for_wo(wo_name: str, target_wh: str) -> dict:
    """Return already-transferred qty per item_code into the staging/WIP warehouse for this WO."""
    if not target_wh:
        return {}
    rows = frappe.db.sql(
        """
        select sei.item_code, sum(sei.qty) as qty
        from `tabStock Entry` se
        join `tabStock Entry Detail` sei on sei.parent = se.name
        where se.docstatus = 1
          and se.purpose = 'Material Transfer for Manufacture'
          and se.work_order = %s
          and coalesce(sei.t_warehouse, se.to_warehouse) = %s
        group by sei.item_code
        """,
        (wo_name, target_wh),
        as_dict=True,
    )
    return {r.item_code: float(r.qty) for r in rows}


def _staging_for(wo_doc):
    """Return staging warehouse from Factory Settings -> Line Warehouse Map (by workstation)."""
    # Child table for Factory Settings line_warehouse_map
    rows = frappe.get_all(
        "Line Warehouse Map",
        fields=["workstation", "staging_warehouse"],
        filters={},
    )
    if not rows:
        return None

    # Determine workstation / line for this WO:
    workstation = None

    # If you use a custom_line field on Work Order, prefer that
    if getattr(wo_doc, "custom_line", None):
        workstation = wo_doc.custom_line

    # Fallback to first operation's workstation
    if not workstation and getattr(wo_doc, "operations", None):
        try:
            if wo_doc.operations:
                workstation = wo_doc.operations[0].workstation
        except Exception:
            workstation = None

    if not workstation:
        return None

    for r in rows:
        if r.workstation == workstation:
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


def _stage_status(work_order_name: str) -> str:
    """Return 'Not Staged' | 'Partial' | 'Staged' for this WO.

    We consider transfers into the WO's staging warehouse (Factory Settings →
    Line Warehouse Map) if present, otherwise its WIP warehouse.
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
          and se.purpose = 'Material Transfer for Manufacture'
          and se.work_order = %s
          and coalesce(sei.t_warehouse, se.to_warehouse) = %s
        group by sei.item_code
        """,
        (work_order_name, target_wh),
        as_dict=True,
    )
    if not rows:
        return "Not Staged"

    req = _required_map_for_wo(work_order_name)
    have_map = {r.item_code: float(r.qty or 0) for r in rows}
    partial = any(
        have_map.get(item, 0.0) < float(info["qty"]) - 1e-9
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


# --- Routing helpers ----------------------------------------------------------


def _filter_wos_by_routing(wos, routing):
    """Given WO rows with bom_no, filter by BOM.routing (bulk map)."""
    if not routing:
        return wos
    bom_nos = list({w["bom_no"] for w in wos if w.get("bom_no")})
    if not bom_nos:
        return []
    bom_rows = frappe.get_all("BOM", filters={"name": ["in", bom_nos]}, fields=["name", "routing"])
    bom_map = {b["name"]: b.get("routing") for b in bom_rows}
    return [w for w in wos if bom_map.get(w.get("bom_no")) == routing]


# --- Page APIs (hub) ---------------------------------------------------------


@frappe.whitelist()
def get_queue(routing: str | None = None, posting_date: str | None = None):
    """Work Orders Not Started/In Process; normalized for UI; optional filter by BOM.routing
    and Production Plan posting_date.
    """
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
        ],
        order_by="planned_start_date asc, creation asc",
    )

    wos = _filter_wos_by_routing(wos, routing)

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
                        "purpose": "Material Transfer for Manufacture",
                        "docstatus": 1,
                    },
                )
                else "Not Staged"
            )
    return wos


@frappe.whitelist()
def get_buckets(routing: str | None = None, posting_date: str | None = None):
    """Group open WOs by BOM (same-BOM bucket), optionally filtered by BOM.routing
    and Production Plan posting_date.
    """
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
        ],
        order_by="planned_start_date asc, creation asc",
    )

    wos = _filter_wos_by_routing(wos, routing)

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
                        "purpose": "Material Transfer for Manufacture",
                        "docstatus": 1,
                    },
                )
                else "Not Staged"
            )

        buckets[key]["wos"].append(w)
        buckets[key]["total_qty"] += float(w["qty"] or 0)

    return sorted(buckets.values(), key=lambda b: (cstr(b["item_name"]), cstr(b["bom_no"])))


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
        se.stock_entry_type = "Material Transfer for Manufacture"
        se.work_order = wo_doc.name
        se.from_warehouse = source_warehouse
        se.to_warehouse = target_wh
        if pallet_id:
            se.remarks = (se.remarks or "") + f" Pallet: {pallet_id}"

        for item_code, qty in alloc.items():
            uom = (
                remaining.get(wo, {}).get(item_code, {}).get("uom")
                or frappe.db.get_value("Item", item_code, "stock_uom")
            )
            se.append(
                "items",
                {
                    "item_code": item_code,
                    "qty": qty,
                    "uom": uom,
                    "s_warehouse": source_warehouse,
                    "t_warehouse": target_wh,
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


@frappe.whitelist()
def get_recent_transfers(routing: str | None = None, hours: int = 24):
    since = add_to_date(now_datetime(), hours=-int(hours))
    if routing:
        q = """
            select se.name, se.posting_date, se.posting_time, se.to_warehouse, se.remarks, se.work_order
            from `tabStock Entry` se
            left join `tabWork Order` wo on wo.name = se.work_order
            left join `tabBOM` bom on bom.name = wo.bom_no
            where se.docstatus=1 and se.purpose='Material Transfer for Manufacture'
              and se.modified >= %s
              and bom.routing = %s
            order by se.modified desc
            limit 50
        """
        se_list = frappe.db.sql(q, (since, routing), as_dict=True)
    else:
        q = """
            select se.name, se.posting_date, se.posting_time, se.to_warehouse, se.remarks, se.work_order
            from `tabStock Entry` se
            where se.docstatus=1 and se.purpose='Material Transfer for Manufacture'
              and se.modified >= %s
            order by se.modified desc
            limit 50
        """
        se_list = frappe.db.sql(q, (since,), as_dict=True)
    return se_list


@frappe.whitelist()
def get_recent_pallets(routing: str | None = None, hours: int = 24):
    """List Material Transfers that include 'Pallet:' in remarks, optionally filtered by BOM.routing."""
    if routing:
        q = """
            select se.name, se.posting_date, se.posting_time, se.to_warehouse, se.remarks
            from `tabStock Entry` se
            left join `tabWork Order` wo on wo.name = se.work_order
            left join `tabBOM` bom on bom.name = wo.bom_no
            where se.docstatus=1 and se.purpose='Material Transfer for Manufacture'
              and bom.routing = %s
            order by se.modified desc
            limit 100
        """
        rows = frappe.db.sql(q, (routing,), as_dict=True)
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
    """Server-side network printing for pallet labels.

    Uses the Raw Print Format 'Pallet Label – Material Transfer' and the
    default Network Printer configured in Print Settings.
    """
    fmt = "Pallet Label Material Transfer"

    # Get default Network Printer (Print Settings → Network Printer / Print Server)
    printer_setting = frappe.db.get_single_value("Print Settings", "default_printer")
    if not printer_setting:
        frappe.throw(
            _(
                "No default Network Printer configured. "
                "Go to Print Settings and set a Default Printer under "
                "'Network Printer / Print Server'."
            )
        )

    # Frappe v15: print_by_server(doctype, name, printer_setting, print_format=...)
    print_by_server("Stock Entry", stock_entry, printer_setting, print_format=fmt)
    return True



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
