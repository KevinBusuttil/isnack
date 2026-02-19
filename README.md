# ISNACK - Manufacturing Execution System for ERPNext

**Version:** 0.0.1  
**ERPNext Compatibility:** v15  
**License:** MIT  
**Developer:** Busuttil Technologies Limited  
**Contact:** kevin.busuttil@busuttil-technologies.com

---

## Table of Contents

1. [Overview](#overview)
2. [Core Customizations](#core-customizations)
   - [Manufacturing Execution System (MES)](#manufacturing-execution-system-mes)
   - [Financial & Accounting](#financial--accounting)
   - [Sales & Pricing](#sales--pricing)
   - [Reports](#reports)
3. [Data Flow Diagrams](#data-flow-diagrams)
   - [Storekeeper Hub Data Flow](#storekeeper-hub-data-flow)
   - [Operator Hub Data Flow](#operator-hub-data-flow)
4. [Detailed Operational Flows](#detailed-operational-flows)
   - [Storekeeper Hub Operations](#storekeeper-hub-operations)
   - [Operator Hub Operations](#operator-hub-operations)
5. [Custom DocTypes](#custom-doctypes)
6. [Installation & Configuration](#installation--configuration)
7. [License](#license)

---

## Overview

**ISNACK** is a comprehensive Manufacturing Execution System (MES) application built as a custom ERPNext v15 app. It provides shop-floor operators and material handlers with specialized interfaces for managing production workflows, material staging, and real-time manufacturing operations.

### Key Features

✅ **Dual Hub Architecture** - Specialized interfaces for storekeepers and operators  
✅ **Material Staging & FIFO Allocation** - Intelligent work order preparation and material allocation  
✅ **Kiosk-Mode Production Interface** - Touch-friendly operator hub for shop-floor use  
✅ **Barcode Scanning Integration** - Real-time material consumption tracking  
✅ **Label Printing with QZ Tray** - Silent printing for finished goods and pallets  
✅ **Multi-Currency Support** - Enhanced financial handling with currency conversion fixes  
✅ **Custom Invoicing** - Service invoice functionality with VAT support  
✅ **Production Planning Integration** - Seamless work order and production plan management

### Dual Hub Architecture

ISNACK provides two specialized interfaces optimized for different roles:

- **Storekeeper Hub**: Material staging and work order preparation interface for warehouse staff
- **Operator Hub**: Kiosk-mode production interface for shop-floor operators

Both hubs integrate seamlessly with ERPNext's native manufacturing, inventory, and accounting modules while providing role-specific workflows that streamline daily operations.

---

## Core Customizations

### Manufacturing Execution System (MES)

#### Storekeeper Hub

**Location:** `isnack/isnack/page/storekeeper_hub/`

**Purpose:** Material staging and work order preparation interface for warehouse staff to efficiently prepare materials for production.

**Key Features:**
- **Work Order Buckets**: Groups work orders by BOM for consolidated material picking
- **Consolidated Pick Cart**: Single staging list across multiple work orders
- **FIFO Allocation Engine**: Automatically distributes cart quantities using FIFO by WO start time
- **Stock Entry Creation**: Generates material transfer entries for staged materials
- **Picklist Generation**: Optional picklist creation for warehouse picking teams
- **PO Receipt Workflow**: Quick purchase receipt creation from purchase orders
- **Activity Tracking**: Real-time tracking of staged materials, manual entries, and pallet movements

**Configuration:**
- Source warehouse selection for material pulls
- Production date (posting date) filtering
- Optional pallet ID tagging for tracking
- Role-based button visibility via Factory Settings

#### Operator Hub

**Location:** `isnack/isnack/page/operator_hub/`

**Purpose:** Kiosk-mode production interface designed for shop-floor operators with touch-friendly controls and barcode scanning.

**Key Features:**
- **Operator & Line Selection**: Multi-line assignment with operator tracking
- **Work Order Queue**: Visual status chips showing WO progress (Not Started, In Process, Completed)
- **Materials Snapshot**: Real-time view of required, transferred, consumed, and remaining materials
- **Barcode Scanning**: Direct material consumption via barcode with duplicate detection
- **Material Requests**: Request additional materials with reason tracking
- **Material Returns**: Per-WO and end-of-shift WIP return workflows
- **Label Printing**: FG carton label printing with QZ Tray integration
- **Work Order Completion**: End WO with SFG consumption and Close Production with packaging

**Configuration:**
- Consume-on-scan behavior (always enabled)
- Duplicate scan window (configurable TTL)
- Max active operators per job
- Material over-consumption threshold alerts

#### Factory Settings DocType

**Location:** `isnack/isnack/doctype/factory_settings/`

**Purpose:** Centralized MES configuration for all manufacturing and production settings.

**Configuration Options:**

**General:**
- Batch space handling (reject, convert to underscore/dash, or allow)

**Scanning and Consumption:**
- Consume materials on scan (hardcoded to enabled)
- Duplicate scan window (default: 45 seconds)
- Max active operators per job (default: 2)
- Material over-consumption threshold (default: 150%)

**Close Production:**
- Validation mode (No Validation, All WOs Must Be Ended, Minimum WO Count)
- Minimum WO count for validation

**Storekeeper Hub:**
- Roles for stock entry buttons (Mat. Transfer, Mat. Issue, Mat. Receipt)

**Item Group Policies:**
- Packaging item groups
- Backflush item groups
- Allowed item groups per line

**Per Line Rules:**
- Default semi-finished warehouse
- Line-specific warehouse mappings

**Label Printing:**
- Default label template
- Default label print format (pallet labels)
- Default FG label print format (carton labels)
- Default label printer
- Default A4 printer
- Enable silent printing (QZ Tray)
- Allowed pallet UOM types

**Per User Defaults:**
- User-specific printer configurations

---

### Financial & Accounting

#### Journal Entry Override

**Location:** `isnack/overrides/journal_entry.py`

**Purpose:** Implements fix from ERPNext PR #43331 for multi-currency Journal Entry handling.

**Issue Fixed:** In standard ERPNext v15, GL entries for all rows in multi-currency Journal Entries incorrectly use the same exchange rate from the first row.

**Solution:** Custom `CustomJournalEntry` class that uses row-specific exchange rates for each Journal Entry line item. The fix applies automatically to Journal Entries created from Service Invoices.

**Key Methods:**
- `_is_from_service_invoice()`: Identifies JEs originating from Service Invoices
- `validate()`: Applies exchange rate fix for multi-currency Service Invoice JEs
- `set_amounts_in_company_currency()`: Prevents overwriting of company currency amounts

#### GL Currency Monkey Patch

**Location:** `isnack/monkey_patches/gl_currency.py`

**Purpose:** Fixes currency conversion issues in General Ledger reports.

**Implementation:** Custom `convert_to_presentation_currency()` function that uses each entry's posting date for accurate currency conversion instead of a single report date.

#### Service Invoice DocType

**Location:** `isnack/isnack/doctype/service_invoice/`

**Purpose:** Custom invoice type specifically designed for service-based transactions.

**Features:**
- Multi-currency support with proper exchange rate handling
- VAT calculation and tracking
- Journal Entry generation with correct currency conversion
- Integration with Customer Discount Rules
- Flexible payment terms

---

### Sales & Pricing

#### Customer Discount Rules

**Location:** `isnack/isnack/doctype/customer_discount_rules/`

**Purpose:** Manage tiered discount structures for customers.

**Features:**
- Customer-specific discount configurations
- Integration with Sales Orders and Service Invoices
- Flexible discount calculation rules

#### Sales Order Customization

**Location:** `isnack/public/js/sales_order_proforma.js`

**Purpose:** Adds proforma invoice functionality to Sales Orders.

**Features:**
- Generate proforma invoices from Sales Orders
- Custom print formats for proforma documents
- Proforma-specific workflow states

---

### Reports

#### VAT Report

**Location:** `isnack/isnack/report/vat/`

**Purpose:** Detailed VAT analysis and reporting for tax compliance.

#### VAT Summary Report

**Location:** `isnack/isnack/report/vat_summary/`

**Purpose:** Summarized VAT overview for quick tax period reviews.

#### Accounts Receivable Proforma Report

**Location:** `isnack/isnack/report/accounts_receivable_proforma/`

**Purpose:** Track proforma invoices and outstanding receivables.

---

## Data Flow Diagrams

### Storekeeper Hub Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          STOREKEEPER HUB WORKFLOW                           │
└─────────────────────────────────────────────────────────────────────────────┘

  ┌──────────────────┐
  │   Start Setup    │  
  │  - Select Line   │ 
  │  - Source WH     │
  │  - Posting Date  │
  │  - Pallet ID     │
  └────────┬─────────┘
           │
           ▼
  ┌──────────────────┐
  │  Work Order      │  ← Groups WOs by same BOM
  │    Buckets       │  ← Enables consolidated picking
  └────────┬─────────┘
           │
           ▼
  ┌──────────────────┐
  │  Consolidated    │  ← Scan/type items
  │    Pick Cart     │  ← Manual row addition
  │                  │  ← Adjust qty/batch/notes
  └────────┬─────────┘
           │
           ▼
  ┌──────────────────────────────────────┐
  │  Allocate & Create Transfers         │
  │                                      │
  │  ┌────────────────────────────────┐ │
  │  │   FIFO Allocation Engine       │ │
  │  │   - Sort WOs by start time     │ │
  │  │   - Distribute cart quantities │ │
  │  │   - Batch validation           │ │
  │  └────────────────────────────────┘ │
  │                                      │
  │  ┌────────────────────────────────┐ │
  │  │   Stock Entry Creation         │ │
  │  │   - Material Transfer for WO   │ │
  │  │   - Source → Target warehouse  │ │
  │  │   - Pallet ID tagging          │ │
  │  └────────────────────────────────┘ │
  └────────┬─────────────────────────────┘
           │
           ▼
  ┌──────────────────┐         ┌──────────────────┐
  │    Generate      │         │  Quick Actions   │
  │    Picklist      │         │  - Mat. Transfer │
  │   (Optional)     │         │  - Mat. Issue    │
  └────────┬─────────┘         │  - Mat. Receipt  │
           │                   │  - PO Receipt    │
           │                   └──────────────────┘
           │
           ▼
  ┌─────────────────────────────────────────┐
  │        Activity Tracking Panel          │
  │  ┌───────────────────────────────────┐  │
  │  │  Staged (Production Date)         │  │
  │  │  - Transfers for selected date    │  │
  │  │  - Last 24h if no date selected   │  │
  │  └───────────────────────────────────┘  │
  │  ┌───────────────────────────────────┐  │
  │  │  Recent Manual Stock Entries      │  │
  │  │  - Manual transfers/issues        │  │
  │  │  - Last 24 hours                  │  │
  │  └───────────────────────────────────┘  │
  │  ┌───────────────────────────────────┐  │
  │  │  Pallet Tracker                   │  │
  │  │  - Pallet-tagged transfers        │  │
  │  │  - Last 24 hours                  │  │
  │  └───────────────────────────────────┘  │
  └─────────────────────────────────────────┘
```

**Key Data Flows:**

1. **Material Staging Workflow**
   - Filter setup → WO bucket selection → Cart building → Allocation → Transfer creation

2. **Batch Validation**
   - Cart items validated against available batches
   - FIFO allocation ensures oldest batches used first

3. **FIFO Allocation Logic**
   - Work orders sorted by planned start date/time
   - Cart quantities distributed proportionally
   - Ensures fair staging across multiple WOs

4. **Transfer Creation Process**
   - Stock Entry (Material Transfer for Manufacture) created per WO
   - Items moved from source warehouse to WIP warehouse
   - Optional pallet ID stored for tracking

5. **Picklist Generation**
   - Groups multiple Stock Entries into single picklist
   - Warehouse team uses for efficient picking
   - Optional step in the workflow

6. **PO Receipt Workflow**
   - Quick creation of Purchase Receipts from POs
   - Bypasses standard form for speed
   - Direct inventory updates

7. **Activity Tracking**
   - **Staged**: Shows transfers for selected production date or last 24h
   - **Manual SE**: Displays manual stock entries (non-WO related)
   - **Pallet Tracker**: Monitors pallet-tagged movements

---

### Operator Hub Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           OPERATOR HUB WORKFLOW                             │
└─────────────────────────────────────────────────────────────────────────────┘

  ┌──────────────────┐
  │  Set Operator    │
  │   & Factory      │  
  │     Line(s)      │
  └────────┬─────────┘
           │
           ▼
  ┌──────────────────────────────────────┐
  │      Work Order Queue                │
  │  ┌────────────────────────────────┐  │
  │  │  Status Chips:                 │  │
  │  │  🔵 Not Started                │  │
  │  │  🟡 In Process                 │  │
  │  │  🟢 Completed                  │  │
  │  └────────────────────────────────┘  │
  └────────┬─────────────────────────────┘
           │
           ▼
  ┌──────────────────┐
  │   Select Work    │  ← Click WO from queue
  │      Order       │  ← Loads Current WO banner
  └────────┬─────────┘
           │
           ▼
  ┌─────────────────────────────────────────────┐
  │        Materials Snapshot                   │
  │  ┌────────────────────────────────────────┐ │
  │  │  For each material:                    │ │
  │  │  - Required qty (from BOM)             │ │
  │  │  - Transferred qty (staged)            │ │
  │  │  - Consumed qty (scanned/used)         │ │
  │  │  - Remaining qty (still needed)        │ │
  │  │  - Recent issue/transfer history       │ │
  │  └────────────────────────────────────────┘ │
  └────────┬────────────────────────────────────┘
           │
           ▼
  ┌──────────────────┐
  │   Start / Pause  │  ← Start only when Allocated
  │  / Resume WO     │  ← Pause ↔ Resume toggle
  └────────┬─────────┘
           │
           ▼
  ┌─────────────────────────────────────────────┐
  │         Barcode Scanning Flow               │
  │  ┌────────────────────────────────────────┐ │
  │  │  1. Click "Load Materials"             │ │
  │  │  2. Scan barcode or type item code     │ │
  │  │  3. System validates:                  │ │
  │  │     - Item exists in BOM               │ │
  │  │     - Sufficient quantity available    │ │
  │  │     - Duplicate scan check (45s TTL)   │ │
  │  │  4. Create Stock Entry (consumption)   │ │
  │  │  5. Update materials snapshot          │ │
  │  │  6. Show scan history                  │ │
  │  └────────────────────────────────────────┘ │
  └────────┬────────────────────────────────────┘
           │
           ├──────────┬──────────┬──────────┬──────────┬──────────┐
           │          │          │          │          │          │
           ▼          ▼          ▼          ▼          ▼          ▼
  ┌────────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐
  │  Request   │ │ Return │ │  End   │ │ Print  │ │ Label  │ │  End   │
  │   More     │ │Material│ │ Shift  │ │ Label  │ │History │ │  Work  │
  │ Material   │ │(Per WO)│ │ Return │ │  (FG)  │ │        │ │ Order  │
  └─────┬──────┘ └────┬───┘ └────┬───┘ └────┬───┘ └────┬───┘ └────┬───┘
        │             │          │          │          │          │
        ▼             ▼          ▼          ▼          ▼          ▼

┌─────────────────────────────────────────────────────────────────────────────┐
│                        PRODUCTION ACTION DETAILS                            │
└─────────────────────────────────────────────────────────────────────────────┘

  Request More Material:               Return Materials (Per WO):
  ┌─────────────────────┐              ┌─────────────────────┐
  │ - Item selection    │              │ - Scan item to      │
  │ - Quantity needed   │              │   return            │
  │ - Reason required   │              │ - Enter quantity    │
  │ - Creates Material  │              │ - Target warehouse  │
  │   Request for       │              │ - Stock Entry       │
  │   Storekeeper       │              │   (Return)          │
  └─────────────────────┘              └─────────────────────┘

  End Shift Return (WIP):              Print Label (FG Only):
  ┌─────────────────────┐              ┌─────────────────────┐
  │ - Retrieve WIP      │              │ - Create carton     │
  │   inventory for     │              │   label             │
  │   selected line     │              │ - QZ Tray silent    │
  │ - Enter quantities  │              │   print or browser  │
  │   to return         │              │   dialog            │
  │ - Bulk WIP return   │              │ - Uses FG print     │
  │   Stock Entry       │              │   format            │
  └─────────────────────┘              └─────────────────────┘

  Label History:                       End Work Order:
  ┌─────────────────────┐              ┌─────────────────────┐
  │ - List previous     │              │ - Enter good qty    │
  │   printed labels    │              │ - Enter reject qty  │
  │ - Reprint option    │              │ - Consume SFG items │
  │ - Split label into  │              │   from semi-        │
  │   multiple          │              │   finished WH       │
  │   quantities        │              │ - Complete Work     │
  └─────────────────────┘              │   Order             │
                                       └─────────────────────┘

  Close Production:
  ┌─────────────────────────────────────┐
  │ - Validation based on Factory       │
  │   Settings mode:                    │
  │   • No Validation                   │
  │   • All WOs Must Be Ended           │
  │   • Minimum WO Count                │
  │ - Consume packaging materials       │
  │ - Final production reconciliation   │
  └─────────────────────────────────────┘
```

**Key Data Flows:**

1. **Operator and Line Selection**
   - Operator selects employee profile
   - Selects one or more factory lines
   - System loads assigned work orders for those lines

2. **Work Order Queue with Status Chips**
   - Visual indicators: 🔵 Not Started, 🟡 In Process, 🟢 Completed
   - Real-time status updates
   - Click to select and load WO details

3. **Materials Snapshot**
   - Required: BOM-specified quantities
   - Transferred: Materials staged by Storekeeper Hub
   - Consumed: Materials scanned/used in production
   - Remaining: Outstanding materials needed
   - History: Recent transfers and issues

4. **Barcode Scanning and Validation**
   - Load Materials button activates scan mode
   - Barcode/item code entry
   - Validation: item in BOM, quantity available, no duplicate scan (45s window)
   - Auto-consumption via Stock Entry creation
   - Real-time snapshot updates

5. **Material Request Workflow**
   - Operator identifies shortage
   - Selects item, enters quantity and reason
   - System creates Material Request
   - Storekeeper receives notification
   - Additional materials staged and transferred

6. **Material Return Workflows**
   - **Per WO**: Return unused materials from specific work order
     - Scan item, enter quantity
     - Stock Entry (Material Return) created
     - Materials returned to source warehouse
   - **End Shift (WIP)**: Bulk return of work-in-progress
     - Retrieves all WIP for selected line
     - Operator enters return quantities
     - Batch return processing

7. **Label Printing with QZ Tray Integration**
   - Print Label: Creates carton label for finished goods
   - QZ Tray: Silent printing when enabled (no dialogs)
   - Browser fallback: Standard print dialog if QZ unavailable
   - Uses FG label print format from Factory Settings

8. **End Work Order with SFG Consumption**
   - Operator enters good and reject quantities
   - System consumes semi-finished goods (SFG) from designated warehouse
   - Work Order status updated to Completed
   - Production entry finalized

9. **Close Production with Packaging Consumption**
   - Validation per Factory Settings mode
   - Consumes packaging materials (boxes, labels, etc.)
   - Final reconciliation of production run
   - Closes out production session

---

## Detailed Operational Flows

### Storekeeper Hub Operations

#### 1. Start-of-Shift Setup

**Purpose:** Configure filters and settings for the day's material staging work.

**Steps:**
- Open Storekeeper Hub page
- **Select Factory Line**: Target production line for staging
- **Select Source Warehouse**: Warehouse to pull materials from
- **Set Production Date (Posting Date)**: Date for material staging (defaults to today)
- **Optional: Set Pallet ID**: Tag transfers with pallet reference for tracking
- Click **Refresh** to load latest work orders and staging data

**Result:** Hub displays work order buckets and activity panels filtered by your selections.

---

#### 2. Review Work Order Buckets

**Purpose:** Identify work orders grouped by common BOM for consolidated picking.

**How It Works:**
- Left column shows **WO Buckets**
- Each bucket contains work orders using the same BOM
- Enables consolidated material picking across multiple WOs

**Actions:**
- Click a bucket to view contained work orders
- Review production quantities and requirements
- Select bucket to populate pick cart

**Result:** Consolidated view of material needs across similar work orders.

---

#### 3. Build Consolidated Pick Cart

**Purpose:** Create a single staging list for materials needed across multiple work orders.

**Steps:**
- In center column, use **Consolidated Pick Cart**
- **Scan Barcodes**: Use barcode scanner or type item codes in scan field
- **Add Manual Rows**: Click to add items not in scan results
- **Adjust Details**: Modify quantities, select batches, add notes
- Cart shows aggregated quantities across all selected WOs

**Features:**
- Single staging list for multiple work orders
- Real-time quantity aggregation
- Batch selection and validation
- Notes for special handling

**Result:** Complete pick list ready for allocation and transfer creation.

---

#### 4. Allocate & Create Transfers

**Purpose:** Distribute pick cart quantities across work orders and generate stock entries.

**Process:**

**FIFO Allocation Engine:**
1. Sorts work orders by planned start date/time (earliest first)
2. Distributes cart quantities proportionally
3. Ensures oldest/earliest WOs are staged first
4. Validates batch availability

**Stock Entry Creation:**
1. Creates Material Transfer for Manufacture per WO
2. Moves items from source warehouse to WIP warehouse
3. Tags entries with optional pallet ID
4. Links entries to specific work orders

**Steps:**
- Click **Allocate & Create Transfers**
- System runs FIFO allocation
- Stock Entries created automatically
- Results displayed in "Created transfers" card

**Result:** Materials staged and ready for production, visible in activity tracking panel.

---

#### 5. Generate Picklist (Optional)

**Purpose:** Create consolidated picklist for warehouse picking teams.

**When to Use:**
- Large staging operations with multiple items
- Warehouse team needs organized picking sequence
- Batch-optimized picking routes

**Steps:**
- Select Stock Entries from created transfers
- Click **Generate Picklist**
- System creates Picklist document
- Picklist groups items for efficient picking

**Result:** Picklist document for warehouse team to execute material picking.

---

#### 6. Quick Stock Entry Actions

**Purpose:** Handle ad-hoc material movements outside of WO staging.

**Available Actions:**

**Mat. Transfer:**
- Create manual material transfer
- Move stock between warehouses
- Non-WO related transfers

**Mat. Issue:**
- Issue materials manually
- Non-production consumption
- Direct material usage

**Mat. Receipt:**
- Receive materials manually
- Returns from production
- Stock adjustments

**PO Receipt:**
- Create Purchase Receipt from PO
- Quick receiving workflow
- Bypasses standard form for speed

**Access Control:** Button visibility controlled by Factory Settings → Stock Entry Button Roles

**Result:** Flexible material handling for non-standard scenarios.

---

#### 7. Recent Activity & Tracking

**Purpose:** Monitor staged materials, manual entries, and pallet movements.

**Three Tracking Panels:**

**Staged (Production Date):**
- Shows transfers for selected production posting date
- Falls back to last 24 hours if no date selected
- Displays WO-linked material staging
- Real-time updates as transfers are created

**Recent Manual Stock Entries (Last 24h):**
- Manual transfers, issues, and receipts
- Non-WO related movements
- Ad-hoc material handling
- Chronological listing

**Pallet Tracker (Last 24h):**
- Displays pallet-tagged transfers
- Tracks pallet movements
- Links to specific pallets via Pallet ID
- Useful for logistics and shipping

**Use Cases:**
- Verify staging completion
- Track manual corrections
- Monitor pallet movements
- Audit material flow

**Result:** Complete visibility into all material movements and staging activities.

---

### Operator Hub Operations

#### 1. Set Operator & Line

**Purpose:** Identify the operator and assign factory line(s) for the session.

**Steps:**
- Click **Set Operator** → Select Employee profile
- Click **Set Line** → Select one or more Factory Lines
- System loads assigned work orders for selected lines

**Result:** Work Order Queue displays WOs assigned to your line(s).

---

#### 2. Select a Work Order

**Purpose:** Choose a work order from the queue to begin production.

**Process:**
- Queue displays WOs with status chips:
  - 🔵 **Not Started**: No production activity yet
  - 🟡 **In Process**: Currently in production
  - 🟢 **Completed**: Finished
- Click any WO to select
- Current Work Order banner loads at top
- Materials Snapshot displays for selected WO

**Result:** WO details and materials loaded, ready for production.

---

#### 3. Start / Pause / Resume

**Purpose:** Control work order production status.

**Start:**
- Enabled only when WO is fully staged (Allocated status)
- Begins production tracking
- Updates WO status to "In Process"

**Pause:**
- Temporarily stops production
- WO status changes to "Stopped"
- Button changes to **Resume**

**Resume:**
- Continues paused production
- WO status returns to "In Process"
- Button changes back to **Pause**

**Result:** Production status accurately tracked with automatic updates.

---

#### 4. Load / Scan Materials

**Purpose:** Consume materials via barcode scanning for real-time tracking.

**Workflow:**

1. Click **Load Materials** button
2. Scan mode activates
3. Scan barcode or type item code
4. System validates:
   - Item exists in BOM
   - Sufficient quantity available
   - No duplicate scan within 45 seconds (configurable)
5. Stock Entry (Material Consumption) created automatically
6. Materials Snapshot updates in real-time
7. Scan history panel shows recent entries

**Features:**
- Duplicate detection prevents accidental double-scans
- Auto-consumption (no manual SE creation needed)
- Real-time inventory updates
- Batch tracking
- Over-consumption warnings (threshold configurable in Factory Settings)

**Result:** Accurate material consumption with minimal operator effort.

---

#### 5. Request More Material

**Purpose:** Request additional materials when quantities are insufficient.

**When to Use:**
- Material shortages discovered during production
- Additional quantity needed beyond BOM
- Material quality issues requiring replacement

**Steps:**
1. Click **Request More Material**
2. Select item from BOM
3. Enter quantity needed
4. Provide reason for additional material
5. Submit request

**Process:**
- System creates Material Request
- Storekeeper receives notification
- Request visible in Storekeeper Hub
- Materials staged and transferred once fulfilled

**Result:** Material requests tracked and fulfilled by warehouse team.

---

#### 6. Return Materials (Per WO)

**Purpose:** Return unused materials from the current work order.

**When to Use:**
- Excess materials staged for WO
- Production complete with leftover materials
- Material not needed after all

**Steps:**
1. Click **Return Materials**
2. Scan item barcode or select from list
3. Enter quantity to return
4. Confirm target warehouse (usually source warehouse)
5. Submit return

**Process:**
- Stock Entry (Material Return) created
- Materials moved from WIP back to source warehouse
- Materials Snapshot updates
- Inventory corrected

**Result:** Unused materials returned to inventory, accurate WO costing.

---

#### 7. End Shift Return (WIP)

**Purpose:** Bulk return of work-in-progress materials at end of shift.

**When to Use:**
- End of production shift
- Multiple WOs with leftover WIP
- Batch cleanup of remaining materials

**Steps:**
1. Click **End Shift Return**
2. System retrieves all WIP inventory for selected line
3. Operator reviews list of WIP items
4. Enter quantities to return for each item
5. Submit bulk return

**Process:**
- Single Stock Entry for all WIP returns
- Materials moved from WIP to source warehouse
- Batch processing for efficiency
- Inventory reconciliation

**Result:** Clean WIP inventory at shift end, ready for next shift.

---

#### 8. Print Label (FG Only)

**Purpose:** Create and print carton labels for finished goods.

**When to Use:**
- Finished goods ready for packaging
- Carton labeling required
- Finished product identification

**Steps:**
1. Click **Print Label**
2. System creates Label Record
3. Label data populated (item, quantity, batch, dates)
4. Printing options:
   - **QZ Tray Enabled**: Silent print to configured printer (no dialog)
   - **QZ Tray Disabled**: Browser print dialog appears
5. Label prints to designated FG label printer

**Configuration:**
- Uses FG Label Print Format from Factory Settings
- Default FG label printer from Factory Settings or user defaults
- QZ Tray integration optional (requires client-side installation)

**Result:** Professional carton labels printed for finished goods.

---

#### 9. Label History

**Purpose:** View, reprint, and manage previously printed labels.

**Features:**

**View History:**
- Lists all labels printed for current WO
- Shows label details (item, quantity, batch, timestamp)
- Searchable and filterable

**Reprint:**
- Select any previous label
- Click **Reprint**
- Label reprinted to configured printer

**Split Label:**
- Select a label with multiple quantities
- Click **Split**
- Enter new quantity breakdown
- Creates multiple labels from original

**Use Cases:**
- Damaged labels need reprinting
- Large carton needs splitting into smaller units
- Audit trail of printed labels

**Result:** Complete label management and audit trail.

---

#### 10. End Work Order

**Purpose:** Complete work order with final quantities and SFG consumption.

**When to Use:**
- All production for WO is complete
- Ready to report good and reject quantities
- Final inventory consumption needed

**Steps:**
1. Click **End Work Order** or **Close** button
2. Enter **Good Quantity** (acceptable finished goods)
3. Enter **Reject Quantity** (defective/scrapped units)
4. If BOM includes semi-finished goods (SFG):
   - System prompts for SFG consumption
   - Enter actual SFG quantities used
   - SFG consumed from Semi-Finished Warehouse
5. Submit completion

**Process:**
- Work Order status updated to Completed
- Stock Entry created for FG production
- SFG consumption recorded (if applicable)
- Production costs calculated
- WO removed from active queue

**Result:** Work order completed with accurate production and consumption data.

---

#### 11. Close Production

**Purpose:** Final production session closure with packaging consumption.

**When to Use:**
- All work orders for the line are complete (or validation threshold met)
- Ready to close production run
- Packaging materials need final consumption

**Validation Modes (Factory Settings):**

**No Validation:**
- Close production at any time
- No WO completion requirements

**All WOs on Line Must Be Ended:**
- All work orders assigned to line must be completed
- Prevents partial closures
- Ensures complete production run

**Minimum Number of WOs:**
- Configurable minimum WO count must be ended
- Flexible threshold for different production scenarios
- Default: 1 WO minimum

**Steps:**
1. Click **Close Production**
2. System validates per configured mode
3. If validation passes:
   - Enter packaging material quantities used (boxes, labels, etc.)
   - System consumes packaging from designated warehouse
   - Final production reconciliation
4. Production session closed

**Packaging Consumption:**
- Packaging item groups defined in Factory Settings
- Auto-consumes packaging materials
- Accurate packaging inventory tracking

**Result:** Production run fully closed, all materials consumed, ready for next session.

---

## Custom DocTypes

### Factory Settings
**Purpose:** Centralized MES configuration  
**Type:** Single DocType (one instance)  
**Key Fields:** All MES settings including scanning, consumption, label printing, line rules

### Factory Line
**Purpose:** Define production lines with warehouse mappings  
**Key Fields:** Line name, source warehouse, WIP warehouse, FG warehouse, SFG warehouse

### Picklist
**Purpose:** Consolidated picking lists for warehouse teams  
**Key Fields:** Posting date, items, quantities, locations

### Picklist Item
**Purpose:** Line items for picklists  
**Key Fields:** Item code, quantity, warehouse, batch

### Picklist Transfer
**Purpose:** Link picklists to stock entries  
**Key Fields:** Picklist reference, stock entry reference

### Label Template
**Purpose:** Define label layouts and data  
**Key Fields:** Template name, label format, print format

### Label Record
**Purpose:** Track printed labels  
**Key Fields:** Work order, item, quantity, batch, print timestamp

### Label Print Job
**Purpose:** Queue and track label print jobs  
**Key Fields:** Label record, printer, status, QZ Tray config

### Storekeeper Hub Role
**Purpose:** Configure role-based button visibility  
**Key Fields:** Role name, button permissions

### Service Invoice
**Purpose:** Service-based invoicing with multi-currency  
**Key Fields:** Customer, currency, exchange rate, VAT, line items

### Service Invoice Items
**Purpose:** Line items for service invoices  
**Key Fields:** Service description, quantity, rate, amount, VAT

### Customer Discount Rules
**Purpose:** Customer-specific discount configurations  
**Key Fields:** Customer, discount percentage, item group, validity

### User Printer Default
**Purpose:** User-specific printer preferences  
**Key Fields:** User, default label printer, default A4 printer

### Line Warehouse Map
**Purpose:** Map warehouses to factory lines  
**Key Fields:** Factory line, source warehouse, WIP warehouse, FG warehouse, SFG warehouse

### Line Allowed Item Groups
**Purpose:** Restrict items allowed on specific lines  
**Key Fields:** Factory line, item group

### Line Backflush Item Groups
**Purpose:** Define backflush item groups per line  
**Key Fields:** Factory line, item group

### Line Packaging Item Groups
**Purpose:** Define packaging item groups per line  
**Key Fields:** Factory line, item group

### Pallet UOM Option
**Purpose:** Configure pallet UOM types  
**Key Fields:** UOM code, description

---

## Installation & Configuration

### Prerequisites

- **Frappe Framework:** v15.x
- **ERPNext:** v15.x
- **Python:** 3.10 or higher
- **Operating System:** Linux (Ubuntu 20.04+ recommended)

### Installation

1. **Navigate to your Frappe bench directory:**

   ```bash
   cd /path/to/frappe-bench
   ```

2. **Get the ISNACK app:**

   ```bash
   bench get-app https://github.com/KevinBusuttil/isnack.git
   ```

3. **Install the app on your site:**

   ```bash
   bench --site your-site-name install-app isnack
   ```

4. **Run database migrations:**

   ```bash
   bench --site your-site-name migrate
   ```

5. **Clear cache and rebuild assets:**

   ```bash
   bench --site your-site-name clear-cache
   bench --site your-site-name build
   ```

6. **Restart bench:**

   ```bash
   bench restart
   ```

### Configuration

#### 1. Configure Factory Settings

Navigate to: **Home → Manufacturing → Factory Settings**

**General Configuration:**
- Set **Batch Space Handling** (default: Convert to Underscore)
- Configure **Duplicate Scan Window** (default: 45 seconds)
- Set **Max Active Operators per Job** (default: 2)
- Set **Material Over-consumption Threshold** (default: 150%)

**Close Production:**
- Choose **Close Production Validation Mode**
- Set **Minimum WO Count** if using Minimum Number of WOs mode

**Storekeeper Hub:**
- Add roles to **Roles for Stock Entry Buttons** to control button visibility

**Item Group Policies:**
- Add **Packaging Item Groups**
- Add **Backflush Item Groups**
- Add **Allowed Item Groups** per line

**Label Printing:**
- Set **Default Label Template**
- Set **Default Label Print Format** (pallet labels)
- Set **Default FG Label Print Format** (carton labels)
- Set **Default Label Printer**
- Set **Default A4 Printer**
- Enable **Silent Printing (QZ Tray)** if using QZ Tray client

**Pallet UOM Options:**
- Add allowed pallet UOM types (e.g., EURO 1, EURO 4)

#### 2. Setup Factory Lines

Navigate to: **Home → Manufacturing → Factory Line**

**For each production line, create:**
- Line name and description
- Source Warehouse (where materials are pulled from)
- WIP Warehouse (work-in-progress staging)
- FG Warehouse (finished goods)
- SFG Warehouse (semi-finished goods)

**Per-Line Configuration:**
- Map line to warehouses in Factory Settings → Line Warehouse Map
- Configure allowed item groups per line
- Set backflush and packaging item groups

#### 3. Setup Label Templates (Optional)

Navigate to: **Home → Manufacturing → Label Template**

**Configure:**
- Template name
- Label format (dimensions, layout)
- Print format selection
- QZ Tray printer configuration

#### 4. Setup QZ Tray for Silent Printing (Optional)

**Client-Side Setup:**
1. Download and install [QZ Tray](https://qz.io/download/) on operator PCs
2. Configure network printers in QZ Tray
3. Enable **Silent Printing** in Factory Settings

**Server-Side:**
- No additional configuration needed
- ISNACK automatically detects QZ Tray presence
- Falls back to browser dialogs if unavailable

#### 5. User Permissions

**Assign roles:**
- **Storekeeper Hub Role**: For warehouse staff using Storekeeper Hub
- **Manufacturing User**: For operators using Operator Hub
- **System Manager**: For Factory Settings configuration

**Configure permissions:**
- Grant users access to required pages
- Set up role-based button visibility in Factory Settings

#### 6. Configure Discount Rules (Optional)

Navigate to: **Home → Selling → Customer Discount Rules**

**For each customer:**
- Select customer
- Define discount percentage
- Specify item groups (if applicable)
- Set validity dates

---

## License

MIT License

Copyright (c) 2024-2026 Busuttil Technologies Limited

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

---

**For support, please contact:**  
📧 kevin.busuttil@busuttil-technologies.com  
🏢 Busuttil Technologies Limited