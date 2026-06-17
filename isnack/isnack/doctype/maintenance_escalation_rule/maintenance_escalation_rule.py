import frappe
from frappe.model.document import Document


class MaintenanceEscalationRule(Document):
    def validate(self):
        # days_before_due = days_after_due = 0 is valid: it means "due today".
        if (self.days_before_due or 0) < 0:
            frappe.throw(frappe._("'Days Before Due' cannot be negative."))
        if (self.days_after_due or 0) < 0:
            frappe.throw(frappe._("'Days After Due' cannot be negative."))
        if not (
            self.notify_technician
            or self.notify_maintenance_manager
            or self.notify_operations_manager
        ):
            frappe.throw(frappe._("Select at least one recipient to notify."))
