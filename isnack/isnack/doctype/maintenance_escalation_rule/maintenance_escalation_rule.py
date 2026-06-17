import frappe
from frappe.model.document import Document


class MaintenanceEscalationRule(Document):
    def validate(self):
        if not (self.days_before_due or self.days_after_due):
            frappe.throw(
                frappe._("Set either 'Days Before Due' or 'Days After Due'.")
            )
        if not (
            self.notify_technician
            or self.notify_maintenance_manager
            or self.notify_operations_manager
        ):
            frappe.throw(frappe._("Select at least one recipient to notify."))
