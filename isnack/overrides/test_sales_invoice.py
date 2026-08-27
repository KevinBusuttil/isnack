# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""Tests for the Sales Invoice customisations the app ships.

The customisations live in ``isnack/isnack/custom/sales_invoice.json`` and are
applied by frappe's ``sync_customizations`` on every ``bench migrate``. That
folder is a data folder, not a python package, so the tests for it live here,
next to the app's other Sales Invoice code.

No site or database is needed: the subject is the declaration itself.
"""

import json
import os
import unittest

CUSTOMISATION_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "isnack",
    "custom",
    "sales_invoice.json",
)


def _load():
    with open(CUSTOMISATION_FILE) as f:
        return json.load(f)


class TestSalesInvoiceCustomisations(unittest.TestCase):
    def setUp(self):
        self.data = _load()

    def _property_setters(self, field_name, property_name):
        return [
            ps
            for ps in self.data["property_setters"]
            if ps.get("field_name") == field_name and ps.get("property") == property_name
        ]

    def test_customisations_are_synced_on_migrate(self):
        # Without this flag sync_customizations skips the file outside of install.
        self.assertEqual(self.data["sync_on_migrate"], 1)
        self.assertEqual(self.data["doctype"], "Sales Invoice")

    def test_remarks_is_editable_after_submit(self):
        setters = self._property_setters("remarks", "allow_on_submit")
        self.assertEqual(len(setters), 1)

        setter = setters[0]
        self.assertEqual(setter["doc_type"], "Sales Invoice")
        self.assertEqual(setter["doctype_or_field"], "DocField")
        self.assertEqual(setter["property_type"], "Check")
        self.assertEqual(setter["value"], "1")

    def test_remarks_setter_carries_frappes_autoname(self):
        # PropertySetter.autoname builds "{doc_type}-{field_name}-{property}".
        # Matching it keeps the export shape valid and the record replaceable.
        names = [ps["name"] for ps in self._property_setters("remarks", "allow_on_submit")]
        self.assertEqual(names, ["Sales Invoice-remarks-allow_on_submit"])

    def test_no_property_is_set_twice(self):
        keys = [
            (ps.get("doc_type"), ps.get("field_name"), ps.get("row_name"), ps.get("property"))
            for ps in self.data["property_setters"]
        ]
        self.assertEqual(len(keys), len(set(keys)))

    def test_file_matches_frappes_export_format(self):
        # frappe.as_json writes indent=1, sort_keys=True. Keeping the file in
        # that shape means a later "Customize Form -> export" is a clean diff.
        with open(CUSTOMISATION_FILE) as f:
            on_disk = f.read()

        self.assertEqual(on_disk, json.dumps(self.data, indent=1, sort_keys=True) + "\n")


if __name__ == "__main__":
    unittest.main()
