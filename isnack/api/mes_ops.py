# apps/isnack/isnack/api/mes_ops.py
from __future__ import annotations

import hashlib
import json
from typing import Optional, Tuple

import frappe
from frappe import _

# ============================================================
# Configuration
# ============================================================

def _consume_on_scan() -> bool:
    """
    If True  -> scan makes 'Material Consumption for Manufacture'
    If False -> scan makes 'Material Transfer for Manufacture' (staging -> WIP)
    """
    val = frappe.conf.get("isnack_consume_on_scan")
    # default True if not set
    return bool(1 if val is None else int(val))


# ============================================================
# Helpers
# ============================================================

def _is_fg(item_code: str) -> bool:
    """Policy: treat sales items as Finished Goods. Adjust to Item Group if preferred."""
    return bool(frappe.db.get_value("Item", item_code, "is_sales_item"))

def _get_item_group(item_code: str) -> Optional[str]:
    return frappe.db.get_value("Item", item_code, "item_group")

def _get_user_line(user: str) -> Optional[str]:
    """Resolve operator's manufacturing line from Session Defaults first, then User.custom_line."""
    line = frappe.defaults.get_user_default("manufacturing_line")
    if line:
        return line
    return frappe.db.get_value("User", user, "custom_line")

def _default_line_staging(work_order: str, *, is_packaging: bool = False) -> Optional[str]:
    """
    Choose a default SOURCE/staging warehouse based on line and item class.
    TODO: Map via your own Line/Workstation settings (recommended).
    For now, fallback to Stock Settings -> default_warehouse.
    """
    # Example if you later add a 'Manufacturing Line' DocType:
    # line = frappe.db.get_value("Work Order", work_order, "custom_line")
    # if line:
    #     field = "packaging_wh" if is_packaging else "staging_wh"
    #     wh = frappe.db.get_value("Manufacturing Line", line, field)
    #     if wh: return wh
    return frappe.db.get_single_value("Stock Settings", "default_warehouse")

def _default_line_wip(work_order: str) -> Optional[str]:
    """
    Destination WIP warehouse if you are staging (Material Transfer for Manufacture).
    TODO: Map from line/workstation/operation.
    """
    # Example mapping like above, fallback to default warehouse for now
    return frappe.db.get_single_value("Stock Settings", "default_warehouse")

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
    Minimal parser:
    - GS1 AIs: (01)gtin (10)batch (17)expiry (30)/(37)qty
    - Fallback: ITEM|BATCH|QTY
    """
    out = {}
    s = code
    if s.startswith(("]d2", "]C1", "]Q3")):  # AIM prefix
        s = s[3:]

    def grab(ai, ln=None):
        idx = s.find(ai)
        if idx < 0:
            return None
        val = s[idx + len(ai) :]
        if ln:
            return val[:ln]
        end = val.find("(")
        return val if end < 0 else val[:end]

    gtin = grab("(01)", 14)
    if gtin:
        out["gtin"] = gtin
    batch = grab("(10)")
    if batch:
        out["batch_no"] = batch
    exp = grab("(17)", 6)
    if exp:
        out["expiry"] = exp  # YYMMDD
    qty = grab("(30)") or grab("(37)")
    if qty:
        try:
            out["qty"] = float(qty)
        except Exception:
            pass

    if "gtin" in out:
        item = frappe.db.get_value("Item Barcode", {"barcode": out["gtin"]}, "parent")
        if item:
            out["item_code"] = item

    if "item_code" not in out:
        parts = s.split("|")
        if len(parts) >= 1:
            out["item_code"] = parts[0]
        if len(parts) >= 2:
            out["batch_no"] = parts[1]
        if len(parts) >= 3:
            try:
                out["qty"] = float(parts[2])
            except Exception:
                pass
    return out

def _scan_cache_key(work_order: str, raw_code: str) -> str:
    h = hashlib.sha1((work_order + "|" + raw_code).encode("utf-8")).hexdigest()
    return f"isnack:mes:scan:{work_order}:{h}"

def _has_recent_duplicate(work_order: str, raw_code: str, ttl_sec: int = 45) -> bool:
    """Soft idempotency using frappe.cache with short TTL to prevent double scans."""
    key = _scan_cache_key(work_order, raw_code)
    cache = frappe.cache()
    if cache.get_value(key):
        return True
    cache.set_value(key, "1", expires_in_sec=ttl_sec)
    return False

def _require_roles(roles: list[str]):
    """Quick role gate for mutating operations."""
    if frappe.session.user == "Guest":
        frappe.throw(_("Login required"))
    user_roles = set(frappe.get_roles(frappe.session.user))
    if not (set(roles) & user_roles):
        frappe.throw(_("Not permitted"), frappe.PermissionError)


# ============================================================
# Whitelisted API
# ============================================================

@frappe.whitelist()
def get_assigned_work_orders():
    """
    Return active WOs, filtered by operator's manufacturing line if available.
    """
    user = frappe.session.user
    line = _get_user_line(user)

    filters = {"docstatus": 1, "status": ["in", ["Not Started", "In Process", "On Hold"]]}
    if line:
        # Adjust to your actual custom field (e.g., 'custom_line' on Work Order)
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


@frappe.whitelist()
def scan_material(work_order, code):
    """
    Scan barcode/QR; validate against BOM; gate by WO type:
      - FG WO: only Packaging items allowed
      - SF WO: raw or semi-finished allowed
    Depending on config, either:
      - consume immediately (Material Consumption for Manufacture), or
      - stage to WIP (Material Transfer for Manufacture)
    """
    _require_roles(["Operator", "Production Manager"])

    try:
        if _has_recent_duplicate(work_order, code):
            return {"ok": False, "msg": _("Duplicate scan ignored")}

        parsed = _parse_gs1_or_basic(code)
        item_code = parsed.get("item_code")
        if not item_code:
            return {"ok": False, "msg": _("Cannot parse item from code")}

        # FG gating: packaging only for FG WOs
        is_fg_wo = is_finished_good(work_order)
        group = (_get_item_group(item_code) or "").lower()
        # TODO: adjust these to your taxonomy
        packaging_groups = {"packaging", "cartons", "films", "labels"}
        is_packaging = any(g in group for g in packaging_groups)

        if is_fg_wo and not is_packaging:
            return {"ok": False, "msg": _("For FG WOs, only packaging items can be loaded")}

        # Validate BOM membership
        ok, msg = _validate_item_in_bom(work_order, item_code)
        if not ok:
            return {"ok": False, "msg": msg}

        uom = frappe.db.get_value("Item", item_code, "stock_uom") or "Nos"
        qty = parsed.get("qty") or 1

        if _consume_on_scan():
            # v15: consumption entry against WO
            se = frappe.new_doc("Stock Entry")
            se.purpose = "Material Consumption for Manufacture"
            se.work_order = work_order
            se.append(
                "items",
                {
                    "item_code": item_code,
                    "qty": qty,
                    "uom": uom,
                    "s_warehouse": parsed.get("warehouse")
                    or _default_line_staging(work_order, is_packaging=is_packaging),
                    "batch_no": parsed.get("batch_no"),
                },
            )
            se.flags.ignore_permissions = True
            se.insert()
            se.submit()
            msg_txt = _("Consumed {0} × {1} (Batch {2})").format(qty, item_code, parsed.get("batch_no", "-"))
        else:
            # Stage to WIP (transfer for manufacture)
            se = frappe.new_doc("Stock Entry")
            se.purpose = "Material Transfer for Manufacture"
            se.work_order = work_order
            se.append(
                "items",
                {
                    "item_code": item_code,
                    "qty": qty,
                    "uom": uom,
                    "s_warehouse": parsed.get("warehouse")
                    or _default_line_staging(work_order, is_packaging=is_packaging),
                    "t_warehouse": _default_line_wip(work_order),
                    "batch_no": parsed.get("batch_no"),
                },
            )
            se.flags.ignore_permissions = True
            se.insert()
            se.submit()
            msg_txt = _("Staged {0} × {1} to WIP (Batch {2})").format(qty, item_code, parsed.get("batch_no", "-"))

        return {"ok": True, "msg": msg_txt}

    except Exception:
        frappe.log_error(frappe.get_traceback(), "iSnack scan_material")
        return {"ok": False, "msg": _("Scan failed")}


@frappe.whitelist()
def request_material(work_order, item_code, qty, reason=None):
    """
    Create Material Request:
      - If central stock available → Material Transfer
      - Else if item is purchaseable → Purchase
    """
    _require_roles(["Operator", "Stores User", "Production Manager"])

    qty = float(qty or 0)
    if qty <= 0:
        frappe.throw(_("Quantity must be positive"))

    central_wh = frappe.db.get_single_value("Stock Settings", "default_warehouse")
    projected_qty = frappe.db.get_value(
        "Bin", {"warehouse": central_wh, "item_code": item_code}, "projected_qty"
    ) or 0

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
    Record operator intent (Start/Pause/Stop) without forcing core WO status.
    Keep the real WO status driven by ERPNext's flows (transfers/consumptions/manufacture).
    """
    _require_roles(["Operator", "Production Manager"])
    wo = frappe.get_doc("Work Order", work_order)

    # Store operator intent on custom fields you add via Customize Form
    # (e.g., mes_status, mes_reason, mes_remarks)
    updates = {}
    if action:
        updates["mes_status"] = action
    if reason:
        updates["mes_reason"] = reason
    if remarks:
        updates["mes_remarks"] = remarks

    if updates:
        for k, v in updates.items():
            try:
                wo.db_set(k, v, commit=False)
            except Exception:
                # Field might not exist yet; ignore silently or log as needed
                pass

    wo.add_comment("Info", _("Production control update: {0}").format(json.dumps({
        "action": action, "reason": reason, "remarks": remarks, "by": frappe.session.user
    })))
    wo.flags.ignore_permissions = True
    wo.save()
    return True


@frappe.whitelist()
def complete_work_order(work_order, good, rejects=0, remarks=None):
    """
    Create a Manufacture entry for the finished good quantity.
    Do NOT add RM lines here; ERPNext v15 expects FG-only on this entry.
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
    se.append(
        "items",
        {
            "item_code": wo.production_item,
            "qty": good,
            "uom": frappe.db.get_value("Item", wo.production_item, "stock_uom") or "Nos",
        },
    )
    se.flags.ignore_permissions = True
    se.insert()
    se.submit()

    if remarks:
        try:
            wo.db_set("remarks", remarks, commit=False)
        except Exception:
            pass

    # Let ERPNext derive status; optionally mark as Completed when target met
    target = float(wo.qty or 0)
    if good >= target:
        try:
            wo.db_set("status", "Completed", commit=False)
        except Exception:
            pass

    wo.add_comment(
        "Info",
        _("WO FG receipt: Good={0}, Rejects={1}, Remarks={2}").format(good, rejects, (remarks or "")),
    )
    wo.flags.ignore_permissions = True
    wo.save()
    return True


@frappe.whitelist()
def print_label(work_order, carton_qty, template, printer):
    """
    Render ZPL/TSPL from a custom 'Label Template' doctype (field 'template'),
    and emit to a client printer channel (or your own microservice).
    Enforces FG-only printing.
    """
    _require_roles(["Operator", "Production Manager"])

    tpl = frappe.db.get_value("Label Template", template, "template")
    if not tpl:
        frappe.throw(_("Label Template not found"))

    wo = frappe.get_doc("Work Order", work_order)
    if not _is_fg(wo.production_item):
        frappe.throw(_("Label printing allowed only for finished goods work orders"))

    payload = tpl.format(
        ITEM=wo.production_item,
        ITEM_NAME=wo.item_name,
        WO=wo.name,
        BATCH=wo.get("batch_no") or "",
        QTY=carton_qty,
    )

    # Option A (quick): realtime (client listener prints to local agent)
    frappe.publish_realtime("isnack_print", {"printer": printer, "raw": payload})

    # Option B (server-to-printer microservice):
    # url = frappe.conf.get("isnack_print_url")
    # if url:
    #     import requests
    #     try:
    #         requests.post(url, json={"printer": printer, "raw": payload}, timeout=5)
    #     except Exception:
    #         frappe.log_error(frappe.get_traceback(), "iSnack print_label http")

    # Optional: log into your own doctype if present
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
