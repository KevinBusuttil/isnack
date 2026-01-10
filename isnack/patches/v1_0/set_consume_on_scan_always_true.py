import frappe

def execute():
    """
    Ensure consume_on_scan is set to 1 before it becomes hardcoded.
    This patch ensures smooth migration for existing installations.
    """
    try:
        if frappe.db.exists("DocType", "Factory Settings"):
            frappe.db.set_single_value("Factory Settings", "consume_on_scan", 1)
            frappe.db.commit()
            
            frappe.logger().info("Set consume_on_scan to 1 in Factory Settings")
            frappe.logger().info("This setting is now hardcoded and will always be True")
    except Exception as e:
        frappe.logger().warning(f"Could not update consume_on_scan field: {str(e)}")
        frappe.logger().warning("This is expected if the field was already removed")
