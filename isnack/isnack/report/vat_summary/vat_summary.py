# Copyright (c) 2025, Busuttil Technologies Limited and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def execute(filters=None):
    columns = get_columns()
    data = get_data(filters)
    
    return  columns, data



def get_data(filters):
    from_date, to_date = filters.get('from'), filters.get('to')
    company = filters.get('company')
    
    sales_conditions = " "
    purchase_conditions = " "
    service_conditions = " "
    reversed_je_conditions = " "
        
    if(filters.get('voucher')):
        sales_conditions += f" AND siv.name='{filters.get('voucher')}' "
        purchase_conditions += f" AND piv.name='{filters.get('voucher')}' "
        service_conditions += f" AND svi.name='{filters.get('voucher')}' "
        reversed_je_conditions += f" AND je.name='{filters.get('voucher')}' "
            
    if(filters.get('vat_code')):
        sales_conditions += f" AND it.item_tax_template='{filters.get('vat_code')}' "
        purchase_conditions += f" AND it.item_tax_template='{filters.get('vat_code')}' "
        service_conditions += f" AND svii.vat_code='{filters.get('vat_code')}' "
        reversed_je_conditions += f" AND svii.vat_code='{filters.get('vat_code')}' "
            
    sql = f"""
	(SELECT
		'Sales Invoice',
		it.item_tax_template, 
		SUM(sii.net_amount), 
		ittd.tax_rate, 
		SUM((((ittd.tax_rate)/100) * sii.net_amount)) AS vat_amount
	FROM `tabSales Invoice Item` AS sii
	JOIN `tabSales Invoice` AS siv
		ON siv.name=sii.parent
	JOIN `tabItem` AS i
		ON i.name=sii.item_code
	JOIN `tabItem Tax` AS it
		ON it.parent=i.item_group AND it.tax_category=siv.tax_category
	JOIN `tabItem Tax Template Detail` as ittd
		ON ittd.parent=it.item_tax_template
	WHERE siv.status not in ('Draft', 'Cancelled')
    AND siv.company = '{company}'
	AND (siv.posting_date BETWEEN '{from_date}' AND '{to_date}' ) {sales_conditions}
	GROUP BY it.item_tax_template)
	
    UNION ALL
	
    (SELECT
		'Purchase Invoice',
		COALESCE(it_item.item_tax_template, it_group.item_tax_template) AS item_tax_template, 
		SUM(pii.net_amount), 
		COALESCE(ittd_item.tax_rate, ittd_group.tax_rate) AS tax_rate, 
		SUM((COALESCE(ittd_item.tax_rate, ittd_group.tax_rate)/100) * pii.net_amount) AS vat_amount
	FROM `tabPurchase Invoice Item` AS pii
	JOIN `tabPurchase Invoice` AS piv
		ON piv.name=pii.parent
	JOIN `tabItem` AS i
		ON i.name=pii.item_code
	LEFT JOIN `tabItem Tax` AS it_item  -- Join for item-specific tax
		ON it_item.parent = i.name AND it_item.tax_category = piv.tax_category 
	LEFT JOIN `tabItem Tax` AS it_group -- Join for item group tax
		ON it_group.parent = i.item_group AND it_group.tax_category = piv.tax_category
	LEFT JOIN `tabItem Tax Template Detail` as ittd_item  -- Join for item-specific tax detail
		ON ittd_item.parent = it_item.item_tax_template
	LEFT JOIN `tabItem Tax Template Detail` as ittd_group -- Join for item group tax detail
		ON ittd_group.parent = it_group.item_tax_template
	WHERE piv.status not in ('Draft', 'Cancelled')
    AND piv.company = '{company}'
	AND (piv.posting_date BETWEEN '{from_date}' AND '{to_date}' ) {purchase_conditions}
	AND COALESCE(ittd_item.tax_rate, ittd_group.tax_rate) IS NOT NULL
	GROUP BY COALESCE(it_item.item_tax_template, it_group.item_tax_template))
    
    UNION ALL
    
    (SELECT
        'Service Invoice',
		svii.vat_code AS item_tax_template, 
		SUM(svii.credit - svii.debit) AS net_amount, 
		ittd.tax_rate, 
        SUM(CASE 
            WHEN svi.vat_inclusive = 1 THEN (svii.credit-svii.debit) * (1 - (1/(1+(ittd.tax_rate/100))))
            ELSE (ittd.tax_rate/100) * (svii.credit-svii.debit)
        END) AS vat_amount
    FROM `tabService Invoice Items` AS svii
    JOIN `tabService Invoice` AS svi on svii.parent = svi.name
	JOIN `tabItem Tax Template Detail` as ittd
		ON ittd.parent=svii.vat_code
    WHERE svii.vat_code is not null
    AND svii.docstatus not in ('Draft', 'Cancelled')    
    AND svi.company = '{company}'
	AND (svii.date BETWEEN '{from_date}' AND '{to_date}' ) {service_conditions}
	GROUP BY svii.vat_code)

	UNION ALL

    (SELECT 
	ReversedEntries.journal_type,
	ReversedEntries.item_tax_template,
	SUM(ReversedEntries.net_amount) AS net_amount,
	ReversedEntries.tax_rate,
	SUM(ReversedEntries.vat_amount) AS vat_amount
	FROM 
		(SELECT distinct je.posting_date as posting_date,
					svii.party as item_code,
					svii.description as item_name,
					svii.party,
					svii.vat_code AS item_tax_template, 
					svii.debit-svii.credit AS net_amount, 
					ittd.tax_rate, 
					(((ittd.tax_rate)/100) * (svii.debit-svii.credit)) AS vat_amount,
					'Reversed' as journal_type,
					jesi.name as service_journal_voucher,
					je.name as journal_voucher
		FROM `tabJournal Entry Account` AS jea
		JOIN `tabJournal Entry` AS je on jea.parent = je.name
		JOIN `tabJournal Entry` AS jesi on je.reversal_of = jesi.name
		JOIN `tabService Invoice Items` AS svii on svii.journal_entry = jesi.name
		JOIN `tabService Invoice` AS svi on svi.name = svii.parent
		JOIN `tabItem Tax Template Detail` as ittd
				ON ittd.parent=svii.vat_code
		WHERE (je.posting_date BETWEEN '{from_date}' AND '{to_date}') {reversed_je_conditions}
		AND je.reversal_of IS NOT NULL
		AND svii.vat_code IS NOT NULL
		AND je.company = '{company}'
		order by je.name) AS ReversedEntries
	GROUP BY ReversedEntries.item_tax_template)
        
    ORDER BY 1
    """
    
    data = frappe.db.sql( sql )
        
    return data


def get_columns():
    return [
		{
			"label": _("Voucher Type"),
			"fieldname": "voucher_type",
			"fieldtype": "Link",
			"options": "Doctype",
			"width": 100,
		},
		{
			"label": _("VAT Code"),
			"fieldtype": "Link",
			"options": "Item Tax Template",
			"width": 150,
		},
		{
			"label": _("Amount Origin"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 150,
			"precision": 3,
		},
		{
			"label": _("Tax Rate"),
			"fieldtype": "Float",
			"width": 150,
			"precision": 2,
			"disable_total": 1
		},
		{
			"label": _("VAT Amount"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 150,
			"precision": 3,
		},
	]