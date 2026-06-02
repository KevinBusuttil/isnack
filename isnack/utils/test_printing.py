# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import unittest
from unittest.mock import patch

from isnack.utils import printing


class TestEnqueueDocPrint(unittest.TestCase):
    """`enqueue_doc_print` resolves the printer + Print Format and enqueues a job."""

    @patch("isnack.utils.printing.frappe.enqueue")
    @patch("isnack.utils.printing.frappe.db.get_value",
           return_value="Isnack Packing Slip")
    @patch("isnack.utils.printing.get_a4_printer", return_value="Main A4")
    def test_resolves_defaults_and_enqueues(
        self, _printer, _get_value, mock_enqueue
    ):
        result = printing.enqueue_doc_print("Packing Slip", "PS-001")

        self.assertTrue(result)
        mock_enqueue.assert_called_once_with(
            "frappe.utils.print_format.print_by_server",
            queue="short",
            doctype="Packing Slip",
            name="PS-001",
            printer_setting="Main A4",
            print_format="Isnack Packing Slip",
        )

    @patch("isnack.utils.printing.frappe.enqueue")
    @patch("isnack.utils.printing.get_a4_printer", return_value=None)
    def test_no_printer_is_a_noop(self, _printer, mock_enqueue):
        # When no A4 printer is configured the helper must not enqueue
        # anything, so a missing-printer setup never blocks Delivery Note
        # submission.
        self.assertFalse(printing.enqueue_doc_print("Packing Slip", "PS-001"))
        mock_enqueue.assert_not_called()

    @patch("isnack.utils.printing.frappe.enqueue")
    @patch("isnack.utils.printing.frappe.db.get_value", return_value=None)
    @patch("isnack.utils.printing.get_a4_printer", return_value="Main A4")
    def test_falls_back_to_standard_print_format(
        self, _printer, _get_value, mock_enqueue
    ):
        printing.enqueue_doc_print("Packing Slip", "PS-001")

        kwargs = mock_enqueue.call_args.kwargs
        self.assertEqual(kwargs["print_format"], "Standard")

    @patch("isnack.utils.printing.frappe.enqueue")
    @patch("isnack.utils.printing.get_a4_printer", return_value="Main A4")
    def test_explicit_overrides_win(self, _printer, mock_enqueue):
        printing.enqueue_doc_print(
            "Packing Slip", "PS-001",
            printer="Override Printer", print_format="Custom PF",
        )

        kwargs = mock_enqueue.call_args.kwargs
        self.assertEqual(kwargs["printer_setting"], "Override Printer")
        self.assertEqual(kwargs["print_format"], "Custom PF")


if __name__ == "__main__":
    unittest.main()
