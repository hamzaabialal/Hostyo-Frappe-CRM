import frappe


def execute():
	"""Add the signwell_document_id custom field to CRM Deal: stores the
	SignWell document id returned when a contract is sent, so the
	document_completed webhook (pbx_integration.signwell.handle_signwell_webhook)
	can find its way back to the right deal.
	"""
	if frappe.db.exists("Custom Field", "CRM Deal-signwell_document_id"):
		return

	frappe.get_doc(
		{
			"doctype": "Custom Field",
			"dt": "CRM Deal",
			"fieldname": "signwell_document_id",
			"label": "SignWell Document ID",
			"fieldtype": "Data",
			"read_only": 1,
			"insert_after": "property_address",
			"description": (
				"Set automatically when a contract is sent via SignWell (send_contract). "
				"Used to match the document_completed webhook back to this deal."
			),
		}
	).insert(ignore_permissions=True)
