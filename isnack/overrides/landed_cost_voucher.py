# Copyright (c) 2024, Busuttil Technologies Limited
# License: MIT
# Custom override for Landed Cost Voucher to fix ERPNext v15 edge case:
# on LCV cancellation, linked draft Assets are not re-synced because
# `landed_cost_voucher_amount` becomes 0, skipping the core update path.

import frappe
from frappe.utils import flt
from erpnext.stock.doctype.landed_cost_voucher.landed_cost_voucher import LandedCostVoucher


RECEIPT_FIELD_MAP = {
    "Purchase Receipt": {
        "parent_field": "purchase_receipt",
        "item_field": "purchase_receipt_item",
        "child_doctype": "Purchase Receipt Item",
    },
    "Purchase Invoice": {
        "parent_field": "purchase_invoice",
        "item_field": "purchase_invoice_item",
        "child_doctype": "Purchase Invoice Item",
    },
}


class CustomLandedCostVoucher(LandedCostVoucher):
    def on_submit(self):
        super().on_submit()
        self._isnack_sync_draft_assets()

    def on_cancel(self):
        super().on_cancel()
        self._isnack_sync_draft_assets()

    def _isnack_sync_draft_assets(self):
        for row in (self.get("purchase_receipts") or []):
            try:
                sync_draft_assets_for_receipt(row.receipt_document_type, row.receipt_document)
            except Exception:
                frappe.log_error(
                    title="isnack: sync_draft_assets_for_receipt failed",
                    message=frappe.get_traceback(),
                )


@frappe.whitelist()
def sync_draft_assets_for_receipt(receipt_document_type: str, receipt_document: str):
    """Resync linked draft Asset Net Purchase Amount from the receipt/invoice item valuation.

    Supports both Purchase Receipt and Purchase Invoice.
    Only updates Assets with docstatus = 0 (Draft).

    Returns a list of dicts describing each updated asset.
    """
    if receipt_document_type not in RECEIPT_FIELD_MAP:
        frappe.throw(
            f"Unsupported receipt_document_type: {receipt_document_type!r}. "
            f"Must be one of: {list(RECEIPT_FIELD_MAP)}"
        )

    if not frappe.db.exists(receipt_document_type, receipt_document):
        frappe.throw(
            f"{receipt_document_type} {receipt_document!r} does not exist."
        )

    field_map = RECEIPT_FIELD_MAP[receipt_document_type]
    parent_field = field_map["parent_field"]
    item_field = field_map["item_field"]
    child_doctype = field_map["child_doctype"]

    # Fetch all fixed-asset item rows from the receipt/invoice
    fixed_asset_items = frappe.get_all(
        child_doctype,
        filters={"parent": receipt_document, "is_fixed_asset": 1},
        fields=["name", "item_code", "valuation_rate"],
    )

    updated = []

    for item in fixed_asset_items:
        item_code = item["item_code"]
        valuation_rate = flt(item["valuation_rate"])
        child_row_name = item["name"]

        # Find draft Assets linked to this receipt + item_code
        draft_assets = frappe.get_all(
            "Asset",
            filters={
                parent_field: receipt_document,
                "item_code": item_code,
                "docstatus": 0,
            },
            fields=[
                "name",
                item_field,
                "asset_quantity",
                "gross_purchase_amount",
                "purchase_amount",
                "additional_asset_cost",
                "opening_accumulated_depreciation",
                "calculate_depreciation",
            ],
        )

        for asset in draft_assets:
            asset_item_ref = asset.get(item_field)

            # If the Asset has a specific child-row reference, only match the exact row.
            # If blank, fall through (loose match by item_code — preserve ERPNext behaviour).
            if asset_item_ref and asset_item_ref != child_row_name:
                continue

            asset_qty = flt(asset.get("asset_quantity")) or 1
            purchase_amount = valuation_rate * asset_qty

            additional_asset_cost = flt(asset.get("additional_asset_cost"))
            total_asset_cost = purchase_amount + additional_asset_cost

            old_gross = flt(asset.get("gross_purchase_amount"))

            values_to_set = {
                "gross_purchase_amount": purchase_amount,
                "purchase_amount": purchase_amount,
                "total_asset_cost": total_asset_cost,
            }

            if asset.get("calculate_depreciation"):
                opening_accumulated_depreciation = flt(asset.get("opening_accumulated_depreciation"))
                values_to_set["value_after_depreciation"] = (
                    purchase_amount - opening_accumulated_depreciation
                )

            frappe.db.set_value("Asset", asset["name"], values_to_set)

            updated.append({
                "asset": asset["name"],
                "item_code": item_code,
                "old_amount": old_gross,
                "new_amount": purchase_amount,
            })

    frappe.logger("isnack").info(
        f"isnack: sync_draft_assets_for_receipt({receipt_document_type!r}, {receipt_document!r}) "
        f"— {len(updated)} asset(s) updated."
    )

    return updated
