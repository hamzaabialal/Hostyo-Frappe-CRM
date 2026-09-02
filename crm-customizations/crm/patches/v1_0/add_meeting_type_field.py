import frappe


def execute():
	"""Add the meeting_type custom field to Event: a CRM-specific meeting
	category (Property Viewing, Onboarding Call, etc.) used by the Meetings
	feature's calendar color-coding and per-row icons. Event has no such
	field natively - this is purely a CRM/Meetings-feature concept, not
	something frappe_appointment or core Frappe defines.

	Follows the exact pattern already established in this codebase for
	adding a custom field to a base doctype -
	pbx_integration/patches/add_telnyx_did_field.py (Custom Field doc,
	exists-check guard, ignore_permissions insert) - rather than a fixtures
	JSON, since that pattern already exists and works.
	"""
	if frappe.db.exists("Custom Field", "Event-meeting_type"):
		return

	frappe.get_doc(
		{
			"doctype": "Custom Field",
			"dt": "Event",
			"fieldname": "meeting_type",
			"label": "Meeting Type",
			"fieldtype": "Select",
			"options": (
				"\nProperty Viewing\nOnboarding Call\nFollow-up Call\nNegotiation Call\n"
				"Product Demo\nTechnical Review\nIntroductory Meeting\nOther"
			),
			"insert_after": "subject",
			"description": "CRM meeting category - drives calendar color-coding and per-row icons in the Meetings feature.",
		}
	).insert(ignore_permissions=True)
