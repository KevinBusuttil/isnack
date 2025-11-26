from __future__ import annotations

import hashlib
import json
from string import Template
from typing import Optional, Tuple

import frappe
from frappe import _

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
            def __getattr__(self, _): return None
        return _Dummy()

def _consume_on_scan() -> bool:
    fs = _fs()
    return bool(int((getattr(fs, "consume_on_scan", None) or 1)))

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
    out = set()
    for r in rows:
        ig = getattr(r, "item_group", None)
        if ig:
            out.add(str(ig).strip().lower())
    return out

def _packaging_groups_global() -> set[str]:
    """From Factory Settings -> Packaging Item Groups (Table MultiSelect)."""
    fs = _fs()
    rows = getattr(fs, "packaging_item_groups", []) or []
    out = set()
    for r in rows:
        ig = getattr(r, "item_group", None)
        if ig:
            out.add(str(ig).strip().lower())
    return out

def _backflush_groups_global() -> set[str]:
    """From Factory Settings -> Backflush Item Groups (Table MultiSelect)."""
    fs = _fs()
    rows = getattr(fs, "backflush_item_groups", []) or []
    out = set()
    for r in rows:
        ig = getattr(r, "item_group", None)
        if ig:
            out.add(str(ig).strip().lower())
    return out

def _warehouses_for_line(line: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """
    Factory Settings -> Line Warehouse Map child table.
    Child rows expected: line (Workstation), staging_warehouse, wip_warehouse
    """
    if not line:
        return None, None
    fs = _fs()
    rows = getattr(fs, "line_warehouse_map", []) or []
    for r in rows:
        if (getattr(r, "line", None) or "").strip().lower() == str(line).strip().lower():
            return (getattr(r, "staging_warehouse", None) or None,
                    getattr(r, "wip_warehouse", None) or None)
    return None, None

# ============================================================
# Generic helpers
# ============================================================

ROLES_OPERATOR = ["Factory Operator", "Operator", "Production Manager"]

def _is_fg(item_code: str) -> bool:
    """Treat sales items as FG by policy (adjust to Item Group if you prefer)."""
    return bool(frappe.db.get_value("Item", item_code, "is_sales_item"))

def _get_item_group(item_code: str) -> Optional[str]:
    return frappe.db.get_value("Item", item_code, "item_group")

def _get_user_line(user: str) -> Optional[str]:
    line = frappe.defaults.get_user_default("manufacturing_line")
    return line or None

def _user_employee(user: str) -> Optional[str]:
    emp = frappe.db.get_value("Employee", {"user_id": user}, "name")
    if emp:
        return emp
    return frappe.db.get_value("User", user, "employee")

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
    if employee:
        return employee
    return _user_employee(frappe.session.user)

def _default_line_staging(work_order: str, *, is_packaging: bool = False) -> Optional[str]:
    line = frappe.db.get_value("Job Card", {"work_order": work_order}, "workstation")
    staging, _wip = _warehouses_for_line(line)
    return staging or frappe.db.get_single_value("Stock Settings", "default_warehouse")

def _default_line_wip(work_order: str) -> Optional[str]:
    line = frappe.db.get_value("Job Card", {"work_order": work_order}, "workstation")
    _staging, wip = _warehouses_for_line(line)
    return wip or frappe.db.get_single_value("Stock Settings", "default_warehouse")

def _validate_item_in_bom(work_order: str, item_code: str) -> Tuple[bool, str]:
    bom = frappe.db.get_value("Work Order", work_order, "bom_no")
    if not bom:
        return False, _("Work Order has no BOM")
    exists = frappe.db.exists("BOM Item", {"parent": bom, "item_code": item_code})
    if not exists:
        return False, _("Item {0} not in BOM {1}").format(item_code, bom)
    return True, "OK"

def _parse_gs1_or_basic(code: str) -> dict:
    out, s = {}, code or ""
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
    if batch: out["batch_no"] = batch
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
        if len(parts) >= 2: out["batch_no"]  = parts[1]
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

    filters = {"docstatus": 1, "status": ["in", ["Not Started", "In Process", "On Hold"]]}
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

    html = f"""
      <div class="d-flex flex-wrap justify-content-between">
        <div><b>{frappe.utils.escape_html(wo.name)}</b> — {frappe.utils.escape_html(wo.item_name)}</div>
        <div><span class="badge {'bg-primary' if is_fg else 'bg-secondary'}">{type_chip}</span></div>
      </div>
      <div>Batch: {frappe.utils.escape_html(batch)}</div>
      <div>Target: {wo.qty} &nbsp; Actual: {actual} &nbsp; Rejects: {rejects} &nbsp; Status: {frappe.utils.escape_html(wo.status)}</div>
      <div class="small text-muted">Operator: {frappe.utils.escape_html(frappe.session.user)}</div>
    """
    return {"html": html}

# ============================================================
# Kiosk helper
# ============================================================

@frappe.whitelist()
def resolve_employee(badge: Optional[str] = None, employee: Optional[str] = None):
    emp = None
    if employee:
        emp = employee
    elif badge:
        emp = _employee_by_badge(badge)
    if not emp:
        return {"ok": False}
    return {
        "ok": True,
        "employee": emp,
        "employee_name": frappe.db.get_value("Employee", emp, "employee_name") or emp,
    }

# ============================================================
# Line queue + card banner
# ============================================================

@frappe.whitelist()
def get_line_queue(line: Optional[str] = None):
    if not line:
        line = _get_user_line(frappe.session.user)

    filters = {
        "docstatus": ["<", 2],
        "status": ["in", ["Open", "Work In Progress", "On Hold"]],
    }
    if line:
        filters["workstation"] = line

    meta = frappe.get_meta("Job Card")
    has_priority = any(df.fieldname == "priority" for df in meta.fields)
    fields = ["name","work_order","operation","workstation","for_quantity","status","modified"]
    if has_priority:
        fields.append("priority")

    order_by = "creation asc"
    if has_priority:
        order_by = "coalesce(priority, 999999), creation asc"

    cards = frappe.get_all(
        "Job Card",
        filters=filters,
        fields=fields,
        order_by=order_by,
        limit=300,
    )

    out = []
    for c in cards:
        wo = frappe.db.get_value("Work Order", c.work_order, ["production_item","item_name","status"], as_dict=True) if c.work_order else {}
        out.append({
            "name": c.name,
            "work_order": c.work_order,
            "operation": c.operation,
            "workstation": c.workstation,
            "for_quantity": c.for_quantity,
            "status": c.status,
            "priority": getattr(c, "priority", None),
            "production_item": (wo or {}).get("production_item"),
            "item_name": (wo or {}).get("item_name"),
            "wo_status": (wo or {}).get("status"),
            "crew_open": _open_log_count(c.name),
            "type": "FG" if (wo and _is_fg(wo.get("production_item"))) else "SF",
        })
    return out

@frappe.whitelist()
def get_card_banner(job_card: str):
    info = _job_card_info(job_card)
    crew = ", ".join([
        frappe.utils.escape_html(
            frappe.db.get_value("Employee", r["employee"], "employee_name") or r["employee"]
        ) for r in info["open_logs"]
    ]) or "-"

    html = f"""
      <div class="d-flex flex-wrap justify-content-between">
        <div><b>{frappe.utils.escape_html(info['name'])}</b> — {frappe.utils.escape_html(info.get('item_name') or '')}</div>
        <div><span class="badge {'bg-primary' if _is_fg(info.get('production_item') or '') else 'bg-secondary'}">{'FG' if _is_fg(info.get('production_item') or '') else 'SF'}</span></div>
      </div>
      <div>WO: {frappe.utils.escape_html(info.get('work_order') or '-')} &nbsp; Op: {frappe.utils.escape_html(info.get('operation') or '-')} &nbsp; Qty: {info.get('for_quantity') or 0}</div>
      <div>Status: {frappe.utils.escape_html(info.get('status') or '-')} &nbsp; Crew (active): {crew}</div>
      <div class="small text-muted">Line: {frappe.utils.escape_html(info.get('workstation') or '-')}</div>
    """
    return {"html": html}

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
        try: jc.db_set("mes_remarks", remarks, commit=False)
        except Exception: pass
    if reason:
        try: jc.db_set("mes_reason", reason, commit=False)
        except Exception: pass

    jc.flags.ignore_permissions = True
    jc.save()
    return True

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

def _post_sfg_consumption(wo: "Work Order", rows: list[dict]):
    """Post Material Consumption for Manufacture for semi-finished items.

    Expects rows like: {"item_code": "SFG10003", "qty": 123.45}.
    We consume from 'Semi-finished - ISN' into the line's WIP (or default warehouse).
    """
    if not rows:
        return

    # Line WIP (target) – fall back to Stock Settings default if not mapped
    t_wh = _default_line_wip(wo.name)
    if not t_wh:
        t_wh = frappe.db.get_single_value("Stock Settings", "default_warehouse")

    # Default SFG source – adjust or make configurable if needed
    default_sfg_wh = "Semi-finished - ISN"

    se = frappe.new_doc("Stock Entry")
    se.company = wo.company
    se.purpose = "Material Consumption for Manufacture"
    se.work_order = wo.name

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
      - Posts either:
          * "Material Consumption for Manufacture" (consume_on_scan = 1), or
          * "Material Transfer for Manufacture"   (consume_on_scan = 0)
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

        # Warehouses from line-map (falls back to Stock Settings default)
        s_wh = parsed.get("warehouse") or _default_line_staging(work_order, is_packaging=is_packaging)
        t_wh = _default_line_wip(work_order)

        # Post either Consumption or Transfer for Manufacture (based on Factory Settings)
        if _consume_on_scan():
            se = frappe.new_doc("Stock Entry")
            se.purpose = "Material Consumption for Manufacture"
            se.work_order = work_order
            se.append("items", {
                "item_code": item_code,
                "qty": qty,
                "uom": uom,
                "s_warehouse": s_wh,
                "batch_no": parsed.get("batch_no"),
            })
            se.flags.ignore_permissions = True
            se.insert()
            se.submit()
            msg_txt = _("Consumed {0} × {1} (Batch {2})").format(qty, item_code, parsed.get("batch_no", "-"))
        else:
            se = frappe.new_doc("Stock Entry")
            se.purpose = "Material Transfer for Manufacture"
            se.work_order = work_order
            se.append("items", {
                "item_code": item_code,
                "qty": qty,
                "uom": uom,
                "s_warehouse": s_wh,
                "t_warehouse": t_wh,
                "batch_no": parsed.get("batch_no"),
            })
            se.flags.ignore_permissions = True
            se.insert()
            se.submit()
            msg_txt = _("Staged {0} × {1} to WIP (Batch {2})").format(qty, item_code, parsed.get("batch_no", "-"))

        return {"ok": True, "msg": msg_txt}

    except Exception:
        frappe.log_error(frappe.get_traceback(), "iSnack scan_material")
        return {"ok": False, "msg": _("Scan failed")}


@frappe.whitelist()
def request_material(item_code, qty, reason=None, job_card: Optional[str] = None, work_order: Optional[str] = None):
    _require_roles(["Stores User", *ROLES_OPERATOR])

    qty = float(qty or 0)
    if qty <= 0:
        frappe.throw(_("Quantity must be positive"))

    if job_card and not work_order:
        work_order = frappe.db.get_value("Job Card", job_card, "work_order")
    if not work_order:
        frappe.throw(_("Missing work_order / job_card"))

    central_wh = frappe.db.get_single_value("Stock Settings", "default_warehouse")
    projected_qty = frappe.db.get_value("Bin", {"warehouse": central_wh, "item_code": item_code}, "projected_qty") or 0
    is_purchase_item = bool(frappe.db.get_value("Item", item_code, "is_purchase_item"))
    mr_type = "Material Transfer" if projected_qty >= qty else ("Purchase" if is_purchase_item else "Material Transfer")

    mr = frappe.new_doc("Material Request")
    mr.material_request_type = mr_type
    mr.schedule_date = frappe.utils.nowdate()
    mr.work_order = work_order
    mr.append("items", {"item_code": item_code, "qty": qty, "schedule_date": mr.schedule_date})
    if reason:
        mr.notes = reason
    mr.flags.ignore_permissions = True
    mr.insert()
    return {"ok": True, "mr": mr.name, "type": mr_type}

@frappe.whitelist()
def set_wo_status(work_order, action, reason=None, remarks=None):
    _require_roles(ROLES_OPERATOR)
    wo = frappe.get_doc("Work Order", work_order)

    updates = {}
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
    _require_roles(ROLES_OPERATOR)

    good = float(good or 0)
    rejects = float(rejects or 0)
    if good <= 0:
        frappe.throw(_("Good quantity must be greater than zero"))
    if rejects < 0:
        frappe.throw(_("Rejects cannot be negative"))

    wo = frappe.get_doc("Work Order", work_order)
    fg_wh = wo.fg_warehouse or frappe.db.get_single_value("Stock Settings", "default_warehouse")
    uom = frappe.db.get_value("Item", wo.production_item, "stock_uom") or "Nos"

    # 1) Manufacture (FG receipt)
    se = frappe.new_doc("Stock Entry")
    se.company = wo.company
    se.purpose = "Manufacture"
    se.work_order = work_order
    se.to_warehouse = fg_wh
    se.fg_completed_qty = good

    se.append("items", {
        "item_code": wo.production_item,
        "qty": good,
        "uom": uom,
        "is_finished_item": 1,
        "t_warehouse": fg_wh,
    })

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
        _post_sfg_consumption(wo, sfg_rows)

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

    wo.add_comment("Info", _("WO FG receipt: Good={0}, Rejects={1}, Remarks={2}").format(good, rejects, (remarks or "")))
    wo.flags.ignore_permissions = True
    wo.save()
    return True

@frappe.whitelist()
def print_label(carton_qty, template: Optional[str] = None, printer: Optional[str] = None,
                work_order: Optional[str] = None, job_card: Optional[str] = None):
    """
    Render ZPL/TSPL from 'Label Template' (preferred) or fall back to 'Print Template'.
    Defaults (template/printer) are taken from Factory Settings if not provided.
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
    template = template or getattr(fs, "default_label_template", None)
    printer  = printer  or getattr(fs, "default_label_printer", None)

    if not template:
        frappe.throw(_("No label template provided and no default set in Factory Settings"))
    if not printer:
        frappe.throw(_("No printer provided and no default set in Factory Settings"))

    tpl = frappe.db.get_value("Label Template", template, "template")
    if not tpl:
        # Fall back to Print Template (if you're still using those)
        tpl = frappe.db.get_value("Print Template", template, "template_body")
    if not tpl:
        frappe.throw(_("Template not found"))

    if "$" in tpl:
        payload = Template(tpl).safe_substitute(
            ITEM=wo.production_item, ITEM_NAME=wo.item_name, WO=wo.name,
            BATCH=wo.get("batch_no") or "", QTY=carton_qty,
        )
    else:
        payload = tpl.format(
            ITEM=wo.production_item, ITEM_NAME=wo.item_name, WO=wo.name,
            BATCH=wo.get("batch_no") or "", QTY=carton_qty,
        )

    frappe.publish_realtime("isnack_print", {"printer": printer, "raw": payload},
                            user=frappe.session.user, after_commit=True)

    if frappe.db.exists("DocType", "Packed Carton"):
        pc = frappe.new_doc("Packed Carton")
        pc.work_order = wo.name
        pc.item_code = wo.production_item
        pc.batch_no = wo.get("batch_no")
        pc.qty = carton_qty
        pc.label_template = template
        pc.flags.ignore_permissions = True
        pc.insert()
    return True

# ============================================================
# Small helpers used by UI (replace client get_list)
# ============================================================

@frappe.whitelist()
def list_workstations():
    _require_roles(["Factory Operator", "Production Manager"])
    rows = frappe.get_all("Workstation", fields=["name"], order_by="name asc", limit=500)
    return [r.name for r in rows]

@frappe.whitelist()
def get_materials_snapshot(work_order: str):
    _require_roles(["Factory Operator", "Stores User", "Production Manager"])

    wo = frappe.get_doc("Work Order", work_order)
    if not wo.get("bom_no"):
        return {"ok": False, "msg": "Work Order has no BOM", "rows": [], "scans": []}

    bom = frappe.get_doc("BOM", wo.bom_no)
    bom_qty = float(bom.get("quantity") or 1) or 1
    wo_qty  = float(wo.get("qty") or 0)
    factor  = wo_qty / bom_qty if bom_qty else 1.0

    rows = []
    for it in bom.items:
        required = float(it.qty or 0) * factor
        rows.append({
            "item_code": it.item_code,
            "item_name": it.item_name or "",
            "uom": (it.stock_uom or it.uom or ""),
            "required": required,
            "issued": 0.0,
            "remain": required,
        })

    issued = frappe.db.sql("""
        select sed.item_code, sum(sed.qty) as qty
        from `tabStock Entry` se
        join `tabStock Entry Detail` sed on sed.parent = se.name
        where se.docstatus=1
          and se.work_order=%s
          and se.purpose in ('Material Consumption for Manufacture','Material Transfer for Manufacture')
        group by sed.item_code
    """, (work_order,), as_dict=True)
    issued_map = {r.item_code: float(r.qty or 0) for r in issued}

    for r in rows:
        iss = issued_map.get(r["item_code"], 0.0)
        r["issued"] = iss
        r["remain"] = max(float(r["required"]) - iss, 0.0)

    scans = frappe.db.sql("""
        select sed.item_code, sed.batch_no, sed.qty, sed.uom, sed.parent, sed.creation
        from `tabStock Entry` se
        join `tabStock Entry Detail` sed on sed.parent = se.name
        where se.docstatus=1
          and se.work_order=%s
          and se.purpose in ('Material Consumption for Manufacture','Material Transfer for Manufacture')
        order by sed.creation desc
        limit 12
    """, (work_order,), as_dict=True)

    return {"ok": True, "wo": wo.name, "rows": rows, "scans": scans}

@frappe.whitelist()
def parse_scan(code: str):
    out = _parse_gs1_or_basic(code or "")
    item_code = out.get("item_code")
    if not item_code:
        return {"ok": False, "msg": _("Cannot parse item from code")}
    uom = frappe.db.get_value("Item", item_code, "stock_uom") or "Nos"
    return {"ok": True, "item_code": item_code, "batch_no": out.get("batch_no"), "uom": uom}

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
