# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# License: MIT
# Tests for sync_attachment_to_journal_entries file hook

import unittest
from unittest.mock import MagicMock, call, patch

from isnack.overrides.file_hooks import sync_attachment_to_journal_entries


class TestSyncAttachmentToJournalEntries(unittest.TestCase):
    """Tests for sync_attachment_to_journal_entries hook."""

    def _make_file_doc(self, attached_to_doctype="Service Invoice", attached_to_name="SINV-001"):
        doc = MagicMock()
        doc.attached_to_doctype = attached_to_doctype
        doc.attached_to_name = attached_to_name
        doc.file_url = "/files/invoice.pdf"
        doc.file_name = "invoice.pdf"
        doc.folder = "Home/Attachments"
        doc.is_private = 0
        return doc

    # ------------------------------------------------------------------
    # Early-return guards
    # ------------------------------------------------------------------

    @patch("isnack.overrides.file_hooks.frappe")
    def test_non_service_invoice_doctype_is_ignored(self, mock_frappe):
        """Files attached to other doctypes must not trigger any DB queries."""
        doc = self._make_file_doc(attached_to_doctype="Journal Entry")
        sync_attachment_to_journal_entries(doc)
        mock_frappe.db.get_value.assert_not_called()

    @patch("isnack.overrides.file_hooks.frappe")
    def test_draft_service_invoice_is_ignored(self, mock_frappe):
        """Files attached to a *draft* (docstatus=0) Service Invoice must be skipped."""
        mock_frappe.db.get_value.return_value = 0  # draft
        doc = self._make_file_doc()
        sync_attachment_to_journal_entries(doc)
        mock_frappe.get_all.assert_not_called()

    @patch("isnack.overrides.file_hooks.frappe")
    def test_cancelled_service_invoice_is_ignored(self, mock_frappe):
        """Files attached to a *cancelled* (docstatus=2) Service Invoice must be skipped."""
        mock_frappe.db.get_value.return_value = 2  # cancelled
        doc = self._make_file_doc()
        sync_attachment_to_journal_entries(doc)
        mock_frappe.get_all.assert_not_called()

    # ------------------------------------------------------------------
    # Happy path
    # ------------------------------------------------------------------

    @patch("isnack.overrides.file_hooks.frappe")
    def test_attachment_copied_to_linked_journal_entries(self, mock_frappe):
        """New file on a submitted SI must be copied to each linked Journal Entry."""
        mock_frappe.db.get_value.return_value = 1  # submitted
        mock_frappe.get_all.return_value = ["JV-001", "JV-002"]
        mock_frappe.db.exists.return_value = None  # not yet attached

        new_file_doc = MagicMock()
        mock_frappe.get_doc.return_value = new_file_doc

        doc = self._make_file_doc()
        sync_attachment_to_journal_entries(doc)

        # get_doc should have been called once per JE
        self.assertEqual(mock_frappe.get_doc.call_count, 2)

        # Verify the payload for the first JE
        first_call_args = mock_frappe.get_doc.call_args_list[0][0][0]
        self.assertEqual(first_call_args["doctype"], "File")
        self.assertEqual(first_call_args["attached_to_doctype"], "Journal Entry")
        self.assertEqual(first_call_args["attached_to_name"], "JV-001")
        self.assertEqual(first_call_args["file_url"], doc.file_url)

        # save() must be called with ignore_permissions=True
        new_file_doc.save.assert_called_with(ignore_permissions=True)
        self.assertEqual(new_file_doc.save.call_count, 2)

    @patch("isnack.overrides.file_hooks.frappe")
    def test_duplicate_attachment_not_created(self, mock_frappe):
        """If the same file_url is already attached to a JE, skip it."""
        mock_frappe.db.get_value.return_value = 1  # submitted
        mock_frappe.get_all.return_value = ["JV-001"]
        mock_frappe.db.exists.return_value = True  # already attached

        doc = self._make_file_doc()
        sync_attachment_to_journal_entries(doc)

        mock_frappe.get_doc.assert_not_called()

    @patch("isnack.overrides.file_hooks.frappe")
    def test_empty_journal_entry_values_are_skipped(self, mock_frappe):
        """Rows with a blank journal_entry value must be skipped gracefully."""
        mock_frappe.db.get_value.return_value = 1  # submitted
        mock_frappe.get_all.return_value = [None, "", "JV-001"]
        mock_frappe.db.exists.return_value = None  # not yet attached

        new_file_doc = MagicMock()
        mock_frappe.get_doc.return_value = new_file_doc

        doc = self._make_file_doc()
        sync_attachment_to_journal_entries(doc)

        # Only the valid JE name should result in a get_doc call
        self.assertEqual(mock_frappe.get_doc.call_count, 1)
        call_args = mock_frappe.get_doc.call_args_list[0][0][0]
        self.assertEqual(call_args["attached_to_name"], "JV-001")

    @patch("isnack.overrides.file_hooks.frappe")
    def test_no_journal_entries_linked(self, mock_frappe):
        """If the SI has no linked JEs, no files should be created."""
        mock_frappe.db.get_value.return_value = 1  # submitted
        mock_frappe.get_all.return_value = []

        doc = self._make_file_doc()
        sync_attachment_to_journal_entries(doc)

        mock_frappe.get_doc.assert_not_called()

    @patch("isnack.overrides.file_hooks.frappe")
    def test_partial_duplicate_only_new_entries_get_file(self, mock_frappe):
        """If the file is already on some JEs but not others, only missing ones are created."""
        mock_frappe.db.get_value.return_value = 1  # submitted
        mock_frappe.get_all.return_value = ["JV-001", "JV-002"]

        # JV-001 already has the attachment; JV-002 does not
        mock_frappe.db.exists.side_effect = [True, None]

        new_file_doc = MagicMock()
        mock_frappe.get_doc.return_value = new_file_doc

        doc = self._make_file_doc()
        sync_attachment_to_journal_entries(doc)

        self.assertEqual(mock_frappe.get_doc.call_count, 1)
        call_args = mock_frappe.get_doc.call_args_list[0][0][0]
        self.assertEqual(call_args["attached_to_name"], "JV-002")

    @patch("isnack.overrides.file_hooks.frappe")
    def test_folder_defaults_to_home_attachments_when_none(self, mock_frappe):
        """When doc.folder is falsy, the created File should use 'Home/Attachments'."""
        mock_frappe.db.get_value.return_value = 1
        mock_frappe.get_all.return_value = ["JV-001"]
        mock_frappe.db.exists.return_value = None

        new_file_doc = MagicMock()
        mock_frappe.get_doc.return_value = new_file_doc

        doc = self._make_file_doc()
        doc.folder = None  # simulate missing folder

        sync_attachment_to_journal_entries(doc)

        call_args = mock_frappe.get_doc.call_args_list[0][0][0]
        self.assertEqual(call_args["folder"], "Home/Attachments")


if __name__ == "__main__":
    unittest.main()
