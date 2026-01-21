# Copyright (c) 2026, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import frappe
from frappe import _

def validate_batch_spaces(doc, method=None):
    """
    Validate and process spaces in batch_id according to Factory Settings.
    This hook fires when a Batch is created or updated via the UI.
    
    Args:
        doc: The Batch document being validated
        method: Hook method name (optional)
    """
    from isnack.isnack.page.storekeeper_hub.storekeeper_hub import _process_batch_spaces
    
    if doc.batch_id:
        # Process the batch_id according to settings
        processed_batch_id = _process_batch_spaces(doc.batch_id)
        
        # Update the batch_id if it was changed
        if processed_batch_id != doc.batch_id:
            doc.batch_id = processed_batch_id
