frappe.ui.form.on("Supplier", {
    refresh(frm) {
        if (frm.doc.__islocal) {
            return;
        }

        frm.add_custom_button(
            __("Linked Landed Vouchers"),
            () => show_linked_landed_vouchers_dialog(frm),
            __("View")
        );
    },
});

function show_linked_landed_vouchers_dialog(frm) {
    const dialog = new frappe.ui.Dialog({
        title: __("Linked Landed Vouchers"),
        size: "extra-large",
        fields: [
            {
                fieldtype: "HTML",
                fieldname: "linked_landed_vouchers_html",
            },
        ],
    });

    dialog.show();
    dialog.$wrapper.find(".modal-dialog").css("max-width", "95vw");

    const wrapper = dialog.get_field("linked_landed_vouchers_html").$wrapper;
    wrapper.html(`<p class="text-muted">${__("Loading linked landed vouchers...")}</p>`);

    frappe.call({
        method: "isnack.api.supplier.get_linked_landed_cost_vouchers",
        args: {
            supplier: frm.doc.name,
        },
        callback: (r) => {
            const payload = r.message || {};
            const vouchers = payload.vouchers || [];
            render_linked_landed_vouchers(wrapper, payload.supplier || frm.doc.name, vouchers);
        },
        error: () => {
            wrapper.html(
                `<div class="text-danger">${__(
                    "Unable to load linked landed vouchers. Please try again."
                )}</div>`
            );
        },
    });
}

function render_linked_landed_vouchers(wrapper, supplier, vouchers) {
    if (!vouchers.length) {
        wrapper.html(
            `<div class="text-muted">${__(
                "No Landed Cost Vouchers are linked to this supplier through Purchase Receipts."
            )}</div>`
        );
        return;
    }

    const mixedSupplierCount = vouchers.filter((voucher) => voucher.has_other_suppliers).length;

    const rows = vouchers
        .map((voucher) => {
            const landedVoucherLink = frappe.utils.get_form_link(
                "Landed Cost Voucher",
                voucher.name,
                true
            );
            const postingDate = voucher.posting_date
                ? frappe.datetime.str_to_user(voucher.posting_date)
                : "";
            const totalTaxes = frappe.format(voucher.total_taxes_and_charges || 0, {
                fieldtype: "Currency",
            });

            const purchaseReceiptLinks = (voucher.supplier_purchase_receipts || [])
                .map((receipt) => frappe.utils.get_form_link("Purchase Receipt", receipt, true))
                .join(", ");

            const mixedSupplierHtml = voucher.has_other_suppliers
                ? `<span class="text-warning">${__("Yes")}: ${escape_html(
                        (voucher.other_suppliers || []).join(", ")
                  )}</span>`
                : `<span class="text-success">${__("No")}</span>`;

            return `
                <tr>
                    <td>${landedVoucherLink}</td>
                    <td>${escape_html(postingDate)}</td>
                    <td>
                        <span class="indicator-pill ${escape_html(voucher.indicator || "gray")}">
                            ${escape_html(voucher.status || "")}
                        </span>
                    </td>
                    <td>${totalTaxes}</td>
                    <td>${purchaseReceiptLinks || "-"}</td>
                    <td>${mixedSupplierHtml}</td>
                </tr>
            `;
        })
        .join("");

    wrapper.html(`
        <div class="alert alert-info" style="margin-bottom: 12px;">
            ${__("Supplier")}: <strong>${escape_html(supplier)}</strong>
            <span style="margin-left: 12px;">
            ${__("Total Linked Vouchers")}: <strong>${vouchers.length}</strong>
            </span>
            <span style="margin-left: 12px;">
                ${__("Mixed-Supplier Vouchers")}: <strong>${mixedSupplierCount}</strong>
            </span>
        </div>

        <div style="max-height: 62vh; overflow: auto;">
            <table class="table table-bordered table-hover" style="margin-bottom: 0;">
                <thead>
                    <tr>
                        <th>${__("Landed Cost Voucher")}</th>
                        <th>${__("Posting Date")}</th>
                        <th>${__("Status")}</th>
                        <th>${__("Total Taxes & Charges")}</th>
                        <th>${__("Purchase Receipts (This Supplier)")}</th>
                        <th>${__("Includes Other Suppliers")}</th>
                    </tr>
                </thead>
                <tbody>
                    ${rows}
                </tbody>
            </table>
        </div>

        <p class="text-muted" style="margin-top: 12px; margin-bottom: 0;">
            ${__(
                "If 'Includes Other Suppliers' is Yes, this Landed Cost Voucher also references Purchase Receipts from supplier(s) other than the current supplier."
            )}
        </p>
    `);
}

function escape_html(value) {
    const text = cstr(value || "");

    if (frappe.utils.escape_html) {
        return frappe.utils.escape_html(text);
    }

    return text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/\"/g, "&quot;")
        .replace(/'/g, "&#39;");
}
