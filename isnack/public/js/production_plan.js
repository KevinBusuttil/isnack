frappe.ui.form.on("Production Plan", {
  make_work_order(frm) {
    // Guard: if not submitted, just run directly
    if (!frm.doc.name || frm.doc.docstatus !== 1) {
      return frm.events._run_make_work_order(frm);
    }

    frappe.call({
      method: "frappe.client.get_list",
      args: {
        doctype: "Work Order",
        fields: ["name"],
        filters: { production_plan: frm.doc.name },
        limit_page_length: 1,
      },
      callback(r) {
        const has_existing = Array.isArray(r.message) && r.message.length > 0;

        if (!has_existing) {
          return frm.events._run_make_work_order(frm);
        }

        frappe.confirm(
          __("Work Orders already exist for this Production Plan. Create again?"),
          () => frm.events._run_make_work_order(frm),
          () => {}
        );
      },
    });
  },

  _run_make_work_order(frm) {
    frappe.call({
      method: "make_work_order",
      freeze: true,
      doc: frm.doc,
      callback: function () {
        frm.reload_doc();
      },
    });
  },
});