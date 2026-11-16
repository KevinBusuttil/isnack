import frappe
from frappe.utils import cstr

from isnack.utils import earlier_layout


def execute():
    """QC Metal Detector Log: the Corrective Action comes off the log
    (2026-11).

    The logs holding one keep it in their Earlier Layout section: mark them,
    whatever their state (a log made since the Metal Detector change is not
    marked yet). The field and its values are left as they are; so is
    ``modified`` (and so the version history), a plain update. A log deleted
    before holding one is marked in its Deleted Document too, so a restore
    brings it back as it was.
    """
    if not frappe.db.has_column("QC Metal Detector Log", "earlier_layout"):
        return

    logs = frappe.get_all(
        "QC Metal Detector Log", filters={"corrective_action": ["is", "set"]}, fields=["name", "corrective_action"]
    )
    earlier_layout.mark_records(
        "QC Metal Detector Log", [log.name for log in logs if cstr(log.corrective_action).strip()]
    )
    earlier_layout.mark_deleted_documents(
        "QC Metal Detector Log", lambda data: bool(cstr(data.get("corrective_action")).strip())
    )
