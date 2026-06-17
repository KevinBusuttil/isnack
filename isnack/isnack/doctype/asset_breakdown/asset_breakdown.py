import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class AssetBreakdown(Document):
    def validate(self):
        if self.status == "Assigned" and not self.assigned_to:
            frappe.throw(frappe._("Set 'Assigned To' when status is Assigned."))
        if self.status == "Resolved":
            if not self.resolved_by:
                self.resolved_by = frappe.session.user
            if not self.resolved_on:
                self.resolved_on = now_datetime()
