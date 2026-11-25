# Quality Hub — Architecture Reference

**App:** isnack  
**Module:** Isnack  
**ERPNext Compatibility:** v15  
**Developer:** Busuttil Technologies Limited  
**Last Updated:** 2026-10-25 (follow-up fixes)

---

## Table of Contents

1. [Overview](#1-overview)
2. [Excel Sheet → DocType Mapping](#2-excel-sheet--doctype-mapping)
3. [DocType Inventory](#3-doctype-inventory)
4. [Common Field Schema](#4-common-field-schema)
5. [Per-DocType Field Schemas](#5-per-doctype-field-schemas)
   - [QCA — QC Receiving Record](#qca--qc-receiving-record)
   - [QCB — QC Puffs Extruder Record](#qcb--qc-puffs-extruder-record)
   - [QCC — QC Rice Extruder Record](#qcc--qc-rice-extruder-record)
   - [QCD — QC Frying Line Record](#qcd--qc-frying-line-record)
   - [QCE — QC Oven Record](#qce--qc-oven-record)
   - [QCF — QC Tasting Record](#qcf--qc-tasting-record)
   - [QCG — QC Packaging Check](#qcg--qc-packaging-check)
   - [QCH — QC Metal Detector Log](#qch--qc-metal-detector-log)
   - [Metal Detector](#metal-detector)
   - [Quality Hub Settings](#quality-hub-settings)
   - [QCI — QC Weight Check](#qci--qc-weight-check)
6. [Child Table Schemas](#6-child-table-schemas)
   - [QC Extruder Reading](#qc-extruder-reading)
   - [QC Puffs Extruder Reading](#qc-puffs-extruder-reading)
   - [QC Puffs Oven Reading](#qc-puffs-oven-reading)
   - [QC Rice Extruder Reading](#qc-rice-extruder-reading)
   - [QC Rice Oven Reading](#qc-rice-oven-reading)
   - [QC Frying Reading](#qc-frying-reading)
   - [QC Oven Reading](#qc-oven-reading)
   - [QC Tasting Score](#qc-tasting-score)
   - [QC Metal Detector Test](#qc-metal-detector-test)
   - [Metal Detector Factory Line](#metal-detector-factory-line)
   - [Quality Hub Factory Line](#quality-hub-factory-line)
   - [QC Weight Sample](#qc-weight-sample)
7. [RBAC / Permissions](#7-rbac--permissions)
8. [Backend Controller Logic](#8-backend-controller-logic)
9. [Hooks & Doc Events](#9-hooks--doc-events)
10. [API Endpoints](#10-api-endpoints)
11. [Quality Hub UI Architecture](#11-quality-hub-ui-architecture)
12. [Data Flow Diagram](#12-data-flow-diagram)
13. [File Map](#13-file-map)
14. [Integration Points](#14-integration-points)
15. [Configuration & Deployment](#15-configuration--deployment)
16. [Future Considerations](#16-future-considerations)

---

## 1. Overview

The **Quality Hub** is isnack's third specialist interface, sitting alongside the **Operator Hub** and **Storekeeper Hub** within the MES layer of the application. Its purpose is to give Quality Control personnel a single, browser-based entry point for capturing, reviewing, and monitoring every quality record generated on the factory floor — replacing the nine Excel QC sheets that were previously maintained by hand.

### Design Principle

> *Paper QC sheets → digital ERP records*

Each physical worksheet (Receiving, Puffs Extruder, Rice Extruder, Frying Line, Oven, Tasting, Packaging, Metal Detector, Weight Check) is mapped 1-to-1 to a submittable Frappe DocType. The Quality Hub page surfaces the DocTypes through a unified, tabbed interface, and the backend triggers automatic field calculations on submission.

**Oven record retired (2026-10).** Oven readings are now taken on the Puffs Extruder (QCB) and Rice Extruder (QCC) records, in an **Oven / Slurry Readings** section under their own readings (**Oven Readings**, with the oven's columns alone, on both until 2026-11: QCC's was renamed when it took the slurry's columns, QCB's when it took the Rice's). QC Oven Record (QCE) stays, so old records remain readable in the desk and in the Quality Explorer, but the Quality Hub no longer offers, counts or expects it (`RETIRED_QC_CODES` in `quality_hub.py`).

**Extruder readings changed (2026-11).** The Puffs Extruder (QCB) and the Rice Extruder (QCC) each take their own readings and oven readings: QCB in `puffs_readings` (QC Puffs Extruder Reading) and `puffs_oven_readings` (QC Puffs Oven Reading), QCC in `rice_readings` (QC Rice Extruder Reading) and `rice_oven_readings` (QC Rice Oven Reading); both oven tables are shown as **Oven / Slurry Readings**. Their earlier tables, `readings` and `oven_readings`, still point to the shared QC Extruder Reading and QC Oven Reading, so the rows recorded in them stay, in an **Earlier Readings** section shown only on a record that has such rows. Those rows can be corrected or removed on a draft or an amendment, but no rows are added: the form hides Add Row (`cannot_add_rows`, set by each record's form script), and the controller drops a blank row added another way (Tab out of the last cell, the grid's shortcuts, a paste) and refuses one with a value (`isnack/utils/earlier_readings.py`). Duplicate does not copy them (`no_copy`); Amend does.

**Packaging check changed (2026-11).** The QC Packaging Check (QCG) no longer records Film Type, Film Batch or the material reconciliation (Qty Issued, Used and Returned, and the Variance worked out from them); Qty Wasted is mandatory, and Label Correct reads **Packet Label Correct (Best Before / Batch Ref)**. The checks made before keep those fields and their variance result, in an **Earlier Layout** section: the patch `isnack.patches.v1_0.qc_packaging_check_earlier_layout` marks them (`earlier_layout`, hidden), every submitted or cancelled one and each draft holding film or reconciliation; a draft holding none is finished the new way. A check made since has no variance, so the Quality Explorer shows it with no result.

**Weight check changed (2026-11).** The QC Weight Check (QCI) judges each sample: a sample has a mandatory **Status** (Pass / Fail) and its own **Remarks**, next to the Gross Weight. The TU1 and TU2 limits, the samples' Tare Weight and the Outcome section (Overall Status, Remarks) came off the check. The checks made before keep them, with the TU failures, each sample's net weight and in-range mark and the Overall Status they were given, in an **Earlier Layout** section; their Samples grid keeps the columns it was made with (Gross, Tare, Net Weight, In Range; no Status or Remarks), set by the form script: the patch `isnack.patches.v1_0.qc_weight_check_earlier_layout` marks them (`earlier_layout`, hidden), every submitted or cancelled one and each draft holding a limit, an Overall Status, Remarks or a tare; a draft holding none is finished the new way. On a check made since, the Overall Status is worked out from the samples (Fail when any sample failed) for the Quality Hub lists and the Quality Explorer; the form does not show it. The mark is kept the way the packaging check's is (`isnack/utils/earlier_layout.py`, shared by both).

**Weight check: no item or batch; numbered and weighed (2026-11).** The QC Weight Check no longer records an **Item Code** or **Batch No**: its Work Order names the product. Both fields are `read_only` and `no_copy`, so a check that holds them (one made before, or an amendment or a restore of one) shows them and a Duplicate leaves them out, while a new check does not show them (Frappe hides a read-only field without a value); nothing fills them in any more (the Quality Hub form filled in the Work Order's item until then). The check does not refuse them: a restore is saved as a new check, and a User Permission on an item fills one in on a new check. The Quality Explorer still finds a check made before by its batch, and one made since by its Work Order. The **Nominal Weight** is mandatory, and so are each sample's **Sample No** and **Gross Weight** (`reqd`); on a check made since, all three must be more than 0, as Frappe saves a blank number as 0 and its mandatory check lets a 0 through. In the Samples the **Status** comes before the **Remarks**. A check is not submitted without a sample (`before_submit`): the Quality Hub already asked for one before it saved, the desk form did not.

**Metal detector log changed (2026-11).** The QC Metal Detector Log (QCH) picks its **Metal Detector ID** from a new master, **Metal Detector**, which holds each detector's Make/Model, Last and Next Calibration Date and Calibration Certificate. The log's Make/Model and calibration dates are filled from the detector picked and cannot be edited (`fetch_from`, `read_only`); they are taken when the log is saved, so a submitted log keeps the calibration it was verified under, and so does its amendment (of the same detector). The Calibration Certificate is kept on the Metal Detector only, and each test's Sensitivity Setting and Remarks came off; Test Piece Size (mm) starts at 0.2. The patch `isnack.patches.v1_0.metal_detectors_from_qc_logs` makes a Metal Detector of each ID the logs named (and the logs deleted before, for a restore), with the details of the newest log holding each, so their links lead somewhere and a draft can still be saved; the log refuses an ID that names no Metal Detector. The logs made before keep their certificate and their tests' sensitivity settings and remarks, in **Earlier Layout** sections: the patch `isnack.patches.v1_0.qc_metal_detector_log_earlier_layout` marks them (`earlier_layout`, hidden), every submitted or cancelled one and each draft holding any of them; a draft holding none is finished the new way.

**Metal detectors by factory line; no corrective action (2026-11).** A Metal Detector is used on one or more factory lines (its **Factory Lines**, required). The log's **Metal Detector ID** offers the detectors used on the Factory Line picked, on the form and in the Quality Hub dialog; a detector picked that is not used on a line picked afterwards is taken off, and the log refuses one not used on its line (an amendment keeps the detector and line of the log it amends). The patch `isnack.patches.v1_0.metal_detector_lines_from_qc_logs` gives each detector the lines of the logs that name it. The **Corrective Action** came off the log: the logs holding one keep it in their Earlier Layout section, marked by the patch `isnack.patches.v1_0.qc_metal_detector_log_corrective_action`.

**Metal detector log: the detector and each test's time and test piece mandatory (2026-11).** On a log made since, the **Metal Detector ID** is mandatory, and so are each test's **Test Time** and **Test Piece Type**; and a log is not submitted without a test (`before_submit`: the Quality Hub already asked for one before it saved, the desk form did not). The fields are not `reqd` on the doctypes, as a log made before keeps what it recorded (a draft, an amendment, a restore): the controller requires them on a log made since (`require_detector_and_tests`), and the form script marks them required there, as the Quality Hub dialog does. A draft from before that a log made since could not be (no detector, a test without a time or a test piece) is marked earlier layout when it is deleted (`on_trash`), and so is one deleted before the deploy (the patch `isnack.patches.v1_0.qc_metal_detector_log_earlier_layout`), so a restore brings it back (`finished_the_new_way`). Test Piece Type starts blank (a blank first option: a Select starts at its first option, so every new test read Fe until someone changed it), and Frappe no longer fills in a test's Test Time or Test Piece Type when it saves the log (`QCMetalDetectorTest.__setup__`; it gave a Time the time of saving), so a test sent without them is refused rather than given them. A Data Import gives a test the time of import as it makes the row: `check_import` refuses a test imported without its time (see *What an import must give*, below).

**Rice extruder: the slurry's tank and mixer (2026-11).** On the Rice Extruder's **Oven / Slurry Readings**, `tank_temp` reads **Slurry Tank Temp (°C)** and `motor_speed` **Mixer Speed (Hz)** (Tank Temp and Motor Speed until then). Only the labels changed, so the readings recorded stay where they are. The extruder's own Motor Speed, in its Readings, keeps its label.

**Puffs extruder: Oven / Slurry Readings, as on the Rice (2026-11).** The Puffs Extruder's oven readings are its **Oven / Slurry Readings** (Oven Readings until then), with the Rice's columns: QC Puffs Oven Reading took **Slurry Tank Temp (°C)** (`tank_temp`), **Mixer Speed (Hz)** (`motor_speed`) and **Flavour Speed (Hz)** (`flavour_speed`), and the Rice's column widths, on the desk form and in the Quality Hub dialog. The two oven tables stay separate doctypes with the same fields. Oven readings recorded before read 0 in the three new columns, as Frappe saves a blank number; none are averaged.

**Rice extruder: the rice's moisture (2026-11).** On the Rice Extruder, `moisture_corn_content` reads **Moisture Rice Content (%)** in its Readings, and its average `avg_moisture_corn_content` **Avg Moisture Rice Content (%)** (Moisture Corn Content until then). Only the labels changed, so the readings recorded stay where they are. The Puffs Extruder keeps **Moisture Corn Content (%)**.

**Factory lines by tab (2026-11).** [Quality Hub Settings](#quality-hub-settings) gives each Quality Hub tab that records a factory line the lines it records on: Puffs Extruder, Rice Extruder, Frying Line, Tasting, Packaging and Weight Checks (one list for both checks, which its form records together) and CCP & Metal. A tab's New dialog, and its records' desk forms, offer only those lines, and fill in the line when the tab has just one; the records refuse another line (`check_factory_line`, a `validate` doc event), an amendment keeping the line of the record it amends. A tab given no lines offers every line, as before the settings came. Receiving has no factory line.

**Work Orders by line, and the item they make (2026-11).** A record's **Work Order** offers the Work Orders on its Factory Line, whatever the tab: those whose own line (`custom_factory_line`, the Work Order's **Factory Section**, filled from its BOM's default line) is the record's, none cancelled, on the Quality Hub's dialogs and on the records' desk forms; before a line is picked, every Work Order. A Work Order on another line is taken off, with an alert ("MFG-WO-2026-00096 is not on FRYING: pick a Work Order on that line."), when the line changes or when it is typed in full. A line no Work Order is planned on offers none, so the Packaging and Weight and CCP & Metal checks are recorded on the production line the product comes from (Quality Hub Settings gives those tabs production lines, and each Metal Detector lists them). On a Process record (QCB–QCD) the **Product Item** offers the item the Work Order makes, which picking the Work Order fills in (it can still be emptied); without a Work Order it offers Finished Goods items, as before. The doctypes' fixed Finished Goods filter (`link_filters`) came off: Frappe puts a field's `link_filters` in place of any query set on it. The pickers apply the rule; a save does not check it (`isnack/public/js/quality_hub_lines.js`). For a few hours main also had a Packing Lines table in Quality Hub Settings mapping packing lines to production lines; it came off, and the patch `isnack.patches.v1_0.remove_quality_hub_packing_line` deletes its doctype on a site migrated in between.

**The Operator is an Employee (2026-11).** Each record type but the retired QCE names its operator in **Operator** (`operator`, a Link to Employee), picked as the Operator Hub's Set Operator picks one: by ID or name, among the Active Employees. Unlike the Operator Hub, it is not locked to the logged-in user's Employee: the QC inspector names the operator whose work was checked. **Operator Name** (`operator_name`) is now read-only, the Employee's name, which the server sets on every save (`check_operator`), so the record lists, the Quality Explorer and the print show it as before. The Operator is required on the records made since: a record made before keeps the name typed on it, and needs no Operator when saved again or amended. An Operator newly picked is an Active Employee; one the record (or the record amended) already had stays. Quality users hold no permission on Employee, whose records carry personal data: the Operator's search (`search_operators`) and its name (`get_operator`) come from `isnack/utils/qc_operator.py`, which gives only an Employee's ID, name and status, and only to a user who may create or change QC records; the Link skips Frappe's client-side check (`ignore_link_validation`), which needs that permission, and the server checks it on save. The same lookup serves the desk lists' and Report View's filters on Operator, and the Link's open arrow is hidden from a user who may not read Employee. `ignore_user_permissions` on the field lets a user linked to an Employee (ERPNext gives them a User Permission to it) save and list the records that name other operators, and keeps Frappe from filling a new record's Operator with that user's own Employee. A deleted record comes back as a new one under a new name, which Frappe does not mark, so a restored record made before is refused for want of an Operator, and one whose Employee has left since is refused that Employee.

**QC records can be imported (2026-11).** Records kept on paper are entered in bulk with Frappe's **Data Import**: every record type, the retired QCE too (for its records from before), has `allow_import: 1`, and its readings come in with it as child rows. Frappe gives the Data Import doctype to System Manager alone (Role Permission Manager could give it to another role; none has it here), and a System Manager may import every doctype that allows it, whatever its Import permission: the record types grant **Import** to System Manager alone, which records that (the permission only decides which types Data Import's form offers a role given Data Import). A desk import runs as a background job, and Frappe refuses to start one, or its Retry, while the site's scheduler is off ("Scheduler is inactive. Cannot import data."), unless the site is in developer mode. A Data Import saved in the desk can instead be run on the server by the job Start Import would enqueue, `bench --site <site> execute frappe.core.doctype.data_import.data_import.start_import --args "['<its name>']"` (as Administrator; run again, it retries the rows refused, as Retry does). Frappe 15.88's `bench data-import` is no substitute: it imports through an unsaved Data Import, whose log rows have no Data Import, so a later run takes every earlier run's rows as its own and fails, or skips the rows they record as imported. A file must reach Frappe as written: Excel's "CSV UTF-8" starts it with a byte-order mark, which Frappe 15 keeps on the first header, so that column matches no field and is left to its default (a Record Date first would date every record the day of import); a file that starts with an empty **ID** column, as Frappe's own template does, loses only that. The QC series take the year a record is made in (`.YYYY.`), not its Record Date's.

**The operator of a record imported (2026-11).** An import names the operator as the paper does, by name: a new record imported with an **Operator Name** but no **Operator** is the Employee's of that name (`check_operator`, through `_operator_named` in `isnack/utils/qc_operator.py`). The names are compared in Python (`_name_key`), on both sides, whatever the case, the accents (Ġ as G, ħ as h), apostrophes and full stops (O'Brien as OBrien, J. Borg as J Borg), dashes (Mary-Anne as Mary Anne) and stray, doubled or non-breaking spaces: ERPNext joins an Employee's first, middle and last names as typed, so a stored name may carry a stray space too. Every Employee counts, whatever their status, as the paper may be older than a namesake who joined or left since: a name several Employees have is refused ("Several Employees are named … (HR-EMP-…, HR-EMP-… (Left)): give the Operator by Employee ID instead"); a name no Employee has is refused ("No Employee is named …: add … as an Employee first, or give the Operator by Employee ID"), but one close to an Employee's (a middle name left out, an initial: `_may_be`) is refused naming them ("No Employee is named …, but it may be HR-EMP-… (…): give the Operator by Employee ID, or add … as an Employee if it is none of them"), so the same person is not added twice. The name is shown as text (Frappe shows a message as HTML, the Data Import Log too). A record imported is of work done before: its Operator, named or given by ID, may be an Employee who has left since, but not one whose Relieving Date is before the record's date, whatever their status now. An Operator given by ID is otherwise taken as on any save, and a record saved (an import updating it) or amended keeps the rules above; an import updating a record that sends another Operator Name, with the same Operator, is refused ("An import does not change Operator Name …"), as the name would be put back without a word: the Operator is changed by its Employee ID. The Employee is added in the Employee form or by importing it (ERPNext gives Employee's Create and Import to HR User and HR Manager); a user linked to an Employee has a User Permission on it (ERPNext adds one), which refuses them a new Employee unless it reports to theirs, so Administrator, or an HR user not so restricted, adds it. A desk import's Retry then brings in the rows refused. Download Template ticks only the required columns, and the Operator is not one (`check_operator` requires it, not the doctype): tick **Operator Name**, as the **Operator** column takes only an Employee ID.

**What an import must give (2026-11).** `check_import` (`isnack/utils/qc_import.py`, the first `before_validate` of every record type) refuses, in an import only, what would otherwise be recorded wrong without a word: the times on the rows the import makes (a new record's, or the new rows of a record it updates), the rest on the record as the import leaves it. A row is named by its place in the record's table ("this record's row 2"), the Import Log giving the file's lines:

- a reading's **Time Slot**, or a test's **Test Time**, left blank or its column left out: Frappe makes each row an import brings with its defaults, which give a Time the time of import (`nowtime()`, as it reads the file), so a time to the millionth of a second from the two hours before is the import's own and refused as missing ("Time Slot is required in Readings (this record's row 2) and in Oven / Slurry Readings (this record's row 1)."); a time in another form than hh:mm[:ss] (8.30, 0830, 8:30 PM, 24:00) is refused naming it, as the database would read 8.30 as 8.3 seconds after midnight, or refuse it in its own words; a time given as hh:mm, to the second or a fraction of one, is taken as given;
- a tasting score that is not a number from 0 to 1: Frappe keeps a Rating as the fraction of the stars given (4 of 5 stars is 0.8), takes more than 1 as full marks and text (4/5, 80%, 4 stars, a date Excel made of 4/5) as no stars, so stars typed as a count would all read as full marks, and scores written as text as none. An import gives 1 star as 0.2 and 5 stars as 1, as a number; a whole number is not read as stars (1 would still be full marks, and the QCF-006 paper scores 1 as the best of 4);
- a field taken off the record type in 2026-11 (the Packaging Check's film and reconciliation; the Weight Check's TU limits, Remarks and samples' tare; the Metal Detector Log's certificate and corrective action, and each test's sensitivity setting and remarks), given to a record not marked **Earlier Layout**: the record type refuses it however it is saved, with "This page is out of date", which an import has no page for; here the fields are named. A record from before is imported with Earlier Layout set to 1 (a hidden column, which Download Template's Select All offers);
- a **QC Receiving Record** of a delivery (its Purchase Receipt, Item Code and Batch No, all three mandatory) that has a record already, not cancelled: an import run again, or after deliveries were recorded by hand, does not record it twice ("QCA-… already records this delivery …").

An import is held to the Quality Hub's other rules only as any save is: the pickers' Work Order on the record's line and Product Item the Work Order makes are not checked on save (above), and a reading is required only where a record type requires one to submit (a Metal Detector Log's test, a Weight Check's sample). An **Update Existing Records** import gives a record's tables the rows its file gives them, as Frappe does: a file listing only a new reading leaves the record with that reading alone, so export the record and keep its rows, or add the reading in the form.

**Packaging and weight checks entered together (2026-11).** The Quality Hub's **Packaging and Weight Checks** tab has one form for both checks: the Record Details they share are entered once, and one save creates the QC Packaging Check and the QC Weight Check together, or neither. Either can be unticked to record the other on its own. The tab lists them in one list too, with a **Check** column, where it had a pill for each. The two doctypes are unchanged, each still one paper sheet (QCG-007, QCI-009); see [Per-Tab Components](#per-tab-components).

The Quality Hub and Quality Explorer pages set no roles of their own (`"roles": []` in their page JSON), so any desk user can open them; what a user sees and may do there follows the QC record types' permissions. The **Quality Controller**, **Quality Manager**, and **System Manager** roles record and review QC records, and **Production Manager** has read-only visibility into all of them (see [Section 7](#7-rbac--permissions)).

### Position Within the isnack MES Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      isnack MES Layer                       │
├─────────────────┬────────────────────┬──────────────────────┤
│  Storekeeper    │   Operator Hub     │   Quality Hub        │
│     Hub         │                    │                      │
│  (material      │  (kiosk-mode       │  (QC data entry &    │
│  staging &      │  production        │  live checkpoint     │
│  transfers)     │  interface)        │  monitoring)         │
└─────────────────┴────────────────────┴──────────────────────┘
                        │
              ERPNext v15 (Frappe)
         Work Order · Batch · Item · Supplier
         Purchase Receipt · Quality Inspection
```

---

## 2. Excel Sheet → DocType Mapping

| # | Excel File | DocType Name | Code | Naming Series | Production Stage |
|---|---|---|---|---|---|
| 1 | QCA-001 Receiving records V2.xlsx | QC Receiving Record | QCA | `QCA-.YYYY.-.#####` | Receiving |
| 2 | QCB-002 Puffs Extruder Record.xlsx | QC Puffs Extruder Record | QCB | `QCB-.YYYY.-.#####` | Process |
| 3 | QCC-003 Rice Extruder Record V2.xlsx | QC Rice Extruder Record | QCC | `QCC-.YYYY.-.#####` | Process |
| 4 | QCD-004 Frying Line Record V2.xlsx | QC Frying Line Record | QCD | `QCD-.YYYY.-.#####` | Process |
| 5 | QCE-005 Oven Record Sheet V2.xlsx | QC Oven Record | QCE | `QCE-.YYYY.-.#####` | Process — retired 2026-10, now on QCB and QCC |
| 6 | QCF-006 Tasting Records V2.xlsx | QC Tasting Record | QCF | `QCF-.YYYY.-.#####` | Tasting |
| 7 | QCG-007 Packaging material checks and reconciliation V2.xlsx | QC Packaging Check | QCG | `QCG-.YYYY.-.#####` | Packaging |
| 8 | QCH-008 Daily Metal Detector Verification.xlsx | QC Metal Detector Log | QCH | `QCH-.YYYY.-.#####` | CCP |
| 9 | QCI-009 Weight Quality Check Sheet.xlsx | QC Weight Check | QCI | `QCI-.YYYY.-.#####` | Packaging |

---

## 3. DocType Inventory

All 23 DocTypes (9 parent records, 12 child tables, the Metal Detector master and the Quality Hub Settings) registered under the **Isnack** module:

| DocType Name | Type | Code | Child Table Of | File Path |
|---|---|---|---|---|
| QC Receiving Record | Parent | QCA | — | `isnack/isnack/doctype/qc_receiving_record/` |
| QC Puffs Extruder Record | Parent | QCB | — | `isnack/isnack/doctype/qc_puffs_extruder_record/` |
| QC Rice Extruder Record | Parent | QCC | — | `isnack/isnack/doctype/qc_rice_extruder_record/` |
| QC Frying Line Record | Parent | QCD | — | `isnack/isnack/doctype/qc_frying_line_record/` |
| QC Oven Record | Parent | QCE (retired) | — | `isnack/isnack/doctype/qc_oven_record/` |
| QC Tasting Record | Parent | QCF | — | `isnack/isnack/doctype/qc_tasting_record/` |
| QC Packaging Check | Parent | QCG | — | `isnack/isnack/doctype/qc_packaging_check/` |
| QC Metal Detector Log | Parent | QCH | — | `isnack/isnack/doctype/qc_metal_detector_log/` |
| QC Weight Check | Parent | QCI | — | `isnack/isnack/doctype/qc_weight_check/` |
| Metal Detector | Master | — | — (linked from QCH) | `isnack/isnack/doctype/metal_detector/` |
| Quality Hub Settings | Single | — | — | `isnack/isnack/doctype/quality_hub_settings/` |
| QC Extruder Reading | Child | N/A | QCB, QCC (earlier readings) | `isnack/isnack/doctype/qc_extruder_reading/` |
| QC Puffs Extruder Reading | Child | N/A | QCB | `isnack/isnack/doctype/qc_puffs_extruder_reading/` |
| QC Puffs Oven Reading | Child | N/A | QCB | `isnack/isnack/doctype/qc_puffs_oven_reading/` |
| QC Rice Extruder Reading | Child | N/A | QCC | `isnack/isnack/doctype/qc_rice_extruder_reading/` |
| QC Rice Oven Reading | Child | N/A | QCC | `isnack/isnack/doctype/qc_rice_oven_reading/` |
| QC Frying Reading | Child | N/A | QCD | `isnack/isnack/doctype/qc_frying_reading/` |
| QC Oven Reading | Child | N/A | QCB, QCC (earlier readings); QCE (retired) | `isnack/isnack/doctype/qc_oven_reading/` |
| QC Tasting Score | Child | N/A | QCF | `isnack/isnack/doctype/qc_tasting_score/` |
| QC Metal Detector Test | Child | N/A | QCH | `isnack/isnack/doctype/qc_metal_detector_test/` |
| Metal Detector Factory Line | Child | N/A | Metal Detector (its Factory Lines) | `isnack/isnack/doctype/metal_detector_factory_line/` |
| Quality Hub Factory Line | Child | N/A | Quality Hub Settings (each tab's lines) | `isnack/isnack/doctype/quality_hub_factory_line/` |
| QC Weight Sample | Child | N/A | QCI | `isnack/isnack/doctype/qc_weight_sample/` |

All parent DocTypes have `"is_submittable": 1` and `"track_changes": 1`, and `"allow_import": 1` (2026-11: Data Import, see [Section 7](#7-rbac--permissions)). All child DocTypes have `"istable": 1` and `"editable_grid": 1`. The Metal Detector is a plain master (not submittable), with `"track_changes": 1`: each change of its calibration is kept in its version history. Quality Hub Settings is a single doctype (`"issingle": 1`), with `"track_changes": 1` too.

---

## 4. Common Field Schema

The following 10 fields are present on every parent DocType (QCA–QCI) with identical definitions, with exceptions (see the notes):

| Fieldname | Fieldtype | Label | Notes |
|---|---|---|---|
| `record_date` | Date | Record Date | `reqd: 1`, `default: "Today"` |
| `shift` | Select | Shift | `reqd: 1`, options: (blank) / Morning / Afternoon / Night: a new record starts blank (2026-11; at Morning until then), as in the Quality Hub's dialogs |
| `factory_line` | Link → Factory Line | Factory Line | `reqd: 1` (2026-11) · **not on QCA** · optional on the retired QCE |
| `work_order` | Link → Work Order | Work Order | `reqd: 1` (2026-11) · **not on QCA** · optional on the retired QCE · offers the Work Orders on the record's Factory Line (2026-11; not on QCE, which no tab records) |
| `operator` | Link → Employee | Operator | Required on the records made since by `check_operator` (2026-11), not in the doctype: a record made before needs none · `ignore_user_permissions: 1`, `print_hide: 1` · offers Active Employees by ID or name (`search_operators`) · on a new record imported without it, the Employee named in Operator Name, who may have left since (2026-11) · **not on the retired QCE** |
| `operator_name` | Data | Operator Name | `read_only: 1`, `no_copy: 1` (2026-11): the Operator's name, set by the server on save; typed (`reqd: 1`) until 2026-11, and still on the retired QCE · a Data Import may name the Operator by it (2026-11; Download Template does not tick it) |
| `qc_inspector` | Link → User | QC Inspector | `reqd: 1`, `default: "__user"` (auto-fills current user) |
| `status` | Select | Status | options: Draft / Submitted / Rejected / Closed |
| `remarks` | Small Text | Remarks | — |
| `amended_from` | Link → (same DocType) | Amended From | `read_only: 1`, `no_copy: 1` |

---

## 5. Per-DocType Field Schemas

Each section below lists only the **DocType-specific** fields (beyond the 10 common fields above).

---

### QCA — QC Receiving Record

**Naming:** `QCA-.YYYY.-.#####`  
**Purpose:** Records goods-inward inspection for raw materials and packaging arriving from suppliers.

A delivery is inspected before any line or Work Order touches it, so QCA has no `factory_line` or `work_order` (FSSC 22000 change, 2026-10). The supplier and item section is all mandatory, and the quality checks are blank / Yes / No / Not applicable selects: a blank answer is a check not done, which a tick box could not tell apart from a failed one ("Not applicable" added 2026-11). The patch `isnack.patches.v1_0.qc_receiving_yes_no_checks` carried existing records over (ticked → Yes, unticked → blank) and moved `colour_acceptable` to `appearance_acceptable`. The old `factory_line`, `work_order` and `colour_acceptable` columns stay in the table, unused.

| Fieldname | Fieldtype | Label | Notes |
|---|---|---|---|
| `supplier` | Link → Supplier | Supplier | `reqd: 1` |
| `purchase_receipt` | Link → Purchase Receipt | Purchase Receipt | `reqd: 1` |
| `item_code` | Link → Item | Item Code | `reqd: 1` |
| `item_name` | Data | Item Name | `fetch_from: item_code.item_name`, `read_only: 1` |
| `batch_no` | Link → Batch | Batch No | `reqd: 1` |
| `qty_received` | Float | Qty Received | `reqd: 1` |
| `packaging_intact` | Select | Packaging Intact | options: (blank) / Yes / No / Not applicable |
| `labelling_correct` | Select | Labelling Correct | options: (blank) / Yes / No / Not applicable |
| `foreign_body_check` | Select | Foreign Body Check | options: (blank) / Yes / No / Not applicable |
| `appearance_acceptable` | Select | Appearance Acceptable | options: (blank) / Yes / No / Not applicable · was `colour_acceptable` |
| `dimensions_acceptable` | Select | Dimensions Acceptable | options: (blank) / Yes / No / Not applicable |
| `weight_acceptable` | Select | Weight Acceptable | options: (blank) / Yes / No / Not applicable |
| `arrival_temperature` | Float | Arrival Temperature (°C) | — |
| `coa_received` | Check | COA Received | — |
| `coa_acceptable` | Check | COA Acceptable | — |
| `spec_sheet_matches` | Check | Spec Sheet Matches | — |
| `overall_status` | Select | Overall Status | options: (blank) / Accepted / Conditionally Accepted / Rejected |

---

### QCB — QC Puffs Extruder Record

**Naming:** `QCB-.YYYY.-.#####`  
**Purpose:** Shift-level extruder process record for puffs production lines, with per-time-slot readings.

| Fieldname | Fieldtype | Label | Notes |
|---|---|---|---|
| `product_item` | Link → Item | Product Item | the item the Work Order makes, filled in when it is picked; Finished Goods items without one (2026-11, a query in `quality_hub_lines.js`; `link_filters` item group Finished Goods until then) |
| `product_name` | Data | Product Name | `fetch_from: product_item.item_name`, `read_only: 1` |
| `puffs_readings` | Table → QC Puffs Extruder Reading | Readings | Child table (since 2026-11) |
| `avg_moisture_corn_content` | Float | Avg Moisture Corn Content (%) | `read_only: 1` — auto-calculated; shown (and printed) when there are readings |
| `oven_readings_section` | Section Break | Oven / Slurry Readings | — (Oven Readings until 2026-11) |
| `puffs_oven_readings` | Table → QC Puffs Oven Reading | Oven / Slurry Readings | Child table, optional (since 2026-11; labelled Oven Readings at first) |
| `avg_oven_temp` | Float | Avg Oven Temp (°C) | `read_only: 1` — auto-calculated; shown (and printed) when there are oven readings |
| `avg_puffs_oven_moisture` | Float | Avg Oven Moisture (%) | `read_only: 1` — auto-calculated; shown (and printed) when there are oven readings |
| `earlier_readings_section` | Section Break | Earlier Readings | shown only when `readings` or `oven_readings` has rows |
| `readings` | Table → QC Extruder Reading | Readings (Earlier Layout) | `no_copy: 1`, no new rows; shown only when it has rows |
| `avg_moisture` | Float | Avg Moisture (%) | `read_only: 1` — auto-calculated from `readings` |
| `avg_density` | Float | Avg Density | `read_only: 1` — auto-calculated from `readings` |
| `out_of_range_count` | Int | Out of Range Count | `read_only: 1` — `readings` with moisture > 14% |
| `oven_readings` | Table → QC Oven Reading | Oven Readings (Earlier Layout) | `no_copy: 1`, no new rows; shown only when it has rows |
| `avg_oven_zone1_temp` | Float | Avg Oven Zone 1 Temp (°C) | `read_only: 1` — auto-calculated from `oven_readings` |
| `avg_oven_zone2_temp` | Float | Avg Oven Zone 2 Temp (°C) | `read_only: 1` — auto-calculated from `oven_readings` |
| `avg_oven_moisture` | Float | Avg Oven Moisture (%) (Earlier Layout) | `read_only: 1` — auto-calculated from `oven_readings` |
| `result_section` | Section Break | — | — |
| `overall_status` | Select | Overall Status | options: (blank) / Pass / Fail |

The averages and the out-of-range count of the earlier layout are kept with its rows, in the Earlier Readings section. No out-of-range rule is set for the new readings yet. The standard print does not evaluate `depends_on`, so `before_print` leaves out the summary fields of a table without rows, as the form does (an earlier record still prints an Out of Range Count of 0).

---

### QCC — QC Rice Extruder Record

**Naming:** `QCC-.YYYY.-.#####`  
**Purpose:** Shift-level extruder process record for rice extruder lines, with per-time-slot readings. Laid out as QCB, with tables of its own: its Readings record the rice's moisture, and its Oven / Slurry Readings have the same columns as QCB's.

| Fieldname | Fieldtype | Label | Notes |
|---|---|---|---|
| `product_item` | Link → Item | Product Item | the item the Work Order makes, filled in when it is picked; Finished Goods items without one (2026-11, a query in `quality_hub_lines.js`; `link_filters` item group Finished Goods until then) |
| `product_name` | Data | Product Name | `fetch_from: product_item.item_name`, `read_only: 1` |
| `rice_readings` | Table → QC Rice Extruder Reading | Readings | Child table (since 2026-11) |
| `avg_moisture_corn_content` | Float | Avg Moisture Rice Content (%) | `read_only: 1` — auto-calculated; shown (and printed) when there are readings (Avg Moisture Corn Content (%) until 2026-11) |
| `oven_readings_section` | Section Break | Oven / Slurry Readings | — |
| `rice_oven_readings` | Table → QC Rice Oven Reading | Oven / Slurry Readings | Child table, optional (since 2026-11) |
| `avg_oven_temp` | Float | Avg Oven Temp (°C) | `read_only: 1` — auto-calculated; shown (and printed) when there are oven readings |
| `avg_rice_oven_moisture` | Float | Avg Oven Moisture (%) | `read_only: 1` — auto-calculated; shown (and printed) when there are oven readings |
| `earlier_readings_section` … `avg_oven_moisture` | | | the Earlier Readings section, as QCB's |
| `result_section` | Section Break | — | — |
| `overall_status` | Select | Overall Status | options: (blank) / Pass / Fail |

---

### QCD — QC Frying Line Record

**Naming:** `QCD-.YYYY.-.#####`  
**Purpose:** Records frying process conditions (oil temperature, product moisture) per time slot.

| Fieldname | Fieldtype | Label | Notes |
|---|---|---|---|
| `product_item` | Link → Item | Product Item | the item the Work Order makes, filled in when it is picked; Finished Goods items without one (2026-11, a query in `quality_hub_lines.js`; `link_filters` item group Finished Goods until then) |
| `product_name` | Data | Product Name | `fetch_from: product_item.item_name`, `read_only: 1` |
| `readings` | Table → QC Frying Reading | Readings | Child table |
| `avg_oil_temperature` | Float | Avg Oil Temperature (°C) | `read_only: 1` — auto-calculated; a reading left blank (saved as 0) is left out |
| `avg_product_moisture` | Float | Avg Moisture Content (%) | `read_only: 1` — auto-calculated; a reading left blank (saved as 0) is left out (was "Avg Product Moisture (%)") |
| `out_of_range_count` | Int | Out of Range Count | `read_only: 1` — placeholder for future spec-based logic |
| `overall_status` | Select | Overall Status | options: (blank) / Pass / Fail |

---

### QCE — QC Oven Record

**Retired 2026-10:** oven readings are taken on QCB (`puffs_oven_readings`) and QCC (`rice_oven_readings`) now, since 2026-11; their earlier `oven_readings` take no new rows. Kept so old records stay readable.

**Naming:** `QCE-.YYYY.-.#####`  
**Purpose:** Records oven zone temperatures, belt speed, and product moisture per time slot.

| Fieldname | Fieldtype | Label | Notes |
|---|---|---|---|
| `product_item` | Link → Item | Product Item | — |
| `product_name` | Data | Product Name | `fetch_from: product_item.item_name`, `read_only: 1` |
| `readings` | Table → QC Oven Reading | Readings | Child table |
| `avg_zone1_temp` | Float | Avg Zone 1 Temp (°C) | `read_only: 1` — auto-calculated |
| `avg_zone2_temp` | Float | Avg Zone 2 Temp (°C) | `read_only: 1` — auto-calculated |
| `avg_moisture` | Float | Avg Moisture (%) | `read_only: 1` — auto-calculated |
| `out_of_range_count` | Int | Out of Range Count | `read_only: 1` — placeholder for future spec-based logic |
| `overall_status` | Select | Overall Status | options: (blank) / Pass / Fail |

---

### QCF — QC Tasting Record

**Naming:** `QCF-.YYYY.-.#####`  
**Purpose:** Panel tasting evaluation with per-taster scores across multiple sensory attributes.

| Fieldname | Fieldtype | Label | Notes |
|---|---|---|---|
| `batch_no` | Link → Batch | Batch No | `reqd: 1` |
| `item_code` | Link → Item | Item Code | `fetch_from: batch_no.item`, `read_only: 1` |
| `item_name` | Data | Item Name | `fetch_from: item_code.item_name`, `read_only: 1` |
| `scores` | Table → QC Tasting Score | Scores | Child table |
| `avg_overall` | Percent | Avg Overall % | `read_only: 1` — average of the tasters' Overall % |
| `min_score` | Percent | Min Overall % | `read_only: 1` — lowest Overall % |
| `overall_status` | Select | Overall Status | auto-set to Pass/Fail by `validate()` |

---

### QCG — QC Packaging Check

**Naming:** `QCG-.YYYY.-.#####`  
**Purpose:** Checks print quality, seal integrity, the packet label (best before, batch reference) and artwork, and records the packaging wasted. Until 2026-11 it also recorded the film and accounted for the film material (issued vs used/wasted/returned); the checks made before keep those, in an Earlier Layout section.

| Fieldname | Fieldtype | Label | Notes |
|---|---|---|---|
| `print_quality_ok` | Check | Print Quality OK | — |
| `seal_integrity_ok` | Check | Seal Integrity OK | — |
| `label_correct` | Check | Packet Label Correct (Best Before / Batch Ref) | — |
| `artwork_matches` | Check | Artwork Matches | — |
| `qty_wasted` | Float | Qty Wasted | `reqd: 1` (a check made before keeps the 0 Frappe saved for a blank) |
| `earlier_layout_section` | Section Break | Earlier Layout | shown only on a check made before 2026-11 (`earlier_layout`) |
| `film_type` | Data | Film Type | `no_copy: 1`; earlier layout |
| `film_batch` | Data | Film Batch | `no_copy: 1`; earlier layout |
| `qty_issued` | Float | Qty Issued | `no_copy: 1`; earlier layout |
| `qty_used` | Float | Qty Used | `no_copy: 1`; earlier layout |
| `qty_returned` | Float | Qty Returned | `no_copy: 1`; earlier layout |
| `variance` | Float | Variance | `read_only: 1`, `no_copy: 1` — auto-calculated on a check made before: `issued − used − wasted − returned`; 0 on one made since |
| `variance_acceptable` | Check | Variance Acceptable | `read_only: 1`, `no_copy: 1` — auto-set on a check made before: `1` if `abs(variance) ≤ 0.5`; 0 on one made since |
| `earlier_layout` | Check | Earlier Layout | `hidden`, `read_only`, `no_copy`, `print_hide` — set by the patch `qc_packaging_check_earlier_layout` on the checks made before 2026-11 that keep the earlier layout (submitted or cancelled, or a draft holding film or reconciliation); Amend carries it, and `validate` never lets it go |

---

### QCH — QC Metal Detector Log

**Naming:** `QCH-.YYYY.-.#####`  
**Purpose:** Critical Control Point (CCP) daily verification log for metal detectors. Mandatory per HACCP requirements. Since 2026-11 the detector is picked from the [Metal Detectors](#metal-detector) used on the log's factory line, and its details are taken from it; until then they were typed on each log, with a calibration certificate, a corrective action and each test's sensitivity setting and remarks. The logs made before keep those, in Earlier Layout sections.

| Fieldname | Fieldtype | Label | Notes |
|---|---|---|---|
| `metal_detector_id` | Link → Metal Detector | Metal Detector ID | Data until 2026-11: the patch `metal_detectors_from_qc_logs` made a Metal Detector of each ID the logs named. Offers the detectors used on the `factory_line` (`qc_metal_detector_log.js`, the Quality Hub dialog). Mandatory on a log made since 2026-11 (`require_detector_and_tests`; the form script marks it, `frm.toggle_reqd`), not `reqd` on the doctype, so a log made before keeps what it recorded |
| `detector_make_model` | Data | Make/Model | `fetch_from: metal_detector_id.make_model`, `read_only: 1` |
| `last_calibration_date` | Date | Last Calibration Date | `fetch_from: metal_detector_id.last_calibration_date`, `read_only: 1` |
| `next_calibration_date` | Date | Next Calibration Date | `fetch_from: metal_detector_id.next_calibration_date`, `read_only: 1` |
| `tests` | Table → QC Metal Detector Test | Tests | Child table |
| `all_tests_passed` | Check | All Tests Passed | `read_only: 1` — auto-calculated |
| `earlier_layout_section` | Section Break | Earlier Layout | shown only on a log made before 2026-11 (`earlier_layout`) |
| `calibration_certificate` | Attach | Calibration Certificate | `no_copy: 1`; earlier layout (kept on the Metal Detector since) |
| `corrective_action` | Small Text | Corrective Action | `no_copy: 1`; earlier layout (since 2026-11; until then required when a test failed, `mandatory_depends_on: eval:!doc.all_tests_passed`) |
| `earlier_layout` | Check | Earlier Layout | `hidden`, `read_only`, `no_copy`, `print_hide` — set by the patch `qc_metal_detector_log_earlier_layout` on the logs made before 2026-11 that keep the earlier layout (submitted or cancelled, or a draft holding a certificate or a test's sensitivity setting or remarks), and by `qc_metal_detector_log_corrective_action` on each log holding a corrective action; Amend carries it, and `validate` never lets it go |

The fetched fields are filled when the detector is picked (the form, the Quality Hub dialog) and again when the log is saved (Frappe's link validation, which overwrites them: they are not `fetch_if_empty`); a submitted log is not saved again, so it keeps the Make/Model and calibration dates it was verified under when the Metal Detector changes. Its amendment is a new record, into which Frappe fetches the detector's current ones, and again each time the amendment is saved as a draft: the log puts back those of the log it amends on each save, until it is submitted, when the detector is the same (`keep_details_verified_under`), and takes the other detector's when another is picked. A deleted log restored is a new record too, and takes the detector's details as they are then. A detector cleared on the form clears them; a log saved with no detector keeps what it holds.

Frappe does not check a Link that fields are fetched from (v15: it reads the record's values, and when there is none it fetches nothing and says nothing), so the log checks its Metal Detector ID names a Metal Detector (`check_metal_detector`, "Could not find Metal Detector: …"): a page loaded before the change, the API, or a draft whose ID could not be made a detector cannot save a log naming none.

The detector is one used on the log's factory line, one of its Factory Lines (`check_detector_on_line`, "Metal Detector … is not used on …"): the form and the dialog offer only those, but a Link takes any detector typed in full. A log made before is held to it too; the patch `metal_detector_lines_from_qc_logs` gave each detector the lines of its logs. An amendment keeps the detector and line of the log it amends (case and surrounding spaces aside), as it keeps its calibration: the detector may have moved to another line since. No line or no detector, nothing is checked.

---

### Metal Detector

**Naming:** `field:metal_detector_id` (the ID is the record's name; renaming it renames the links on the logs)  
**Purpose:** A metal detector the QC Metal Detector Logs verify: the factory lines it is used on, and its calibration. Not submittable; `track_changes: 1`. Made from the log's Metal Detector ID without leaving the form (`quick_entry: 1`, all its fields `allow_in_quick_entry`; the quick entry asks for its Factory Lines), or from the Quality Hub's **Metal Detectors** quick link.

| Fieldname | Fieldtype | Label | Notes |
|---|---|---|---|
| `metal_detector_id` | Data | Metal Detector ID | `reqd: 1`, `unique: 1`; the name |
| `make_model` | Data | Make/Model | searched in the log's Metal Detector ID (`search_fields`) |
| `factory_lines` | Table MultiSelect → Metal Detector Factory Line | Factory Lines | `reqd: 1` (since 2026-11): the lines it is used on, where a log offers it. The patch `metal_detector_lines_from_qc_logs` gave each detector the lines of the logs naming it |
| `calibration_section` | Section Break | Calibration | — |
| `last_calibration_date` | Date | Last Calibration Date | — |
| `next_calibration_date` | Date | Next Calibration Date | — |
| `calibration_certificate` | Attach | Calibration Certificate | — |

Permissions follow the log's: Quality Controller read, write and create; Quality Manager and System Manager also delete; Production Manager read.

---

### Quality Hub Settings

**Naming:** single doctype (`issingle: 1`, `track_changes: 1`)  
**Purpose:** The factory lines each Quality Hub tab records on (since 2026-11). Opened from the Quality Hub's **Quality Hub Settings** quick link.

| Fieldname | Fieldtype | Label | Record types it restricts |
|---|---|---|---|
| `factory_lines_section` | Section Break | Factory Lines by Tab | — |
| `puffs_extruder_lines` | Table MultiSelect → Quality Hub Factory Line | Puffs Extruder (QCB) | QC Puffs Extruder Record |
| `rice_extruder_lines` | Table MultiSelect → Quality Hub Factory Line | Rice Extruder (QCC) | QC Rice Extruder Record |
| `frying_line_lines` | Table MultiSelect → Quality Hub Factory Line | Frying Line (QCD) | QC Frying Line Record |
| `tasting_lines` | Table MultiSelect → Quality Hub Factory Line | Tasting (QCF) | QC Tasting Record |
| `packaging_and_weight_lines` | Table MultiSelect → Quality Hub Factory Line | Packaging and Weight Checks (QCG/QCI) | QC Packaging Check, QC Weight Check (their form records both, with one line) |
| `metal_detector_lines` | Table MultiSelect → Quality Hub Factory Line | CCP & Metal (QCH) | QC Metal Detector Log |

A tab given no lines records on any line: nothing is restricted until the settings are filled in. Each line is kept once in a tab (`validate`, case and surrounding spaces aside). Receiving (QCA) has no factory line, and the retired Oven Record (QCE) is not offered, so neither has a field.

The controller, `quality_hub_settings.py`, holds which field is each record type's (`TAB_FIELDS`), and:
- `factory_lines(doctype)` — the lines records of `doctype` may be on, read from the cached settings (saving them clears the cache), each once: merging one listed line into another (Factory Line's Rename, "Merge with existing") rewrites the rows without the settings' `validate`. `[]` for any line, and before the migrate makes the settings (no `Quality Hub Settings` DocType yet: Frappe would find no controller to read them with, and raise `ImportError`).
- `get_factory_lines()` — whitelisted: those of each restricted record type, by doctype, for the hub's dialogs and the records' forms.
- `get_work_order_details(work_order)` — whitelisted: `{factory_line, production_item}` of a Work Order (`custom_factory_line`, `production_item`), for the pickers: a Work Order on another line than the record's is taken off, and its item fills in a Process record's Product Item. `{}` for a Work Order there is not, or one the user may neither select nor read (the document's permission, User Permissions included): whoever may pick it may know both, as its search lists its item.
- `check_factory_line(doc, method)` — the `validate` doc event of the seven restricted record types (`hooks.py`): refuses a Factory Line not given to the record's tab ("FRYING is not one of the factory lines Quality Hub Settings gives Puffs Extruder (QCB): CORN EXTRUSION."). The hub and the forms offer only those, but a Link takes any line typed in full. An amendment keeping the line of the record it amends is let through, as the Metal Detector Log keeps its detector: the tab may have left the line since. A draft is held to the lines as they are when it is saved again; a record with no line, or of a tab given none, is not checked.

Quality Manager and System Manager set it; a Quality Controller reads it. The hub and the forms read the lines through `get_factory_lines`, whoever the user.

---

### QCI — QC Weight Check

**Naming:** `QCI-.YYYY.-.#####`  
**Purpose:** Weight control for finished goods, sample by sample: each sample's number, gross weight, Status (Pass / Fail) and Remarks, with the average, standard deviation and min/max, against the nominal weight. Its Work Order names the product. Until 2026-11 it took TU1/TU2 limits, tares and an Overall Status instead, and named an item and a batch; the checks made before keep those (the limits, tares and status in an Earlier Layout section).

| Fieldname | Fieldtype | Label | Notes |
|---|---|---|---|
| `item_code` | Link → Item | Item Code | `read_only: 1`, `no_copy: 1` — held by checks made before 2026-11 (and their amendments and restores), shown only on them; nothing fills it in |
| `item_name` | Data | Item Name | `fetch_from: item_code.item_name`, `read_only: 1`, `no_copy: 1` |
| `batch_no` | Link → Batch | Batch No | `read_only: 1`, `no_copy: 1` — as Item Code; the Quality Explorer still finds a check made before by it |
| `nominal_weight` | Float | Nominal Weight (g) | `reqd: 1`; more than 0 on a check made since 2026-11 (`require_nominal_weight`) |
| `samples` | Table → QC Weight Sample | Samples | Child table |
| `sample_count` | Int | Sample Count | `read_only: 1` — auto-calculated |
| `average_weight` | Float | Average Weight (g) | `read_only: 1` — auto-calculated (of the net weights: the gross weights since 2026-11) |
| `std_deviation` | Float | Std Deviation | `read_only: 1` — population std dev |
| `min_weight` | Float | Min Weight (g) | `read_only: 1` — auto-calculated |
| `max_weight` | Float | Max Weight (g) | `read_only: 1` — auto-calculated |
| `earlier_layout_section` | Section Break | Earlier Layout | shown only on a check made before 2026-11 (`earlier_layout`) |
| `tu1_limit` | Float | TU1 Limit (g) | `no_copy: 1`; earlier layout — lower tolerance limit 1 |
| `tu2_limit` | Float | TU2 Limit (g) | `no_copy: 1`; earlier layout — lower tolerance limit 2 (maximum permissible shortage) |
| `tu1_failures` | Int | TU1 Failures | `read_only: 1`, `no_copy: 1`; earlier layout — count of samples below `tu1_limit` (0 on a check made since) |
| `tu2_failures` | Int | TU2 Failures | `read_only: 1`, `no_copy: 1`; earlier layout — count of samples below `tu2_limit` (0 on a check made since) |
| `overall_status` | Select | Overall Status | options: (blank) / Pass / Fail / Marginal; `no_copy: 1`. Entered on a check made before (earlier layout); on one made since, worked out from the samples' Status (Fail when any failed) and not shown on the form |
| `remarks` | Small Text | Remarks | `no_copy: 1`; earlier layout (a check made since has Remarks on each sample) |
| `earlier_layout` | Check | Earlier Layout | `hidden`, `read_only`, `no_copy`, `print_hide` — set by the patch `qc_weight_check_earlier_layout` on the checks made before 2026-11 that keep the earlier layout (submitted or cancelled, or a draft holding a limit, an Overall Status, Remarks or a tare); Amend carries it, and `validate` never lets it go |

The common `remarks` field (see above) sits in the Earlier Layout on this record.

---

## 6. Child Table Schemas

Child tables inherit no permissions (permissions are enforced on the parent). All have `"editable_grid": 1` for in-grid editing on the form view.

---

### QC Extruder Reading

**Used by:** QC Puffs Extruder Record (QCB) and QC Rice Extruder Record (QCC) for their earlier readings (`readings`; no new rows, `no_copy`)

| Fieldname | Fieldtype | Label | `in_list_view` |
|---|---|---|---|
| `time_slot` | Time | Time Slot | ✅ |
| `screw_speed_rpm` | Float | Screw Speed (RPM) | ✅ |
| `barrel_temp_zone_1` | Float | Barrel Temp Zone 1 (°C) | ✅ |
| `barrel_temp_zone_2` | Float | Barrel Temp Zone 2 (°C) | ✅ |
| `barrel_temp_zone_3` | Float | Barrel Temp Zone 3 (°C) | — |
| `die_pressure` | Float | Die Pressure (bar) | — |
| `moisture_content` | Float | Moisture Content (%) | ✅ |
| `product_density` | Float | Product Density | — |
| `reading_remarks` | Small Text | Remarks | — |

---

### QC Puffs Extruder Reading

**Used by:** QC Puffs Extruder Record (QCB) as `puffs_readings` (since 2026-11)

| Fieldname | Fieldtype | Label | `in_list_view` |
|---|---|---|---|
| `time_slot` | Time | Time Slot | ✅ (`columns: 1`) |
| `moisture_corn_content` | Float | Moisture Corn Content (%) | ✅ |
| `start_temp` | Float | Start Temp (°C) | ✅ (`columns: 1`) |
| `motor_speed` | Float | Motor Speed (Hz) | ✅ |
| `feed_motor` | Float | Feed Motor (Hz) | ✅ |
| `cutter_speed` | Float | Cutter Speed (Hz) | ✅ |

The desk grid has 10 units for columns; two narrow ones let all six show.

---

### QC Puffs Oven Reading

**Used by:** QC Puffs Extruder Record (QCB) as `puffs_oven_readings`, labelled **Oven / Slurry Readings** (since 2026-11). The same fields as QC Rice Oven Reading since 2026-11, when it took the slurry's three (it had the oven's four until then); kept apart so each line's readings can change on their own.

| Fieldname | Fieldtype | Label | `in_list_view` |
|---|---|---|---|
| `time_slot` | Time | Time Slot | ✅ (`columns: 1`) |
| `oven_temp` | Float | Oven Temp (°C) | ✅ (`columns: 1`) |
| `belt_speed` | Float | Belt Speed (Hz) | ✅ |
| `moisture` | Float | Moisture (%) | ✅ (`columns: 1`) |
| `tank_temp` | Float | Slurry Tank Temp (°C) | ✅ (`columns: 1`; since 2026-11) |
| `motor_speed` | Float | Mixer Speed (Hz) | ✅ (the slurry mixer's; since 2026-11) |
| `flavour_speed` | Float | Flavour Speed (Hz) | ✅ (since 2026-11) |

Seven columns in the desk grid's 10 units, as QC Rice Oven Reading's. Oven readings recorded before the slurry's columns came read 0 in them, as Frappe saves a blank number.

---

### QC Rice Extruder Reading

**Used by:** QC Rice Extruder Record (QCC) as `rice_readings` (since 2026-11). Same columns as QC Puffs Extruder Reading, kept apart so each line's readings can change on their own; its moisture is the rice's since 2026-11.

| Fieldname | Fieldtype | Label | `in_list_view` |
|---|---|---|---|
| `time_slot` | Time | Time Slot | ✅ (`columns: 1`) |
| `moisture_corn_content` | Float | Moisture Rice Content (%) | ✅ (Moisture Corn Content (%) until 2026-11; the fieldname is kept) |
| `start_temp` | Float | Start Temp (°C) | ✅ (`columns: 1`) |
| `motor_speed` | Float | Motor Speed (Hz) | ✅ |
| `feed_motor` | Float | Feed Motor (Hz) | ✅ |
| `cutter_speed` | Float | Cutter Speed (Hz) | ✅ |

---

### QC Rice Oven Reading

**Used by:** QC Rice Extruder Record (QCC) as `rice_oven_readings`, labelled **Oven / Slurry Readings** (since 2026-11)

| Fieldname | Fieldtype | Label | `in_list_view` |
|---|---|---|---|
| `time_slot` | Time | Time Slot | ✅ (`columns: 1`) |
| `oven_temp` | Float | Oven Temp (°C) | ✅ (`columns: 1`) |
| `belt_speed` | Float | Belt Speed (Hz) | ✅ |
| `moisture` | Float | Moisture (%) | ✅ (`columns: 1`) |
| `tank_temp` | Float | Slurry Tank Temp (°C) | ✅ (`columns: 1`; Tank Temp (°C) until 2026-11) |
| `motor_speed` | Float | Mixer Speed (Hz) | ✅ (the slurry mixer's; Motor Speed (Hz) until 2026-11) |
| `flavour_speed` | Float | Flavour Speed (Hz) | ✅ |

Seven columns in the desk grid's 10 units: four are narrow (the full label shows on hover).

---

### QC Frying Reading

**Used by:** QC Frying Line Record (QCD)

| Fieldname | Fieldtype | Label | `in_list_view` |
|---|---|---|---|
| `time_slot` | Time | Time Slot | ✅ |
| `oil_temperature` | Float | Oil Temperature (°C) | ✅ |
| `oil_ffa` | Float | Oil (FFA) (was "Oil FFA") | ✅ |
| `oil_tpm` | Float | Oil (TPM) (was "Oil TPM") | ✅ |
| `oil_pv` | Float | Oil (PV) | — |
| `oil_anv` | Float | Oil (ANV) | — |
| `product_moisture` | Float | Moisture Content (%) (was "Product Moisture (%)") | ✅ |
| `oil_change_flag` | Check | Oil Changed | — |

The per-reading Remarks (`reading_remarks`) was removed in 2026-11: remarks go in the record's own Remarks field (Product & Outcome). Values entered before stay in the table's column, no longer shown.

---

### QC Oven Reading

**Used by:** QC Puffs Extruder Record (QCB) and QC Rice Extruder Record (QCC) for their earlier oven readings (`oven_readings`; no new rows, `no_copy`); QC Oven Record (QCE, retired) as `readings`

| Fieldname | Fieldtype | Label | `in_list_view` |
|---|---|---|---|
| `time_slot` | Time | Time Slot | ✅ |
| `zone_1_temp` | Float | Zone 1 Temp (°C) | ✅ |
| `zone_2_temp` | Float | Zone 2 Temp (°C) | ✅ |
| `zone_3_temp` | Float | Zone 3 Temp (°C) | — |
| `belt_speed` | Float | Belt Speed | ✅ |
| `moisture` | Float | Moisture (%) | ✅ |
| `colour_value` | Float | Colour Value | — |
| `reading_remarks` | Small Text | Remarks | — |

---

### QC Tasting Score

**Used by:** QC Tasting Record (QCF)

| Fieldname | Fieldtype | Label | `in_list_view` |
|---|---|---|---|
| `taster_name` | Data | Taster Name | ✅ |
| `appearance_score` | Rating | Shape (was "Appearance") | ✅ |
| `colour_score` | Rating | Colour | ✅ |
| `aroma_score` | Rating | Smell (was "Aroma") | ✅ (since 2026-11, as it makes the Overall %) |
| `taste_score` | Rating | Taste | ✅ |
| `texture_score` | Rating | Texture | ✅ (since 2026-11, as it makes the Overall %) |
| `overall_percent` | Percent | Overall % | ✅ — `read_only: 1`, worked out from the five scores (since 2026-11) |
| `overall_score` | Rating | Overall (stars, before 2026-11) | — `hidden: 1`, `read_only: 1`, `print_hide: 1`, `no_copy: 1`: the taster's own Overall rating on tastings scored before |

The desk grid shows the taster, all five scores and the Overall % (`columns`: taster 2, the others 1, within the grid's 10 units).
| `comments` | Small Text | Comments | — |

---

### QC Metal Detector Test

**Used by:** QC Metal Detector Log (QCH)

| Fieldname | Fieldtype | Label | `in_list_view` |
|---|---|---|---|
| `test_time` | Time | Test Time | ✅ (mandatory on a log made since 2026-11: the log requires it, the form script marks the column, `grid.toggle_reqd`; not `reqd` on the doctype) |
| `test_piece_type` | Select | Test Piece Type | ✅ (options: blank / Fe / Non-Fe / Stainless: a new test starts blank since 2026-11, at Fe until then; mandatory on a log made since 2026-11, as Test Time) |
| `test_piece_size_mm` | Float | Test Piece Size (mm) | ✅ (`default: 0.2`, since 2026-11) |
| `detected` | Check | Detected (Pass) | ✅ |
| `earlier_layout_section` | Section Break | Earlier Layout | — (in the row's form, shown only on a log made before 2026-11: `eval:parent.earlier_layout`) |
| `sensitivity_setting` | Data | Sensitivity Setting | — (`no_copy`, `print_hide_if_no_value`; earlier layout) |
| `test_remarks` | Small Text | Remarks | — (`no_copy`, `print_hide_if_no_value`; earlier layout) |

When it saves a log, Frappe gives a new test what it was not sent from a new test's defaults (a Time takes the time of saving, a Select its first option). The controller turns that off for Test Time and Test Piece Type (`QCMetalDetectorTest.__setup__` sets `dont_update_if_missing`), so a test sent without them is refused (`require_detector_and_tests`), and the tests of a log made before keep a missing time when the log is amended or restored. A Data Import gives a row its defaults as it makes the row, so it gives a blank Test Time the time of import: `check_import` (`isnack/utils/qc_import.py`) refuses that test.

---

### Metal Detector Factory Line

**Used by:** Metal Detector (`factory_lines`, a Table MultiSelect: a row per line, picked by its one Link)

| Fieldname | Fieldtype | Label | `in_list_view` |
|---|---|---|---|
| `factory_line` | Link → Factory Line | Factory Line | ✅ (`reqd`) |

The log's Metal Detector ID is filtered on it: `[["Metal Detector Factory Line", "factory_line", "=", <line>]]`, which Frappe's link search and `frappe.db.get_list` join on the detector.

---

### Quality Hub Factory Line

**Used by:** Quality Hub Settings (each tab's Table MultiSelect: a row per line, picked by its one Link)

| Fieldname | Fieldtype | Label | `in_list_view` |
|---|---|---|---|
| `factory_line` | Link → Factory Line | Factory Line | ✅ (`reqd`) |


---

### QC Weight Sample

**Used by:** QC Weight Check (QCI)

| Fieldname | Fieldtype | Label | `in_list_view` | Notes |
|---|---|---|---|---|
| `sample_no` | Int | Sample No | ✅ | `reqd: 1`; more than 0 on a check made since 2026-11 (`QCWeightCheck.require_sample_figures`) |
| `gross_weight` | Float | Gross Weight (g) | ✅ | `reqd: 1`; more than 0 on a check made since 2026-11, as Sample No |
| `status` | Select | Status | ✅ | options: (blank) / Pass / Fail; `depends_on: eval:!parent.earlier_layout`; mandatory on a check made since 2026-11 (`QCWeightCheck.require_sample_status`; the form script `qc_weight_check.js` marks the column with `grid.toggle_reqd`), not on one made before |
| `remarks` | Small Text | Remarks | ✅ | `columns: 4`; `depends_on: eval:!parent.earlier_layout` |
| `earlier_layout_section` | Section Break | Earlier Layout | — | in the row's form, shown only on a check made before 2026-11 (`eval:parent.earlier_layout`) |
| `tare_weight` | Float | Tare Weight (g) | — | `no_copy`, `print_hide_if_no_value`; earlier layout |
| `net_weight` | Float | Net Weight (g) | — | `read_only: 1`, `no_copy`, `print_hide_if_no_value` — Gross − Tare, calculated by parent `validate()` (the gross weight since 2026-11) |
| `in_range` | Check | In Range | — | `read_only: 1`, `no_copy`, `print_hide_if_no_value` — on a check made before, 1 if `net_weight >= tu2_limit` |

The grid's columns follow the check: on one made since, Sample No, Gross Weight, Status and Remarks (the doctype's `in_list_view`); on one made before, Sample No, Gross Weight, Tare Weight, Net Weight and In Range, as it was made. The form script `qc_weight_check.js` sets them (`grid.update_docfield_property(…, "in_list_view", …)`, `grid.reset_grid()`); the doctype cannot say either per check.

---

## 7. RBAC / Permissions

The permission model is identical across all 9 parent DocTypes (read from the `"permissions"` block of each `.json` file):

| Permission | Quality Controller | Quality Manager | System Manager | Production Manager |
|---|:---:|:---:|:---:|:---:|
| Read | ✅ | ✅ | ✅ | ✅ |
| Write | ✅ | ✅ | ✅ | — |
| Create | ✅ | ✅ | ✅ | — |
| Submit | ✅ | ✅ | ✅ | — |
| Cancel | ✅ | ✅ | ✅ | — |
| Amend | ✅ | ✅ | ✅ | — |
| Delete | — | ✅ | ✅ | — |
| Export | ✅ | ✅ | ✅ | — |
| Import | — | — | ✅ | — |
| Print | ✅ | ✅ | ✅ | — |
| Email | ✅ | ✅ | ✅ | — |
| Report | ✅ | ✅ | ✅ | — |
| Share | ✅ | ✅ | ✅ | — |

**Key points:**
- Quality Controllers can create, edit, and submit records, but **cannot delete** them.
- Quality Managers have full CRUD including deletion.
- Production Managers have **read-only** access — they can view QC records from their Operator Hub context but cannot create or modify them.
- Child table permissions are inherited from the parent DocType.
- Import (since 2026-11): records are imported with Frappe's Data Import, whose doctype Frappe gives System Manager alone (Role Permission Manager could give it to another role). A System Manager may import every doctype with `allow_import`, whatever its Import permission; the Import permission, the System Manager's alone, records that, and would only decide which types Data Import's form offers another role given Data Import.
- [Quality Hub Settings](#quality-hub-settings) (since 2026-11): Quality Manager and System Manager set it; Quality Controller reads it.
- Employee (since 2026-11, for the **Operator**): the quality roles need **no** permission on Employee. `isnack.utils.qc_operator` searches the Active Employees and reads an Employee's name for any user who may create or change a record type that names an Operator, and gives only the ID, name and status. Read or even Select on Employee is not granted: Employee records carry personal data (date of birth, bank and health details), which Select still lets the search API return.

---

## 8. Backend Controller Logic

Each parent DocType has a Python controller in `<doctype_folder>/<doctype_name>.py` that inherits from `frappe.model.document.Document` and implements a `validate()` method.

---

### QCA — QC Receiving Record

**File:** `isnack/isnack/doctype/qc_receiving_record/qc_receiving_record.py`

No calculation. The arrival temperature is recorded as read; the acceptable range and the Temperature Pass computed from it were removed in 2026-11 (their old values stay in the table, no longer shown).

---

### QCB — QC Puffs Extruder Record

**File:** `isnack/isnack/doctype/qc_puffs_extruder_record/qc_puffs_extruder_record.py`

```
validate():
    close_earlier_tables()
    # zero_is_blank: Frappe saves a blank Float as 0, and none of these is ever 0
    avg_moisture_corn_content = average(puffs_readings, "moisture_corn_content", zero_is_blank)
    avg_oven_temp             = average(puffs_oven_readings, "oven_temp", zero_is_blank)
    avg_puffs_oven_moisture   = average(puffs_oven_readings, "moisture", zero_is_blank)
    average_earlier_readings()   # the earlier layout: earlier_readings.set_averages

close_earlier_tables():       # earlier_readings.close_tables
    # in readings / oven_readings, a row added since the last save (on a new
    # amendment: beyond the amended record's count; on any other new record:
    # any row) is dropped if blank, refused otherwise

before_print():               # earlier_readings.leave_out_empty_summaries
    # the standard print ignores depends_on: blank the summary fields of a
    # table without rows, in memory only

earlier_readings.set_averages(doc):
    avg_moisture = average(readings, "moisture_content")
    avg_density  = average(readings, "product_density")
    out_of_range_count = count(r for r in readings if r.moisture_content > 14)
    avg_oven_zone1_temp, avg_oven_zone2_temp, avg_oven_moisture = oven_averages(oven_readings)
```

---

### QCC — QC Rice Extruder Record

**File:** `isnack/isnack/doctype/qc_rice_extruder_record/qc_rice_extruder_record.py`

As QCB, on `rice_readings` and `rice_oven_readings` (`avg_rice_oven_moisture`); its earlier tables follow the same rules, from `isnack/utils/earlier_readings.py`.

---

### QCD — QC Frying Line Record

**File:** `isnack/isnack/doctype/qc_frying_line_record/qc_frying_line_record.py`

```
validate():
    # zero_is_blank: Frappe saves a blank Float as 0, and neither is ever 0
    # (as on QCB / QCC, with the same average() from qc_oven_reading)
    avg_oil_temperature  = average(readings, "oil_temperature", zero_is_blank)
    avg_product_moisture = average(readings, "product_moisture", zero_is_blank)
    out_of_range_count   = 0   # placeholder — spec-based logic to be added
```

**Since 2026-11** a reading left blank (saved as 0) is left out of both averages, as on QCB and QCC. Until then the record counted it once the blank had been saved (a desk save, then Submit, for one), which pulled the averages down. The patch `isnack.patches.v1_0.recompute_qc_frying_averages` worked the averages of every record but the cancelled ones out again from its stored readings; it writes only a record whose averages change (`db_set`, `update_modified=False`) and leaves an Info comment on it saying what changed.

---

### QCE — QC Oven Record

**File:** `isnack/isnack/doctype/qc_oven_record/qc_oven_record.py`

```
validate():
    avg_zone1_temp, avg_zone2_temp, avg_moisture = oven_averages(readings)
    out_of_range_count = 0   # placeholder — spec-based logic to be added
```

`average(readings, fieldname, zero_is_blank=False)` (in `qc_oven_reading.py`) averages a field over the readings that have it, 0 when none does (with `zero_is_blank`, a 0 counts as not recorded); `oven_averages` uses it for zone 1 temperature, zone 2 temperature and moisture. The earlier readings of QCB and QCC use `oven_averages` on their `oven_readings` (`earlier_readings.set_averages`).

---

### QCF — QC Tasting Record

**File:** `isnack/isnack/doctype/qc_tasting_record/qc_tasting_record.py`

Frappe stores a Rating as the fraction of stars given (4 of 5 stars is `0.8`) and clamps it to 0..1 on save.

**Since 2026-11** each taster's **Overall %** is worked out from their five scores (Shape, Colour, Smell, Taste, Texture): the stars given over full marks, 5 × 5, a score left blank counting as 0. It replaces the Overall rating the taster gave; the record's average and lowest read in % and a tasting passes at an average of 60 % (`PASS_THRESHOLD_PERCENT`, 3 of 5 stars). The patch `isnack.patches.v1_0.qc_tasting_overall_percent` keeps the result of the tastings scored before: their Overall % is the taster's own Overall rating as a percentage (`overall_score` × 100; it stays, hidden), their average and lowest are worked out from those, and each says so in a comment. The result read in % is the result read in stars (3 stars is 60 %), except on a tasting never judged in stars (cancelled before 2026-10, its average still a fraction), which gets the result its scores give. A tasting whose ratings `recompute_qc_tasting_results` could not trust (all stored as full stars by the old dialog, its average still a fraction) gets no Overall % from them: its average and lowest read 0, its result stays, and its comment asks QC to check and re-enter the scores. The Quality Hub dialog and the desk form (`qc_tasting_record.js`) show the Overall % as the scores are given.

```
validate():
    for each taster row:
        overall_percent = sum(min(score, 1) for the five scores) / 5 * 100     # blank = 0
    scored = [overall_percent of rows with any score]                          # no score at all: left out
    avg_overall = mean(scored) if scored else 0
    min_score   = min(scored)  if scored else 0
    overall_status = "Pass" if scored and avg_overall >= PASS_THRESHOLD_PERCENT else "Fail"   # 60 %
```

**Until 2026-11** the result was worked out in stars from each taster's own Overall rating, passing at a 3-star average. Before 2026-10 the scores were not turned into stars and every tasting read "Fail"; the patch `isnack.patches.v1_0.recompute_qc_tasting_results` recomputed the stored results on the star scale (it keeps that calculation in itself, `_star_result`) and left a comment on each record whose result it changed. The Quality Hub dialog used to send the stars themselves, which Frappe clamped to 1.0, so 1 star and 5 stars were stored alike: that patch leaves a record with a taster whose every rating is 1.0 as it was, with a comment asking QC to check its scores, and lists it in the migrate output. The dialog picks stars (1–5) and sends the fraction.

---

### QCG — QC Packaging Check

**File:** `isnack/isnack/doctype/qc_packaging_check/qc_packaging_check.py`

```
validate():
    keep_earlier_layout()               # a form loaded before the migrate sends no mark:
                                        # keep the saved check's, or the amended one's
    if not earlier_layout:              # a check made since 2026-11: no reconciliation
        film_type, film_batch = None if only whitespace
        if any RETIRED_FIELDS holds a value:
            throw "This page is out of date"   # a form, Duplicate or hub page from before
        variance, variance_acceptable = 0, 0
        return
    issued   = qty_issued   or 0
    used     = qty_used     or 0
    wasted   = qty_wasted   or 0
    returned = qty_returned or 0
    variance             = issued - used - wasted - returned
    variance_acceptable  = 1 if abs(variance) ≤ 0.5 else 0

before_print():
    if not earlier_layout:              # print ignores depends_on
        blank EARLIER_FIELDS            # film, reconciliation, variance (in memory)
```

The checks made before 2026-11 that keep the earlier layout (`earlier_layout`, set by the patch `isnack.patches.v1_0.qc_packaging_check_earlier_layout`: every submitted or cancelled check, and each draft holding film or reconciliation, `belongs_to_earlier_layout`) keep their film, their reconciliation and the variance result worked out from it, in the Earlier Layout section; those can be corrected on a draft or an amendment. The patch marks a check deleted before in its Deleted Document too, so a restore brings it back as it was. A check made since records neither: its variance is 0, a value in a retired field is refused (a form loaded before the change), and the Quality Explorer gives it no result (`_result` in `quality_explorer.py`). Until the migrate adds the mark, every check is treated as one made before.

---

### QCH — QC Metal Detector Log

**File:** `isnack/isnack/doctype/qc_metal_detector_log/qc_metal_detector_log.py`

```
validate():
    earlier_layout.keep_mark(self)      # a form loaded before the migrate sends no mark
    if not earlier_layout:              # a log made since 2026-11
        refuse_retired_values()         # certificate, corrective action, a test's sensitivity
                                        # setting or remarks:
            blank a value of only spaces
            throw "This page is out of date"   # a form or hub page from before
        require_detector_and_tests():   # not reqd on the doctypes: a log made before keeps
                                        # what it recorded
            if no metal_detector_id: throw "Metal Detector ID is required."
            if a test has no test_time, then no test_piece_type:
                throw "<Test Time | Test Piece Type> is required in Tests (row …)."
    check_metal_detector()              # the ID names a Metal Detector (Frappe does not check
                                        # a Link that fields are fetched from)
    check_detector_on_line()            # the detector is used on the log's factory line; an
                                        # amendment keeps the detector and line it amends
    keep_details_verified_under()       # an amendment of the same detector: the Make/Model and
                                        # dates of the log amended, not the detector's current ones
    if tests is not empty:
        all_tests_passed = 1 if all(t.detected == True for t in tests) else 0
    else:
        all_tests_passed = 0

before_submit():
    if no tests:                        # the hub asks for one before it saves
        throw "Add at least one row in Tests to submit the log."

on_trash():
    if not earlier_layout and not finished_the_new_way(self, tests):
        earlier_layout = 1              # an unmarked draft from before: no detector, or a test
                                        # without a time or a test piece; in memory: its
                                        # Deleted Document can be restored
```

The Corrective Action came off in 2026-11 (it was mandatory when `all_tests_passed = 0`, through `mandatory_depends_on`); a log holding one keeps it in the Earlier Layout section, marked by the patch `isnack.patches.v1_0.qc_metal_detector_log_corrective_action` whatever its state (a log made since the Metal Detector change, unmarked till then, too), and in its Deleted Document when it was deleted before. A draft so marked shows the other retired fields too, blank.

The Make/Model and calibration dates are Frappe's to fetch from the Metal Detector as it validates the link (see the schema above); the controller only puts back an amendment's. The logs made before 2026-11 that keep the earlier layout (`belongs_to_earlier_layout`: submitted or cancelled, or a draft holding a calibration certificate, a corrective action or a test's sensitivity setting or remarks; marked by the patch `isnack.patches.v1_0.qc_metal_detector_log_earlier_layout`, which also marks a log deleted before in its Deleted Document when it keeps the earlier layout or is not all a log made since must be (`finished_the_new_way`: no Metal Detector ID, a test without a Test Time or Test Piece Type), which a restore could not fill in, and forgets the Tests grid columns a user had chosen when they show the sensitivity setting or remarks: `earlier_layout.forget_grid_columns(…, fieldnames)`) keep them, and can correct them on a draft or an amendment. A log made since records none. Until the migrate adds the mark, every log is treated as one made before. There is no `before_print`: a log made since cannot hold them, and the standard print leaves out a field without a value.

The patch `isnack.patches.v1_0.metal_detectors_from_qc_logs` (run before it) makes a Metal Detector of each Metal Detector ID the logs name, and the logs deleted before (their Deleted Documents: a restore needs the detector): an ID differing only in case or surrounding spaces is one detector, named as the newest log spells it; it takes the Make/Model, the calibration dates (the two together) and the certificate of the newest log holding each, a cancelled log only when no other does, a deleted one only when no log there is does. The database matches a log's ID to its detector whatever its case or trailing spaces, but not a leading space, tab or line break: a log whose ID has one is given the detector's name (a plain update, `modified` left alone), and so is a log deleted before, in its Deleted Document, so a restore leads to its detector. The other logs are left as they are. An ID that cannot name a record (one with `<` or `>`) is reported in the migrate output and left out; a draft naming it is saved again with a detector picked. It makes the detectors without their Factory Lines (`ignore_mandatory`), which come next:

The patch `isnack.patches.v1_0.metal_detector_lines_from_qc_logs` gives each Metal Detector with no Factory Lines yet the lines of the logs that name it, submitted or draft, and deleted before (a restore needs it), so each log made before can still be saved and restored. A cancelled log gives none: one cancelled for its line or detector would put the detector on a line it was logged on by mistake, and an amendment keeping the detector and line it amends needs none (`check_detector_on_line` lets it). The database matches a log's ID and line to the detector and line whatever their case or trailing spaces; a row takes the line's own spelling. A detector or line that is not there is left out, and a detector no log names is left without lines: it is offered on no line until one is added (it cannot be saved without one). The rows are inserted as they are (`db_insert`), leaving the detector's `modified` alone.

---

### QCI — QC Weight Check

**File:** `isnack/isnack/doctype/qc_weight_check/qc_weight_check.py`

```
validate():
    earlier_layout.keep_mark(self)      # a form loaded before the migrate sends no mark
    earlier = earlier_layout.in_earlier_layout(self)
    if not earlier:
        remarks = None if only whitespace
        if tu1_limit or tu2_limit or remarks or any sample's tare_weight:
            throw "This page is out of date"   # a form, Duplicate or hub page from before
        if any sample has no Status:
            throw "Status is required in Samples (row …). If the Samples table has
                   no Status column, this page is out of date: reload it …"
        if nominal_weight <= 0:             # reqd lets the 0 of a blank through
            throw "Nominal Weight (g) must be more than 0."
        if any sample's sample_no <= 0, then any sample's gross_weight <= 0:
            throw "<Sample No | Gross Weight (g)> must be more than 0 in Samples (row …)."

    tu1 = tu1_limit or 0
    tu2 = tu2_limit or 0
    for s in samples:
        s.net_weight = (s.gross_weight or 0) - (s.tare_weight or 0)
        s.in_range   = (1 if s.net_weight >= tu2 else 0) if earlier else 0

    net_weights = [s.net_weight for s in samples]
    sample_count   = len(net_weights)
    if net_weights:
        average_weight = mean(net_weights)
        variance       = mean((w - average_weight)² for w in net_weights)  # population variance
        std_deviation  = sqrt(variance)
        min_weight     = min(net_weights)
        max_weight     = max(net_weights)
    else:
        all summary fields = 0
    if earlier:                         # the Overall Status entered stands
        tu1_failures = count(w for w in net_weights if w < tu1)
        tu2_failures = count(w for w in net_weights if w < tu2)
    else:
        tu1_failures = tu2_failures = 0
        overall_status = "Fail" if any sample's Status is Fail
                         else "Pass" if every one is Pass else ""

before_submit():
    if no samples:                      # the hub asks for one before it saves
        throw "Add at least one row in Samples to submit the check."

before_print():
    if not earlier_layout:              # print ignores depends_on
        blank EARLIER_FIELDS and each sample's EARLIER_SAMPLE_FIELDS (in memory)

on_trash():
    if not earlier_layout and not finished_the_new_way(self, samples):
        earlier_layout = 1              # an unmarked draft from before: a sample with no Status,
                                        # a Nominal Weight, Sample No or Gross Weight of 0 or less;
                                        # in memory: its Deleted Document can be restored
```

The checks made before 2026-11 that keep the earlier layout (`belongs_to_earlier_layout`: submitted or cancelled, or a draft holding a TU limit, an Overall Status, Remarks or a tare; marked by the patch `isnack.patches.v1_0.qc_weight_check_earlier_layout`, which also marks a check deleted before in its Deleted Document when it keeps the earlier layout or is not all a check made since must be (`finished_the_new_way`: a sample with no Status, a Nominal Weight, Sample No or Gross Weight of 0 or less), which a restore could not fill in, and forgets the Samples grid columns users had chosen, which would keep Status and Remarks out of the grid: `earlier_layout.forget_grid_columns`) keep their limits, tares and the Overall Status they were given, reckoned as before. Each sample's Status is mandatory on a check made since, not on one made before: a draft finished now, an amendment or a restore of one keeps the Overall Status it was given. The doctype cannot say that per check, so the Status field is not `reqd`; the controller requires it, and the form script `qc_weight_check.js` marks the column required on the checks that need it (`grid.toggle_reqd`). Sample No, Gross Weight and Nominal Weight are `reqd` on every check, as they always existed (a blank in a check made before reads 0, which the mandatory check lets through); the controller requires them more than 0 on a check made since only, so a check made before is kept, amended and restored as it was.

---

## 9. Hooks & Doc Events

The `doc_events` section in `isnack/hooks.py` previously wired all 9 QC DocTypes to an `on_qc_record_submit` function that updated Lab Checkpoint timestamps. This hook has been removed along with the Lab Checkpoint workflow. Since 2026-11 it holds one entry per record type a Quality Hub tab restricts the line of (QC Puffs Extruder Record, QC Rice Extruder Record, QC Frying Line Record, QC Tasting Record, QC Packaging Check, QC Weight Check, QC Metal Detector Log): `validate` → `isnack.isnack.doctype.quality_hub_settings.quality_hub_settings.check_factory_line` ([Quality Hub Settings](#quality-hub-settings)). Frappe runs it after the record's own `validate`. All nine record types also have `before_validate` handlers (2026-11). First `isnack.utils.qc_import.check_import`: in a Data Import (`frappe.flags.in_import`) it refuses what the file must give and does not (a reading's or test's time, as hh:mm; a tasting score as a number from 0 to 1; no field retired since 2026-11 on a record made since; no second QC Receiving Record of a delivery; see *What an import must give* in [Section 1](#1-overview)). Then, on the eight that name an Operator (all but the retired QCE), `isnack.utils.qc_operator.check_operator`: it requires the Operator on a record made since, refuses an Employee newly picked who is not Active, and sets Operator Name to the Employee's name (or, with no Operator on a record made before, back to the name typed on it). In a Data Import, a new record that comes with an Operator Name but no Operator first takes the Employee of that name, whatever their status, and is refused when no Employee has it or several have it; the Operator of a new record imported may be an Employee who has left since, but not one who had left by its Record Date (whatever their status now); and an import updating a record does not change its Operator Name. Frappe runs `before_validate` even when a save skips validation (`flags.ignore_validate`); then, as with `flags.ignore_mandatory` for the Operator, neither refuses anything.

`app_include_js` loads `/assets/isnack/js/quality_hub_lines.js?v=<the start of its md5>` on every desk page (the version makes browsers fetch the file again when it changes, as assets are cached for a year; `test_quality_hub_settings` fails until it is bumped with the file): `isnack.quality_hub_lines`, the lines of each restricted record type (`load()`, from `get_factory_lines`) and the query offering them (`query(doctypes, df)`, the line when there is just one: `only_line(doctypes)`); the Work Order's query (`work_order_query(line, df)`: `[["Work Order", "custom_factory_line", "=", line], ["Work Order", "docstatus", "<", 2]]`, "Work Orders on <line>" under them, or every Work Order before a line is picked) and the Product Item's (`product_query(work_order, df)`: `[["Item", "name", "=", <the item the Work Order makes>]]`, once `work_order_details` has read it, else `[["Item", "item_group", "=", "Finished Goods"]]`); and what a change of line or Work Order does (`line_changed(record)`, `work_order_changed(record)`: a Work Order on another line is taken off with an alert, once the Work Order is read and only if neither field changed meanwhile; another fills in the Product Item). The Quality Hub's dialogs use the same (`restrict_factory_line`, `restrict_work_order`). For each of those record types it adds form handlers: `setup` sets the Factory Line's, the Work Order's and (QCB–QCD) the Product Item's queries, `onload` fills in a new record's only line and reads its Work Order's item, and `factory_line` and `work_order` call `line_changed` and `work_order_changed` on the document open (`form_record(frm)`).

`app_include_js` also loads `/assets/isnack/js/quality_hub_operator.js?v=<the start of its md5>` (2026-11; `test_qc_operator` checks the version): `isnack.quality_hub_operator`, the Operator's query (`query()`: `{query: "isnack.utils.qc_operator.search_operators"}`), each Employee's name and status read once (`details(employee)`, from `get_operator`), whether a record was made before the Operator (`made_before(doc)`: no Operator, a typed name, and saved or an amendment), and what a change of Operator does (`operator_changed(record)`: Operator Name shows the Employee's name; an Employee who is not Active, typed in full, is taken off with an alert; emptied, the name typed on a record made before comes back). For each of the eight record types it adds form handlers: `setup` sets the query and, through `prepare(doctype)`, puts the lookup (`get_query`, `ignore_link_validation`, `only_select`) on the doctype's own field, from which Frappe copies each document's (Frappe checks a link a new record comes with, from a list's filter or the address, before the form's `refresh`); `refresh` sets the same on the document's field, hides the open arrow from a user who may not read Employee, makes the Operator required unless the record was made before (`typed_name(frm)`, decided on the document as loaded or saved, not as edited since), and looks up the name of a new record that comes with an Operator (a duplicate); `operator` calls `operator_changed`. Its `frappe.listview_settings[doctype].onload` calls `prepare` too, so the list's and Report View's filters on Operator use the same lookup. An Employee who cannot be looked up now (the request failed, or the desk is offline) is left as picked for the server to check on save; only Active answers are remembered, and the value shown in an alert is escaped. The Quality Hub's dialogs use the same (`restrict_operator`).

---

## 10. API Endpoints

All endpoints are decorated with `@frappe.whitelist()`, and defined in `isnack/isnack/page/quality_hub/quality_hub.py` but for `get_factory_lines` and `get_work_order_details`, in the settings' controller (`quality_hub_settings.py`), and `search_operators` and `get_operator`, in `isnack/utils/qc_operator.py`.

---

### `get_quality_hub_data()`

**Method:** `isnack.isnack.page.quality_hub.quality_hub.get_quality_hub_data`  
**Purpose:** Returns all data needed to populate the Live Monitor tab on page load or on poll.

**Returns:**
```json
{
  "stats": {
    "completed_last_hour": <int>,
    "open_non_conformances": <int>
  },
  "recent_out_of_range": [ { "quality_inspection", "specification", "status",
                              "item_code", "inspection_type", "reference_type",
                              "reference_name", "ts" }, ... ]
}
```

**Helper functions:**
- `_get_completed_last_hour(now)` — counts submitted Quality Inspections modified in the last hour
- `_get_open_non_conformances()` — counts open Non Conformance records (returns 0 if the table does not exist)
- `_get_recent_out_of_range_readings(limit=10, hours=4)` — fetches rejected Quality Inspection Readings from the last 4 hours (returns `[]` if the table does not exist)

---

### `get_qc_record_summary(date=None)`

**Method:** `isnack.isnack.page.quality_hub.quality_hub.get_qc_record_summary`  
**Arguments:** `date` (optional, defaults to today)  
**Purpose:** Returns per-DocType record counts for the given date, used to render the QC summary grid on the Live Monitor tab. Retired types (QCE) are left out.

**Returns:**
```json
{
  "QCA": { "doctype": "QC Receiving Record",      "total": 3, "submitted": 2, "draft": 1, "hidden": false },
  "QCB": { "doctype": "QC Puffs Extruder Record", "total": 0, "submitted": 0, "draft": 0, "hidden": false },
  "QCF": { "doctype": "QC Tasting Record",        "total": 0, "submitted": 0, "draft": 0, "hidden": true },
  ...
}
```

Counts come from one `frappe.get_list` per DocType, so User Permissions apply. `hidden: true` (all counts 0) marks a DocType the user may not read; the card shows "—". A DocType whose table does not exist yet counts 0 with `hidden: false`.

---

### `get_completion_matrix(date=None)`

**Method:** `isnack.isnack.page.quality_hub.quality_hub.get_completion_matrix`  
**Arguments:** `date` (optional, defaults to today)  
**Purpose:** Returns a shift × DocType matrix showing completion status for the Reports & Trends tab. Retired types (QCE) are left out of `matrix` and `doctypes`.

**Returns:**
```json
{
  "matrix": {
    "Morning":   { "QCA": "submitted", "QCB": "draft", "QCC": "not_started", ... },
    "Afternoon": { ... },
    "Night":     { ... }
  },
  "date": "2026-04-15",
  "doctypes": { "QCA": "QC Receiving Record", "QCB": "QC Puffs Extruder Record", ... }
}
```

**Cell values:** `"submitted"` | `"draft"` | `"not_started"` | `"hidden"` (a DocType the user may not read; shown as "·")

---

### `get_qc_records(doctype, filters=None, limit=20)`

**Method:** `isnack.isnack.page.quality_hub.quality_hub.get_qc_records`  
**Arguments:**  
- `doctype` — must be a value in `QC_DOCTYPES`; throws `frappe.throw` otherwise  
- `filters` — JSON string or dict of filter conditions (optional)  
- `limit` — integer row cap (default 20, UI passes 50)

**Purpose:** Generic record fetcher used by every record-list tab. Returns the base common fields plus `supplier`, `item_code`, `batch_no`, `overall_status` and `modified`, with fields not present on the specific DocType silently dropped. Requires read permission on the DocType and reads with `frappe.get_list`, so the user's User Permissions apply. `get_qc_record_summary` and `get_completion_matrix` count the same way: a DocType the user may not read comes back `hidden` (a "—" card, a "·" matrix cell) instead of with counts.

**Note:** `frappe.db.table_exists()` takes the DocType name and adds the `tab` prefix itself. `get_qc_records`, `get_qc_record_summary` and `get_completion_matrix` used to pass `tab<DocType>`, which never matched, so every list, summary card and matrix cell came back empty; fixed 2026-10.

**Returns:** List of record dicts ordered by `record_date desc, modified desc`.

---

### `get_packaging_and_weight_records(filters=None, limit=20)`

**Method:** `isnack.isnack.page.quality_hub.quality_hub.get_packaging_and_weight_records`  
**Arguments:**  
- `filters` — those of `get_qc_records`, plus `check`: `QC Packaging Check` or `QC Weight Check`, to list that one alone (any other value throws)  
- `limit` — integer row cap (default 20, UI passes 50)

**Purpose:** The Packaging and Weight Checks tab's list (since 2026-11; until then a pill for each, read with `get_qc_records`). Reads each doctype with `get_qc_records` (the newest `limit` of each) and merges them, so permissions and User Permissions apply as they do to every list. With no `check`, a doctype the user may not read is left out, and a user who may read neither is refused; with a `check`, that doctype is refused as its own list was.

**Returns:** The newest `limit` records of both, ordered by `record_date desc, modified desc` as each list is, each with its `doctype`.

---

### `get_factory_lines()`

**Method:** `isnack.isnack.doctype.quality_hub_settings.quality_hub_settings.get_factory_lines` (in the settings' controller, not `quality_hub.py`)  
**Arguments:** none

**Purpose:** The factory lines each Quality Hub tab records on (since 2026-11), for the hub's dialogs and the records' forms (`quality_hub_lines.js`). Read whoever the user: a Quality Controller who may not read the settings is still offered the lines.

**Returns:** `{doctype: [line, ...]}` for each restricted record type; an empty list where the tab is given none (any line).


---

### `get_work_order_details(work_order)`

**Method:** `isnack.isnack.doctype.quality_hub_settings.quality_hub_settings.get_work_order_details`  
**Arguments:** `work_order`

**Purpose:** The line a Work Order is planned on and the item it makes (since 2026-11), for the pickers: a Work Order on another line than the record's is taken off, and its item fills in a Process record's Product Item.

**Returns:** `{factory_line, production_item}`; `{}` for a Work Order there is not, or one the user may neither select nor read.

---

### `search_operators(doctype, txt, searchfield, start, page_len, filters)`

**Method:** `isnack.utils.qc_operator.search_operators` (a Link query)  
**Purpose:** The Operator's search (since 2026-11): the Active Employees whose ID or name holds `txt`, by name, for users who hold no permission on Employee.

**Returns:** `[[name, employee_name], ...]` (dicts with `as_dict`); `[]` for a user who may neither create nor change any record type that names an Operator.

---

### `get_operator(employee)`

**Method:** `isnack.utils.qc_operator.get_operator`  
**Purpose:** An Employee's name and status (since 2026-11), for the Operator Name shown as the Operator is picked; an Employee who is not Active is taken off.

**Returns:** `{employee, employee_name, status}`; `{}` for an Employee there is not, or a user who may not record checks.

---

## 11. Quality Hub UI Architecture

**Page registration:** `isnack/isnack/page/quality-hub/`  
**Entry point:** `frappe.pages["quality-hub"].on_page_load = function(wrapper) { ... }`  
**Class:** `isnack.quality_hub.QualityHub`

### Constructor Sequence

```
new QualityHub(wrapper)
  ├── frappe.ui.make_app_page(...)   // Frappe page scaffold
  ├── isnack.quality_hub_lines.load() // Each tab's factory lines (Quality Hub Settings)
  ├── make_layout()                  // Render full tab HTML into DOM
  ├── bind_tabs()                    // Attach click/filter/sub-nav events
  ├── start_clock()                  // Live clock (updates every 30 s)
  ├── refresh_data(false)            // Initial data load for Live Monitor
  ├── start_polling()                // 30-second poll (monitor tab only)
  └── show_tab("monitor")            // Activate first tab
```

### Tab Structure

| Tab Button Label | `data-tab` | DocType(s) | Sub-Nav Pills |
|---|---|---|---|
| Live Monitor | `monitor` | Quality Inspection Readings (out-of-range panel) | — |
| Receiving (QCA) | `receiving` | QC Receiving Record | — |
| Process (QCB–QCD) | `process` | QC Puffs / Rice / Frying | Puffs · Rice · Frying |
| Tasting (QCF) | `tasting` | QC Tasting Record | — |
| Packaging and Weight Checks (QCG/QCI) | `pkg_weight` | QC Packaging Check / QC Weight Check | — (one list; Packaging · Weight until 2026-11) |
| CCP & Metal (QCH) | `metal` | QC Metal Detector Log | — |
| Reports & Trends | `reports` | (matrix — the 8 types in use) | — |

### Factory Lines by Tab

Each New dialog's **Factory Line** offers the lines [Quality Hub Settings](#quality-hub-settings) gives its tab (`restrict_factory_line(dialog, doctypes)`, since 2026-11): the Link's `get_query` is `[["Factory Line", "name", "in", <lines>]]`, with "The lines Quality Hub Settings gives this tab" under the lines offered (`df.filter_description`), or nothing, and so every line with no note, when the tab is given none. When the tab has just one line, the dialog fills it in. The lines are those `isnack.quality_hub_lines` loaded as the hub opened, loaded again as each dialog opens. The Packaging and Weight form offers a line both its checks may be on (the lines their tab shares). The records' desk forms do the same (`quality_hub_lines.js`), and the records refuse another line (`check_factory_line`). A desk loaded before the settings came (no `isnack.quality_hub_lines`) offers every line.

### Work Orders by Line

Each New dialog with a Work Order, the Packaging and Weight form included, sets it up with `restrict_work_order(dialog)` (since 2026-11), right after `restrict_factory_line` and before the metal detector's own wrapping of the line's `onchange`. The Work Order's `get_query` is `isnack.quality_hub_lines.work_order_query(<the line picked>, df)`: the Work Orders on the line, none cancelled; every Work Order before a line is picked. On the Process dialogs, the Product Item's is `product_query(<the Work Order picked>, df)` (their fields no longer carry `link_filters`, which Frappe would put in its place). The line's and the Work Order's `df.onchange` are wrapped, the line's own still running first: a Work Order on another line than the new one is taken off with an alert, and a Work Order picked fills in the Product Item with the item it makes (`line_changed`, `work_order_changed`, given the dialog's fields). They read each field's value as last set (the control's `value`), not the box's text, so a line half typed in is not taken for a line. A dialog's Link runs its `onchange` again for the value it holds when its box is left (it has no document to compare with): that is not taken for a change (`value === last_value`), so a Product Item just emptied stays empty. A dialog saved and closed is left as it was (`dialog.display`), with no alert. A desk whose `quality_hub_lines.js` predates the rule (no `work_order_query`) leaves the Work Order as it was.

### The Operator

Each New dialog, the Packaging and Weight form included, sets up its **Operator** with `restrict_operator(dialog)` (since 2026-11), right after `restrict_work_order`. The dialogs' Operator is a Link to Employee with `ignore_link_validation` (Frappe's check needs Employee permission; the server checks the link on save), `only_select` and `ignore_user_permissions`, followed by a read-only Operator Name. Its `get_query` is `isnack.quality_hub_operator.query()`; its `onchange` is wrapped, the dialog's own kept, to call `operator_changed` on a real change only (a dialog's Link runs `onchange` again for the value it holds when its box is left), with nothing done once the dialog is closed. It compares the Operator with the one it last looked up, not with the Link's `last_value`: with no link check, a dialog's Link may already hold a value typed in when `onchange` runs. A box emptied by hand after a pick is set empty, which a dialog's Link does not see by itself, and the Link's open arrow is hidden from a user who may not read Employee (`hide_open_link`). `_new_qc_record` refuses an Operator Name sent with no Operator, from a page loaded before: "This page is out of date. Reload it and enter the record again."

### Per-Tab Components

**Live Monitor (`monitor`)**
- 4-card stat grid: Overdue readings · Due in next 5 min · Completed last hour · Open non-conformances
- 8-card QC summary grid (one card per type in use, QCA–QCI without the retired QCE, coloured green/amber by submission status)
- Two-column panel layout:
  - Left: "Due & Overdue Checkpoints" datatable (red badge count)
  - Right: "Recent Out-of-Range Readings" datatable (amber badge count)

**Receiving (`receiving`)**
- Filter bar: date · supplier · docstatus · Filter button · New Record button
- Single panel with record list datatable

**Process (`process`)**
- Sub-nav pills: Puffs Extruder (QCB) · Rice Extruder (QCC) · Frying Line (QCD)
- The New Record dialog for QCB and QCC has two row editors, each in its own section: **Readings** (at least one row) and **Oven / Slurry Readings** (optional; the same columns on both since 2026-11, when QCB's **Oven Readings** took the slurry's). A dialog config lists extra tables under `extra_child_tables`; `create_qc_record` takes them through `optional_child_tables` in `QC_DIALOG_CONFIG`. QCB's are `puffs_readings` and `puffs_oven_readings`; QCC's are `rice_readings` and `rice_oven_readings`. QCC's Readings record **Moisture Rice Content (%)**, QCB's **Moisture Corn Content (%)**
- Filter bar: date · work_order · factory_line · docstatus · Filter button · New Record button
- Single panel with record list datatable
- Active sub-nav pill updates `active_process_sub` and re-loads records

**Tasting (`tasting`)**
- Filter bar: date · factory_line · docstatus · Filter button · New Record button
- Single panel with record list datatable
- The New Record dialog: Batch No is mandatory, in the **Product** section; the Scores toolbar shows what the stars mean (1 Poor · 2 Fair · 3 Good · 4 Very good · 5 Excellent, `child_legend`), and each taster's **Overall %** is worked out as the scores are picked (a column with `compute`, not sent: the record works it out on save)

**Packaging and Weight Checks (`pkg_weight`)** (Pkg & Weight until 2026-11)
- One list of both checks, newest first (`get_packaging_and_weight_records`), with a **Check** column (Packaging Check (QCG) or Weight Check (QCI), the form's labels); each row opens its own record. Until 2026-11 the tab had a pill for each, Packaging Checks (QCG) · Weight Checks (QCI), and showed their lists one at a time
- The filter bar's **Check** (All Checks · Packaging Checks (QCG) · Weight Checks (QCI)) lists one alone, as a pill did. The tab is listed as its filter bar shows it, also on coming back to it (as a pill kept its choice); Receiving, Process and Tasting list unfiltered when opened, and CCP & Metal lists today's logs
- **New Packaging and Weight Check** (since 2026-11; it replaced the New Record button, which opened the active pill's dialog) opens one form for both records (`PACKAGING_AND_WEIGHT` in `quality_hub.js`, `open_packaging_and_weight`). The two records stay two doctypes, one per paper sheet; only the entry is merged:
  - Two ticks at the top, **Packaging Check (QCG)** and **Weight Check (QCI)**, both ticked. Unticking one hides its sections and stops asking for its required fields (a dialog asks for a required field even hidden), so the form also records either check on its own. One of the two stays ticked; a record type the user may not create is unticked and cannot be ticked.
  - The Record Details once (the first section of both dialogs below, the same fields: a test pins it), written to both records.
  - Then each record's own fields, taken from its dialog config, under the headings **Packaging Check (QCG)** (with the QCG-007 instruction; Qty Wasted and Remarks in the same section) and **Weight Check (QCI)**, then the Samples editor. The packaging Remarks go to the packaging check only: the weight check's record-level Remarks is retired.
  - Until 2026-11, picking the Work Order filled the weight check's Item Code with the Work Order's product (`get_work_order_product`, since removed) and Batch No offered that item's batches; the weight check names neither since.
  - **Save Draft** and **Save & Submit** call `create_qc_records(details, records, submit)`: each record is built as `create_qc_record` builds it (`_new_qc_record`), all are inserted before any is submitted, and a failure keeps none (the request rolls back, and so does the `create_qc_records` savepoint). The alert names both records; a Check filter that would hide a saved check is cleared (the Date, Work Order and Status filters stay, and can still hide them).
  - A dialog draws a field it has no document for as `value || null`, which loses a 0, and Frappe redraws a required field holding 0 as it reads the dialog. So a dialog's values are read once (on Save Draft, those its button already read), a required 0 is drawn again after the read (`read_dialog_values`), and the tick keeps a 0 when it changes a field's `reqd` (`set_dialog_df_property`): a Qty Wasted of 0 saves.
- The Packaging Check dialog: the four checks (**Packet Label Correct (Best Before / Batch Ref)** among them) and a mandatory **Qty Wasted**; no film or reconciliation since 2026-11. A page loaded before that change still sends them: the check refuses them with "This page is out of date" (`QCPackagingCheck.validate`)
- The Weight Check dialog: Record Details, Product (the Nominal Weight, required; Item Code and Batch No until 2026-11; Product & Limits until the TU limits came off, 2026-11) and the Samples editor (Sample No, Gross Weight, Status, Remarks); no Outcome section. Sample No, Gross Weight and Status are required columns (`reqd` on a child field: the header is marked and Save names the rows without one, `missing_child_values`), and Sample No and Gross Weight must be more than 0 (`positive`: Save names the rows, `not_positive_child_values`, numbered as the editor shows them; Sample No's input starts at 1). A save needs a sample, Save Draft as well as Save & Submit (`min_rows: 1`). A page loaded before the change still sends the TU limits, Remarks or tares: the check refuses them with "This page is out of date" (`QCWeightCheck.validate`)
- The two dialogs above are no longer opened from the tab: the combined form is built from them
- Filter bar: date · work_order · check · docstatus · Filter button · New Packaging and Weight Check button
- Single panel with record list datatable

**CCP & Metal (`metal`)**
- CCP alert banner (`.qh-ccp-alert`):
  - Green (`.qh-ccp-alert-ok`) when today's records exist
  - Amber warning (`.qh-ccp-alert-warn`) when no records for today
- Filter bar: date · metal_detector_id · docstatus · Filter button · New Record button
- Single panel with record list datatable
- The New Record dialog: **Metal Detector ID**, required (since 2026-11), picks a Metal Detector (a Link; a new one can be made from it, in a quick entry over the dialog), which fills **Make/Model**, **Last Calibration Date** and **Next Calibration Date** (read-only, `fetch_from`, as on the form); no Calibration Certificate, and no Corrective Action, since 2026-11. The Tests editor has Test Time, Test Piece Type, Test Piece Size (mm) and Detected (Pass); no Sensitivity Setting or Remarks since 2026-11. A page loaded before that change still sends them: the log refuses them with "This page is out of date" (`QCMetalDetectorLog.validate`). Test Time and Test Piece Type are required columns since 2026-11 (`reqd` on a child field: the header is marked and Save names the rows without them, `missing_child_values`); a test that arrives without them (from a page loaded before) is refused by the log, which names the rows (`require_detector_and_tests`)
- The Metal Detector ID offers the detectors used on the Factory Line picked (every one before a line is picked, with no filter, so no empty "Filters applied for" row under them: `isnack.quality_hub.metal_detectors_on_line`, set as the Link's `get_query` by `setup_metal_detector_dialog`). A detector picked that is not used on a line picked afterwards is taken off, with its details, and the user is told (`drop_detector_off_line`; an answer that comes after the line or detector changed again is left to that change). The desk form does the same (`qc_metal_detector_log.js`)
- Test Piece Size starts at 0.2 in each new row (`default` on a child field, `make_empty_child_row`). A row holding nothing but its defaults is not a test (`child_row_entered`): it is not saved, and Save asks for a test when there is no other
- Emptying the Metal Detector ID empties Make/Model and the dates. A dialog's Link has no document and compares what is typed with the value before last, so emptying it after a first pick goes unseen (Frappe v15): the dialog sets a Link that fields are fetched from empty when it is left empty (`empty_cleared_links`, also on the tasting's Batch No). A detector made from the Link's **Create a new Metal Detector** is picked and its details shown; Frappe's quick entry sets a copy of the Link (`deep_clone`), so the dialog's own values for them stay blank, and the log takes them from the detector when it is saved

**Reports & Trends (`reports`)**
- Date-picker + Refresh button → calls `get_completion_matrix(date)` 
- Completion matrix rendered as `<table class="qh-table qh-matrix">` (shift rows × code columns)
  - ✅ = submitted, 🟡 = draft, — = not started
- Quick Links row with direct `#List/` links to the 8 DocType list views in use, the Metal Detectors (since 2026-11), and the Quality Explorer page (see `docs/quality-explorer.md`); and to the Quality Hub Settings form (`data-form`, since 2026-11), for a user who may read it

### Record List Datatable

All record lists (`render_record_list`) render the same columns, except that the Receiving list shows Supplier, Item and Batch where the others show Line, and the Packaging and Weight list adds a Check column:

| Column | Key | Rendering |
|---|---|---|
| Name | `name` | Hyperlink to the record's form, `frappe.utils.get_form_link(doctype, name)` (`/app/<doctype-slug>/<name>`). Until 2026-11 a v1 `#Form/<doctype>/<name>` link, which Frappe v15 opens as "Page #Form not found" |
| Check | `doctype` | The form's label, Packaging Check (QCG) or Weight Check (QCI) (Packaging and Weight only) |
| Date | `record_date` | Plain text |
| Shift | `shift` | Plain text |
| Line | `factory_line` | Plain text (not on Receiving) |
| Supplier · Item · Batch | `supplier` · `item_code` · `batch_no` | Plain text (Receiving only) |
| Operator | `operator_name` | Plain text: the Employee's name (since 2026-11), or the name typed on a record made before |
| Result | `overall_status` | Badge: green (Pass/Accepted), red (Fail/Rejected), amber (other) |
| Status | `docstatus` | Badge: amber (Draft), green (Submitted), red (Cancelled) |

Clicking a row navigates to the form via `frappe.set_route("Form", doctype, name)`, with the row's own doctype (`data-doctype`: on the Packaging and Weight list, each record's; on the others, the list's).

### CSS Class Naming Convention (`.qh-*`)

All styles live in `isnack/isnack/page/quality_hub/quality_hub.css`. The namespace is `.qh-`:

| Class | Purpose |
|---|---|
| `.quality-hub-wrapper` | Root container — light neutral background (#f3f4f6) |
| `.qh-header` / `.qh-header-title` / `.qh-header-subtitle` | Page header layout |
| `.qh-pill` / `.qh-pill-live` | Status pills (e.g. "Live monitoring" indicator) |
| `.qh-dot` / `.qh-blink` | Animated green dot in header |
| `.qh-stat-grid` | 4-column responsive stat card grid |
| `.qh-qc-summary-grid` | 9-column QC record summary grid (extends `.qh-stat-grid`) |
| `.qh-card` / `.qh-card-label` / `.qh-card-value` | Stat card components |
| `.qh-card-success` / `.qh-card-warn` | Card colour variants (green/amber) |
| `.qh-layout` | Two-column panel grid (2.1fr + 1.4fr) |
| `.qh-panel` / `.qh-panel-header` / `.qh-panel-title` | White card panel |
| `.qh-badge` / `.qh-badge-red` / `.qh-badge-amber` / `.qh-badge-emerald` | Status badges |
| `.qh-tabs` | Tab bar (horizontal flex, bottom border) |
| `.qh-tab` / `.qh-tab-active` | Individual tab buttons (blue underline when active) |
| `.qh-sub-nav` | Sub-navigation pill row |
| `.qh-pill-nav` / `.qh-pill-active` | Sub-nav pill buttons (solid blue when active) |
| `.qh-filter-bar` | Horizontal filter inputs + buttons row |
| `.qh-filter-input` | Width-constrained form inputs (140–200px) |
| `.qh-table` | QC record datatable |
| `.qh-row-overdue` / `.qh-row-due-now` | Coloured checkpoint rows (red / blue) |
| `.qh-chip` / `.qh-chip-out-of-range` | Small inline chips |
| `.qh-ccp-alert` / `.qh-ccp-alert-ok` / `.qh-ccp-alert-warn` | CCP status banner |
| `.qh-matrix` / `.qh-matrix-cell` / `.qh-matrix-submitted` / `.qh-matrix-draft` / `.qh-matrix-not-started` | Completion matrix |
| `.qh-quick-links` | Flex row of quick-link buttons |

### Polling & Refresh Mechanism

```
start_polling()
  └── setInterval(30 000 ms)
        └── if active_tab === "monitor"
              └── refresh_data(true)
                    ├── frappe.call(get_quality_hub_data)  → update_ui()
                    └── frappe.call(get_qc_record_summary) → render_qc_summary_cards()

start_clock()
  └── setInterval(30 000 ms)
        └── update current-time display
```

The Live Monitor polls automatically every 30 seconds. Other tabs load data lazily on first activation (via `show_tab()`) and can be re-filtered manually.

---

## 12. Data Flow Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                         Quality Control Workflow                             │
└──────────────────────────────────────────────────────────────────────────────┘

Paper Sheet                   Digital Entry
(factory floor)               (browser)
     │                             │
     │   QC personnel opens        │
     ▼   Quality Hub page          ▼
 [Paper QC   ]            [Quality Hub Page]
 [Sheet (QCA-]            [  frappe.pages  ]
 [QCI format)]            ["quality-hub"  ]
     │                             │
     │  Enters data manually       │  Tab selected (e.g. "Receiving (QCA)")
     ▼  into DocType form          ▼
 [Field Values]           [New Record button → frappe.new_doc("QC Receiving Record")]
     │                             │
     │                             ▼
     │                    [DocType Form (standard Frappe)]
     │                             │
     │  validate() fires           ▼
     │  on every Save     [validate() in controller .py]
     │                    - Recalculates derived fields
     │                    - e.g. avg_moisture, avg_overall,
     │                      variance, all_tests_passed …
     │                             │
     │  User clicks Submit         ▼
     │                    [Frappe Submit (docstatus → 1)]
     │                             │
     ▼                             ▼
 [Paper filed]            [Live Monitor auto-poll (30 s)]
                                   │
                                   ▼
                          [get_quality_hub_data()]
                          - Returns stat cards data
                          - Returns out-of-range readings
                                   │
                                   ▼
                          [Quality Hub Live Monitor]
                          - Stat cards update
                          - Out-of-range panel refreshes
```

---

## 13. File Map

```
isnack/
├── hooks.py                                  ← doc_events: each restricted QC record's Factory Line (check_factory_line), each QC record's Operator (check_operator); app_include_js
│
├── public/js/
│   ├── quality_hub_lines.js                  ← each tab's factory lines, and each line's Work Orders and their items, on the hub's dialogs and the records' forms
│   └── quality_hub_operator.js               ← the Operator (an Employee) and its name, on the hub's dialogs and the records' forms
│
├── utils/
│   ├── earlier_layout.py                     ← QCG/QCH/QCI earlier layout: the mark, kept; the patches' marking; grid columns forgotten
│   ├── earlier_readings.py                   ← QCB/QCC earlier tables: no new rows, print, averages
│   ├── qc_import.py                          ← in a Data Import, what the file must give: check_import
│   ├── qc_operator.py                        ← the Operator: search and name without Employee permission; check_operator
│   ├── test_qc_import.py
│   ├── test_qc_operator.py
│   └── test_earlier_readings.py
│
└── isnack/
    ├── page/
    │   └── quality_hub/
    │       ├── quality_hub.js                ← Full UI (QualityHub class, 7 tabs)
    │       ├── quality_hub.py                ← API endpoints (whitelisted methods)
    │       ├── quality_hub.css               ← .qh-* CSS classes
    │       └── quality_hub.json              ← Page definition
    │
    └── doctype/
        │
        ├── qc_receiving_record/              ── QCA
        │   ├── qc_receiving_record.json
        │   ├── qc_receiving_record.py
        │   ├── test_qc_receiving_record.py
        │   └── __init__.py
        │
        ├── qc_puffs_extruder_record/         ── QCB
        │   ├── qc_puffs_extruder_record.js   ── no new rows in the earlier tables
        │   ├── qc_puffs_extruder_record.json
        │   ├── qc_puffs_extruder_record.py
        │   ├── test_qc_puffs_extruder_record.py
        │   └── __init__.py
        │
        ├── qc_rice_extruder_record/          ── QCC
        │   ├── qc_rice_extruder_record.js    ── no new rows in the earlier tables
        │   ├── qc_rice_extruder_record.json
        │   ├── qc_rice_extruder_record.py
        │   ├── test_qc_rice_extruder_record.py
        │   └── __init__.py
        │
        ├── qc_frying_line_record/            ── QCD
        │   ├── qc_frying_line_record.json
        │   ├── qc_frying_line_record.py
        │   ├── test_qc_frying_line_record.py
        │   └── __init__.py
        │
        ├── qc_oven_record/                   ── QCE (retired)
        │   ├── qc_oven_record.json
        │   ├── qc_oven_record.py
        │   ├── test_qc_oven_record.py
        │   └── __init__.py
        │
        ├── qc_tasting_record/                ── QCF
        │   ├── qc_tasting_record.js          ── Overall % as the scores are given
        │   ├── qc_tasting_record.json
        │   ├── qc_tasting_record.py          ── overall_percent(), PASS_THRESHOLD_PERCENT
        │   ├── test_qc_tasting_record.py
        │   ├── test_tasting_scores.py
        │   └── __init__.py
        │
        ├── qc_packaging_check/               ── QCG
        │   ├── qc_packaging_check.json
        │   ├── qc_packaging_check.py
        │   ├── test_packaging_layout.py      ── variance, print, earlier-layout patch
        │   ├── test_qc_packaging_check.py
        │   └── __init__.py
        │
        ├── qc_metal_detector_log/            ── QCH
        │   ├── qc_metal_detector_log.js      ── the Metal Detector ID offers the detectors used on the Factory Line
        │   ├── qc_metal_detector_log.json
        │   ├── qc_metal_detector_log.py
        │   ├── test_metal_detector_layout.py ── retired values refused, earlier layout, the line, the form, the patches, the doctypes
        │   ├── test_qc_metal_detector_log.py
        │   └── __init__.py
        │
        ├── metal_detector/                   ── master (linked from QCH)
        │   ├── metal_detector.json
        │   ├── metal_detector.py
        │   ├── test_metal_detector.py
        │   └── __init__.py
        │
        ├── metal_detector_factory_line/      ── child (Metal Detector's Factory Lines)
        │   ├── metal_detector_factory_line.json
        │   ├── metal_detector_factory_line.py
        │   └── __init__.py
        │
        ├── quality_hub_settings/             ── single: each tab's factory lines
        │   ├── quality_hub_settings.json
        │   ├── quality_hub_settings.py       ── TAB_FIELDS, factory_lines, get_factory_lines, check_factory_line, get_work_order_details
        │   ├── test_quality_hub_settings.py  ── the lines, the check, the Work Order details, the doctypes, the hooks, the script, the Work Orders
        │   └── __init__.py
        │
        ├── quality_hub_factory_line/         ── child (Quality Hub Settings' lines)
        │   ├── quality_hub_factory_line.json
        │   ├── quality_hub_factory_line.py
        │   └── __init__.py
        │
        ├── qc_weight_check/                  ── QCI
        │   ├── qc_weight_check.js            ── marks the samples' Status required on a check made since
        │   ├── qc_weight_check.json
        │   ├── qc_weight_check.py
        │   ├── test_qc_weight_check.py
        │   ├── test_weight_layout.py         ── samples judged, earlier layout, print, patch
        │   └── __init__.py
        │
        ├── qc_extruder_reading/              ── child (QCB, QCC earlier readings)
        │   ├── qc_extruder_reading.json
        │   ├── qc_extruder_reading.py
        │   └── __init__.py
        │
        ├── qc_frying_reading/                ── child (QCD)
        │   ├── qc_frying_reading.json
        │   ├── qc_frying_reading.py
        │   └── __init__.py
        │
        ├── qc_oven_reading/                  ── child (QCB, QCC earlier readings; QCE retired)
        │   ├── qc_oven_reading.json
        │   ├── qc_oven_reading.py            ── average(), oven_averages()
        │   ├── test_oven_averages.py
        │   └── __init__.py
        │
        ├── qc_puffs_extruder_reading/        ── child (QCB)
        │   ├── qc_puffs_extruder_reading.json
        │   ├── qc_puffs_extruder_reading.py
        │   └── __init__.py
        │
        ├── qc_puffs_oven_reading/            ── child (QCB, Oven / Slurry Readings)
        │   ├── qc_puffs_oven_reading.json
        │   ├── qc_puffs_oven_reading.py
        │   └── __init__.py
        │
        ├── qc_rice_extruder_reading/         ── child (QCC)
        │   ├── qc_rice_extruder_reading.json
        │   ├── qc_rice_extruder_reading.py
        │   └── __init__.py
        │
        ├── qc_rice_oven_reading/             ── child (QCC, Oven / Slurry Readings)
        │   ├── qc_rice_oven_reading.json
        │   ├── qc_rice_oven_reading.py
        │   └── __init__.py
        │
        ├── qc_tasting_score/                 ── child (QCF)
        │   ├── qc_tasting_score.json
        │   ├── qc_tasting_score.py
        │   └── __init__.py
        │
        ├── qc_metal_detector_test/           ── child (QCH)
        │   ├── qc_metal_detector_test.json
        │   ├── qc_metal_detector_test.py
        │   └── __init__.py
        │
        ├── qc_weight_sample/                 ── child (QCI)
        │   ├── qc_weight_sample.json
        │   ├── qc_weight_sample.py
        │   └── __init__.py
        │
        ├── factory_line/                     ── referenced by factory_line field
        │   └── factory_line.json
        │
        └── factory_settings/                 ── central factory configuration (Single)
            └── factory_settings.json

docs/
├── QCA-001 Receiving records V2.xlsx         ← original paper sheet source files
├── QCB-002 Puffs Extruder Record.xlsx
├── QCC-003 Rice Extruder Record V2.xlsx
├── QCD-004 Frying Line Record V2.xlsx
├── QCE-005 Oven Record Sheet V2.xlsx
├── QCF-006 Tasting Records V2.xlsx
├── QCG-007 Packaging material checks and reconciliation V2.xlsx
├── QCH-008 Daily Metal Detector Verification Record Sheet V2.xlsx
├── QCI-009 Weight Quality Check Sheet.xlsx
└── QUALITY_HUB_ARCHITECTURE.md              ← this document
```

---

## 14. Integration Points

| QC DocType(s) | Linked DocType | Field | Purpose |
|---|---|---|---|
| QCA | Purchase Receipt | `purchase_receipt` | Ties QC to the inbound goods receipt |
| QCA | Batch | `batch_no` | Traces the specific goods batch being inspected |
| QCA | Item | `item_code` | The raw material or packaging item being received |
| QCA | Supplier | `supplier` | The vendor supplying the goods |
| QCB–QCE | Work Order | `work_order` | Links process record to active production order |
| QCB–QCE | Factory Line | `factory_line` | Identifies which production line generated the reading |
| QCB–QCE | Item | `product_item` | The product being manufactured (QCB–QCD: the item the Work Order makes, filled in from it; Finished Goods items without one) |
| QCF | Item | `item_code` | Product being tasted |
| QCF | Batch | `batch_no` | Specific batch under evaluation |
| QCG | Work Order | `work_order` | Packaging run being checked |
| QCH | Factory Line | `factory_line` | Line whose metal detector is being verified (CCP); its Metal Detector ID offers the detectors used on it |
| Metal Detector | Factory Line | `factory_lines` (Metal Detector Factory Line) | The lines a detector is used on |
| Quality Hub Settings | Factory Line | `*_lines` (Quality Hub Factory Line) | The lines each Quality Hub tab records on |
| QCB–QCD, QCF–QCI | Work Order | `work_order` | Offers the Work Orders on the record's line (`custom_factory_line`); not on the retired QCE |
| QCA–QCD, QCF–QCI | Employee | `operator` | The operator whose work was checked (since 2026-11): an Active Employee, looked up without Employee permission; its name in `operator_name` |
| QCI | Work Order | `work_order` | The production run checked; it names the product |
| QCI | Item | `item_code` | Finished product being weight-checked (checks made before 2026-11) |
| QCI | Batch | `batch_no` | The finished goods batch (checks made before 2026-11) |
| Live Monitor | Quality Inspection Reading | (SQL join) | Rejected readings displayed in "Recent Out-of-Range" panel |
| Live Monitor | Quality Feedback | `status` | Open non-conformance count (if module is in use) |

---

## 15. Configuration & Deployment

### Required Roles

The following roles must exist before QC personnel can use the module:

| Role | Purpose |
|---|---|
| Quality Controller | Day-to-day QC data entry — create, submit, amend |
| Quality Manager | Full access including deletion and reporting |
| Production Manager | Read-only visibility for production planning purposes |

Create these roles in **ERPNext → Setup → Role**.

Since 2026-11 every operator a QC record names must be an **Employee** (Active), as on the Operator Hub: line operators, packers, goods-in staff and agency workers. The quality roles need no permission on Employee (§7).

### Fixtures

`isnack/hooks.py` defines:

```python
fixtures = [
    {"dt": "Client Script"},
    {"dt": "Custom Field"},
    {"dt": "Property Setter"},
]
```

These fixtures are exported/imported with `bench export-fixtures` / `bench import-fixtures` for Client Scripts, Custom Fields, and Property Setters that extend standard ERPNext DocTypes.

### Factory Line Setup

Before creating QC records, create at least one **Factory Line** document via **Isnack → Factory Line**. The name (set by user, e.g. `"Line 1"`) is used as the primary link key across all QC record DocTypes. Each **Metal Detector** names the lines it is used on: a metal detector log offers it on those only. **Quality Hub Settings** gives each Quality Hub tab the lines it records on; a tab given none offers every line. A record's Work Order offers the Work Orders on its line, and a line no Work Order is planned on offers none: Work Orders take their BOM's default line, a production line, so the tabs whose checks need a Work Order (Packaging and Weight, CCP & Metal) are given the production lines their checks are recorded on, and each Metal Detector lists those lines.

### Deployment Steps

```bash
# 1. Install the app (first time)
bench get-app isnack <repo-url>
bench --site <site> install-app isnack

# 2. Apply all DocType and Page definitions
bench --site <site> migrate

# 3. (Optional) Load fixtures
bench --site <site> import-fixtures --app isnack

# 4. Restart to register page assets
bench restart
```

After `bench migrate`, the Quality Hub page is accessible at:
```
https://<site>/app/quality-hub
```

---

## 16. Future Considerations

The following enhancements have been identified during the initial implementation but are deferred for future development cycles:

- **Configurable Thresholds** — The out-of-range threshold for extruder moisture (> 14%) and the packaging variance limit (≤ 0.5) are hard-coded in the Python controllers, and the weight check's TU limits were entered on each check; all three now apply only to the records made before 2026-11. Should limits come back for the new readings, the waste or the samples, keeping them in the **Factory Settings** DocType or a dedicated `QC Specification` DocType would let quality managers adjust them without code changes.

- **SPC / Trend Charts** — The time-series data already captured in the extruder, frying, and oven child tables is well-suited for Statistical Process Control (SPC) control charts. A future Reports tab enhancement could render X-bar and R charts using Frappe's Chart library.

- **Mobile / Touch Interface** — The current UI is designed for desktop browsers used by quality inspectors at workstations. A lightweight mobile-first view (similar to the Operator Hub's kiosk mode) would allow inspectors to enter readings directly on the factory floor using tablets or mobile devices.

- **Notification / Alert Rules** — When `all_tests_passed = 0` (metal detector failure) or `overall_status = "Fail"` on submission, automated email or system notifications to the Quality Manager and Production Manager could be triggered via Frappe's `Notification` DocType or a custom scheduler event.

- **`out_of_range_count` Logic for QCD and QCE** — The frying line (QCD) and oven (QCE) controllers currently set `out_of_range_count = 0` with a placeholder comment. Implementing spec-based range checks (e.g. comparing oil temperature against configurable min/max limits) is the next step for these DocTypes.
