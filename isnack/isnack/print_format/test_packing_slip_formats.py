# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""Rendering tests for the two ISNACK Packing Slip print formats.

The formats are Jinja stored inside the Print Format JSON, so the only way to
test what they print is to render them. The templates are rendered here through
a jinja2 environment configured like frappe's (``SandboxedEnvironment``,
``DebugUndefined``, autoescape off -- see ``frappe.utils.jinja.get_jenv``) with
small stand-ins for ``doc``, ``frappe`` and the app's jinja methods, so no site
or database is needed.

The subject of these tests is the footer text: it must come from
``Delivery Note.instructions`` and never from a Sales Invoice, so the ``frappe``
stub fails the test the moment a format asks for an invoice -- except in the one
test that hands it an invoice to ignore.
"""

import json
import os
import unittest
from datetime import date

from jinja2 import DebugUndefined
from jinja2.sandbox import SandboxedEnvironment

PRINT_FORMAT_DIR = os.path.dirname(os.path.abspath(__file__))

# The instructions a user typed on the Delivery Note, single- and multi-line.
INSTRUCTIONS = "Deliver before 12:00. Use loading bay 3."
MULTILINE_INSTRUCTIONS = (
    "Deliver before 12:00\nUse loading bay 3\nCall customer before unloading"
)
# What ERPNext tends to leave in Sales Invoice.remarks, and the reason the slip
# stopped printing it: it is accounting text, not a shipping instruction.
SALES_INVOICE_REMARKS = "Against Customer Order PO-9912"
# How the instructions reach the page: an inline pre-wrap span around the value,
# so the newlines of the Text field survive without any new CSS.
INSTRUCTIONS_SPAN = '<span style="white-space: pre-wrap;">%s</span>'


class _Doc:
    """Stand-in for a frappe document: attribute access plus ``get()``.

    Unset fields read as ``None`` rather than raising, the way a saved
    Document's untouched fields do.
    """

    def __init__(self, **values):
        self.__dict__.update(values)

    def get(self, key, default=None):
        return self.__dict__.get(key, default)

    def __getattr__(self, key):
        return None


class _FrappeStub:
    """The subset of the ``frappe`` namespace these print formats reach for.

    Every lookup is recorded in ``doctypes_read``. Sales Invoice data is served
    only when a test passes ``sales_invoice``, standing in for a site where the
    Delivery Note has been billed; otherwise asking for one fails the test,
    since the slip must not depend on an invoice existing at all.
    """

    def __init__(self, delivery_note=None, addresses=None, sales_invoice=None):
        self.delivery_note = delivery_note
        self.addresses = addresses or {}
        self.sales_invoice = sales_invoice
        self.doctypes_read = []
        self.utils = _Doc(flt=_flt, formatdate=_formatdate)

    @property
    def db(self):
        return self

    def _record(self, doctype):
        self.doctypes_read.append(doctype)
        if doctype.startswith("Sales Invoice") and self.sales_invoice is None:
            raise AssertionError(
                f"the Packing Slip print format must not read {doctype}"
            )

    def get_doc(self, doctype, name):
        self._record(doctype)
        if doctype == "Delivery Note":
            return self.delivery_note
        if doctype == "Address":
            return self.addresses[name]
        raise AssertionError(f"unexpected get_doc({doctype!r}, {name!r})")

    def get_value(self, doctype, name, fields):
        self._record(doctype)
        if doctype == "Sales Invoice Item":
            return "ACC-SINV-2026-00042"
        if doctype == "Sales Invoice":
            return self.sales_invoice
        if doctype == "Company":
            return "/files/isnack-logo.png"
        if doctype == "Batch":
            return date(2027, 1, 31)
        if doctype == "Item":
            return {"customs_tariff_number": "1905 90", "weight_per_unit": 1.17}[fields]
        raise AssertionError(f"unexpected get_value({doctype!r}, {name!r}, {fields!r})")

    def format_value(self, value, df=None, **kwargs):
        if df and df.get("fieldtype") == "Float":
            return f"{_flt(value):.3f}"
        return str(value)


def _flt(value, precision=None):
    value = float(value or 0)
    return round(value, precision) if precision is not None else value


def _formatdate(value, *args, **kwargs):
    return value.strftime("%d-%m-%Y") if value else ""


def _render(print_format, doc, delivery_note=None, addresses=None, sales_invoice=None):
    """Render a stored print format, returning ``(html, frappe_stub)``."""
    path = os.path.join(PRINT_FORMAT_DIR, print_format, f"{print_format}.json")
    with open(path, encoding="utf-8") as f:
        template = json.load(f)["html"]

    frappe = _FrappeStub(
        delivery_note=delivery_note, addresses=addresses, sales_invoice=sales_invoice
    )
    # Mirrors frappe.utils.jinja.get_jenv: sandboxed, DebugUndefined, and no
    # autoescape -- which is why the format escapes the instructions itself.
    env = SandboxedEnvironment(undefined=DebugUndefined, autoescape=False)
    html = env.from_string(template).render(
        doc=doc,
        frappe=frappe,
        # isnack.api.delivery_note_pallets.get_dn_item_bundle_batches, exposed
        # through the `jinja` hook. Rows here carry their own batch.
        get_dn_item_bundle_batches=lambda dn_detail: [],
    )
    return html, frappe


def _slip(name="MAT-PAC-2026-00001", **overrides):
    values = dict(
        name=name,
        delivery_note="MAT-DN-2026-00007",
        posting_date=date(2026, 8, 27),
        net_weight_pkg=210.0,
        net_weight_uom="Kg",
        gross_weight_pkg=292.5,
        gross_weight_uom="Kg",
        items=[
            _Doc(
                item_code="FG10002",
                description="Corn Puffs 30g",
                qty=250,
                stock_uom="Carton",
                net_weight=0.84,
                batch_no="BATCH-0001",
                custom_pallet_type="EUR1",
                custom_pallet_qty=2,
            )
        ],
        custom_pallets=[],
    )
    values.update(overrides)
    return _Doc(**values)


def _delivery_note(instructions=None, **overrides):
    values = dict(
        name="MAT-DN-2026-00007",
        company="ISNACK SARL",
        customer="CUST-0001",
        customer_name="Acme Foods SA",
        currency="EUR",
        incoterm="FCA",
        named_place="Enfidha",
        po_no="PO-9912",
        instructions=instructions,
    )
    values.update(overrides)
    return _Doc(**values)


def _address(**overrides):
    values = dict(
        address_title="Acme Foods SA",
        address_line1="12 Rue du Port",
        address_line2=None,
        city="Marseille",
        pincode="13002",
        country="France",
    )
    values.update(overrides)
    return _Doc(**values)


def _pallet(pallet_no, qty=125):
    """A row of the ISNACK pallet manifest (Packing Slip `custom_pallets`)."""
    return _Doc(
        pallet_no=pallet_no,
        pallet_type="EUR1",
        item_code="FG10002",
        batch_no="BATCH-0001",
        qty=qty,
        uom="Carton",
    )


class _PackingSlipFormatTests:
    """Shared expectations -- both formats print the same footer."""

    PRINT_FORMAT = None
    # `.weights-footer` also names a rule in the <style> block, so the footer
    # is looked for by its element.
    FOOTER = '<div class="weights-footer">'

    def render(self, doc=None, delivery_note=None, **kwargs):
        return _render(
            self.PRINT_FORMAT,
            doc if doc is not None else _slip(),
            delivery_note=delivery_note,
            **kwargs,
        )

    def assertRendered(self, html):
        """No DebugUndefined leftovers, i.e. the stub covered the template."""
        self.assertNotIn("{{", html)

    def test_delivery_note_instructions_are_printed(self):
        html, _ = self.render(delivery_note=_delivery_note(INSTRUCTIONS))

        self.assertRendered(html)
        self.assertIn("Instructions:", html)
        self.assertIn(INSTRUCTIONS, html)

    def test_label_is_exactly_instructions(self):
        html, _ = self.render(delivery_note=_delivery_note(INSTRUCTIONS))

        self.assertIn(
            '<span class="weights-remark-label">Instructions:</span>', html
        )
        self.assertNotIn("Remark:", html)
        self.assertNotIn("Delivery Instructions:", html)

    def test_blank_instructions_print_no_label(self):
        for blank in (None, "", "   \n  "):
            with self.subTest(instructions=repr(blank)):
                html, _ = self.render(delivery_note=_delivery_note(blank))

                self.assertRendered(html)
                self.assertNotIn("Instructions:", html)
                # The weights keep the footer, so nothing else is lost.
                self.assertIn(self.FOOTER, html)
                self.assertIn("Net Weight:", html)
                self.assertIn("Gross Weight:", html)

    def test_footer_is_dropped_when_there_are_no_weights_and_no_instructions(self):
        doc = _slip(net_weight_pkg=0, gross_weight_pkg=0)
        html, _ = self.render(doc=doc, delivery_note=_delivery_note(None))

        self.assertRendered(html)
        self.assertNotIn(self.FOOTER, html)

    def test_instructions_alone_bring_the_footer_back(self):
        doc = _slip(net_weight_pkg=0, gross_weight_pkg=0)
        html, _ = self.render(doc=doc, delivery_note=_delivery_note(INSTRUCTIONS))

        self.assertIn(self.FOOTER, html)
        self.assertIn(INSTRUCTIONS, html)
        self.assertNotIn("Net Weight:", html)

    def test_multiline_instructions_keep_their_line_breaks(self):
        html, _ = self.render(delivery_note=_delivery_note(MULTILINE_INSTRUCTIONS))

        self.assertRendered(html)
        # The newlines reach the page as newlines...
        self.assertIn(MULTILINE_INSTRUCTIONS, html)
        # ...inside an element that renders them, rather than collapsing them.
        self.assertIn(INSTRUCTIONS_SPAN % MULTILINE_INSTRUCTIONS, html)

    def test_surrounding_whitespace_is_trimmed(self):
        """A trailing newline must not print as a blank line under pre-wrap."""
        html, _ = self.render(
            delivery_note=_delivery_note(f"\n{MULTILINE_INSTRUCTIONS}\n\n")
        )

        self.assertIn(INSTRUCTIONS_SPAN % MULTILINE_INSTRUCTIONS, html)

    def test_instruction_text_is_escaped_not_stripped(self):
        html, _ = self.render(
            delivery_note=_delivery_note("Deliver <before> 12:00 & call ahead")
        )

        self.assertIn(
            INSTRUCTIONS_SPAN % "Deliver &lt;before&gt; 12:00 &amp; call ahead", html
        )

    def test_no_sales_invoice_is_read(self):
        """The text used to come from Sales Invoice.remarks. It must not."""
        html, frappe = self.render(delivery_note=_delivery_note(INSTRUCTIONS))

        self.assertRendered(html)
        self.assertIn(INSTRUCTIONS, html)
        self.assertEqual(
            [d for d in frappe.doctypes_read if d.startswith("Sales Invoice")], []
        )

    def test_an_invoice_with_remarks_is_ignored(self):
        """Even where the invoice exists and has remarks, they stay off the slip."""
        html, frappe = self.render(
            delivery_note=_delivery_note(INSTRUCTIONS),
            sales_invoice=SALES_INVOICE_REMARKS,
        )

        self.assertRendered(html)
        self.assertNotIn(SALES_INVOICE_REMARKS, html)
        self.assertNotIn("Remark:", html)
        self.assertIn(INSTRUCTIONS, html)
        self.assertEqual(
            [d for d in frappe.doctypes_read if d.startswith("Sales Invoice")], []
        )

    def test_renders_without_any_sales_invoice(self):
        """No invoice, no linked Sales Order: the slip still prints in full."""
        doc = _slip(custom_sales_order=None)
        html, _ = self.render(doc=doc, delivery_note=_delivery_note(INSTRUCTIONS))

        self.assertRendered(html)
        self.assertIn("Packing Slip", html)
        self.assertIn("FG10002", html)
        self.assertIn("Instructions:", html)
        self.assertIn("Net Weight:", html)

    def test_every_slip_of_one_delivery_note_shows_the_same_instructions(self):
        """ISNACK creates one slip per Sales Order; the text is DN-level."""
        dn = _delivery_note(MULTILINE_INSTRUCTIONS)

        first, _ = self.render(
            doc=_slip("MAT-PAC-2026-00001", custom_sales_order="SO-0001"),
            delivery_note=dn,
        )
        second, _ = self.render(
            doc=_slip("MAT-PAC-2026-00002", custom_sales_order="SO-0002"),
            delivery_note=dn,
        )

        marker = INSTRUCTIONS_SPAN % MULTILINE_INSTRUCTIONS
        self.assertIn(marker, first)
        self.assertIn(marker, second)

    def test_the_rest_of_the_slip_is_untouched(self):
        """Everything the footer change was not supposed to move."""
        dn = _delivery_note(
            INSTRUCTIONS,
            customer_address="ADDR-BILL",
            shipping_address_name="ADDR-SHIP",
            tax_id="FR12345678901",
        )
        html, _ = self.render(
            doc=_slip(custom_pallets=[_pallet(1), _pallet(2)]),
            delivery_note=dn,
            addresses={
                "ADDR-BILL": _address(),
                "ADDR-SHIP": _address(address_title="Acme DC Nord", city="Lille"),
            },
        )

        self.assertRendered(html)
        for expected in (
            'id="header-html"',  # heading repeated on every PDF page
            'id="footer-html"',  # page numbering
            "Bill To",
            "Ship To",
            "Acme Foods SA",
            "Acme DC Nord",
            "FR12345678901",
            "FCA",  # incoterm
            "Enfidha",  # named place
            "PO-9912",  # reference
            "CURRENCY:",
            "BATCH-0001",
            "31-01-2027",  # batch expiry
            "Package Statistics",
            "Pallet Breakdown",
            "EUR1",  # pallet type
            "Net Weight:",
            "Gross Weight:",
            "Instructions:",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, html)

    def test_slip_without_a_delivery_note_still_renders(self):
        doc = _slip(delivery_note=None)
        html, _ = self.render(doc=doc)

        self.assertRendered(html)
        self.assertNotIn("Instructions:", html)
        self.assertIn("Net Weight:", html)

    def _template(self):
        path = os.path.join(
            PRINT_FORMAT_DIR, self.PRINT_FORMAT, f"{self.PRINT_FORMAT}.json"
        )
        with open(path, encoding="utf-8") as f:
            return json.load(f)["html"]

    def test_source_holds_no_sales_invoice_lookup(self):
        template = self._template()

        self.assertNotIn("Sales Invoice", template)
        self.assertNotIn("remarks", template)

    def test_the_stylesheet_gained_nothing(self):
        """The instructions must not cost the tuned layout a single CSS rule.

        Everything about how they print is inline on the value itself, so the
        <style> block -- margins, page geometry, the repeating header and
        footer, table and font sizing -- has no stake in this change.
        """
        style = self._template().split("</style>")[0]

        self.assertNotIn("instruction", style.lower())
        self.assertNotIn("pre-wrap", style)
        # The footer still hangs off the rules that were already there.
        for rule in (".weights-footer {", ".weights-remark {", ".weights-remark-label {"):
            with self.subTest(rule=rule):
                self.assertIn(rule, style)

    def test_the_footer_markup_is_the_original(self):
        """Only the label and the value inside it changed."""
        template = self._template()

        self.assertIn('<div class="col-xs-6 weights-remark">', template)
        self.assertIn('<span class="weights-remark-label">Instructions:</span>', template)
        self.assertIn('<div class="col-xs-6 text-right">', template)


class TestIsnackPackingSlip(_PackingSlipFormatTests, unittest.TestCase):
    PRINT_FORMAT = "isnack_packing_slip"


class TestPackingSlipMixed(_PackingSlipFormatTests, unittest.TestCase):
    PRINT_FORMAT = "packing_slip_mixed"


if __name__ == "__main__":
    unittest.main()
