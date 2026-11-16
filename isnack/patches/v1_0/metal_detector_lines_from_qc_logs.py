import json

import frappe
from frappe.utils import cstr


def execute():
    """Metal Detector: the factory lines it is used on (2026-11). A QC Metal
    Detector Log offers a detector on those lines only, and refuses one that
    is not used on its line.

    Give each Metal Detector that has no Factory Lines yet the lines of the
    logs that name it: submitted or draft, and deleted before (a restore needs
    it). So each log made before can still be saved and restored, and a new
    one on those lines offers its detector. A cancelled log gives none: one
    cancelled for its line or detector would put the detector on a line it was
    logged on by mistake, and an amendment keeping the detector and line it
    amends needs none (the log lets it).

    The database matches a log's ID and line to the detector and line whatever
    their case or trailing spaces; a detector takes the line's own spelling. A
    detector no log names is left without: it is offered on no line until one
    is added to it (it cannot be saved without one).

    The rows are inserted as they are, leaving the detector's ``modified`` (and
    so its version history) alone.
    """
    if not frappe.db.table_exists("Metal Detector Factory Line"):
        return

    named = {
        (cstr(log.metal_detector_id).strip(), cstr(log.factory_line).strip())
        for log in frappe.get_all(
            "QC Metal Detector Log",
            filters={"metal_detector_id": ["is", "set"], "factory_line": ["is", "set"], "docstatus": ["!=", 2]},
            fields=["metal_detector_id", "factory_line"],
            distinct=True,
        )
    }
    for deleted in frappe.get_all(
        "Deleted Document", filters={"deleted_doctype": "QC Metal Detector Log", "restored": 0}, fields=["data"]
    ):
        data = json.loads(deleted.data)
        named.add((cstr(data.get("metal_detector_id")).strip(), cstr(data.get("factory_line")).strip()))

    with_lines = set(
        frappe.get_all(
            "Metal Detector Factory Line",
            filters={"parenttype": "Metal Detector", "parentfield": "factory_lines"},
            pluck="parent",
            distinct=True,
        )
    )
    detector_named, line_named = {}, {}
    lines = {}
    for detector_id, line_id in named:
        if not (detector_id and line_id):
            continue
        if detector_id not in detector_named:
            detector_named[detector_id] = frappe.db.exists("Metal Detector", detector_id)
        if line_id not in line_named:
            line_named[line_id] = frappe.db.exists("Factory Line", line_id)
        detector, line = detector_named[detector_id], line_named[line_id]
        if detector and line and detector not in with_lines:
            lines.setdefault(detector, set()).add(line)

    for detector in sorted(lines):
        for idx, line in enumerate(sorted(lines[detector]), 1):
            frappe.get_doc(
                {
                    "doctype": "Metal Detector Factory Line",
                    "parent": detector,
                    "parenttype": "Metal Detector",
                    "parentfield": "factory_lines",
                    "idx": idx,
                    "factory_line": line,
                }
            ).db_insert()
