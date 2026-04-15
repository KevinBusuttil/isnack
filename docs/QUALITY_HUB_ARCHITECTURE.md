# Quality Hub — Architecture Reference

**App:** isnack  
**Module:** Isnack  
**ERPNext Compatibility:** v15  
**Developer:** Busuttil Technologies Limited  
**Last Updated:** 2026-04-15

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
   - [QCI — QC Weight Check](#qci--qc-weight-check)
6. [Child Table Schemas](#6-child-table-schemas)
   - [QC Extruder Reading](#qc-extruder-reading)
   - [QC Frying Reading](#qc-frying-reading)
   - [QC Oven Reading](#qc-oven-reading)
   - [QC Tasting Score](#qc-tasting-score)
   - [QC Metal Detector Test](#qc-metal-detector-test)
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

Each physical worksheet (Receiving, Puffs Extruder, Rice Extruder, Frying Line, Oven, Tasting, Packaging, Metal Detector, Weight Check) is mapped 1-to-1 to a submittable Frappe DocType. The Quality Hub page surfaces all nine DocTypes through a unified, tabbed interface, and the backend triggers automatic field calculations and Lab Checkpoint updates on submission.

Access is restricted to the **Quality Controller**, **Quality Manager**, and **System Manager** roles. **Production Manager** has read-only visibility into all QC records (see [Section 7](#7-rbac--permissions)).

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
| 5 | QCE-005 Oven Record Sheet V2.xlsx | QC Oven Record | QCE | `QCE-.YYYY.-.#####` | Process |
| 6 | QCF-006 Tasting Records V2.xlsx | QC Tasting Record | QCF | `QCF-.YYYY.-.#####` | Tasting |
| 7 | QCG-007 Packaging material checks and reconciliation V2.xlsx | QC Packaging Check | QCG | `QCG-.YYYY.-.#####` | Packaging |
| 8 | QCH-008 Daily Metal Detector Verification.xlsx | QC Metal Detector Log | QCH | `QCH-.YYYY.-.#####` | CCP |
| 9 | QCI-009 Weight Quality Check Sheet.xlsx | QC Weight Check | QCI | `QCI-.YYYY.-.#####` | Packaging |

---

## 3. DocType Inventory

All 15 DocTypes (9 parent + 6 child) registered under the **Isnack** module:

| DocType Name | Type | Code | Child Table Of | File Path |
|---|---|---|---|---|
| QC Receiving Record | Parent | QCA | — | `isnack/isnack/doctype/qc_receiving_record/` |
| QC Puffs Extruder Record | Parent | QCB | — | `isnack/isnack/doctype/qc_puffs_extruder_record/` |
| QC Rice Extruder Record | Parent | QCC | — | `isnack/isnack/doctype/qc_rice_extruder_record/` |
| QC Frying Line Record | Parent | QCD | — | `isnack/isnack/doctype/qc_frying_line_record/` |
| QC Oven Record | Parent | QCE | — | `isnack/isnack/doctype/qc_oven_record/` |
| QC Tasting Record | Parent | QCF | — | `isnack/isnack/doctype/qc_tasting_record/` |
| QC Packaging Check | Parent | QCG | — | `isnack/isnack/doctype/qc_packaging_check/` |
| QC Metal Detector Log | Parent | QCH | — | `isnack/isnack/doctype/qc_metal_detector_log/` |
| QC Weight Check | Parent | QCI | — | `isnack/isnack/doctype/qc_weight_check/` |
| QC Extruder Reading | Child | N/A | QCB, QCC | `isnack/isnack/doctype/qc_extruder_reading/` |
| QC Frying Reading | Child | N/A | QCD | `isnack/isnack/doctype/qc_frying_reading/` |
| QC Oven Reading | Child | N/A | QCE | `isnack/isnack/doctype/qc_oven_reading/` |
| QC Tasting Score | Child | N/A | QCF | `isnack/isnack/doctype/qc_tasting_score/` |
| QC Metal Detector Test | Child | N/A | QCH | `isnack/isnack/doctype/qc_metal_detector_test/` |
| QC Weight Sample | Child | N/A | QCI | `isnack/isnack/doctype/qc_weight_sample/` |

All parent DocTypes have `"is_submittable": 1` and `"track_changes": 1`. All child DocTypes have `"istable": 1` and `"editable_grid": 1`.

---

## 4. Common Field Schema

The following 9 fields are present on **every** parent DocType (QCA–QCI) with identical definitions:

| Fieldname | Fieldtype | Label | Notes |
|---|---|---|---|
| `record_date` | Date | Record Date | `reqd: 1`, `default: "Today"` |
| `shift` | Select | Shift | `reqd: 1`, options: Morning / Afternoon / Night |
| `factory_line` | Link → Factory Line | Factory Line | — |
| `work_order` | Link → Work Order | Work Order | — |
| `operator_name` | Data | Operator Name | — |
| `qc_inspector` | Link → User | QC Inspector | `default: "__user"` (auto-fills current user) |
| `status` | Select | Status | options: Draft / Submitted / Rejected / Closed |
| `remarks` | Small Text | Remarks | — |
| `amended_from` | Link → (same DocType) | Amended From | `read_only: 1`, `no_copy: 1` |

---

## 5. Per-DocType Field Schemas

Each section below lists only the **DocType-specific** fields (beyond the 9 common fields above).

---

### QCA — QC Receiving Record

**Naming:** `QCA-.YYYY.-.#####`  
**Purpose:** Records goods-inward inspection for raw materials and packaging arriving from suppliers.

| Fieldname | Fieldtype | Label | Notes |
|---|---|---|---|
| `supplier` | Link → Supplier | Supplier | — |
| `purchase_receipt` | Link → Purchase Receipt | Purchase Receipt | — |
| `item_code` | Link → Item | Item Code | `reqd: 1` |
| `item_name` | Data | Item Name | `fetch_from: item_code.item_name`, `read_only: 1` |
| `batch_no` | Link → Batch | Batch No | — |
| `qty_received` | Float | Qty Received | — |
| `packaging_intact` | Check | Packaging Intact | — |
| `labelling_correct` | Check | Labelling Correct | — |
| `foreign_body_check` | Check | Foreign Body Check | — |
| `colour_acceptable` | Check | Colour Acceptable | — |
| `arrival_temperature` | Float | Arrival Temperature (°C) | — |
| `acceptable_range_min` | Float | Acceptable Range Min (°C) | — |
| `acceptable_range_max` | Float | Acceptable Range Max (°C) | — |
| `temp_pass` | Check | Temperature Pass | `read_only: 1` — auto-calculated by `validate()` |
| `coa_received` | Check | COA Received | — |
| `coa_acceptable` | Check | COA Acceptable | — |
| `spec_sheet_matches` | Check | Spec Sheet Matches | — |
| `overall_status` | Select | Overall Status | options: Accepted / Conditionally Accepted / Rejected |

---

### QCB — QC Puffs Extruder Record

**Naming:** `QCB-.YYYY.-.#####`  
**Purpose:** Shift-level extruder process record for puffs production lines, with per-time-slot readings.

| Fieldname | Fieldtype | Label | Notes |
|---|---|---|---|
| `product_item` | Link → Item | Product Item | — |
| `product_name` | Data | Product Name | `fetch_from: product_item.item_name`, `read_only: 1` |
| `readings` | Table → QC Extruder Reading | Readings | Child table |
| `avg_moisture` | Float | Avg Moisture (%) | `read_only: 1` — auto-calculated |
| `avg_density` | Float | Avg Density | `read_only: 1` — auto-calculated |
| `out_of_range_count` | Int | Out of Range Count | `read_only: 1` — moisture > 14% |
| `overall_status` | Select | Overall Status | options: Pass / Fail |

---

### QCC — QC Rice Extruder Record

**Naming:** `QCC-.YYYY.-.#####`  
**Purpose:** Identical structure to QCB but for rice extruder lines.

| Fieldname | Fieldtype | Label | Notes |
|---|---|---|---|
| `product_item` | Link → Item | Product Item | — |
| `product_name` | Data | Product Name | `fetch_from: product_item.item_name`, `read_only: 1` |
| `readings` | Table → QC Extruder Reading | Readings | Shared child table with QCB |
| `avg_moisture` | Float | Avg Moisture (%) | `read_only: 1` — auto-calculated |
| `avg_density` | Float | Avg Density | `read_only: 1` — auto-calculated |
| `out_of_range_count` | Int | Out of Range Count | `read_only: 1` — moisture > 14% |
| `overall_status` | Select | Overall Status | options: Pass / Fail |

---

### QCD — QC Frying Line Record

**Naming:** `QCD-.YYYY.-.#####`  
**Purpose:** Records frying process conditions (oil temperature, product moisture) per time slot.

| Fieldname | Fieldtype | Label | Notes |
|---|---|---|---|
| `product_item` | Link → Item | Product Item | — |
| `product_name` | Data | Product Name | `fetch_from: product_item.item_name`, `read_only: 1` |
| `readings` | Table → QC Frying Reading | Readings | Child table |
| `avg_oil_temperature` | Float | Avg Oil Temperature (°C) | `read_only: 1` — auto-calculated |
| `avg_product_moisture` | Float | Avg Product Moisture (%) | `read_only: 1` — auto-calculated |
| `out_of_range_count` | Int | Out of Range Count | `read_only: 1` — placeholder for future spec-based logic |
| `overall_status` | Select | Overall Status | options: Pass / Fail |

---

### QCE — QC Oven Record

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
| `overall_status` | Select | Overall Status | options: Pass / Fail |

---

### QCF — QC Tasting Record

**Naming:** `QCF-.YYYY.-.#####`  
**Purpose:** Panel tasting evaluation with per-taster scores across multiple sensory attributes.

| Fieldname | Fieldtype | Label | Notes |
|---|---|---|---|
| `item_code` | Link → Item | Item Code | — |
| `item_name` | Data | Item Name | `fetch_from: item_code.item_name`, `read_only: 1` |
| `batch_no` | Link → Batch | Batch No | — |
| `scores` | Table → QC Tasting Score | Scores | Child table |
| `avg_overall` | Float | Avg Overall Score | `read_only: 1` — auto-calculated |
| `min_score` | Float | Min Score | `read_only: 1` — auto-calculated |
| `pass_threshold` | Float | Pass Threshold | `default: "3.0"` — configurable per record |
| `overall_status` | Select | Overall Status | auto-set to Pass/Fail by `validate()` |

---

### QCG — QC Packaging Check

**Naming:** `QCG-.YYYY.-.#####`  
**Purpose:** Checks packaging film quality, seal integrity, label accuracy, and accounts for film material reconciliation (issued vs used/wasted/returned).

| Fieldname | Fieldtype | Label | Notes |
|---|---|---|---|
| `film_type` | Data | Film Type | — |
| `film_batch` | Data | Film Batch | — |
| `print_quality_ok` | Check | Print Quality OK | — |
| `seal_integrity_ok` | Check | Seal Integrity OK | — |
| `label_correct` | Check | Label Correct | — |
| `artwork_matches` | Check | Artwork Matches | — |
| `qty_issued` | Float | Qty Issued | — |
| `qty_used` | Float | Qty Used | — |
| `qty_wasted` | Float | Qty Wasted | — |
| `qty_returned` | Float | Qty Returned | — |
| `variance` | Float | Variance | `read_only: 1` — auto-calculated: `issued − used − wasted − returned` |
| `variance_acceptable` | Check | Variance Acceptable | `read_only: 1` — auto-set: `1` if `abs(variance) ≤ 0.5` |

---

### QCH — QC Metal Detector Log

**Naming:** `QCH-.YYYY.-.#####`  
**Purpose:** Critical Control Point (CCP) daily verification log for metal detectors. Mandatory per HACCP requirements.

| Fieldname | Fieldtype | Label | Notes |
|---|---|---|---|
| `metal_detector_id` | Data | Metal Detector ID | — |
| `detector_make_model` | Data | Make/Model | — |
| `tests` | Table → QC Metal Detector Test | Tests | Child table |
| `all_tests_passed` | Check | All Tests Passed | `read_only: 1` — auto-calculated |
| `corrective_action` | Small Text | Corrective Action | `mandatory_depends_on: eval:!doc.all_tests_passed` |
| `last_calibration_date` | Date | Last Calibration Date | — |
| `next_calibration_date` | Date | Next Calibration Date | — |
| `calibration_certificate` | Attach | Calibration Certificate | — |

---

### QCI — QC Weight Check

**Naming:** `QCI-.YYYY.-.#####`  
**Purpose:** Statistical weight control for finished goods. Calculates average, standard deviation, min/max, and TU1/TU2 failure counts across individual package samples.

| Fieldname | Fieldtype | Label | Notes |
|---|---|---|---|
| `item_code` | Link → Item | Item Code | — |
| `item_name` | Data | Item Name | `fetch_from: item_code.item_name`, `read_only: 1` |
| `batch_no` | Link → Batch | Batch No | — |
| `nominal_weight` | Float | Nominal Weight (g) | — |
| `tu1_limit` | Float | TU1 Limit (g) | Lower tolerance limit 1 |
| `tu2_limit` | Float | TU2 Limit (g) | Lower tolerance limit 2 (maximum permissible shortage) |
| `samples` | Table → QC Weight Sample | Samples | Child table |
| `sample_count` | Int | Sample Count | `read_only: 1` — auto-calculated |
| `average_weight` | Float | Average Weight (g) | `read_only: 1` — auto-calculated |
| `std_deviation` | Float | Std Deviation | `read_only: 1` — population std dev |
| `min_weight` | Float | Min Weight (g) | `read_only: 1` — auto-calculated |
| `max_weight` | Float | Max Weight (g) | `read_only: 1` — auto-calculated |
| `tu1_failures` | Int | TU1 Failures | `read_only: 1` — count of samples below `tu1_limit` |
| `tu2_failures` | Int | TU2 Failures | `read_only: 1` — count of samples below `tu2_limit` |
| `overall_status` | Select | Overall Status | options: Pass / Fail / Marginal |

---

## 6. Child Table Schemas

Child tables inherit no permissions (permissions are enforced on the parent). All have `"editable_grid": 1` for in-grid editing on the form view.

---

### QC Extruder Reading

**Used by:** QC Puffs Extruder Record (QCB), QC Rice Extruder Record (QCC)

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

### QC Frying Reading

**Used by:** QC Frying Line Record (QCD)

| Fieldname | Fieldtype | Label | `in_list_view` |
|---|---|---|---|
| `time_slot` | Time | Time Slot | ✅ |
| `oil_temperature` | Float | Oil Temperature (°C) | ✅ |
| `oil_ffa` | Float | Oil FFA | ✅ |
| `oil_tpm` | Float | Oil TPM | ✅ |
| `product_temperature` | Float | Product Temp (°C) | — |
| `product_moisture` | Float | Product Moisture (%) | ✅ |
| `oil_change_flag` | Check | Oil Changed | — |
| `reading_remarks` | Small Text | Remarks | — |

---

### QC Oven Reading

**Used by:** QC Oven Record (QCE)

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
| `appearance_score` | Rating | Appearance | ✅ |
| `colour_score` | Rating | Colour | ✅ |
| `aroma_score` | Rating | Aroma | — |
| `taste_score` | Rating | Taste | ✅ |
| `texture_score` | Rating | Texture | — |
| `overall_score` | Rating | Overall | ✅ |
| `comments` | Small Text | Comments | — |

---

### QC Metal Detector Test

**Used by:** QC Metal Detector Log (QCH)

| Fieldname | Fieldtype | Label | `in_list_view` |
|---|---|---|---|
| `test_time` | Time | Test Time | ✅ |
| `test_piece_type` | Select | Test Piece Type | ✅ (options: Fe / Non-Fe / Stainless) |
| `test_piece_size_mm` | Float | Test Piece Size (mm) | ✅ |
| `detected` | Check | Detected (Pass) | ✅ |
| `sensitivity_setting` | Data | Sensitivity Setting | — |
| `test_remarks` | Small Text | Remarks | — |

---

### QC Weight Sample

**Used by:** QC Weight Check (QCI)

| Fieldname | Fieldtype | Label | `in_list_view` | Notes |
|---|---|---|---|---|
| `sample_no` | Int | Sample No | ✅ | — |
| `gross_weight` | Float | Gross Weight (g) | ✅ | — |
| `tare_weight` | Float | Tare Weight (g) | ✅ | — |
| `net_weight` | Float | Net Weight (g) | ✅ | `read_only: 1` — calculated by parent `validate()` |
| `in_range` | Check | In Range | ✅ | `read_only: 1` — set to 1 if `net_weight >= tu2_limit` |

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
| Print | ✅ | ✅ | ✅ | — |
| Email | ✅ | ✅ | ✅ | — |
| Report | ✅ | ✅ | ✅ | — |
| Share | ✅ | ✅ | ✅ | — |

**Key points:**
- Quality Controllers can create, edit, and submit records, but **cannot delete** them.
- Quality Managers have full CRUD including deletion.
- Production Managers have **read-only** access — they can view QC records from their Operator Hub context but cannot create or modify them.
- Child table permissions are inherited from the parent DocType.

---

## 8. Backend Controller Logic

Each parent DocType has a Python controller in `<doctype_folder>/<doctype_name>.py` that inherits from `frappe.model.document.Document` and implements a `validate()` method.

---

### QCA — QC Receiving Record

**File:** `isnack/isnack/doctype/qc_receiving_record/qc_receiving_record.py`

```
validate():
    if arrival_temperature is not None
       AND acceptable_range_min is not None
       AND acceptable_range_max is not None:
        temp_pass = 1  if  acceptable_range_min ≤ arrival_temperature ≤ acceptable_range_max
        temp_pass = 0  otherwise
```

---

### QCB — QC Puffs Extruder Record

**File:** `isnack/isnack/doctype/qc_puffs_extruder_record/qc_puffs_extruder_record.py`

```
validate():
    moistures = [r.moisture_content for r in readings if moisture_content is not None]
    densities = [r.product_density  for r in readings if product_density  is not None]
    avg_moisture = mean(moistures) if moistures else 0
    avg_density  = mean(densities) if densities else 0
    out_of_range_count = count(r for r in readings if r.moisture_content > 14)
```

---

### QCC — QC Rice Extruder Record

**File:** `isnack/isnack/doctype/qc_rice_extruder_record/qc_rice_extruder_record.py`

Identical logic to QCB (same threshold: moisture > 14%):

```
validate():
    moistures = [r.moisture_content for r in readings if moisture_content is not None]
    densities = [r.product_density  for r in readings if product_density  is not None]
    avg_moisture = mean(moistures) if moistures else 0
    avg_density  = mean(densities) if densities else 0
    out_of_range_count = count(r for r in readings if r.moisture_content > 14)
```

---

### QCD — QC Frying Line Record

**File:** `isnack/isnack/doctype/qc_frying_line_record/qc_frying_line_record.py`

```
validate():
    oil_temps = [r.oil_temperature  for r in readings if oil_temperature  is not None]
    moistures = [r.product_moisture for r in readings if product_moisture is not None]
    avg_oil_temperature  = mean(oil_temps) if oil_temps else 0
    avg_product_moisture = mean(moistures) if moistures else 0
    out_of_range_count   = 0   # placeholder — spec-based logic to be added
```

---

### QCE — QC Oven Record

**File:** `isnack/isnack/doctype/qc_oven_record/qc_oven_record.py`

```
validate():
    z1    = [r.zone_1_temp for r in readings if zone_1_temp is not None]
    z2    = [r.zone_2_temp for r in readings if zone_2_temp is not None]
    moist = [r.moisture    for r in readings if moisture    is not None]
    avg_zone1_temp = mean(z1)    if z1    else 0
    avg_zone2_temp = mean(z2)    if z2    else 0
    avg_moisture   = mean(moist) if moist else 0
    out_of_range_count = 0   # placeholder — spec-based logic to be added
```

---

### QCF — QC Tasting Record

**File:** `isnack/isnack/doctype/qc_tasting_record/qc_tasting_record.py`

```
validate():
    overall_scores = [s.overall_score for s in scores if overall_score is not None]
    avg_overall = mean(overall_scores) if overall_scores else 0
    min_score   = min(overall_scores)  if overall_scores else 0
    threshold   = pass_threshold or 3.0
    overall_status = "Pass" if avg_overall >= threshold else "Fail"
```

---

### QCG — QC Packaging Check

**File:** `isnack/isnack/doctype/qc_packaging_check/qc_packaging_check.py`

```
validate():
    issued   = qty_issued   or 0
    used     = qty_used     or 0
    wasted   = qty_wasted   or 0
    returned = qty_returned or 0
    variance             = issued - used - wasted - returned
    variance_acceptable  = 1 if abs(variance) ≤ 0.5 else 0
```

---

### QCH — QC Metal Detector Log

**File:** `isnack/isnack/doctype/qc_metal_detector_log/qc_metal_detector_log.py`

```
validate():
    if tests is not empty:
        all_tests_passed = 1 if all(t.detected == True for t in tests) else 0
    else:
        all_tests_passed = 0
```

Note: `corrective_action` is mandatory when `all_tests_passed = 0`, enforced via the `mandatory_depends_on` expression on the field.

---

### QCI — QC Weight Check

**File:** `isnack/isnack/doctype/qc_weight_check/qc_weight_check.py`

```
validate():
    tu1 = tu1_limit or 0
    tu2 = tu2_limit or 0
    for s in samples:
        s.net_weight = (s.gross_weight or 0) - (s.tare_weight or 0)
        s.in_range   = 1 if s.net_weight >= tu2 else 0

    net_weights = [s.net_weight for s in samples]
    sample_count   = len(net_weights)
    if net_weights:
        average_weight = mean(net_weights)
        variance       = mean((w - average_weight)² for w in net_weights)  # population variance
        std_deviation  = sqrt(variance)
        min_weight     = min(net_weights)
        max_weight     = max(net_weights)
        tu1_failures   = count(w for w in net_weights if w < tu1)
        tu2_failures   = count(w for w in net_weights if w < tu2)
    else:
        all summary fields = 0
```

---

## 9. Hooks & Doc Events

### `on_qc_record_submit`

**Location:** `isnack/isnack/page/quality_hub/quality_hub.py`

This function fires on submission of any of the 9 QC parent DocTypes. It updates the `last_inspection` timestamp on all active Lab Checkpoints that share the same `factory_line`:

```python
def on_qc_record_submit(doc, method):
    factory_line = doc.factory_line   # read from the submitted document
    if not factory_line:
        return                        # no-op if no line linked

    if not frappe.db.table_exists("Lab Checkpoint"):
        return                        # graceful degradation if table missing

    checkpoints = frappe.get_all(
        "Lab Checkpoint",
        filters={"disabled": 0, "factory_line": factory_line},
        fields=["name"],
    )
    for cp in checkpoints:
        frappe.db.set_value(
            "Lab Checkpoint", cp.name,
            "last_inspection", now_datetime(),
            update_modified=False,
        )
```

### `hooks.py` Wiring

All 9 DocTypes are wired in `isnack/hooks.py` under `doc_events`:

```python
doc_events = {
    "QC Receiving Record":       {"on_submit": "isnack.isnack.page.quality_hub.quality_hub.on_qc_record_submit"},
    "QC Puffs Extruder Record":  {"on_submit": "isnack.isnack.page.quality_hub.quality_hub.on_qc_record_submit"},
    "QC Rice Extruder Record":   {"on_submit": "isnack.isnack.page.quality_hub.quality_hub.on_qc_record_submit"},
    "QC Frying Line Record":     {"on_submit": "isnack.isnack.page.quality_hub.quality_hub.on_qc_record_submit"},
    "QC Oven Record":            {"on_submit": "isnack.isnack.page.quality_hub.quality_hub.on_qc_record_submit"},
    "QC Tasting Record":         {"on_submit": "isnack.isnack.page.quality_hub.quality_hub.on_qc_record_submit"},
    "QC Packaging Check":        {"on_submit": "isnack.isnack.page.quality_hub.quality_hub.on_qc_record_submit"},
    "QC Metal Detector Log":     {"on_submit": "isnack.isnack.page.quality_hub.quality_hub.on_qc_record_submit"},
    "QC Weight Check":           {"on_submit": "isnack.isnack.page.quality_hub.quality_hub.on_qc_record_submit"},
}
```

There is also a separate `on_quality_inspection_submit(doc, method)` function in `quality_hub.py` that updates `Lab Checkpoint.last_inspection` when a native ERPNext **Quality Inspection** (linked via `lab_checkpoint` field) is submitted. This function is **not currently wired** in `hooks.py` — it is reserved for a future phase where native ERPNext Quality Inspections (created via `create_quality_inspection_from_checkpoint`) are fully integrated into the submission workflow. To activate it, add the following to `doc_events` in `hooks.py`:

```python
"Quality Inspection": {
    "on_submit": "isnack.isnack.page.quality_hub.quality_hub.on_quality_inspection_submit",
},
```

---

## 10. API Endpoints

All endpoints are defined in `isnack/isnack/page/quality_hub/quality_hub.py` and decorated with `@frappe.whitelist()`.

---

### `get_quality_hub_data()`

**Method:** `isnack.isnack.page.quality_hub.quality_hub.get_quality_hub_data`  
**Purpose:** Returns all data needed to populate the Live Monitor tab on page load or on poll.

**Returns:**
```json
{
  "stats": {
    "overdue_count": <int>,
    "due_now_count": <int>,
    "completed_last_hour": <int>,
    "open_non_conformances": <int>
  },
  "overdue": [ { "name", "checkpoint_name", "equipment", "frequency_mins",
                 "last_inspection", "responsible_user", "minutes_to_next",
                 "minutes_since" }, ... ],
  "due_now":  [ ...same shape... ],
  "upcoming": [ ...same shape... ],
  "recent_out_of_range": [ { "quality_inspection", "specification", "status",
                              "item_code", "inspection_type", "reference_type",
                              "reference_name", "ts" }, ... ]
}
```

**Classification logic:**
- `minutes_to_next <= 0` → overdue
- `0 < minutes_to_next <= 5` → due now
- `minutes_to_next > 5` → upcoming

**Helper functions:**
- `_get_completed_last_hour(now)` — counts submitted Quality Inspections modified in the last hour
- `_get_open_non_conformances()` — counts open Quality Feedback records (returns 0 if the table does not exist)
- `_get_recent_out_of_range_readings(limit=10, hours=4)` — fetches rejected Quality Inspection Readings from the last 4 hours (returns `[]` if the table does not exist)

---

### `get_qc_record_summary(date=None)`

**Method:** `isnack.isnack.page.quality_hub.quality_hub.get_qc_record_summary`  
**Arguments:** `date` (optional, defaults to today)  
**Purpose:** Returns per-DocType record counts for the given date, used to render the 9-card QC summary grid on the Live Monitor tab.

**Returns:**
```json
{
  "QCA": { "doctype": "QC Receiving Record",      "total": 3, "submitted": 2, "draft": 1 },
  "QCB": { "doctype": "QC Puffs Extruder Record", "total": 0, "submitted": 0, "draft": 0 },
  ...
}
```

If a DocType's database table does not yet exist, the entry is `{ "total": 0, "submitted": 0, "draft": 0 }`.

---

### `get_completion_matrix(date=None)`

**Method:** `isnack.isnack.page.quality_hub.quality_hub.get_completion_matrix`  
**Arguments:** `date` (optional, defaults to today)  
**Purpose:** Returns a shift × DocType matrix showing completion status for the Reports & Trends tab.

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

**Cell values:** `"submitted"` | `"draft"` | `"not_started"`

---

### `get_qc_records(doctype, filters=None, limit=20)`

**Method:** `isnack.isnack.page.quality_hub.quality_hub.get_qc_records`  
**Arguments:**  
- `doctype` — must be a value in `QC_DOCTYPES`; throws `frappe.throw` otherwise  
- `filters` — JSON string or dict of filter conditions (optional)  
- `limit` — integer row cap (default 20, UI passes 50)

**Purpose:** Generic record fetcher used by every record-list tab. Returns the base common fields plus `overall_status` and `modified`, with fields not present on the specific DocType silently dropped.

**Returns:** List of record dicts ordered by `record_date desc, modified desc`.

---

### `create_quality_inspection_from_checkpoint(checkpoint)`

**Method:** `isnack.isnack.page.quality_hub.quality_hub.create_quality_inspection_from_checkpoint`  
**Arguments:** `checkpoint` — name of a Lab Checkpoint document  
**Purpose:** Creates a draft ERPNext **Quality Inspection** pre-filled from the Lab Checkpoint (template, linked checkpoint, reference type/name) and returns its name so the UI can route to the form.

**Returns:**
```json
{ "name": "QI-0001" }
```

---

## 11. Quality Hub UI Architecture

**Page registration:** `isnack/isnack/page/quality-hub/`  
**Entry point:** `frappe.pages["quality-hub"].on_page_load = function(wrapper) { ... }`  
**Class:** `isnack.quality_hub.QualityHub`

### Constructor Sequence

```
new QualityHub(wrapper)
  ├── frappe.ui.make_app_page(...)   // Frappe page scaffold
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
| Live Monitor | `monitor` | Lab Checkpoint (monitoring only) | — |
| Receiving (QCA) | `receiving` | QC Receiving Record | — |
| Process (QCB–QCE) | `process` | QC Puffs / Rice / Frying / Oven | Puffs · Rice · Frying · Oven |
| Tasting (QCF) | `tasting` | QC Tasting Record | — |
| Pkg & Weight (QCG/QCI) | `pkg_weight` | QC Packaging Check / QC Weight Check | Packaging · Weight |
| CCP & Metal (QCH) | `metal` | QC Metal Detector Log | — |
| Reports & Trends | `reports` | (matrix — all 9 types) | — |

### Per-Tab Components

**Live Monitor (`monitor`)**
- 4-card stat grid: Overdue readings · Due in next 5 min · Completed last hour · Open non-conformances
- 9-card QC summary grid (one card per QCA–QCI, coloured green/amber by submission status)
- Two-column panel layout:
  - Left: "Due & Overdue Checkpoints" datatable (red badge count)
  - Right: "Recent Out-of-Range Readings" datatable (amber badge count)

**Receiving (`receiving`)**
- Filter bar: date · supplier · docstatus · Filter button · New Record button
- Single panel with record list datatable

**Process (`process`)**
- Sub-nav pills: Puffs Extruder (QCB) · Rice Extruder (QCC) · Frying Line (QCD) · Oven (QCE)
- Filter bar: date · work_order · factory_line · docstatus · Filter button · New Record button
- Single panel with record list datatable
- Active sub-nav pill updates `active_process_sub` and re-loads records

**Tasting (`tasting`)**
- Filter bar: date · factory_line · docstatus · Filter button · New Record button
- Single panel with record list datatable

**Pkg & Weight (`pkg_weight`)**
- Sub-nav pills: Packaging Checks (QCG) · Weight Checks (QCI)
- Filter bar: date · work_order · docstatus · Filter button · New Record button
- Single panel with record list datatable

**CCP & Metal (`metal`)**
- CCP alert banner (`.qh-ccp-alert`):
  - Green (`.qh-ccp-alert-ok`) when today's records exist
  - Amber warning (`.qh-ccp-alert-warn`) when no records for today
- Filter bar: date · metal_detector_id · docstatus · Filter button · New Record button
- Single panel with record list datatable

**Reports & Trends (`reports`)**
- Date-picker + Refresh button → calls `get_completion_matrix(date)` 
- Completion matrix rendered as `<table class="qh-table qh-matrix">` (shift rows × code columns)
  - ✅ = submitted, 🟡 = draft, — = not started
- Quick Links row with direct `#List/` links to all 9 DocType list views

### Record List Datatable

All record lists (`render_record_list`) render the same 7 columns:

| Column | Key | Rendering |
|---|---|---|
| Name | `name` | Hyperlink to form view (`#Form/<doctype>/<name>`) |
| Date | `record_date` | Plain text |
| Shift | `shift` | Plain text |
| Line | `factory_line` | Plain text |
| Operator | `operator_name` | Plain text |
| Result | `overall_status` | Badge: green (Pass/Accepted), red (Fail/Rejected), amber (other) |
| Status | `docstatus` | Badge: amber (Draft), green (Submitted), red (Cancelled) |

Clicking a row navigates to the form via `frappe.set_route("Form", doctype, name)`.

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
     │                    - e.g. temp_pass, avg_moisture,
     │                      variance, all_tests_passed …
     │                             │
     │  User clicks Submit         ▼
     │                    [Frappe Submit (docstatus → 1)]
     │                             │
     │  on_submit hook fires       ▼
     │                    [on_qc_record_submit(doc, method)]
     │                    - Reads doc.factory_line
     │                    - Finds Lab Checkpoints for that line
     │                    - Sets last_inspection = now()
     │                             │
     ▼                             ▼
 [Paper filed]            [Lab Checkpoint updated]
                                   │
                          [Live Monitor auto-poll (30 s)]
                                   │
                                   ▼
                          [get_quality_hub_data()]
                          - Re-classifies checkpoints
                            as overdue / due-now / upcoming
                                   │
                                   ▼
                          [Quality Hub Live Monitor]
                          - Stat cards update
                          - Checkpoint tables refresh
                          - Out-of-range panel refreshes
```

---

## 13. File Map

```
isnack/
├── hooks.py                                  ← doc_events for all 9 QC DocTypes
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
        │   ├── qc_puffs_extruder_record.json
        │   ├── qc_puffs_extruder_record.py
        │   ├── test_qc_puffs_extruder_record.py
        │   └── __init__.py
        │
        ├── qc_rice_extruder_record/          ── QCC
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
        ├── qc_oven_record/                   ── QCE
        │   ├── qc_oven_record.json
        │   ├── qc_oven_record.py
        │   ├── test_qc_oven_record.py
        │   └── __init__.py
        │
        ├── qc_tasting_record/                ── QCF
        │   ├── qc_tasting_record.json
        │   ├── qc_tasting_record.py
        │   ├── test_qc_tasting_record.py
        │   └── __init__.py
        │
        ├── qc_packaging_check/               ── QCG
        │   ├── qc_packaging_check.json
        │   ├── qc_packaging_check.py
        │   ├── test_qc_packaging_check.py
        │   └── __init__.py
        │
        ├── qc_metal_detector_log/            ── QCH
        │   ├── qc_metal_detector_log.json
        │   ├── qc_metal_detector_log.py
        │   ├── test_qc_metal_detector_log.py
        │   └── __init__.py
        │
        ├── qc_weight_check/                  ── QCI
        │   ├── qc_weight_check.json
        │   ├── qc_weight_check.py
        │   ├── test_qc_weight_check.py
        │   └── __init__.py
        │
        ├── qc_extruder_reading/              ── child (QCB, QCC)
        │   ├── qc_extruder_reading.json
        │   ├── qc_extruder_reading.py
        │   └── __init__.py
        │
        ├── qc_frying_reading/                ── child (QCD)
        │   ├── qc_frying_reading.json
        │   ├── qc_frying_reading.py
        │   └── __init__.py
        │
        ├── qc_oven_reading/                  ── child (QCE)
        │   ├── qc_oven_reading.json
        │   ├── qc_oven_reading.py
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
| QCA | Work Order | `work_order` | Links receiving inspection to the production order it feeds |
| QCA | Factory Line | `factory_line` | Identifies the line receiving the goods |
| QCA | Purchase Receipt | `purchase_receipt` | Ties QC to the inbound goods receipt |
| QCA | Batch | `batch_no` | Traces the specific goods batch being inspected |
| QCA | Item | `item_code` | The raw material or packaging item being received |
| QCA | Supplier | `supplier` | The vendor supplying the goods |
| QCB–QCE | Work Order | `work_order` | Links process record to active production order |
| QCB–QCE | Factory Line | `factory_line` | Identifies which production line generated the reading |
| QCB–QCE | Item | `product_item` | The product being manufactured |
| QCF | Item | `item_code` | Product being tasted |
| QCF | Batch | `batch_no` | Specific batch under evaluation |
| QCG | Work Order | `work_order` | Packaging run being checked |
| QCH | Factory Line | `factory_line` | Line whose metal detector is being verified (CCP) |
| QCI | Item | `item_code` | Finished product being weight-checked |
| QCI | Batch | `batch_no` | The finished goods batch |
| All 9 | Lab Checkpoint | `factory_line` (indirect) | `on_qc_record_submit` updates `last_inspection` on all checkpoints for the line |
| Live Monitor | Quality Inspection | `lab_checkpoint` | Existing ERPNext QI records are surfaced in out-of-range panel |
| Live Monitor | Quality Inspection Reading | (SQL join) | Rejected readings displayed in "Recent Out-of-Range" panel |
| Live Monitor | Quality Feedback | `status` | Open non-conformance count (if module is in use) |
| `create_quality_inspection_from_checkpoint` | Quality Inspection | `lab_checkpoint`, `quality_inspection_template` | Creates a draft QI from a Lab Checkpoint via the Live Monitor |

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

Before creating QC records, create at least one **Factory Line** document via **Isnack → Factory Line**. The name (set by user, e.g. `"Line 1"`) is used as the primary link for Lab Checkpoint lookups in `on_qc_record_submit`.

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

- **Configurable Thresholds** — Currently the out-of-range threshold for extruder moisture (> 14%) and the packaging variance limit (≤ 0.5) are hard-coded in the Python controllers. Moving these to the **Factory Settings** DocType or a dedicated `QC Specification` DocType would allow quality managers to adjust limits without code changes.

- **SPC / Trend Charts** — The time-series data already captured in the extruder, frying, and oven child tables is well-suited for Statistical Process Control (SPC) control charts. A future Reports tab enhancement could render X-bar and R charts using Frappe's Chart library.

- **Mobile / Touch Interface** — The current UI is designed for desktop browsers used by quality inspectors at workstations. A lightweight mobile-first view (similar to the Operator Hub's kiosk mode) would allow inspectors to enter readings directly on the factory floor using tablets or mobile devices.

- **Notification / Alert Rules** — When `all_tests_passed = 0` (metal detector failure) or `overall_status = "Fail"` on submission, automated email or system notifications to the Quality Manager and Production Manager could be triggered via Frappe's `Notification` DocType or a custom scheduler event.

- **`out_of_range_count` Logic for QCD and QCE** — The frying line (QCD) and oven (QCE) controllers currently set `out_of_range_count = 0` with a placeholder comment. Implementing spec-based range checks (e.g. comparing oil temperature against configurable min/max limits) is the next step for these DocTypes.

- **ERPNext Quality Inspection Integration** — The `create_quality_inspection_from_checkpoint` API and `on_quality_inspection_submit` function provide a bridge to ERPNext's native quality module. A future enhancement could create a QI automatically for each submitted QC record, enabling use of ERPNext's standard quality reports and non-conformance workflows.
