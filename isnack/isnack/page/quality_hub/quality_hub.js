frappe.provide("isnack.quality_hub");

isnack.quality_hub.DIALOG_RECORD_CONFIG = {
    "QC Puffs Extruder Record": {
        child_table_field: "readings",
        child_label: __("Readings"),
        min_rows: 1,
        parent_fields: [
            { fieldname: "record_date", fieldtype: "Date", label: __("Record Date"), reqd: 1, default: frappe.datetime.get_today() },
            { fieldname: "shift", fieldtype: "Select", label: __("Shift"), reqd: 1, options: "\nMorning\nAfternoon\nNight" },
            { fieldname: "factory_line", fieldtype: "Link", label: __("Factory Line"), options: "Factory Line" },
            { fieldname: "work_order", fieldtype: "Link", label: __("Work Order"), options: "Work Order" },
            { fieldname: "operator_name", fieldtype: "Data", label: __("Operator Name") },
            { fieldname: "qc_inspector", fieldtype: "Link", label: __("QC Inspector"), options: "User", default: frappe.session.user },
            { fieldname: "product_item", fieldtype: "Link", label: __("Product Item"), options: "Item" },
            { fieldname: "overall_status", fieldtype: "Select", label: __("Overall Status"), options: "\nPass\nFail" },
            { fieldname: "remarks", fieldtype: "Small Text", label: __("Remarks") },
        ],
        child_fields: [
            { fieldname: "time_slot", fieldtype: "Time", label: __("Time Slot") },
            { fieldname: "screw_speed_rpm", fieldtype: "Float", label: __("Screw Speed (RPM)") },
            { fieldname: "barrel_temp_zone_1", fieldtype: "Float", label: __("Barrel Temp Zone 1 (°C)") },
            { fieldname: "barrel_temp_zone_2", fieldtype: "Float", label: __("Barrel Temp Zone 2 (°C)") },
            { fieldname: "barrel_temp_zone_3", fieldtype: "Float", label: __("Barrel Temp Zone 3 (°C)") },
            { fieldname: "die_pressure", fieldtype: "Float", label: __("Die Pressure (bar)") },
            { fieldname: "moisture_content", fieldtype: "Float", label: __("Moisture Content (%)") },
            { fieldname: "product_density", fieldtype: "Float", label: __("Product Density") },
            { fieldname: "reading_remarks", fieldtype: "Small Text", label: __("Remarks") },
        ],
    },
    "QC Rice Extruder Record": {
        child_table_field: "readings",
        child_label: __("Readings"),
        min_rows: 1,
        parent_fields: [
            { fieldname: "record_date", fieldtype: "Date", label: __("Record Date"), reqd: 1, default: frappe.datetime.get_today() },
            { fieldname: "shift", fieldtype: "Select", label: __("Shift"), reqd: 1, options: "\nMorning\nAfternoon\nNight" },
            { fieldname: "factory_line", fieldtype: "Link", label: __("Factory Line"), options: "Factory Line" },
            { fieldname: "work_order", fieldtype: "Link", label: __("Work Order"), options: "Work Order" },
            { fieldname: "operator_name", fieldtype: "Data", label: __("Operator Name") },
            { fieldname: "qc_inspector", fieldtype: "Link", label: __("QC Inspector"), options: "User", default: frappe.session.user },
            { fieldname: "product_item", fieldtype: "Link", label: __("Product Item"), options: "Item" },
            { fieldname: "overall_status", fieldtype: "Select", label: __("Overall Status"), options: "\nPass\nFail" },
            { fieldname: "remarks", fieldtype: "Small Text", label: __("Remarks") },
        ],
        child_fields: [
            { fieldname: "time_slot", fieldtype: "Time", label: __("Time Slot") },
            { fieldname: "screw_speed_rpm", fieldtype: "Float", label: __("Screw Speed (RPM)") },
            { fieldname: "barrel_temp_zone_1", fieldtype: "Float", label: __("Barrel Temp Zone 1 (°C)") },
            { fieldname: "barrel_temp_zone_2", fieldtype: "Float", label: __("Barrel Temp Zone 2 (°C)") },
            { fieldname: "barrel_temp_zone_3", fieldtype: "Float", label: __("Barrel Temp Zone 3 (°C)") },
            { fieldname: "die_pressure", fieldtype: "Float", label: __("Die Pressure (bar)") },
            { fieldname: "moisture_content", fieldtype: "Float", label: __("Moisture Content (%)") },
            { fieldname: "product_density", fieldtype: "Float", label: __("Product Density") },
            { fieldname: "reading_remarks", fieldtype: "Small Text", label: __("Remarks") },
        ],
    },
    "QC Frying Line Record": {
        child_table_field: "readings",
        child_label: __("Readings"),
        min_rows: 1,
        parent_fields: [
            { fieldname: "record_date", fieldtype: "Date", label: __("Record Date"), reqd: 1, default: frappe.datetime.get_today() },
            { fieldname: "shift", fieldtype: "Select", label: __("Shift"), reqd: 1, options: "\nMorning\nAfternoon\nNight" },
            { fieldname: "factory_line", fieldtype: "Link", label: __("Factory Line"), options: "Factory Line" },
            { fieldname: "work_order", fieldtype: "Link", label: __("Work Order"), options: "Work Order" },
            { fieldname: "operator_name", fieldtype: "Data", label: __("Operator Name") },
            { fieldname: "qc_inspector", fieldtype: "Link", label: __("QC Inspector"), options: "User", default: frappe.session.user },
            { fieldname: "product_item", fieldtype: "Link", label: __("Product Item"), options: "Item" },
            { fieldname: "overall_status", fieldtype: "Select", label: __("Overall Status"), options: "\nPass\nFail" },
            { fieldname: "remarks", fieldtype: "Small Text", label: __("Remarks") },
        ],
        child_fields: [
            { fieldname: "time_slot", fieldtype: "Time", label: __("Time Slot") },
            { fieldname: "oil_temperature", fieldtype: "Float", label: __("Oil Temperature (°C)") },
            { fieldname: "oil_ffa", fieldtype: "Float", label: __("Oil FFA") },
            { fieldname: "oil_tpm", fieldtype: "Float", label: __("Oil TPM") },
            { fieldname: "product_temperature", fieldtype: "Float", label: __("Product Temp (°C)") },
            { fieldname: "product_moisture", fieldtype: "Float", label: __("Product Moisture (%)") },
            { fieldname: "oil_change_flag", fieldtype: "Check", label: __("Oil Changed") },
            { fieldname: "reading_remarks", fieldtype: "Small Text", label: __("Remarks") },
        ],
    },
    "QC Oven Record": {
        child_table_field: "readings",
        child_label: __("Readings"),
        min_rows: 1,
        parent_fields: [
            { fieldname: "record_date", fieldtype: "Date", label: __("Record Date"), reqd: 1, default: frappe.datetime.get_today() },
            { fieldname: "shift", fieldtype: "Select", label: __("Shift"), reqd: 1, options: "\nMorning\nAfternoon\nNight" },
            { fieldname: "factory_line", fieldtype: "Link", label: __("Factory Line"), options: "Factory Line" },
            { fieldname: "work_order", fieldtype: "Link", label: __("Work Order"), options: "Work Order" },
            { fieldname: "operator_name", fieldtype: "Data", label: __("Operator Name") },
            { fieldname: "qc_inspector", fieldtype: "Link", label: __("QC Inspector"), options: "User", default: frappe.session.user },
            { fieldname: "product_item", fieldtype: "Link", label: __("Product Item"), options: "Item" },
            { fieldname: "overall_status", fieldtype: "Select", label: __("Overall Status"), options: "\nPass\nFail" },
            { fieldname: "remarks", fieldtype: "Small Text", label: __("Remarks") },
        ],
        child_fields: [
            { fieldname: "time_slot", fieldtype: "Time", label: __("Time Slot") },
            { fieldname: "zone_1_temp", fieldtype: "Float", label: __("Zone 1 Temp (°C)") },
            { fieldname: "zone_2_temp", fieldtype: "Float", label: __("Zone 2 Temp (°C)") },
            { fieldname: "zone_3_temp", fieldtype: "Float", label: __("Zone 3 Temp (°C)") },
            { fieldname: "belt_speed", fieldtype: "Float", label: __("Belt Speed") },
            { fieldname: "moisture", fieldtype: "Float", label: __("Moisture (%)") },
            { fieldname: "colour_value", fieldtype: "Float", label: __("Colour Value") },
            { fieldname: "reading_remarks", fieldtype: "Small Text", label: __("Remarks") },
        ],
    },
    "QC Tasting Record": {
        child_table_field: "scores",
        child_label: __("Scores"),
        min_rows: 1,
        parent_fields: [
            { fieldname: "record_date", fieldtype: "Date", label: __("Record Date"), reqd: 1, default: frappe.datetime.get_today() },
            { fieldname: "shift", fieldtype: "Select", label: __("Shift"), reqd: 1, options: "\nMorning\nAfternoon\nNight" },
            { fieldname: "factory_line", fieldtype: "Link", label: __("Factory Line"), options: "Factory Line" },
            { fieldname: "work_order", fieldtype: "Link", label: __("Work Order"), options: "Work Order" },
            { fieldname: "operator_name", fieldtype: "Data", label: __("Operator Name") },
            { fieldname: "qc_inspector", fieldtype: "Link", label: __("QC Inspector"), options: "User", default: frappe.session.user },
            { fieldname: "item_code", fieldtype: "Link", label: __("Item Code"), options: "Item" },
            { fieldname: "batch_no", fieldtype: "Link", label: __("Batch No"), options: "Batch" },
            { fieldname: "pass_threshold", fieldtype: "Float", label: __("Pass Threshold"), default: 3.0 },
            { fieldname: "remarks", fieldtype: "Small Text", label: __("Remarks") },
        ],
        child_fields: [
            { fieldname: "taster_name", fieldtype: "Data", label: __("Taster Name") },
            { fieldname: "appearance_score", fieldtype: "Rating", label: __("Appearance") },
            { fieldname: "colour_score", fieldtype: "Rating", label: __("Colour") },
            { fieldname: "aroma_score", fieldtype: "Rating", label: __("Aroma") },
            { fieldname: "taste_score", fieldtype: "Rating", label: __("Taste") },
            { fieldname: "texture_score", fieldtype: "Rating", label: __("Texture") },
            { fieldname: "overall_score", fieldtype: "Rating", label: __("Overall") },
            { fieldname: "comments", fieldtype: "Small Text", label: __("Comments") },
        ],
    },
    "QC Metal Detector Log": {
        child_table_field: "tests",
        child_label: __("Tests"),
        min_rows: 1,
        parent_fields: [
            { fieldname: "record_date", fieldtype: "Date", label: __("Record Date"), reqd: 1, default: frappe.datetime.get_today() },
            { fieldname: "shift", fieldtype: "Select", label: __("Shift"), reqd: 1, options: "\nMorning\nAfternoon\nNight" },
            { fieldname: "factory_line", fieldtype: "Link", label: __("Factory Line"), options: "Factory Line" },
            { fieldname: "work_order", fieldtype: "Link", label: __("Work Order"), options: "Work Order" },
            { fieldname: "operator_name", fieldtype: "Data", label: __("Operator Name") },
            { fieldname: "qc_inspector", fieldtype: "Link", label: __("QC Inspector"), options: "User", default: frappe.session.user },
            { fieldname: "metal_detector_id", fieldtype: "Data", label: __("Metal Detector ID") },
            { fieldname: "detector_make_model", fieldtype: "Data", label: __("Make/Model") },
            { fieldname: "corrective_action", fieldtype: "Small Text", label: __("Corrective Action") },
            { fieldname: "last_calibration_date", fieldtype: "Date", label: __("Last Calibration Date") },
            { fieldname: "next_calibration_date", fieldtype: "Date", label: __("Next Calibration Date") },
            { fieldname: "calibration_certificate", fieldtype: "Attach", label: __("Calibration Certificate") },
            { fieldname: "remarks", fieldtype: "Small Text", label: __("Remarks") },
        ],
        child_fields: [
            { fieldname: "test_time", fieldtype: "Time", label: __("Test Time") },
            { fieldname: "test_piece_type", fieldtype: "Select", label: __("Test Piece Type"), options: "\nFe\nNon-Fe\nStainless" },
            { fieldname: "test_piece_size_mm", fieldtype: "Float", label: __("Test Piece Size (mm)") },
            { fieldname: "detected", fieldtype: "Check", label: __("Detected (Pass)") },
            { fieldname: "sensitivity_setting", fieldtype: "Data", label: __("Sensitivity Setting") },
            { fieldname: "test_remarks", fieldtype: "Small Text", label: __("Remarks") },
        ],
    },
    "QC Weight Check": {
        child_table_field: "samples",
        child_label: __("Samples"),
        min_rows: 1,
        parent_fields: [
            { fieldname: "record_date", fieldtype: "Date", label: __("Record Date"), reqd: 1, default: frappe.datetime.get_today() },
            { fieldname: "shift", fieldtype: "Select", label: __("Shift"), reqd: 1, options: "\nMorning\nAfternoon\nNight" },
            { fieldname: "factory_line", fieldtype: "Link", label: __("Factory Line"), options: "Factory Line" },
            { fieldname: "work_order", fieldtype: "Link", label: __("Work Order"), options: "Work Order" },
            { fieldname: "operator_name", fieldtype: "Data", label: __("Operator Name") },
            { fieldname: "qc_inspector", fieldtype: "Link", label: __("QC Inspector"), options: "User", default: frappe.session.user },
            { fieldname: "item_code", fieldtype: "Link", label: __("Item Code"), options: "Item" },
            { fieldname: "batch_no", fieldtype: "Link", label: __("Batch No"), options: "Batch" },
            { fieldname: "nominal_weight", fieldtype: "Float", label: __("Nominal Weight (g)") },
            { fieldname: "tu1_limit", fieldtype: "Float", label: __("TU1 Limit (g)") },
            { fieldname: "tu2_limit", fieldtype: "Float", label: __("TU2 Limit (g)") },
            { fieldname: "overall_status", fieldtype: "Select", label: __("Overall Status"), options: "\nPass\nFail" },
            { fieldname: "remarks", fieldtype: "Small Text", label: __("Remarks") },
        ],
        child_fields: [
            { fieldname: "sample_no", fieldtype: "Int", label: __("Sample No") },
            { fieldname: "gross_weight", fieldtype: "Float", label: __("Gross Weight (g)") },
            { fieldname: "tare_weight", fieldtype: "Float", label: __("Tare Weight (g)") },
        ],
    },
};

frappe.pages["quality-hub"].on_page_load = function (wrapper) {
    isnack.quality_hub.page = new isnack.quality_hub.QualityHub(wrapper);
};

isnack.quality_hub.QualityHub = class {
    constructor(wrapper) {
        this.wrapper = $(wrapper);
        this.page = frappe.ui.make_app_page({
            parent: wrapper,
            title: __("Quality Hub"),
            single_column: true,
        });

        this.$main = this.wrapper.find(".layout-main-section");
        this.$main.empty();

        this.active_tab = "monitor";
        this.active_process_sub = "puffs";
        this.active_pkg_sub = "packaging";
        this.make_layout();
        this.bind_tabs();
        this.start_clock();
        this.refresh_data(false);
        this.start_polling();
        this.show_tab("monitor");
    }

    make_layout() {
        this.$container = $(`
            <div class="quality-hub-wrapper">
                <div class="qh-header">
                    <div>
                        <div class="qh-header-subtitle qh-header-subtitle-standalone">
                            ${__("Central entry point for all Quality Control records.")}
                        </div>
                    </div>
                    <div class="qh-header-right text-right">
                        <div>
                            <span class="qh-pill qh-pill-live">
                                <i class="fa fa-circle"></i>&nbsp;${__("Live monitoring")}
                            </span>
                        </div>
                        <div class="qh-header-subtitle" data-role="current-time"></div>
                    </div>
                </div>

                <div class="qh-tabs">
                    <button class="qh-tab qh-tab-active" data-tab="monitor">${__("Live Monitor")}</button>
                    <button class="qh-tab" data-tab="receiving">${__("Receiving (QCA)")}</button>
                    <button class="qh-tab" data-tab="process">${__("Process (QCB–QCE)")}</button>
                    <button class="qh-tab" data-tab="tasting">${__("Tasting (QCF)")}</button>
                    <button class="qh-tab" data-tab="pkg_weight">${__("Pkg & Weight (QCG/QCI)")}</button>
                    <button class="qh-tab" data-tab="metal">${__("CCP & Metal (QCH)")}</button>
                    <button class="qh-tab" data-tab="reports">${__("Reports & Trends")}</button>
                </div>

                <!-- TAB: Live Monitor -->
                <div class="qh-tab-content" data-content="monitor">
                    <div class="qh-stat-grid qh-stat-grid-2col">
                        <div class="qh-card qh-card-stat-success">
                            <div class="qh-card-label">${__("Completed last hour")}</div>
                            <div class="qh-card-value" data-role="stat-completed-hour">0</div>
                        </div>
                        <div class="qh-card qh-card-stat-danger">
                            <div class="qh-card-label">${__("Open non-conformances")}</div>
                            <div class="qh-card-value" data-role="stat-nc">0</div>
                        </div>
                    </div>
                    <div class="qh-stat-grid qh-qc-summary-grid" data-role="qc-summary-grid">
                    </div>
                    <div class="qh-layout">
                        <div class="qh-panel">
                            <div class="qh-panel-header">
                                <div class="qh-panel-title qh-panel-title-out-of-range">${__("Recent Out-of-Range Readings")}</div>
                                <span class="qh-badge qh-badge-amber" data-role="badge-out-of-range">
                                    0 ${__("events")}
                                </span>
                            </div>
                            <div data-role="table-out-of-range"></div>
                        </div>
                    </div>
                </div>

                <!-- TAB: Receiving -->
                <div class="qh-tab-content" data-content="receiving" style="display:none">
                    <div class="qh-filter-bar">
                        <input type="date" class="form-control qh-filter-input" data-filter="record_date" placeholder="${__("Date")}">
                        <input type="text" class="form-control qh-filter-input" data-filter="supplier" placeholder="${__("Supplier")}">
                        <select class="form-control qh-filter-input" data-filter="docstatus">
                            <option value="">${__("All Status")}</option>
                            <option value="0">${__("Draft")}</option>
                            <option value="1">${__("Submitted")}</option>
                        </select>
                        <button class="btn btn-sm btn-default qh-filter-apply" data-target="receiving">${__("Filter")}</button>
                        <button class="btn btn-sm btn-primary qh-new-record" data-doctype="QC Receiving Record">
                            <i class="fa fa-plus"></i> ${__("New Record")}
                        </button>
                    </div>
                    <div class="qh-panel">
                        <div data-role="list-receiving"></div>
                    </div>
                </div>

                <!-- TAB: Process Records -->
                <div class="qh-tab-content" data-content="process" style="display:none">
                    <div class="qh-sub-nav">
                        <button class="qh-pill-nav qh-pill-active" data-sub="puffs">${__("Puffs Extruder (QCB)")}</button>
                        <button class="qh-pill-nav" data-sub="rice">${__("Rice Extruder (QCC)")}</button>
                        <button class="qh-pill-nav" data-sub="frying">${__("Frying Line (QCD)")}</button>
                        <button class="qh-pill-nav" data-sub="oven">${__("Oven (QCE)")}</button>
                    </div>
                    <div class="qh-filter-bar">
                        <input type="date" class="form-control qh-filter-input" data-filter="record_date" placeholder="${__("Date")}">
                        <input type="text" class="form-control qh-filter-input" data-filter="work_order" placeholder="${__("Work Order")}">
                        <input type="text" class="form-control qh-filter-input" data-filter="factory_line" placeholder="${__("Line")}">
                        <select class="form-control qh-filter-input" data-filter="docstatus">
                            <option value="">${__("All Status")}</option>
                            <option value="0">${__("Draft")}</option>
                            <option value="1">${__("Submitted")}</option>
                        </select>
                        <button class="btn btn-sm btn-default qh-filter-apply" data-target="process">${__("Filter")}</button>
                        <button class="btn btn-sm btn-primary qh-new-record" data-doctype="QC Puffs Extruder Record">
                            <i class="fa fa-plus"></i> ${__("New Record")}
                        </button>
                    </div>
                    <div class="qh-panel">
                        <div data-role="list-process"></div>
                    </div>
                </div>

                <!-- TAB: Tasting -->
                <div class="qh-tab-content" data-content="tasting" style="display:none">
                    <div class="qh-filter-bar">
                        <input type="date" class="form-control qh-filter-input" data-filter="record_date" placeholder="${__("Date")}">
                        <input type="text" class="form-control qh-filter-input" data-filter="factory_line" placeholder="${__("Line")}">
                        <select class="form-control qh-filter-input" data-filter="docstatus">
                            <option value="">${__("All Status")}</option>
                            <option value="0">${__("Draft")}</option>
                            <option value="1">${__("Submitted")}</option>
                        </select>
                        <button class="btn btn-sm btn-default qh-filter-apply" data-target="tasting">${__("Filter")}</button>
                        <button class="btn btn-sm btn-primary qh-new-record" data-doctype="QC Tasting Record">
                            <i class="fa fa-plus"></i> ${__("New Record")}
                        </button>
                    </div>
                    <div class="qh-panel">
                        <div data-role="list-tasting"></div>
                    </div>
                </div>

                <!-- TAB: Packaging & Weight -->
                <div class="qh-tab-content" data-content="pkg_weight" style="display:none">
                    <div class="qh-sub-nav">
                        <button class="qh-pill-nav qh-pill-active" data-sub="packaging">${__("Packaging Checks (QCG)")}</button>
                        <button class="qh-pill-nav" data-sub="weight">${__("Weight Checks (QCI)")}</button>
                    </div>
                    <div class="qh-filter-bar">
                        <input type="date" class="form-control qh-filter-input" data-filter="record_date" placeholder="${__("Date")}">
                        <input type="text" class="form-control qh-filter-input" data-filter="work_order" placeholder="${__("Work Order")}">
                        <select class="form-control qh-filter-input" data-filter="docstatus">
                            <option value="">${__("All Status")}</option>
                            <option value="0">${__("Draft")}</option>
                            <option value="1">${__("Submitted")}</option>
                        </select>
                        <button class="btn btn-sm btn-default qh-filter-apply" data-target="pkg_weight">${__("Filter")}</button>
                        <button class="btn btn-sm btn-primary qh-new-record" data-doctype="QC Packaging Check">
                            <i class="fa fa-plus"></i> ${__("New Record")}
                        </button>
                    </div>
                    <div class="qh-panel">
                        <div data-role="list-pkg_weight"></div>
                    </div>
                </div>

                <!-- TAB: CCP & Metal Detector -->
                <div class="qh-tab-content" data-content="metal" style="display:none">
                    <div class="qh-ccp-alert" data-role="ccp-alert">
                        <i class="fa fa-shield"></i>
                        <span data-role="ccp-alert-text">${__("Loading CCP status...")}</span>
                    </div>
                    <div class="qh-filter-bar">
                        <input type="date" class="form-control qh-filter-input" data-filter="record_date" placeholder="${__("Date")}">
                        <input type="text" class="form-control qh-filter-input" data-filter="metal_detector_id" placeholder="${__("Detector ID")}">
                        <select class="form-control qh-filter-input" data-filter="docstatus">
                            <option value="">${__("All Status")}</option>
                            <option value="0">${__("Draft")}</option>
                            <option value="1">${__("Submitted")}</option>
                        </select>
                        <button class="btn btn-sm btn-default qh-filter-apply" data-target="metal">${__("Filter")}</button>
                        <button class="btn btn-sm btn-primary qh-new-record" data-doctype="QC Metal Detector Log">
                            <i class="fa fa-plus"></i> ${__("New Record")}
                        </button>
                    </div>
                    <div class="qh-panel">
                        <div data-role="list-metal"></div>
                    </div>
                </div>

                <!-- TAB: Reports & Trends -->
                <div class="qh-tab-content" data-content="reports" style="display:none">
                    <div class="qh-panel" style="margin-bottom:1.2rem">
                        <div class="qh-panel-header">
                            <div class="qh-panel-title">${__("Today's Completion Matrix")}</div>
                            <input type="date" class="form-control" data-role="matrix-date" style="width:auto">
                            <button class="btn btn-sm btn-default" data-role="matrix-refresh">${__("Refresh")}</button>
                        </div>
                        <div data-role="completion-matrix"></div>
                    </div>
                    <div class="qh-panel">
                        <div class="qh-panel-title" style="margin-bottom:0.75rem">${__("Quick Links")}</div>
                        <div class="qh-quick-links">
                            <a class="btn btn-sm btn-default qh-ql-blue" href="#List/QC Receiving Record">${__("Receiving Records")}</a>
                            <a class="btn btn-sm btn-default qh-ql-green" href="#List/QC Puffs Extruder Record">${__("Puffs Extruder")}</a>
                            <a class="btn btn-sm btn-default qh-ql-green" href="#List/QC Rice Extruder Record">${__("Rice Extruder")}</a>
                            <a class="btn btn-sm btn-default qh-ql-green" href="#List/QC Frying Line Record">${__("Frying Line")}</a>
                            <a class="btn btn-sm btn-default qh-ql-green" href="#List/QC Oven Record">${__("Oven Records")}</a>
                            <a class="btn btn-sm btn-default qh-ql-violet" href="#List/QC Tasting Record">${__("Tasting Records")}</a>
                            <a class="btn btn-sm btn-default qh-ql-teal" href="#List/QC Packaging Check">${__("Packaging Checks")}</a>
                            <a class="btn btn-sm btn-default qh-ql-amber" href="#List/QC Metal Detector Log">${__("Metal Detector Logs")}</a>
                            <a class="btn btn-sm btn-default qh-ql-teal" href="#List/QC Weight Check">${__("Weight Checks")}</a>
                        </div>
                    </div>
                </div>
            </div>
        `).appendTo(this.$main);
    }

    bind_tabs() {
        // Main tabs
        this.$container.on("click", ".qh-tab", (e) => {
            const tab = $(e.currentTarget).data("tab");
            this.show_tab(tab);
        });

        // Process sub-nav pills
        this.$container.on("click", ".qh-pill-nav", (e) => {
            const $btn = $(e.currentTarget);
            $btn.closest(".qh-sub-nav").find(".qh-pill-nav").removeClass("qh-pill-active");
            $btn.addClass("qh-pill-active");

            const sub = $btn.data("sub");
            const tab = this.active_tab;

            if (tab === "process") {
                this.active_process_sub = sub;
                const dtmap = {
                    puffs: "QC Puffs Extruder Record",
                    rice: "QC Rice Extruder Record",
                    frying: "QC Frying Line Record",
                    oven: "QC Oven Record",
                };
                this.$container.find("[data-target='process']").closest(".qh-filter-bar")
                    .find(".qh-new-record").data("doctype", dtmap[sub]);
                this.load_records("process", {});
            } else if (tab === "pkg_weight") {
                this.active_pkg_sub = sub;
                const dtmap = {
                    packaging: "QC Packaging Check",
                    weight: "QC Weight Check",
                };
                this.$container.find("[data-target='pkg_weight']").closest(".qh-filter-bar")
                    .find(".qh-new-record").data("doctype", dtmap[sub]);
                this.load_records("pkg_weight", {});
            }
        });

        // New record buttons
        this.$container.on("click", ".qh-new-record", (e) => {
            const doctype = $(e.currentTarget).data("doctype");
            this.open_new_record(doctype);
        });

        // Filter apply
        this.$container.on("click", ".qh-filter-apply", (e) => {
            const target = $(e.currentTarget).data("target");
            const filters = this.get_filters(target);
            this.load_records(target, filters);
        });

        // Matrix date / refresh
        this.$container.on("click", "[data-role='matrix-refresh']", () => {
            const date = this.$container.find("[data-role='matrix-date']").val() || frappe.datetime.get_today();
            this.load_completion_matrix(date);
        });
    }

    get_filters(tab) {
        const filters = {};
        this.$container.find(`[data-content="${tab}"] .qh-filter-input`).each(function () {
            const key = $(this).data("filter");
            const val = $(this).val();
            if (val !== "" && val !== undefined && val !== null) {
                filters[key] = val;
            }
        });
        return filters;
    }

    open_new_record(doctype) {
        const config = isnack.quality_hub.DIALOG_RECORD_CONFIG[doctype];
        if (!config) {
            frappe.new_doc(doctype);
            return;
        }

        const dialog = new frappe.ui.Dialog({
            title: __("New {0}", [doctype]),
            size: "extra-large",
            fields: [
                ...config.parent_fields,
                {
                    fieldtype: "HTML",
                    fieldname: "child_table_editor",
                },
            ],
            primary_action_label: __("Save Draft"),
            primary_action: () => this.handle_dialog_save(dialog, doctype, false),
        });

        dialog.__config = config;
        dialog.__child_rows = this.make_initial_child_rows(config);
        dialog.show();
        dialog.$wrapper.addClass("qh-record-dialog");
        this.setup_dialog_secondary_action(dialog, doctype);
        this.render_child_editor(dialog, doctype);
    }

    setup_dialog_secondary_action(dialog, doctype) {
        const $secondary = dialog.get_secondary_btn();
        $secondary
            .removeClass("hide")
            .text(__("Save & Submit"))
            .off("click")
            .on("click", () => this.handle_dialog_save(dialog, doctype, true));
    }

    handle_dialog_save(dialog, doctype, submit) {
        const values = dialog.get_values();
        if (!values) return;

        const config = dialog.__config;
        const child_rows = this.get_non_empty_child_rows(dialog);
        if (!child_rows.length) {
            frappe.msgprint(__("Add at least one row in {0}.", [config.child_label]));
            return;
        }

        const payload = {
            ...values,
            [config.child_table_field]: child_rows,
        };

        this.save_dialog_record({ dialog, doctype, payload, submit });
    }

    save_dialog_record({ dialog, doctype, payload, submit }) {
        const action_label = submit ? __("Saving and submitting") : __("Saving");
        frappe.call({
            method: "isnack.isnack.page.quality_hub.quality_hub.create_qc_record",
            freeze: true,
            freeze_message: `${action_label}...`,
            args: {
                doctype,
                payload,
                submit: submit ? 1 : 0,
            },
            callback: (r) => {
                if (!r.message) return;

                dialog.hide();
                this.reload_active_tab_records();
                frappe.show_alert({
                    message: __("{0} created", [r.message.name]),
                    indicator: submit ? "green" : "blue",
                });
            },
        });
    }

    reload_active_tab_records() {
        if (this.active_tab === "receiving") {
            this.load_records("receiving", this.get_filters("receiving"));
        } else if (this.active_tab === "process") {
            this.load_records("process", this.get_filters("process"));
        } else if (this.active_tab === "tasting") {
            this.load_records("tasting", this.get_filters("tasting"));
        } else if (this.active_tab === "pkg_weight") {
            this.load_records("pkg_weight", this.get_filters("pkg_weight"));
        } else if (this.active_tab === "metal") {
            this.load_metal_tab();
        }
        this.refresh_data(false);
    }

    make_initial_child_rows(config) {
        const rows = [];
        const row_count = Math.max(config.min_rows || 1, 1);
        for (let index = 0; index < row_count; index++) {
            rows.push(this.make_empty_child_row(config));
        }
        return rows;
    }

    make_empty_child_row(config) {
        const row = {};
        (config.child_fields || []).forEach((field) => {
            if (field.default !== undefined) {
                row[field.fieldname] =
                    typeof field.default === "function" ? field.default() : field.default;
            } else {
                row[field.fieldname] = field.fieldtype === "Check" ? 0 : "";
            }
        });
        return row;
    }

    render_child_editor(dialog, doctype) {
        const config = dialog.__config || isnack.quality_hub.DIALOG_RECORD_CONFIG[doctype];
        const $wrapper = $(dialog.get_field("child_table_editor").wrapper);
        const rows = dialog.__child_rows || [];
        const headers = (config.child_fields || [])
            .map((field) => `<th>${frappe.utils.escape_html(field.label)}</th>`)
            .join("");
        const row_html = rows
            .map((row, index) => {
                const cells = config.child_fields
                    .map((field) => `<td>${this.render_child_input(field, row[field.fieldname], index)}</td>`)
                    .join("");

                return `
                    <tr data-row-index="${index}">
                        ${cells}
                        <td class="qh-child-row-actions">
                            <button type="button" class="btn btn-xs btn-default qh-child-duplicate" data-row-index="${index}">
                                <i class="fa fa-copy"></i>
                            </button>
                            <button type="button" class="btn btn-xs btn-default qh-child-delete" data-row-index="${index}">
                                <i class="fa fa-trash"></i>
                            </button>
                        </td>
                    </tr>
                `;
            })
            .join("");

        $wrapper.html(`
            <div class="qh-child-editor">
                <div class="qh-child-toolbar">
                    <div class="qh-child-toolbar-label">${frappe.utils.escape_html(config.child_label)}</div>
                    <button type="button" class="btn btn-sm btn-default qh-child-add">
                        <i class="fa fa-plus"></i> ${__("Add Row")}
                    </button>
                </div>
                <div class="qh-child-table-wrap">
                    <table class="qh-table qh-child-table">
                        <thead>
                            <tr>
                                ${headers}
                                <th>${__("Actions")}</th>
                            </tr>
                        </thead>
                        <tbody>${row_html}</tbody>
                    </table>
                </div>
            </div>
        `);

        $wrapper.find(".qh-child-add").on("click", () => {
            dialog.__child_rows.push(this.make_empty_child_row(config));
            this.render_child_editor(dialog, doctype);
        });

        $wrapper.find(".qh-child-delete").on("click", (e) => {
            const index = Number($(e.currentTarget).data("row-index"));
            if (dialog.__child_rows.length <= (config.min_rows || 1)) {
                frappe.show_alert({
                    message: __("Minimum row count reached. Row cleared instead."),
                    indicator: "orange",
                });
                dialog.__child_rows[index] = this.make_empty_child_row(config);
            } else {
                dialog.__child_rows.splice(index, 1);
            }
            this.render_child_editor(dialog, doctype);
        });

        $wrapper.find(".qh-child-duplicate").on("click", (e) => {
            const index = Number($(e.currentTarget).data("row-index"));
            const cloned_row = JSON.parse(JSON.stringify(dialog.__child_rows[index]));
            dialog.__child_rows.splice(index + 1, 0, cloned_row);
            this.render_child_editor(dialog, doctype);
        });

        $wrapper.find(".qh-child-input").on("input change", (e) => {
            const $input = $(e.currentTarget);
            const row_index = Number($input.data("row-index"));
            const fieldname = $input.data("fieldname");
            const field = config.child_fields.find((item) => item.fieldname === fieldname);
            if (!field) return;
            dialog.__child_rows[row_index][fieldname] = this.get_input_value($input, field);
        });
    }

    render_child_input(field, value, row_index) {
        const escaped_fieldname = frappe.utils.escape_html(field.fieldname);
        const escaped_label = frappe.utils.escape_html(field.label);

        if (field.fieldtype === "Check") {
            return `
                <label class="qh-child-check">
                    <input
                        type="checkbox"
                        class="qh-child-input"
                        data-row-index="${row_index}"
                        data-fieldname="${escaped_fieldname}"
                        ${value ? "checked" : ""}
                    />
                    <span>${escaped_label}</span>
                </label>
            `;
        }

        if (field.fieldtype === "Select" || field.fieldtype === "Rating") {
            const options = field.fieldtype === "Rating"
                ? ["", "1", "2", "3", "4", "5"]
                : (field.options || "").split("\n");
            const options_html = options
                .map((option) => {
                    const current_value =
                        value === null || value === undefined ? "" : `${value}`;
                    const selected = `${option}` === current_value ? "selected" : "";
                    const is_placeholder_option = option === "";
                    const option_label = is_placeholder_option ? __("Select") : option;
                    return `<option value="${frappe.utils.escape_html(option)}" ${selected}>${frappe.utils.escape_html(option_label)}</option>`;
                })
                .join("");

            return `
                <select
                    class="form-control qh-child-input"
                    data-row-index="${row_index}"
                    data-fieldname="${escaped_fieldname}">
                    ${options_html}
                </select>
            `;
        }

        if (field.fieldtype === "Small Text") {
            return `
                <textarea
                    class="form-control qh-child-input qh-child-textarea"
                    data-row-index="${row_index}"
                    data-fieldname="${escaped_fieldname}"
                    rows="2"
                    placeholder="${escaped_label}">${frappe.utils.escape_html(value || "")}</textarea>
            `;
        }

        const type_map = {
            Int: "number",
            Float: "number",
            Time: "time",
            Date: "date",
        };
        const input_type = type_map[field.fieldtype] || "text";
        const step_attr = field.fieldtype === "Float" ? 'step="any"' : "";
        const display_value = value === null || value === undefined ? "" : value;

        return `
            <input
                type="${input_type}"
                class="form-control qh-child-input"
                data-row-index="${row_index}"
                data-fieldname="${escaped_fieldname}"
                placeholder="${escaped_label}"
                value="${frappe.utils.escape_html(display_value)}"
                ${step_attr}
            />
        `;
    }

    get_input_value($input, field) {
        if (field.fieldtype === "Check") {
            return $input.is(":checked") ? 1 : 0;
        }

        const value = $input.val();
        if (value === "" || value === null || value === undefined) {
            return "";
        }

        if (field.fieldtype === "Int") {
            const parsed = parseInt(value, 10);
            return Number.isNaN(parsed) ? "" : parsed;
        }

        if (field.fieldtype === "Float" || field.fieldtype === "Rating") {
            return Number(value);
        }

        return value;
    }

    get_non_empty_child_rows(dialog) {
        const config = dialog.__config;
        return (dialog.__child_rows || [])
            .map((row) => {
                const clean_row = {};
                config.child_fields.forEach((field) => {
                    clean_row[field.fieldname] = row[field.fieldname];
                });
                return clean_row;
            })
            .filter((row) => this.child_row_has_values(row, config.child_fields));
    }

    child_row_has_values(row, fields) {
        return fields.some((field) => {
            const value = row[field.fieldname];
            if (field.fieldtype === "Check") {
                return !!value;
            }
            return value !== "" && value !== null && value !== undefined;
        });
    }

    show_tab(tab) {
        this.active_tab = tab;
        this.$container.find(".qh-tab").removeClass("qh-tab-active");
        this.$container.find(`.qh-tab[data-tab="${tab}"]`).addClass("qh-tab-active");
        this.$container.find(".qh-tab-content").hide();
        this.$container.find(`[data-content="${tab}"]`).show();

        // Lazy-load data when switching to a tab
        if (tab === "receiving") {
            this.load_records("receiving", {});
        } else if (tab === "process") {
            this.load_records("process", {});
        } else if (tab === "tasting") {
            this.load_records("tasting", {});
        } else if (tab === "pkg_weight") {
            this.load_records("pkg_weight", {});
        } else if (tab === "metal") {
            this.load_metal_tab();
        } else if (tab === "reports") {
            this.load_completion_matrix(frappe.datetime.get_today());
        }
    }

    load_records(tab, filters) {
        const dtmap = {
            receiving: "QC Receiving Record",
            process: {
                puffs: "QC Puffs Extruder Record",
                rice: "QC Rice Extruder Record",
                frying: "QC Frying Line Record",
                oven: "QC Oven Record",
            },
            tasting: "QC Tasting Record",
            pkg_weight: {
                packaging: "QC Packaging Check",
                weight: "QC Weight Check",
            },
            metal: "QC Metal Detector Log",
        };

        let doctype;
        if (tab === "process") {
            const sub = this.active_process_sub || "puffs";
            doctype = dtmap.process[sub];
        } else if (tab === "pkg_weight") {
            const sub = this.active_pkg_sub || "packaging";
            doctype = dtmap.pkg_weight[sub];
        } else {
            doctype = dtmap[tab];
        }

        if (!doctype) return;

        frappe.call({
            method: "isnack.isnack.page.quality_hub.quality_hub.get_qc_records",
            args: { doctype, filters, limit: 50 },
            callback: (r) => {
                const records = r.message || [];
                this.render_record_list(tab, doctype, records);
            },
        });
    }

    render_record_list(tab, doctype, records) {
        const $target = this.$container.find(`[data-role="list-${tab}"]`);

        if (!records.length) {
            $target.html(`<div class="text-muted small" style="padding:1rem">${__("No records found.")}</div>`);
            return;
        }

        const cols = [
            { key: "name", label: __("Name") },
            { key: "record_date", label: __("Date") },
            { key: "shift", label: __("Shift") },
            { key: "factory_line", label: __("Line") },
            { key: "operator_name", label: __("Operator") },
            { key: "overall_status", label: __("Result") },
            { key: "docstatus", label: __("Status") },
        ];

        const status_map = { 0: __("Draft"), 1: __("Submitted"), 2: __("Cancelled") };
        const status_cls = { 0: "qh-badge-amber", 1: "qh-badge-emerald", 2: "qh-badge-red" };

        const rows_html = records.map((r) => {
            const cells = cols.map((c) => {
                let val = r[c.key];
                if (c.key === "docstatus") {
                    val = `<span class="qh-badge ${status_cls[val] || ""}">${status_map[val] || val}</span>`;
                } else if (c.key === "overall_status" && val) {
                    const cls = val === "Pass" || val === "Accepted" ? "qh-badge-emerald" :
                                val === "Fail" || val === "Rejected" ? "qh-badge-red" : "qh-badge-amber";
                    val = `<span class="qh-badge ${cls}">${frappe.utils.escape_html(val)}</span>`;
                } else if (c.key === "name") {
                    val = `<a href="#Form/${encodeURIComponent(doctype)}/${encodeURIComponent(val)}">${frappe.utils.escape_html(val)}</a>`;
                } else {
                    val = frappe.utils.escape_html(val || "-");
                }
                return `<td>${val}</td>`;
            }).join("");
            return `<tr data-name="${frappe.utils.escape_html(r.name)}">${cells}</tr>`;
        }).join("");

        const header_html = cols.map((c) => `<th>${c.label}</th>`).join("");

        $target.html(`
            <table class="qh-table">
                <thead><tr>${header_html}</tr></thead>
                <tbody>${rows_html}</tbody>
            </table>
        `);

        $target.find("tr[data-name]").on("click", (e) => {
            if ($(e.target).is("a")) return;
            const name = $(e.currentTarget).data("name");
            frappe.set_route("Form", doctype, name);
        });
    }

    load_metal_tab() {
        // Update CCP alert banner
        frappe.call({
            method: "isnack.isnack.page.quality_hub.quality_hub.get_qc_records",
            args: {
                doctype: "QC Metal Detector Log",
                filters: { record_date: frappe.datetime.get_today() },
                limit: 5,
            },
            callback: (r) => {
                const records = r.message || [];
                const $alert = this.$container.find("[data-role='ccp-alert']");
                const $text = this.$container.find("[data-role='ccp-alert-text']");
                if (records.length) {
                    const last = records[0];
                    $text.text(__("Last verification: {0} — Shift: {1}", [last.record_date, last.shift || "-"]));
                    $alert.removeClass("qh-ccp-alert-warn").addClass("qh-ccp-alert-ok");
                } else {
                    $text.text(__("No metal detector verification recorded today."));
                    $alert.removeClass("qh-ccp-alert-ok").addClass("qh-ccp-alert-warn");
                }
                this.render_record_list("metal", "QC Metal Detector Log", records);
            },
        });
    }

    load_completion_matrix(date) {
        const $target = this.$container.find("[data-role='completion-matrix']");
        $target.html(`<div class="text-muted small" style="padding:1rem">${__("Loading...")}</div>`);

        frappe.call({
            method: "isnack.isnack.page.quality_hub.quality_hub.get_completion_matrix",
            args: { date },
            callback: (r) => {
                if (!r.message) return;
                this.render_completion_matrix(r.message);
            },
        });
    }

    render_completion_matrix(data) {
        const { matrix, doctypes } = data;
        const shifts = ["Morning", "Afternoon", "Night"];
        const codes = Object.keys(doctypes);

        const icon_map = {
            submitted: '<span class="qh-matrix-cell qh-matrix-submitted">✅</span>',
            draft: '<span class="qh-matrix-cell qh-matrix-draft">🟡</span>',
            not_started: '<span class="qh-matrix-cell qh-matrix-not-started">—</span>',
        };

        const shift_cls = {
            Morning: "qh-matrix-shift-morning",
            Afternoon: "qh-matrix-shift-afternoon",
            Night: "qh-matrix-shift-night",
        };

        const header = `<tr><th>${__("Shift")}</th>${codes.map((c) => `<th>${c}</th>`).join("")}</tr>`;
        const body = shifts.map((shift) => {
            const cells = codes.map((code) => {
                const status = (matrix[shift] || {})[code] || "not_started";
                return `<td class="text-center">${icon_map[status] || "—"}</td>`;
            }).join("");
            const cls = shift_cls[shift] || "";
            return `<tr><td><strong class="${cls}">${__(shift)}</strong></td>${cells}</tr>`;
        }).join("");

        const $target = this.$container.find("[data-role='completion-matrix']");
        $target.html(`
            <table class="qh-table qh-matrix">
                <thead>${header}</thead>
                <tbody>${body}</tbody>
            </table>
            <div style="margin-top:0.5rem;font-size:0.75rem;color:#6b7280">
                ✅ ${__("Submitted")} &nbsp; 🟡 ${__("Draft")} &nbsp; — ${__("Not started")}
            </div>
        `);
    }

    start_clock() {
        const $time = this.$container.find("[data-role='current-time']");
        const update = () => {
            const now = frappe.datetime.str_to_user(frappe.datetime.now_datetime());
            $time.text(now);
        };
        update();
        setInterval(update, 30 * 1000);
    }

    start_polling() {
        this.poll_interval = setInterval(() => {
            if (this.active_tab === "monitor") {
                this.refresh_data(true);
            }
        }, 30 * 1000);
    }

    refresh_data(from_timer) {
        frappe.call({
            method: "isnack.isnack.page.quality_hub.quality_hub.get_quality_hub_data",
            freeze: false,
            callback: (r) => {
                if (!r.message) return;
                this.update_ui(r.message, from_timer);
            },
        });

        // Also refresh QC record summary for stat cards
        frappe.call({
            method: "isnack.isnack.page.quality_hub.quality_hub.get_qc_record_summary",
            args: { date: frappe.datetime.get_today() },
            callback: (r) => {
                if (!r.message) return;
                this.render_qc_summary_cards(r.message);
            },
        });
    }

    render_qc_summary_cards(summary) {
        const $grid = this.$container.find("[data-role='qc-summary-grid']");
        const label_map = {
            QCA: __("Receiving"),
            QCB: __("Puffs Extr."),
            QCC: __("Rice Extr."),
            QCD: __("Frying"),
            QCE: __("Oven"),
            QCF: __("Tasting"),
            QCG: __("Packaging"),
            QCH: __("Metal Det."),
            QCI: __("Weight"),
        };

        const cards = Object.entries(summary).map(([code, data]) => {
            const submitted = data.submitted || 0;
            const total = data.total || 0;
            const cls = submitted > 0 ? "qh-card-success" : total > 0 ? "qh-card-warn" : "";
            return `
                <div class="qh-card ${cls}">
                    <div class="qh-card-label">${label_map[code] || code}</div>
                    <div class="qh-card-value">${submitted}<span class="qh-card-total">/${total}</span></div>
                </div>`;
        }).join("");

        $grid.html(cards);
    }

    update_ui(data, from_timer) {
        const stats = data.stats || {};
        const out_of_range = data.recent_out_of_range || [];

        // stats
        this.$container
            .find("[data-role='stat-completed-hour']")
            .text(stats.completed_last_hour || 0);
        this.$container
            .find("[data-role='stat-nc']")
            .text(stats.open_non_conformances || 0);

        this.$container
            .find("[data-role='badge-out-of-range']")
            .text(`${out_of_range.length} ${__("events")}`);

        this.render_out_of_range_table(out_of_range);
    }

    render_out_of_range_table(rows) {
        const $target = this.$container.find("[data-role='table-out-of-range']");
        if (!rows.length) {
            $target.html(
                `<div class="text-muted small">${__(
                    "No recent out-of-range readings."
                )}</div>`
            );
            return;
        }

        const html = `
            <table class="qh-table">
                <thead>
                    <tr>
                        <th>${__("When")}</th>
                        <th>${__("Parameter")}</th>
                        <th>${__("Item / Ref")}</th>
                        <th>${__("Type")}</th>
                        <th>${__("Inspection")}</th>
                    </tr>
                </thead>
                <tbody>
                    ${rows
                        .map((r) => {
                            const ts = frappe.datetime.str_to_user(r.ts || "");
                            const ref =
                                r.reference_type && r.reference_name
                                    ? `${r.reference_type} ${r.reference_name}`
                                    : r.item_code || "-";

                            return `
                                <tr>
                                    <td>${ts}</td>
                                    <td>
                                        <span class="qh-chip qh-chip-out-of-range">
                                            ${frappe.utils.escape_html(
                                                r.specification || "-"
                                            )}
                                        </span>
                                    </td>
                                    <td>${frappe.utils.escape_html(ref)}</td>
                                    <td>${frappe.utils.escape_html(
                                        r.inspection_type || ""
                                    )}</td>
                                    <td>
                                        <a href="#Form/Quality%20Inspection/${encodeURIComponent(
                                            r.quality_inspection
                                        )}">
                                            ${frappe.utils.escape_html(
                                                r.quality_inspection || ""
                                            )}
                                        </a>
                                    </td>
                                </tr>`;
                        })
                        .join("")}
                </tbody>
            </table>
        `;

        $target.html(html);
    }

};
