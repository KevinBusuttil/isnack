import frappe
from frappe.model.document import Document


class MaintenanceSparePart(Document):
    def validate(self):
        if self.asset_maintenance_log and not self.asset:
            self.asset = frappe.db.get_value(
                "Asset Maintenance Log", self.asset_maintenance_log, "asset_name"
            )
        self.refresh_available_qty()

    def refresh_available_qty(self):
        if self.item_code and self.source_warehouse:
            self.available_qty = (
                frappe.db.get_value(
                    "Bin",
                    {"item_code": self.item_code, "warehouse": self.source_warehouse},
                    "actual_qty",
                )
                or 0
            )
        else:
            self.available_qty = 0
