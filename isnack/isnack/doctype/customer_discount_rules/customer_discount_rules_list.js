frappe.listview_settings["Customer Discount Rules"] = {
    onload(listview) {
        listview.page.add_actions_menu_item(__("Adjust Discounts"), () => {
            const selected = listview.get_checked_items();
            if (!selected.length) {
                frappe.msgprint({ message: __("Please select at least one record."), indicator: "orange" });
                return;
            }

            const dialog = new frappe.ui.Dialog({
                title: __("Adjust Discounts"),
                fields: [
                    {
                        label: __("Tier 1 Action"),
                        fieldname: "tier1_action",
                        fieldtype: "Select",
                        options: ["", "Add", "Deduct"],
                    },
                    {
                        label: __("Tier 1 Change (%)"),
                        fieldname: "tier1_value",
                        fieldtype: "Float",
                        depends_on: "eval:['Add','Deduct'].includes(doc.tier1_action)",
                    },
                    { fieldtype: "Section Break" },
                    {
                        label: __("Tier 2 Action"),
                        fieldname: "tier2_action",
                        fieldtype: "Select",
                        options: ["", "Add", "Deduct", "Clear"],
                    },
                    {
                        label: __("Tier 2 Change (%)"),
                        fieldname: "tier2_value",
                        fieldtype: "Float",
                        depends_on: "eval:['Add','Deduct'].includes(doc.tier2_action)",
                    },
                ],
                primary_action_label: __("Apply"),
                primary_action: (values) => {
                    if (!values.tier1_action && !values.tier2_action) {
                        frappe.msgprint({ message: __("Choose at least one action."), indicator: "orange" });
                        return;
                    }

                    frappe.call({
                        method: "isnack.isnack.doctype.customer_discount_rules.customer_discount_rules.bulk_adjust_discounts",
                        freeze: true,
                        args: {
                            names: selected.map((row) => row.name),
                            tier1_action: values.tier1_action,
                            tier1_value: values.tier1_value,
                            tier2_action: values.tier2_action,
                            tier2_value: values.tier2_value,
                        },
                        callback: () => {
                            dialog.hide();
                            listview.refresh();
                        },
                    });
                },
            });

            dialog.show();
        });
    },
};