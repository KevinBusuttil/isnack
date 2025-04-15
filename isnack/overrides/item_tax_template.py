from erpnext.accounts.doctype.item_tax_template.item_tax_template import ItemTaxTemplate

class CustomItemTaxTemplate(ItemTaxTemplate):
    def get_title(self):
        print(f'In title')
        return f"{self.name} - {self.custom_description or ''}"