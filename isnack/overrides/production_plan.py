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
    def before_save(self):
        #    This method will populate the 'total_estimated_cost' field.
        self.calculate_total_estimated_cost()

    def calculate_total_estimated_cost(self):
        """
        Calculates the total estimated cost of the production plan
        by summing up the total cost of each item's active Bill of Materials (BOM)
        multiplied by its quantity in the plan.
        """
        total_cost = 0.0

        # The 'items' is the child table in the Production Plan doctype
        if self.po_items:
            for item_row in self.po_items:
                if item_row.item_code and item_row.planned_qty:
                    try:
                        # Fetch the name of the active BOM for the current item
                        # We assume 'is_active: 1' identifies the primary BOM to use for costing.
                        bom_name = frappe.db.get_value(
                            "BOM",
                            {"item": item_row.item_code, "is_active": 1},
                            "name"
                        )

                        if bom_name:
                            # Get the full BOM document to access its total_cost field
                            bom_doc = frappe.get_doc("BOM", bom_name)
                            if bom_doc.total_cost is not None:
                                # Add the cost of this item (BOM total_cost * quantity) to the total
                                cost_per_bom_unit = flt(bom_doc.total_cost) / flt(bom_doc.quantity)
                                total_cost += cost_per_bom_unit * flt(item_row.planned_qty)
                            else:
                                frappe.log_error(
                                    f"BOM '{bom_name}' for item '{item_row.item_code}' has no 'total_cost'.",
                                    "Production Plan Cost Calculation Warning"
                                )
                        else:
                            frappe.log_warn(
                                f"No active BOM found for item '{item_row.item_code}' in Production Plan '{self.name}'. "
                                "This item's cost will not be included in the total.",
                                "Production Plan Cost Calculation Warning"
                            )
                    except Exception as e:
                        # Log any errors during BOM fetching or calculation
                        frappe.log_error(
                            f"Error fetching BOM cost for item '{item_row.item_code}' in Production Plan '{self.name}': {e}",
                            "Production Plan Cost Calculation Error"
                        )
                        # Optionally, you might want to raise an error or set a specific status
                        # For now, we'll just log and continue, effectively treating this item's cost as 0 for the total.

        # Set the calculated total cost to the custom field on the Production Plan document
        self.custom_total_estimated_cost = total_cost

        # Optional: For debugging, you can use frappe.msgprint
        # frappe.msgprint(f"Calculated Total Estimated Cost: {self.total_estimated_cost}")

    @frappe.whitelist()
    def get_sub_assembly_items(self, manufacturing_type=None):
        "Fetch sub assembly items and optionally combine them."
        self.sub_assembly_items = []
        sub_assembly_items_store = []  # temporary store to process all subassembly items
        bin_details = frappe._dict()

        for row in self.po_items:
            if self.skip_available_sub_assembly_item and not self.sub_assembly_warehouse:
                frappe.throw(_("Row #{0}: Please select the Sub Assembly Warehouse").format(row.idx))

            if not row.item_code:
                frappe.throw(_("Row #{0}: Please select Item Code in Assembly Items").format(row.idx))

            if not row.bom_no:
                frappe.throw(_("Row #{0}: Please select the BOM No in Assembly Items").format(row.idx))

            bom_data = []

            if self.custom_split_sub_assembly_items:
                get_sub_assembly_items_split(
                    [item.production_item for item in sub_assembly_items_store],
                    bin_details,
                    row.bom_no,
                    bom_data,
                    row.planned_qty,
                    self.company,
                    warehouse=self.sub_assembly_warehouse,
                    skip_available_sub_assembly_item=self.skip_available_sub_assembly_item,
                )
            else:
                get_sub_assembly_items(
                    [item.production_item for item in sub_assembly_items_store],
                    bin_details,
                    row.bom_no,
                    bom_data,
                    row.planned_qty,
                    self.company,
                    warehouse=self.sub_assembly_warehouse,
                    skip_available_sub_assembly_item=self.skip_available_sub_assembly_item,
                )

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


# def get_sub_assembly_items_split(bom_no, bom_data, to_produce_qty, company, warehouse=None, indent=0):
#     data = get_bom_children(parent=bom_no)
#     for d in data:
#         if d.expandable:
#             parent_item_code = frappe.get_cached_value("BOM", bom_no, "item")
#             stock_qty = (d.stock_qty / d.parent_bom_qty) * flt(to_produce_qty)

#             if warehouse:
#                 bin_details = get_bin_details(d, company, for_warehouse=warehouse)

#                 for _bin_dict in bin_details:
#                     if _bin_dict.projected_qty > 0:
#                         if _bin_dict.projected_qty > stock_qty:
#                             stock_qty = 0
#                             continue
#                         else:
#                             stock_qty = stock_qty - _bin_dict.projected_qty

#             if stock_qty > 0:
#                 def make_row(qty):
#                     return frappe._dict({
#                         "parent_item_code":      parent_item_code,
#                         "description":           d.description,
#                         "production_item":       d.item_code,
#                         "item_name":             d.item_name,
#                         "stock_uom":             d.stock_uom,
#                         "uom":                   d.stock_uom,
#                         "bom_no":                d.value,
#                         "is_sub_contracted_item":d.is_sub_contracted_item,
#                         "bom_level":             indent,
#                         "indent":                indent,
#                         "stock_qty":             qty,
#                     })
                
#                 whole = int(stock_qty)
#                 frac  = stock_qty - whole

#                 # append one row per full unit
#                 for _ in range(whole):
#                     bom_data.append(make_row(1.0))

#                 # append the leftover fractional piece, if any
#                 if frac > 0:
#                     bom_data.append(make_row(frac))

#                 if d.value:
#                     get_sub_assembly_items_split(
#                         d.value, bom_data, stock_qty, company, warehouse, indent=indent + 1
#                     )

def get_sub_assembly_items_split(
    sub_assembly_items,
    bin_details,
    bom_no,
    bom_data,
    to_produce_qty,
    company,
    warehouse=None,
    indent=0,
    skip_available_sub_assembly_item=False,
):
    from frappe import _dict
    data = get_bom_children(parent=bom_no)
    parent_item_code = frappe.get_cached_value("BOM", bom_no, "item")

    for d in data:
        if not d.expandable:
            continue

        total_qty = (d.stock_qty / d.parent_bom_qty) * flt(to_produce_qty)

        print(f'SPLIT {d} {d.item_code} {d.stock_qty} {d.parent_bom_qty} {flt(to_produce_qty)}  TOTAL QTY: {total_qty}')

        if skip_available_sub_assembly_item and d.item_code not in sub_assembly_items:
            bin_details.setdefault(d.item_code, get_bin_details(d, company, for_warehouse=warehouse))

            for _bin_dict in bin_details[d.item_code]:
                if _bin_dict.projected_qty > 0:
                    if _bin_dict.projected_qty >= total_qty:
                        _bin_dict.projected_qty -= total_qty
                        total_qty = 0
                        continue
                    else:
                        total_qty = total_qty - _bin_dict.projected_qty
                        sub_assembly_items.append(d.item_code)
        elif warehouse:
            bin_details.setdefault(d.item_code, get_bin_details(d, company, for_warehouse=warehouse))

        if total_qty <= 0:
            continue

        # 3) Determine chunk_size from the child’s own BOM output qty
        if d.value:
            chunk_size = flt(frappe.db.get_value("BOM", d.value, "quantity") or 0)
        else:
            # if there is no further BOM, treat entire quantity as one chunk
            chunk_size = total_qty

        if chunk_size <= 0:
            continue

        # how many full chunks, and the leftover
        num_full  = int(total_qty // chunk_size)
        remainder = total_qty - (chunk_size * num_full)

        def make_row(qty):
            return frappe._dict({
                "parent_item_code":       parent_item_code,
                "description":            d.description,
                "production_item":        d.item_code,
                "item_name":              d.item_name,
                "stock_uom":              d.stock_uom,
                "uom":                    d.stock_uom,
                "bom_no":                 d.value,
                "is_sub_contracted_item": d.is_sub_contracted_item,
                "bom_level":              indent,
                "indent":                 indent,
                "stock_qty":              qty,
            })

        # 4a) Append & recurse for each full chunk
        for _ in range(num_full):
            bom_data.append(make_row(chunk_size))
            if d.value:
                get_sub_assembly_items_split(
                    sub_assembly_items,
                    bin_details,
                    d.value,
                    bom_data,
                    chunk_size,
                    company,
                    warehouse=warehouse,
                    indent=indent + 1,
                    skip_available_sub_assembly_item=skip_available_sub_assembly_item,
                )

        # 4b) Append & recurse for the final remainder (if any)
        if remainder > 0:
            bom_data.append(make_row(remainder))
            if d.value:
                get_sub_assembly_items_split(
                    sub_assembly_items,
                    bin_details,
                    d.value,
                    bom_data,
                    remainder,
                    company,
                    warehouse=warehouse,
                    indent=indent + 1,
                    skip_available_sub_assembly_item=skip_available_sub_assembly_item,
                )

