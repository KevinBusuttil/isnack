"""Checklist generation and response capture for maintenance logs."""

import frappe
from frappe import _
from frappe.utils import now_datetime

from isnack.utils.maintenance import ensure_log_access


@frappe.whitelist()
def ensure_checklist_for_log(asset_maintenance_log):
    """Generate Maintenance Checklist Response rows from the best-matching
    template, if they don't already exist. Idempotent."""
    log = frappe.get_doc("Asset Maintenance Log", asset_maintenance_log)

    if frappe.db.exists("Maintenance Checklist Response",
                        {"asset_maintenance_log": asset_maintenance_log}):
        return {"created": 0, "already": True}

    from isnack.isnack.doctype.maintenance_checklist_template.maintenance_checklist_template \
        import find_matching_template

    asset_category = None
    item_code = None
    company = None
    if log.get("asset_name"):
        asset_category, item_code, company = frappe.db.get_value(
            "Asset", log.asset_name, ["asset_category", "item_code", "company"]
        ) or (None, None, None)

    template_name = find_matching_template(
        asset_category=asset_category,
        item_code=item_code,
        maintenance_type=log.get("maintenance_type"),
        maintenance_task=log.get("task"),
        company=company,
    )
    if not template_name:
        frappe.db.set_value("Asset Maintenance Log", asset_maintenance_log,
                            "custom_checklist_generated", 1, update_modified=False)
        return {"created": 0, "template": None}

    template = frappe.get_doc("Maintenance Checklist Template", template_name)
    created = 0
    for item in sorted(template.items, key=lambda r: (r.sequence or 0, r.idx)):
        resp = frappe.get_doc({
            "doctype": "Maintenance Checklist Response",
            "asset_maintenance_log": asset_maintenance_log,
            "checklist_template": template_name,
            "sequence": item.sequence,
            "instruction": item.instruction,
            "input_type": item.input_type,
            "required": item.required,
            "is_safety_step": item.is_safety_step,
            "expected_value": item.expected_value,
            "min_value": item.min_value,
            "max_value": item.max_value,
            "uom": item.uom,
            "requires_photo": item.requires_photo,
            "requires_comment": item.requires_comment,
        })
        resp.insert(ignore_permissions=True)
        created += 1

    frappe.db.set_value("Asset Maintenance Log", asset_maintenance_log,
                        "custom_checklist_generated", 1, update_modified=False)
    return {"created": created, "template": template_name}


@frappe.whitelist()
def save_checklist_response(name, response_value=None, pass_fail=None,
                            numeric_value=None, comment=None, attachment=None):
    """Save a single checklist response row (technician)."""
    log = frappe.db.get_value("Maintenance Checklist Response", name,
                              "asset_maintenance_log")
    if not log:
        frappe.throw(_("Checklist response not found."))
    ensure_log_access(log, write=True)

    doc = frappe.get_doc("Maintenance Checklist Response", name)
    if response_value is not None:
        doc.response_value = response_value
    if pass_fail is not None:
        doc.pass_fail = pass_fail
    if numeric_value is not None and numeric_value != "":
        doc.numeric_value = frappe.utils.flt(numeric_value)
    if comment is not None:
        doc.comment = comment
    if attachment is not None:
        doc.attachment = attachment
    doc.completed_by = frappe.session.user
    doc.completed_on = now_datetime()
    doc.save(ignore_permissions=True)
    return {"ok": True, "is_out_of_range": doc.is_out_of_range}
