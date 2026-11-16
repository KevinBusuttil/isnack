import json

import frappe
from frappe.utils import cstr

# What a Metal Detector takes from the logs that name it.
LOG_FIELDS = ("detector_make_model", "last_calibration_date", "next_calibration_date", "calibration_certificate")


def execute():
    """QC Metal Detector Log: the Metal Detector ID becomes a link to a Metal
    Detector, which holds the Make/Model and calibration the log takes from it
    (2026-11).

    Make a Metal Detector of each ID the logs name, so their links lead to one
    and a draft can still be saved: with the Make/Model, the calibration dates
    (the two together) and the certificate of the newest log holding each, a
    cancelled log only when no other holds it, a log deleted before (its
    Deleted Document, which a restore needs the detector for) only when no log
    there is does. An ID differing only in case or surrounding spaces is the
    same detector; it takes the newest log's spelling. The database matches a
    log's ID to it whatever its case or trailing spaces, but not a leading
    space, tab or line break: a log whose ID has one is given the detector's
    name (a plain update, leaving ``modified`` alone), and so is a log deleted
    before, in its Deleted Document, so a restore leads to it. The other logs
    are left as they are.

    An ID that cannot name a record is reported and left out: its logs keep
    it, and a draft of them is saved again with a detector picked (the log
    refuses a Metal Detector ID that names none).
    """
    if not frappe.db.table_exists("Metal Detector"):
        return

    logs = frappe.get_all(
        "QC Metal Detector Log",
        filters={"metal_detector_id": ["is", "set"]},
        fields=["name", "metal_detector_id", "docstatus", *LOG_FIELDS],
        order_by="record_date desc, modified desc",
    )
    deleted = _deleted_logs()
    detectors = {}
    # newest first, the cancelled after the rest (sorted keeps the date order),
    # then those deleted before
    for log in sorted(logs, key=lambda log: log.docstatus == 2) + [log for _name, log in deleted]:
        detector_id = cstr(log.metal_detector_id).strip()
        if not detector_id:
            continue
        detector = detectors.setdefault(detector_id.casefold(), {"metal_detector_id": detector_id})
        make_model = cstr(log.detector_make_model).strip()
        if make_model and "make_model" not in detector:
            detector["make_model"] = make_model
        if (log.last_calibration_date or log.next_calibration_date) and "last_calibration_date" not in detector:
            detector["last_calibration_date"] = log.last_calibration_date
            detector["next_calibration_date"] = log.next_calibration_date
        certificate = cstr(log.calibration_certificate).strip()
        if certificate and "calibration_certificate" not in detector:
            detector["calibration_certificate"] = certificate

    for detector in detectors.values():
        if frappe.db.exists("Metal Detector", detector["metal_detector_id"]):
            continue
        frappe.db.savepoint("metal_detector_from_logs")
        try:
            frappe.get_doc({"doctype": "Metal Detector", **detector}).insert(ignore_permissions=True)
        except (frappe.NameError, frappe.ValidationError) as e:
            frappe.db.rollback(save_point="metal_detector_from_logs")
            frappe.clear_last_message()
            print(f"Metal Detector {detector['metal_detector_id']!r} not made from the QC Metal Detector Logs: {e}")

    for log in logs:
        detector = _unmatched_detector(log.metal_detector_id)
        if detector:
            frappe.db.sql(
                "update `tabQC Metal Detector Log` set metal_detector_id = %s where name = %s", (detector, log.name)
            )
    for name, log in deleted:
        detector = _unmatched_detector(log.metal_detector_id)
        if detector:
            log.metal_detector_id = detector
            frappe.db.set_value("Deleted Document", name, "data", frappe.as_json(log), update_modified=False)


def _deleted_logs():
    """The logs deleted before and not restored: (their Deleted Document, its
    snapshot), newest first."""
    deleted = [
        (row.name, frappe._dict(json.loads(row.data)))
        for row in frappe.get_all(
            "Deleted Document",
            filters={"deleted_doctype": "QC Metal Detector Log", "restored": 0},
            fields=["name", "data"],
        )
    ]
    return sorted(deleted, key=lambda item: (cstr(item[1].record_date), cstr(item[1].modified)), reverse=True)


def _unmatched_detector(detector_id):
    """The detector a log's ID names when the database does not match the ID
    as it is (a leading space, a tab or a line break around it); else None."""
    raw = cstr(detector_id)
    if raw == raw.strip() or frappe.db.exists("Metal Detector", raw):
        return None
    return frappe.db.exists("Metal Detector", raw.strip())
