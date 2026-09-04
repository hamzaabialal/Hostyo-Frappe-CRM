import frappe


def execute():
	"""Add the contract_sent_on custom field to CRM Deal: the date the
	SignWell contract was generated/sent, set automatically by
	pbx_integration.signwell.send_contract.
	"""
	if frappe.db.exists("Custom Field", "CRM Deal-contract_sent_on"):
		return

	frappe.get_doc(
		{
			"doctype": "Custom Field",
			"dt": "CRM Deal",
			"fieldname": "contract_sent_on",
			"label": "Contract Sent On",
			"fieldtype": "Date",
			"read_only": 1,
			"insert_after": "signwell_document_id",
			"description": "Date the SignWell contract was sent (set automatically by send_contract).",
		}
	).insert(ignore_permissions=True)
