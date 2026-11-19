# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""Quality Hub Settings: the factory lines each Quality Hub tab records on
(2026-11), and the QC records held to them; the production lines each packing
line packs for, whose Work Orders its records offer (no database)."""

import json
import os
import re
import shutil
import subprocess
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from isnack.isnack.doctype.quality_hub_settings import quality_hub_settings as settings_module
from isnack.isnack.doctype.quality_hub_settings.quality_hub_settings import (
    PACKING_FIELD,
    RESTRICTED_DOCTYPES,
    TAB_FIELDS,
    QualityHubSettings,
    check_factory_line,
    factory_lines,
    get_factory_lines,
    get_packing_lines,
    get_work_order_details,
    packing_lines,
)

DOCTYPE_DIR = os.path.join(os.path.dirname(__file__), "..")
APP_DIR = os.path.join(DOCTYPE_DIR, "..", "..")


def _doctype(name):
    folder = name.lower().replace(" ", "_")
    with open(os.path.join(DOCTYPE_DIR, folder, f"{folder}.json")) as fh:
        return json.load(fh)


LABELS = {f["fieldname"]: f.get("label") for f in _doctype("Quality Hub Settings")["fields"]}


class _Settings(frappe._dict):
    """Quality Hub Settings as the database holds them: ``lines`` by field, and
    the Packing Lines rows as (packing line, production line) pairs."""

    def get(self, fieldname, default=None):
        if fieldname == PACKING_FIELD:
            return [frappe._dict(packing_line=packing, production_line=production) for packing, production in self.packing]
        return [frappe._dict(factory_line=line) for line in self.lines.get(fieldname, [])]


@contextmanager
def _given(packing=(), **lines):
    """Quality Hub Settings giving ``lines`` and the ``packing`` rows, on a
    site that has them. The settings are read only once their DocType exists
    (frappe.db.exists), which Frappe looks up with frappe.db.get_value: patched
    here, so a test that patches get_value for the record an amendment amends
    sees only that call."""
    settings = _Settings(lines=lines, packing=list(packing))
    with patch("frappe.db.exists", return_value=True), patch("frappe.get_cached_doc", return_value=settings):
        yield


_META = patch("frappe.get_meta", return_value=SimpleNamespace(get_label=LABELS.get))


def _record(doctype, line, **values):
    return frappe._dict({"doctype": doctype, "factory_line": line, "amended_from": None, **values})


class TestTheLines(unittest.TestCase):
    def test_a_tab_given_lines(self):
        with _given(puffs_extruder_lines=["CORN EXTRUSION"], packaging_and_weight_lines=["PACKING LINE 1", "PACKING LINE 2"]):
            self.assertEqual(factory_lines("QC Puffs Extruder Record"), ["CORN EXTRUSION"])
            # the Packaging and Weight tab records both its checks, on the same lines
            for doctype in ("QC Packaging Check", "QC Weight Check"):
                self.assertEqual(factory_lines(doctype), ["PACKING LINE 1", "PACKING LINE 2"], doctype)
            # a tab given none: any line
            self.assertEqual(factory_lines("QC Rice Extruder Record"), [])

    def test_a_record_type_no_tab_restricts(self):
        # Receiving has no factory line; the Oven Record is retired
        with patch("frappe.get_cached_doc") as get_cached_doc:
            for doctype in ("QC Receiving Record", "QC Oven Record", "Work Order"):
                self.assertEqual(factory_lines(doctype), [], doctype)
            get_cached_doc.assert_not_called()

    def test_before_the_migrate_makes_the_settings(self):
        # no DocType yet: Frappe would find no controller to read them with
        # (ImportError), so they are not read; every record is on any line
        with patch("frappe.db.exists", return_value=None) as exists, patch("frappe.get_cached_doc") as get_cached_doc:
            self.assertEqual(factory_lines("QC Tasting Record"), [])
            self.assertEqual(get_factory_lines(), {doctype: [] for doctype in RESTRICTED_DOCTYPES})
            check_factory_line(_record("QC Tasting Record", "FRYING"))
            check_factory_line(_record("QC Puffs Extruder Record", None))
        get_cached_doc.assert_not_called()
        exists.assert_called_with("DocType", "Quality Hub Settings", cache=True)

    def test_a_line_listed_twice_is_read_once(self):
        # merging one listed line into another (Rename, "Merge with existing")
        # rewrites the rows without the settings' validate
        with _given(packaging_and_weight_lines=["PACKING LINE 1", "packing line 1 ", "PACKING LINE 1"], tasting_lines=["FRYING", "CORN MIX", "FRYING"]):
            # the tab's only line, still filled in (quality_hub_lines.js only_line)
            self.assertEqual(factory_lines("QC Weight Check"), ["PACKING LINE 1"])
            self.assertEqual(factory_lines("QC Tasting Record"), ["FRYING", "CORN MIX"])

    def test_every_tabs_lines_by_record_type(self):
        with _given(metal_detector_lines=["CORN EXTRUSION", "FRYING"]):
            lines = get_factory_lines()
        self.assertEqual(list(lines), list(RESTRICTED_DOCTYPES))
        self.assertEqual(lines["QC Metal Detector Log"], ["CORN EXTRUSION", "FRYING"])
        self.assertEqual({doctype: given for doctype, given in lines.items() if given}, {"QC Metal Detector Log": ["CORN EXTRUSION", "FRYING"]})


class TestThePackingLines(unittest.TestCase):
    """A record on a packing line offers the Work Orders of the production lines
    it packs for: Work Orders are planned on the line that makes the product."""

    def test_what_each_packing_line_packs_for(self):
        rows = [("PACKING LINE 1", "CORN EXTRUSION"), ("PACKING LINE 2", "FRYING"), ("PACKING LINE 1", "FRYING")]
        with _given(packing=rows):
            self.assertEqual(packing_lines(), {"PACKING LINE 1": ["CORN EXTRUSION", "FRYING"], "PACKING LINE 2": ["FRYING"]})
            # the forms and the Quality Hub read the same
            self.assertEqual(get_packing_lines(), packing_lines())

    def test_a_row_read_once(self):
        # rows Rename's "Merge with existing" rewrote without the settings' validate
        rows = [
            ("PACKING LINE 1", "CORN EXTRUSION"),
            (" packing line 1", "Corn Extrusion "),
            ("PACKING LINE 1", "packing line 1"),
            ("PACKING LINE 2", ""),
            (None, "FRYING"),
        ]
        with _given(packing=rows):
            self.assertEqual(packing_lines(), {"PACKING LINE 1": ["CORN EXTRUSION"]})

    def test_none_given(self):
        with _given():
            self.assertEqual(packing_lines(), {})

    def test_before_the_migrate_makes_the_settings(self):
        with patch("frappe.db.exists", return_value=None), patch("frappe.get_cached_doc") as get_cached_doc:
            self.assertEqual(get_packing_lines(), {})
        get_cached_doc.assert_not_called()


class TestTheWorkOrderDetails(unittest.TestCase):
    """The line a Work Order is planned on and the item it makes, for the
    pickers: whoever may pick the Work Order may know them."""

    def _ask(self, work_order, exists=True, permitted=("select",), line="CORN EXTRUSION"):
        doc = frappe._dict(name=work_order, production_item="FG10020", custom_factory_line=line)
        with patch("frappe.db.exists", return_value=exists) as db_exists, patch("frappe.get_doc", return_value=doc) as get_doc, patch(
            "frappe.has_permission", side_effect=lambda doctype, ptype, doc=None: ptype in permitted
        ) as has_permission:
            details = get_work_order_details(work_order)
        return details, db_exists, get_doc, has_permission

    def test_a_work_order_the_user_may_pick(self):
        details, db_exists, get_doc, has_permission = self._ask("MFG-WO-2026-00096")
        self.assertEqual(details, {"factory_line": "CORN EXTRUSION", "production_item": "FG10020"})
        db_exists.assert_called_once_with("Work Order", "MFG-WO-2026-00096")
        get_doc.assert_called_once_with("Work Order", "MFG-WO-2026-00096")
        # the document's own permission (User Permissions included)
        self.assertEqual(has_permission.call_args_list[0].args, ("Work Order", "select"))
        self.assertIs(has_permission.call_args_list[0].kwargs["doc"], get_doc.return_value)

    def test_read_permission_is_enough(self):
        self.assertEqual(self._ask("MFG-WO-2026-00096", permitted=("read",))[0]["production_item"], "FG10020")

    def test_nothing_for_a_user_who_may_not_pick_it(self):
        self.assertEqual(self._ask("MFG-WO-2026-00096", permitted=())[0], {})

    def test_nothing_for_a_work_order_there_is_not(self):
        details, _exists, get_doc, _perm = self._ask("MFG-WO-2026-99999", exists=False)
        self.assertEqual(details, {})
        get_doc.assert_not_called()
        details, db_exists, get_doc, _perm = self._ask("")
        self.assertEqual(details, {})
        db_exists.assert_not_called()

    def test_a_work_order_on_no_line(self):
        # its line is the custom Factory Section field, filled from the BOM
        self.assertEqual(self._ask("MFG-WO-2026-00001", line=None)[0], {"factory_line": None, "production_item": "FG10020"})


@patch("frappe.db.get_value")
class TestTheCheck(unittest.TestCase):
    """A QC record's Factory Line is one Quality Hub Settings gives its tab (a
    Link takes any line typed in full)."""

    def test_a_line_the_tab_is_given(self, get_value):
        with _given(puffs_extruder_lines=["CORN EXTRUSION"], packaging_and_weight_lines=["PACKING LINE 1", "PACKING LINE 2"]):
            check_factory_line(_record("QC Puffs Extruder Record", "CORN EXTRUSION"))
            # spelled otherwise, as the database matches it
            check_factory_line(_record("QC Weight Check", "packing line 2 "))
        get_value.assert_not_called()

    def test_another_line(self, get_value):
        with _given(packaging_and_weight_lines=["PACKING LINE 1", "PACKING LINE 2"]), _META:
            with self.assertRaises(frappe.ValidationError) as raised:
                check_factory_line(_record("QC Packaging Check", "FRYING"))
        self.assertEqual(
            re.sub("<[^>]+>", "", str(raised.exception)),
            "FRYING is not one of the factory lines Quality Hub Settings gives Packaging and Weight Checks (QCG/QCI): PACKING LINE 1, PACKING LINE 2.",
        )
        get_value.assert_not_called()

    def test_any_line_when_the_tab_is_given_none_or_no_line(self, get_value):
        with _given(puffs_extruder_lines=["CORN EXTRUSION"]):
            check_factory_line(_record("QC Rice Extruder Record", "FRYING"))
            check_factory_line(_record("QC Puffs Extruder Record", None))
            check_factory_line(_record("QC Puffs Extruder Record", ""))

    def test_an_amendment_keeps_the_line_it_amends(self, get_value):
        # PACKING LINE 2 was the Packaging and Weight tab's when the check it
        # amends was made, and has left it since
        get_value.return_value = "packing line 2"
        with _given(packaging_and_weight_lines=["PACKING LINE 1"]):
            check_factory_line(_record("QC Packaging Check", "PACKING LINE 2", amended_from="QCG-2026-00004"))
        get_value.assert_called_once_with("QC Packaging Check", "QCG-2026-00004", "factory_line")

    def test_an_amendment_on_another_line(self, get_value):
        for amended in ("PACKING LINE 2", None):  # another line, or a record there is not
            get_value.return_value = amended
            with _given(packaging_and_weight_lines=["PACKING LINE 1"]), _META:
                with self.assertRaisesRegex(frappe.ValidationError, "FRYING.* is not one of the factory lines"):
                    check_factory_line(_record("QC Weight Check", "FRYING", amended_from="QCI-2026-00007"))


class TestTheSettings(unittest.TestCase):
    def test_each_line_once_in_a_tab(self):
        doc = frappe._dict(
            puffs_extruder_lines=[frappe._dict(factory_line=line, idx=i) for i, line in enumerate(["CORN EXTRUSION", "corn extrusion ", "CORN MIX", None], 1)],
            metal_detector_lines=[frappe._dict(factory_line="FRYING", idx=4)],
        )
        doc.set = doc.__setitem__
        QualityHubSettings.validate(doc)
        self.assertEqual([(row.factory_line, row.idx) for row in doc.puffs_extruder_lines], [("CORN EXTRUSION", 1), ("CORN MIX", 2)])
        self.assertEqual([(row.factory_line, row.idx) for row in doc.metal_detector_lines], [("FRYING", 1)])
        # a tab given none stays so
        self.assertEqual(doc.tasting_lines, [])

    def test_each_production_line_once_for_a_packing_line(self):
        rows = [
            ("PACKING LINE 1", "CORN EXTRUSION"),
            ("packing line 1 ", "corn extrusion"),  # the same row again
            ("PACKING LINE 1", "PACKING LINE 1"),  # a packing line packs for itself already
            ("PACKING LINE 1", "FRYING"),
            ("PACKING LINE 2", "FRYING"),
            ("PACKING LINE 2", None),  # half a row: the mandatory check asks for the rest
        ]
        doc = frappe._dict(packing_lines=[frappe._dict(packing_line=a, production_line=b, idx=i) for i, (a, b) in enumerate(rows, 1)])
        doc.set = doc.__setitem__
        QualityHubSettings.validate(doc)
        self.assertEqual(
            [(row.packing_line, row.production_line, row.idx) for row in doc.packing_lines],
            [("PACKING LINE 1", "CORN EXTRUSION", 1), ("PACKING LINE 1", "FRYING", 2), ("PACKING LINE 2", "FRYING", 3), ("PACKING LINE 2", None, 4)],
        )


class TestTheDoctypes(unittest.TestCase):
    def test_the_settings(self):
        doc = _doctype("Quality Hub Settings")
        self.assertEqual(doc.get("issingle"), 1)
        self.assertEqual(doc["field_order"], [f["fieldname"] for f in doc["fields"]])
        # a field per tab, in the hub's order
        self.assertEqual(
            [(f["fieldname"], f["fieldtype"], f.get("options")) for f in doc["fields"] if f["fieldtype"] == "Table MultiSelect"],
            [(fieldname, "Table MultiSelect", "Quality Hub Factory Line") for fieldname in TAB_FIELDS],
        )
        # each labelled as the hub labels the tab
        with open(os.path.join(APP_DIR, "isnack", "page", "quality_hub", "quality_hub.js")) as fh:
            hub = fh.read()
        for fieldname in TAB_FIELDS:
            self.assertIn(f'__("{LABELS[fieldname]}")', hub, fieldname)
        # the Quality Manager sets them; a Quality Controller reads them
        perms = {p["role"]: p for p in doc["permissions"]}
        self.assertEqual(perms["Quality Manager"].get("write"), 1)
        self.assertEqual((perms["Quality Controller"].get("read"), perms["Quality Controller"].get("write")), (1, None))
        self.assertEqual(doc.get("track_changes"), 1)

    def test_the_packing_lines(self):
        fields = {f["fieldname"]: f for f in _doctype("Quality Hub Settings")["fields"]}
        table = fields[PACKING_FIELD]
        self.assertEqual((table["fieldtype"], table["options"], table["label"]), ("Table", "Quality Hub Packing Line", "Packing Lines"))
        self.assertEqual(fields["packing_lines_section"]["label"], "Work Orders on Packing Lines")
        doc = _doctype("Quality Hub Packing Line")
        self.assertEqual((doc.get("istable"), doc.get("editable_grid")), (1, 1))
        self.assertEqual(
            [(f["fieldname"], f["fieldtype"], f.get("options"), f.get("reqd"), f.get("in_list_view")) for f in doc["fields"]],
            [("packing_line", "Link", "Factory Line", 1, 1), ("production_line", "Link", "Factory Line", 1, 1)],
        )

    def test_a_tabs_factory_line(self):
        doc = _doctype("Quality Hub Factory Line")
        self.assertEqual(doc.get("istable"), 1)
        self.assertEqual(
            [(f["fieldname"], f["fieldtype"], f.get("options"), f.get("reqd"), f.get("in_list_view")) for f in doc["fields"]],
            [("factory_line", "Link", "Factory Line", 1, 1)],
        )

    def test_each_restricted_record_has_a_factory_line(self):
        self.assertEqual(len(RESTRICTED_DOCTYPES), len(set(RESTRICTED_DOCTYPES)))
        for doctype in RESTRICTED_DOCTYPES:
            fields = {f["fieldname"]: f for f in _doctype(doctype)["fields"]}
            self.assertEqual((fields["factory_line"]["fieldtype"], fields["factory_line"]["options"]), ("Link", "Factory Line"), doctype)


class TestTheHooks(unittest.TestCase):
    def setUp(self):
        hooks = {}
        with open(os.path.join(APP_DIR, "hooks.py")) as fh:
            exec(compile(fh.read(), "hooks.py", "exec"), hooks)
        self.hooks = hooks
        with open(os.path.join(APP_DIR, "public", "js", "quality_hub_lines.js")) as fh:
            self.script = fh.read()

    def test_each_restricted_record_is_checked(self):
        path = "isnack.isnack.doctype.quality_hub_settings.quality_hub_settings.check_factory_line"
        self.assertEqual(path, f"{settings_module.__name__}.{check_factory_line.__name__}")
        checked = [doctype for doctype, events in self.hooks["doc_events"].items() if events.get("validate") == path]
        self.assertEqual(sorted(checked), sorted(RESTRICTED_DOCTYPES))

    def test_the_forms_and_the_hub_restrict_the_same_records(self):
        self.assertIn("/assets/isnack/js/quality_hub_lines.js", self.hooks["app_include_js"])
        listed = re.search(r"DOCTYPES: \[(.*?)\]", self.script, re.S).group(1)
        self.assertEqual(re.findall(r'"([^"]+)"', listed), list(RESTRICTED_DOCTYPES))
        self.assertIn("isnack.isnack.doctype.quality_hub_settings.quality_hub_settings.get_factory_lines", self.script)
        # and their Work Orders and products
        for method in (get_packing_lines, get_work_order_details):
            self.assertIn(f"{settings_module.__name__}.{method.__name__}", self.script)


@unittest.skipUnless(shutil.which("node"), "needs node to run the script")
class TestTheScript(unittest.TestCase):
    """quality_hub_lines.js, run on a fake desk: the lines offered and the line
    filled in, on the records' forms (the Quality Hub's dialogs use the same)."""

    def test_the_lines_offered_and_the_only_line(self):
        with open(os.path.join(APP_DIR, "public", "js", "quality_hub_lines.js")) as fh:
            script = fh.read()
        harness = (
            "const isnack = {};\n"
            "const __ = (msg) => msg;\n"
            "const handlers = {};\n"
            "let given = {};\n"
            "const calls = [];\n"
            "const frappe = {\n"
            "  provide: (path) => { let o = globalThis; path.split('.').forEach((p) => { o[p] = o[p] || {}; o = o[p]; }); },\n"
            "  xcall: (method) => { calls.push(method); return Promise.resolve(method.endsWith('.get_packing_lines') ? {} : given); },\n"
            "  ui: {form: {on: (doctype, h) => { handlers[doctype] = h; }}},\n"
            "};\n"
            "globalThis.isnack = isnack;\n"
            f"{script}\n"
            "const lines = isnack.quality_hub_lines;\n"
            "const form = (doctype, doc, is_new) => {\n"
            "  const frm = {doctype, doc, queries: {}, set: [], fields_dict: {factory_line: {df: {}}},\n"
            "    is_new: () => is_new, set_query: (f, q) => { frm.queries[f] = q; }, set_value: (f, v) => { frm.set.push([f, v]); frm.doc[f] = v; }};\n"
            "  handlers[doctype].setup(frm);\n"
            "  return frm;\n"
            "};\n"
            "const flush = () => new Promise((r) => setTimeout(r, 0));\n"
            "(async () => {\n"
            "  const out = {registered: Object.keys(handlers)};\n"
            "  // before the lines are loaded: every line\n"
            "  out.before = lines.query(['QC Puffs Extruder Record']);\n"
            "  given = {'QC Puffs Extruder Record': ['CORN EXTRUSION'], 'QC Packaging Check': ['PACKING LINE 1', 'PACKING LINE 2'],\n"
            "    'QC Weight Check': ['PACKING LINE 2', 'PACKING LINE 3'], 'QC Rice Extruder Record': []};\n"
            "  await lines.load();\n"
            "  out.calls = calls.slice();\n"
            "  out.lines_for = [['QC Puffs Extruder Record'], ['QC Rice Extruder Record'], ['QC Packaging Check', 'QC Weight Check'],\n"
            "    ['QC Rice Extruder Record', 'QC Packaging Check'], ['QC Tasting Record']].map((d) => lines.lines_for(d));\n"
            "  const df = {};\n"
            "  out.query = lines.query(['QC Puffs Extruder Record'], df); out.note = df.filter_description;\n"
            "  out.query_any = lines.query(['QC Rice Extruder Record'], df); out.note_any = df.filter_description;\n"
            "  out.only = [['QC Puffs Extruder Record'], ['QC Packaging Check'], ['QC Rice Extruder Record']].map((d) => lines.only_line(d));\n"
            "  // the forms\n"
            "  const fresh = form('QC Puffs Extruder Record', {}, true);\n"
            "  out.form_query = fresh.queries.factory_line(); out.form_note = fresh.fields_dict.factory_line.df.filter_description;\n"
            "  handlers['QC Puffs Extruder Record'].onload(fresh); await flush(); await flush();\n"
            "  out.fresh = fresh.set;\n"
            "  const saved = form('QC Puffs Extruder Record', {factory_line: 'CORN MIX'}, false);\n"
            "  handlers['QC Puffs Extruder Record'].onload(saved); await flush(); await flush();\n"
            "  const picked = form('QC Puffs Extruder Record', {factory_line: 'CORN MIX'}, true);\n"
            "  handlers['QC Puffs Extruder Record'].onload(picked); await flush(); await flush();\n"
            "  const two = form('QC Packaging Check', {}, true);\n"
            "  handlers['QC Packaging Check'].onload(two); await flush(); await flush();\n"
            "  out.left = [saved.set, picked.set, two.set];\n"
            "  console.log(JSON.stringify(out));\n"
            "})();\n"
        )
        out = json.loads(subprocess.run(["node", "-e", harness], capture_output=True, text=True, check=True).stdout)
        # each restricted record's form
        self.assertEqual(out["registered"], list(RESTRICTED_DOCTYPES))
        self.assertEqual(out["before"], {})
        self.assertEqual(
            out["calls"],
            [
                "isnack.isnack.doctype.quality_hub_settings.quality_hub_settings.get_factory_lines",
                "isnack.isnack.doctype.quality_hub_settings.quality_hub_settings.get_packing_lines",
            ],
        )
        # a tab's lines; none given: every line (null); records made together: the lines they share
        self.assertEqual(out["lines_for"], [["CORN EXTRUSION"], None, ["PACKING LINE 2"], ["PACKING LINE 1", "PACKING LINE 2"], None])
        self.assertEqual(out["query"], {"filters": [["Factory Line", "name", "in", ["CORN EXTRUSION"]]]})
        self.assertEqual(out["note"], "The lines Quality Hub Settings gives this tab")
        # every line, and no note under them
        self.assertEqual((out["query_any"], out["note_any"]), ({}, None))
        self.assertEqual(out["only"], ["CORN EXTRUSION", None, None])
        # the form: its tab's lines, and a new record takes the only one
        self.assertEqual(out["form_query"], out["query"])
        self.assertEqual(out["form_note"], "The lines Quality Hub Settings gives this tab")
        self.assertEqual(out["fresh"], [["factory_line", "CORN EXTRUSION"]])
        # a saved record, a line picked already, a tab with two lines: left as they are
        self.assertEqual(out["left"], [[], [], []])


@unittest.skipUnless(shutil.which("node"), "needs node to run the script")
class TestTheWorkOrders(unittest.TestCase):
    """quality_hub_lines.js, run on a fake desk: the Work Orders a record's line
    offers, one it does not offer taken off, and the Product Item the Work
    Order fills in, on the records' forms (the Quality Hub's dialogs use the
    same, through restrict_work_order)."""

    def _run(self, body):
        with open(os.path.join(APP_DIR, "public", "js", "quality_hub_lines.js")) as fh:
            script = fh.read()
        harness = (
            "const isnack = {};\n"
            "const __ = (msg, args) => msg.replace(/\\{(\\d)\\}/g, (_m, i) => args[i]);\n"
            "const handlers = {};\n"
            "const calls = [], alerts = [];\n"
            "const details = {\n"
            "  'WO-EXT': {factory_line: 'CORN EXTRUSION', production_item: 'FG10020'},\n"
            "  'WO-FRY': {factory_line: 'FRYING', production_item: 'FG10001'},\n"
            "  'WO-MIX': {factory_line: 'CORN MIX', production_item: 'SFG10001'},\n"
            "  'WO-NONE': {factory_line: null, production_item: 'FG10002'},\n"
            "};\n"
            "let failing = [];\n"
            "const frappe = {\n"
            "  provide: (path) => { let o = globalThis; path.split('.').forEach((p) => { o[p] = o[p] || {}; o = o[p]; }); },\n"
            "  xcall: (method, args) => {\n"
            "    const name = method.split('.').pop(); calls.push(args ? [name, args.work_order] : [name]);\n"
            "    if (name === 'get_factory_lines') return Promise.resolve({'QC Packaging Check': ['PACKING LINE 1', 'PACKING LINE 2']});\n"
            "    if (name === 'get_packing_lines') return Promise.resolve({'PACKING LINE 1': ['CORN EXTRUSION', 'FRYING']});\n"
            "    if (failing.includes(args.work_order)) return Promise.reject(new Error('no'));\n"
            "    return Promise.resolve(details[args.work_order] || {});\n"
            "  },\n"
            "  show_alert: (a) => alerts.push([a.message, a.indicator]),\n"
            "  ui: {form: {on: (doctype, h) => { handlers[doctype] = h; }}},\n"
            "};\n"
            "globalThis.isnack = isnack;\n"
            f"{script}\n"
            "const lines = isnack.quality_hub_lines;\n"
            "const flush = async () => { for (let i = 0; i < 5; i++) await new Promise((r) => setTimeout(r, 0)); };\n"
            "const record = (values, fields = ['factory_line', 'work_order']) => ({values, log: [],\n"
            "  get(f) { return values[f]; }, set(f, v) { this.log.push([f, v]); values[f] = v; },\n"
            "  has: (f) => fields.includes(f), alive: () => true});\n"
            "(async () => {\n"
            "  const out = {};\n"
            f"{body}\n"
            "  console.log(JSON.stringify(out));\n"
            "})();\n"
        )
        run = subprocess.run(["node", "-e", harness], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr[-2000:])
        return json.loads(run.stdout)

    def test_the_work_orders_a_line_offers(self):
        out = self._run(
            "  out.before = lines.work_order_lines('PACKING LINE 1');\n"
            "  await lines.load();\n"
            "  out.lines = ['PACKING LINE 1', ' packing line 1', 'FRYING', '', null].map((l) => lines.work_order_lines(l));\n"
            "  const df = {};\n"
            "  out.none = lines.work_order_query('', df); out.none_note = df.filter_description;\n"
            "  out.packing = lines.work_order_query('PACKING LINE 1', df); out.packing_note = df.filter_description;\n"
            "  out.frying = lines.work_order_query('FRYING');\n"
        )
        # a line's own Work Orders until the settings are read
        self.assertEqual(out["before"], ["PACKING LINE 1"])
        # a packing line: its own and those of the lines it packs for (as the
        # database matches a line); a production line: its own; no line: every Work Order
        self.assertEqual(
            out["lines"],
            [["PACKING LINE 1", "CORN EXTRUSION", "FRYING"], [" packing line 1", "CORN EXTRUSION", "FRYING"], ["FRYING"], None, None],
        )
        self.assertEqual((out["none"], out["none_note"]), ({}, None))
        self.assertEqual(
            out["packing"],
            {"filters": [["Work Order", "custom_factory_line", "in", ["PACKING LINE 1", "CORN EXTRUSION", "FRYING"]], ["Work Order", "docstatus", "<", 2]]},
        )
        self.assertEqual(out["packing_note"], "Work Orders for PACKING LINE 1")
        self.assertEqual(out["frying"]["filters"][0], ["Work Order", "custom_factory_line", "in", ["FRYING"]])

    def test_the_product_a_work_order_makes(self):
        out = self._run(
            "  const df = {};\n"
            "  out.none = lines.product_query('', df); out.none_note = df.filter_description;\n"
            "  out.unread = lines.product_query('WO-MIX', df);\n"
            "  await flush();\n"
            "  out.read = lines.product_query('WO-MIX', df); out.read_note = df.filter_description;\n"
            "  lines.product_query('WO-MIX', df);\n"
            "  out.calls = calls.slice();\n"
        )
        finished_goods = {"filters": [["Item", "item_group", "=", "Finished Goods"]]}
        self.assertEqual((out["none"], out["none_note"]), (finished_goods, "Finished Goods items"))
        # a Work Order not read yet: read for the next search
        self.assertEqual(out["unread"], finished_goods)
        # the item it makes, whatever its group (a Semi-Finished one here)
        self.assertEqual(out["read"], {"filters": [["Item", "name", "=", "SFG10001"]]})
        self.assertEqual(out["read_note"], "The item Work Order WO-MIX makes")
        # read once
        self.assertEqual(out["calls"], [["get_work_order_details", "WO-MIX"]])

    def test_a_line_changed(self):
        out = self._run(
            "  // a production line's Work Order, on the packing line that packs for it: kept\n"
            "  const kept = record({factory_line: 'PACKING LINE 1', work_order: 'WO-EXT'});\n"
            "  await lines.line_changed(kept);\n"
            "  // on a packing line that does not: taken off, and the user told\n"
            "  const off = record({factory_line: 'PACKING LINE 2', work_order: 'WO-EXT'});\n"
            "  await lines.line_changed(off);\n"
            "  // a Work Order planned on no line is offered on none\n"
            "  const lineless = record({factory_line: 'FRYING', work_order: 'WO-NONE'});\n"
            "  await lines.line_changed(lineless);\n"
            "  // the line changed again before the answer came: left to that change\n"
            "  const again = record({factory_line: 'CORN MIX', work_order: 'WO-FRY'});\n"
            "  const pending = lines.line_changed(again); again.values.factory_line = 'FRYING'; await pending;\n"
            "  // a Work Order that cannot be read, no Work Order, no line: left as they are\n"
            "  failing = ['WO-SECRET'];\n"
            "  const secret = record({factory_line: 'FRYING', work_order: 'WO-SECRET'});\n"
            "  await lines.line_changed(secret);\n"
            "  const empty = record({factory_line: 'FRYING', work_order: ''}); await lines.line_changed(empty);\n"
            "  const unlined = record({factory_line: '', work_order: 'WO-FRY'}); await lines.line_changed(unlined);\n"
            "  out.set = [kept, off, lineless, again, secret, empty, unlined].map((r) => r.log);\n"
            "  out.alerts = alerts;\n"
        )
        self.assertEqual(out["set"], [[], [["work_order", ""]], [["work_order", ""]], [], [], [], []])
        self.assertEqual(
            out["alerts"],
            [
                ["WO-EXT is not a Work Order for PACKING LINE 2: pick one from the list.", "orange"],
                ["WO-NONE is not a Work Order for FRYING: pick one from the list.", "orange"],
            ],
        )

    def test_a_work_order_picked(self):
        out = self._run(
            "  const fields = ['factory_line', 'work_order', 'product_item'];\n"
            "  // offered: the Product Item takes the item it makes\n"
            "  const picked = record({factory_line: 'PACKING LINE 1', work_order: 'WO-FRY', product_item: 'FG10020'}, fields);\n"
            "  await lines.work_order_changed(picked);\n"
            "  // no line yet: any Work Order, its item filled in\n"
            "  const first = record({factory_line: '', work_order: 'WO-MIX'}, fields);\n"
            "  await lines.work_order_changed(first);\n"
            "  // a record with no Product Item\n"
            "  const packing = record({factory_line: 'PACKING LINE 1', work_order: 'WO-EXT'});\n"
            "  await lines.work_order_changed(packing);\n"
            "  // typed in full, not offered: taken off, its item not filled in\n"
            "  const typed = record({factory_line: 'FRYING', work_order: 'WO-EXT', product_item: ''}, fields);\n"
            "  await lines.work_order_changed(typed);\n"
            "  // picked again before the answer came: left to that pick\n"
            "  const again = record({factory_line: 'FRYING', work_order: 'WO-EXT'}, fields);\n"
            "  const pending = lines.work_order_changed(again); again.values.work_order = 'WO-FRY'; await pending;\n"
            "  // the line changed before the answer came: left to that change\n"
            "  const moved = record({factory_line: 'FRYING', work_order: 'WO-EXT'}, fields);\n"
            "  const moving = lines.work_order_changed(moved); moved.values.factory_line = 'CORN EXTRUSION'; await moving;\n"
            "  // the item already there, a Work Order that cannot be read, none\n"
            "  const same = record({factory_line: 'FRYING', work_order: 'WO-FRY', product_item: 'FG10001'}, fields);\n"
            "  await lines.work_order_changed(same);\n"
            "  failing = ['WO-SECRET'];\n"
            "  const secret = record({factory_line: 'FRYING', work_order: 'WO-SECRET', product_item: 'FG10001'}, fields);\n"
            "  await lines.work_order_changed(secret); await lines.work_order_changed(secret);\n"
            "  await lines.work_order_changed(record({factory_line: 'FRYING', work_order: ''}, fields));\n"
            "  out.set = [picked, first, packing, typed, again, moved, same, secret].map((r) => r.log);\n"
            "  out.alerts = alerts;\n"
            "  out.details = calls.filter((c) => c[0] === 'get_work_order_details').map((c) => c[1]);\n"
        )
        self.assertEqual(
            out["set"],
            [
                [["product_item", "FG10001"]],
                [["product_item", "SFG10001"]],
                [],
                [["work_order", ""]],
                [],
                [],
                [],
                [],
            ],
        )
        self.assertEqual(out["alerts"], [["WO-EXT is not a Work Order for FRYING: pick one from the list.", "orange"]])
        # each Work Order read once; one that could not be, asked again next time
        self.assertEqual(out["details"], ["WO-FRY", "WO-MIX", "WO-EXT", "WO-SECRET", "WO-SECRET"])

    def test_the_forms(self):
        out = self._run(
            "  const form = (doctype, doc, fields) => {\n"
            "    const fields_dict = {}; fields.forEach((f) => { fields_dict[f] = {df: {}}; });\n"
            "    const frm = {doctype, doc, queries: {}, set: [], fields_dict, is_new: () => false,\n"
            "      set_query: (f, q) => { frm.queries[f] = q; }, set_value: (f, v) => { frm.set.push([f, v]); frm.doc[f] = v; }};\n"
            "    handlers[doctype].setup(frm);\n"
            "    return frm;\n"
            "  };\n"
            "  await lines.load();\n"
            "  const puffs = form('QC Puffs Extruder Record', {factory_line: 'PACKING LINE 1', work_order: 'WO-FRY'},\n"
            "    ['factory_line', 'work_order', 'product_item']);\n"
            "  out.queried = Object.keys(puffs.queries);\n"
            "  out.work_order = puffs.queries.work_order(); out.work_order_note = puffs.fields_dict.work_order.df.filter_description;\n"
            "  handlers['QC Puffs Extruder Record'].onload(puffs); await flush();\n"
            "  out.product = puffs.queries.product_item(); out.product_note = puffs.fields_dict.product_item.df.filter_description;\n"
            "  // the Work Order picked fills in the Product Item\n"
            "  handlers['QC Puffs Extruder Record'].work_order(puffs); await flush();\n"
            "  // the line changed: the Work Order it does not offer taken off\n"
            "  puffs.doc.factory_line = 'PACKING LINE 2';\n"
            "  handlers['QC Puffs Extruder Record'].factory_line(puffs); await flush();\n"
            "  out.puffs = puffs.set;\n"
            "  // another document opened before the answer came: left as it is\n"
            "  const check = form('QC Packaging Check', {factory_line: 'PACKING LINE 2', work_order: 'WO-EXT'}, ['factory_line', 'work_order']);\n"
            "  out.check_queried = Object.keys(check.queries);\n"
            "  handlers['QC Packaging Check'].factory_line(check); check.doc = {factory_line: 'PACKING LINE 2', work_order: 'WO-EXT'}; await flush();\n"
            "  out.check = check.set;\n"
        )
        self.assertEqual(out["queried"], ["factory_line", "work_order", "product_item"])
        self.assertEqual(out["work_order"]["filters"][0], ["Work Order", "custom_factory_line", "in", ["PACKING LINE 1", "CORN EXTRUSION", "FRYING"]])
        self.assertEqual(out["work_order_note"], "Work Orders for PACKING LINE 1")
        # the Work Order's item, read as the form loaded
        self.assertEqual(out["product"], {"filters": [["Item", "name", "=", "FG10001"]]})
        self.assertEqual(out["product_note"], "The item Work Order WO-FRY makes")
        self.assertEqual(out["puffs"], [["product_item", "FG10001"], ["work_order", ""]])
        # a record with no Product Item has no query for one
        self.assertEqual(out["check_queried"], ["factory_line", "work_order"])
        self.assertEqual(out["check"], [])
