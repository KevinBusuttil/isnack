// Shared filter for the Items table on selling transactions (Sales Quotation,
// Sales Order, Sales Invoice). Restricts item_code lookups to the Item Groups
// configured under General Settings → Sales → Allowed Sales Item Groups.
//
// Loaded via app_include_js. The per-doctype scripts call
// isnack_apply_sales_item_group_filter(frm) from their refresh handler so the
// filter is layered on top of (and wins over) ERPNext's selling-controller
// setup_queries, which also registers a get_query on items.item_code.
//
// General Settings is only readable by System Manager, so the configured Item
// Groups are fetched via a whitelisted server method to avoid permission
// errors for regular sales users.

window.isnack_apply_sales_item_group_filter = function (frm) {
    if (!frm || !frm.fields_dict || !frm.fields_dict.items) {
        return;
    }

    isnack_load_allowed_sales_item_groups(frm).then((item_groups) => {
        // Mirror ERPNext's selling-controller filter (is_sales_item / customer /
        // has_variants) and layer item_group on top so search keeps working.
        frm.set_query("item_code", "items", () => {
            const filters = {
                is_sales_item: 1,
                has_variants: 0,
            };
            if (frm.doc.customer) {
                filters.customer = frm.doc.customer;
            }
            const groups = frm.__isnack_allowed_sales_item_groups || [];
            if (groups.length) {
                filters.item_group = ["in", groups];
            }
            return {
                query: "erpnext.controllers.queries.item_query",
                filters: filters,
            };
        });
    });
};

function isnack_load_allowed_sales_item_groups(frm) {
    if (frm.__isnack_allowed_sales_item_groups_promise) {
        return frm.__isnack_allowed_sales_item_groups_promise;
    }
    frm.__isnack_allowed_sales_item_groups_promise = new Promise((resolve) => {
        frappe.call({
            method: "isnack.isnack.doctype.general_settings.general_settings.get_allowed_sales_item_groups",
            callback(r) {
                const groups = (r && Array.isArray(r.message)) ? r.message : [];
                frm.__isnack_allowed_sales_item_groups = groups;
                resolve(groups);
            },
            error() {
                frm.__isnack_allowed_sales_item_groups = [];
                resolve([]);
            },
        });
    });
    return frm.__isnack_allowed_sales_item_groups_promise;
}
