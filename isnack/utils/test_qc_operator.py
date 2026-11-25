# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""The Operator of a QC record (qc_operator.py, quality_hub_operator.js): an
Employee, looked up without Employee permission (no database)."""

import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import unittest
from unittest.mock import patch

import frappe
from isnack.isnack.page.quality_hub.quality_hub import QC_DOCTYPES
from isnack.utils import qc_operator
from isnack.utils.qc_operator import (
    OPERATOR_DOCTYPES,
    check_operator,
    get_operator,
    may_record_checks,
    search_operators,
)

APP_DIR = os.path.join(os.path.dirname(__file__), "..")
DOCTYPE_DIR = os.path.join(APP_DIR, "isnack", "doctype")
SCRIPT = os.path.join(APP_DIR, "public", "js", "quality_hub_operator.js")

EMPLOYEES = {
    "HR-EMP-00001": frappe._dict(employee_name="Joan Borg", status="Active"),
    "HR-EMP-00002": frappe._dict(employee_name="Mark Vella", status="Left", relieving_date="2026-06-30"),
}


def _doctype(name):
    folder = name.lower().replace(" ", "_")
    with open(os.path.join(DOCTYPE_DIR, folder, f"{folder}.json")) as fh:
        return json.load(fh)


class _Doc(frappe._dict):
    """A QC record as check_operator sees it: new (inserting) or saved."""

    def __init__(self, new=False, flags=None, **fields):
        super().__init__(doctype="QC Weight Check", name="QCI-2026-00001", **fields)
        self.flags = frappe._dict(flags or {})
        if new:
            self.flags.in_insert = True

    def is_new(self):
        return bool(self.flags.in_insert)


def _db(saved=None):
    """frappe.db.get_value over EMPLOYEES and the QC records ``saved`` (name:
    {operator, operator_name})."""
    saved = saved or {}

    def get_value(doctype, name, fields, as_dict=False):
        if doctype == "Employee":
            row = EMPLOYEES.get(name)
            if isinstance(fields, str):
                return row.get(fields) if row else None
            if row and "name" in fields:
                return frappe._dict(name=name, **row)
            return row
        row = saved.get(name)
        return frappe._dict(row) if row is not None else None

    return get_value


class TestCheckOperator(unittest.TestCase):
    """check_operator, before_validate of the eight record types."""

    def _check(self, doc, saved=None):
        with patch("frappe.db.get_value", side_effect=_db(saved)):
            check_operator(doc)
        return doc

    def test_a_new_record_needs_an_operator(self):
        with self.assertRaisesRegex(frappe.MandatoryError, "Value missing for QC Weight Check: Operator"):
            self._check(_Doc(new=True))
        # a name typed with it, as on a page loaded before the Operator came, is no Operator
        with self.assertRaises(frappe.MandatoryError):
            self._check(_Doc(new=True, operator_name="J. Borg"))

    def test_as_frappe_does_when_told_not_to_check(self):
        # before_validate runs even when validation is skipped
        self._check(_Doc(new=True, flags={"ignore_validate": 1}))
        self._check(_Doc(new=True, flags={"ignore_mandatory": 1}))

    def test_the_name_is_the_employees(self):
        doc = self._check(_Doc(new=True, operator="HR-EMP-00001", operator_name="Someone else"))
        self.assertEqual(doc.operator_name, "Joan Borg")

    def test_an_employee_who_left_is_refused_when_picked(self):
        with self.assertRaisesRegex(frappe.ValidationError, "is not an active Employee"):
            self._check(_Doc(new=True, operator="HR-EMP-00002"))
        # on a saved record, picked instead of another
        with self.assertRaisesRegex(frappe.ValidationError, "is not an active Employee"):
            self._check(
                _Doc(operator="HR-EMP-00002"),
                saved={"QCI-2026-00001": {"operator": "HR-EMP-00001", "operator_name": "Joan Borg"}},
            )

    def test_one_the_record_had_stays(self):
        # saved again, or amended, naming someone who has left since
        doc = self._check(
            _Doc(operator="HR-EMP-00002"),
            saved={"QCI-2026-00001": {"operator": "HR-EMP-00002", "operator_name": "Mark Vella"}},
        )
        self.assertEqual(doc.operator_name, "Mark Vella")
        doc = self._check(
            _Doc(new=True, operator="HR-EMP-00002", amended_from="QCI-2026-00000"),
            saved={"QCI-2026-00000": {"operator": "HR-EMP-00002", "operator_name": "Mark Vella"}},
        )
        self.assertEqual(doc.operator_name, "Mark Vella")

    def test_a_record_made_before_keeps_its_typed_name(self):
        saved = {"QCI-2026-00001": {"operator": None, "operator_name": "J. Borg"}}
        # saved again without an Operator: the typed name stays, even if sent changed
        doc = self._check(_Doc(operator_name="Changed by hand"), saved=saved)
        self.assertEqual(doc.operator_name, "J. Borg")
        # amended: the amendment keeps it too
        doc = self._check(
            _Doc(new=True, amended_from="QCI-2026-00001", operator_name="J. Borg"), saved=saved
        )
        self.assertEqual(doc.operator_name, "J. Borg")
        # an Employee picked for it: the Employee's name
        doc = self._check(_Doc(operator="HR-EMP-00001", operator_name="J. Borg"), saved=saved)
        self.assertEqual(doc.operator_name, "Joan Borg")

    def test_a_record_made_since_keeps_an_operator(self):
        saved = {"QCI-2026-00001": {"operator": "HR-EMP-00001", "operator_name": "Joan Borg"}}
        with self.assertRaises(frappe.MandatoryError):
            self._check(_Doc(operator_name="Joan Borg"), saved=saved)
        # its amendment too
        with self.assertRaises(frappe.MandatoryError):
            self._check(_Doc(new=True, amended_from="QCI-2026-00001", operator_name="Joan Borg"), saved=saved)

    def test_an_employee_there_is_not(self):
        with self.assertRaisesRegex(frappe.ValidationError, "Could not find Employee"):
            self._check(_Doc(new=True, operator="HR-EMP-09999"))
        # Frappe's link check, which runs first, was told not to check
        self._check(_Doc(new=True, operator="HR-EMP-09999", flags={"ignore_links": 1}))


class TestAnImport(unittest.TestCase):
    """check_operator in a Data Import, which names the operator by name."""

    @contextlib.contextmanager
    def _importing(self, employees=None):
        """In a Data Import, the Employees being ``employees`` (ID: their name,
        status and relieving date), EMPLOYEES unless given."""
        employees = EMPLOYEES if employees is None else employees
        roster = [
            frappe._dict(name=name, employee_name=row.employee_name, status=row.status)
            for name, row in employees.items()
        ]
        with patch.dict(frappe.flags, {"in_import": True}), patch.dict(EMPLOYEES, employees, clear=True), patch(
            "frappe.get_all", return_value=roster
        ) as get_all:
            yield get_all

    def _check(self, doc, saved=None):
        with patch("frappe.db.get_value", side_effect=_db(saved)):
            check_operator(doc)
        return doc

    def test_the_operator_is_the_employee_of_the_name(self):
        # a register on paper names its operator, not the Employee's ID
        with self._importing() as get_all:
            doc = self._check(_Doc(new=True, record_date="2026-03-02", operator_name="  joan   BORG "))
        self.assertEqual((doc.operator, doc.operator_name), ("HR-EMP-00001", "Joan Borg"))
        # every Employee, whatever the user may read: the names are compared here
        get_all.assert_called_once_with("Employee", fields=["name", "employee_name", "status"], order_by="name asc")

    def test_names_are_compared_whatever_the_case_the_accents_or_the_spacing(self):
        # on both sides: ERPNext joins an Employee's first and last names as typed
        employees = {
            "HR-EMP-00011": frappe._dict(employee_name="Paul  Grech ", status="Active"),
            "HR-EMP-00012": frappe._dict(employee_name=" Ġorġ Żammit", status="Active"),
            "HR-EMP-00013": frappe._dict(employee_name="Ħilda\u00a0Camilleri", status="Active"),
            "HR-EMP-00014": frappe._dict(employee_name="Mary-Anne O’Brien", status="Active"),
        }
        for typed, employee in (
            ("Paul Grech", "HR-EMP-00011"),
            ("Paul  Grech ", "HR-EMP-00011"),  # the name as the Employee holds it
            ("PAUL GRECH", "HR-EMP-00011"),
            ("Paul\tGrech", "HR-EMP-00011"),
            ("Gorg Zammit", "HR-EMP-00012"),
            ("ġorġ żammit", "HR-EMP-00012"),
            ("Hilda Camilleri", "HR-EMP-00013"),
            # apostrophes and full stops left out, dashes read as spaces
            ("Mary Anne OBrien", "HR-EMP-00014"),
            ("mary-anne o'brien", "HR-EMP-00014"),
            ("Mary Anne O.Brien", "HR-EMP-00014"),
        ):
            with self._importing(employees):
                doc = self._check(_Doc(new=True, record_date="2026-03-02", operator_name=typed))
            self.assertEqual((doc.operator, doc.operator_name), (employee, employees[employee].employee_name), typed)
        # other letters are other names
        with self._importing(employees), self.assertRaisesRegex(frappe.ValidationError, "No Employee is named"):
            self._check(_Doc(new=True, record_date="2026-03-02", operator_name="Paula Grechi"))

    def test_a_name_no_one_or_several_have_is_refused(self):
        with self._importing(), self.assertRaisesRegex(
            frappe.ValidationError, "No Employee is named .*Paul Grech.*: add .*Paul Grech.* as an Employee first"
        ):
            self._check(_Doc(new=True, record_date="2026-03-02", operator_name=" Paul   Grech"))
        # a namesake who has left counts too: the paper may be theirs
        employees = {
            **EMPLOYEES,
            "HR-EMP-00003": frappe._dict(employee_name="joan borg", status="Left", relieving_date="2025-12-31"),
        }
        with self._importing(employees), self.assertRaisesRegex(
            frappe.ValidationError,
            r"Several Employees are named .*Joan Borg.* \(HR-EMP-00001, HR-EMP-00003 \(Left\)\): give the Operator by Employee ID",
        ):
            self._check(_Doc(new=True, record_date="2026-03-02", operator_name="Joan Borg"))
        # with no name either, the Operator is missing, as ever
        with self._importing() as get_all, self.assertRaises(frappe.MandatoryError):
            self._check(_Doc(new=True, record_date="2026-03-02", operator_name=" "))
        get_all.assert_not_called()

    def test_an_employee_who_has_left_since_may_be_the_operator(self):
        # the paper records work done before: by name, or by ID
        for fields in ({"operator_name": "mark vella"}, {"operator": "HR-EMP-00002"}):
            for record_date in ("2026-03-02", "2026-06-30"):
                with self._importing():
                    doc = self._check(_Doc(new=True, record_date=record_date, **fields))
                self.assertEqual((doc.operator, doc.operator_name), ("HR-EMP-00002", "Mark Vella"), fields)
            # not one who had left by the record's date
            with self._importing(), self.assertRaisesRegex(
                frappe.ValidationError, "Mark Vella.* had left by this record's date"
            ):
                self._check(_Doc(new=True, record_date="2026-07-01", **fields))
        # an Employee newly picked outside an import is an Active one, as ever
        with patch.dict(frappe.flags, {"in_import": False}), self.assertRaisesRegex(
            frappe.ValidationError, "is not an active Employee"
        ):
            self._check(_Doc(new=True, record_date="2026-03-02", operator="HR-EMP-00002"))
        # and an amendment imported keeps the rules of an amendment
        with self._importing(), self.assertRaisesRegex(frappe.ValidationError, "is not an active Employee"):
            self._check(
                _Doc(new=True, record_date="2026-03-02", amended_from="QCI-2026-00000", operator="HR-EMP-00002"),
                saved={"QCI-2026-00000": {"operator": "HR-EMP-00001", "operator_name": "Joan Borg"}},
            )

    def test_a_name_close_to_an_employees_is_not_added_again(self):
        # a middle name left out, or an initial: give the ID, rather than add a second Employee
        employees = {**EMPLOYEES, "HR-EMP-00021": frappe._dict(employee_name="Karl Paul Borg", status="Active")}
        for typed in ("Karl Borg", "K. Borg", "Karl Paul Anthony Borg"):
            with self._importing(employees), self.assertRaisesRegex(
                frappe.ValidationError,
                r"No Employee is named .*, but it may be HR-EMP-00021 \(Karl Paul Borg\): give the Operator by Employee ID, or add .* as an Employee if it is none of them",
            ):
                self._check(_Doc(new=True, record_date="2026-03-02", operator_name=typed))
        # a name nobody's is close to: add the Employee
        with self._importing(employees), self.assertRaises(frappe.ValidationError) as refused:
            self._check(_Doc(new=True, record_date="2026-03-02", operator_name="Rita Zahra"))
        self.assertNotIn("it may be", str(refused.exception))

    def test_an_employee_who_had_left_by_the_records_date_is_refused_whatever_their_status(self):
        # an Active Employee given a Relieving Date (leaving, or put back since)
        employees = {"HR-EMP-00031": frappe._dict(employee_name="Lina Spiteri", status="Active", relieving_date="2026-05-31")}
        with self._importing(employees):
            doc = self._check(_Doc(new=True, record_date="2026-05-31", operator_name="Lina Spiteri"))
        self.assertEqual(doc.operator, "HR-EMP-00031")
        with self._importing(employees), self.assertRaisesRegex(frappe.ValidationError, "had left by this record's date"):
            self._check(_Doc(new=True, record_date="2026-06-01", operator_name="Lina Spiteri"))

    def test_an_import_updating_a_record_does_not_change_its_operator_name(self):
        saved = {"QCI-2026-00001": {"operator": "HR-EMP-00001", "operator_name": "Joan Borg"}}
        with self._importing(), self.assertRaisesRegex(
            frappe.ValidationError, "An import does not change Operator Name .*Joan Borg.*, sent as .*Mark Vella"
        ):
            self._check(_Doc(operator="HR-EMP-00001", operator_name="Mark Vella"), saved=saved)
        with self._importing({**EMPLOYEES, "HR-EMP-00004": frappe._dict(employee_name="Rita Zahra", status="Active")}):
            # the same name, as typed
            doc = self._check(_Doc(operator="HR-EMP-00001", operator_name=" joan  BORG"), saved=saved)
            self.assertEqual(doc.operator_name, "Joan Borg")
            # another Operator, by ID, the file's name left as it was: the new Operator's name
            doc = self._check(_Doc(operator="HR-EMP-00004", operator_name="Joan Borg"), saved=saved)
            self.assertEqual(doc.operator_name, "Rita Zahra")
            # the Employee's name now, renamed since the record was saved
            renamed = {"QCI-2026-00001": {"operator": "HR-EMP-00001", "operator_name": "Joan B."}}
            doc = self._check(_Doc(operator="HR-EMP-00001", operator_name="Joan Borg"), saved=renamed)
            self.assertEqual(doc.operator_name, "Joan Borg")
        # a record made before keeps its typed name: not changed by an import either
        typed = {"QCI-2026-00001": {"operator": None, "operator_name": "J. Borg"}}
        with self._importing(), self.assertRaisesRegex(frappe.ValidationError, "An import does not change Operator Name"):
            self._check(_Doc(operator_name="John Borg"), saved=typed)
        # outside an import, a form sending another name is put right, as ever
        with patch.dict(frappe.flags, {"in_import": False}):
            doc = self._check(_Doc(operator="HR-EMP-00001", operator_name="Mark Vella"), saved=saved)
        self.assertEqual(doc.operator_name, "Joan Borg")

    def test_what_was_sent_is_shown_as_text(self):
        # Frappe shows a message as HTML, the Data Import Log too
        with self._importing(), self.assertRaises(frappe.ValidationError) as refused:
            self._check(_Doc(new=True, record_date="2026-03-02", operator_name="<img src=x onerror=alert(1)>"))
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", str(refused.exception))
        self.assertNotIn("<img", str(refused.exception))

    def test_an_operator_given_is_taken(self):
        with self._importing() as get_all:
            doc = self._check(_Doc(new=True, record_date="2026-03-02", operator="HR-EMP-00001", operator_name="Someone else"))
        self.assertEqual((doc.operator, doc.operator_name), ("HR-EMP-00001", "Joan Borg"))
        get_all.assert_not_called()

    def test_only_a_new_record_is_looked_up(self):
        # a record saved (an import updating it) or amended keeps what it had
        saved = {"QCI-2026-00001": {"operator": None, "operator_name": "J. Borg"}}
        with self._importing() as get_all:
            doc = self._check(_Doc(operator_name="J. Borg"), saved=saved)
            self.assertEqual((doc.get("operator"), doc.operator_name), (None, "J. Borg"))
            doc = self._check(_Doc(new=True, amended_from="QCI-2026-00001", operator_name="J. Borg"), saved=saved)
            self.assertEqual((doc.get("operator"), doc.operator_name), (None, "J. Borg"))
        get_all.assert_not_called()

    def test_outside_an_import_a_name_is_no_operator(self):
        with patch.dict(frappe.flags, {"in_import": False}), patch("frappe.get_all") as get_all:
            with self.assertRaises(frappe.MandatoryError):
                self._check(_Doc(new=True, operator_name="Joan Borg"))
        get_all.assert_not_called()

    def test_as_frappe_does_when_told_not_to_check(self):
        # nothing refused, as for the Operator itself: the name stays as sent
        namesakes = {
            "HR-EMP-00011": frappe._dict(employee_name="Paul Grech", status="Active"),
            "HR-EMP-00012": frappe._dict(employee_name="Paul Grech", status="Left", relieving_date="2026-01-31"),
        }
        for flags in ({"ignore_validate": 1}, {"ignore_mandatory": 1}):
            for employees in ({}, namesakes):
                with self._importing(employees):
                    doc = self._check(_Doc(new=True, operator_name="Paul Grech", flags=flags))
                self.assertEqual(
                    (doc.get("operator"), doc.operator_name), (None, "Paul Grech"), (flags, list(employees))
                )
        # and an Employee who had left by the record's date is not refused either
        with self._importing():
            doc = self._check(
                _Doc(new=True, record_date="2026-07-01", operator="HR-EMP-00002", flags={"ignore_validate": 1})
            )
        self.assertEqual(doc.operator_name, "Mark Vella")


class TestTheLookup(unittest.TestCase):
    """The Operator's search and name, for users with no Employee permission."""

    def test_who_records_checks_may_look_up_operators(self):
        with patch("frappe.has_permission", side_effect=lambda doctype, ptype: doctype == "QC Tasting Record" and ptype == "write"):
            self.assertTrue(may_record_checks())
        with patch("frappe.has_permission", return_value=False):
            self.assertFalse(may_record_checks())

    @patch("frappe.db.exists", return_value=True)
    @patch("frappe.get_all", return_value=[("HR-EMP-00001", "Joan Borg")])
    def test_the_search_offers_active_employees_by_id_or_name(self, get_all, _exists):
        with patch.object(qc_operator, "may_record_checks", return_value=True):
            found = search_operators("Employee", "bor", "name", 0, 20, {})
        self.assertEqual(found, [("HR-EMP-00001", "Joan Borg")])
        get_all.assert_called_once_with(
            "Employee",
            filters={"status": "Active"},
            or_filters={"name": ["like", "%bor%"], "employee_name": ["like", "%bor%"]},
            fields=["name", "employee_name"],
            order_by="employee_name asc, name asc",
            limit_start=0,
            limit_page_length=20,
            as_list=True,
        )
        # as dicts when asked
        with patch.object(qc_operator, "may_record_checks", return_value=True):
            search_operators("Employee", "", "name", 20, 20, {}, as_dict=True)
        self.assertEqual(get_all.call_args.kwargs["as_list"], False)
        self.assertEqual(get_all.call_args.kwargs["or_filters"]["name"], ["like", "%%"])

    @patch("frappe.db.exists", return_value=True)
    @patch("frappe.get_all")
    def test_no_search_for_who_records_no_checks(self, get_all, _exists):
        # (a query raising a PermissionError reads as a method not found)
        with patch.object(qc_operator, "may_record_checks", return_value=False):
            self.assertEqual(search_operators("Employee", "", "name", 0, 20, {}), [])
        get_all.assert_not_called()

    def test_the_name_of_an_employee(self):
        with patch.object(qc_operator, "may_record_checks", return_value=True), patch(
            "frappe.db.get_value", side_effect=_db()
        ):
            self.assertEqual(
                get_operator("HR-EMP-00002"),
                {"employee": "HR-EMP-00002", "employee_name": "Mark Vella", "status": "Left"},
            )
            self.assertEqual(get_operator("HR-EMP-09999"), {})
            self.assertEqual(get_operator(""), {})
        with patch.object(qc_operator, "may_record_checks", return_value=False):
            self.assertEqual(get_operator("HR-EMP-00001"), {})

    def test_the_desk_may_call_them(self):
        for method in (search_operators, get_operator):
            self.assertIn(method, frappe.whitelisted, method.__name__)


class TestTheSchema(unittest.TestCase):
    def test_the_record_types_that_name_an_operator(self):
        named = [doctype for doctype in QC_DOCTYPES.values() if "operator" in {f["fieldname"] for f in _doctype(doctype)["fields"]}]
        self.assertEqual(sorted(named), sorted(OPERATOR_DOCTYPES))
        # all but the retired Oven record, which keeps its typed, required Operator Name
        self.assertEqual(set(QC_DOCTYPES.values()) - set(OPERATOR_DOCTYPES), {"QC Oven Record"})
        oven = {f["fieldname"]: f for f in _doctype("QC Oven Record")["fields"]}
        self.assertEqual((oven["operator_name"]["fieldtype"], oven["operator_name"].get("reqd")), ("Data", 1))

    def test_the_operator_and_its_name(self):
        for doctype in OPERATOR_DOCTYPES:
            doc = _doctype(doctype)
            fields = {f["fieldname"]: f for f in doc["fields"]}
            operator = fields["operator"]
            self.assertEqual((operator["fieldtype"], operator["options"], operator["label"]), ("Link", "Employee", "Operator"), doctype)
            # who is linked to an Employee still finds, saves and lists the others
            self.assertEqual(operator.get("ignore_user_permissions"), 1, doctype)
            # required on records made since by check_operator, not on those made before
            self.assertFalse(operator.get("reqd"), doctype)
            # printed by name, in Operator Name
            self.assertEqual(operator.get("print_hide"), 1, doctype)
            # no fetch_from: a fetch needs Employee permission, and turns Frappe's link check off
            self.assertNotIn("fetch_from", fields["operator_name"], doctype)
            name = fields["operator_name"]
            self.assertEqual((name.get("read_only"), name.get("no_copy")), (1, 1), doctype)
            self.assertFalse(name.get("reqd"), doctype)
            order = doc["field_order"]
            self.assertEqual(order[order.index("operator") + 1], "operator_name", doctype)
            self.assertEqual(order, [f["fieldname"] for f in doc["fields"]], doctype)


class TestTheHooks(unittest.TestCase):
    def setUp(self):
        hooks = {}
        with open(os.path.join(APP_DIR, "hooks.py")) as fh:
            exec(compile(fh.read(), "hooks.py", "exec"), hooks)
        self.hooks = hooks
        with open(SCRIPT) as fh:
            self.script = fh.read()

    def test_each_record_that_names_an_operator_is_checked(self):
        path = f"{qc_operator.__name__}.{check_operator.__name__}"
        self.assertEqual(path, "isnack.utils.qc_operator.check_operator")
        checked = [d for d, events in self.hooks["doc_events"].items() if path in (events.get("before_validate") or [])]
        self.assertEqual(sorted(checked), sorted(OPERATOR_DOCTYPES))

    def test_the_desk_loads_the_script(self):
        # the script's address changes with it, so a browser cannot keep the one
        # before (assets are cached for a year): bump it with the script
        with open(SCRIPT, "rb") as fh:
            version = hashlib.md5(fh.read()).hexdigest()[:8]
        self.assertIn(f"/assets/isnack/js/quality_hub_operator.js?v={version}", self.hooks["app_include_js"])
        listed = re.search(r"OPERATOR_DOCTYPES: \[(.*?)\]", self.script, re.S).group(1)
        self.assertEqual(re.findall(r'"([^"]+)"', listed), list(OPERATOR_DOCTYPES))
        for method in (search_operators, get_operator):
            self.assertIn(f"{qc_operator.__name__}.{method.__name__}", self.script)


@unittest.skipUnless(shutil.which("node"), "needs node to run the script")
class TestTheScript(unittest.TestCase):
    """quality_hub_operator.js, run on a fake desk: the records' forms and
    lists (the Quality Hub's dialogs use the same, through restrict_operator)."""

    def _run(self, body):
        with open(SCRIPT) as fh:
            script = fh.read()
        harness = (
            "const __ = (msg, args) => msg.replace(/\\{(\\d)\\}/g, (_m, i) => args[i]);\n"
            "const handlers = {};\n"
            "const calls = [], alerts = [];\n"
            "const employees = {\n"
            "  'HR-EMP-00001': {employee: 'HR-EMP-00001', employee_name: 'Joan Borg', status: 'Active'},\n"
            "  'HR-EMP-00002': {employee: 'HR-EMP-00002', employee_name: 'Mark Vella', status: 'Left'},\n"
            "  'HR-EMP-00005': {employee: 'HR-EMP-00005', employee_name: 'Ann Zammit', status: 'Active'},\n"
            "};\n"
            "let failing = [], can_read = false;\n"
            "const docfields = {};\n"
            "const frappe = {\n"
            "  provide: (path) => { let o = globalThis; path.split('.').forEach((p) => { o[p] = o[p] || {}; o = o[p]; }); },\n"
            "  xcall: (method, args) => {\n"
            "    calls.push([method, args.employee]);\n"
            "    if (failing.includes(args.employee)) return Promise.reject(new Error('no'));\n"
            "    return Promise.resolve(employees[args.employee] || {});\n"
            "  },\n"
            "  show_alert: (a) => alerts.push([a.message, a.indicator]),\n"
            "  meta: {get_docfield: (dt, f) => ((docfields[dt] = docfields[dt] || {operator: {}})[f])},\n"
            "  model: {can_read: () => can_read},\n"
            "  utils: {escape_html: (t) => String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')},\n"
            "  ui: {form: {on: (doctype, h) => { handlers[doctype] = h; }}},\n"
            "};\n"
            "globalThis.frappe = frappe;\n"
            "const isnack = {};\n"
            "globalThis.isnack = isnack;\n"
            f"{script}\n"
            "const operators = isnack.quality_hub_operator;\n"
            "const flush = async () => { for (let i = 0; i < 5; i++) await new Promise((r) => setTimeout(r, 0)); };\n"
            "// a desk form: a value set marks the document unsaved, as Frappe does\n"
            "const form = (doctype, doc) => {\n"
            "  const arrow = {classes: [], addClass(c) { this.classes.push(c); }};\n"
            "  const frm = {doctype, doc, queries: {}, set: [], props: [], seen: [], reqd: {},\n"
            "    fields_dict: {operator: {df: {}, $link_open: arrow}, operator_name: {df: {}}},\n"
            "    is_dirty: () => !!frm.doc.__unsaved, is_new: () => !!frm.doc.__islocal,\n"
            "    set_query: (f, q) => { frm.queries[f] = q; },\n"
            "    set_df_property: (f, p, v) => { frm.props.push([f, p, v]); frm.seen.push(frm.doc.operator || ''); },\n"
            "    toggle_reqd: (f, r) => { frm.reqd[f] = r; },\n"
            "    set_value: (f, v) => { frm.set.push([f, v]); frm.doc[f] = v; frm.doc.__unsaved = 1; }};\n"
            "  handlers[doctype].setup(frm);\n"
            "  handlers[doctype].before_load(frm);\n"
            "  handlers[doctype].refresh(frm);\n"
            "  return frm;\n"
            "};\n"
            "// the user picks an Operator in the form\n"
            "const pick = (frm, value) => { frm.doc.operator = value; frm.doc.__unsaved = 1; handlers[frm.doctype].operator(frm); };\n"
            "(async () => {\n"
            "  const out = {};\n"
            f"{body}\n"
            "  console.log(JSON.stringify(out));\n"
            "})();\n"
        )
        run = subprocess.run(["node", "-e", harness], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr[-2000:])
        return json.loads(run.stdout)

    def test_every_form_and_list_looks_up_its_operator(self):
        out = self._run(
            "  out.registered = Object.keys(handlers);\n"
            "  // a list opened first: its filters use the same lookup (an onload of its own kept)\n"
            "  let own = 0; frappe.listview_settings['QC Tasting Record'].onload = ((first) => function () { own++; return first.apply(this, arguments); })(frappe.listview_settings['QC Tasting Record'].onload);\n"
            "  frappe.listview_settings['QC Tasting Record'].onload({});\n"
            "  const listed = frappe.meta.get_docfield('QC Tasting Record', 'operator');\n"
            "  out.listed = [listed.ignore_link_validation, listed.only_select, listed.get_query(), own];\n"
            "  const frm = form('QC Weight Check', {__islocal: 1});\n"
            "  // on the doctype's field, from which Frappe copies each document's\n"
            "  const df = frappe.meta.get_docfield('QC Weight Check', 'operator');\n"
            "  out.field = [df.ignore_link_validation, df.only_select, df.get_query()];\n"
            "  out.query = frm.queries.operator();\n"
            "  out.props = frm.props;\n"
            "  out.hidden = frm.fields_dict.operator.$link_open.classes;\n"
            "  can_read = true;\n"
            "  out.shown = form('QC Weight Check', {__islocal: 1}).fields_dict.operator.$link_open.classes;\n"
        )
        self.assertEqual(sorted(out["registered"]), sorted(OPERATOR_DOCTYPES))
        query = {"query": "isnack.utils.qc_operator.search_operators"}
        self.assertEqual(out["listed"], [1, 1, query, 1])
        # checked on the server: Frappe's check needs Employee permission; and no "Create a new"
        self.assertEqual(out["field"], [1, 1, query])
        self.assertEqual(out["query"], query)
        # on the document's own field too: before its load (Frappe may copy it before setup, and checks a
        # link a new record comes with before refresh), and again as it shows
        self.assertEqual(out["props"], [["operator", "ignore_link_validation", 1], ["operator", "only_select", 1]] * 2)
        # the open arrow leads to an Employee page: hidden from who may not read Employee
        self.assertEqual(out["hidden"], ["hide"])
        self.assertEqual(out["shown"], [])

    def test_the_operator_is_required_on_records_made_since(self):
        out = self._run(
            "  out.new = form('QC Weight Check', {__islocal: 1}).reqd.operator;\n"
            "  out.since = form('QC Weight Check', {name: 'QCI-1', operator: 'HR-EMP-00001', operator_name: 'Joan Borg'}).reqd.operator;\n"
            "  const before = form('QC Weight Check', {name: 'QCI-2', operator_name: 'J. Borg'});\n"
            "  out.before = before.reqd.operator;\n"
            "  // an Employee picked, not saved, the form shown again: still a record made before\n"
            "  pick(before, 'HR-EMP-00001'); await flush();\n"
            "  handlers['QC Weight Check'].refresh(before);\n"
            "  out.picked = before.reqd.operator;\n"
            "  // emptied again: its typed name back\n"
            "  before.set.splice(0); pick(before, ''); await flush();\n"
            "  out.emptied = before.set;\n"
            "  // saved with the Employee: a record made since\n"
            "  before.doc.operator = 'HR-EMP-00001'; before.doc.operator_name = 'Joan Borg'; delete before.doc.__unsaved;\n"
            "  handlers['QC Weight Check'].refresh(before);\n"
            "  out.saved = before.reqd.operator;\n"
            "  out.amended = form('QC Weight Check', {name: 'new-1', __islocal: 1, __unsaved: 1, amended_from: 'QCI-2026-00001', operator_name: 'J. Borg'}).reqd.operator;\n"
            "  // a new record with a typed name and no amendment: no record made before\n"
            "  out.typed_new = form('QC Weight Check', {name: 'new-2', __islocal: 1, __unsaved: 1, operator_name: 'J. Borg'}).reqd.operator;\n"
        )
        self.assertEqual(out["new"], True)
        self.assertEqual(out["since"], True)
        self.assertEqual(out["before"], False)
        self.assertEqual(out["picked"], False)
        self.assertEqual(out["emptied"], [["operator_name", "J. Borg"]])
        self.assertEqual(out["saved"], True)
        self.assertEqual(out["amended"], False)
        self.assertEqual(out["typed_new"], True)

    def test_the_operator_picked_names_it(self):
        out = self._run(
            "  const frm = form('QC Packaging Check', {__islocal: 1});\n"
            "  pick(frm, 'HR-EMP-00001'); await flush();\n"
            "  out.picked = frm.set.splice(0);\n"
            "  // another picked: the name before goes at once\n"
            "  pick(frm, 'HR-EMP-00005'); await flush();\n"
            "  out.other = frm.set.splice(0);\n"
            "  // emptied\n"
            "  pick(frm, ''); await flush();\n"
            "  out.emptied = frm.set.splice(0);\n"
            "  // someone who has left, typed in full: taken off\n"
            "  pick(frm, 'HR-EMP-00002'); await flush();\n"
            "  out.left = frm.set.splice(0);\n"
            "  // no such Employee, with markup in it (from the address): shown as text\n"
            "  pick(frm, '<img src=x onerror=alert(1)>'); await flush();\n"
            "  out.none = frm.set.splice(0);\n"
            "  out.alerts = alerts;\n"
        )
        self.assertEqual(out["picked"], [["operator_name", "Joan Borg"]])
        self.assertEqual(out["other"], [["operator_name", ""], ["operator_name", "Ann Zammit"]])
        self.assertEqual(out["emptied"], [["operator_name", ""]])
        self.assertEqual(out["left"], [["operator", ""], ["operator_name", ""]])
        self.assertEqual(out["none"], [["operator", ""], ["operator_name", ""]])
        self.assertEqual(
            out["alerts"],
            [
                ["HR-EMP-00002 is not an active Employee: pick the Operator from the list.", "orange"],
                ["&lt;img src=x onerror=alert(1)&gt; is not an active Employee: pick the Operator from the list.", "orange"],
            ],
        )

    def test_an_employee_not_known_now_is_left_as_picked(self):
        out = self._run(
            "  const frm = form('QC Packaging Check', {__islocal: 1});\n"
            "  pick(frm, 'HR-EMP-00001'); await flush();\n"
            "  // the request fails: left as picked, its name not the one before; the server checks it on save\n"
            "  failing = ['HR-EMP-00005'];\n"
            "  frm.set.splice(0); pick(frm, 'HR-EMP-00005'); await flush();\n"
            "  out.failed = [frm.set.splice(0), frm.doc.operator, alerts.length];\n"
            "  // offline: not asked at all\n"
            "  failing = [];\n"
            "  Object.defineProperty(globalThis, 'navigator', {value: {onLine: false}, configurable: true});\n"
            "  const asked = calls.length;\n"
            "  out.offline = [await operators.details('HR-EMP-00005'), calls.length - asked];\n"
        )
        self.assertEqual(out["failed"], [[["operator_name", ""]], "HR-EMP-00005", 0])
        self.assertEqual(out["offline"], [None, 0])

    def test_a_new_record_with_an_operator_shows_its_name(self):
        out = self._run(
            "  // a duplicate: the Operator copied, not its name\n"
            "  const copy = form('QC Weight Check', {__islocal: 1, operator: 'HR-EMP-00001'}); await flush();\n"
            "  out.copy = copy.set;\n"
            "  // one opened from a list's filter on someone who has left: taken off\n"
            "  const left = form('QC Weight Check', {__islocal: 1, operator: 'HR-EMP-00002'}); await flush();\n"
            "  out.left = [left.set, alerts.length];\n"
            "  // a saved record is not looked up as it loads\n"
            "  const saved = form('QC Weight Check', {name: 'QCI-1', operator: 'HR-EMP-00001'}); await flush();\n"
            "  out.saved = saved.set;\n"
        )
        self.assertEqual(out["copy"], [["operator_name", "Joan Borg"]])
        self.assertEqual(out["left"], [[["operator", ""], ["operator_name", ""]], 1])
        self.assertEqual(out["saved"], [])

    def test_markup_in_the_address_is_never_shown(self):
        # Frappe shows a Link to a doctype the user may not read as it stands, and refreshes
        # the field when a property is set: the value goes before anything shows it
        out = self._run(
            "  const frm = form('QC Weight Check', {__islocal: 1, operator: '<img src=x onerror=alert(1)>'});\n"
            "  out.doc = frm.doc.operator; out.seen = frm.seen; out.alerts = alerts;\n"
            "  // a saved record is left as it is (its Operator is an Employee the server checked)\n"
            "  out.saved = form('QC Weight Check', {name: 'QCI-1', operator: 'HR-EMP-00001'}).doc.operator;\n"
        )
        self.assertEqual(out["doc"], "")
        self.assertEqual(set(out["seen"]), {""})
        self.assertEqual(
            out["alerts"],
            [["&lt;img src=x onerror=alert(1)&gt; is not an active Employee: pick the Operator from the list.", "orange"]],
        )
        self.assertEqual(out["saved"], "HR-EMP-00001")

    def test_a_late_answer_changes_nothing(self):
        out = self._run(
            "  const frm = form('QC Tasting Record', {__islocal: 1});\n"
            "  // picked, then another picked before the answer came\n"
            "  pick(frm, 'HR-EMP-00001'); frm.doc.operator = 'HR-EMP-00003'; await flush();\n"
            "  out.changed = frm.set.splice(0);\n"
            "  // picked, then another document opened in the form\n"
            "  operators._operators = {};\n"
            "  pick(frm, 'HR-EMP-00005'); frm.doc = {operator: 'HR-EMP-00005'}; await flush();\n"
            "  out.other = frm.set.splice(0);\n"
        )
        self.assertEqual(out["changed"], [])
        self.assertEqual(out["other"], [])

    def test_only_an_active_employee_is_remembered(self):
        out = self._run(
            "  await operators.details('HR-EMP-00001'); await operators.details('HR-EMP-00001');\n"
            "  // one who has left is asked again: HR may set them back to Active\n"
            "  await operators.details('HR-EMP-00002'); await operators.details('HR-EMP-00002');\n"
            "  // a failed read is tried again next time\n"
            "  failing = ['HR-EMP-00005'];\n"
            "  out.failed = await operators.details('HR-EMP-00005');\n"
            "  failing = [];\n"
            "  out.again = await operators.details('HR-EMP-00005');\n"
            "  out.empty = await operators.details('');\n"
            "  out.calls = calls.map((c) => c[1]);\n"
        )
        self.assertIsNone(out["failed"])
        self.assertEqual(out["again"]["employee_name"], "Ann Zammit")
        self.assertEqual(out["empty"], {})
        self.assertEqual(out["calls"], ["HR-EMP-00001", "HR-EMP-00002", "HR-EMP-00002", "HR-EMP-00005", "HR-EMP-00005"])
