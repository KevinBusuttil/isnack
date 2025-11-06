# apps/isnack/isnack/api/mes_ops.py
from __future__ import annotations

import hashlib
from string import Template
from typing import Optional, Tuple

import frappe
from frappe import _

# ============================================================
# Config helpers
# ============================================================

def _consume_on_scan() -> bool:
    """
    If True  -> scan makes 'Material Consumption for Manufacture'
    If False -> scan makes 'Material Transfer for Manufacture' (staging -> WIP)
    """
    val = frappe.conf.get("isnack_consume_on_scan")
    return bool(1 if val is None else int(val))

def _scan_dup_ttl() -> int:
    return int(frappe.conf.get("isnack_scan_dup_ttl_sec") or 45)

def _max_active_ops() -> int:
    return int(frappe.conf.get("isnack_max_active_operators") or 2)

def _require_packaging_in_bom() -> bool:
    # 1 = packaging must be listed in BOM; 0 = allow packaging even if not in BOM
    return bool(int(frappe.conf.get("isnack_require_packaging_in_bom") or 1))

def _allowed_groups_for_line(line: Optional[str]) -> set[str]:
    """
    site_config.json example:
    {
      "isnack_line_allowed_item_groups": {
        "Line – Frying":    ["Semi Finished", "Oils & Fats", "Seasoning"],
        "Line – Extrusion": ["Raw Materials", "Cereals & Grains", "Seasoning", "Additives"],
        "Line – Packing":   ["Packaging"]
      }
    }
    """
    cfg = frappe.conf.get("isnack_line_allowed_item_groups") or {}
    groups = (cfg.get(line) or []) if line else []
    return {str(g).lower() for g in groups}

def _warehouses_for_line(line: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """
    Optional per-line WH mapping in site_config.json (falls back to Stock Settings):
    {
      "isnack_line_warehouses": {
        "Line – Frying":    {"staging":"Staging – Frying", "wip":"WIP – Frying"},
        "Line – Extrusion": {"staging":"Staging – Extrusion", "wip":"WIP – Extrusion"}
      }
    }
    """
    cfg = frappe.conf.get("isnack_line_warehouses") or {}
    row = cfg.get(line or "") or {}
    return row.get("staging"), row.get("wip")

# ============================================================
# Generic helpers
# ============================================================

def _is_fg(item_code: str) -> bool:
    """Treat sales items as FG by policy (adjust to Item Group if you prefer)."""
    return bool(frappe.db.get_value("Item", item_code, "is_sales_item"))

def _get_item_group(item_code: str) -> Optional[str]:
    return frappe.db.get_value("Item", item_code, "item_group")

def _get_user_line(user: str) -> Optional[str]:
    """Prefer explicit line from UI. Only use session default if present; never assume custom fields."""
    line = frappe.defaults.get_user_default("manufacturing_line")
    return line or None

def _user_employee(user: str) -> Optional[str]:
    emp = frappe.db.get_value("Employee", {"user_id": user}, "name")
    if emp:
        return emp
    return frappe.db.get_value("User", user, "employee")

def _employee_by_badge(badge: str) -> Optional[str]:
    """Find Employee by a badge/id in a few common fields."""
    if not badge:
        return None
    meta = frappe.get_meta("Employee")
    candidates = []
    for fname in ("badge_code", "attendance_device_id", "employee_number", "barcode"):
        if meta.has_field(fname):
            candidates.append(fname)
    for f in candidates:
        emp = frappe.db.get_value("Employee", {f: badge}, "name")
        if emp:
            return emp
    return None

def _employee_or_user_default(employee: Optional[str]) -> Optional[str]:
    """Prefer explicit employee (kiosk), else linked Employee of the session user."""
    if employee:
        return employee
    return _user_employee(frappe.session.user)

def _default_line_staging(work_order: str, *, is_packaging: bool = False) -> Optional[str]:
    """Stage FROM here; can be line-aware via site_config."""
    # Try line from any JC for this WO (first match)
    line = frappe.db.get_value("Job Card", {"work_order": work_order}, "workstation")
    staging, _wip = _warehouses_for_line(line)
    return staging or frappe.db.get_single_value("Stock Settings", "default_warehouse")

def _default_line_wip(work_order: str) -> Optional[str]:
    """WIP destination (for Material Transfer for Manufacture)."""
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
    """
    Very small parser:
    - GS1 AIs: (01)gtin (10)batch (17)expiry (30)/(37)qty
    - Fallback: ITEM|BATCH|QTY
    """
    out, s = {}, code
    if s.startswith(("]d2", "]C1", "]Q3")):  # AIM prefix
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
    if exp: out["expiry"] = exp  # YYMMDD
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
    """Soft idempotency to avoid double-scans."""
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
    """Return open time logs (to_time is null)."""
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
    """
    Old list: active WOs (kept while migrating to Job Cards).
    """
    user = frappe.session.user
    line = _get_user_line(user)

    filters = {"docstatus": 1, "status": ["in", ["Not Started", "In Process", "On Hold"]]}
    if line:
        # Only apply if you actually have such a field; otherwise ignore
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
    """Return canonical Employee id + name for a badge or explicit employee link."""
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
# New: Line queue + quick claim on Job Cards
# ============================================================

@frappe.whitelist()
def get_line_queue(line: Optional[str] = None):
    """
    Return current line queue (Job Cards).
    Status in Open / Work In Progress / On Hold.
    """
    if not line:
        line = _get_user_line(frappe.session.user)

    filters = {
        "docstatus": ["<", 2],
        "status": ["in", ["Open", "Work In Progress", "On Hold"]],
    }
    if line:
        filters["workstation"] = line

    # Guard optional 'priority' custom field
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

@frappe.whitelist()
def claim_job_card(job_card: str, employee: Optional[str] = None):
    """Open a time log for the given Employee (kiosk passes employee explicitly)."""
    _require_roles(["Operator", "Production Manager"])

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

    # Concurrency guard
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
    """Close the specified Employee's open time log (kiosk passes employee)."""
    _require_roles(["Operator", "Production Manager"])

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
def set_card_status(job_card: str, action: str, reason: Optional[str] = None, remarks: Optional[str] = None):
    """
    Operator intent for a Job Card (Start/Pause/Stop).
    """
    _require_roles(["Operator", "Production Manager"])
    jc = frappe.get_doc("Job Card", job_card)

    action = (action or "").strip()
    if action == "Start":
        if not _open_time_logs(job_card):
            jc.append("time_logs", {"from_time": frappe.utils.now_datetime()})
        jc.status = "Work In Progress"
    elif action == "Pause":
        for r in _open_time_logs(job_card):
            frappe.db.set_value("Job Card Time Log", r["name"], "to_time", frappe.utils.now_datetime(), update_modified=False)
        jc.status = "On Hold"
    elif action == "Stop":
        for r in _open_time_logs(job_card):
            frappe.db.set_value("Job Card Time Log", r["name"], "to_time", frappe.utils.now_datetime(), update_modified=False)
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
# Scanning, requests, labels, completion  (JC-aware)
# ============================================================

@frappe.whitelist()
def scan_material(code, job_card: Optional[str] = None, work_order: Optional[str] = None):
    """
    Scan barcode/QR; validate vs BOM; gate by LINE (workstation) using item groups.
    Accepts either job_card or work_order; if job_card is sent, WO is derived.
    """
    _require_roles(["Operator", "Production Manager"])

    try:
        # Resolve WO
        if job_card and not work_order:
            work_order = frappe.db.get_value("Job Card", job_card, "work_order")
        if not work_order:
            frappe.throw(_("Missing work_order / job_card"))

        if _has_recent_duplicate(work_order, code):
            return {"ok": False, "msg": _("Duplicate scan ignored")}

        parsed = _parse_gs1_or_basic(code)
        item_code = parsed.get("item_code")
        if not item_code:
            return {"ok": False, "msg": _("Cannot parse item from code")}

        # Batch guard
        if frappe.db.get_value("Item", item_code, "has_batch_no") and not parsed.get("batch_no"):
            return {"ok": False, "msg": _("Batch number required for {0}").format(item_code)}

        # Determine line (workstation on the JC), item group, and apply per-line allowlist
        line = frappe.db.get_value("Job Card", job_card, "workstation") if job_card else None
        group = (_get_item_group(item_code) or "").lower()
        allowed = _allowed_groups_for_line(line)
        if allowed and group not in allowed:
            return {"ok": False, "msg": _("Item group {0} not allowed on {1}").format(group or "?", line or "this line")}

        # Optional: FG/packaging safeguard (kept compatible)
        is_fg_wo = is_finished_good(work_order)
        packaging_groups = {"packaging", "cartons", "films", "labels"}
        is_packaging = any(g in group for g in packaging_groups)

        # Validate BOM membership (unless you decided to relax for packaging)
        if not (is_packaging and not _require_packaging_in_bom()):
            ok, msg = _validate_item_in_bom(work_order, item_code)
            if not ok:
                return {"ok": False, "msg": msg}

        uom = frappe.db.get_value("Item", item_code, "stock_uom") or "Nos"
        qty = parsed.get("qty") or 1

        if _consume_on_scan():
            se = frappe.new_doc("Stock Entry")
            se.purpose = "Material Consumption for Manufacture"
            se.work_order = work_order
            se.append("items", {
                "item_code": item_code,
                "qty": qty,
                "uom": uom,
                "s_warehouse": parsed.get("warehouse") or _default_line_staging(work_order, is_packaging=is_packaging),
                "batch_no": parsed.get("batch_no"),
            })
            se.flags.ignore_permissions = True
            se.insert(); se.submit()
            msg_txt = _("Consumed {0} × {1} (Batch {2})").format(qty, item_code, parsed.get("batch_no", "-"))
        else:
            se = frappe.new_doc("Stock Entry")
            se.purpose = "Material Transfer for Manufacture"
            se.work_order = work_order
            se.append("items", {
                "item_code": item_code,
                "qty": qty,
                "uom": uom,
                "s_warehouse": parsed.get("warehouse") or _default_line_staging(work_order, is_packaging=is_packaging),
                "t_warehouse": _default_line_wip(work_order),
                "batch_no": parsed.get("batch_no"),
            })
            se.flags.ignore_permissions = True
            se.insert(); se.submit()
            msg_txt = _("Staged {0} × {1} to WIP (Batch {2})").format(qty, item_code, parsed.get("batch_no", "-"))

        return {"ok": True, "msg": msg_txt}

    except Exception:
        frappe.log_error(frappe.get_traceback(), "iSnack scan_material")
        return {"ok": False, "msg": _("Scan failed")}

@frappe.whitelist()
def request_material(item_code, qty, reason=None, job_card: Optional[str] = None, work_order: Optional[str] = None):
    """
    Create Material Request (Transfer if stock is available, else Purchase if purchaseable).
    Accepts job_card or work_order.
    """
    _require_roles(["Operator", "Stores User", "Production Manager"])

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
    """
    (Legacy) Operator intent on WO. Prefer set_card_status for Job Cards.
    """
    _require_roles(["Operator", "Production Manager"])
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
    """Helper for pre-filling remaining qty on 'Complete WO'."""
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
def complete_work_order(work_order, good, rejects=0, remarks=None):
    """
    Manufacture entry for finished good quantity (FG only on the entry in v15).
    """
    _require_roles(["Operator", "Production Manager"])

    good = float(good or 0)
    rejects = float(rejects or 0)
    if good < 0 or rejects < 0:
        frappe.throw(_("Quantities cannot be negative"))

    wo = frappe.get_doc("Work Order", work_order)

    se = frappe.new_doc("Stock Entry")
    se.purpose = "Manufacture"
    se.work_order = work_order
    se.to_warehouse = wo.fg_warehouse or frappe.db.get_single_value("Stock Settings", "default_warehouse")
    se.append("items", {
        "item_code": wo.production_item,
        "qty": good,
        "uom": frappe.db.get_value("Item", wo.production_item, "stock_uom") or "Nos",
    })
    se.flags.ignore_permissions = True
    se.insert(); se.submit()

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
def print_label(carton_qty, template, printer, work_order: Optional[str] = None, job_card: Optional[str] = None):
    """
    Render ZPL/TSPL from a custom 'Label Template' (field 'template') or fall back to 'Print Template'.
    FG-only safeguard. Accepts job_card or work_order.
    """
    _require_roles(["Operator", "Production Manager"])

    if job_card and not work_order:
        work_order = frappe.db.get_value("Job Card", job_card, "work_order")
    if not work_order:
        frappe.throw(_("Missing work_order / job_card"))

    wo = frappe.get_doc("Work Order", work_order)
    if not _is_fg(wo.production_item):
        frappe.throw(_("Label printing allowed only for finished goods"))

    # Try custom Label Template first; fall back to Print Template if you’re already using it
    tpl = frappe.db.get_value("Label Template", template, "template")
    if not tpl:
        tpl = frappe.db.get_value("Print Template", template, "template_body")
    if not tpl:
        frappe.throw(_("Template not found"))

    # If template uses $PLACEHOLDERS use string.Template; otherwise treat as .format() style
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

    # Realtime: scope to caller & after commit so only the user’s agent prints
    frappe.publish_realtime("isnack_print", {"printer": printer, "raw": payload},
                            user=frappe.session.user, after_commit=True)

    # Optional: log to your own doctype if present
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
