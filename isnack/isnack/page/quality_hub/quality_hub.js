frappe.provide("isnack.quality_hub");

frappe.pages["quality-hub"].on_page_load = function (wrapper) {
    isnack.quality_hub.page = new isnack.quality_hub.QualityHub(wrapper);
};

isnack.quality_hub.QualityHub = class {
    constructor(wrapper) {
        this.wrapper = $(wrapper);
        this.page = frappe.ui.make_app_page({
            parent: wrapper,
            title: __("Lab Quality Hub"),
            single_column: true,
        });

        this.$main = this.wrapper.find(".layout-main-section");
        this.$main.empty();

        this.make_layout();
        this.start_clock();
        this.refresh_data(false);
        this.start_polling();
    }

    make_layout() {
        this.$container = $(`
            <div class="quality-hub-wrapper">
                <div class="qh-header">
                    <div>
                        <div class="qh-header-title">
                            <span class="qh-dot qh-blink"></span>
                            ${__("Lab Quality Hub")}
                        </div>
                        <div class="qh-header-subtitle">
                            ${__("Real-time view of routine checks and critical readings.")}
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

                <div class="qh-stat-grid">
                    <div class="qh-card">
                        <div class="qh-card-label">${__("Overdue readings")}</div>
                        <div class="qh-card-value" data-role="stat-overdue">0</div>
                    </div>
                    <div class="qh-card">
                        <div class="qh-card-label">${__("Due in next 5 min")}</div>
                        <div class="qh-card-value" data-role="stat-due-now">0</div>
                    </div>
                    <div class="qh-card">
                        <div class="qh-card-label">${__("Completed last hour")}</div>
                        <div class="qh-card-value" data-role="stat-completed-hour">0</div>
                    </div>
                    <div class="qh-card">
                        <div class="qh-card-label">${__("Open non-conformances")}</div>
                        <div class="qh-card-value" data-role="stat-nc">0</div>
                    </div>
                </div>

                <div class="qh-layout">
                    <div class="qh-panel">
                        <div class="qh-panel-header">
                            <div class="qh-panel-title">${__("Due & Overdue Checkpoints")}</div>
                            <span class="qh-badge qh-badge-red" data-role="badge-due">
                                0 ${__("checkpoints")}
                            </span>
                        </div>
                        <div data-role="table-due"></div>
                    </div>

                    <div class="qh-panel">
                        <div class="qh-panel-header">
                            <div class="qh-panel-title">${__("Recent Out-of-Range Readings")}</div>
                            <span class="qh-badge qh-badge-amber" data-role="badge-out-of-range">
                                0 ${__("events")}
                            </span>
                        </div>
                        <div data-role="table-out-of-range"></div>
                    </div>
                </div>
            </div>
        `).appendTo(this.$main);
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
            this.refresh_data(true);
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
    }

    update_ui(data, from_timer) {
        const stats = data.stats || {};
        const overdue = data.overdue || [];
        const due_now = data.due_now || [];
        const upcoming = data.upcoming || [];
        const out_of_range = data.recent_out_of_range || [];

        const total_due = overdue.length + due_now.length;

        // stats
        this.$container.find("[data-role='stat-overdue']").text(overdue.length);
        this.$container.find("[data-role='stat-due-now']").text(due_now.length);
        this.$container
            .find("[data-role='stat-completed-hour']")
            .text(stats.completed_last_hour || 0);
        this.$container
            .find("[data-role='stat-nc']")
            .text(stats.open_non_conformances || 0);

        this.$container
            .find("[data-role='badge-due']")
            .text(`${total_due} ${__("checkpoints")}`);
        this.$container
            .find("[data-role='badge-out-of-range']")
            .text(`${out_of_range.length} ${__("events")}`);

        // alert if new items appear
        if (from_timer) {
            const prev_overdue = this._prev_overdue_count || 0;
            const prev_due = this._prev_total_due || 0;

            if (overdue.length > prev_overdue || total_due > prev_due) {
                frappe.show_alert(
                    {
                        message: __("New quality readings are due"),
                        indicator: "red",
                    },
                    7
                );
                if (frappe.utils.play_sound) {
                    frappe.utils.play_sound("ping");
                }
            }

            this._prev_overdue_count = overdue.length;
            this._prev_total_due = total_due;
        }

        this.render_due_table(overdue, due_now, upcoming);
        this.render_out_of_range_table(out_of_range);
    }

    render_due_table(overdue, due_now, upcoming) {
        const $target = this.$container.find("[data-role='table-due']");
        if (!overdue.length && !due_now.length && !upcoming.length) {
            $target.html(
                `<div class="text-muted small">${__(
                    "All checkpoints are within schedule."
                )}</div>`
            );
            return;
        }

        const rows = []
            .concat(
                overdue.map((r) => ({ ...r, _state: "overdue" })),
                due_now.map((r) => ({ ...r, _state: "due_now" })),
                upcoming.map((r) => ({ ...r, _state: "upcoming" }))
            );

        const html = `
            <table class="qh-table">
                <thead>
                    <tr>
                        <th>${__("Checkpoint")}</th>
                        <th>${__("Equipment")}</th>
                        <th>${__("Freq (min)")}</th>
                        <th>${__("Next in (min)")}</th>
                        <th>${__("Responsible")}</th>
                        <th style="width: 1%"></th>
                    </tr>
                </thead>
                <tbody>
                    ${rows
                        .map((r) => {
                            const cls =
                                r._state === "overdue"
                                    ? "qh-row-overdue"
                                    : r._state === "due_now"
                                    ? "qh-row-due-now"
                                    : "";
                            const badge =
                                r._state === "overdue"
                                    ? `<span class="qh-badge qh-badge-red">${__(
                                          "Overdue"
                                      )}</span>`
                                    : r._state === "due_now"
                                    ? `<span class="qh-badge qh-badge-amber">${__(
                                          "Due soon"
                                      )}</span>`
                                    : `<span class="qh-badge qh-badge-emerald">${__(
                                          "Upcoming"
                                      )}</span>`;

                            return `
                                <tr class="${cls}">
                                    <td>
                                        <div>${frappe.utils.escape_html(
                                            r.checkpoint_name
                                        )}</div>
                                        <div class="text-muted small">
                                            ${frappe.utils.escape_html(r.name)}
                                        </div>
                                    </td>
                                    <td>${frappe.utils.escape_html(
                                        r.equipment || "-"
                                    )}</td>
                                    <td class="text-right">${
                                        r.frequency_mins || ""
                                    }</td>
                                    <td class="text-right">
                                        ${
                                            r.minutes_to_next !== null &&
                                            r.minutes_to_next !== undefined
                                                ? r.minutes_to_next.toFixed(1)
                                                : "-"
                                        }
                                    </td>
                                    <td>${frappe.utils.escape_html(
                                        r.responsible_user || "-"
                                    )}</td>
                                    <td class="text-right">
                                        ${badge}
                                        <button class="btn btn-xs btn-primary qh-take-reading"
                                            data-checkpoint="${frappe.utils.escape_html(
                                                r.name
                                            )}">
                                            ${__("Start")}
                                        </button>
                                    </td>
                                </tr>`;
                        })
                        .join("")}
                </tbody>
            </table>
        `;

        $target.html(html);

        // bind click
        $target.find(".qh-take-reading").on("click", (e) => {
            const checkpoint = $(e.currentTarget).data("checkpoint");
            this.start_inspection(checkpoint);
        });
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

    start_inspection(checkpoint) {
        frappe.call({
            method:
                "isnack.isnack.page.quality_hub.quality_hub.create_quality_inspection_from_checkpoint",
            args: { checkpoint },
            callback: (r) => {
                if (!r.message) return;
                frappe.set_route("Form", "Quality Inspection", r.message.name);
            },
        });
    }
};
