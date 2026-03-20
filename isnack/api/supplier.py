from __future__ import annotations

import frappe
from frappe import _

DOCSTATUS_LABELS = {
    0: _("Draft"),
    1: _("Submitted"),
    2: _("Cancelled"),
}

DOCSTATUS_INDICATORS = {
    0: "orange",
    1: "green",
    2: "red",
}


@frappe.whitelist()
def get_linked_landed_cost_vouchers(supplier: str | None = None) -> dict:
    """Return Landed Cost Vouchers linked to a supplier via Purchase Receipts."""
    supplier = (supplier or "").strip()
    if not supplier:
        frappe.throw(_("Supplier is required."))

    if not frappe.db.exists("Supplier", supplier):
        frappe.throw(_("Supplier {0} does not exist.").format(frappe.bold(supplier)))

    if not frappe.has_permission("Supplier", "read", doc=supplier):
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    candidate_rows = frappe.db.sql(
        """
        SELECT DISTINCT lpr.parent
        FROM `tabLanded Cost Purchase Receipt` lpr
        LEFT JOIN `tabPurchase Receipt` pr
            ON pr.name = lpr.receipt_document
        WHERE lpr.parenttype = 'Landed Cost Voucher'
          AND lpr.receipt_document_type = 'Purchase Receipt'
          AND COALESCE(NULLIF(lpr.supplier, ''), pr.supplier) = %(supplier)s
        """,
        {"supplier": supplier},
        as_dict=True,
    )

    voucher_names = [row.parent for row in candidate_rows]
    if not voucher_names:
        return {
            "supplier": supplier,
            "total_vouchers": 0,
            "vouchers": [],
        }

    placeholders = ", ".join(["%s"] * len(voucher_names))
    detail_rows = frappe.db.sql(
        f"""
        SELECT
            lpr.parent AS voucher_name,
            lpr.receipt_document,
            COALESCE(NULLIF(lpr.supplier, ''), pr.supplier) AS receipt_supplier,
            lcv.posting_date,
            lcv.company,
            lcv.total_taxes_and_charges,
            lcv.docstatus
        FROM `tabLanded Cost Purchase Receipt` lpr
        INNER JOIN `tabLanded Cost Voucher` lcv
            ON lcv.name = lpr.parent
        LEFT JOIN `tabPurchase Receipt` pr
            ON pr.name = lpr.receipt_document
        WHERE lpr.parenttype = 'Landed Cost Voucher'
          AND lpr.receipt_document_type = 'Purchase Receipt'
          AND lpr.parent IN ({placeholders})
        ORDER BY lcv.posting_date DESC, lcv.name DESC, lpr.idx ASC
        """,
        tuple(voucher_names),
        as_dict=True,
    )

    grouped = {}
    for row in detail_rows:
        voucher_name = row.voucher_name
        entry = grouped.setdefault(
            voucher_name,
            {
                "name": voucher_name,
                "posting_date": row.posting_date,
                "company": row.company,
                "total_taxes_and_charges": row.total_taxes_and_charges,
                "docstatus": row.docstatus,
                "supplier_purchase_receipts": set(),
                "all_purchase_receipts": set(),
                "all_suppliers": set(),
            },
        )

        if row.receipt_document:
            entry["all_purchase_receipts"].add(row.receipt_document)

        if row.receipt_supplier:
            entry["all_suppliers"].add(row.receipt_supplier)

        if row.receipt_supplier == supplier and row.receipt_document:
            entry["supplier_purchase_receipts"].add(row.receipt_document)

    vouchers = []
    for voucher_name, entry in grouped.items():
        if not entry["supplier_purchase_receipts"]:
            continue

        if not frappe.has_permission("Landed Cost Voucher", "read", doc=voucher_name):
            continue

        all_suppliers = sorted(entry["all_suppliers"])
        other_suppliers = [s for s in all_suppliers if s != supplier]

        vouchers.append(
            {
                "name": voucher_name,
                "posting_date": entry["posting_date"],
                "company": entry["company"],
                "total_taxes_and_charges": entry["total_taxes_and_charges"],
                "docstatus": entry["docstatus"],
                "status": DOCSTATUS_LABELS.get(entry["docstatus"], _("Unknown")),
                "indicator": DOCSTATUS_INDICATORS.get(entry["docstatus"], "gray"),
                "supplier_purchase_receipts": sorted(entry["supplier_purchase_receipts"]),
                "supplier_purchase_receipt_count": len(entry["supplier_purchase_receipts"]),
                "all_purchase_receipt_count": len(entry["all_purchase_receipts"]),
                "all_suppliers": all_suppliers,
                "other_suppliers": other_suppliers,
                "has_other_suppliers": bool(other_suppliers),
            }
        )

    vouchers.sort(
        key=lambda d: (
            d.get("posting_date") or "",
            d.get("name") or "",
        ),
        reverse=True,
    )

    return {
        "supplier": supplier,
        "total_vouchers": len(vouchers),
        "vouchers": vouchers,
    }
