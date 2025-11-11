import frappe
from frappe import _
from frappe.utils import now_datetime, add_to_date

# --- Helpers -----------------------------------------------------------------

def _wip_for(wo: dict) -> str:
    # If WO has wip_warehouse set, prefer it; else map by manufacturing_line.
    if wo.get('wip_warehouse'):
        return wo['wip_warehouse']
    line = wo.get('manufacturing_line')
    mapping = {
        'Frying': 'WIP - Frying',
        'Execution': 'WIP - Execution',
    }
    return mapping.get(line, '')


def _stage_status(work_order_name: str, wip_wh: str) -> str:
    """Return 'Not Staged' | 'Partial' | 'Staged'.
    Simplified: any submitted Material Transfer rows to the target WIP
    → Partial; if quantities for all BOM components are fully covered → Staged.
    """
    # any transfer?
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
        (work_order_name, wip_wh), as_dict=True)
    if not rows:
        return 'Not Staged'

    # compare to required qty by BOM * WO.qty
    req = frappe.db.sql(
        """
        select bi.item_code, sum(bi.qty) as qty
        from `tabWork Order` wo
        join `tabBOM Explosion Item` bi on bi.parent = wo.bom_no
        where wo.name = %s
        group by bi.item_code
        """,
        (work_order_name,), as_dict=True)
    req_map = {r.item_code: r.qty * frappe.db.get_value('Work Order', work_order_name, 'qty') for r in req}
    have_map = {r.item_code: r.qty for r in rows}

    partial = False
    for item, rq in req_map.items():
        if have_map.get(item, 0) < rq - 1e-9:
            partial = True
    return 'Partial' if partial else 'Staged'

# --- API ---------------------------------------------------------------------

@frappe.whitelist()
def get_queue(company: str, line: str):
    """Work Orders that are Not Started/In Process, filtered by line, annotated with staging status."""
    wos = frappe.get_all('Work Order',
        filters={
            'company': company,
            'manufacturing_line': line,
            'status': ['in', ['Not Started','In Process']]
        },
        fields=['name','item_code','item_name','qty','uom','wip_warehouse','manufacturing_line'])

    for w in wos:
        wip = _wip_for(w)
        try:
            w['stage_status'] = _stage_status(w.name, wip) if wip else 'Not Staged'
        except Exception:
            # if BOM explosion table missing or mapping not set, fall back
            w['stage_status'] = 'Partial' if frappe.db.exists('Stock Entry', {'work_order': w.name, 'purpose':'Material Transfer for Manufacture', 'docstatus':1}) else 'Not Staged'
    return wos


@frappe.whitelist()
def create_pick_list(work_order: str, target_wip: str = None):
    wo = frappe.get_doc('Work Order', work_order)
    pl = frappe.new_doc('Pick List')
    pl.purpose = 'Material Transfer for Manufacture'
    pl.company = wo.company
    pl.work_order = wo.name
    if target_wip:
        pl.set('to_warehouse', target_wip)  # visible on child table after load
    pl.insert(ignore_permissions=True)
    # Assign to current user so it shows in "In Picking"
    frappe.desk.form.assign_to.add({
        'doctype': 'Pick List',
        'name': pl.name,
        'assign_to': [frappe.session.user]
    })
    return pl.name


@frappe.whitelist()
def get_picks(my_only: int = 1):
    filters = {'docstatus': 0, 'purpose': 'Material Transfer for Manufacture'}
    if my_only:
        filters['owner'] = frappe.session.user
    return frappe.get_all('Pick List', filters=filters, fields=['name','modified','work_order'])


@frappe.whitelist()
def get_recent_transfers(line: str = None, hours: int = 24):
    since = add_to_date(now_datetime(), hours=-int(hours))
    q = """
        select se.name, se.posting_date, se.posting_time, se.to_warehouse
        from `tabStock Entry` se
        where se.docstatus=1 and se.purpose='Material Transfer for Manufacture'
          and se.modified >= %s
        order by se.modified desc
        limit 50
    """
    se_list = frappe.db.sql(q, (since,), as_dict=True)
    if line:
        # crude filter by WIP suffix in mapping
        mapping = {'Frying': 'WIP - Frying', 'Execution': 'WIP - Execution'}
        suffix = mapping.get(line)
        if suffix:
            se_list = [r for r in se_list if (r.to_warehouse or '').endswith(suffix)]
    return se_list


@frappe.whitelist()
def print_labels(stock_entry: str):
    """Server-side print with your Raw print format. Requires Print Settings and QZ Tray trust."""
    fmt = 'Pallet Label – Material Transfer'
    frappe.printing.print_by_server(doctype='Stock Entry', name=stock_entry, print_format=fmt)
    return True


@frappe.whitelist()
def find_se_by_item_row(rowname: str):
    parent = frappe.db.get_value('Stock Entry Detail', rowname, 'parent')
    return parent