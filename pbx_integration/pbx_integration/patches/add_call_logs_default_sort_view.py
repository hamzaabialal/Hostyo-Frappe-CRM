import frappe


def execute():
	"""Ship a standard "CRM View Settings" record for the Call Logs list so
	it defaults to most-recent-call-first instead of the CRM frontend's
	generic fallback (ViewControls.vue: `_view?.order_by || 'modified desc'`).

	No standard view currently exists for CRM Call Log's list, so it was
	silently falling through to that "modified desc" default - and
	`modified` bumps on any later field write (status change on hangup,
	recording_url landing, and now call_transcript/ai_summary arriving via
	the async transcription webhook), so a call touched more recently can
	outrank a call that actually happened more recently.

	crm.api.views.get_views only filters on `dt` and `user in ("", session
	user)` - `user=""` here is what makes this apply to every user, not
	just whoever the patch runs as.
	"""
	if frappe.db.exists("CRM View Settings", {"dt": "CRM Call Log", "type": "list", "is_standard": 1}):
		return

	frappe.get_doc(
		{
			"doctype": "CRM View Settings",
			"dt": "CRM Call Log",
			"type": "list",
			"route_name": "Call Logs",
			"label": "Call Logs",
			"is_standard": 1,
			"user": "",
			"order_by": "creation desc",
		}
	).insert(ignore_permissions=True)
