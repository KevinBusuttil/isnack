# apps/isnack/isnack/api/mes_ops.py
import frappe
from frappe import _

# -------- Helpers --------

def _is_fg(item_code: str) -> bool:
    """Treat sales items as Finished Goods. Adjust per your policy (e.g., Item Group)."""
    return bool(frappe.db.get_value('Item', item_code, 'is_sales_item'))

def _default_line_staging(work_order: str) -> str | None:
    # TODO: map by custom fields on WO (e.g., line). Fallback to Stock Settings default.
    return frappe.db.get_single_value('Stock Settings', 'default_warehouse')

def _validate_item_in_bom(work_order: str, item_code: str) -> tuple[bool, str]:
    bom = frappe.db.get_value('Work Order', work_order, 'bom_no')
    if not bom:
      return False, _('Work Order has no BOM')
    exists = frappe.db.exists('BOM Item', {'parent': bom, 'item_code': item_code})
    if not exists:
      return False, _('Item {0} not in BOM {1}').format(item_code, bom)
    return True, 'OK'

def _parse_gs1_or_basic(code: str) -> dict:
    """
    Minimal parser:
    - GS1 AIs: (01)gtin (10)batch (17)expiry (30)/(37)qty
    - Fallback: ITEM|BATCH|QTY
    """
    out = {}
    s = code
    if s.startswith((']d2', ']C1', ']Q3')):  # AIM prefix
        s = s[3:]

    def grab(ai, ln=None):
        idx = s.find(ai)
        if idx < 0: return None
        val = s[idx+len(ai):]
        if ln: return val[:ln]
        end = val.find('(')
        return val if end < 0 else val[:end]

    gtin = grab('(01)', 14)
    if gtin: out['gtin'] = gtin
    batch = grab('(10)')
    if batch: out['batch_no'] = batch
    exp   = grab('(17)', 6)
    if exp: out['expiry'] = exp  # YYMMDD
    qty   = grab('(30)') or grab('(37)')
    if qty:
        try: out['qty'] = float(qty)
        except: pass

    if 'gtin' in out:
        item = frappe.db.get_value('Item Barcode', {'barcode': out['gtin']}, 'parent')
        if item: out['item_code'] = item

    if 'item_code' not in out:
        parts = s.split('|')
        if len(parts) >= 1: out['item_code'] = parts[0]
        if len(parts) >= 2: out['batch_no']  = parts[1]
        if len(parts) >= 3:
            try: out['qty'] = float(parts[2])
            except: pass
    return out

# -------- Whitelisted API --------

@frappe.whitelist()
def get_assigned_work_orders():
    """
    v15 baseline: show active WOs. 
    You can filter by assignment/line/shift if you have custom fields.
    """
    rows = frappe.get_all('Work Order',
        filters={'docstatus': 1, 'status': ['in', ['Not Started','In Process','On Hold']]},
        fields=['name','production_item','item_name','qty','status'])
    for r in rows:
        r['type'] = 'FG' if _is_fg(r['production_item']) else 'SF'
    return rows

@frappe.whitelist()
def is_finished_good(work_order):
    item = frappe.db.get_value('Work Order', work_order, 'production_item')
    return _is_fg(item) if item else False

@frappe.whitelist()
def get_wo_banner(work_order):
    wo = frappe.get_doc('Work Order', work_order)
    # Actual produced so far (Manufacture entries)
    actual = frappe.db.sql("""
        select coalesce(sum(sed.qty),0)
        from `tabStock Entry` se
        join `tabStock Entry Detail` sed on sed.parent = se.name
        where se.docstatus=1 and se.work_order=%s and se.purpose='Manufacture'
    """, work_order)[0][0] or 0
    batch = wo.get('batch_no') or '-'
    html = f"""
      <div><b>{frappe.utils.escape_html(wo.name)}</b> — {frappe.utils.escape_html(wo.item_name)} (Batch: {frappe.utils.escape_html(batch)})</div>
      <div>Target: {wo.qty} &nbsp; Actual: {actual} &nbsp; Status: {frappe.utils.escape_html(wo.status)}</div>
      <div class="small text-muted">Operator: {frappe.session.user}</div>
    """
    return {"html": html}

@frappe.whitelist()
def scan_material(work_order, code):
    """
    Scan barcode/QR; validate BOM membership; create Material Issue (or stage).
    """
    try:
        parsed = _parse_gs1_or_basic(code)
        item_code = parsed.get('item_code')
        if not item_code:
            return {'ok': False, 'msg': _('Cannot parse item from code')}

        ok, msg = _validate_item_in_bom(work_order, item_code)
        if not ok:
            return {'ok': False, 'msg': msg}

        uom = frappe.db.get_value('Item', item_code, 'stock_uom') or 'Nos'
        qty = parsed.get('qty') or 1

        se = frappe.new_doc('Stock Entry')
        se.purpose = 'Material Issue'
        se.work_order = work_order
        se.from_warehouse = parsed.get('warehouse') or _default_line_staging(work_order)
        se.append('items', {
            'item_code': item_code,
            'qty': qty,
            'uom': uom,
            'batch_no': parsed.get('batch_no')
        })
        se.flags.ignore_permissions = True
        se.insert()
        se.submit()

        return {'ok': True, 'msg': _('Loaded {0} x {1} (Batch {2})').format(qty, item_code, parsed.get('batch_no','-'))}
    except Exception:
        frappe.log_error(frappe.get_traceback(), 'iSnack scan_material')
        return {'ok': False, 'msg': _('Scan failed')}

@frappe.whitelist()
def request_material(work_order, item_code, qty, reason=None):
    mr = frappe.new_doc('Material Request')
    mr.material_request_type = 'Material Transfer'
    mr.schedule_date = frappe.utils.nowdate()
    mr.work_order = work_order
    mr.append('items', {'item_code': item_code, 'qty': qty, 'schedule_date': mr.schedule_date})
    if reason: mr.notes = reason
    mr.flags.ignore_permissions = True
    mr.insert()
    return {'ok': True, 'mr': mr.name}

@frappe.whitelist()
def set_wo_status(work_order, action, reason=None, remarks=None):
    wo = frappe.get_doc('Work Order', work_order)
    if action == 'Start' and wo.status in ('Not Started','On Hold'):
        wo.db_set('status', 'In Process')
    elif action == 'Pause':
        wo.db_set('status', 'On Hold')
        # TODO: add downtime log if you maintain one
    elif action == 'Stop':
        wo.db_set('status', 'Stopped')
    return True

@frappe.whitelist()
def complete_work_order(work_order, good, rejects=0, remarks=None):
    """Post a Manufacture entry for good qty and mark WO Completed."""
    good = float(good or 0)
    wo = frappe.get_doc('Work Order', work_order)

    se = frappe.new_doc('Stock Entry')
    se.purpose = 'Manufacture'
    se.work_order = work_order
    se.to_warehouse = wo.fg_warehouse or frappe.db.get_single_value('Stock Settings', 'default_warehouse')
    se.append('items', {
        'item_code': wo.production_item,
        'qty': good,
        'uom': frappe.db.get_value('Item', wo.production_item, 'stock_uom') or 'Nos'
    })
    se.flags.ignore_permissions = True
    se.insert()
    se.submit()

    if remarks:
        frappe.db.set_value('Work Order', work_order, 'remarks', remarks)
    frappe.db.set_value('Work Order', work_order, 'status', 'Completed')
    return True

@frappe.whitelist()
def print_label(work_order, carton_qty, template, printer):
    """
    Render ZPL/TSPL from a Print Template and 'send to printer'.
    Logs an event (you can wire to your own label log doctype if you have one).
    """
    tpl = frappe.db.get_value('Print Template', template, 'template_body')
    if not tpl:
        frappe.throw(_('Print Template not found'))

    wo  = frappe.get_doc('Work Order', work_order)
    payload = tpl.format(
        ITEM=wo.production_item,
        ITEM_NAME=wo.item_name,
        WO=wo.name,
        BATCH=wo.get('batch_no') or '',
        QTY=carton_qty
    )

    # TODO: replace with your print microservice (HTTP/Socket). For now, emit realtime.
    frappe.publish_realtime('isnack_print', {'printer': printer, 'raw': payload})

    # Optional: log into your own doctype (Packed Carton, if you have one)
    if frappe.db.exists('DocType', 'Packed Carton'):
        pc = frappe.new_doc('Packed Carton')
        pc.work_order = wo.name
        pc.item_code = wo.production_item
        pc.batch_no = wo.get('batch_no')
        pc.qty = carton_qty
        pc.label_template = template
        pc.flags.ignore_permissions = True
        pc.insert()
    return True
