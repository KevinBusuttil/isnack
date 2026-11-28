# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""A deadlock is the transaction failing, not the write that met it.

Some writes in mes_ops are best effort: the notes on a short material, a Work
Order's remarks, a Job Card's status. Each is wrapped so that its failing never
stops the close, start or status change it belongs to, and that still holds.

A deadlock is not that kind of failure. MariaDB rolls back the whole
transaction, everything the request has written so far, and frappe.db.sql
raises frappe.QueryDeadlockError. The next statement starts a fresh transaction
and the request commits that. So a bare ``except Exception: pass`` around the
remarks let complete_work_order go on to commit its Work Order as Completed
while the Manufacture entry it had just submitted was gone.

Each of these sites now lets frappe.QueryDeadlockError through, and
frappe.QueryTimeoutError with it: a lock wait timeout undoes only its own
statement unless the server sets innodb_rollback_on_timeout, which the request
cannot see. Every other failure is swallowed exactly as before. These tests pin
both halves, site by site.
"""

import unittest
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import frappe
import pymysql

import isnack.api.mes_ops as mes_ops

WO = "MFG-WO-2026-00041"
JOB_CARD = "PO-JOB00017"
EMPLOYEE = "HR-EMP-00003"
TIME_LOG = "jctl-0001"
WIP = "EXT1-WIP - ISN"
STAGING = "EXT1-Staging - ISN"


def setUpModule():
    # Read before any patch is active. Frappe answers these from System
    # Settings, which it loads through frappe.get_doc the first time, and the
    # tests below put a stub in frappe.get_doc's place.
    frappe.get_system_settings("time_zone")
    frappe.utils.now_datetime()
    frappe._("Production control update: {0}")


def transaction_failures():
    """What frappe.db.sql raises when MariaDB gives up on a statement (see
    frappe.database.database.Database.sql)."""
    return (
        frappe.QueryDeadlockError(
            "(1213, 'Deadlock found when trying to get lock; try restarting transaction')"),
        frappe.QueryTimeoutError(
            "(1205, 'Lock wait timeout exceeded; try restarting transaction')"),
    )


def unknown_column(field):
    """A database error that is not the transaction failing: what db_set on a
    field the site has not migrated raises, which these writes are guarded
    against."""
    return pymysql.err.OperationalError(1054, f"Unknown column '{field}' in 'field list'")


def run(fn, *args, **kwargs):
    """(what ``fn`` returned or None, the exception it raised or None)."""
    try:
        return fn(*args, **kwargs), None
    except Exception as e:
        return None, e


class WorkOrderStub:
    """The parts of a Work Order complete_work_order and set_wo_status use.

    ``fail`` maps a field to what db_set raises for it."""

    def __init__(self, fail=None):
        self.name = WO
        self.qty = 500.0
        self.company = "Isnack"
        self.production_item = "FG10019"
        self.bom_no = None        # no BOM rows: what is under test comes after them
        self.fg_warehouse = "Finished Goods - ISN"
        self.wip_warehouse = WIP
        self.custom_rejects_qty = 3.0
        self.flags = MagicMock()
        self.fail = fail or {}
        self.written = {}
        self.comments = []
        self.saved = False

    def get(self, field, default=None):
        return getattr(self, field, default)

    def db_set(self, field, value, commit=False):
        if field in self.fail:
            raise self.fail[field]
        self.written[field] = value

    def reload(self):
        pass

    def add_comment(self, _kind, text):
        self.comments.append(text)

    def save(self):
        self.saved = True


class FakeStockEntry:
    def __init__(self):
        self.items = []
        self.flags = MagicMock()
        self.inserted = self.submitted = False

    def append(self, _table, row):
        self.items.append(row)

    def insert(self):
        self.inserted = True

    def submit(self):
        self.submitted = True


class TestTheShortfallNotes(unittest.TestCase):
    """_record_material_shortfall writes an Error Log and a comment in the middle
    of a close: after the surplus sweep and every order closed before this one."""

    ROW = {
        "item_code": "RM10007", "uom": "Kg", "required_qty": 12.0,
        "already_consumed": 0.0, "source_warehouse": WIP,
        "post_qty": 10.0, "short_qty": 2.0,
    }

    def record(self, log_failure=None, comment_failure=None):
        wo = MagicMock()
        wo.name, wo.qty = WO, 500.0
        wo.add_comment = MagicMock(side_effect=comment_failure)
        with patch.object(mes_ops.frappe, "log_error", side_effect=log_failure) as log:
            _result, raised = run(mes_ops._record_material_shortfall, wo, dict(self.ROW), 500.0)
        return raised, log, wo.add_comment

    def test_a_deadlock_writing_the_error_log_is_not_swallowed(self):
        for failure in transaction_failures():
            with self.subTest(type(failure).__name__):
                raised, _log, add_comment = self.record(log_failure=failure)

                self.assertIs(raised, failure)
                add_comment.assert_not_called()

    def test_a_deadlock_writing_the_comment_is_not_swallowed(self):
        for failure in transaction_failures():
            with self.subTest(type(failure).__name__):
                raised, log, add_comment = self.record(comment_failure=failure)

                self.assertIs(raised, failure)
                log.assert_called_once()
                add_comment.assert_called_once()

    def test_notes_that_cannot_be_written_still_do_not_stop_the_close(self):
        raised, log, add_comment = self.record(
            log_failure=RuntimeError("Error Log could not be written"),
            comment_failure=frappe.ValidationError("Comment could not be written"),
        )

        self.assertIsNone(raised)
        log.assert_called_once()
        add_comment.assert_called_once()


def leave(status_failure):
    """leave_job_card for an operator whose time log is the last one open.

    Returns (result, the time log, the status write, the exception raised)."""
    tl = MagicMock()
    with patch.object(mes_ops, "_require_roles"), \
            patch.object(mes_ops, "_employee_or_user_default", return_value=EMPLOYEE), \
            patch.object(mes_ops.frappe.db, "get_value", return_value=TIME_LOG), \
            patch.object(mes_ops.frappe, "get_doc", return_value=tl), \
            patch.object(mes_ops, "_open_time_logs", return_value=[]), \
            patch.object(mes_ops.frappe.db, "set_value", side_effect=status_failure) as set_value:
        result, raised = run(mes_ops.leave_job_card, JOB_CARD)
    return result, tl, set_value, raised


class TestLeavingAJobCard(unittest.TestCase):
    """leave_job_card closes the operator's time log, then puts the card On Hold."""

    def test_a_deadlock_putting_the_card_on_hold_is_not_swallowed(self):
        """The time log closed before it went with the transaction, so True
        would tell the operator they left a job they are still on."""
        for failure in transaction_failures():
            with self.subTest(type(failure).__name__):
                result, tl, set_value, raised = leave(failure)

                tl.save.assert_called_once()
                set_value.assert_called_once()
                self.assertIs(raised, failure)
                self.assertIsNone(result)

    def test_a_status_that_cannot_be_written_still_lets_the_operator_leave(self):
        result, tl, _set_value, raised = leave(frappe.ValidationError("Job Card is cancelled"))

        self.assertIsNone(raised)
        self.assertIs(result, True)
        tl.save.assert_called_once()


class JobCardStub:
    def __init__(self, fail=None):
        self.name = JOB_CARD
        self.status = "Work In Progress"
        self.flags = MagicMock()
        self.fail = fail or {}
        self.written = {}
        self.saved = False

    def append(self, _table, _row):
        raise AssertionError("a Pause adds no time log")

    def db_set(self, field, value, commit=False):
        if field in self.fail:
            raise self.fail[field]
        self.written[field] = value

    def save(self):
        self.saved = True


def pause(jc):
    """set_card_status(Pause) with a reason and remarks, for one operator.

    Returns (result, the time log write, the exception raised)."""
    with patch.object(mes_ops, "_require_roles"), \
            patch.object(mes_ops.frappe, "get_doc", return_value=jc), \
            patch.object(mes_ops, "_employee_or_user_default", return_value=EMPLOYEE), \
            patch.object(mes_ops.frappe.db, "get_value", return_value=TIME_LOG), \
            patch.object(mes_ops.frappe.db, "set_value") as set_value:
        result, raised = run(mes_ops.set_card_status, JOB_CARD, "Pause",
                             reason="No film", remarks="Reel jammed at the sealer")
    return result, set_value, raised


class TestPausingAJobCard(unittest.TestCase):
    """set_card_status closes the operator's time log, writes the remarks and the
    reason, then saves the card On Hold."""

    def test_a_deadlock_writing_the_remarks_is_not_swallowed(self):
        """The time log closed above went with the transaction; saving would put
        the card On Hold without it."""
        for failure in transaction_failures():
            with self.subTest(type(failure).__name__):
                jc = JobCardStub(fail={"mes_remarks": failure})
                _result, set_value, raised = pause(jc)

                set_value.assert_called_once()
                self.assertIs(raised, failure)
                self.assertEqual((jc.written, jc.saved), ({}, False))

    def test_a_deadlock_writing_the_reason_is_not_swallowed(self):
        for failure in transaction_failures():
            with self.subTest(type(failure).__name__):
                jc = JobCardStub(fail={"mes_reason": failure})
                _result, _set_value, raised = pause(jc)

                self.assertIs(raised, failure)
                self.assertEqual(jc.written, {"mes_remarks": "Reel jammed at the sealer"})
                self.assertFalse(jc.saved)

    def test_fields_the_card_does_not_have_still_do_not_stop_the_pause(self):
        jc = JobCardStub(fail={
            "mes_remarks": unknown_column("mes_remarks"),
            "mes_reason": unknown_column("mes_reason"),
        })
        result, _set_value, raised = pause(jc)

        self.assertIsNone(raised)
        self.assertIs(result, True)
        self.assertEqual((jc.status, jc.saved), ("On Hold", True))


class TestSweepingSurplus(unittest.TestCase):
    """_sweep_surplus_to_wip runs inside a start or a close, after the request
    has written what came before it. Each surplus has its own savepoint, so an
    ordinary failure takes back only that surplus."""

    SURPLUS = ["MAT-STE-2026-00112", "MAT-STE-2026-00113"]

    def sweep(self, failure):
        wo = MagicMock()
        wo.company = "Isnack"
        with patch.object(mes_ops, "_find_eligible_surplus_ses", return_value=list(self.SURPLUS)), \
                patch.object(mes_ops, "_claim_surplus_for_sweep", return_value=True), \
                patch.object(mes_ops, "_create_surplus_wip_transfer", side_effect=failure) as create, \
                patch.object(mes_ops.frappe.db, "savepoint"), \
                patch.object(mes_ops.frappe.db, "rollback") as rollback, \
                patch.object(mes_ops.frappe.db, "release_savepoint"), \
                patch.object(mes_ops.frappe, "log_error") as log:
            created, raised = run(mes_ops._sweep_surplus_to_wip, WO, STAGING, WIP, wo)
        return created, raised, create, rollback, log

    def test_a_deadlock_moving_the_surplus_is_not_swallowed(self):
        """The savepoint went with the rest of the transaction: rolling back to
        it would only fail on a savepoint that no longer exists, and sweeping on
        would commit the start or close without what it wrote first."""
        for failure in transaction_failures():
            with self.subTest(type(failure).__name__):
                _created, raised, create, rollback, log = self.sweep(failure)

                self.assertIs(raised, failure)
                create.assert_called_once()     # the next surplus is not attempted
                rollback.assert_not_called()
                log.assert_not_called()

    def test_a_surplus_that_cannot_be_moved_still_does_not_stop_the_sweep(self):
        """As before (see also test_mes_ops_surplus): its savepoint is rolled
        back, the failure logged, and the next surplus tried."""
        created, raised, create, rollback, log = self.sweep(
            frappe.ValidationError("Batch No EXT1-0712 has negative stock"))

        self.assertIsNone(raised)
        self.assertEqual(created, [])
        self.assertEqual((create.call_count, rollback.call_count, log.call_count), (2, 2, 2))


class TestProductionControlUpdate(unittest.TestCase):
    """set_wo_status writes up to three fields, then comments and saves."""

    def update(self, wo):
        with patch.object(mes_ops, "_require_roles"), \
                patch.object(mes_ops.frappe, "get_doc", return_value=wo):
            return run(mes_ops.set_wo_status, WO, "Paused",
                       reason="No film", remarks="Reel jammed at the sealer")

    def test_a_deadlock_writing_a_field_is_not_swallowed(self):
        """The field written before it went with the transaction."""
        for failure in transaction_failures():
            with self.subTest(type(failure).__name__):
                wo = WorkOrderStub(fail={"mes_reason": failure})
                _result, raised = self.update(wo)

                self.assertIs(raised, failure)
                self.assertEqual(wo.written, {"mes_status": "Paused"})
                self.assertEqual((wo.comments, wo.saved), ([], False))

    def test_a_field_the_order_does_not_have_is_still_skipped(self):
        wo = WorkOrderStub(fail={"mes_reason": unknown_column("mes_reason")})
        result, raised = self.update(wo)

        self.assertIsNone(raised)
        self.assertIs(result, True)
        self.assertEqual(wo.written, {"mes_status": "Paused", "mes_remarks": "Reel jammed at the sealer"})
        self.assertEqual(len(wo.comments), 1)
        self.assertTrue(wo.saved)


def complete(wo, status_failure=None):
    """complete_work_order(500 good, 5 rejects, remarks) on ``wo``.

    Returns (the Stock Entry it submitted, the Completed status write, the
    exception raised or None)."""
    se = FakeStockEntry()
    with ExitStack() as stack:
        stack.enter_context(patch.object(mes_ops, "_require_roles"))
        stack.enter_context(patch.object(mes_ops.frappe, "get_doc", return_value=wo))
        stack.enter_context(patch.object(mes_ops.frappe, "new_doc", return_value=se))
        stack.enter_context(patch.object(mes_ops.frappe.db, "get_value", return_value="Carton"))
        stack.enter_context(patch.object(mes_ops, "_get_consumed_materials_from_load", return_value={}))
        stack.enter_context(patch.object(mes_ops, "_default_line_scrap", return_value="EXT1-Scrap - ISN"))
        stack.enter_context(patch.object(mes_ops, "_apply_pre_consumed_cost_to_finished_item"))
        set_value = stack.enter_context(
            patch.object(mes_ops.frappe.db, "set_value", side_effect=status_failure))
        _result, raised = run(mes_ops.complete_work_order, WO, 500, rejects=5,
                              remarks="Film changed twice")
    return se, set_value, raised


class TestCompletingAfterTheManufactureEntry(unittest.TestCase):
    """complete_work_order writes the remarks, the rejects and the Completed
    status after it has submitted the Manufacture entry in the same request."""

    def test_a_deadlock_writing_the_remarks_is_not_swallowed(self):
        """The Manufacture entry went with the transaction; carrying on would
        commit the order as Completed without it."""
        for failure in transaction_failures():
            with self.subTest(type(failure).__name__):
                wo = WorkOrderStub(fail={"remarks": failure})
                se, set_value, raised = complete(wo)

                self.assertTrue(se.submitted)
                self.assertIs(raised, failure)
                self.assertEqual(wo.written, {})
                set_value.assert_not_called()
                self.assertEqual((wo.comments, wo.saved), ([], False))

    def test_a_deadlock_writing_the_rejects_is_not_swallowed(self):
        for failure in transaction_failures():
            with self.subTest(type(failure).__name__):
                wo = WorkOrderStub(fail={"custom_rejects_qty": failure})
                se, set_value, raised = complete(wo)

                self.assertTrue(se.submitted)
                self.assertIs(raised, failure)
                self.assertEqual(wo.written, {"remarks": "Film changed twice"})
                set_value.assert_not_called()
                self.assertFalse(wo.saved)

    def test_a_deadlock_marking_the_order_completed_is_not_swallowed(self):
        for failure in transaction_failures():
            with self.subTest(type(failure).__name__):
                wo = WorkOrderStub()
                se, set_value, raised = complete(wo, status_failure=failure)

                self.assertTrue(se.submitted)
                self.assertIs(raised, failure)
                set_value.assert_called_once()
                self.assertEqual((wo.comments, wo.saved), ([], False))

    def test_writes_that_fail_for_any_other_reason_still_do_not_stop_it(self):
        """An order without the remarks field, or a status write that is
        refused, is completed as it always was."""
        wo = WorkOrderStub(fail={"remarks": unknown_column("remarks")})
        se, set_value, raised = complete(
            wo, status_failure=frappe.ValidationError("Work Order is already Completed"))

        self.assertIsNone(raised)
        self.assertTrue(se.submitted)
        self.assertEqual(wo.written, {"custom_rejects_qty": 8.0})
        set_value.assert_called_once()
        self.assertEqual(len(wo.comments), 1)
        self.assertTrue(wo.saved)


if __name__ == "__main__":
    unittest.main()
