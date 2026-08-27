# Editing Sales Invoice Remarks After Submit

`Sales Invoice.remarks` is now editable on a submitted invoice, without amending
or cancelling it.

## Why

`remarks` is the free-text note the iSnack Sales Invoice print format puts under
the terms:

```jinja
{# isnack/isnack/print_format/sales_invoice/sales_invoice.json #}
{% if doc.remarks and doc.remarks != "No Remarks" %}
```

ERPNext fills that field in `before_submit` and never again — if it is empty at
submit time it becomes either `Against Customer Order <po_no>` or the literal
`No Remarks`:

```python
# erpnext/accounts/doctype/sales_invoice/sales_invoice.py (version-15)
def before_submit(self):
    self.add_remarks()

def add_remarks(self):
    if not self.remarks:
        ...
        self.remarks = _("No Remarks")
```

Upstream ships the field without `allow_on_submit`, so a note that was missed or
mistyped could only be corrected by cancelling and amending the invoice — a new
invoice number for a text change.

## The change

| | |
|---|---|
| Doctype | Sales Invoice (More Info tab → Additional Info) |
| Field | `remarks` (Small Text) |
| Property | `allow_on_submit` = **1** |
| Property Setter | `Sales Invoice-remarks-allow_on_submit` |

Shipped as a Property Setter in `isnack/isnack/custom/sales_invoice.json`
(`sync_on_migrate: 1`), the same mechanism the app uses for its other doctype
customisations — the equivalent of ticking *Allow on Submit* in Customize Form,
but version-controlled. It applies on `bench migrate`; nothing in `apps/erpnext`
or `apps/frappe` is touched.

Editing on a submitted document requires the **submit** permission, not just
write: frappe's `Document.set_docstatus` calls `check_permission("submit")` for
the `update_after_submit` action. Users who can only read or write submitted
invoices still cannot change the remark.

## Why it is safe

* **Nothing overwrites the new text.** `add_remarks()` runs in `before_submit`
  only. On a submitted document frappe runs `before_update_after_submit` instead
  of `validate` (`frappe/model/document.py`, `run_before_save_methods`), so the
  "No Remarks" default cannot come back and re-blank or re-derive the field.
* **No accounting is reposted.** `SalesInvoice.on_update_after_submit` triggers a
  repost only when one of the account fields it lists changes
  (`additional_discount_account`, `cash_bank_account`, `write_off_account`, the
  item/tax accounts, …). `remarks` is not one of them, and the field carries no
  value used by any calculation.
* **The rest of the document is still frozen.** `allow_on_submit` is per field;
  frappe's `_validate_update_after_submit` continues to reject a change to any
  other field of a submitted invoice.

## Known limitation

**Ledger remarks keep the text as posted.** `AccountsController.get_gl_dict`
copies `remarks` into every GL Entry at submit time, and
`get_payment_ledger_entries` carries it on into the Payment Ledger Entries.
Editing the invoice afterwards does not rewrite those rows, so the General
Ledger report with *Show Remarks* on still shows the wording that was posted.
That is deliberate — the invoice is the document that gets reprinted, while the
ledger keeps what it recorded at posting time. Amend the invoice if the ledger
text itself has to change.
