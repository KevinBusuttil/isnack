# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# License: MIT

import frappe


def sync_attachment_to_journal_entries(doc, method=None):
    """
    After a File is inserted, if it is attached to a submitted Service Invoice,
    copy the attachment to all linked Journal Entries (one per Service Invoice Items row).

    This handles the case where attachments are added to a Service Invoice after
    submission — the on_submit hook only copies attachments that exist at submit time.

    Re-entrancy is safe: when this hook creates a File attached to a Journal Entry,
    the hook fires again but exits immediately because attached_to_doctype is not
    "Service Invoice".
    """
    if doc.attached_to_doctype != "Service Invoice":
        return

    docstatus = frappe.db.get_value("Service Invoice", doc.attached_to_name, "docstatus")
    if docstatus != 1:
        return

    journal_entries = frappe.get_all(
        "Service Invoice Items",
        filters={"parent": doc.attached_to_name},
        pluck="journal_entry",
    )

    for je_name in journal_entries:
        if not je_name:
            continue

        already_attached = frappe.db.exists(
            "File",
            {
                "attached_to_doctype": "Journal Entry",
                "attached_to_name": je_name,
                "file_url": doc.file_url,
            },
        )
        if already_attached:
            continue

        _file = frappe.get_doc(
            {
                "doctype": "File",
                "file_url": doc.file_url,
                "file_name": doc.file_name,
                "attached_to_name": je_name,
                "attached_to_doctype": "Journal Entry",
                "folder": doc.folder or "Home/Attachments",
                "is_private": doc.is_private,
            }
        )
        _file.save(ignore_permissions=True)
