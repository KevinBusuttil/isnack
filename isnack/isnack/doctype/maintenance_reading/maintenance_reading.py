import frappe
from frappe.model.document import Document


class MaintenanceReading(Document):
    def validate(self):
        self.set_asset_from_log()
        self.flag_out_of_range()

    def set_asset_from_log(self):
        if self.asset_maintenance_log and not self.asset:
            self.asset = frappe.db.get_value(
                "Asset Maintenance Log", self.asset_maintenance_log, "asset_name"
            )

    def flag_out_of_range(self):
        self.is_out_of_range = 0
        value = self.reading_value
        if value is None:
            return
        if self.min_value and value < self.min_value:
            self.is_out_of_range = 1
        if self.max_value and value > self.max_value:
            self.is_out_of_range = 1
