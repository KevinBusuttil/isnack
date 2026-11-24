# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""The Operator of a QC record (2026-11).

A QC record names its operator as an Employee, in ``operator``, picked as the
Operator Hub's Set Operator picks one: by ID or name. Only Active Employees are
offered. Unlike the Operator Hub, the Operator is not locked to the logged-in
user's Employee: the QC inspector who records a check names the operator whose
work was checked.

``operator_name`` holds that Employee's name, set on every save
(``check_operator``), so the record lists, the Quality Explorer and the print
show it as before. A record made before the Operator came keeps the name typed
on it, and needs no Operator when saved again or amended.

Quality users hold no permission on Employee, whose records carry personal data
(date of birth, bank and health details). They search Employees through
``search_operators`` and read an Employee's name through ``get_operator``, which
give no more than an Employee's ID, name and status, and only to a user who may
create or change QC records.
"""

import frappe
from frappe import _

# the record types that name an Employee as their Operator (the retired QC Oven
# Record keeps its typed Operator Name)
OPERATOR_DOCTYPES = (
    "QC Receiving Record",
    "QC Puffs Extruder Record",
    "QC Rice Extruder Record",
    "QC Frying Line Record",
    "QC Tasting Record",
    "QC Packaging Check",
    "QC Weight Check",
    "QC Metal Detector Log",
)


def may_record_checks() -> bool:
    """Whether the user may create or change records of a type that names an
    Operator: who records checks may look up the operators."""
    return any(
        frappe.has_permission(doctype, "create") or frappe.has_permission(doctype, "write")
        for doctype in OPERATOR_DOCTYPES
    )


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def search_operators(doctype, txt, searchfield, start, page_len, filters, as_dict=False, **kwargs):
    """The Operator's search: Active Employees whose ID or name holds ``txt``,
    by name, each with its name under the ID. None for a user who may not
    record checks (a query that raises a PermissionError reads as a method not
    found)."""
    if not may_record_checks():
        return []
    like = f"%{txt or ''}%"
    return frappe.get_all(
        "Employee",
        filters={"status": "Active"},
        or_filters={"name": ["like", like], "employee_name": ["like", like]},
        fields=["name", "employee_name"],
        order_by="employee_name asc, name asc",
        limit_start=start,
        limit_page_length=page_len,
        as_list=not as_dict,
    )


@frappe.whitelist()
def get_operator(employee: str) -> dict:
    """An Employee's name and status, for the Operator Name shown as the
    Operator is picked: {employee, employee_name, status}. Nothing for an
    Employee there is not, or for a user who may not record checks."""
    if not employee or not may_record_checks():
        return {}
    row = frappe.db.get_value("Employee", employee, ["name", "employee_name", "status"], as_dict=True)
    if not row:
        return {}
    return {"employee": row.name, "employee_name": row.employee_name, "status": row.status}


def check_operator(doc, method=None):
    """``before_validate`` of the QC records that name an Operator (doc_events).

    The Operator is required, except on a record made before it came, which
    keeps the name typed on it. An Operator newly picked is an Active Employee;
    one the record already had (or the record amended had) stays, even if the
    Employee has left since. Operator Name is the Operator's name, whatever was
    sent for it.

    Frappe runs before_validate even when a save skips validation
    (``ignore_validate``): then, as with ``ignore_mandatory`` for the Operator
    itself, nothing is refused, and only Operator Name is kept in step.

    A deleted record comes back (Deleted Document, Restore) as a new one under
    a new name, which Frappe does not mark: restored, a record made before is
    refused for want of an Operator, as the other fields made mandatory refuse
    it, and one whose Employee has left since is refused that Employee."""
    checking = not doc.flags.ignore_validate
    operator = doc.get("operator")
    before = _before(doc)
    if operator:
        row = frappe.db.get_value("Employee", operator, ["employee_name", "status"], as_dict=True)
        if not row:
            # (Frappe's link check, which runs first, refuses it unless told not to)
            if checking and not doc.flags.ignore_links:
                frappe.throw(_("Could not find Employee {0}.").format(frappe.bold(operator)), title=_("Operator"))
            return
        if checking and row.status != "Active" and operator != (before or {}).get("operator"):
            frappe.throw(
                _("{0} is not an active Employee ({1}): pick the Operator from the Employees who work here now.").format(
                    frappe.bold(row.employee_name or operator), _(row.status)
                ),
                title=_("Operator"),
            )
        doc.operator_name = row.employee_name or operator
        return

    typed = _typed_name(before)
    if typed:
        # made before the Operator came: the name typed on it stays as it was
        doc.operator_name = typed
        return
    if checking and not doc.flags.ignore_mandatory:
        frappe.throw(
            _("Value missing for {0}: {1}").format(_(doc.doctype), _("Operator")),
            frappe.MandatoryError,
            title=_("Missing Value"),
        )


def _before(doc):
    """The Operator and Operator Name the record had before: as saved, or, on a
    new amendment, the amended record's. None for a new record."""
    if not (doc.flags.in_insert or doc.is_new()):
        return frappe.db.get_value(doc.doctype, doc.name, ["operator", "operator_name"], as_dict=True)
    if doc.get("amended_from"):
        return frappe.db.get_value(doc.doctype, doc.amended_from, ["operator", "operator_name"], as_dict=True)
    return None


def _typed_name(before) -> str | None:
    """The operator name typed on a record made before the Operator came: one
    that has a name but no Operator."""
    if before and not before.get("operator") and before.get("operator_name"):
        return before.operator_name
    return None
