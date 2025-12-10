import frappe
from frappe.desk.reportview import get_match_cond, get_filters_cond

@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_items_filtered_by_supplier(doctype, txt, searchfield, start, page_len, filters):
    supplier = filters.get("supplier")
    conditions = []
    if not supplier:
        return []
    return frappe.db.sql("""
        SELECT DISTINCT i.name, i.item_name
        FROM `tabItem` i
        INNER JOIN `tabItem Supplier` ON `tabItem Supplier`.parent = i.name
        WHERE i.disabled = 0
            AND i.is_purchase_item = 1
            AND (i.name LIKE %(txt)s OR i.item_name LIKE %(txt)s)
        {match_cond}
        {filters_cond}
        ORDER BY i.name
        LIMIT %(start)s, %(page_len)s
    """.format(
        match_cond=get_match_cond(doctype),
        filters_cond=get_filters_cond(doctype, filters, conditions)
    ), {
        'txt': '%' + txt + '%',
        'start': start,
        'page_len': page_len,
        'supplier': supplier
    })
