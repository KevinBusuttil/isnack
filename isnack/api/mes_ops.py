from __future__ import annotations

import hashlib
import json
import math
from string import Template
from typing import Optional, Tuple

import frappe
from frappe import _
from frappe.utils import cint, flt
from isnack.isnack.page.storekeeper_hub.storekeeper_hub import (
    _stage_status as _storekeeper_stage_status,
    _process_batch_spaces,
)
from isnack.utils.printing import get_label_printer

# ============================================================
# Factory Settings helpers (Single doctype)
# ============================================================

def _fs():
    """Cached Factory Settings doc (Single)."""
    try:
        return frappe.get_cached_doc("Factory Settings")
    except Exception:
        # If not installed yet, return a dummy object with attributes returning None
        class _Dummy:
            def __getattr__(self, _):
                return None
        return _Dummy()

def _consume_on_scan() -> bool:
    """Always consume materials immediately on scan (Material Consumption for Manufacture).
    
    This is hardcoded to True. Materials scanned via the Load button are directly
    consumed from source warehouse into the Work Order, not transferred to WIP.
    
    Returns:
        bool: Always True
    """
    return True

def _scan_dup_ttl() -> int:
    fs = _fs()
    val = getattr(fs, "scan_dup_ttl_sec", None)
    return int(val or 45)

def _max_active_ops() -> int:
    fs = _fs()
    val = getattr(fs, "max_active_operators", None)
    return int(val or 2)

def _allowed_groups_global() -> set[str]:
    """
    From Factory Settings -> Allowed Item Groups (Table MultiSelect).
    Child rows expected to have field 'item_group'.
    """
    fs = _fs()
    rows = getattr(fs, "allowed_item_groups", []) or []
    out: set[str] = set()
    for r in rows:
        ig = getattr(r, "item_group", None)
        if ig:
            out.add(str(ig).strip().lower())
    return out

def _packaging_groups_global() -> set[str]:
    """From Factory Settings -> Packaging Item Groups (Table MultiSelect)."""
    fs = _fs()
    rows = getattr(fs, "packaging_item_groups", []) or []
    out: set[str] = set()
    for r in rows:
        ig = getattr(r, "item_group", None)
        if ig:
            out.add(str(ig).strip().lower())
    return out

def _backflush_groups_global() -> set[str]:
    """From Factory Settings -> Backflush Item Groups (Table MultiSelect)."""
    fs = _fs()
    rows = getattr(fs, "backflush_item_groups", []) or []
    out: set[str] = set()
    for r in rows:
        ig = getattr(r, "item_group", None)
        if ig:
            out.add(str(ig).strip().lower())
    return out

def _warehouses_for_line(
    line: Optional[str],
) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    Factory Settings -> Line Warehouse Map child table.
    Child rows expected: line (Workstation), staging_warehouse, wip_warehouse,
    target_warehouse, return_warehouse.
    Returns (staging, wip, target, return_wh).
    """
    if not line:
        return None, None, None, None
    fs = _fs()
    rows = getattr(fs, "line_warehouse_map", []) or []
    for r in rows:
        row_line = (
            getattr(r, "factory_line", None)
            or getattr(r, "workstation", None)
            or ""
        ).strip()
        if row_line.lower() == str(line).strip().lower():
            return (
                getattr(r, "staging_warehouse", None) or None,
                getattr(r, "wip_warehouse", None) or None,
                getattr(r, "target_warehouse", None) or None,
                getattr(r, "return_warehouse", None) or None,
            )
    return None, None, None, None

def _default_line_scrap(work_order: str) -> Optional[str]:
    """Get scrap/reject warehouse for the work order's line."""
    line = _line_for_work_order(work_order)
    if not line:
        return None
    
    fs = _fs()
    rows = getattr(fs, "line_warehouse_map", []) or []
    for r in rows:
        row_line = (
            getattr(r, "factory_line", None)
            or getattr(r, "workstation", None)
            or ""
        ).strip()
        if row_line.lower() == str(line).strip().lower():
            return getattr(r, "scrap_warehouse", None) or None
    
    return None

def _get_consumed_materials_from_load(work_order: str) -> dict:
    """
    Get materials already consumed via LOAD button (Material Consumption for Manufacture entries).
    
    Args:
        work_order: Work Order name
    
    Returns:
        dict: {item_code: total_qty_consumed, ...}
    """
    consumed = frappe.db.sql("""
        SELECT 
            sed.item_code,
            SUM(sed.qty) as total_qty
        FROM `tabStock Entry` se
        JOIN `tabStock Entry Detail` sed ON sed.parent = se.name
        WHERE se.docstatus = 1
            AND se.work_order = %(work_order)s
            AND se.purpose = 'Material Consumption for Manufacture'
            AND sed.s_warehouse IS NOT NULL
            AND sed.is_finished_item = 0
            AND sed.is_scrap_item = 0
        GROUP BY sed.item_code
    """, {"work_order": work_order}, as_dict=True)
    
    return {row.item_code: row.total_qty for row in consumed}


def _consumed_qty_by_batch(wo_list, item_code: str) -> dict:
    """
    Total qty consumed per batch via "Material Consumption for Manufacture"
    Stock Entries for the given work orders and item.

    Counts batches recorded directly on the Stock Entry Detail (sed.batch_no)
    AND batches recorded via a Serial-and-Batch Bundle (ERPNext v15). Each
    detail row is counted exactly once: the direct field is used when set,
    the bundle is used only when the direct field is empty — so rows that
    carry both (use_serial_batch_fields=1) are not double-counted.

    Args:
        wo_list: List of Work Order names
        item_code: Item code

    Returns:
        dict: {batch_no: qty}. Rows with no batch are keyed under "".
    """
    if not wo_list or not item_code:
        return {}

    wo_placeholders = ", ".join(["%s"] * len(wo_list))
    rows = frappe.db.sql(f"""
        SELECT batch_no, COALESCE(SUM(consumed_qty), 0) AS consumed_qty FROM (
            SELECT COALESCE(sed.batch_no, '') AS batch_no, sed.qty AS consumed_qty
            FROM `tabStock Entry` se
            JOIN `tabStock Entry Detail` sed ON sed.parent = se.name
            WHERE se.docstatus = 1
              AND se.work_order IN ({wo_placeholders})
              AND se.purpose = 'Material Consumption for Manufacture'
              AND sed.item_code = %s
              AND sed.is_finished_item = 0
              AND NOT (
                  (sed.batch_no IS NULL OR sed.batch_no = '')
                  AND sed.serial_and_batch_bundle IS NOT NULL
                  AND sed.serial_and_batch_bundle != ''
              )

            UNION ALL

            SELECT sbe.batch_no AS batch_no, ABS(sbe.qty) AS consumed_qty
            FROM `tabStock Entry` se
            JOIN `tabStock Entry Detail` sed ON sed.parent = se.name
            JOIN `tabSerial and Batch Entry` sbe ON sbe.parent = sed.serial_and_batch_bundle
            WHERE se.docstatus = 1
              AND se.work_order IN ({wo_placeholders})
              AND se.purpose = 'Material Consumption for Manufacture'
              AND sed.item_code = %s
              AND sed.is_finished_item = 0
              AND (sed.batch_no IS NULL OR sed.batch_no = '')
              AND sed.serial_and_batch_bundle IS NOT NULL
              AND sed.serial_and_batch_bundle != ''
              AND sbe.batch_no IS NOT NULL AND sbe.batch_no != ''
        ) combined
        GROUP BY batch_no
    """, tuple(wo_list + [item_code] + wo_list + [item_code]), as_dict=True)

    return {row.batch_no: flt(row.consumed_qty) for row in rows}


def _get_total_consumed_cost(work_order: str) -> float:
    """
    Get the total cost of materials already consumed via "Material Consumption for Manufacture"
    Stock Entries for a given Work Order.

    This is used to ensure that when a Manufacture Stock Entry is created after pre-consumption
    via the LOAD button, the finished item's basic_rate reflects all consumed materials costs,
    not just the cost of any remaining materials in the current Manufacture entry.

    Args:
        work_order: Work Order name

    Returns:
        float: Sum of (valuation_rate * qty) for all outgoing items in prior
               "Material Consumption for Manufacture" entries for this WO.
    """
    result = frappe.db.sql("""
        SELECT COALESCE(SUM(sed.amount), 0) AS total_cost
        FROM `tabStock Entry` se
        JOIN `tabStock Entry Detail` sed ON sed.parent = se.name
        WHERE se.docstatus = 1
            AND se.work_order = %(work_order)s
            AND se.purpose = 'Material Consumption for Manufacture'
            AND sed.s_warehouse IS NOT NULL
            AND sed.is_finished_item = 0
            AND sed.is_scrap_item = 0
    """, {"work_order": work_order})
    return flt(result[0][0]) if result else 0.0


def _apply_pre_consumed_cost_to_finished_item(se, work_order: str, finished_qty: float) -> None:
    """
    Set basic_rate and set_basic_rate_manually on the finished item row of a Manufacture
    Stock Entry so that ERPNext includes the cost of materials consumed in prior
    "Material Consumption for Manufacture" entries (via the LOAD button).

    Without this, when all raw materials have already been pre-consumed, ERPNext computes
    a zero outgoing_items_cost for the current entry and assigns a zero basic_rate to the
    finished good, which causes a "Valuation Rate required" error on submit.

    Args:
        se: Stock Entry document (not yet inserted)
        work_order: Work Order name
        finished_qty: Finished good quantity
    """
    pre_consumed_cost = _get_total_consumed_cost(work_order)
    if not (pre_consumed_cost > 0 and finished_qty > 0):
        return

    # Collect outgoing (non-finished) rows once for reuse
    outgoing_rows = [
        row for row in se.items
        if row.get("s_warehouse") and not row.get("is_finished_item")
    ]

    remaining_materials_cost = 0.0
    if outgoing_rows:
        placeholders = ", ".join(
            ["(%s, %s)"] * len(outgoing_rows)
        )
        flat_values = [v for row in outgoing_rows for v in (row.item_code, row.s_warehouse)]
        bin_rates = frappe.db.sql(
            f"""
            SELECT item_code, warehouse, valuation_rate
            FROM `tabBin`
            WHERE (item_code, warehouse) IN ({placeholders})
            """,
            flat_values,
            as_dict=True,
        )
        rate_map = {(r.item_code, r.warehouse): flt(r.valuation_rate) for r in bin_rates}
        remaining_materials_cost = sum(
            rate_map.get((row.item_code, row.s_warehouse), 0.0) * flt(row.qty)
            for row in outgoing_rows
        )

    total_cost = pre_consumed_cost + remaining_materials_cost
    for row in se.items:
        if row.get("is_finished_item"):
            row.basic_rate = total_cost / finished_qty
            row.set_basic_rate_manually = 1
            break


def _get_bom_items_for_quantity(bom_no: str, qty: float) -> list:
    """
    Get BOM items scaled for the production quantity.
    
    Args:
        bom_no: BOM name
        qty: Production quantity
    
    Returns:
        list: [{"item_code": str, "qty": float, "uom": str, ...}, ...]
    """
    from erpnext.manufacturing.doctype.bom.bom import get_bom_items_as_dict
    
    # Get BOM items (exploded if multi-level)
    items_dict = get_bom_items_as_dict(
        bom_no,
        company=frappe.db.get_value("BOM", bom_no, "company"),
        qty=qty,
        fetch_exploded=1,
        fetch_qty_in_stock_uom=True
    )
    
    items = []
    for item_code, item_data in items_dict.items():
        items.append({
            "item_code": item_code,
            "qty": item_data.get("qty", 0),
            "uom": item_data.get("stock_uom", "Nos"),
        })
    
    return items


# ============================================================
# Batch Code Generation - ISNACK System
# ============================================================

def generate_batch_code(date=None, sequence: int = 1) -> str:
    """
    Generate ISNACK batch code in format: YYM-DD# → [Letter][Letter][Letter]-[Number][Number][Number]
    
    PART 1: THE YEAR (Letters 1 & 2)
    Map each digit of last two digits of year: 0=A, 1=B, 2=C, 3=D, 4=E, 5=F, 6=G, 7=H, 8=I, 9=J
    - 2025 → CF, 2026 → CG, 2027 → CH, 2028 → CI, 2029 → CJ, 2030 → DA
    
    PART 2: THE MONTH (Letter 3)
    A=Jan, B=Feb, C=Mar, D=Apr, E=May, F=Jun, G=Jul, H=Aug, I=Sep, J=Oct, K=Nov, L=Dec
    
    PART 3: THE DAY & SEQUENCE (Numbers 4, 5, & 6)
    - Numbers 4 & 5: Calendar day of month, zero-padded (01-31)
    - Number 6: Batch sequence for that day (1-9)
    
    Examples:
    - February 15, 2026 (1st batch) → CGB-151
    - October 31, 2026 (3rd batch) → CGJ-313
    - January 05, 2027 (1st batch) → CHA-051
    
    Args:
        date: Date object or string (defaults to today)
        sequence: Sequence number for the day (1-9)
    
    Returns:
        str: 7-character batch code (3 letters + dash + 3 digits)
    """
    from frappe.utils import getdate
    
    if date is None:
        date = frappe.utils.today()
    
    date_obj = getdate(date)
    
    # Digit to letter mapping
    digit_map = {0: 'A', 1: 'B', 2: 'C', 3: 'D', 4: 'E', 5: 'F', 6: 'G', 7: 'H', 8: 'I', 9: 'J'}
    
    # PART 1: Year - last two digits, each mapped to letter
    year_str = str(date_obj.year)[-2:]  # Get last 2 digits
    year_letter1 = digit_map[int(year_str[0])]
    year_letter2 = digit_map[int(year_str[1])]
    
    # PART 2: Month - A=Jan through L=Dec
    month_letters = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L']
    month_letter = month_letters[date_obj.month - 1]
    
    # PART 3: Day (2 digits) + Sequence (1 digit)
    day_str = f"{date_obj.day:02d}"
    sequence_str = str(sequence)[-1]  # Last digit only
    
    return f"{year_letter1}{year_letter2}{month_letter}-{day_str}{sequence_str}"


def _get_batch_code_prefix(date=None) -> str:
    """
    Generate the 6-character batch code prefix (without sequence number).
    
    Args:
        date: Date object or string (defaults to today)
    
    Returns:
        str: 6-character prefix with dash (e.g., "CGB-15" for Feb 15, 2026)
    """
    from frappe.utils import getdate
    
    if date is None:
        date = frappe.utils.today()
    
    date_obj = getdate(date)
    
    # Digit to letter mapping
    digit_map = {0: 'A', 1: 'B', 2: 'C', 3: 'D', 4: 'E', 5: 'F', 6: 'G', 7: 'H', 8: 'I', 9: 'J'}
    
    # PART 1: Year - last two digits, each mapped to letter
    year_str = str(date_obj.year)[-2:]
    year_letter1 = digit_map[int(year_str[0])]
    year_letter2 = digit_map[int(year_str[1])]
    
    # PART 2: Month - A=Jan through L=Dec
    month_letters = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L']
    month_letter = month_letters[date_obj.month - 1]
    
    # PART 3: Day (2 digits)
    day_str = f"{date_obj.day:02d}"
    
    return f"{year_letter1}{year_letter2}{month_letter}-{day_str}"


def _get_next_batch_sequence(date=None) -> int:
    """
    Get the next batch sequence number for the given date by querying existing batches.
    
    Args:
        date: Date object or string (defaults to today)
    
    Returns:
        int: Next sequence number (1-9)
    """
    from frappe.utils import getdate
    
    if date is None:
        date = frappe.utils.today()
    
    date_obj = getdate(date)
    
    # Generate the 5-character prefix (without sequence)
    prefix = _get_batch_code_prefix(date)
    
    # Query existing batches matching this prefix
    existing_batches = frappe.db.sql("""
        SELECT batch_id
        FROM `tabBatch`
        WHERE batch_id LIKE %(pattern)s
        ORDER BY batch_id DESC
        LIMIT 1
    """, {"pattern": f"{prefix}%"}, as_dict=True)
    
    if not existing_batches:
        return 1
    
    # Extract the sequence number from the last batch
    last_batch = existing_batches[0].batch_id
    if len(last_batch) >= 7:
        try:
            last_sequence = int(last_batch[6])  # 7th character (index 6) - after dash
            return min(last_sequence + 1, 9)  # Cap at 9
        except (ValueError, IndexError):
            return 1
    
    return 1


@frappe.whitelist()
def generate_next_batch_code(date=None) -> str:
    """
    Generate the next available batch code for the given date.
    This is the API endpoint called from the frontend.
    
    Args:
        date: Date string (defaults to today)
    
    Returns:
        str: 6-character batch code with auto-incremented sequence
    """
    sequence = _get_next_batch_sequence(date)
    return generate_batch_code(date, sequence)


def _ensure_batch(item_code: str, batch_no: str) -> str:
    """
    Create or get existing Batch for the given item/batch_no.

    Batch.name is globally unique (name == batch_id), so we first check
    existence by name. If the batch exists but belongs to a different item,
    raise a clear validation error instead of letting the DB throw a duplicate-key error.
    
    Args:
        item_code: Item code
        batch_no: Batch number/ID
    
    Returns:
        str: Batch name
    """
    # Process spaces in batch number according to settings
    batch_no = _process_batch_spaces(batch_no)

    if frappe.db.exists("Batch", batch_no):
        existing_item = frappe.db.get_value("Batch", batch_no, "item")
        if existing_item != item_code:
            frappe.throw(
                _("Batch {0} already exists for item {1}. Please use a different batch ID for {2}.")
                .format(batch_no, existing_item, item_code)
            )
        return batch_no
    
    batch = frappe.get_doc({
        "doctype": "Batch",
        "item": item_code,
        "batch_id": batch_no,
    })
    batch.insert()
    return batch.name


def _validate_batch_code_format(batch_no: str) -> bool:
    """
    Validate that batch code matches ISNACK format: 3 letters + dash + 3 digits.
    
    Args:
        batch_no: Batch code to validate
    
    Returns:
        bool: True if valid format
    
    Raises:
        frappe.ValidationError: If format is invalid
    """
    import re
    
    if not batch_no:
        frappe.throw(_("Batch number is required"))
    
    # Pattern: 3 uppercase letters A-Z followed by dash and 3 digits
    pattern = r'^[A-Za-z]{3}-\d{3}$'
    
    if not re.match(pattern, batch_no.upper()):
        frappe.throw(_(
            "Invalid batch code format. Expected format: 3 letters + dash + 3 digits. "
            "Example: CGB-151"
        ))
    
    return True


# ============================================================
# Generic helpers
# ============================================================

ROLES_OPERATOR = ["Factory Operator", "Operator", "Production Manager"]

# Tolerance for floating point quantity comparisons
QTY_EPSILON = 0.0001

def _is_fg(item_code: str) -> bool:
    """Treat sales items as FG by policy (adjust to Item Group if you prefer)."""
    return bool(frappe.db.get_value("Item", item_code, "is_sales_item"))

def _get_item_group(item_code: str) -> Optional[str]:
    return frappe.db.get_value("Item", item_code, "item_group")

def _get_user_line(user: str) -> Optional[str]:
    line = (
        frappe.defaults.get_user_default("factory_line")
        or frappe.defaults.get_user_default("manufacturing_line")
    )
    return line or None

def _user_employee(user: str) -> Optional[str]:
    """Return the active Employee linked to a user, or None."""
    if not user or user == "Guest":
        return None
    emp = frappe.db.get_value(
        "Employee", {"user_id": user, "status": "Active"}, "name"
    )
    if emp:
        return emp
    fallback = frappe.db.get_value("User", user, "employee")
    if fallback and frappe.db.get_value("Employee", fallback, "status") == "Active":
        return fallback
    return None

def _employee_by_badge(badge: str) -> Optional[str]:
    if not badge:
        return None
    meta = frappe.get_meta("Employee")
    for fname in ("badge_code", "attendance_device_id", "employee_number", "barcode"):
        if meta.has_field(fname):
            emp = frappe.db.get_value("Employee", {fname: badge}, "name")
            if emp:
                return emp
    return None

def _employee_or_user_default(employee: Optional[str]) -> Optional[str]:
    """Resolve the operator for an Operator Hub action.

    When the logged-in user is linked to an active Employee, that Employee
    is authoritative: any conflicting client-supplied value is rejected.
    This enforces the locked-operator rule server-side, so it does not rely
    on the read-only behaviour of the front-end alone.
    """
    linked = _user_employee(frappe.session.user)
    if linked:
        if employee and employee != linked:
            frappe.throw(
                _("Your account is linked to Employee {0}; you cannot act as another operator.").format(linked)
            )
        return linked
    return employee or None

def _line_for_work_order(work_order: str) -> Optional[str]:
    """Prefer WO.factory_line/custom_factory_line, then BOM default, then first operation/workstation."""
    if not work_order:
        return None

    info = frappe.db.get_value(
        "Work Order",
        work_order,
        ["custom_factory_line", "bom_no"],
        as_dict=True,
    ) or {}
    line = (info.get("custom_factory_line") or "").strip() or None

    if not line and info.get("bom_no"):
        line = frappe.db.get_value("BOM", info["bom_no"], "custom_default_factory_line")

    if line:
        return line

    # Legacy fallback: first operation workstation or Job Card workstation
    op_line = frappe.db.get_value("Work Order Operation", {"parent": work_order}, "workstation")
    return op_line or frappe.db.get_value("Job Card", {"work_order": work_order}, "workstation")

def _default_line_staging(work_order: str, *, is_packaging: bool = False) -> Optional[str]:
    line = _line_for_work_order(work_order)
    staging, _wip, _target, _return_wh = _warehouses_for_line(line)
    return staging or frappe.db.get_single_value("Stock Settings", "default_warehouse")

def _default_line_wip(work_order: str) -> Optional[str]:
    line = _line_for_work_order(work_order)
    _staging, wip, _target, _return_wh = _warehouses_for_line(line)
    return wip or frappe.db.get_single_value("Stock Settings", "default_warehouse")

def _default_line_target(work_order: str) -> Optional[str]:
    """Default FG/SFG output warehouse for a WO based on its line."""
    line = _line_for_work_order(work_order)
    _staging, _wip, target, _return_wh = _warehouses_for_line(line)
    return target or None

def _default_sfg_source(work_order: str) -> Optional[str]:
    """
    Default source warehouse for semi-finished (slurry / rice mix) consumption.
    Order:
      1) Factory Settings.default_semi_finished_warehouse
      2) Warehouse named 'Semi-finished - ISN' if it exists
      3) Stock Settings default warehouse
    """
    fs = _fs()
    wh = getattr(fs, "default_semi_finished_warehouse", None)
    if wh:
        return wh
    try:
        if frappe.db.exists("Warehouse", "Semi-finished - ISN"):
            return "Semi-finished - ISN"
    except Exception:
        # Fallback to default warehouse
        pass
    return frappe.db.get_single_value("Stock Settings", "default_warehouse")

@frappe.whitelist()
def get_staging_items_for_wo(doctype, txt, searchfield, start, page_len, filters):
    """Return items from the WO's BOM that have stock in the WIP warehouse.

    This is used by the Manual Load dialog item picker. Manual Load is intended
    to be used after the operator clicks Start, which runs transfer_staged_to_wip
    and moves all materials from the Staging warehouse into the WIP warehouse.
    We therefore query the WIP warehouse so the picker is populated post-Start.
    """
    if isinstance(filters, str):
        filters = json.loads(filters)
    work_order = filters.get("work_order") if isinstance(filters, dict) else None
    if not work_order:
        return []

    line = _line_for_work_order(work_order)
    _staging_wh, wip_wh, _target, _return_wh = _warehouses_for_line(line)
    if not wip_wh:
        return []

    bom_no = frappe.db.get_value("Work Order", work_order, "bom_no")
    if not bom_no:
        return []

    params = {
        "wip_wh": wip_wh,
        "bom_no": bom_no,
        "txt": "%{}%".format(txt),
        "start": int(start),
        "page_len": int(page_len),
    }

    # Optionally include packaging items (by item group) in addition to BOM items
    # when Factory Settings allows packaging consumption at material loading.
    packaging_union = ""
    if getattr(_fs(), "allow_packaging_at_material_loading", 0):
        packaging_groups = _packaging_groups_global()
        if packaging_groups:
            params["packaging_groups"] = tuple(packaging_groups)
            packaging_union = """
                UNION
                SELECT DISTINCT i.name AS item_code, i.item_name
                FROM `tabItem` i
                JOIN `tabBin` bin ON bin.item_code = i.name
                    AND bin.warehouse = %(wip_wh)s
                    AND bin.actual_qty > 0
                WHERE LOWER(i.item_group) IN %(packaging_groups)s
                    AND (i.name LIKE %(txt)s OR i.item_name LIKE %(txt)s)
            """

    return frappe.db.sql(f"""
        SELECT DISTINCT bi.item_code, bi.item_name
        FROM `tabBOM Item` bi
        JOIN `tabBin` bin ON bin.item_code = bi.item_code
            AND bin.warehouse = %(wip_wh)s
            AND bin.actual_qty > 0
        WHERE bi.parent = %(bom_no)s
            AND (bi.item_code LIKE %(txt)s OR bi.item_name LIKE %(txt)s)
        {packaging_union}
        ORDER BY item_code
        LIMIT %(page_len)s OFFSET %(start)s
    """, params)

def _validate_item_in_bom(work_order: str, item_code: str) -> Tuple[bool, str]:
    bom = frappe.db.get_value("Work Order", work_order, "bom_no")
    if not bom:
        return False, _("Work Order has no BOM")
    exists = frappe.db.exists("BOM Item", {"parent": bom, "item_code": item_code})
    if not exists:
        return False, _("Item {0} not in BOM {1}").format(item_code, bom)
    return True, "OK"

def _parse_gs1_or_basic(code: str) -> dict:
    out: dict = {}
    s = code or ""
    if s.startswith(("]d2", "]C1", "]Q3")):
        s = s[3:]

    def grab(ai, ln=None):
        idx = s.find(ai)
        if idx < 0:
            return None
        val = s[idx + len(ai):]
        if ln:
            return val[:ln]
        end = val.find("(")
        return val if end < 0 else val[:end]

    gtin = grab("(01)", 14)
    if gtin: out["gtin"] = gtin
    batch = grab("(10)")
    if batch: out["batch_no"] = _process_batch_spaces(batch)
    exp = grab("(17)", 6)
    if exp: out["expiry"] = exp
    qty = grab("(30)") or grab("(37)")
    if qty:
        try: out["qty"] = float(qty)
        except Exception: pass

    if "gtin" in out:
        item = frappe.db.get_value("Item Barcode", {"barcode": out["gtin"]}, "parent")
        if item: out["item_code"] = item

    if "item_code" not in out:
        parts = s.split("|")
        if len(parts) >= 1: out["item_code"] = parts[0]
        if len(parts) >= 2: out["batch_no"] = _process_batch_spaces(parts[1])
        if len(parts) >= 3:
            try: out["qty"] = float(parts[2])
            except Exception: pass
    return out

def _scan_cache_key(work_order: str, raw_code: str) -> str:
    h = hashlib.sha1((work_order + "|" + raw_code).encode("utf-8")).hexdigest()
    return f"isnack:mes:scan:{work_order}:{h}"

def _has_recent_duplicate(work_order: str, raw_code: str, ttl_sec: Optional[int] = None) -> bool:
    key = _scan_cache_key(work_order, raw_code)
    cache = frappe.cache()
    if cache.get_value(key):
        return True
    cache.set_value(key, "1", expires_in_sec=ttl_sec or _scan_dup_ttl())
    return False

def _scan_already_consumed(work_order: str, raw_code: str) -> bool:
    """Pure check — unlike _has_recent_duplicate it does NOT set the cache key.

    Used by the confirm-then-post scan flow so a cancelled or failed
    confirmation never blocks the operator from re-scanning the same label.
    """
    if not raw_code:
        return False
    return bool(frappe.cache().get_value(_scan_cache_key(work_order, raw_code)))

def _mark_scan_consumed(work_order: str, raw_code: str, ttl_sec: Optional[int] = None) -> None:
    """Record that a raw scan was consumed, so a quick re-scan is rejected."""
    if not raw_code:
        return
    frappe.cache().set_value(
        _scan_cache_key(work_order, raw_code), "1",
        expires_in_sec=ttl_sec or _scan_dup_ttl(),
    )

def _require_roles(roles: list[str]):
    if frappe.session.user == "Guest":
        frappe.throw(_("Login required"))
    user_roles = set(frappe.get_roles(frappe.session.user))
    if not (set(roles) & user_roles):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

# ============================================================
# Job Card (line-centric) helpers
# ============================================================

def _open_time_logs(job_card: str) -> list[dict]:
    rows = frappe.db.sql("""
        select name, employee
        from `tabJob Card Time Log`
        where parent=%s and (to_time is null or to_time='')
    """, (job_card,), as_dict=True)
    return rows

def _open_log_count(job_card: str) -> int:
    return frappe.db.sql(
        "select count(*) from `tabJob Card Time Log` where parent=%s and (to_time is null or to_time='')",
        (job_card,),
    )[0][0]

def _job_card_info(name: str) -> dict:
    jc = frappe.get_doc("Job Card", name)
    wo = frappe.get_doc("Work Order", jc.work_order) if jc.work_order else None
    return {
        "name": jc.name,
        "status": jc.status,
        "operation": jc.operation,
        "workstation": jc.workstation,
        "for_quantity": jc.for_quantity,
        "work_order": jc.work_order,
        "production_item": wo.production_item if wo else None,
        "item_name": wo.item_name if wo else None,
        "wo_status": wo.status if wo else None,
        "open_logs": _open_time_logs(jc.name),
    }

# ============================================================
# Legacy WO-centric endpoints (kept for compatibility)
# ============================================================

@frappe.whitelist()
def get_assigned_work_orders():
    user = frappe.session.user
    line = _get_user_line(user)

    filters = {"docstatus": 1, "status": ["in", ["Not Started", "In Process", "Stopped"]]}
    if line:
        meta = frappe.get_meta("Work Order")
        if meta.has_field("custom_line"):
            filters["custom_line"] = line

    rows = frappe.get_all(
        "Work Order",
        filters=filters,
        fields=["name", "production_item", "item_name", "qty", "status"],
        order_by="modified desc",
        limit=200,
    )
    for r in rows:
        r["type"] = "FG" if _is_fg(r["production_item"]) else "SF"
    return rows

@frappe.whitelist()
def is_finished_good(work_order):
    item = frappe.db.get_value("Work Order", work_order, "production_item")
    return _is_fg(item) if item else False

@frappe.whitelist()
def get_wo_banner(work_order):
    wo = frappe.get_doc("Work Order", work_order)
    actual = frappe.db.sql(
        """
        select coalesce(sum(sed.qty),0)
        from `tabStock Entry` se
        join `tabStock Entry Detail` sed on sed.parent = se.name
        where se.docstatus=1 and se.work_order=%s and se.purpose='Manufacture'
        """,
        work_order,
    )[0][0] or 0

    rejects = wo.get("custom_rejects_qty") or 0
    is_fg = _is_fg(wo.production_item)
    type_chip = "FG" if is_fg else "SF"
    batch = wo.get("batch_no") or "-"
    line = _line_for_work_order(work_order) or "-"
    ended = bool(wo.get("custom_production_ended"))
    ended_badge = (
        ' <span class="badge bg-dark ms-2">Production Ended</span>' if ended else ""
    )
    ended_note = (
        '<div class="small" style="color:#92400e;">'
        '<b>Production ended</b> — awaiting Close Production. '
        'No further material loading allowed.'
        "</div>"
        if ended
        else ""
    )

    html = f"""
      <div class="d-flex flex-wrap justify-content-between">
        <div><b>{frappe.utils.escape_html(wo.name)}</b> — {frappe.utils.escape_html(wo.item_name)}</div>
        <div><span class="badge {'bg-primary' if is_fg else 'bg-secondary'}">{type_chip}</span>{ended_badge}</div>
      </div>
      <div>Batch: {frappe.utils.escape_html(batch)}</div>
      <div>Target: {wo.qty} &nbsp; Actual: {actual} &nbsp; Rejects: {rejects} &nbsp; Status: {frappe.utils.escape_html(wo.status)}</div>
      <div class="small text-muted">Line: {frappe.utils.escape_html(line)} · Operator: {frappe.utils.escape_html(frappe.session.user)}</div>
      {ended_note}
    """
    return {"html": html}

# ============================================================
# Kiosk helper
# ============================================================

@frappe.whitelist()
def get_operator_context():
    """Operator binding for the current user.

    When the logged-in user is linked to an active Employee, the Operator
    Hub auto-selects that Employee and locks the Operator field. The same
    binding is enforced server-side in `_employee_or_user_default`, so this
    endpoint only drives the UI convenience.
    """
    emp = _user_employee(frappe.session.user)
    if not emp:
        return {"locked": False, "employee": None, "employee_name": None}
    return {
        "locked": True,
        "employee": emp,
        "employee_name": frappe.db.get_value("Employee", emp, "employee_name") or emp,
    }


@frappe.whitelist()
def resolve_employee(badge: Optional[str] = None, employee: Optional[str] = None):
    emp = None
    if employee:
        emp = employee
    elif badge:
        emp = _employee_by_badge(badge)
    if not emp:
        return {"ok": False}
    linked = _user_employee(frappe.session.user)
    if linked and emp != linked:
        frappe.throw(
            _("Your account is linked to Employee {0}; you cannot select another operator.").format(linked)
        )
    return {
        "ok": True,
        "employee": emp,
        "employee_name": frappe.db.get_value("Employee", emp, "employee_name") or emp,
    }

# ============================================================
# Line queue + banner (Factory Section / Work Order centric)
# ============================================================

@frappe.whitelist()
def get_line_queue(line: Optional[str] = None, lines: Optional[str] = None):
    """Return Work Orders for one or more lines (Factory Sections)."""
    # Parse lines parameter (JSON array from frontend)
    selected_lines = []
    if lines:
        try:
            selected_lines = json.loads(lines) if isinstance(lines, str) else lines
        except (json.JSONDecodeError, ValueError) as e:
            frappe.throw(_("Invalid lines parameter: {0}").format(str(e)))
    elif line:
        selected_lines = [line]
    
    if not selected_lines:
        user_line = _get_user_line(frappe.session.user)
        if user_line:
            selected_lines = [user_line]

    filters: dict = {
        "docstatus": 1,
        "status": ["in", ["Not Started", "In Process", "Stopped"]],
    }
    
    if selected_lines:
        meta = frappe.get_meta("Work Order")
        if meta.has_field("custom_factory_line"):
            filters["custom_factory_line"] = ["in", selected_lines]

    wos = frappe.get_all(
        "Work Order",
        filters=filters,
        fields=[
            "name",
            "production_item",
            "item_name",
            "qty",
            "status",
            "custom_factory_line",
            "custom_production_ended",
            "planned_start_date",
            "creation",
        ],
        order_by="coalesce(planned_start_date, creation) asc",
        limit=300,
    )

    out = []
    for wo in wos:
        wo_line = wo.get("custom_factory_line") or _line_for_work_order(wo.name)
        out.append(
            {
                "name": wo.name,
                "work_order": wo.name,
                "line": wo_line,
                "for_quantity": wo.qty,
                "status": wo.status,
                "stage_status": _storekeeper_stage_status(wo.name),
                "production_item": wo.production_item,
                "item_name": wo.item_name,
                "type": "FG" if _is_fg(wo.production_item) else "SF",
                "custom_production_ended": wo.get("custom_production_ended", 0),
                "planned_start_date": wo.get("planned_start_date"),
            }
        )
    return out

@frappe.whitelist()
def get_card_banner(job_card: Optional[str] = None, work_order: Optional[str] = None):
    """Compatibility wrapper: returns the Work Order banner."""
    if not work_order and job_card:
        work_order = frappe.db.get_value("Job Card", job_card, "work_order")
    if not work_order:
        frappe.throw(_("Missing Work Order"))
    return get_wo_banner(work_order)

# ============================================================
# Job control (Start / Pause / Stop) — employee-specific logs
# ============================================================

@frappe.whitelist()
def claim_job_card(job_card: str, employee: Optional[str] = None):
    _require_roles(ROLES_OPERATOR)

    emp = _employee_or_user_default(employee)
    if not emp:
        frappe.throw(_("No Employee specified and no Employee linked to user"))

    jc = frappe.get_doc("Job Card", job_card)
    open_logs = _open_time_logs(job_card)

    if any(r["employee"] == emp for r in open_logs):
        frappe.throw(_("You already joined this job"))

    if len(open_logs) >= _max_active_ops():
        frappe.throw(_("This job already has {0} active operators").format(_max_active_ops()))

    jc.append("time_logs", {"employee": emp, "from_time": frappe.utils.now_datetime()})
    if jc.status == "Open":
        jc.status = "Work In Progress"
    jc.flags.ignore_permissions = True
    jc.save()

    if _open_log_count(job_card) > _max_active_ops():
        last = frappe.db.get_value(
            "Job Card Time Log",
            {"parent": job_card, "employee": emp},
            "name",
            order_by="creation desc",
        )
        if last:
            frappe.delete_doc("Job Card Time Log", last, ignore_permissions=True)
        frappe.throw(_("Too many active operators on this job, please try again."))
    return True

@frappe.whitelist()
def leave_job_card(job_card: str, employee: Optional[str] = None):
    _require_roles(ROLES_OPERATOR)

    emp = _employee_or_user_default(employee)
    if not emp:
        frappe.throw(_("No Employee specified and no Employee linked to user"))

    name = frappe.db.get_value(
        "Job Card Time Log",
        {"parent": job_card, "employee": emp, "to_time": ["in", ("", None)]},
        "name",
    )
    if not name:
        frappe.throw(_("This employee is not on this job"))

    tl = frappe.get_doc("Job Card Time Log", name)
    tl.to_time = frappe.utils.now_datetime()
    tl.flags.ignore_permissions = True
    tl.save()

    if not _open_time_logs(job_card):
        try:
            frappe.db.set_value("Job Card", job_card, "status", "On Hold", update_modified=False)
        except Exception:
            pass
    return True

@frappe.whitelist()
def set_card_status(
    job_card: str,
    action: str,
    reason: Optional[str] = None,
    remarks: Optional[str] = None,
    employee: Optional[str] = None,
):
    _require_roles(["Factory Operator", "Production Manager"])
    jc = frappe.get_doc("Job Card", job_card)
    now = frappe.utils.now_datetime()
    emp = _employee_or_user_default(employee)
    action = (action or "").strip()

    if action == "Start":
        if emp:
            open_for_emp = frappe.db.exists(
                "Job Card Time Log",
                {"parent": job_card, "employee": emp, "to_time": ["in", ("", None)]},
            )
            if not open_for_emp:
                if _open_log_count(job_card) >= _max_active_ops():
                    frappe.throw(_("This job already has {0} active operators").format(_max_active_ops()))
                jc.append("time_logs", {"employee": emp, "from_time": now})
        else:
            if not _open_time_logs(job_card):
                jc.append("time_logs", {"from_time": now})
        jc.status = "Work In Progress"

    elif action in ("Pause", "Stop"):
        if emp:
            name = frappe.db.get_value(
                "Job Card Time Log",
                {"parent": job_card, "employee": emp, "to_time": ["in", ("", None)]},
                "name",
            )
            if name:
                frappe.db.set_value("Job Card Time Log", name, "to_time", now, update_modified=False)
        else:
            for r in _open_time_logs(job_card):
                frappe.db.set_value("Job Card Time Log", r["name"], "to_time", now, update_modified=False)
        jc.status = "On Hold"

    else:
        frappe.throw(_("Unknown action"))

    if remarks:
        try:
            jc.db_set("mes_remarks", remarks, commit=False)
        except Exception:
            pass
    if reason:
        try:
            jc.db_set("mes_reason", reason, commit=False)
        except Exception:
            pass

    jc.flags.ignore_permissions = True
    jc.save()
    return True

@frappe.whitelist()
def set_work_order_state(
    work_order: str,
    action: str,
    reason: Optional[str] = None,
    remarks: Optional[str] = None,
):
    """Start / Pause / Stop a Work Order directly (Factory Section execution)."""
    _require_roles(ROLES_OPERATOR)
    wo = frappe.get_doc("Work Order", work_order)

    now = frappe.utils.now_datetime()
    action_lc = (action or "").strip().lower()
    # Block any state change that resumes production after End WO.
    if action_lc in ("start", "resume", "reopen"):
        _assert_not_ended(work_order)
    updates: dict = {}
    stage_status = _storekeeper_stage_status(work_order)
    if stage_status != "Staged" and action_lc in ("start", "pause", "stop", "resume", "reopen"):
        frappe.throw(_("Work Order must be fully allocated before this action."))

    if action_lc == "start":
        updates["status"] = "In Process"
        if not wo.actual_start_date:
            updates["actual_start_date"] = now
        
        # NEW: Transfer staged materials to WIP
        try:
            transfer_result = transfer_staged_to_wip(work_order)
            if transfer_result.get("stock_entry"):
                frappe.msgprint(_("Materials transferred from Staging to WIP: {0}").format(
                    transfer_result["stock_entry"]
                ))
            surplus_transfers = transfer_result.get("surplus_transfers") or []
            if surplus_transfers:
                frappe.msgprint(_("Surplus transferred from Staging to WIP: {0}").format(
                    ", ".join(surplus_transfers)
                ))
        except Exception as e:
            # Log the error but don't block the Start action
            frappe.log_error(
                title="Transfer Staged To WIP Error",
                message=f"Failed to transfer staged materials for {work_order}: {str(e)}",
            )
            frappe.msgprint(_("Warning: Could not transfer staged materials. Error: {0}").format(str(e)), 
                          indicator="orange")
    elif action_lc == "pause":
        updates["status"] = "Stopped"
    elif action_lc == "stop":
        updates["status"] = "Stopped"
        if not wo.actual_end_date:
            updates["actual_end_date"] = now
    elif action_lc == "resume" or action_lc == "reopen":
        updates["status"] = "In Process"
    else:
        frappe.throw(_("Unknown action"))

    if reason:
        updates["mes_reason"] = reason
    if remarks:
        updates["mes_remarks"] = remarks

    if updates:
        frappe.db.set_value("Work Order", work_order, updates)

    wo.add_comment(
        "Info",
        _("Work Order control update: {0}").format(
            {"action": action, "reason": reason, "remarks": remarks, "by": frappe.session.user}
        ),
    )
    return True


@frappe.whitelist()
def transfer_staged_to_wip(work_order: str, employee: Optional[str] = None):
    """Transfer materials from Staging to WIP when operator clicks Start.
    
    This creates a 'Material Transfer for Manufacture' which:
    1. Moves materials from Staging → WIP warehouse
    2. Updates material_transferred_for_manufacturing on Work Order
    3. Changes Work Order status to 'In Process' (if not already)
    
    Important: This function preserves individual Stock Entry Detail rows from staging
    (no aggregation) to maintain serial_and_batch_bundle integrity. Each bundle
    represents a specific batch allocation that must be transferred as-is to WIP.
    """
    _require_roles(ROLES_OPERATOR)
    
    wo = frappe.get_doc("Work Order", work_order)
    staging_wh = _default_line_staging(work_order)
    wip_wh = _default_line_wip(work_order)
    
    if not staging_wh:
        frappe.throw(_("No Staging warehouse configured for this Work Order"))
    if not wip_wh:
        frappe.throw(_("No WIP warehouse configured for this Work Order"))
    
    # Get materials currently in staging for this WO
    # Look for recent "Material Transfer" stock entries to this staging warehouse
    # Note: work_order parameter is validated by frappe.get_doc() above, ensuring it's a valid Work Order name
    # Using a more precise pattern match to avoid matching partial work order names
    #
    # IMPORTANT: Preserve each bundle as separate row (no aggregation) to maintain batch allocation integrity
    #   - Fetch batch_no from staging transfer
    #   - Let ERPNext create NEW serial_and_batch_bundle records (don't reuse existing ones)
    #   - Each Stock Entry needs its own unique bundle, even if referencing the same batch
    #   - ORDER BY preserves chronological order and row sequence from staging transfers
    wo_escaped = frappe.db.escape(work_order)
    items_in_staging = frappe.db.sql("""
        SELECT 
            sed.item_code,
            sed.batch_no,
            sed.uom,
            sed.qty
        FROM `tabStock Entry` se
        JOIN `tabStock Entry Detail` sed ON sed.parent = se.name
        WHERE se.docstatus = 1
            AND se.purpose = 'Material Transfer'
            AND sed.t_warehouse = %(staging_wh)s
            AND (se.remarks LIKE %(wo_pattern1)s OR se.remarks LIKE %(wo_pattern2)s)
            AND sed.qty > 0
        ORDER BY se.posting_date, se.posting_time, sed.idx
    """, {
        'staging_wh': staging_wh,
        'wo_pattern1': f'%WO: {work_order}|%',
        'wo_pattern2': f'%WO: {work_order}'
    }, as_dict=True)
    
    se_name = None
    if items_in_staging:
        # Create Material Transfer for Manufacture
        se = frappe.new_doc("Stock Entry")
        se.company = wo.company
        se.purpose = "Material Transfer for Manufacture"
        se.stock_entry_type = "Material Transfer for Manufacture"
        se.work_order = work_order
        se.from_warehouse = staging_wh
        se.to_warehouse = wip_wh
        se.from_bom = 1
        se.bom_no = wo.bom_no
        se.use_multi_level_bom = wo.use_multi_level_bom

        # Set fg_completed_qty for ERPNext to update material_transferred_for_manufacturing
        remaining_qty = flt(wo.qty) - flt(wo.material_transferred_for_manufacturing)
        if remaining_qty <= 0:
            frappe.msgprint(_("Warning: Material already transferred for full quantity. Proceeding with transfer."),
                           indicator="orange")
            se.fg_completed_qty = 0
        else:
            se.fg_completed_qty = remaining_qty

        if employee:
            se.custom_operator = employee  # If you have this custom field

        # Add items from staging
        for item in items_in_staging:
            item_dict = {
                "item_code": item.item_code,
                "qty": item.qty,
                "uom": item.uom,
                "s_warehouse": staging_wh,
                "t_warehouse": wip_wh,
            }

            # Handle batch tracking: Use batch_no and let ERPNext create new bundles
            # Don't reuse serial_and_batch_bundle as it's already linked to the staging transfer
            # Each Stock Entry needs its own unique bundle, even if referencing the same batch
            if item.batch_no:
                # Use batch_no and let ERPNext create a new bundle
                item_dict["batch_no"] = item.batch_no
                # use_serial_batch_fields=1 tells ERPNext to create a new bundle from batch_no
                item_dict["use_serial_batch_fields"] = 1
            # else: No batch tracking - ERPNext will handle as a regular item without batch/serial

            se.append("items", item_dict)

        se.flags.ignore_permissions = True
        se.insert()
        se.submit()
        se_name = se.name

    # Sweep any eligible surplus (from a Consolidated Pick Cart) into WIP too, so
    # operators can consume it during production close. This runs even when there
    # are no normal staged materials left for this WO.
    surplus_transfers = _sweep_surplus_to_wip(work_order, staging_wh, wip_wh, wo, employee)

    if not se_name and not surplus_transfers:
        return {"ok": True, "msg": _("No staged materials found to transfer to WIP"),
                "stock_entry": None, "surplus_transfers": []}

    msg = _("Transferred materials from Staging to WIP") if se_name else _("Transferred surplus from Staging to WIP")
    return {"ok": True, "msg": msg, "stock_entry": se_name, "surplus_transfers": surplus_transfers}


def _find_eligible_surplus_ses(work_order: str, staging_wh: str) -> list[str]:
    """Surplus Stock Entries eligible to be swept to WIP for this Work Order.

    Eligible = submitted, marked surplus, not yet swept, sitting in this WO's
    staging warehouse, AND this WO is one of its originating WOs. Membership is
    read from the new ``custom_originating_work_orders`` child table; when that
    table is empty (legacy surplus records) we fall back to the single
    ``custom_originating_work_order`` field.

    The ``to_warehouse = staging_wh`` condition is what keeps sweeping safe across
    multiple production lines: a WO never sweeps surplus that physically lives in
    another line's staging warehouse.
    """
    if not staging_wh:
        return []
    rows = frappe.db.sql("""
        select se.name
        from `tabStock Entry` se
        where se.docstatus = 1
          and coalesce(se.custom_is_surplus, 0) = 1
          and coalesce(se.custom_surplus_swept_to_wip, 0) = 0
          and se.to_warehouse = %(staging_wh)s
          and (
              exists (
                  select 1 from `tabSurplus Originating Work Order` sowo
                  where sowo.parent = se.name
                    and sowo.parenttype = 'Stock Entry'
                    and sowo.work_order = %(work_order)s
              )
              or (
                  not exists (
                      select 1 from `tabSurplus Originating Work Order` sowo2
                      where sowo2.parent = se.name
                        and sowo2.parenttype = 'Stock Entry'
                  )
                  and se.custom_originating_work_order = %(work_order)s
              )
          )
    """, {"work_order": work_order, "staging_wh": staging_wh}, as_dict=True)
    return [r["name"] for r in rows]


def _claim_surplus_for_sweep(se_name: str, work_order: str) -> bool:
    """Atomically claim a surplus SE so it is swept to WIP exactly once.

    Uses a conditional UPDATE (``... where custom_surplus_swept_to_wip = 0``) and
    checks the affected row count. Because the UPDATE locks the row until the
    transaction commits, a concurrent second Work Order start blocks, then sees
    the flag already set and claims zero rows — guaranteeing idempotency even if
    two originating WOs start at the same time. Returns True only for the caller
    that won the claim.
    """
    frappe.db.sql(
        """
        update `tabStock Entry`
        set custom_surplus_swept_to_wip = 1,
            custom_surplus_swept_by_work_order = %(wo)s,
            custom_surplus_swept_at = %(now)s
        where name = %(name)s
          and coalesce(custom_surplus_swept_to_wip, 0) = 0
        """,
        {"name": se_name, "wo": work_order, "now": frappe.utils.now_datetime()},
    )
    return cint(frappe.db._cursor.rowcount) == 1


def _create_surplus_wip_transfer(
    se_name: str,
    work_order: str,
    staging_wh: str,
    wip_wh: str,
    company: str,
    employee: Optional[str] = None,
) -> Optional[str]:
    """Move a claimed surplus Stock Entry's contents from staging to WIP.

    A plain "Material Transfer" (NOT "Material Transfer for Manufacture") is used:
    surplus is intentionally beyond the WO's theoretical BOM requirement, so a
    Manufacture transfer would trip ERPNext v15's over-transfer validation
    (transferred qty vs. required-for-manufacture). A plain Material Transfer
    between two warehouses carries no BOM/required-qty checks, which is exactly
    what we want — the surplus simply becomes available in WIP for over-
    consumption at production close.
    """
    rows = frappe.db.sql(
        """
        select sed.item_code, sed.batch_no, sed.uom, sed.qty
        from `tabStock Entry Detail` sed
        where sed.parent = %(name)s
          and sed.t_warehouse = %(staging_wh)s
          and sed.qty > 0
        order by sed.idx
        """,
        {"name": se_name, "staging_wh": staging_wh},
        as_dict=True,
    )
    if not rows:
        return None

    se = frappe.new_doc("Stock Entry")
    se.company = company
    se.purpose = "Material Transfer"
    se.stock_entry_type = "Material Transfer"
    se.from_warehouse = staging_wh
    se.to_warehouse = wip_wh
    se.remarks = f"Surplus swept to WIP for WO: {work_order} (from {se_name})"
    if employee:
        se.custom_operator = employee

    for item in rows:
        item_dict = {
            "item_code": item.item_code,
            "qty": item.qty,
            "uom": item.uom,
            "s_warehouse": staging_wh,
            "t_warehouse": wip_wh,
        }
        if item.batch_no:
            item_dict["batch_no"] = item.batch_no
            item_dict["use_serial_batch_fields"] = 1
        se.append("items", item_dict)

    se.flags.ignore_permissions = True
    se.insert()
    se.submit()
    return se.name


def _sweep_surplus_to_wip(
    work_order: str,
    staging_wh: str,
    wip_wh: str,
    wo,
    employee: Optional[str] = None,
) -> list[str]:
    """Find, claim and move eligible surplus from staging to WIP for this WO.

    Idempotent: each surplus SE is claimed atomically before being moved, so a
    later start of another originating WO will not move it again. A failure on one
    surplus SE rolls back only its own claim and is logged; it does not block the
    remaining surplus or the Work Order start.
    """
    if not staging_wh or not wip_wh:
        return []

    created: list[str] = []
    for se_name in _find_eligible_surplus_ses(work_order, staging_wh):
        if not _claim_surplus_for_sweep(se_name, work_order):
            # Another originating WO already swept this surplus.
            continue
        try:
            new_name = _create_surplus_wip_transfer(
                se_name, work_order, staging_wh, wip_wh, wo.company, employee
            )
            if new_name:
                frappe.db.set_value(
                    "Stock Entry", se_name, "custom_surplus_wip_transfer", new_name,
                    update_modified=False,
                )
                created.append(new_name)
        except Exception as exc:
            # Roll back the claim so the surplus can be retried on a later start.
            frappe.db.set_value(
                "Stock Entry",
                se_name,
                {
                    "custom_surplus_swept_to_wip": 0,
                    "custom_surplus_swept_by_work_order": None,
                    "custom_surplus_swept_at": None,
                },
                update_modified=False,
            )
            frappe.log_error(
                title="Sweep Surplus To WIP Error",
                message=f"Failed to sweep surplus {se_name} for {work_order}: {exc}",
            )
    return created


# ============================================================
# New: Semi-finished (SFG) helpers
# ============================================================

@frappe.whitelist()
def get_sfg_components_for_wo(work_order: str):
    """Return BOM components for this WO that should be treated as semi-finished.

    Heuristic:
      - Start from the WO's BOM.
      - Exclude items in Packaging / Backflush item groups.
      - Include components that themselves have a default active BOM (i.e. SFGs).
    """
    bom_no = frappe.db.get_value("Work Order", work_order, "bom_no")
    if not bom_no:
        return {"items": []}

    try:
        bom = frappe.get_doc("BOM", bom_no)
    except Exception:
        return {"items": []}

    packaging_groups = _packaging_groups_global()
    backflush_groups = _backflush_groups_global()

    items: list[dict] = []
    for row in bom.items:
        ig = _get_item_group(row.item_code) or ""
        group = ig.strip().lower()
        # skip packaging/backflush groups
        if group in packaging_groups or group in backflush_groups:
            continue

        # Treat "has its own default BOM" as semi-finished
        has_child_bom = bool(
            frappe.db.exists(
                "BOM",
                {"item": row.item_code, "is_active": 1, "is_default": 1},
            )
        )
        if not has_child_bom:
            continue

        items.append(
            {
                "item_code": row.item_code,
                "item_name": row.get("item_name") or row.item_code,
                "uom": row.uom or frappe.db.get_value("Item", row.item_code, "stock_uom") or "Nos",
            }
        )

    return {"items": items}

def _post_sfg_consumption(wo, rows: list[dict], fg_completed_qty: float = 0):
    """Post Material Consumption for Manufacture for semi-finished items.

    Expects rows like: {"item_code": "SFG10003", "qty": 123.45}.
    We consume from the configured semi-finished warehouse into the line's WIP (or default warehouse).
    """
    if not rows:
        return

    # Line WIP (target) – fall back to Stock Settings default if not mapped
    t_wh = _default_line_wip(wo.name)
    if not t_wh:
        t_wh = frappe.db.get_single_value("Stock Settings", "default_warehouse")

    # Default SFG source – from Factory Settings, or Semi-finished - ISN, or default
    default_sfg_wh = _default_sfg_source(wo.name)

    se = frappe.new_doc("Stock Entry")
    se.company = wo.company
    se.purpose = "Material Consumption for Manufacture"
    se.work_order = wo.name
    se.fg_completed_qty = fg_completed_qty  # Set to satisfy ERPNext validation - represents finished goods quantity

    for r in rows:
        item_code = (r.get("item_code") or "").strip()
        if not item_code:
            continue
        try:
            qty = float(r.get("qty") or 0)
        except Exception:
            qty = 0.0
        if qty <= 0:
            continue

        ok, msg = _validate_item_in_bom(wo.name, item_code)
        if not ok:
            frappe.throw(msg)

        uom = frappe.db.get_value("Item", item_code, "stock_uom") or "Nos"

        se.append(
            "items",
            {
                "item_code": item_code,
                "qty": qty,
                "uom": uom,
                "s_warehouse": default_sfg_wh,
                # t_warehouse is optional for Consumption; set if you want clearer audit trail
                "t_warehouse": t_wh,
            },
        )

    if not se.items:
        return

    se.flags.ignore_permissions = True
    se.insert()
    se.submit()

# ============================================================
# Scanning, requests, labels, completion  (JC-aware)
# ============================================================

@frappe.whitelist()
def scan_material(code, job_card: Optional[str] = None, work_order: Optional[str] = None):
    """
    Handle a material scan for a job:
      - Parses GS1 (01,10,17,30/37) or fallback "ITEM|BATCH|QTY"
      - Enforces batch when Item has_batch_no = 1
      - Optionally restricts by global Allowed Item Groups (Factory Settings)
      - Skips BOM-membership validation for Packaging Item Groups (Factory Settings)
      - Always posts "Material Consumption for Manufacture" (consume_on_scan is hardcoded to True)
        with warehouses derived from Factory Settings -> Line Warehouse Map, falling
        back to Stock Settings default warehouse.
      - Soft idempotency: ignores duplicates within the configured TTL.
    Returns: {"ok": bool, "msg": str}
    """
    _require_roles(ROLES_OPERATOR)

    try:
        # Resolve target Work Order
        if job_card and not work_order:
            work_order = frappe.db.get_value("Job Card", job_card, "work_order")
        if not work_order:
            frappe.throw(_("Missing work_order / job_card"))

        # Block scans on ended Work Orders.
        _assert_not_ended(work_order)

        # Duplicate-scan guard
        if _has_recent_duplicate(work_order, code):
            return {"ok": False, "msg": _("Duplicate scan ignored")}

        # Parse the scanned payload
        parsed = _parse_gs1_or_basic(code)
        item_code = parsed.get("item_code")
        if not item_code:
            return {"ok": False, "msg": _("Cannot parse item from code")}

        # Require batch if the item is batch-tracked
        if frappe.db.get_value("Item", item_code, "has_batch_no") and not parsed.get("batch_no"):
            return {"ok": False, "msg": _("Batch number required for {0}").format(item_code)}

        # Global Item Group allowlist (Factory Settings -> Allowed Item Groups)
        group = (_get_item_group(item_code) or "").strip().lower()
        allowed_groups = _allowed_groups_global()
        if allowed_groups and group not in allowed_groups:
            return {"ok": False, "msg": _("Item group {0} not allowed").format(group or "?")}

        # Packaging relax: if this item is in Packaging Item Groups, we don't insist it's on the WO BOM
        packaging_groups = _packaging_groups_global()
        is_packaging = group in packaging_groups

        if not is_packaging:
            ok, msg = _validate_item_in_bom(work_order, item_code)
            if not ok:
                return {"ok": False, "msg": msg}

        # Quantities & UoM
        uom = frappe.db.get_value("Item", item_code, "stock_uom") or "Nos"
        qty = float(parsed.get("qty") or 1)

        # Check for over-consumption (only for non-packaging items already in BOM)
        if not is_packaging:
            # Get BOM required quantity for this item
            bom = frappe.db.get_value("Work Order", work_order, "bom_no")
            wo_qty = float(frappe.db.get_value("Work Order", work_order, "qty") or 0)
            
            # Get BOM item qty per unit
            bom_item_qty = frappe.db.sql("""
                SELECT COALESCE(qty_consumed_per_unit, qty, 0) as qty_per_unit
                FROM `tabBOM Item`
                WHERE parent = %s AND item_code = %s
                LIMIT 1
            """, (bom, item_code), as_dict=True)
            
            if bom_item_qty and len(bom_item_qty) > 0:
                bom_required = float(bom_item_qty[0].qty_per_unit) * wo_qty
                
                # Get already consumed quantity
                already_consumed = frappe.db.sql("""
                    SELECT COALESCE(SUM(sed.qty), 0) as total
                    FROM `tabStock Entry` se
                    JOIN `tabStock Entry Detail` sed ON sed.parent = se.name
                    WHERE se.docstatus = 1
                        AND se.work_order = %s
                        AND se.purpose = 'Material Consumption for Manufacture'
                        AND sed.item_code = %s
                        AND sed.is_finished_item = 0
                """, (work_order, item_code))[0][0] or 0
                
                total_after_scan = float(already_consumed) + qty
                
                # Get threshold from Factory Settings (default 150%)
                fs = _fs()
                threshold_pct = float(getattr(fs, "material_overconsumption_threshold", 150))
                threshold_qty = bom_required * (threshold_pct / 100.0)
                
                if total_after_scan > threshold_qty:
                    return {
                        "ok": False, 
                        "msg": _("Excessive quantity: {0:.2f} total (BOM requires {1:.2f}, threshold {2:.0f}%). Contact supervisor.").format(
                            total_after_scan, bom_required, threshold_pct
                        )
                    }

        # Warehouses from line-map (falls back to Stock Settings default)
        s_wh = parsed.get("warehouse") or _default_line_wip(work_order)
        t_wh = _default_line_wip(work_order)
        
        # Check stock availability before attempting consumption
        available_qty = frappe.db.get_value(
            "Bin", 
            {"warehouse": s_wh, "item_code": item_code}, 
            "actual_qty"
        ) or 0

        if qty > available_qty:
            return {
                "ok": False, 
                "msg": _("Insufficient stock in {0}: {1} available, {2} requested").format(
                    s_wh, available_qty, qty
                )
            }
        
        # Always consume materials directly (Material Consumption for Manufacture)
        wo_doc = frappe.get_doc("Work Order", work_order)

        se = frappe.new_doc("Stock Entry")
        se.purpose = "Material Consumption for Manufacture"
        se.stock_entry_type = "Material Consumption for Manufacture"
        se.company = wo_doc.company
        se.work_order = work_order
        se.from_bom = 1
        se.bom_no = wo_doc.bom_no
        se.use_multi_level_bom = wo_doc.use_multi_level_bom
        se.fg_completed_qty = flt(wo_doc.qty) - flt(wo_doc.produced_qty)

        item_dict = {
            "item_code": item_code,
            "qty": qty,
            "uom": uom,
            "s_warehouse": s_wh,
            # For Consumption entries, t_warehouse can be blank or set to WIP for audit trail
            "t_warehouse": t_wh if t_wh else None,
        }
        
        # Handle batch tracking: Use batch_no and let ERPNext create new bundles
        batch_no = parsed.get("batch_no")
        if batch_no:
            item_dict["batch_no"] = batch_no
            # use_serial_batch_fields=1 tells ERPNext to create a new bundle from batch_no
            item_dict["use_serial_batch_fields"] = 1
        
        se.append("items", item_dict)

        se.flags.ignore_permissions = True
        se.insert()
        se.submit()

        return {"ok": True, "msg": _("Consumed {0} {1} of {2}").format(qty, uom, item_code)}

    except Exception as e:
        frappe.log_error(
            title="Material Scan Error",
            message=f"scan_material error: {str(e)}",
        )
        return {"ok": False, "msg": _("Failed to consume material. Please contact administrator.")}


@frappe.whitelist()
def get_requestable_items_for_wo(work_order: str):
    """Return leaf BOM raw-material items for the WO that an operator may
    legitimately request from stores.

    Excludes:
      - Items that have their own active+default BOM (semi-finished goods —
        those are produced via sub-WOs, not requested from stores).

    Each row carries `required / consumed / remaining` so the Operator Hub
    can pre-fill the Qty input and show a shortage hint.
    """
    _require_roles(["Stores User", *ROLES_OPERATOR])

    wo = frappe.get_doc("Work Order", work_order)
    if not wo.bom_no:
        return {"items": []}

    bom_items = _get_bom_items_for_quantity(wo.bom_no, flt(wo.qty))
    consumed_map = _get_consumed_materials_from_load(work_order)
    sfg_codes = {
        row["item_code"]
        for row in (get_sfg_components_for_wo(work_order).get("items") or [])
    }

    out = []
    for bi in bom_items:
        item_code = bi["item_code"]
        if item_code in sfg_codes:
            continue
        required = float(bi.get("qty") or 0)
        consumed = float(consumed_map.get(item_code, 0) or 0)
        remaining = max(required - consumed, 0)
        out.append({
            "item_code": item_code,
            "item_name": frappe.db.get_value("Item", item_code, "item_name") or item_code,
            "uom": bi.get("uom") or "",
            "required": required,
            "consumed": consumed,
            "remaining": remaining,
        })
    return {"items": out}


@frappe.whitelist()
def request_material(item_code, qty, reason=None, job_card: Optional[str] = None, work_order: Optional[str] = None):
    """Operator-initiated Material Request for a shortage on the current WO.

    Restricted to leaf BOM raw materials of the Work Order (non-SFG). Always
    creates a Material Transfer Material Request — central-warehouse / purchase
    decisions are made by the buyer, not the operator.
    """
    _require_roles(["Stores User", *ROLES_OPERATOR])

    qty = float(qty or 0)
    if qty <= 0:
        frappe.throw(_("Quantity must be positive"))

    if job_card and not work_order:
        work_order = frappe.db.get_value("Job Card", job_card, "work_order")
    if not work_order:
        frappe.throw(_("Missing work_order / job_card"))

    _assert_not_ended(work_order)

    requestable = {
        it["item_code"]
        for it in (get_requestable_items_for_wo(work_order).get("items") or [])
    }
    if item_code not in requestable:
        frappe.throw(
            _(
                "Item {0} is not a raw material of this Work Order, or is a "
                "semi-finished item (those are produced, not requested)."
            ).format(item_code)
        )

    mr = frappe.new_doc("Material Request")
    mr.material_request_type = "Material Transfer"
    mr.schedule_date = frappe.utils.nowdate()
    mr.work_order = work_order
    mr.append("items", {
        "item_code": item_code,
        "qty": qty,
        "schedule_date": mr.schedule_date,
    })
    mr.flags.ignore_permissions = True
    mr.insert()
    # Submit so the request is immediately actionable (visible to the
    # Storekeeper Hub Pending Requests panel, which only lists submitted MRs).
    mr.submit()
    if reason:
        # Material Request has no 'notes' field; persist the operator's reason
        # as a Comment so it is visible in the timeline and queryable later.
        mr.add_comment("Comment", reason)

    # Notify any live Storekeeper Hub sessions so they refresh their
    # Pending Requests panel without polling. Listeners are scoped on the
    # client side (only open Storekeeper Hubs react to the event).
    try:
        frappe.publish_realtime(
            event="isnack_pending_mr_changed",
            message={"mr": mr.name, "work_order": work_order, "item_code": item_code},
            after_commit=True,
        )
    except Exception:
        pass

    return {"ok": True, "mr": mr.name, "type": "Material Transfer"}

@frappe.whitelist()
def set_wo_status(work_order, action, reason=None, remarks=None):
    _require_roles(ROLES_OPERATOR)
    wo = frappe.get_doc("Work Order", work_order)

    updates: dict = {}
    if action:  updates["mes_status"]  = action
    if reason:  updates["mes_reason"]  = reason
    if remarks: updates["mes_remarks"] = remarks

    if updates:
        for k, v in updates.items():
            try:
                wo.db_set(k, v, commit=False)
            except Exception:
                pass

    wo.add_comment("Info", _("Production control update: {0}").format({
        "action": action, "reason": reason, "remarks": remarks, "by": frappe.session.user
    }))
    wo.flags.ignore_permissions = True
    wo.save()
    return True

@frappe.whitelist()
def get_wo_progress(work_order):
    actual = frappe.db.sql(
        """
        select coalesce(sum(sed.qty),0)
        from `tabStock Entry` se
        join `tabStock Entry Detail` sed on sed.parent = se.name
        where se.docstatus=1 and se.work_order=%s and se.purpose='Manufacture'
        """,
        work_order,
    )[0][0] or 0
    target = float(frappe.db.get_value("Work Order", work_order, "qty") or 0)
    remaining = max(target - float(actual), 0.0)
    return {"target": target, "actual": float(actual), "remaining": remaining}

@frappe.whitelist()
def complete_work_order(work_order, good, rejects=0, remarks=None, sfg_usage=None):
    """
    Complete a Work Order by:
    1. Creating a Manufacture Stock Entry for the finished goods
    2. Consuming any remaining BOM materials not already consumed via LOAD button
    3. Handling semi-finished goods usage if provided
    4. Recording rejects and remarks
    
    Materials already consumed via LOAD button (Material Consumption for Manufacture)
    are accounted for and not re-consumed.
    """
    _require_roles(ROLES_OPERATOR)

    good = float(good or 0)
    rejects = float(rejects or 0)
    if good <= 0:
        frappe.throw(_("Good quantity must be greater than zero"))
    if rejects < 0:
        frappe.throw(_("Rejects cannot be negative"))

    wo = frappe.get_doc("Work Order", work_order)
    fg_wh = (
        wo.fg_warehouse
        or _default_line_target(work_order)
        or frappe.db.get_single_value("Stock Settings", "default_warehouse")
    )
    uom = frappe.db.get_value("Item", wo.production_item, "stock_uom") or "Nos"
    wip_wh = wo.wip_warehouse or _default_line_wip(work_order)

    # 1) Manufacture (FG/SFG receipt) with material consumption
    se = frappe.new_doc("Stock Entry")
    se.company = wo.company
    se.purpose = "Manufacture"
    se.stock_entry_type = "Manufacture"
    se.work_order = work_order
    se.to_warehouse = fg_wh
    se.fg_completed_qty = good
    se.from_bom = 1
    se.bom_no = wo.bom_no

    # Add finished item
    se.append("items", {
        "item_code": wo.production_item,
        "qty": good,
        "uom": uom,
        "is_finished_item": 1,
        "t_warehouse": fg_wh,
    })

    # Get materials already consumed via LOAD button
    consumed_from_load = _get_consumed_materials_from_load(work_order)

    # Get BOM items scaled for production quantity
    if wo.bom_no:
        bom_items = _get_bom_items_for_quantity(wo.bom_no, good)
        
        # Add remaining materials to consume (subtract what was already consumed via LOAD)
        for bom_item in bom_items:
            item_code = bom_item["item_code"]
            required_qty = bom_item["qty"]
            already_consumed = consumed_from_load.get(item_code, 0)
            remaining_qty = required_qty - already_consumed
            
            # Handle both under-consumption and over-consumption
            if abs(remaining_qty) > QTY_EPSILON:  # Use epsilon for floating point tolerance
                if remaining_qty > 0:
                    # Under-consumed: add remaining quantity
                    se.append("items", {
                        "item_code": item_code,
                        "qty": remaining_qty,
                        "uom": bom_item["uom"],
                        "s_warehouse": wip_wh,
                        "is_finished_item": 0,
                    })
                else:
                    # Over-consumed: log variance for tracking
                    # Calculate variance percentage safely
                    if required_qty > QTY_EPSILON:
                        variance_pct = (abs(remaining_qty) / required_qty * 100)
                    else:
                        # Should not happen - BOM items with zero qty indicate data issue
                        variance_pct = 0
                        frappe.log_error(
                            title="BOM Data Issue",
                            message=f"BOM item with zero required quantity for WO {work_order}: {item_code}",
                        )
                    
                    frappe.log_error(
                        title="Material Over-Consumption",
                        message=(
                            f"Over-consumption detected for WO {work_order}\n"
                            f"Item: {item_code}\n"
                            f"Required: {required_qty:.4f}\n"
                            f"Consumed: {already_consumed:.4f}\n"
                            f"Excess: {abs(remaining_qty):.4f} ({variance_pct:.1f}%)"
                        ),
                    )
                    
                    # Add comment to Work Order for audit trail
                    wo.add_comment(
                        "Comment",
                        f"Over-consumption: {item_code} - Required: {required_qty:.4f}, Consumed: {already_consumed:.4f} ({variance_pct:.1f}% excess)"
                    )

    # Add scrap/rejects if applicable
    if rejects > 0:
        scrap_wh = _default_line_scrap(work_order)
        if scrap_wh:
            se.append("items", {
                "item_code": wo.production_item,
                "qty": rejects,
                "uom": uom,
                "is_scrap_item": 1,
                "t_warehouse": scrap_wh,
            })

    # Set basic_rate on the finished item to account for costs from prior
    # "Material Consumption for Manufacture" entries (consumed via LOAD button).
    # Without this, ERPNext only sees the current entry's outgoing items and may
    # calculate a zero rate for the finished good, causing a valuation error.
    _apply_pre_consumed_cost_to_finished_item(se, work_order, good)

    se.flags.ignore_permissions = True
    se.insert()
    se.submit()

    # 2) Semi-finished usage (slurry / rice mix etc.) if provided
    sfg_rows: list[dict] = []
    if sfg_usage:
        if isinstance(sfg_usage, str):
            try:
                sfg_rows = json.loads(sfg_usage) or []
            except Exception:
                sfg_rows = []
        elif isinstance(sfg_usage, (list, tuple)):
            sfg_rows = list(sfg_usage)

    if sfg_rows:
        _post_sfg_consumption(wo, sfg_rows, good)

    # 3) Remarks + rejects
    if remarks:
        try:
            wo.db_set("remarks", remarks, commit=False)
        except Exception:
            pass

    if rejects:
        try:
            current = float(wo.get("custom_rejects_qty") or 0)
            wo.db_set("custom_rejects_qty", current + rejects, commit=False)
        except Exception:
            pass

    try:
        frappe.db.set_value(
            "Work Order",
            work_order,
            {"status": "Completed", "actual_end_date": frappe.utils.now_datetime()},
        )
    except Exception:
        pass

    # Reload the document to get the updated modified timestamp
    wo.reload()
    
    wo.add_comment("Info", _("WO FG receipt: Good={0}, Rejects={1}, Remarks={2}").format(good, rejects, (remarks or "")))
    wo.flags.ignore_permissions = True
    wo.save()
    return True

def _assert_not_ended(work_order: str) -> None:
    """Block any material movement / state change once End WO has been pressed.

    Source-of-truth guard used by scan, manual load, and Start/Resume so a stale
    UI tab cannot keep posting against an ended Work Order. Cleared by
    `close_production` when it sets `custom_production_ended = 0`.
    """
    if not work_order:
        return
    if frappe.db.get_value("Work Order", work_order, "custom_production_ended"):
        frappe.throw(
            _("Work Order {0} has been ended; further material movements are "
              "not allowed until Close Production.").format(work_order)
        )


# Default tolerance applied to End WO consumption check when Factory Settings
# does not define `end_wo_tolerance_pct`. Expressed as a percent of required qty.
END_WO_DEFAULT_TOLERANCE_PCT = 2.0
ROLES_END_WO_OVERRIDE = ["Production Manager"]


def _end_wo_tolerance_pct() -> float:
    """Read End WO tolerance % from Factory Settings, falling back to the
    default. The Factory Settings field is optional; we check the meta first
    so we never call `get_single_value` on a missing field (which would emit
    a "Field does not exist" message to the client even if we catch the
    Python exception)."""
    try:
        meta = frappe.get_meta("Factory Settings")
        if not meta.has_field("end_wo_tolerance_pct"):
            return END_WO_DEFAULT_TOLERANCE_PCT
        val = frappe.db.get_single_value("Factory Settings", "end_wo_tolerance_pct")
        if val is not None and float(val) >= 0:
            return float(val)
    except Exception:
        pass
    return END_WO_DEFAULT_TOLERANCE_PCT


def _end_wo_consumption_summary(work_order: str) -> dict:
    """Compute required vs consumed for each BOM item on the WO.

    Returns a dict with:
      - tolerance_pct: float
      - items: list of rows (excluding SFG components, which are handled
        separately via the End WO dialog's SFG section). Each row:
          {item_code, item_name, uom, required, consumed, remaining,
           is_packaging, is_sfg, status}
        status ∈ {"ok", "short", "over"}.
      - shortfalls: count of items with status == "short" (non-SFG, non-packaging)
      - can_end: True iff there are no shortfalls

    Packaging items are intentionally excluded from the shortfall gate:
    they are deferred to Close Production, where ``_close_single_wo``
    consumes them from WIP as part of the final Manufacture Stock Entry.
    """
    tolerance_pct = _end_wo_tolerance_pct()
    out = {"tolerance_pct": tolerance_pct, "items": [], "shortfalls": 0, "can_end": True}

    wo = frappe.get_doc("Work Order", work_order)
    if not wo.bom_no:
        return out

    bom_items = _get_bom_items_for_quantity(wo.bom_no, flt(wo.qty))
    consumed_map = _get_consumed_materials_from_load(work_order)

    sfg_codes = {row["item_code"] for row in (get_sfg_components_for_wo(work_order).get("items") or [])}
    packaging_groups = _packaging_groups_global()

    rows: list[dict] = []
    shortfalls = 0
    for bi in bom_items:
        item_code = bi["item_code"]
        required = float(bi.get("qty") or 0)
        consumed = float(consumed_map.get(item_code, 0) or 0)
        remaining = required - consumed
        group = (_get_item_group(item_code) or "").strip().lower()
        is_packaging = group in packaging_groups
        is_sfg = item_code in sfg_codes
        allowed_short = required * (tolerance_pct / 100.0)

        if remaining > allowed_short + QTY_EPSILON:
            status = "short"
        elif remaining < -QTY_EPSILON:
            status = "over"
        else:
            status = "ok"

        # SFG items are handled by the SFG section of the dialog and are
        # excluded from the "must be consumed" gate. Packaging items are
        # intentionally deferred to Close Production (consumed there via
        # the Manufacture Stock Entry), so they also do not block End WO.
        if not is_sfg and not is_packaging and status == "short":
            shortfalls += 1

        rows.append(
            {
                "item_code": item_code,
                "item_name": frappe.db.get_value("Item", item_code, "item_name") or item_code,
                "uom": bi.get("uom") or "",
                "required": required,
                "consumed": consumed,
                "remaining": remaining,
                "is_packaging": is_packaging,
                "is_sfg": is_sfg,
                "status": status,
            }
        )

    out["items"] = rows
    out["shortfalls"] = shortfalls
    out["can_end"] = shortfalls == 0
    return out


@frappe.whitelist()
def get_end_wo_summary(work_order: str):
    """Snapshot used by the Operator Hub End WO dialog.

    Combines the consumption summary with the existing SFG component list and
    a flag indicating whether the current user can override a shortfall.
    """
    _require_roles(ROLES_OPERATOR)
    summary = _end_wo_consumption_summary(work_order)
    summary["sfg_items"] = (get_sfg_components_for_wo(work_order) or {}).get("items") or []
    user_roles = set(frappe.get_roles(frappe.session.user))
    summary["can_override"] = bool(set(ROLES_END_WO_OVERRIDE) & user_roles)
    return summary


@frappe.whitelist()
def end_work_order(work_order: str, sfg_usage: str = None,
                   override_reason: str = None):
    """
    End a work order - consume SFG materials and mark as ended.
    Does NOT create Manufacture Stock Entry.
    
    Args:
        work_order: Work Order name
        sfg_usage: JSON string of SFG items to consume [{"item_code": "...", "qty": ...}]
    """
    _require_roles(ROLES_OPERATOR)

    wo = frappe.get_doc("Work Order", work_order)

    # Validate WO status - must be In Process or Not Started with allocation
    if wo.status not in ("Not Started", "In Process"):
        frappe.throw(_("Work Order must be 'Not Started' or 'In Process' to end"))

    # Check if already ended
    if wo.get("custom_production_ended"):
        frappe.throw(_("Work Order is already ended"))

    # Parse and post SFG consumption if provided
    sfg_rows: list[dict] = []
    if sfg_usage:
        if isinstance(sfg_usage, str):
            try:
                sfg_rows = json.loads(sfg_usage) or []
            except Exception:
                sfg_rows = []
        elif isinstance(sfg_usage, (list, tuple)):
            sfg_rows = list(sfg_usage)

    if sfg_rows:
        _post_sfg_consumption(wo, sfg_rows, 0)  # fg_completed_qty = 0 since we're not creating FG yet

    # Tolerance-based check: every required (non-SFG) BOM item must be
    # consumed at or above (required - tolerance). Production Managers can
    # override with a written reason which is stored on the WO for audit.
    summary = _end_wo_consumption_summary(work_order)
    if not summary["can_end"]:
        reason = (override_reason or "").strip()
        user_roles = set(frappe.get_roles(frappe.session.user))
        is_override_allowed = bool(set(ROLES_END_WO_OVERRIDE) & user_roles)

        # Packaging shortfalls are not blocking (deferred to Close Production)
        # so keep them out of the audit / override message as well.
        short_rows = [
            r for r in summary["items"]
            if (not r["is_sfg"]) and (not r["is_packaging"]) and r["status"] == "short"
        ]
        short_summary = ", ".join(
            f"{r['item_code']} ({r['consumed']:.4g}/{r['required']:.4g} {r['uom']})"
            for r in short_rows
        )

        if not reason:
            frappe.throw(
                _(
                    "Cannot end Work Order: {0} required item(s) below tolerance "
                    "({1}%): {2}. All required materials must be consumed "
                    "(within tolerance) before ending."
                ).format(summary["shortfalls"], summary["tolerance_pct"], short_summary)
            )
        if not is_override_allowed:
            frappe.throw(
                _(
                    "Only a Production Manager can force-end an under-consumed "
                    "Work Order. Shortfall: {0}."
                ).format(short_summary)
            )
        # Reason supplied + manager role: log and continue.
        wo.add_comment(
            "Info",
            _(
                "End WO override by {0}. Shortfall (>{1}% tolerance): {2}. Reason: {3}"
            ).format(frappe.session.user, summary["tolerance_pct"], short_summary, reason),
        )

    # Mark as ended
    wo.db_set("custom_production_ended", 1, commit=True)
    wo.add_comment("Info", _("Work Order ended - awaiting production closure"))

    return {"success": True, "message": "Work Order ended successfully"}

@frappe.whitelist()
def get_ended_work_orders(lines: str = None):
    """
    Get all work orders that have been 'ended' but not 'closed'.
    Filter by lines if provided.
    
    Args:
        lines: JSON array of line names to filter
    
    Returns:
        dict: {"work_orders": [{"name": "...", "item_name": "...", "qty": ..., "production_item": "..."}]}
    """
    _require_roles(ROLES_OPERATOR)
    
    filters = {
        "custom_production_ended": 1,
        "status": ["!=", "Completed"],
    }
    
    line_list = []

    # Filter by lines if provided
    if lines:
        try:
            line_list = json.loads(lines) if isinstance(lines, str) else lines
            if line_list:
                filters["custom_factory_line"] = ["in", line_list]
        except Exception:
            pass
    
    work_orders = frappe.get_all(
        "Work Order",
        filters=filters,
        fields=["name", "production_item", "qty"],
        order_by="creation asc"
    )

    if lines and line_list:
        work_orders = [
            wo for wo in work_orders
            if (_line_for_work_order(wo["name"]) in line_list)
        ]
    
    # Enrich with item names
    for wo in work_orders:
        wo["item_name"] = frappe.db.get_value("Item", wo["production_item"], "item_name") or wo["production_item"]
    
    return {"work_orders": work_orders}

@frappe.whitelist()
def get_pallet_label_data(lines: str = None):
    """
    Get pallet label data from Work Orders closed today (FG items only).
    Groups by production_item and returns summed quantities.
    
    Args:
        lines: JSON array of line names to filter
    
    Returns:
        dict: {
            "items": [
                {
                    "item_code": "...",
                    "item_name": "...",
                    "description": "...",
                    "default_uom": "...",
                    "carton_qty": ...,
                    "work_orders": ["WO-001", "WO-002"]
                }
            ],
            "allowed_pallet_uoms": ["EURO 1", "EURO 4"]
        }
    """
    _require_roles(ROLES_OPERATOR)
    
    # Source: FG Work Orders closed (status Completed) today on the selected
    # line(s). The client prints pallet labels after the daily production
    # close, so only Work Orders closed today are aggregated.
    today = frappe.utils.today()
    wo_filters = {
        "status": "Completed",
        "actual_end_date": ["between", [today + " 00:00:00", today + " 23:59:59"]],
    }

    line_list = []
    if lines:
        try:
            line_list = json.loads(lines) if isinstance(lines, str) else lines
        except Exception:
            line_list = []
        if line_list:
            wo_filters["custom_factory_line"] = ["in", line_list]

    work_orders = frappe.get_all(
        "Work Order",
        filters=wo_filters,
        fields=["name", "production_item", "produced_qty"],
        order_by="creation asc",
    )

    if lines and line_list:
        work_orders = [
            wo for wo in work_orders
            if _line_for_work_order(wo["name"]) in line_list
        ]
    
    # Group by production_item
    grouped = {}
    for wo in work_orders:
        item_code = wo["production_item"]
        if item_code not in grouped:
            grouped[item_code] = {
                "item_code": item_code,
                "work_orders": [],
                "qty": 0
            }
        grouped[item_code]["work_orders"].append(wo["name"])
        # Carton Qty reflects the quantity actually produced, not the planned
        # Work Order qty, so pallet labels match what was really palletised.
        grouped[item_code]["qty"] += flt(wo.get("produced_qty", 0))
    
    # Enrich with item details
    items = []
    for item_code, data in grouped.items():
        item_details = frappe.db.get_value(
            "Item",
            item_code,
            ["item_name", "description", "stock_uom"],
            as_dict=True
        )
        if item_details:
            items.append({
                "item_code": item_code,
                "item_name": item_details.get("item_name", ""),
                "description": item_details.get("description", ""),
                "default_uom": item_details.get("stock_uom", ""),
                "carton_qty": data["qty"],
                "work_orders": data["work_orders"]
            })
    
    # Get allowed pallet UOMs from Factory Settings
    allowed_pallet_uoms = []
    try:
        fs = frappe.get_cached_doc("Factory Settings")
        if hasattr(fs, "pallet_uom_options") and fs.pallet_uom_options:
            allowed_pallet_uoms = [row.uom for row in fs.pallet_uom_options if row.uom]
    except Exception:
        pass
    
    return {
        "items": items,
        "allowed_pallet_uoms": allowed_pallet_uoms
    }


def _pallet_label_print_summary(work_orders: list) -> dict:
    """
    Summarise prior *pallet*-label prints for a set of Work Orders so the
    reprint screen can show what was already printed.

    Pallet-label prints are identified by their Label Record payload carrying a
    "pallet_type" (set by print_pallet_label); plain carton-label records are
    ignored.

    Returns {"printed_wo_count": int, "label_count": int, "last_printed_on": datetime|None}.
    """
    summary = {"printed_wo_count": 0, "label_count": 0, "last_printed_on": None}
    if not work_orders:
        return summary

    src_rows = frappe.get_all(
        "Label Record Source",
        filters={"source_doctype": "Work Order", "source_docname": ["in", work_orders]},
        fields=["source_docname", "parent"],
    )
    if not src_rows:
        return summary

    parent_names = list({r["parent"] for r in src_rows})
    records = frappe.get_all(
        "Label Record",
        filters={"name": ["in", parent_names]},
        fields=["name", "payload", "creation"],
    )

    pallet_records = {}
    for rec in records:
        try:
            payload = json.loads(rec.get("payload") or "{}")
        except Exception:
            payload = {}
        if payload.get("pallet_type"):
            pallet_records[rec["name"]] = rec["creation"]

    if not pallet_records:
        return summary

    printed_wos = {r["source_docname"] for r in src_rows if r["parent"] in pallet_records}
    summary["printed_wo_count"] = len(printed_wos)
    summary["label_count"] = len(pallet_records)
    summary["last_printed_on"] = max(pallet_records.values())
    return summary


@frappe.whitelist()
def get_pallet_label_data_for_production_plan(production_plan: str):
    """
    Pallet label data for the closed (status Completed) Work Orders of a
    Production Plan, grouped per production item. Data source for the
    pallet-label reprint dialog on the Production Plan form.

    Mirrors get_pallet_label_data but is scoped to a Production Plan instead of
    a factory line + today, and adds a printed-status summary per item so the
    production manager can see which pallet labels were already printed before
    reprinting. Carton Qty is the produced quantity, summed across the WOs.
    """
    _require_roles(ROLES_OPERATOR)

    if not production_plan:
        return {"items": [], "allowed_pallet_uoms": []}

    work_orders = frappe.get_all(
        "Work Order",
        filters={"production_plan": production_plan, "status": "Completed"},
        fields=["name", "production_item", "produced_qty"],
        order_by="creation asc",
    )

    # Group by production_item
    grouped = {}
    for wo in work_orders:
        item_code = wo["production_item"]
        if item_code not in grouped:
            grouped[item_code] = {"item_code": item_code, "work_orders": [], "qty": 0}
        grouped[item_code]["work_orders"].append(wo["name"])
        grouped[item_code]["qty"] += flt(wo.get("produced_qty", 0))

    # Enrich with item details and printed status
    items = []
    for item_code, data in grouped.items():
        item_details = frappe.db.get_value(
            "Item", item_code, ["item_name", "description", "stock_uom"], as_dict=True
        )
        if not item_details:
            continue
        printed = _pallet_label_print_summary(data["work_orders"])
        items.append({
            "item_code": item_code,
            "item_name": item_details.get("item_name", ""),
            "description": item_details.get("description", ""),
            "default_uom": item_details.get("stock_uom", ""),
            "carton_qty": data["qty"],
            "work_orders": data["work_orders"],
            "total_wo_count": len(data["work_orders"]),
            "printed_wo_count": printed["printed_wo_count"],
            "label_count": printed["label_count"],
            "last_printed_on": printed["last_printed_on"],
        })

    # Allowed pallet UOMs from Factory Settings
    allowed_pallet_uoms = []
    try:
        fs = frappe.get_cached_doc("Factory Settings")
        if hasattr(fs, "pallet_uom_options") and fs.pallet_uom_options:
            allowed_pallet_uoms = [row.uom for row in fs.pallet_uom_options if row.uom]
    except Exception:
        pass

    return {"items": items, "allowed_pallet_uoms": allowed_pallet_uoms}


@frappe.whitelist()
def get_pallet_conversion_factor(item_code: str, from_uom: str, to_uom: str):
    """
    Get UOM conversion factor for pallet label calculation.
    
    Priority:
    1. Check Item's UOM Conversion Detail (child table on Item)
    2. Check global UOM Conversion Factor table
    3. If no conversion exists, return found: false
    
    Args:
        item_code: Item code
        from_uom: Source UOM (e.g., "Carton")
        to_uom: Target UOM (e.g., "EUR 1 Pallet")
    
    Returns:
        dict: {"conversion_factor": <value>, "found": true} when found
              {"conversion_factor": null, "found": false} when not found
    """
    _require_roles(ROLES_OPERATOR)
    
    if not item_code or not from_uom or not to_uom:
        return {"conversion_factor": None, "found": False}
    
    if from_uom == to_uom:
        return {"conversion_factor": 1.0, "found": True}
    
    try:
        # Priority 1: Check item-specific UOM conversions from the Item's UOM Conversion Detail
        # We need to get the item's stock UOM and the conversion factors for both from_uom and to_uom
        item = frappe.get_cached_value("Item", item_code, ["stock_uom"], as_dict=True)
        stock_uom = item.get("stock_uom") if item else None
        
        if stock_uom:
            # Get conversion factors for both from_uom and to_uom relative to stock UOM
            from_uom_factor = None
            to_uom_factor = None
            
            if from_uom == stock_uom:
                from_uom_factor = 1.0
            else:
                from_uom_result = frappe.get_all(
                    "UOM Conversion Detail",
                    filters={"parent": item_code, "uom": from_uom},
                    fields=["conversion_factor"],
                    limit=1
                )
                if from_uom_result and from_uom_result[0].get("conversion_factor"):
                    from_uom_factor = flt(from_uom_result[0]["conversion_factor"])
            
            if to_uom == stock_uom:
                to_uom_factor = 1.0
            else:
                to_uom_result = frappe.get_all(
                    "UOM Conversion Detail",
                    filters={"parent": item_code, "uom": to_uom},
                    fields=["conversion_factor"],
                    limit=1
                )
                if to_uom_result and to_uom_result[0].get("conversion_factor"):
                    to_uom_factor = flt(to_uom_result[0]["conversion_factor"])
            
            # If both conversions exist, calculate the conversion from from_uom to to_uom
            # Formula: pallet_qty = carton_qty / conversion_factor
            # Example: If stock UOM is "Carton" and:
            #   - 1 Carton = 1 Carton (from_uom_factor = 1)
            #   - 1 EUR 1 Pallet = 4 Cartons (to_uom_factor = 4)
            # Then: conversion_factor = to_uom_factor / from_uom_factor = 4 / 1 = 4
            # So: pallet_qty = 10 cartons / 4 = 2.5 pallets ✓
            #
            # General case:
            # from_uom_factor = how many stock UOMs in 1 from_uom
            # to_uom_factor = how many stock UOMs in 1 to_uom
            # conversion = to_uom_factor / from_uom_factor
            if from_uom_factor is not None and to_uom_factor is not None and from_uom_factor != 0:
                conversion_factor = to_uom_factor / from_uom_factor
                return {"conversion_factor": conversion_factor, "found": True}
        
        # Priority 2: Check global UOM Conversion Factor table
        uom_conversions = frappe.get_all(
            "UOM Conversion Factor",
            filters=[
                ["from_uom", "=", from_uom],
                ["to_uom", "=", to_uom]
            ],
            fields=["value"],
            limit=1
        )
        if uom_conversions and uom_conversions[0].get("value"):
            return {"conversion_factor": flt(uom_conversions[0]["value"]), "found": True}
        
        # Try inverse conversion in global table
        uom_conversions_inverse = frappe.get_all(
            "UOM Conversion Factor",
            filters=[
                ["from_uom", "=", to_uom],
                ["to_uom", "=", from_uom]
            ],
            fields=["value"],
            limit=1
        )
        if uom_conversions_inverse and uom_conversions_inverse[0].get("value"):
            inverse_value = flt(uom_conversions_inverse[0]["value"])
            if inverse_value:
                return {"conversion_factor": 1.0 / inverse_value, "found": True}
        
    except Exception as e:
        frappe.log_error(
            title="Pallet Conversion Factor Error",
            message=f"Error getting conversion factor: {str(e)}",
        )
    
    # No conversion found
    return {"conversion_factor": None, "found": False}

@frappe.whitelist()
def get_packaging_items():
    """
    Get items from Packaging Item Groups (Factory Settings).
    
    Returns:
        dict: {"items": [{"item_code": "...", "item_name": "...", "stock_uom": "..."}]}
    """
    _require_roles(ROLES_OPERATOR)
    
    packaging_groups = _packaging_groups_global()
    
    if not packaging_groups:
        return {"items": []}
    
    # Get all items in packaging item groups
    items = frappe.get_all(
        "Item",
        filters={"item_group": ["in", list(packaging_groups)]},
        fields=["item_code", "item_name", "stock_uom"],
        order_by="item_code asc"
    )
    
    return {"items": items}

@frappe.whitelist()
def get_packaging_bom_items_for_ended_wos(work_orders: str = None, lines: str = None):
    """
    Get packaging BOM items for ended work orders.
    
    Only returns packaging items that appear on the BOMs of the ended work orders
    being closed (and are in Packaging Item Groups).
    
    Args:
        work_orders: JSON array of work order names (preferred)
        lines: JSON array of line names (fallback to resolve ended WOs)
    
    Returns:
        dict: {"items": [{"item_code": "...", "item_name": "...", "stock_uom": "..."}]}
    """
    _require_roles(ROLES_OPERATOR)
    
    packaging_groups = _packaging_groups_global()
    
    if not packaging_groups:
        return {"items": []}
    
    # Parse work_orders parameter
    wo_list = []
    if work_orders:
        try:
            wo_list = json.loads(work_orders) if isinstance(work_orders, str) else work_orders
        except Exception as e:
            # Log parsing error but continue with empty list
            frappe.log_error(
                title="Packaging BOM Work Orders Parse Error",
                message=f"Failed to parse work_orders parameter: {str(e)}",
            )
    
    # If no explicit work orders provided, resolve from lines
    if not wo_list and lines:
        try:
            line_list = json.loads(lines) if isinstance(lines, str) else lines
            if line_list:
                filters = {
                    "custom_production_ended": 1,
                    "status": ["!=", "Completed"],
                    "custom_factory_line": ["in", line_list]
                }
                ended_wos = frappe.get_all(
                    "Work Order",
                    filters=filters,
                    fields=["name"],
                    order_by="creation asc"
                )
                wo_list = [wo["name"] for wo in ended_wos]
        except Exception as e:
            # Log error but continue - may be invalid lines parameter or query failure
            frappe.log_error(
                title="Packaging BOM Work Orders Resolve Error",
                message=f"Failed to resolve work orders from lines: {str(e)}",
            )
    
    if not wo_list:
        return {"items": []}
    
    # Collect BOMs for the work orders in a single query
    bom_data = frappe.db.get_all(
        "Work Order",
        filters={"name": ["in", wo_list]},
        fields=["name", "bom_no"]
    )
    bom_nos = [row["bom_no"] for row in bom_data if row.get("bom_no")]
    
    if not bom_nos:
        return {"items": []}
    
    # Get all BOM items from all BOMs in a single query
    bom_items = frappe.db.get_all(
        "BOM Item",
        filters={"parent": ["in", bom_nos]},
        fields=["item_code"]
    )
    
    # Get unique item codes using set comprehension
    unique_item_codes = list({row["item_code"] for row in bom_items})
    
    if not unique_item_codes:
        return {"items": []}
    
    # Get WIP warehouses for these work orders (used for batch availability lookup)
    wip_warehouses = set()
    for wo_name in wo_list:
        line = _line_for_work_order(wo_name)
        if line:
            _, wip_wh, _, _ = _warehouses_for_line(line)
            if wip_wh:
                wip_warehouses.add(wip_wh)

    # Get item groups for all items in a single query
    item_group_data = frappe.db.get_all(
        "Item",
        filters={"name": ["in", unique_item_codes]},
        fields=["name", "item_group", "item_name", "stock_uom", "has_batch_no"]
    )
    
    # Filter items that belong to packaging groups
    packaging_items = []
    for item_data in item_group_data:
        ig = item_data.get("item_group") or ""
        group = ig.strip().lower()
        
        if group in packaging_groups:
            has_batch = item_data.get("has_batch_no")

            if has_batch and wip_warehouses:
                item_code = item_data["name"]
                wh_list = list(wip_warehouses)
                wh_placeholders = ", ".join(["%s"] * len(wh_list))
                wo_placeholders = ", ".join(["%s"] * len(wo_list))
                params_wo = tuple([item_code] + wh_list + wo_list)

                # Strategy 1: find batches via direct batch_no on SLE linked to these work orders
                direct_rows = frappe.db.sql(f"""
                    SELECT DISTINCT sle.batch_no
                    FROM `tabStock Ledger Entry` sle
                    JOIN `tabStock Entry` se ON se.name = sle.voucher_no
                    WHERE sle.item_code = %s
                      AND sle.warehouse IN ({wh_placeholders})
                      AND se.work_order IN ({wo_placeholders})
                      AND se.docstatus = 1
                      AND sle.batch_no IS NOT NULL AND sle.batch_no != ''
                """, params_wo, as_dict=True)

                # Strategy 2: find batches via serial_and_batch_bundle (ERPNext v15 bundle approach)
                bundle_rows = frappe.db.sql(f"""
                    SELECT DISTINCT sbe.batch_no
                    FROM `tabStock Ledger Entry` sle
                    JOIN `tabStock Entry` se ON se.name = sle.voucher_no
                    JOIN `tabSerial and Batch Entry` sbe ON sbe.parent = sle.serial_and_batch_bundle
                    WHERE sle.item_code = %s
                      AND sle.warehouse IN ({wh_placeholders})
                      AND se.work_order IN ({wo_placeholders})
                      AND se.docstatus = 1
                      AND sle.serial_and_batch_bundle IS NOT NULL
                      AND sle.serial_and_batch_bundle != ''
                      AND sbe.batch_no IS NOT NULL AND sbe.batch_no != ''
                """, params_wo, as_dict=True)

                found_batches = list(
                    {r.batch_no for r in direct_rows} | {r.batch_no for r in bundle_rows}
                )

                # Compute consumed qty per batch from Material Consumption for Manufacture
                # Stock Entries for the ended work orders. This shows how much was already
                # consumed via the LOAD button during production. Counts batches recorded
                # both directly and via Serial-and-Batch Bundles.
                batch_map = {}
                if found_batches:
                    consumed_by_batch = _consumed_qty_by_batch(wo_list, item_code)
                    for bno in found_batches:
                        batch_map[bno] = consumed_by_batch.get(bno, 0)

                if batch_map:
                    for bno in sorted(batch_map):
                        packaging_items.append({
                            "item_code": item_data["name"],
                            "item_name": item_data.get("item_name") or item_data["name"],
                            "stock_uom": item_data.get("stock_uom") or "Nos",
                            "has_batch_no": 1,
                            "batch_no": bno,
                            "consumed_qty": batch_map[bno],
                        })
                else:
                    # Batch-tracked item but no batches found — still expose it
                    packaging_items.append({
                        "item_code": item_data["name"],
                        "item_name": item_data.get("item_name") or item_data["name"],
                        "stock_uom": item_data.get("stock_uom") or "Nos",
                        "has_batch_no": 1,
                        "batch_no": None,
                        "consumed_qty": None,
                    })
            else:
                packaging_items.append({
                    "item_code": item_data["name"],
                    "item_name": item_data.get("item_name") or item_data["name"],
                    "stock_uom": item_data.get("stock_uom") or "Nos",
                    "has_batch_no": 0,
                    "batch_no": None,
                    "consumed_qty": None,
                })
    
    # Sort by item_code then batch_no for consistency
    packaging_items.sort(key=lambda x: (x["item_code"], x.get("batch_no") or ""))
    
    return {"items": packaging_items}

def _validate_close_production(lines, ended_wos):
    """
    Validate close production based on Factory Settings validation mode.
    
    Args:
        lines: List of line names
        ended_wos: List of ended work orders
    
    Raises:
        frappe.ValidationError if validation fails
    """
    fs = _fs()
    mode = getattr(fs, "close_production_validation_mode", "No Validation") or "No Validation"
    
    if mode == "No Validation":
        return True
    
    if mode == "All WOs on Line Must Be Ended":
        # Get all non-completed WOs for these lines
        filters = {
            "status": ["!=", "Completed"],
        }
        if lines:
            filters["custom_factory_line"] = ["in", lines]
        
        all_wos = frappe.get_all(
            "Work Order",
            filters=filters,
            fields=["name", "custom_production_ended"]
        )

        if lines:
            all_wos = [
                wo for wo in all_wos
                if _line_for_work_order(wo["name"]) in lines
            ]
        
        not_ended = [wo.name for wo in all_wos if not wo.get("custom_production_ended")]
        if not_ended:
            frappe.throw(_("All work orders on the line must be ended. Not ended: {0}").format(
                ", ".join(not_ended)
            ))
    
    elif mode == "Minimum Number of WOs":
        min_count = int(getattr(fs, "close_production_min_wo_count", 1) or 1)
        if len(ended_wos) < min_count:
            frappe.throw(_("At least {0} work orders must be ended. Currently ended: {1}").format(
                min_count, len(ended_wos)
            ))
    
    return True

def _calculate_proportional_split(ended_wos, total_good, total_reject, packaging_items):
    """
    Split quantities proportionally based on each WO's qty.
    
    Args:
        ended_wos: List of work order dicts with 'name' and 'qty'
        total_good: Total good quantity to split
        total_reject: Total reject quantity to split
        packaging_items: List of packaging item dicts with 'item_code', 'qty', and optional 'batch_no'
    
    Returns:
        dict: {wo_name: {"good": X, "reject": Y, "packaging": [{"item_code": ..., "qty": ..., "batch_no": ...}]}}
    """
    total_wo_qty = sum(float(wo.get("qty", 0)) for wo in ended_wos)
    
    if total_wo_qty <= 0:
        frappe.throw(_("Total work order quantity is zero or negative"))
    
    result = {}
    for wo in ended_wos:
        proportion = float(wo.get("qty", 0)) / total_wo_qty
        
        result[wo["name"]] = {
            "good": total_good * proportion,
            "reject": total_reject * proportion,
            "packaging": [
                {
                    "item_code": item["item_code"],
                    "qty": float(item.get("qty", 0)) * proportion,
                    "batch_no": item.get("batch_no"),
                }
                for item in packaging_items
            ]
        }
    
    return result

def _close_single_wo(wo_data: dict, split: dict, batch_no: str) -> None:
    """Close one Work Order: book Manufacture Stock Entry, mark Completed."""
    wo_name = wo_data["name"]
    try:
        wo = frappe.get_doc("Work Order", wo_name)
        fg_wh = (
            wo.fg_warehouse
            or _default_line_target(wo_name)
            or frappe.db.get_single_value("Stock Settings", "default_warehouse")
        )
        uom = frappe.db.get_value("Item", wo.production_item, "stock_uom") or "Nos"
        wip_wh = wo.wip_warehouse or _default_line_wip(wo_name)
        has_batch = bool(frappe.db.get_value("Item", wo.production_item, "has_batch_no"))

        scrap_wh = None
        if split["reject"] > 0:
            scrap_wh = _default_line_scrap(wo_name)
            if not scrap_wh:
                line = _line_for_work_order(wo_name) or "?"
                frappe.throw(_(
                    "Scrap warehouse is not configured for line {0} (Work Order {1}). "
                    "Set scrap_warehouse in Factory Settings → Line Warehouse Map before "
                    "closing production with rejects."
                ).format(line, wo_name))

        # Create Manufacture Stock Entry
        se = frappe.new_doc("Stock Entry")
        se.company = wo.company
        se.purpose = "Manufacture"
        se.stock_entry_type = "Manufacture"
        se.work_order = wo_name
        se.to_warehouse = fg_wh
        se.fg_completed_qty = split["good"]
        se.from_bom = 1
        se.bom_no = wo.bom_no

        # Add finished item
        finished_item = {
            "item_code": wo.production_item,
            "qty": split["good"],
            "uom": uom,
            "is_finished_item": 1,
            "t_warehouse": fg_wh,
        }
        if batch_no:
            _ensure_batch(wo.production_item, batch_no)
            finished_item["batch_no"] = batch_no
            finished_item["use_serial_batch_fields"] = 1
        se.append("items", finished_item)

        # Materials already consumed via LOAD button
        consumed_from_load = _get_consumed_materials_from_load(wo_name)

        # Scale BOM to total throughput (good + reject) so the inputs that went
        # into rejected units are also consumed; otherwise they remain in WIP.
        total_production_qty = split["good"] + split["reject"]

        # Packaging items are handled exclusively by the dedicated packaging
        # loop below (which uses the qty entered at Close Production and the
        # selected batch). They must be skipped here, otherwise the BOM-scaling
        # loop would consume them once on a BOM-quantity basis without a batch
        # and the packaging loop would consume them again on a usage basis —
        # leading to double consumption / negative-stock errors.
        packaging_groups = _packaging_groups_global()

        if wo.bom_no and total_production_qty > 0:
            bom_items = _get_bom_items_for_quantity(wo.bom_no, total_production_qty)

            for bom_item in bom_items:
                item_code = bom_item["item_code"]
                group = (_get_item_group(item_code) or "").strip().lower()
                if group in packaging_groups:
                    continue
                required_qty = bom_item["qty"]
                already_consumed = consumed_from_load.get(item_code, 0)
                remaining_qty = required_qty - already_consumed

                if abs(remaining_qty) > QTY_EPSILON:
                    if remaining_qty > 0:
                        se.append("items", {
                            "item_code": item_code,
                            "qty": remaining_qty,
                            "uom": bom_item["uom"],
                            "s_warehouse": wip_wh,
                            "is_finished_item": 0,
                        })
                    else:
                        if required_qty > QTY_EPSILON:
                            variance_pct = (abs(remaining_qty) / required_qty * 100)
                        else:
                            variance_pct = 0
                        frappe.log_error(
                            title="Material Over-Consumption",
                            message=(
                                f"Over-consumption detected for WO {wo_name}\n"
                                f"Item: {item_code}\n"
                                f"Required: {required_qty:.4f}\n"
                                f"Consumed: {already_consumed:.4f}\n"
                                f"Excess: {abs(remaining_qty):.4f} ({variance_pct:.1f}%)"
                            ),
                        )

        # Packaging materials (only the portion not already consumed via LOAD)
        if split["packaging"]:
            for pkg_item in split["packaging"]:
                item_code = pkg_item["item_code"]
                qty = pkg_item["qty"]
                # Must not shadow the outer parameter batch_no (Finished Goods batch).
                pkg_batch_no = pkg_item.get("batch_no")
                if qty <= 0:
                    continue

                consumed_by_batch = _consumed_qty_by_batch([wo_name], item_code)
                if pkg_batch_no:
                    already_consumed_pkg_qty = flt(consumed_by_batch.get(pkg_batch_no, 0))
                else:
                    already_consumed_pkg_qty = flt(sum(consumed_by_batch.values()))
                remaining_pkg_qty = qty - already_consumed_pkg_qty

                if remaining_pkg_qty > QTY_EPSILON:
                    item_uom = frappe.db.get_value("Item", item_code, "stock_uom") or "Nos"
                    row = {
                        "item_code": item_code,
                        "qty": remaining_pkg_qty,
                        "uom": item_uom,
                        "s_warehouse": wip_wh,
                        "is_finished_item": 0,
                    }
                    if pkg_batch_no:
                        row["batch_no"] = pkg_batch_no
                        row["use_serial_batch_fields"] = 1
                    se.append("items", row)
                elif remaining_pkg_qty < -QTY_EPSILON:
                    frappe.log_error(
                        title="Packaging Over-Consumption",
                        message=(
                            f"Packaging item over-consumed for WO {wo_name}\n"
                            f"Item: {item_code}" + (f" Batch: {pkg_batch_no}" if pkg_batch_no else "") + "\n"
                            f"Entered: {qty:.4f}\n"
                            f"Already consumed: {already_consumed_pkg_qty:.4f}"
                        ),
                    )

        # Scrap row for rejected output. When the production item is
        # batch-tracked the scrap row must carry the same batch_no as the
        # finished item, otherwise ERPNext fails Stock Entry submission with
        # "Batch No is required for Item …".
        if split["reject"] > 0:
            scrap_row = {
                "item_code": wo.production_item,
                "qty": split["reject"],
                "uom": uom,
                "is_scrap_item": 1,
                "t_warehouse": scrap_wh,
            }
            if has_batch and batch_no:
                scrap_row["batch_no"] = batch_no
                scrap_row["use_serial_batch_fields"] = 1
            se.append("items", scrap_row)

        _apply_pre_consumed_cost_to_finished_item(se, wo_name, split["good"])

        se.flags.ignore_permissions = True
        se.insert()
        se.submit()

        if split["reject"] > 0:
            current_rejects = float(wo.get("custom_rejects_qty") or 0)
            wo.db_set("custom_rejects_qty", current_rejects + split["reject"], commit=False)

        frappe.db.set_value(
            "Work Order",
            wo_name,
            {
                "status": "Completed",
                "actual_end_date": frappe.utils.now_datetime(),
                "custom_production_ended": 0,
            },
        )

        wo.reload()
        wo.add_comment("Info", _("Production closed: Good={0:.2f}, Rejects={1:.2f}").format(
            split["good"], split["reject"]
        ))
        wo.flags.ignore_permissions = True
        wo.save()
    except frappe.ValidationError:
        raise
    except Exception as e:
        frappe.log_error(
            title="Close Production Error",
            message=f"Failed to close production for {wo_name}: {str(e)}",
        )
        frappe.throw(_("Failed to close production for {0}: {1}").format(wo_name, str(e)))


@frappe.whitelist()
def close_production(groups: str = None, lines: str = None,
                     good_qty: float = None, reject_qty: float = 0,
                     batch_no: str = None, packaging_usage: str = None):
    """
    Close ended work orders for the given lines, grouped by finished product.

    Each product is closed independently so that:
      - good/reject totals only aggregate WOs of the same product,
      - each product carries its own batch number,
      - packaging is scoped to that product's BOMs.

    Args:
        groups: JSON array, one entry per product:
            [{
                "production_item": str,
                "good_qty": float,
                "reject_qty": float,
                "batch_no": "AAA-000",
                "packaging_usage": [{"item_code", "qty", "batch_no"}, ...]
            }, ...]
        lines: JSON array of line names to scope ended-WO lookup.

        good_qty/reject_qty/batch_no/packaging_usage: legacy single-product
            signature, retained only so old clients keep working. New callers
            should pass `groups`.
    """
    _require_roles(ROLES_OPERATOR)

    line_list = []
    if lines:
        try:
            line_list = json.loads(lines) if isinstance(lines, str) else lines
        except Exception:
            pass

    group_list = []
    if groups:
        try:
            group_list = json.loads(groups) if isinstance(groups, str) else groups
        except Exception:
            frappe.throw(_("Invalid groups payload"))
    elif good_qty is not None:
        # Legacy single-product call: synthesize one group.
        legacy_pkg = []
        if packaging_usage:
            try:
                legacy_pkg = json.loads(packaging_usage) if isinstance(packaging_usage, str) else packaging_usage
            except Exception:
                legacy_pkg = []
        group_list = [{
            "production_item": None,  # resolved below from first ended WO
            "good_qty": good_qty,
            "reject_qty": reject_qty,
            "batch_no": batch_no,
            "packaging_usage": legacy_pkg,
        }]

    if not group_list:
        frappe.throw(_("No production groups provided"))

    # Parse + validate each group; collect ended WOs.
    prepared = []
    all_ended_wos = []
    seen_batch_per_item = {}

    for g in group_list:
        production_item = g.get("production_item")
        good = float(g.get("good_qty") or 0)
        reject = float(g.get("reject_qty") or 0)
        bno = (g.get("batch_no") or "").strip() or None
        pkg = g.get("packaging_usage") or []

        if good <= 0:
            label = production_item or _("(unspecified item)")
            frappe.throw(_("Good quantity must be greater than zero for {0}").format(label))
        if reject < 0:
            frappe.throw(_("Rejects cannot be negative"))
        if not bno:
            label = production_item or _("(unspecified item)")
            frappe.throw(_("Batch number is required for {0}").format(label))
        _validate_batch_code_format(bno)

        # Each finished item must own its batch_no. Two different items
        # cannot share the same batch_id (it would clash on Batch.name).
        if bno in seen_batch_per_item and production_item and seen_batch_per_item[bno] != production_item:
            frappe.throw(_(
                "Batch {0} is assigned to both {1} and {2}. "
                "Each finished product needs a unique batch number."
            ).format(bno, seen_batch_per_item[bno], production_item))
        if production_item:
            seen_batch_per_item[bno] = production_item

        filters = {
            "custom_production_ended": 1,
            "status": ["!=", "Completed"],
        }
        if production_item:
            filters["production_item"] = production_item
        if line_list:
            filters["custom_factory_line"] = ["in", line_list]

        ended_wos = frappe.get_all(
            "Work Order",
            filters=filters,
            fields=["name", "qty", "production_item", "company", "bom_no",
                    "fg_warehouse", "wip_warehouse", "custom_factory_line"],
            order_by="creation asc",
        )
        if line_list:
            ended_wos = [
                wo for wo in ended_wos
                if _line_for_work_order(wo["name"]) in line_list
            ]
        if not ended_wos:
            label = production_item or _("the specified lines")
            frappe.throw(_("No ended work orders found for {0}").format(label))

        # Legacy single-group call: backfill production_item for batch tracking.
        if not production_item:
            items_in_set = {wo["production_item"] for wo in ended_wos}
            if len(items_in_set) > 1:
                frappe.throw(_(
                    "Multiple finished products are pending close ({0}). "
                    "Use the per-product Close Production dialog so each gets its own batch."
                ).format(", ".join(sorted(items_in_set))))
            production_item = ended_wos[0]["production_item"]
            seen_batch_per_item[bno] = production_item

        # Pre-validate scrap warehouse before booking anything when rejects exist.
        if reject > 0:
            for wo_data in ended_wos:
                if not _default_line_scrap(wo_data["name"]):
                    line = _line_for_work_order(wo_data["name"]) or "?"
                    frappe.throw(_(
                        "Scrap warehouse is not configured for line {0} (Work Order {1}). "
                        "Set scrap_warehouse in Factory Settings → Line Warehouse Map before "
                        "closing production with rejects."
                    ).format(line, wo_data["name"]))

        prepared.append({
            "production_item": production_item,
            "good_qty": good,
            "reject_qty": reject,
            "batch_no": bno,
            "packaging_items": pkg,
            "ended_wos": ended_wos,
        })
        all_ended_wos.extend(ended_wos)

    # Single Factory-Settings validation across everything being closed.
    _validate_close_production(line_list, all_ended_wos)

    completed_wos = []
    for entry in prepared:
        splits = _calculate_proportional_split(
            entry["ended_wos"], entry["good_qty"], entry["reject_qty"], entry["packaging_items"],
        )
        for wo_data in entry["ended_wos"]:
            _close_single_wo(wo_data, splits[wo_data["name"]], entry["batch_no"])
            completed_wos.append(wo_data["name"])

    return {
        "success": True,
        "message": f"Successfully closed production for {len(completed_wos)} work order(s)",
        "completed_wos": completed_wos,
    }

@frappe.whitelist()
def print_label(carton_qty, template: Optional[str] = None, printer: Optional[str] = None,
                work_order: Optional[str] = None, job_card: Optional[str] = None):
    """
    Create label record and return print information for client-side printing.
    The label record is kept for audit trail, but printing happens on the client.
    
    Args:
        carton_qty: Quantity to print on the label
        template: Label template name (defaults to Factory Settings)
        printer: DEPRECATED - Kept for backward compatibility only, not used for printing
        work_order: Work Order name
        job_card: Job Card name (will resolve to work_order if provided)
    
    Returns:
        dict: Contains print_url, doctype, docname, print_format, and label_record
    """
    _require_roles(ROLES_OPERATOR)

    if job_card and not work_order:
        work_order = frappe.db.get_value("Job Card", job_card, "work_order")
    if not work_order:
        frappe.throw(_("Missing work_order / job_card"))

    wo = frappe.get_doc("Work Order", work_order)
    if not _is_fg(wo.production_item):
        frappe.throw(_("Label printing allowed only for finished goods"))

    fs = _fs()
    # Try default_fg_label_print_format first (for FG carton labels), then fall back to default_label_print_format and default_label_template for backward compatibility
    template = template or getattr(fs, "default_fg_label_print_format", None) or getattr(fs, "default_label_print_format", None) or getattr(fs, "default_label_template", None)

    if not template:
        frappe.throw(_("No label template or print format provided and no default configured in Factory Settings (default_label_print_format or default_label_template)"))

    # Check if template is a Print Format (new method)
    is_print_format = frappe.db.exists("Print Format", template)
    
    # Create audit trail records (Label Record for history)
    label_record = None
    if frappe.db.exists("DocType", "Label Record"):
        label_record = frappe.new_doc("Label Record")
        label_record.label_template = template
        label_record.template_engine = "Jinja" if is_print_format else "Template"
        label_record.payload = f"Print Format: {template}" if is_print_format else ""
        label_record.payload_hash = hashlib.sha256(f"{template}_{carton_qty}_{work_order}".encode("utf-8")).hexdigest()
        label_record.quantity = carton_qty
        label_record.item_code = wo.production_item
        label_record.item_name = wo.item_name
        label_record.batch_no = wo.get("batch_no")
        label_record.append("sources", {
            "source_doctype": "Work Order",
            "source_docname": wo.name,
        })
        label_record.flags.ignore_permissions = True
        label_record.insert()

        if frappe.db.exists("DocType", "Label Print Job"):
            print_job = frappe.new_doc("Label Print Job")
            print_job.label_record = label_record.name
            print_job.quantity = carton_qty
            print_job.status = "Queued"
            print_job.requested_by = frappe.session.user
            print_job.requested_at = frappe.utils.now_datetime()
            print_job.flags.ignore_permissions = True
            print_job.insert()

    # Create Packed Carton record for tracking
    if frappe.db.exists("DocType", "Packed Carton"):
        pc = frappe.new_doc("Packed Carton")
        pc.work_order = wo.name
        pc.item_code = wo.production_item
        pc.batch_no = wo.get("batch_no")
        pc.qty = carton_qty
        pc.label_template = template
        pc.flags.ignore_permissions = True
        pc.insert()
    
    # Return print URL for client-side printing
    print_url = frappe.utils.get_url(
        f"/printview?doctype=Work%20Order&name={frappe.utils.quote(work_order)}&format={frappe.utils.quote(template)}&carton_qty={carton_qty}&trigger_print=1"
    )
    
    # Get silent printing settings
    enable_silent_printing = getattr(fs, "enable_silent_printing", False)
    default_label_printer = get_label_printer(fs)
    
    return {
        "success": True,
        "label_record": label_record.name if label_record else None,
        "print_url": print_url,
        "doctype": "Work Order",
        "docname": work_order,
        "print_format": template,
        "enable_silent_printing": enable_silent_printing,
        "printer_name": default_label_printer
    }


@frappe.whitelist()
def print_pallet_label(item_code: str, pallet_qty: float, pallet_type: str, 
                       work_orders: str, template: Optional[str] = None,
                       carton_qty: Optional[float] = None):
    """
    Create pallet label record and return print information for client-side printing.
    The label record is kept for audit trail, but printing happens on the client.
    
    Args:
        item_code: Item code for the pallet
        pallet_qty: Quantity to print on the pallet label
        pallet_type: Pallet UOM type (e.g., "EURO 1")
        work_orders: JSON string list of Work Order names
        template: Label template/print format name (defaults to Factory Settings)
        carton_qty: Total cartons across the work orders. When provided, the
            cartons are split across pallets so each label shows that pallet's
            carton count instead of the full Work Order quantity.
    
    Returns:
        dict: Contains print_url, print_urls, doctype, docname, print_format, label_record, 
              enable_silent_printing, and printer_name
    """
    _require_roles(ROLES_OPERATOR)

    # Parse work_orders JSON string
    try:
        wo_list = json.loads(work_orders) if isinstance(work_orders, str) else work_orders
        if not isinstance(wo_list, list):
            wo_list = [wo_list]
    except (json.JSONDecodeError, TypeError):
        wo_list = []
    
    if not wo_list:
        frappe.throw(_("At least one work order is required"))
    
    # Use first work order for traceability
    first_work_order = wo_list[0]
    
    # Validate that the first work order exists
    if not frappe.db.exists("Work Order", first_work_order):
        frappe.throw(_("Work Order {0} not found").format(first_work_order))

    fs = _fs()
    # Try default_fg_label_print_format first (for FG pallet labels), then fall back to 
    # default_label_print_format and default_label_template for backward compatibility
    template = template or getattr(fs, "default_fg_label_print_format", None) or \
               getattr(fs, "default_label_print_format", None) or \
               getattr(fs, "default_label_template", None)

    if not template:
        frappe.throw(_("No label template or print format provided and no default configured in Factory Settings (default_fg_label_print_format, default_label_print_format or default_label_template)"))

    # Check if template is a Print Format (new method)
    is_print_format = frappe.db.exists("Print Format", template)
    
    # Get item details
    item_details = frappe.db.get_value("Item", item_code, ["item_name"], as_dict=True)
    item_name = item_details.get("item_name") if item_details else item_code
    
    # Create audit trail record (Label Record for history)
    label_record = None
    if frappe.db.exists("DocType", "Label Record"):
        label_record = frappe.new_doc("Label Record")
        label_record.label_template = template
        label_record.template_engine = "Jinja" if is_print_format else "Template"
        
        # Store pallet info in payload
        payload_info = {
            "pallet_type": pallet_type,
            "carton_qty": flt(carton_qty) or None,
            "work_orders": wo_list,
            "print_format": template if is_print_format else None
        }
        label_record.payload = json.dumps(payload_info)
        label_record.payload_hash = hashlib.sha256(
            f"{template}_{pallet_qty}_{item_code}_{pallet_type}".encode("utf-8")
        ).hexdigest()
        
        label_record.quantity = pallet_qty
        label_record.item_code = item_code
        label_record.item_name = item_name
        
        # Populate sources child table for multi-WO support
        for wo_name in wo_list:
            label_record.append("sources", {
                "source_doctype": "Work Order",
                "source_docname": wo_name,
            })
        
        label_record.flags.ignore_permissions = True
        label_record.insert()

        # Create Label Print Job for audit trail
        if frappe.db.exists("DocType", "Label Print Job"):
            print_job = frappe.new_doc("Label Print Job")
            print_job.label_record = label_record.name
            print_job.quantity = pallet_qty
            print_job.status = "Queued"
            print_job.requested_by = frappe.session.user
            print_job.requested_at = frappe.utils.now_datetime()
            print_job.flags.ignore_permissions = True
            print_job.insert()
    
    # Get silent printing settings
    enable_silent_printing = getattr(fs, "enable_silent_printing", False)
    default_label_printer = get_label_printer(fs)

    base_url = _generate_print_url("Work Order", first_work_order, template)
    pallet_type_q = frappe.utils.quote(pallet_type)

    def _fmt(n):
        n = flt(n)
        return int(n) if n == int(n) else n

    # Split the cartons across pallets so each label shows the cartons on THAT
    # pallet, not the full Work Order quantity. Full pallets carry
    # ceil(carton_qty / pallet_qty) cartons; the last pallet carries the
    # remainder. e.g. 1000 cartons over 15.385 pallets -> 15 labels of 65 + 1
    # of 25. The FG print format reads carton_qty from the query string.
    cq = flt(carton_qty)
    quantities = []
    if cq > 0 and flt(pallet_qty) > 0:
        cartons_per_pallet = math.ceil(round(cq / flt(pallet_qty), 6))
        if cartons_per_pallet > 0:
            full_pallets = int(cq // cartons_per_pallet)
            quantities = [cartons_per_pallet] * full_pallets
            remainder = cq - full_pallets * cartons_per_pallet
            if remainder > 1e-6:
                quantities.append(remainder)

    if quantities:
        print_urls = [
            f"{base_url}&carton_qty={_fmt(q)}&pallet_qty={pallet_qty}"
            f"&pallet_type={pallet_type_q}"
            for q in quantities
        ]
    else:
        # No carton_qty supplied: keep legacy one-identical-URL-per-pallet.
        legacy_url = f"{base_url}&pallet_qty={pallet_qty}&pallet_type={pallet_type_q}"
        print_urls = [legacy_url] * max(1, math.ceil(flt(pallet_qty)))

    print_url = print_urls[0]
    
    return {
        "success": True,
        "label_record": label_record.name if label_record else None,
        "print_url": print_url,
        "print_urls": print_urls,  # One URL per pallet copy
        "doctype": "Work Order",
        "docname": first_work_order,
        "print_format": template,
        "enable_silent_printing": enable_silent_printing,
        "printer_name": default_label_printer
    }


def _create_label_print_job(label_record, printer, quantity, reason_code=None, parent_print_job=None):
    if not frappe.db.exists("DocType", "Label Print Job"):
        return None

    print_job = frappe.new_doc("Label Print Job")
    print_job.label_record = label_record.name
    print_job.quantity = quantity
    print_job.printer = printer
    print_job.status = "Queued"
    print_job.requested_by = frappe.session.user
    print_job.requested_at = frappe.utils.now_datetime()
    print_job.reason_code = reason_code
    print_job.parent_print_job = parent_print_job
    print_job.flags.ignore_permissions = True
    print_job.insert()
    return print_job


@frappe.whitelist()
def list_label_records(work_order: str):
    _require_roles(ROLES_OPERATOR)

    if not frappe.db.exists("DocType", "Label Record"):
        return []

    # Query via child table to find labels linked to ANY of the work orders.
    # Source rows tagged 'combined-into:%' represent labels that were merged
    # into an aggregate record; skip them so operators can't re-select an
    # already-consumed original (which would double-count its quantity).
    records = frappe.db.sql("""
        SELECT DISTINCT
            lr.name,
            lr.label_template,
            lr.quantity,
            lr.item_code,
            lr.item_name,
            lr.batch_no,
            lr.creation
        FROM `tabLabel Record` lr
        INNER JOIN `tabLabel Record Source` lrs ON lrs.parent = lr.name
        WHERE lrs.source_doctype = 'Work Order'
            AND lrs.source_docname = %(work_order)s
            AND (lrs.source_status IS NULL
                 OR lrs.source_status = ''
                 OR lrs.source_status NOT LIKE 'combined-into:%%')
        ORDER BY lr.creation DESC
        LIMIT 20
    """, {"work_order": work_order}, as_dict=True)

    return records


def _generate_print_url(source_doctype: str, source_docname: str, print_format: str, row_name: str = None) -> str:
    """
    Helper function to generate print URL for a document.
    
    Args:
        source_doctype: DocType of the source document
        source_docname: Name of the source document
        print_format: Print format name
        row_name: Optional row name for child table items (e.g., Stock Entry Detail)
    
    Returns:
        Full print URL
    """
    url = f"/printview?doctype={frappe.utils.quote(source_doctype)}&name={frappe.utils.quote(source_docname)}&format={frappe.utils.quote(print_format)}"
    if row_name:
        url += f"&row_name={frappe.utils.quote(row_name)}"
    url += "&trigger_print=1"
    return frappe.utils.get_url(url)


@frappe.whitelist()
def print_label_record(label_record: str, printer: Optional[str] = None, quantities=None, reason_code: Optional[str] = None):
    """
    Reprint or split a label record. Returns print URLs for client-side printing.
    
    Args:
        label_record: Name of the Label Record to reprint
        printer: OPTIONAL - Only used for audit trail in Print Jobs, not for actual printing
        quantities: Optional list of quantities for split printing (defaults to original quantity)
        reason_code: Reason for reprinting (e.g., 'reprint', 'split', 'damaged')
    
    Returns:
        dict: Contains label_record, jobs (print job names), print_urls, doctype, docname, print_format
    """
    _require_roles(ROLES_OPERATOR)

    if not frappe.db.exists("DocType", "Label Record"):
        frappe.throw(_("Label Record is not enabled."))

    record = frappe.get_doc("Label Record", label_record)

    raw_quantities = quantities or [record.quantity]
    if isinstance(raw_quantities, str):
        raw_quantities = json.loads(raw_quantities)
    if not isinstance(raw_quantities, (list, tuple)):
        raw_quantities = [raw_quantities]

    cleaned_quantities = [flt(qty) for qty in raw_quantities if flt(qty) > 0]
    if not cleaned_quantities:
        frappe.throw(_("No valid quantities provided."))

    # Get first source document for compatibility
    first_source = record.sources[0] if (record.sources and len(record.sources) > 0) else None
    source_doctype = first_source.source_doctype if first_source else None
    source_docname = first_source.source_docname if first_source else None

    # Check if the label_template is a Print Format (new method)
    is_print_format = frappe.db.exists("Print Format", record.label_template)
    
    # Create print jobs for audit trail (only if printer is provided)
    fs = _fs()
    target_printer = printer or get_label_printer(fs)
    
    jobs = []
    print_urls = []
    
    # Special handling for Stock Entry with multiple items when reprinting (not splitting)
    if (source_doctype == "Stock Entry" and 
        not quantities and 
        source_docname):
        # When reprinting a Stock Entry Label Record, print all items in the Stock Entry
        se_doc = frappe.get_doc("Stock Entry", source_docname)
        if se_doc.items and len(se_doc.items) > 1:
            # Multiple items: generate one print URL per item
            for item in se_doc.items:
                if target_printer:
                    jobs.append(_create_label_print_job(record, target_printer, item.qty, reason_code=reason_code))
                
                # Generate print URL with row_name parameter
                print_urls.append(_generate_print_url(
                    source_doctype,
                    source_docname,
                    record.label_template,
                    row_name=item.name
                ))
        else:
            # Single item or no items: use standard single print URL
            for qty in cleaned_quantities:
                if target_printer:
                    jobs.append(_create_label_print_job(record, target_printer, qty, reason_code=reason_code))
                
                if source_doctype and source_docname:
                    print_urls.append(_generate_print_url(
                        source_doctype,
                        source_docname,
                        record.label_template
                    ))
    else:
        # Standard handling for split printing or non-Stock Entry documents
        for qty in cleaned_quantities:
            if target_printer:
                jobs.append(_create_label_print_job(record, target_printer, qty, reason_code=reason_code))
            
            # Generate print URL for client-side printing
            if source_doctype and source_docname:
                print_urls.append(_generate_print_url(
                    source_doctype,
                    source_docname,
                    record.label_template
                ))

    # Get silent printing settings
    enable_silent_printing = getattr(fs, "enable_silent_printing", False)
    
    return {
        "label_record": record.name,
        "jobs": [job.name for job in jobs if job],
        "print_urls": print_urls,
        "doctype": source_doctype,
        "docname": source_docname,
        "print_format": record.label_template,
        "enable_silent_printing": enable_silent_printing,
        "printer_name": target_printer
    }


@frappe.whitelist()
def combine_label_records(label_records, reason_code: Optional[str] = None, printer: Optional[str] = None):
    """
    Combine two or more Label Records into a single aggregated Label Record and
    return a print URL for the merged label. Mirrors the Split flow in reverse:
    Split keeps one record and prints N copies; Combine takes N records and
    produces one new record with the summed quantity.

    All input records must share the same item_code, label_template and batch_no.
    The new record's `sources` child table is the deduplicated union of the
    inputs' sources, so the combined label appears in Label History for every
    Work Order that fed into it.

    Args:
        label_records: List (or JSON string) of Label Record names to combine.
        reason_code:   Audit reason recorded on the new Label Print Job
                       (defaults to 'combine').
        printer:       Optional printer override for the Print Job audit row.

    Returns:
        dict with the same shape as print_label_record so the client can reuse
        its print-handling code: label_record, jobs, print_urls, doctype,
        docname, print_format, enable_silent_printing, printer_name, and the
        list of combined source record names.
    """
    _require_roles(ROLES_OPERATOR)

    if not frappe.db.exists("DocType", "Label Record"):
        frappe.throw(_("Label Record is not enabled."))

    raw_names = label_records
    if isinstance(raw_names, str):
        raw_names = json.loads(raw_names)
    if not isinstance(raw_names, (list, tuple)):
        frappe.throw(_("label_records must be a list of Label Record names."))

    # Preserve order while removing duplicates
    seen = set()
    names = []
    for n in raw_names:
        if not n or n in seen:
            continue
        seen.add(n)
        names.append(n)

    if len(names) < 2:
        frappe.throw(_("Select at least two Label Records to combine."))

    records = [frappe.get_doc("Label Record", n) for n in names]

    first = records[0]
    for rec in records[1:]:
        if (rec.item_code or "") != (first.item_code or ""):
            frappe.throw(_("All selected labels must be for the same Item (got {0} and {1}).")
                         .format(first.item_code, rec.item_code))
        if (rec.label_template or "") != (first.label_template or ""):
            frappe.throw(_("All selected labels must use the same Label Template (got {0} and {1}).")
                         .format(first.label_template, rec.label_template))
        if (rec.batch_no or "") != (first.batch_no or ""):
            frappe.throw(_("All selected labels must share the same Batch (got {0} and {1}).")
                         .format(first.batch_no or "-", rec.batch_no or "-"))

    total_qty = sum(flt(rec.quantity) for rec in records)
    if total_qty <= 0:
        frappe.throw(_("Combined quantity must be greater than zero."))

    is_print_format = frappe.db.exists("Print Format", first.label_template)

    combined = frappe.new_doc("Label Record")
    combined.label_template = first.label_template
    combined.template_engine = first.template_engine or ("Jinja" if is_print_format else "Template")

    payload_info = {
        "combined_from": names,
        "original_quantities": [flt(rec.quantity) for rec in records],
        "reason_code": reason_code or "combine",
    }
    combined.payload = json.dumps(payload_info)
    combined.payload_hash = hashlib.sha256(
        f"combine_{first.label_template}_{first.item_code}_{first.batch_no or ''}_{total_qty}_{'|'.join(names)}".encode("utf-8")
    ).hexdigest()

    combined.quantity = total_qty
    combined.item_code = first.item_code
    combined.item_name = first.item_name
    combined.batch_no = first.batch_no

    # Union the source documents from every input record, preserving order
    seen_sources = set()
    for rec in records:
        for src in (rec.sources or []):
            key = (src.source_doctype, src.source_docname)
            if not src.source_doctype or not src.source_docname or key in seen_sources:
                continue
            seen_sources.add(key)
            combined.append("sources", {
                "source_doctype": src.source_doctype,
                "source_docname": src.source_docname,
            })

    combined.flags.ignore_permissions = True
    combined.insert()

    # Mark every source row on the inputs as consumed by this combine so they
    # stop appearing in Label History — otherwise an operator could pick an
    # original plus the aggregate and double-count the original's quantity.
    consumed_marker = f"combined-into:{combined.name}"
    for rec in records:
        for src in (rec.sources or []):
            if not src.name:
                continue
            frappe.db.set_value(
                "Label Record Source",
                src.name,
                "source_status",
                consumed_marker,
                update_modified=False,
            )

    fs = _fs()
    target_printer = printer or get_label_printer(fs)

    first_source = combined.sources[0] if combined.sources else None
    source_doctype = first_source.source_doctype if first_source else None
    source_docname = first_source.source_docname if first_source else None

    # Detect label flavor from the inputs' payload so we pass the same quantity
    # query parameter the originating print path used (carton_qty vs pallet_qty),
    # which is the only quantity the print format actually receives.
    is_pallet_label = False
    pallet_type = None
    try:
        first_payload = json.loads(first.payload) if first.payload else {}
        if isinstance(first_payload, dict) and first_payload.get("pallet_type"):
            is_pallet_label = True
            pallet_type = first_payload.get("pallet_type")
    except (TypeError, ValueError):
        pass

    jobs = []
    print_urls = []

    if target_printer:
        jobs.append(_create_label_print_job(
            combined,
            target_printer,
            total_qty,
            reason_code=reason_code or "combine",
        ))

    if source_doctype and source_docname:
        url = _generate_print_url(
            source_doctype,
            source_docname,
            combined.label_template,
        )
        if is_pallet_label:
            url = f"{url}&pallet_qty={total_qty}&pallet_type={frappe.utils.quote(pallet_type or '')}"
        else:
            url = f"{url}&carton_qty={total_qty}"
        print_urls.append(url)

    enable_silent_printing = getattr(fs, "enable_silent_printing", False)

    return {
        "label_record": combined.name,
        "combined_from": names,
        "combined_quantity": total_qty,
        "jobs": [job.name for job in jobs if job],
        "print_urls": print_urls,
        "doctype": source_doctype,
        "docname": source_docname,
        "print_format": combined.label_template,
        "enable_silent_printing": enable_silent_printing,
        "printer_name": target_printer,
    }


# ============================================================
# Small helpers used by UI (replace client get_list)
# ============================================================

@frappe.whitelist()
def list_workstations():
    """Deprecated name; now returns Factory Sections for Operator Hub."""
    _require_roles(["Factory Operator", "Production Manager"])
    target_dt = "Factory Line" if frappe.db.exists("DocType", "Factory Line") else "Workstation"
    rows = frappe.get_all(target_dt, fields=["name"], order_by="name asc", limit=500)
    return [r.name for r in rows]

@frappe.whitelist()
def get_materials_snapshot(work_order: str):
    """
    Get materials required, transferred, and consumed for a Work Order.
    
    Returns detailed breakdown:
    - Required: From BOM
    - Transferred: Via START button (Material Transfer for Manufacture)
    - Consumed: Via LOAD button (Material Consumption for Manufacture)
    - Remaining: Required - (Transferred + Consumed)
    """
    _require_roles(["Factory Operator", "Stores User", "Production Manager"])

    wo = frappe.get_doc("Work Order", work_order)
    if not wo.get("bom_no"):
        return {"ok": False, "msg": "Work Order has no BOM", "rows": [], "scans": []}

    bom = frappe.get_doc("BOM", wo.bom_no)
    bom_qty = float(bom.get("quantity") or 1) or 1
    wo_qty = float(wo.get("qty") or 0)
    factor = wo_qty / bom_qty if bom_qty else 1.0

    rows = []
    for it in bom.items:
        required = float(it.qty or 0) * factor
        rows.append({
            "item_code": it.item_code,
            "item_name": it.item_name or "",
            "uom": (it.stock_uom or it.uom or ""),
            "required": required,
            "transferred": 0.0,
            "consumed": 0.0,
            "remain": required,
        })

    # Get transferred quantities (from START button)
    transferred = frappe.db.sql("""
        SELECT sed.item_code, SUM(sed.qty) as qty
        FROM `tabStock Entry` se
        JOIN `tabStock Entry Detail` sed ON sed.parent = se.name
        WHERE se.docstatus = 1
          AND se.work_order = %s
          AND se.purpose = 'Material Transfer for Manufacture'
          AND sed.t_warehouse IS NOT NULL
        GROUP BY sed.item_code
    """, (work_order,), as_dict=True)

    # Get consumed quantities (from LOAD button)
    consumed = frappe.db.sql("""
        SELECT sed.item_code, SUM(sed.qty) as qty
        FROM `tabStock Entry` se
        JOIN `tabStock Entry Detail` sed ON sed.parent = se.name
        WHERE se.docstatus = 1
          AND se.work_order = %s
          AND se.purpose = 'Material Consumption for Manufacture'
          AND sed.is_finished_item = 0
          AND sed.is_scrap_item = 0
        GROUP BY sed.item_code
    """, (work_order,), as_dict=True)

    transferred_map = {r.item_code: float(r.qty or 0) for r in transferred}
    consumed_map = {r.item_code: float(r.qty or 0) for r in consumed}

    for row in rows:
        item = row["item_code"]
        row["transferred"] = transferred_map.get(item, 0.0)
        row["consumed"] = consumed_map.get(item, 0.0)
        row["remain"] = row["required"] - row["transferred"] - row["consumed"]

    scans = frappe.db.sql("""
        SELECT sed.item_code, sed.batch_no, sed.qty, sed.uom,
               se.posting_date, se.posting_time
        FROM `tabStock Entry` se
        JOIN `tabStock Entry Detail` sed ON sed.parent = se.name
        WHERE se.docstatus = 1
          AND se.work_order = %s
          AND se.purpose = 'Material Consumption for Manufacture'
          AND sed.is_finished_item = 0
        ORDER BY se.creation DESC
        LIMIT 12
    """, (work_order,), as_dict=True)

    return {"ok": True, "wo": wo.name, "rows": rows, "scans": scans}

@frappe.whitelist()
def parse_scan(code: str):
    """
    Parse a scanned barcode into item/batch/qty without moving any stock.

    The returned `barcode_qty` is the quantity embedded in the barcode (0 when
    the barcode carries none). It is informational only — for an aggregated
    Storekeeper label it may cover several Work Orders, so callers must NOT
    consume it directly; the operator confirms the quantity to consume.
    """
    out = _parse_gs1_or_basic(code or "")
    item_code = out.get("item_code")
    if not item_code:
        return {"ok": False, "msg": _("Cannot parse item from code")}
    uom = frappe.db.get_value("Item", item_code, "stock_uom") or "Nos"
    return {
        "ok": True,
        "item_code": item_code,
        "batch_no": out.get("batch_no"),
        "barcode_qty": flt(out.get("qty") or 0),
        "uom": uom,
    }

@frappe.whitelist()
def get_staging_batches(work_order: str, item_code: str):
    """
    Return batches with available stock in the WIP Warehouse for a given item and work order.

    Returns a list of {"batch_no": str, "qty": float, "uom": str}.
    """
    from erpnext.stock.doctype.batch.batch import get_batch_qty as erpnext_get_batch_qty

    line = _line_for_work_order(work_order)
    _staging_wh, wip_wh, _target, _return_wh = _warehouses_for_line(line)
    if not wip_wh:
        return []

    uom = frappe.db.get_value("Item", item_code, "stock_uom") or "Nos"

    has_batch = frappe.db.get_value("Item", item_code, "has_batch_no")
    if has_batch:
        batches = erpnext_get_batch_qty(item_code=item_code, warehouse=wip_wh)
        return [{"batch_no": b["batch_no"], "qty": flt(b["qty"]), "uom": uom} for b in batches if flt(b["qty"]) > 0]
    else:
        bin_qty = frappe.db.get_value(
            "Bin",
            {"warehouse": wip_wh, "item_code": item_code},
            "actual_qty",
        ) or 0
        if float(bin_qty) > 0:
            return [{"batch_no": None, "qty": float(bin_qty), "uom": uom}]
        return []


@frappe.whitelist()
def get_batch_available_qty(work_order: str, item_code: str, batch_no: str):
    """
    Return available quantity for a given item/batch in the WIP Warehouse for
    the work order's line.

    Returns {"qty": float, "uom": str, "warehouse": str}.
    """
    from erpnext.stock.doctype.batch.batch import get_batch_qty as erpnext_get_batch_qty

    line = _line_for_work_order(work_order)
    _staging_wh, wip_wh, _target, _return_wh = _warehouses_for_line(line)
    if not wip_wh:
        return {"qty": 0.0, "uom": "Nos", "warehouse": ""}

    uom = frappe.db.get_value("Item", item_code, "stock_uom") or "Nos"

    if batch_no:
        qty = flt(erpnext_get_batch_qty(batch_no=batch_no, warehouse=wip_wh, item_code=item_code))
    else:
        qty = float(
            frappe.db.get_value(
                "Bin",
                {"warehouse": wip_wh, "item_code": item_code},
                "actual_qty",
            ) or 0
        )

    return {"qty": qty, "uom": uom, "warehouse": wip_wh}


@frappe.whitelist()
def get_manual_load_item_context(work_order: str, item_code: str):
    """
    Return BOM-required, consumed and remaining quantities for a given item on
    a Work Order. Used by the Manual Load dialog to give operators WO-specific
    context alongside the existing WIP availability figure.

    Required qty is computed using the same scaling logic as
    get_materials_snapshot (BOM item qty * WO/BOM factor).

    Consumed qty sums submitted "Material Consumption for Manufacture" Stock
    Entries for this WO/item, ignoring finished/scrap rows.
    """
    _require_roles(["Factory Operator", "Stores User", "Production Manager"])

    item_code = (item_code or "").strip()
    if not work_order or not item_code:
        return {
            "item_code": item_code,
            "uom": "",
            "required_qty": 0.0,
            "consumed_qty": 0.0,
            "remaining_qty": 0.0,
        }

    wo = frappe.get_doc("Work Order", work_order)
    uom = frappe.db.get_value("Item", item_code, "stock_uom") or "Nos"

    required_qty = 0.0
    if wo.get("bom_no"):
        bom = frappe.get_doc("BOM", wo.bom_no)
        bom_qty = float(bom.get("quantity") or 1) or 1
        wo_qty = float(wo.get("qty") or 0)
        factor = wo_qty / bom_qty if bom_qty else 1.0
        for it in bom.items:
            if it.item_code == item_code:
                required_qty += float(it.qty or 0) * factor

    consumed_row = frappe.db.sql("""
        SELECT COALESCE(SUM(sed.qty), 0) AS total
        FROM `tabStock Entry` se
        JOIN `tabStock Entry Detail` sed ON sed.parent = se.name
        WHERE se.docstatus = 1
          AND se.work_order = %s
          AND se.purpose = 'Material Consumption for Manufacture'
          AND sed.item_code = %s
          AND sed.is_finished_item = 0
          AND sed.is_scrap_item = 0
    """, (work_order, item_code))
    consumed_qty = float((consumed_row and consumed_row[0][0]) or 0)

    remaining_qty = max(required_qty - consumed_qty, 0.0)

    return {
        "item_code": item_code,
        "uom": uom,
        "required_qty": required_qty,
        "consumed_qty": consumed_qty,
        "remaining_qty": remaining_qty,
    }


def _post_material_consumption_for_wo(work_order: str, items: list, allow_packaging: bool = True) -> dict:
    """
    Validate and post a single "Material Consumption for Manufacture" Stock
    Entry for `work_order`, with one row per item in `items`.

    Each item dict: {"item_code": str, "batch_no": str|None, "qty": float}.

    Shared by manual_load_materials() and consume_scanned_material() so the
    validation lives in exactly one place. Callers handle their own role checks.

    Per-item validation: Work Order not ended, item exists, item belongs to the
    WO BOM unless it is in a packaging group, and total consumption stays within
    the material_overconsumption_threshold. The Stock Entry consumes from the
    Work Order line WIP warehouse and is linked to the Work Order.

    When allow_packaging is False, items in a packaging group are rejected
    instead of bypassing the BOM-membership check.

    Returns {"ok": True, "msg": str, "stock_entry": str}.
    """
    if not work_order:
        frappe.throw(_("Missing work_order"))

    _assert_not_ended(work_order)

    if not items:
        frappe.throw(_("No items provided"))

    wo = frappe.get_doc("Work Order", work_order)
    # Consume from WIP warehouse (mirrors scan_material behaviour)
    s_wh = _default_line_wip(work_order)
    t_wh = s_wh

    packaging_groups = _packaging_groups_global()

    se = frappe.new_doc("Stock Entry")
    se.purpose = "Material Consumption for Manufacture"
    se.stock_entry_type = "Material Consumption for Manufacture"
    se.company = wo.company
    se.work_order = work_order
    se.from_bom = 1
    se.bom_no = wo.bom_no
    se.fg_completed_qty = flt(wo.qty) - flt(wo.produced_qty)

    for it in items:
        item_code = (it.get("item_code") or "").strip()
        qty = float(it.get("qty") or 0)
        if not item_code or qty <= 0:
            continue

        # Validate item exists
        if not frappe.db.exists("Item", item_code):
            frappe.throw(_("Item {0} does not exist").format(item_code))

        # Check BOM membership or packaging group
        group = (_get_item_group(item_code) or "").strip().lower()
        is_packaging = group in packaging_groups
        if is_packaging and not allow_packaging:
            frappe.throw(_("Packaging item {0} cannot be consumed at material loading").format(item_code))
        if not is_packaging:
            ok, msg = _validate_item_in_bom(work_order, item_code)
            if not ok:
                frappe.throw(msg)

        # Check over-consumption threshold (non-packaging only)
        if not is_packaging:
            bom = frappe.db.get_value("Work Order", work_order, "bom_no")
            wo_qty = float(frappe.db.get_value("Work Order", work_order, "qty") or 0)
            bom_item_qty = frappe.db.sql("""
                SELECT COALESCE(qty_consumed_per_unit, qty, 0) AS qty_per_unit
                FROM `tabBOM Item`
                WHERE parent = %s AND item_code = %s
                LIMIT 1
            """, (bom, item_code), as_dict=True)
            if bom_item_qty:
                bom_required = float(bom_item_qty[0].qty_per_unit) * wo_qty
                already_consumed = frappe.db.sql("""
                    SELECT COALESCE(SUM(sed.qty), 0) AS total
                    FROM `tabStock Entry` se
                    JOIN `tabStock Entry Detail` sed ON sed.parent = se.name
                    WHERE se.docstatus = 1
                      AND se.work_order = %s
                      AND se.purpose = 'Material Consumption for Manufacture'
                      AND sed.item_code = %s
                      AND sed.is_finished_item = 0
                """, (work_order, item_code))[0][0] or 0
                total_after = float(already_consumed) + qty
                fs = _fs()
                threshold_pct = float(getattr(fs, "material_overconsumption_threshold", 150))
                threshold_qty = bom_required * (threshold_pct / 100.0)
                if total_after > threshold_qty:
                    frappe.throw(
                        _("Excessive quantity for {0}: {1:.2f} total (BOM requires {2:.2f}, threshold {3:.0f}%)").format(
                            item_code, total_after, bom_required, threshold_pct
                        )
                    )

        uom = frappe.db.get_value("Item", item_code, "stock_uom") or "Nos"
        batch_no = (it.get("batch_no") or "").strip() or None

        if frappe.db.get_value("Item", item_code, "has_batch_no") and not batch_no:
            frappe.throw(_("Batch number required for {0}").format(item_code))

        item_dict = {
            "item_code": item_code,
            "qty": qty,
            "uom": uom,
            "s_warehouse": s_wh,
            "t_warehouse": t_wh if t_wh else None,
        }
        if batch_no:
            item_dict["batch_no"] = batch_no
            item_dict["use_serial_batch_fields"] = 1

        se.append("items", item_dict)

    if not se.items:
        frappe.throw(_("No valid items to consume"))

    se.flags.ignore_permissions = True
    se.insert()
    se.submit()

    count = len(se.items)
    return {"ok": True, "msg": _("Consumed {0} item(s)").format(count), "stock_entry": se.name}


@frappe.whitelist()
def manual_load_materials(work_order: str, items: str):
    """
    Manually consume materials from WIP warehouse into a Work Order without barcode scanning.

    items: JSON list of {"item_code": str, "batch_no": str|null, "qty": float}

    Creates a single "Material Consumption for Manufacture" Stock Entry with one row per item.
    Returns {"ok": True, "msg": str, "stock_entry": str}.
    """
    _require_roles(ROLES_OPERATOR)

    try:
        item_list = json.loads(items) if isinstance(items, str) else items
    except Exception:
        item_list = []

    allow_packaging = bool(getattr(_fs(), "allow_packaging_at_material_loading", 0))
    return _post_material_consumption_for_wo(work_order, item_list or [], allow_packaging=allow_packaging)


@frappe.whitelist()
def consume_scanned_material(work_order: str, item_code: str, qty,
                             batch_no: str = None, raw_code: str = None):
    """
    Post a single confirmed scanned-material consumption against a Work Order.

    The Operator Hub "Load Materials" scan flow parses a barcode, shows the
    operator a quantity-confirmation dialog, then calls this method with the
    operator-confirmed quantity.

    IMPORTANT: the barcode quantity is never consumed here. A Storekeeper label
    may carry an aggregate quantity staged for several Work Orders, so only the
    confirmed `qty` is posted against this Work Order.

    Validation/posting is shared with Manual Load via
    _post_material_consumption_for_wo().

    Returns {"ok": True, "msg": str, "stock_entry": str}.
    """
    _require_roles(ROLES_OPERATOR)

    item_code = (item_code or "").strip()
    if not work_order or not item_code:
        frappe.throw(_("Missing work_order or item_code"))

    qty = flt(qty)
    if qty <= 0:
        frappe.throw(_("Quantity to consume must be greater than zero"))

    _assert_not_ended(work_order)

    # Duplicate guard: reject only a label already consumed for this WO. The
    # cache key is set *after* a successful post (below), so a cancelled or
    # failed confirmation never blocks a re-scan of the same label.
    if _scan_already_consumed(work_order, raw_code):
        frappe.throw(_("This label was already consumed for this Work Order"))

    result = _post_material_consumption_for_wo(
        work_order,
        [{"item_code": item_code, "batch_no": (batch_no or "").strip() or None, "qty": qty}],
    )

    _mark_scan_consumed(work_order, raw_code)

    result["msg"] = _("Consumed {0} of {1}").format(qty, item_code)
    return result


@frappe.whitelist()
def return_materials(job_card: Optional[str] = None, work_order: Optional[str] = None, lines: Optional[str] = None):
    """
    Return leftover materials from line WIP back to staging/central.
    lines = JSON list of {item_code, qty, batch_no?}
    """
    _require_roles(["Factory Operator", "Stores User", "Production Manager"])

    if job_card and not work_order:
        work_order = frappe.db.get_value("Job Card", job_card, "work_order")
    if not work_order:
        frappe.throw(_("Missing work_order / job_card"))

    try:
        items = json.loads(lines or "[]")
    except Exception:
        items = []
    if not items:
        frappe.throw(_("No items to return"))

    s_wh = _default_line_wip(work_order) or frappe.db.get_single_value("Stock Settings", "default_warehouse")
    t_wh = _default_line_staging(work_order) or frappe.db.get_single_value("Stock Settings", "default_warehouse")

    se = frappe.new_doc("Stock Entry")
    se.purpose = "Material Transfer"
    se.set_stock_entry_type()
    se.work_order = work_order

    for it in items:
        item_code = (it.get("item_code") or "").strip()
        qty = float(it.get("qty") or 0)
        if not item_code or qty <= 0:
            continue
        row = {
            "item_code": item_code,
            "qty": qty,
            "uom": frappe.db.get_value("Item", item_code, "stock_uom") or "Nos",
            "s_warehouse": s_wh,
            "t_warehouse": t_wh,
        }
        if it.get("batch_no"):
            row["batch_no"] = it["batch_no"]
        se.append("items", row)

    if not se.items:
        frappe.throw(_("No valid items to transfer"))

    se.flags.ignore_permissions = True
    se.insert()
    se.submit()
    return {"ok": True, "stock_entry": se.name}


@frappe.whitelist()
def get_wip_inventory(line: Optional[str] = None):
    """
    Get current WIP inventory for a Factory Section.
    Returns list of items with item_code, item_name, qty, batch_no, uom.
    """
    _require_roles(["Factory Operator", "Stores User", "Production Manager"])
    
    if not line:
        frappe.throw(_("Missing line parameter"))
    
    # Get WIP warehouse for the line
    _staging_wh, wip_wh, _target_wh, _return_wh = _warehouses_for_line(line)
    
    if not wip_wh:
        frappe.throw(_("WIP warehouse not configured for line {0}").format(line))
    
    # Query current stock in WIP warehouse
    bins = frappe.get_all(
        "Bin",
        filters={"warehouse": wip_wh, "actual_qty": [">", 0]},
        fields=["item_code", "actual_qty"]
    )
    
    result = []
    for b in bins:
        item_name = frappe.db.get_value("Item", b.item_code, "item_name")
        uom = frappe.db.get_value("Item", b.item_code, "stock_uom") or "Nos"
        
        # Check if item has batch tracking
        has_batch = frappe.db.get_value("Item", b.item_code, "has_batch_no")
        
        if has_batch:
            from erpnext.stock.doctype.batch.batch import get_batch_qty as erpnext_get_batch_qty
            # Use the authoritative ERPNext API to compute net batch quantities
            batches = erpnext_get_batch_qty(item_code=b.item_code, warehouse=wip_wh)
            for batch in (batches or []):
                batch_qty = flt(batch.get("qty"))
                if batch_qty <= 0:
                    continue
                result.append({
                    "item_code": b.item_code,
                    "item_name": item_name,
                    "qty": batch_qty,
                    "batch_no": batch.get("batch_no"),
                    "uom": uom
                })
        else:
            # For non-batch items, just add the total quantity
            result.append({
                "item_code": b.item_code,
                "item_name": item_name,
                "qty": b.actual_qty,
                "batch_no": None,
                "uom": uom
            })
    
    return {"ok": True, "items": result}


@frappe.whitelist()
def return_wip_to_staging(line: Optional[str] = None, items: Optional[str] = None):
    """
    Return WIP materials to staging warehouse without requiring a work order.
    items = JSON list of {item_code, qty, batch_no?}
    """
    _require_roles(["Factory Operator", "Stores User", "Production Manager"])
    
    if not line:
        frappe.throw(_("Missing line parameter"))
    
    try:
        items_list = json.loads(items or "[]")
    except Exception:
        items_list = []
    
    if not items_list:
        frappe.throw(_("No items to return"))
    
    # Get warehouses for the line
    staging_wh, wip_wh, _target_wh, return_wh = _warehouses_for_line(line)
    
    target_wh = return_wh or staging_wh
    if not wip_wh or not target_wh:
        frappe.throw(_("WIP or Return/Staging warehouse not configured for line {0}").format(line))
    
    # Create Stock Entry for Material Transfer
    se = frappe.new_doc("Stock Entry")
    se.purpose = "Material Transfer"
    se.set_stock_entry_type()
    se.custom_factory_line = line
    se.custom_is_end_shift_return = 1
    se.custom_return_received_by_storekeeper = 0
    se.remarks = "End Shift Return — WIP return for line {}".format(line)
    
    for it in items_list:
        item_code = (it.get("item_code") or "").strip()
        qty = float(it.get("qty") or 0)
        if not item_code or qty <= 0:
            continue
        
        row = {
            "item_code": item_code,
            "qty": qty,
            "uom": frappe.db.get_value("Item", item_code, "stock_uom") or "Nos",
            "s_warehouse": wip_wh,
            "t_warehouse": target_wh,
        }
        
        if it.get("batch_no"):
            row["batch_no"] = it["batch_no"]
            row["use_serial_batch_fields"] = 1
        
        se.append("items", row)
    
    if not se.items:
        frappe.throw(_("No valid items to transfer"))
    
    se.flags.ignore_permissions = True
    se.insert()
    se.submit()

    try:
        frappe.publish_realtime(
            event="isnack_pending_end_shift_return_changed",
            message={"stock_entry": se.name, "factory_line": line},
            after_commit=True,
        )
    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            "Failed to publish pending end shift return update",
        )
    
    return {"ok": True, "stock_entry": se.name}


def apply_line_warehouses_to_work_order(doc, method=None):
    """
    Auto-fill Work Order WIP / Target warehouses from Factory Settings → Line Warehouse Map.

    Logic:
      1) Determine the line for this WO:
           - Prefer doc.custom_line (your line field).
           - Else, fall back to the first operation's workstation.
      2) Look up (staging, wip, target, return) from _warehouses_for_line(line).
      3) If we have values:
           - On NEW docs (doc.__islocal), override whatever is there (including
             Manufacturing Settings defaults).
           - On existing Draft docs, only fill if fields are empty.
    """

    # 1) Find the line
    line = getattr(doc, "custom_factory_line", None) or getattr(doc, "custom_line", None)

    if not line and getattr(doc, "bom_no", None):
        line = frappe.db.get_value("BOM", doc.bom_no, "custom_default_factory_line")
        if line and not getattr(doc, "custom_factory_line", None):
            doc.custom_factory_line = line

    if not line and getattr(doc, "operations", None):
        for op in doc.operations:
            ws = getattr(op, "workstation", None)
            if ws:
                line = ws
                break

    if not line:
        return  # nothing to map

    # 2) Get warehouses from Factory Settings → Line Warehouse Map
    _staging, wip, target, _return_wh = _warehouses_for_line(line)
    if not (wip or target):
        return

    is_new = bool(getattr(doc, "__islocal", False))

    # 3) Apply mapping
    # Work-in-Progress Warehouse
    if wip:
        if is_new or not getattr(doc, "wip_warehouse", None):
            doc.wip_warehouse = wip

    # Target / FG Warehouse
    if target:
        if is_new or not getattr(doc, "fg_warehouse", None):
            doc.fg_warehouse = target
