# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

"""Tests for the Storekeeper Hub Delivery Note batch-scan backend.

The rules that matter are the ones that decide where a scanned carton's quantity
lands and whether the Delivery Note can still be saved afterwards:

* a label is matched to the Delivery Note's own lines and spills from one line to
  the next of the same item — it never creates a line;
* two batches on one line accumulate into one allocation, which is the whole reason
  the allocation is written as a Serial and Batch Bundle rather than ``batch_no``;
* a line is linked to its bundle only once it is fully allocated, because a short
  bundle on ``Delivery Note Item.serial_and_batch_bundle`` fails
  ``SerialandBatchBundle.validate_quantity`` on the next save of the draft;
* a fully scanned Delivery Note cannot be reopened, and a submitted one was never
  open.

Payload parsing itself is covered by ``test_delivery_note_scan.py``; these tests
stub ``parse_gs1_or_basic`` so a scan reads as the literal label string.
"""

import unittest
from unittest.mock import patch

import frappe

from isnack.api import delivery_note_batch_scan as dnbs


class _FakeRow:
    """Minimal stand-in for a Delivery Note Item child document."""

    def __init__(self, **values):
        values.setdefault("item_name", values.get("item_code", ""))
        values.setdefault("uom", "Carton")
        values.setdefault("stock_uom", "Carton")
        values.setdefault("conversion_factor", 1.0)
        values.setdefault("stock_qty", values.get("qty", 0))
        values.setdefault("warehouse", "Finished Goods - ISN")
        values.setdefault("batch_no", None)
        values.setdefault("serial_and_batch_bundle", None)
        self.__dict__.update(values)

    def get(self, key, default=None):
        return self.__dict__.get(key, default)


class _FakeDoc:
    """Minimal stand-in for a draft Delivery Note."""

    def __init__(self, items, name="MAT-DN-2026-00011", **values):
        self._items = items
        self.name = name
        self.docstatus = 0
        self.company = "Isnack"
        self.customer = "Nectar Ltd"
        self.customer_name = "Nectar Ltd"
        self.posting_date = "2026-09-22"
        self.posting_time = "09:00:00"
        self.set_warehouse = "Finished Goods - ISN"
        self.__dict__.update(values)

    @property
    def items(self):
        return self._items

    def get(self, key, default=None):
        if key == "items":
            return self._items
        return self.__dict__.get(key, default)

    def reload(self):
        return self


POSTING = {
    "bundle_fields": {"posting_datetime": "2026-09-22 09:00:00"},
    "qty_kwargs": {"posting_datetime": "2026-09-22 09:00:00"},
    "key": "2026-09-22 09:00:00",
    "posting_date": "2026-09-22",
}

BATCH_ITEM = {"BBB-112": "FG10011", "BBB-113": "FG10011", "BBB-114": "FG10011"}


def _fake_parse(code):
    """Stand-in for isnack.utils.scan.parse_gs1_or_basic over the pipe payload."""
    parts = (code or "").split("|")
    out = {}
    if parts:
        out["item_code"] = parts[0]
    if len(parts) > 1:
        out["batch_no"] = parts[1]
    if len(parts) > 2:
        try:
            out["qty"] = float(parts[2])
        except ValueError:
            pass
    return out


def _fg_items(*codes):
    return {code: {"has_batch_no": 1, "has_serial_no": 0, "stock_uom": "Carton"} for code in codes}


def _scan(doc, code, allocations=None, allow_partial=0, stock=None, items=None,
          batch_item=None, expiry=None):
    """Drive scan_label with the document layer stubbed out.

    ``stock`` maps batch_no -> qty available in every warehouse, which is the only
    shape these scenarios need.
    """
    stock = {"BBB-112": 100.0, "BBB-113": 150.0, "BBB-114": 150.0} if stock is None else stock
    batch_item = BATCH_ITEM if batch_item is None else batch_item
    items = items or _fg_items(*{row.item_code for row in doc.get("items")})

    def _db_get_value(doctype, name, field, *args, **kwargs):
        if doctype == "Batch" and field == "item":
            return batch_item.get(name)
        return None

    with patch.object(dnbs, "_load_delivery_note", return_value=doc), patch.object(
        dnbs, "_posting_context", return_value=POSTING
    ), patch.object(dnbs, "_item_cache", return_value=items), patch.object(
        dnbs, "parse_gs1_or_basic", side_effect=_fake_parse
    ), patch.object(
        dnbs, "_available_qty", side_effect=lambda i, b, w, p: float(stock.get(b, 0.0))
    ), patch.object(
        dnbs, "_batch_expiry", return_value=expiry
    ), patch.object(
        dnbs, "_linked_bundle_batches", return_value={}
    ), patch.object(
        dnbs, "_scan_status", return_value=dnbs.STATUS_NOT_SCANNED
    ), patch(
        "frappe.db.exists", return_value=True
    ), patch(
        "frappe.db.get_value", side_effect=_db_get_value
    ), patch(
        "frappe.get_cached_value",
        return_value={"has_batch_no": 1, "has_serial_no": 0, "stock_uom": "Carton"},
    ):
        return dnbs.scan_label(
            doc.name,
            code,
            allocations=allocations or {},
            allow_partial=allow_partial,
        )


def _alloc(payload, row_name):
    """The {batch_no: qty} map a scan result carries for one row."""
    return {e["batch_no"]: e["qty"] for e in (payload["allocations"].get(row_name) or [])}


class TestRequiredQty(unittest.TestCase):
    """Allocation targets are in stock UOM, because that is what a bundle is
    measured in and what the label QR carries."""

    def test_stock_qty_wins_when_set(self):
        row = _FakeRow(name="r1", idx=1, item_code="FG10011", qty=10, conversion_factor=12,
                       stock_qty=120)
        self.assertEqual(dnbs._required_qty(row), 120.0)

    def test_falls_back_to_qty_times_conversion_factor(self):
        row = _FakeRow(name="r1", idx=1, item_code="FG10011", qty=10, conversion_factor=12,
                       stock_qty=0)
        self.assertEqual(dnbs._required_qty(row), 120.0)

    def test_missing_conversion_factor_is_one(self):
        row = _FakeRow(name="r1", idx=1, item_code="FG10011", qty=7, conversion_factor=0,
                       stock_qty=0)
        self.assertEqual(dnbs._required_qty(row), 7.0)


class TestRowIsScannable(unittest.TestCase):
    """Only batch-tracked, non-serialised lines take part."""

    def test_batch_tracked_item_is_scannable(self):
        self.assertTrue(dnbs._row_is_scannable({"has_batch_no": 1, "has_serial_no": 0}))

    def test_serialised_item_is_not(self):
        self.assertFalse(dnbs._row_is_scannable({"has_batch_no": 1, "has_serial_no": 1}))

    def test_untracked_item_is_not(self):
        # "Delivery Charges" and friends must not hold a Delivery Note back from
        # ever reaching Fully Scanned.
        self.assertFalse(dnbs._row_is_scannable({"has_batch_no": 0, "has_serial_no": 0}))


class TestNormaliseAllocations(unittest.TestCase):
    """The client's map is a proposal; the server decides what is in it."""

    def setUp(self):
        self.doc = _FakeDoc([_FakeRow(name="r1", idx=1, item_code="FG10011", qty=300)])
        self.items = _fg_items("FG10011")

    def _run(self, raw):
        with patch.object(dnbs, "_item_cache", return_value=self.items):
            return dnbs._normalise_allocations(raw, self.doc)

    def test_json_string_is_parsed(self):
        self.assertEqual(
            self._run('{"r1": [{"batch_no": "BBB-113", "qty": 20}]}'),
            {"r1": {"BBB-113": 20.0}},
        )

    def test_unknown_row_is_dropped(self):
        self.assertEqual(self._run({"nope": [{"batch_no": "BBB-113", "qty": 20}]}), {})

    def test_blank_batch_and_non_positive_qty_are_dropped(self):
        self.assertEqual(
            self._run({"r1": [{"batch_no": "", "qty": 5}, {"batch_no": "BBB-113", "qty": 0}]}),
            {},
        )

    def test_repeated_batch_is_merged(self):
        # A bundle may carry a batch only once — validate_duplicate_serial_and_batch_no.
        self.assertEqual(
            self._run({"r1": [{"batch_no": "BBB-113", "qty": 20},
                              {"batch_no": "BBB-113", "qty": 5}]}),
            {"r1": {"BBB-113": 25.0}},
        )

    def test_garbage_payload_is_empty(self):
        self.assertEqual(self._run("[1, 2, 3]"), {})
        self.assertEqual(self._run(None), {})


class TestDeriveStatus(unittest.TestCase):
    def _rows(self, *specs):
        return [
            {"scannable": s, "fully_allocated": f, "allocated_qty": a}
            for s, f, a in specs
        ]

    def test_nothing_scanned(self):
        self.assertEqual(dnbs._derive_status(self._rows((1, 0, 0))), dnbs.STATUS_NOT_SCANNED)

    def test_some_scanned(self):
        self.assertEqual(dnbs._derive_status(self._rows((1, 1, 10), (1, 0, 0))),
                         dnbs.STATUS_PARTIAL)

    def test_all_scanned(self):
        self.assertEqual(dnbs._derive_status(self._rows((1, 1, 10), (1, 1, 5))),
                         dnbs.STATUS_FULL)

    def test_unscannable_rows_are_ignored(self):
        # A Delivery Note whose only outstanding line is a delivery charge is done.
        self.assertEqual(dnbs._derive_status(self._rows((1, 1, 10), (0, 0, 0))),
                         dnbs.STATUS_FULL)

    def test_no_scannable_rows_at_all(self):
        self.assertEqual(dnbs._derive_status(self._rows((0, 0, 0))), dnbs.STATUS_NOT_SCANNED)


class TestScanLabel(unittest.TestCase):
    """One label, applied to the lines the Delivery Note already has."""

    def setUp(self):
        self.doc = _FakeDoc([_FakeRow(name="r1", idx=1, item_code="FG10011", qty=300)])

    def test_single_label_allocates_its_batch(self):
        out = _scan(self.doc, "FG10011|BBB-114|150")
        self.assertEqual(_alloc(out, "r1"), {"BBB-114": 150.0})
        self.assertEqual(out["scan"]["applied_qty"], 150.0)
        self.assertEqual(out["rows"][0]["allocated_qty"], 150.0)
        self.assertEqual(out["rows"][0]["remaining_qty"], 150.0)
        self.assertEqual(out["pending_status"], dnbs.STATUS_PARTIAL)

    def test_second_batch_accumulates_on_the_same_line(self):
        # The headline case: one batch does not hold enough, so the line ends up
        # carrying two — which is only expressible as a Serial and Batch Bundle.
        first = _scan(self.doc, "FG10011|BBB-114|150")
        second = _scan(self.doc, "FG10011|BBB-113|150", allocations=first["allocations"])
        self.assertEqual(_alloc(second, "r1"), {"BBB-113": 150.0, "BBB-114": 150.0})
        self.assertEqual(second["rows"][0]["allocated_qty"], 300.0)
        self.assertEqual(second["rows"][0]["fully_allocated"], 1)
        self.assertEqual(second["pending_status"], dnbs.STATUS_FULL)

    def test_repeated_scans_of_one_batch_merge_into_one_entry(self):
        first = _scan(self.doc, "FG10011|BBB-113|75")
        second = _scan(self.doc, "FG10011|BBB-113|75", allocations=first["allocations"])
        self.assertEqual(_alloc(second, "r1"), {"BBB-113": 150.0})

    def test_label_spills_onto_the_next_line_of_the_same_item(self):
        doc = _FakeDoc([
            _FakeRow(name="r1", idx=1, item_code="FG10011", qty=100),
            _FakeRow(name="r2", idx=2, item_code="FG10011", qty=100),
        ])
        out = _scan(doc, "FG10011|BBB-113|150")
        self.assertEqual(_alloc(out, "r1"), {"BBB-113": 100.0})
        self.assertEqual(_alloc(out, "r2"), {"BBB-113": 50.0})
        self.assertEqual([r["qty"] for r in out["scan"]["rows"]], [100.0, 50.0])

    def test_over_scan_asks_before_clamping(self):
        doc = _FakeDoc([_FakeRow(name="r1", idx=1, item_code="FG10011", qty=100)])
        asked = _scan(doc, "FG10011|BBB-113|150")
        self.assertEqual(asked["over_scan"], 1)
        self.assertEqual(asked["remaining_qty"], 100.0)
        self.assertEqual(asked["allocations"], {})

        allowed = _scan(doc, "FG10011|BBB-113|150", allow_partial=1)
        self.assertEqual(_alloc(allowed, "r1"), {"BBB-113": 100.0})
        self.assertEqual(allowed["scan"]["ignored_qty"], 50.0)

    def test_batchless_label_is_refused_with_a_reprint_message(self):
        with self.assertRaisesRegex(frappe.ValidationError, "carries no batch"):
            _scan(self.doc, "FG10011||150")

    def test_label_without_quantity_is_refused(self):
        with self.assertRaisesRegex(frappe.ValidationError, "no quantity"):
            _scan(self.doc, "FG10011|BBB-113")

    def test_batch_of_another_item_is_refused(self):
        with self.assertRaisesRegex(frappe.ValidationError, "inconsistent"):
            _scan(self.doc, "FG10011|BBB-113|150", batch_item={"BBB-113": "FG10012"})

    def test_unknown_batch_is_refused(self):
        with self.assertRaisesRegex(frappe.ValidationError, "does not exist"):
            _scan(self.doc, "FG10011|NOPE-999|150", batch_item={})

    def test_item_not_on_the_delivery_note_is_refused(self):
        with self.assertRaisesRegex(frappe.ValidationError, "not on Delivery Note"):
            _scan(self.doc, "FG10099|BBB-113|150", batch_item={"BBB-113": "FG10099"})

    def test_expired_batch_is_refused(self):
        with self.assertRaisesRegex(frappe.ValidationError, "expired"):
            _scan(self.doc, "FG10011|BBB-113|150", expiry="2026-09-01")

    def test_batch_with_no_stock_in_the_warehouse_is_refused(self):
        with self.assertRaisesRegex(frappe.ValidationError, "no stock in"):
            _scan(self.doc, "FG10011|BBB-113|150", stock={"BBB-113": 0.0})

    def test_batch_cannot_be_allocated_beyond_its_stock(self):
        # 100 on hand, 80 already claimed by this Delivery Note: the next carton
        # has to come from another batch.
        first = _scan(self.doc, "FG10011|BBB-112|80", stock={"BBB-112": 100.0})
        with self.assertRaisesRegex(frappe.ValidationError, "only .* left"):
            _scan(self.doc, "FG10011|BBB-112|40", allocations=first["allocations"],
                  stock={"BBB-112": 100.0})

    def test_fully_allocated_item_refuses_further_scans(self):
        first = _scan(self.doc, "FG10011|BBB-113|150")
        second = _scan(self.doc, "FG10011|BBB-114|150", allocations=first["allocations"])
        with self.assertRaisesRegex(frappe.ValidationError, "already fully allocated"):
            _scan(self.doc, "FG10011|BBB-112|10", allocations=second["allocations"])

    def test_empty_scan_is_refused(self):
        with self.assertRaisesRegex(frappe.ValidationError, "Nothing was scanned"):
            _scan(self.doc, "   ")

    def test_untracked_line_is_listed_but_never_allocated(self):
        doc = _FakeDoc([
            _FakeRow(name="r1", idx=1, item_code="FG10011", qty=150),
            _FakeRow(name="r2", idx=2, item_code="Delivery Charges", qty=1, uom="Unit"),
        ])
        items = _fg_items("FG10011")
        items["Delivery Charges"] = {"has_batch_no": 0, "has_serial_no": 0, "stock_uom": "Unit"}
        out = _scan(doc, "FG10011|BBB-113|150", items=items)
        self.assertEqual(out["rows"][1]["scannable"], 0)
        self.assertNotIn("r2", out["allocations"])
        # The charge line does not stop the Delivery Note being finished.
        self.assertEqual(out["pending_status"], dnbs.STATUS_FULL)


class TestPostDeliveryNoteScan(unittest.TestCase):
    """Post records the allocation without submitting the Delivery Note."""

    def setUp(self):
        self.rows = [
            _FakeRow(name="r1", idx=1, item_code="FG10011", qty=150),
            _FakeRow(name="r2", idx=2, item_code="FG10002", qty=100),
        ]
        self.doc = _FakeDoc(self.rows)
        self.items = _fg_items("FG10011", "FG10002")

    def _post(self, allocations, previous=None, stock=None):
        stock = stock or {"BBB-113": 150.0, "AAA-007": 100.0}

        def _db_get_value(doctype, name, field, *args, **kwargs):
            if doctype == "Batch" and field == "item":
                return {"BBB-113": "FG10011", "AAA-007": "FG10002"}.get(name)
            return None

        with patch.object(dnbs, "_load_delivery_note", return_value=self.doc), patch.object(
            dnbs, "_posting_context", return_value=POSTING
        ), patch.object(dnbs, "_item_cache", return_value=self.items), patch.object(
            dnbs, "_stored_allocations", return_value=previous or {}
        ), patch.object(
            dnbs, "_available_qty", side_effect=lambda i, b, w, p: float(stock.get(b, 0.0))
        ), patch.object(dnbs, "_batch_expiry", return_value=None), patch.object(
            dnbs, "_linked_bundle_batches", return_value={}
        ), patch.object(
            dnbs, "_scan_status", return_value=dnbs.STATUS_NOT_SCANNED
        ), patch.object(
            dnbs, "_sync_bundle", side_effect=lambda doc, row, batches, posting: f"SABB-{row.name}"
        ) as sync, patch.object(
            dnbs, "_link_bundle_to_row"
        ) as link, patch.object(
            dnbs, "_unlink_bundle_from_row"
        ) as unlink, patch.object(
            dnbs, "_clear_row_bundle", return_value=True
        ) as clear, patch.object(
            dnbs, "_set_scan_status"
        ) as set_status, patch(
            "frappe.db.get_value", side_effect=_db_get_value
        ):
            out = dnbs.post_delivery_note_scan(self.doc.name, allocations)
            return out, {
                "sync": sync,
                "link": link,
                "unlink": unlink,
                "clear": clear,
                "set_status": set_status,
            }

    def test_fully_allocated_line_is_linked_to_its_bundle(self):
        out, calls = self._post({"r1": [{"batch_no": "BBB-113", "qty": 150}]})
        calls["link"].assert_called_once()
        self.assertEqual(calls["link"].call_args[0][1], "SABB-r1")
        calls["unlink"].assert_not_called()
        self.assertEqual(out["posted"]["linked_rows"], 1)
        self.assertEqual(out["posted"]["status"], dnbs.STATUS_PARTIAL)

    def test_partially_allocated_line_keeps_its_bundle_unlinked(self):
        # A short bundle on the row would fail validate_quantity on the Delivery
        # Note's next save, so the work is parked in an unlinked bundle instead.
        _out, calls = self._post({"r1": [{"batch_no": "BBB-113", "qty": 80}]})
        calls["sync"].assert_called_once()
        calls["unlink"].assert_called_once()
        calls["link"].assert_not_called()

    def test_every_line_allocated_marks_the_note_fully_scanned(self):
        out, calls = self._post({
            "r1": [{"batch_no": "BBB-113", "qty": 150}],
            "r2": [{"batch_no": "AAA-007", "qty": 100}],
        })
        self.assertEqual(out["posted"]["status"], dnbs.STATUS_FULL)
        calls["set_status"].assert_called_once_with(self.doc.name, dnbs.STATUS_FULL)

    def test_allocating_more_than_the_line_needs_is_refused(self):
        with self.assertRaisesRegex(frappe.ValidationError, "only 150.0 is required"):
            self._post({"r1": [{"batch_no": "BBB-113", "qty": 200}]})

    def test_batch_that_lost_stock_is_reported_not_refused(self):
        # ERPNext lets a draft bundle exceed current stock — draft bundles reserve
        # nothing — and refusing here would strand work already done on the floor.
        out, calls = self._post(
            {"r1": [{"batch_no": "BBB-113", "qty": 150}]}, stock={"BBB-113": 10.0}
        )
        calls["link"].assert_called_once()
        self.assertEqual(len(out["posted"]["warnings"]), 1)
        self.assertIn("BBB-113", out["posted"]["warnings"][0])

    def test_bundle_of_a_line_this_dialog_never_wrote_is_left_alone(self):
        # A Pick List allocation, or one of the legacy drafts already on site, is
        # not ours to delete just because nothing was scanned against it.
        _out, calls = self._post({"r1": [{"batch_no": "BBB-113", "qty": 150}]})
        calls["clear"].assert_not_called()

    def test_cleared_line_drops_the_bundle_this_dialog_wrote(self):
        _out, calls = self._post(
            {"r1": [{"batch_no": "BBB-113", "qty": 150}]},
            previous={"r2": {"AAA-007": 40.0}},
        )
        calls["clear"].assert_called_once()


class TestLoadDeliveryNote(unittest.TestCase):
    """Which Delivery Notes are open for scanning."""

    def _load(self, docstatus=0, status=dnbs.STATUS_NOT_SCANNED, exists=True):
        doc = _FakeDoc([_FakeRow(name="r1", idx=1, item_code="FG10011", qty=10)])
        doc.docstatus = docstatus
        with patch("frappe.db.exists", return_value=exists), patch(
            "frappe.has_permission", return_value=True
        ), patch("frappe.get_doc", return_value=doc), patch.object(
            dnbs, "_scan_status", return_value=status
        ):
            return dnbs._load_delivery_note("MAT-DN-2026-00011")

    def test_draft_not_yet_scanned_loads(self):
        self.assertEqual(self._load().name, "MAT-DN-2026-00011")

    def test_partially_scanned_can_be_revisited(self):
        self.assertEqual(self._load(status=dnbs.STATUS_PARTIAL).name, "MAT-DN-2026-00011")

    def test_fully_scanned_cannot_be_reopened(self):
        with self.assertRaisesRegex(frappe.ValidationError, "already fully scanned"):
            self._load(status=dnbs.STATUS_FULL)

    def test_submitted_delivery_note_is_refused(self):
        with self.assertRaisesRegex(frappe.ValidationError, "not a draft"):
            self._load(docstatus=1)

    def test_missing_delivery_note_is_refused(self):
        with self.assertRaisesRegex(frappe.ValidationError, "does not exist"):
            self._load(exists=False)

    def test_blank_name_is_refused(self):
        with self.assertRaisesRegex(frappe.ValidationError, "Select a Delivery Note"):
            dnbs._load_delivery_note("")


class TestPostingContext(unittest.TestCase):
    """The bundle's posting fields follow the installed schema.

    ``Serial and Batch Bundle`` carried posting_date + posting_time for most of v15
    and only later collapsed them into posting_datetime; both are live on isnack
    sites.
    """

    def _context(self, has_posting_datetime):
        doc = _FakeDoc([])

        class _Meta:
            def has_field(self, fieldname):
                return fieldname == "posting_datetime" and has_posting_datetime

        with patch("frappe.get_meta", return_value=_Meta()), patch.object(
            dnbs, "_combine_datetime", return_value="2026-09-22 09:00:00"
        ):
            return dnbs._posting_context(doc)

    def test_new_schema_writes_posting_datetime(self):
        out = self._context(True)
        self.assertEqual(out["bundle_fields"], {"posting_datetime": "2026-09-22 09:00:00"})

    def test_old_schema_writes_posting_date_and_time(self):
        out = self._context(False)
        self.assertEqual(
            out["bundle_fields"], {"posting_date": "2026-09-22", "posting_time": "09:00:00"}
        )


class TestScannableDeliveryNoteQuery(unittest.TestCase):
    """The Link query is the first half of "revisit until fully scanned"."""

    def _query(self, has_field=True, txt=None, filters=None):
        class _Meta:
            def has_field(self, fieldname):
                return has_field

        captured = {}

        def _sql(query, params):
            captured["query"] = " ".join(query.split())
            captured["params"] = params
            return []

        with patch("frappe.get_meta", return_value=_Meta()), patch(
            "frappe.db.sql", side_effect=_sql
        ):
            dnbs.get_scannable_delivery_notes(
                "Delivery Note", txt, "name", 0, 10, filters
            )
        return captured

    def test_only_drafts_that_are_not_fully_scanned(self):
        out = self._query()
        self.assertIn("dn.docstatus = 0", out["query"])
        self.assertIn("custom_scan_status", out["query"])
        self.assertEqual(out["params"]["full_status"], dnbs.STATUS_FULL)

    def test_search_text_matches_name_and_customer(self):
        out = self._query(txt="00011")
        self.assertEqual(out["params"]["txt"], "%00011%")
        self.assertIn("dn.customer_name like", out["query"])

    def test_customer_filter_is_applied(self):
        out = self._query(filters={"customer": "Nectar Ltd"})
        self.assertEqual(out["params"]["customer"], "Nectar Ltd")

    def test_missing_custom_field_does_not_break_the_picker(self):
        # Before the fixture is synced the column does not exist; the picker must
        # still list drafts rather than erroring.
        out = self._query(has_field=False)
        self.assertNotIn("custom_scan_status", out["query"])
        self.assertNotIn("full_status", out["params"])
