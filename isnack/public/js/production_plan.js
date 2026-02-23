frappe.ui.form.off("Production Plan", "make_work_order");

frappe.ui.form.on("Production Plan", {
  make_work_order(frm) {
    // Guard: if not submitted, just run directly
    if (!frm.doc.name || frm.doc.docstatus !== 1) {
      return frm.events._run_make_work_order(frm);
    }

    // Prevent double clicks while request is running
    if (frm._making_work_orders) {
      return;
    }

    const confirm_again = () => {
      frappe.confirm(
        __("Work Orders already exist for this Production Plan. Create again?"),
        () => frm.events._run_make_work_order(frm),
        () => {}
      );
    };

    // If we already created WOs this session, confirm immediately
    if (frm._work_orders_created) {
      return confirm_again();
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

        confirm_again();
      },
    });
  },

  _run_make_work_order(frm) {
    frm._making_work_orders = true;

    frappe.call({
      method: "make_work_order",
      freeze: true,
      doc: frm.doc,
      callback: function () {
        // Mark that WOs were created in this session
        frm._work_orders_created = true;
        frm.reload_doc();
      },
      always: function () {
        frm._making_work_orders = false;
      },
    });
  },
});