import copy
import json

import frappe
from frappe import _, msgprint
from frappe.model.document import Document
from frappe.query_builder.functions import IfNull, Sum
from frappe.utils import (
    add_days,
    ceil,
    cint,
    comma_and,
    flt,
    get_link_to_form,
    getdate,
    now_datetime,
    nowdate,
)
from frappe.utils.csvutils import build_csv_response
from pypika.terms import ExistsCriterion

from erpnext.manufacturing.doctype.bom.bom import get_children as get_bom_children
from erpnext.manufacturing.doctype.bom.bom import validate_bom_no
from erpnext.manufacturing.doctype.work_order.work_order import get_item_details
from erpnext.setup.doctype.item_group.item_group import get_item_group_defaults
from erpnext.stock.get_item_details import get_conversion_factor
from erpnext.stock.utils import get_or_make_bin
from erpnext.utilities.transaction_base import validate_uom_is_integer

from erpnext.manufacturing.doctype.production_plan.production_plan import ProductionPlan, get_sub_assembly_items, get_bin_details

class CustomProductionPlan(ProductionPlan):

    @frappe.whitelist()
    def get_sub_assembly_items(self, manufacturing_type=None):
        "Fetch sub assembly items and optionally combine them."
        self.sub_assembly_items = []
        sub_assembly_items_store = []  # temporary store to process all subassembly items

        for row in self.po_items:
            if self.skip_available_sub_assembly_item and not self.sub_assembly_warehouse:
                frappe.throw(_("Row #{0}: Please select the Sub Assembly Warehouse").format(row.idx))

            if not row.item_code:
                frappe.throw(_("Row #{0}: Please select Item Code in Assembly Items").format(row.idx))

            if not row.bom_no:
                frappe.throw(_("Row #{0}: Please select the BOM No in Assembly Items").format(row.idx))

            bom_data = []

            warehouse = (self.sub_assembly_warehouse) if self.skip_available_sub_assembly_item else None
            if self.custom_split_sub_assembly_items:
                get_sub_assembly_items_split(row.bom_no, bom_data, row.planned_qty, self.company, warehouse=warehouse)
            else:
                get_sub_assembly_items(row.bom_no, bom_data, row.planned_qty, self.company, warehouse=warehouse)
                
            self.set_sub_assembly_items_based_on_level(row, bom_data, manufacturing_type)
            sub_assembly_items_store.extend(bom_data)

        if not sub_assembly_items_store and self.skip_available_sub_assembly_item:
            message = (
                _(
                    "As there are sufficient Sub Assembly Items, Work Order is not required for Warehouse {0}."
                ).format(self.sub_assembly_warehouse)
                + "<br><br>"
            )
            message += _(
                "If you still want to proceed, please disable 'Skip Available Sub Assembly Items' checkbox."
            )

            frappe.msgprint(message, title=_("Note"))

        if self.combine_sub_items:
            # Combine subassembly items
            sub_assembly_items_store = self.combine_subassembly_items(sub_assembly_items_store)

        for idx, row in enumerate(sub_assembly_items_store):
            row.idx = idx + 1
            self.append("sub_assembly_items", row)

        self.set_default_supplier_for_subcontracting_order()

def get_sub_assembly_items_split(bom_no, bom_data, to_produce_qty, company, warehouse=None, indent=0):
    data = get_bom_children(parent=bom_no)
    for d in data:
        if d.expandable:
            parent_item_code = frappe.get_cached_value("BOM", bom_no, "item")
            stock_qty = (d.stock_qty / d.parent_bom_qty) * flt(to_produce_qty)

            if warehouse:
                bin_details = get_bin_details(d, company, for_warehouse=warehouse)

                for _bin_dict in bin_details:
                    if _bin_dict.projected_qty > 0:
                        if _bin_dict.projected_qty > stock_qty:
                            stock_qty = 0
                            continue
                        else:
                            stock_qty = stock_qty - _bin_dict.projected_qty

            if stock_qty > 0:
                def make_row(qty):
                    return frappe._dict({
                        "parent_item_code":      parent_item_code,
                        "description":           d.description,
                        "production_item":       d.item_code,
                        "item_name":             d.item_name,
                        "stock_uom":             d.stock_uom,
                        "uom":                   d.stock_uom,
                        "bom_no":                d.value,
                        "is_sub_contracted_item":d.is_sub_contracted_item,
                        "bom_level":             indent,
                        "indent":                indent,
                        "stock_qty":             qty,
                    })
                
                whole = int(stock_qty)
                frac  = stock_qty - whole

                # append one row per full unit
                for _ in range(whole):
                    bom_data.append(make_row(1.0))

                # append the leftover fractional piece, if any
                if frac > 0:
                    bom_data.append(make_row(frac))

                if d.value:
                    get_sub_assembly_items_split(
                        d.value, bom_data, stock_qty, company, warehouse, indent=indent + 1
                    )