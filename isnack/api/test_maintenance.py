# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""Unit tests for the Maintenance Operations Hub.

These focus on the pure status/urgency logic and the idempotency of reminder
sending — none require a live ERPNext site, so they run fast in CI.
"""

import unittest
from unittest.mock import patch

from frappe.utils import add_days, nowdate

from isnack.utils.maintenance import (
    derive_operational_status,
    urgency_bucket,
    OP_PLANNED,
    OP_ASSIGNED,
    OP_OVERDUE,
    OP_IN_PROGRESS,
    OP_COMPLETED,
    OP_WAITING_PARTS,
    OP_VERIFIED,
)


class TestUrgencyBucket(unittest.TestCase):
    def test_overdue_by_date(self):
        log = {"custom_operational_status": OP_PLANNED,
               "due_date": add_days(nowdate(), -2)}
        self.assertEqual(urgency_bucket(log), "overdue")

    def test_due_today(self):
        log = {"custom_operational_status": OP_ASSIGNED, "due_date": nowdate()}
        self.assertEqual(urgency_bucket(log), "due_today")

    def test_next_7_days(self):
        log = {"custom_operational_status": OP_ASSIGNED,
               "due_date": add_days(nowdate(), 3)}
        self.assertEqual(urgency_bucket(log), "next_7_days")

    def test_later_is_not_a_bucket(self):
        log = {"custom_operational_status": OP_ASSIGNED,
               "due_date": add_days(nowdate(), 30)}
        self.assertEqual(urgency_bucket(log), "later")

    def test_in_progress_overrides_date(self):
        log = {"custom_operational_status": OP_IN_PROGRESS,
               "due_date": add_days(nowdate(), -5)}
        self.assertEqual(urgency_bucket(log), "in_progress")

    def test_waiting_for_parts(self):
        log = {"custom_operational_status": OP_WAITING_PARTS,
               "due_date": add_days(nowdate(), -5)}
        self.assertEqual(urgency_bucket(log), "waiting_for_parts")

    def test_completed_bucket(self):
        log = {"custom_operational_status": OP_COMPLETED, "due_date": nowdate()}
        self.assertEqual(urgency_bucket(log), "completed")


class TestDeriveStatus(unittest.TestCase):
    def test_cancelled_maps(self):
        log = {"maintenance_status": "Cancelled"}
        self.assertEqual(derive_operational_status(log), "Cancelled")

    def test_completed_maps(self):
        log = {"maintenance_status": "Completed"}
        self.assertEqual(derive_operational_status(log), OP_COMPLETED)

    def test_overdue_from_due_date(self):
        log = {"maintenance_status": "Planned", "due_date": add_days(nowdate(), -1)}
        self.assertEqual(derive_operational_status(log), OP_OVERDUE)

    def test_assigned_when_technician_set(self):
        log = {"maintenance_status": "Planned", "due_date": add_days(nowdate(), 5),
               "custom_assigned_technician": "tech@example.com"}
        self.assertEqual(derive_operational_status(log), OP_ASSIGNED)

    def test_planned_default(self):
        log = {"maintenance_status": "Planned", "due_date": add_days(nowdate(), 5)}
        self.assertEqual(derive_operational_status(log), OP_PLANNED)

    def test_advanced_status_not_clobbered(self):
        # An already-advanced operational status must win over derivation.
        log = {"custom_operational_status": OP_VERIFIED,
               "maintenance_status": "Completed"}
        self.assertEqual(derive_operational_status(log), OP_VERIFIED)


class TestReminderIdempotency(unittest.TestCase):
    """The scheduler must not re-send the same reminder twice in one day."""

    def test_already_sent_today_blocks_resend(self):
        import isnack.api.maintenance_tasks as mt

        class Rule:
            name = "7 days before due"

        log = {"custom_reminder_stage": "7 days before due",
               "custom_last_reminder_on": nowdate()}
        self.assertTrue(mt._already_sent_today(log, Rule()))

        log_other = {"custom_reminder_stage": "3 days before due",
                     "custom_last_reminder_on": nowdate()}
        self.assertFalse(mt._already_sent_today(log_other, Rule()))

        log_old = {"custom_reminder_stage": "7 days before due",
                   "custom_last_reminder_on": add_days(nowdate(), -1)}
        self.assertFalse(mt._already_sent_today(log_old, Rule()))


if __name__ == "__main__":
    unittest.main()
