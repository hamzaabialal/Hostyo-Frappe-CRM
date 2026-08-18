import frappe


def execute():
	"""Add the telnyx_did custom field to User: the Telnyx DID (E.164 number)
	that should ring only this user for inbound calls, instead of the whole
	ring-group. Left blank, the user stays part of the general ring-group.
	"""
	if frappe.db.exists("Custom Field", "User-telnyx_did"):
		return

	frappe.get_doc(
		{
			"doctype": "Custom Field",
			"dt": "User",
			"fieldname": "telnyx_did",
			"label": "Telnyx DID",
			"fieldtype": "Data",
			"insert_after": "pbx_extension",
			"description": (
				"Telnyx phone number (E.164, e.g. +35700000000) assigned to this user. "
				"Inbound calls to this exact number ring only this user. Leave blank to "
				"keep this user in the general inbound ring-group."
			),
		}
	).insert(ignore_permissions=True)
