import frappe


def execute():
	"""Add call_transcript and ai_summary custom fields to CRM Call Log.
	Both are set automatically by the Telnyx transcription webhook and the
	OpenAI summary job (pbx_integration.telnyx / pbx_integration.ai_summary).
	"""
	if not frappe.db.exists("Custom Field", "CRM Call Log-call_transcript"):
		frappe.get_doc(
			{
				"doctype": "Custom Field",
				"dt": "CRM Call Log",
				"fieldname": "call_transcript",
				"label": "Call Transcript",
				"fieldtype": "Long Text",
				"read_only": 1,
				"insert_after": "recording_url",
				"description": "Full transcript from Telnyx post-call transcription. Set automatically.",
			}
		).insert(ignore_permissions=True)

	if not frappe.db.exists("Custom Field", "CRM Call Log-ai_summary"):
		frappe.get_doc(
			{
				"doctype": "Custom Field",
				"dt": "CRM Call Log",
				"fieldname": "ai_summary",
				"label": "AI Summary",
				"fieldtype": "Small Text",
				"read_only": 1,
				"insert_after": "call_transcript",
				"description": "AI-generated summary of the call transcript. Set automatically.",
			}
		).insert(ignore_permissions=True)
