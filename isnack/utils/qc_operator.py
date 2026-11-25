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

Records kept on paper are entered in bulk with Data Import (2026-11), which
names the operator as the paper does: by name, in Operator Name, the Employee's
ID being unknown to it. A record so imported is the Employee's of that name
(``_operator_named``), the names compared whatever the case, the accents, the
apostrophes, full stops and dashes, and stray or doubled spaces; a name no
Employee has, or several have, is refused, so the Employee is added first (or,
for a name close to an Employee's, given by ID). The paper records work done
before: the Operator of a record imported may be an Employee who has left since,
though not one who had left by the record's date. An import updating a record
does not change its Operator Name.
"""

import unicodedata

import frappe
from frappe import _
from frappe.utils import cstr, escape_html, formatdate, getdate

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
    it, and one whose Employee has left since is refused that Employee.

    A new record imported (Data Import) with an Operator Name but no Operator
    is the Employee's of that name. A record imported is of work done before:
    its Operator, named or given by ID, may be an Employee who has left since,
    but not one who had left by the record's date (whatever their status now).
    Only a new one: a record saved, or amended, keeps what it had, as above; an
    import updating a record that sends another Operator Name, with the same
    Operator, is refused, as the name would be put back without a word."""
    checking = not doc.flags.ignore_validate
    operator = doc.get("operator")
    before = _before(doc)
    new = doc.flags.in_insert or doc.is_new()
    imported = bool(frappe.flags.in_import and new and not doc.get("amended_from"))
    if checking and frappe.flags.in_import and not new:
        _refuse_a_name_changed(doc, before)
    if not operator and imported:
        operator = doc.operator = _operator_named(
            doc.get("operator_name"), refuse=checking and not doc.flags.ignore_mandatory
        )
    if operator:
        row = frappe.db.get_value(
            "Employee", operator, ["employee_name", "status", "relieving_date"], as_dict=True
        )
        if not row:
            # (Frappe's link check, which runs first, refuses it unless told not to)
            if checking and not doc.flags.ignore_links:
                frappe.throw(_("Could not find Employee {0}.").format(_bold(operator)), title=_("Operator"))
            return
        if checking and operator != (before or {}).get("operator"):
            if imported:
                # work done before: by an Employee who may have left since
                _refuse_if_left_before(doc, row, operator)
            elif row.status != "Active":
                frappe.throw(
                    _("{0} is not an active Employee ({1}): pick the Operator from the Employees who work here now.").format(
                        _bold(row.employee_name or operator), _(row.status)
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


def _operator_named(name, refuse=True):
    """The Employee named ``name``, for a record imported with its operator's
    name: whatever their status, the paper being older than a namesake who may
    have joined, or left, since. The names are compared whatever the case, the
    accents and the spacing (``_name_key``), on both sides. None for no name,
    which is then refused as no Operator is; refused, unless told not to (then
    None), when no Employee has the name, or several have it."""
    key = _name_key(name)
    if not key:
        return None
    # (every Employee, whatever the user may read: the name is all that is compared)
    employees = frappe.get_all("Employee", fields=["name", "employee_name", "status"], order_by="name asc")
    found = [employee for employee in employees if _name_key(employee.employee_name) == key]
    if len(found) == 1:
        return found[0].name
    if refuse:
        shown = _bold(" ".join(cstr(name).split()))
        if found:
            frappe.throw(
                _("Several Employees are named {0} ({1}): give the Operator by Employee ID instead.").format(
                    shown,
                    escape_html(
                        ", ".join(
                            employee.name if employee.status == "Active" else f"{employee.name} ({_(employee.status)})"
                            for employee in found
                        )
                    ),
                ),
                title=_("Operator"),
            )
        near = [employee for employee in employees if _may_be(key, _name_key(employee.employee_name))]
        if near:
            # a middle name, an initial: not to be added again as a new Employee
            frappe.throw(
                _("No Employee is named {0}, but it may be {1}: give the Operator by Employee ID, or add {0} as an Employee if it is none of them.").format(
                    shown,
                    escape_html(", ".join(f"{employee.name} ({employee.employee_name})" for employee in near[:5])),
                ),
                title=_("Operator"),
            )
        frappe.throw(
            _("No Employee is named {0}: add {0} as an Employee first, or give the Operator by Employee ID.").format(shown),
            title=_("Operator"),
        )
    return None


def _may_be(key, other) -> bool:
    """Whether the names (as ``_name_key`` gives them) may be the same person's:
    the same last name, and the same first name or its initial; or every word
    of one in the other (a middle name left out)."""
    words, others = key.split(), other.split()
    if not words or not others:
        return False
    if words[-1] == others[-1] and _same_first(words[0], others[0]):
        return True
    return set(words) <= set(others) or set(others) <= set(words)


def _same_first(one, other) -> bool:
    return one == other or (len(one) == 1 and other.startswith(one)) or (len(other) == 1 and one.startswith(other))


# Letters Unicode does not take apart into a letter and an accent (the Maltese
# ħ, the other letters with a stroke, the dotless i); apostrophes and full stops
# left out (O'Brien, OBrien; J. Borg, J Borg) and dashes read as spaces
# (Mary-Anne, Mary Anne).
_PLAIN_LETTERS = str.maketrans(
    {"ħ": "h", "ł": "l", "ø": "o", "đ": "d", "ı": "i"}
    | dict.fromkeys("'’‘ʼ`´.", None)
    | dict.fromkeys("-‐‑‒–—―−", " ")
)


def _name_key(name) -> str:
    """A name as an import compares it: whatever the case, the accents (Ġ as G,
    ħ as h), the apostrophes, full stops and dashes, and stray, doubled or
    non-breaking spaces. ERPNext joins an Employee's first, middle and last
    names as typed, so an Employee may be named with a stray space as well as
    the file."""
    text = unicodedata.normalize("NFKD", cstr(name).casefold())
    text = "".join(c for c in text if not unicodedata.combining(c)).translate(_PLAIN_LETTERS)
    return " ".join(text.split())


def _refuse_if_left_before(doc, row, operator):
    """A record imported names an Employee: refused if they had left by the
    record's date (their Relieving Date is before it), whatever their status. A
    record with no date yet is dated today, as Frappe dates it."""
    record_date = getdate(doc.get("record_date"))
    if row.relieving_date and record_date > getdate(row.relieving_date):
        frappe.throw(
            _("{0} had left by this record's date ({1}; their Relieving Date is {2}): give the Operator who did the work, or check the Record Date.").format(
                _bold(row.employee_name or operator), formatdate(record_date), formatdate(row.relieving_date)
            ),
            title=_("Operator"),
        )


def _refuse_a_name_changed(doc, before):
    """An import updating a saved record sends another Operator Name, the
    Operator unchanged: the name is the Operator's (or, on a record made before
    the Operator came, the one typed on it), and would be put back without a
    word. Refused, so the Operator is changed by its Employee ID."""
    if not before or (doc.get("operator") or None) != (before.get("operator") or None):
        return
    sent = doc.get("operator_name")
    if _name_key(sent) == _name_key(before.get("operator_name")):
        return
    if before.get("operator") and _name_key(sent) == _name_key(
        frappe.db.get_value("Employee", before.operator, "employee_name")
    ):
        return  # the Employee's name now (renamed since the record was saved)
    frappe.throw(
        _("An import does not change Operator Name ({0}, sent as {1}): give the Operator's Employee ID in Operator to change the Operator.").format(
            _bold(before.get("operator_name")), _bold(sent)
        ),
        title=_("Operator"),
    )


def _bold(text) -> str:
    """``text`` (a value sent, or an Employee's name) in bold, shown as text:
    Frappe shows a message as HTML, the Data Import Log too."""
    return frappe.bold(escape_html(cstr(text)))


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
