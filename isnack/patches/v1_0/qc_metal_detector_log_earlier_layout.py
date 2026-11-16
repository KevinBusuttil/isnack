import frappe

from isnack.isnack.doctype.qc_metal_detector_log.qc_metal_detector_log import (
    RETIRED_FIELDS,
    RETIRED_TEST_FIELDS,
    belongs_to_earlier_layout,
)
from isnack.utils import earlier_layout


def execute():
    """QC Metal Detector Log: the Calibration Certificate (kept on the Metal
    Detector since) and each test's Sensitivity Setting and Remarks come off the
    log (2026-11).

    The logs made before that keep them (submitted or cancelled, or a draft
    holding any) keep them in Earlier Layout sections: mark them. A draft
    holding none is finished the new way. Fields and values are left as they
    are; so is ``modified`` (and so the version history), a plain update.

    A log deleted before is marked in its Deleted Document too, so a restore
    brings it back as it was. A user who chose to see the sensitivity setting
    or remarks in the Tests grid has the grid's columns forgotten, so a log
    made since does not offer them.
    """
    if not frappe.db.has_column("QC Metal Detector Log", "earlier_layout"):
        return

    tests = {}
    for test in frappe.get_all(
        "QC Metal Detector Test",
        filters={"parenttype": "QC Metal Detector Log"},
        fields=["parent", *RETIRED_TEST_FIELDS],
    ):
        tests.setdefault(test.parent, []).append(test)
    logs = frappe.get_all("QC Metal Detector Log", fields=["name", "docstatus", *RETIRED_FIELDS])
    earlier_layout.mark_records(
        "QC Metal Detector Log", [log.name for log in logs if belongs_to_earlier_layout(log, tests.get(log.name, ()))]
    )
    earlier_layout.mark_deleted_documents(
        "QC Metal Detector Log", lambda data: belongs_to_earlier_layout(data, data.get("tests") or ())
    )
    earlier_layout.forget_grid_columns("QC Metal Detector Log", "QC Metal Detector Test", RETIRED_TEST_FIELDS)
