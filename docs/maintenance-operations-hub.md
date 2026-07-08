# Maintenance Operations Hub

A technician- and manager-facing operational layer built **on top of** ERPNext
v15's standard Asset Maintenance module. ERPNext core is **not** modified — the
operational work item remains the standard **Asset Maintenance Log**, extended
with `custom_*` fields and surrounded by custom doctypes, pages, reports and
scheduled jobs.

---

## 1. Data model

### Reused ERPNext doctypes (unchanged)
Asset · Asset Maintenance · Asset Maintenance Task · **Asset Maintenance Log**
(the operational work item) · Asset Maintenance Team.

### Custom fields (added via patch `add_maintenance_custom_fields`)
**Asset Maintenance Log:** `custom_operational_status`, `custom_assigned_technician`,
`custom_estimated_duration_mins`, `custom_started_on`, `custom_completed_on`,
`custom_safety_warning`, `custom_completion_notes`, `custom_requires_verification`,
`custom_verified_by`, `custom_verified_on`, `custom_verification_comments`,
`custom_checklist_generated`, `custom_reminder_stage`, `custom_last_reminder_on`.

**Asset Maintenance Task:** `custom_estimated_duration_mins`, `custom_safety_warning`,
`custom_requires_verification`.

**Asset:** `custom_maintenance_barcode` (scan lookup fallback).

> ERPNext's standard `maintenance_status` is left authoritative. The operations
> layer writes a parallel `custom_operational_status` and only sets
> `maintenance_status = Completed/Cancelled` at the right lifecycle points so core
> scheduling (next due date / last completion) keeps working.

### New custom doctypes
| DocType | Kind | Purpose |
|---|---|---|
| Maintenance Checklist Template | normal | checklist header + matching criteria |
| Maintenance Checklist Template Item | child | template steps |
| Maintenance Checklist Response | normal | per-log answered checklist rows |
| Maintenance Reading | normal | readings with out-of-range flag |
| Maintenance Spare Part | normal | required/consumed parts + stock links |
| Asset Breakdown | normal | corrective maintenance reports |
| Maintenance Escalation Rule | normal | reminder/escalation config |

---

## 2. Page / API architecture

### Pages (Frappe desk pages)
- `maintenance-technician-hub` — cards grouped by urgency, scan/lookup, task
  detail dialog. Supports deep links `?asset=ASSET-0001` and `?log=<log>`.
- `maintenance-manager-hub` — KPI cards + Today / This Week / Next 30 / Calendar /
  Kanban / Breakdowns / Reports views, with reassign / status / verify actions.

HTML templates live in `isnack/public/page/<page>/<page>.html` and are fetched at
runtime; JS/CSS live in `isnack/isnack/page/<page>/` (bundled by `bench build`).

### Whitelisted API modules (`isnack/api/`)
- `maintenance_hub.py` — `get_technician_work`, `get_task_detail`, `start_task`,
  `acknowledge_task`, `complete_task`, `cannot_complete`, `reassign_task`,
  `set_operational_status`, `verify_task`, `lookup_asset`, `get_manager_dashboard`,
  `get_technicians`.
- `maintenance_checklist.py` — `ensure_checklist_for_log`, `save_checklist_response`.
- `maintenance_readings.py` — `add_reading`, `delete_reading`.
- `maintenance_spares.py` — `add_spare_part`, `delete_spare_part`,
  `create_material_request`, `create_material_issue` (both create **drafts** only).
- `maintenance_breakdown.py` — `report_breakdown`.
- `maintenance_tasks.py` — scheduler jobs.

All technician actions enforce `ensure_log_access` (a technician may only touch a
log assigned to them); manager actions enforce a manager/supervisor role.

### Scheduled jobs (daily — `hooks.py`)
- `sync_operational_statuses` — open+past-due → Overdue; ERPNext-Completed → Completed.
- `send_upcoming_maintenance_reminders` — before-due rules.
- `escalate_overdue_maintenance` — after-due / escalation rules.
- `check_required_spare_parts` — refresh availability, flag shortages.

Reminders are **idempotent**: each log tracks `custom_reminder_stage` +
`custom_last_reminder_on`, so re-running the scheduler the same day never
re-sends the same reminder. `repeat_daily_until_resolved` rules resend on the
next day automatically.

### Operational statuses
`Planned · Assigned · Acknowledged · In Progress · Waiting for Parts ·
Waiting for Shutdown · Completed · Completed with Issue · Cannot Complete ·
Skipped · Cancelled · Overdue · Pending Verification · Verified`

---

## 3. Migration & fixtures

Changes ship as **code** (doctypes, pages, reports, workspace) plus four
idempotent patches (registered in `patches.txt`, run on migrate):

1. `setup_maintenance_roles` — creates the three maintenance roles.
2. `add_maintenance_custom_fields` — creates all custom fields.
3. `seed_maintenance_escalation_rules` — seeds the six default rules.
4. `backfill_operational_status` — fills `custom_operational_status` on existing logs.

No manual fixture editing is required. (The app already exports `Custom Field`
fixtures, so a later `bench export-fixtures` will capture these too.)

---

## 4. Bench commands

```bash
bench --site <site> migrate        # creates doctypes + runs the 4 patches
bench --site <site> clear-cache
bench build                        # bundles the two hub pages
bench --site <site> clear-website-cache
bench restart                      # picks up new scheduler_events / hooks
```

Grant roles to users (Maintenance Technician / Maintenance Manager /
Maintenance Supervisor) via **User** records or **Role Profile**.

---

## 5. Testing guide

### Sample data
1. **Asset** — create an Asset (e.g. `ASSET-0001`); optionally set
   `custom_maintenance_barcode` for scan testing.
2. **Asset Maintenance** — create one for the asset, add an **Asset Maintenance
   Task** (maintenance_task, type Preventive Maintenance, periodicity, start
   date). Save — ERPNext generates an **Asset Maintenance Log** with a due date.
3. **Assign a technician** — open the log (or use the Manager Hub → *Reassign*)
   and set `custom_assigned_technician`.
4. **Checklist template** — create a *Maintenance Checklist Template* matching the
   asset category / maintenance type, add items (include a `Safety Step`).

### Functional tests
- **Technician Hub** (`/app/maintenance-technician-hub`): the log appears in the
  correct urgency bucket. Press **Start** → status → In Progress and checklist
  rows are generated. Fill checklist, add a reading (out-of-range value shows ⚠),
  add a spare part, upload a photo, then **Complete**.
- **Required checklist enforcement**: try completing with a required/safety row
  unanswered → blocked with a clear message.
- **Verification**: set `custom_requires_verification` on the task/log; completing
  moves it to *Pending Verification*; Manager Hub → **Verify** moves it to *Verified*.
- **QR lookup**: `/app/maintenance-technician-hub?asset=ASSET-0001` or type the
  asset code / barcode into the scan box → asset panel with open logs, history,
  breakdowns and documents.
- **Breakdown**: report one from a card / asset panel → creates an *Asset
  Breakdown* and notifies managers.
- **Spares**: *Create Material Request* / *Create Material Issue* produce **draft**
  documents (links shown) — nothing is submitted automatically.

### Scheduler tests (run jobs on demand)
```bash
bench --site <site> execute isnack.api.maintenance_tasks.sync_operational_statuses
bench --site <site> execute isnack.api.maintenance_tasks.send_upcoming_maintenance_reminders
bench --site <site> execute isnack.api.maintenance_tasks.escalate_overdue_maintenance
bench --site <site> execute isnack.api.maintenance_tasks.check_required_spare_parts
```
- Set a log's due date to today/−1/−3 to trigger the matching rules; check the
  recipient's **Notification Log**. Re-run the same job → **no duplicate** (the
  reminder stage guards it). Next day, `repeat_daily_until_resolved` rules re-fire.

### Reports
`/app/query-report/Maintenance Due Next 30 Days`, `Overdue Maintenance`,
`Technician Workload`, `Maintenance Compliance`.

### Unit tests
```bash
bench --site <site> run-tests --module isnack.api.test_maintenance
```

---

## 6. Assumptions & risks

- **ERPNext assets module installed.** All patches/jobs no-op gracefully when the
  `Asset Maintenance Log` doctype is absent.
- **Completion advances ERPNext core.** `complete_task` sets
  `maintenance_status = Completed` (and `completion_date`) when the technician
  finishes, even if verification is still pending — so ERPNext's next-due-date
  scheduling advances at physical completion. *Verified* is an operational overlay.
  Change `complete_task` if you need ERPNext completion deferred until verification.
- **Stock is confirm-only.** Material Request / Material Issue are created as
  drafts; a user must review and submit them. No silent stock transactions.
- **Out-of-range readings flag only** — no automatic breakdown is created
  (per chosen configuration); raise one manually if needed.
- **Asset field names.** Optional Asset fields (`serial_no`, `custodian`,
  `custom_maintenance_barcode`) are read defensively via meta checks.
- **Notifications** use Notification Log (+ optional email per rule). SMS/WhatsApp
  are intentionally out of scope but the rule's `notification_channel` leaves room
  to extend.
- **Manager-as-technician view** lets managers view a technician's board; the
  technician-only guard still blocks technicians from other technicians' work.
