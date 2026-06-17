"""Seed the default escalation rules (idempotent, keyed by rule_name)."""

import frappe

DEFAULT_RULES = [
    {
        "rule_name": "7 days before due",
        "days_before_due": 7,
        "notify_technician": 1,
        "notify_maintenance_manager": 1,
    },
    {
        "rule_name": "3 days before due",
        "days_before_due": 3,
        "notify_technician": 1,
    },
    {
        "rule_name": "1 day before due",
        "days_before_due": 1,
        "notify_technician": 1,
    },
    {
        "rule_name": "Due today",
        "days_before_due": 0,
        "days_after_due": 0,
        "notify_technician": 1,
    },
    {
        "rule_name": "Overdue (1 day)",
        "days_after_due": 1,
        "notify_technician": 1,
        "notify_maintenance_manager": 1,
        "repeat_daily_until_resolved": 1,
    },
    {
        "rule_name": "Overdue 3 days - escalate",
        "days_after_due": 3,
        "notify_maintenance_manager": 1,
        "notify_operations_manager": 1,
        "repeat_daily_until_resolved": 1,
    },
]


def execute():
    if not frappe.db.exists("DocType", "Maintenance Escalation Rule"):
        return
    for rule in DEFAULT_RULES:
        if frappe.db.exists("Maintenance Escalation Rule", {"rule_name": rule["rule_name"]}):
            continue
        doc = frappe.get_doc({
            "doctype": "Maintenance Escalation Rule",
            "enabled": 1,
            "notification_channel": "Notification Log",
            **rule,
        })
        doc.insert(ignore_permissions=True)
    frappe.db.commit()
