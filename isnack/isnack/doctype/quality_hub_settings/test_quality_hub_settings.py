# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""Quality Hub Settings: the factory lines each Quality Hub tab records on
(2026-11), and the QC records held to them (no database)."""

import json
import os
import re
import shutil
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from isnack.isnack.doctype.quality_hub_settings import quality_hub_settings as settings_module
from isnack.isnack.doctype.quality_hub_settings.quality_hub_settings import (
    RESTRICTED_DOCTYPES,
    TAB_FIELDS,
    QualityHubSettings,
    check_factory_line,
    factory_lines,
    get_factory_lines,
)

DOCTYPE_DIR = os.path.join(os.path.dirname(__file__), "..")
APP_DIR = os.path.join(DOCTYPE_DIR, "..", "..")


def _doctype(name):
    folder = name.lower().replace(" ", "_")
    with open(os.path.join(DOCTYPE_DIR, folder, f"{folder}.json")) as fh:
        return json.load(fh)


LABELS = {f["fieldname"]: f.get("label") for f in _doctype("Quality Hub Settings")["fields"]}


class _Settings(frappe._dict):
    """Quality Hub Settings as the database holds them: ``lines`` by field."""

    def get(self, fieldname, default=None):
        return [frappe._dict(factory_line=line) for line in self.lines.get(fieldname, [])]


def _given(**lines):
    return patch("frappe.get_cached_doc", return_value=_Settings(lines=lines))


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
            "  xcall: (method) => { calls.push(method); return Promise.resolve(given); },\n"
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
        self.assertEqual(out["calls"], ["isnack.isnack.doctype.quality_hub_settings.quality_hub_settings.get_factory_lines"])
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
