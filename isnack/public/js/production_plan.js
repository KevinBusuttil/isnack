frappe.ui.form.on("Production Plan", {
  refresh(frm) {
    // Override the core handler so only our confirmation flow runs
    frm.events.make_work_order = () => {
      frm.events._confirm_and_make_work_order(frm);
    };
  },

  _confirm_and_make_work_order(frm) {
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