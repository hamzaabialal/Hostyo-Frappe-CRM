import json

import frappe
from frappe import _
from frappe.query_builder import JoinType, Order


@frappe.whitelist()
def is_meetings_enabled():
	"""Whether the Meetings tab should show - gated on frappe_appointment
	actually being installed on this bench, same role
	whatsapp_integration.api.is_sms_enabled plays for the SMS tab (that
	function's own source isn't available to mirror line-for-line - it's a
	separate app not present in this repo and not publicly hosted - so this
	follows the same simple whitelisted-boolean-check shape rather than a
	verified exact copy of its internals).
	"""
	return "frappe_appointment" in frappe.get_installed_apps()


@frappe.whitelist()
def book_meeting(
	duration_id: str,
	date: str,
	start_time: str,
	end_time: str,
	user_timezone_offset: str,
	user_name: str,
	user_email: str,
	reference_doctype: str,
	reference_name: str,
	other_participants: str = None,
	meeting_type: str = None,
):
	"""Book a meeting slot via frappe_appointment and link the resulting Event
	back to a CRM Lead/Deal.

	frappe_appointment's own personal_meet.book_time_slot already accepts a
	custom_doctype_link_with_event kwarg - a JSON list of
	{reference_doctype, reference_docname, value} dicts matching its own
	"Event DocType Link" child table schema exactly (confirmed against its
	source: event_override._create_event_for_appointment_group reads
	event_info.get("custom_doctype_link_with_event", "[]") and writes it onto
	the created Event) - and it merges this in with the organizer's own
	auto-added link rather than replacing it. So the CRM reference is passed
	straight through as an extra link entry here, instead of inserting a
	separate Event DocType Link row afterwards - doing both would duplicate
	the link frappe_appointment already writes.

	frappe_appointment is imported lazily (inside the function, not at module
	level) so this file doesn't fail to import - and doesn't affect site boot
	for anything else in this module - on a bench where frappe_appointment
	isn't installed yet.

	Deliberately calls book_time_slot's own Python function directly rather
	than going through frappe.call/the HTTP layer - it's a plain in-process
	function call to another installed app's module, same as pbx_integration
	calling into crm's own doctype controllers. Its @frappe.whitelist
	decorator only gates HTTP access; calling the decorated name directly in
	Python still runs whatever its decorators do (including
	@add_response_code, whose exact behavior on the returned tuple/dict
	wasn't traced further here - worth confirming once this is actually
	wired up and testable end to end).
	"""
	if not frappe.has_permission(reference_doctype, "read", reference_name):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	from frappe_appointment.api.personal_meet import book_time_slot

	custom_doctype_link_with_event = json.dumps(
		[
			{
				"reference_doctype": reference_doctype,
				"reference_docname": reference_name,
				"value": reference_name,
			}
		]
	)

	response = book_time_slot(
		duration_id=duration_id,
		date=date,
		start_time=start_time,
		end_time=end_time,
		user_timezone_offset=user_timezone_offset,
		user_name=user_name,
		user_email=user_email,
		other_participants=other_participants,
		custom_doctype_link_with_event=custom_doctype_link_with_event,
	)

	# meeting_type is a CRM-only custom field frappe_appointment has no
	# knowledge of. Whether an unrecognized **args key like this would
	# actually reach the created Event if passed through book_time_slot
	# wasn't verified - only _create_event_for_appointment_group's return
	# statement was inspected earlier, not its full doc-creation body, so
	# nothing about its **args handling is confirmed either way. Rather than
	# gamble on that, it's set explicitly here once the Event actually
	# exists, via the same frappe.db.set_value pattern used throughout
	# pbx_integration/telnyx.py - a mechanism already proven to work in this
	# codebase, not an assumption.
	if meeting_type:
		body = response[0] if isinstance(response, (list, tuple)) else response
		event_id = (body or {}).get("event_id")
		if event_id:
			frappe.db.set_value("Event", event_id, "meeting_type", meeting_type)
			frappe.db.commit()

	# book_time_slot can return a plain dict (success, or some error paths)
	# or a (dict, status_code) tuple (confirmed for at least the "no user
	# found" 404 case in its own source) - pass either shape straight through
	# rather than assuming one, since the frontend caller needs to handle
	# whatever add_response_code's wrapping actually produces.
	return response


@frappe.whitelist()
def get_meetings(reference_doctype: str = None, reference_name: str = None):
	"""List meetings (Events) linked to a CRM Lead/Deal via frappe_appointment's
	"Event DocType Link" child table, following the same
	child-table-join shape crm.api.activities.get_linked_calls uses for
	CRM Call Log's Dynamic Link rows.

	reference_doctype/reference_name are now optional (both together, or
	neither) - when omitted, this returns every meeting linked to ANY CRM
	Lead/Deal (still scoped to the Event DocType Link join, so an unrelated
	Event on the bench with no CRM link at all won't show up here) - the data
	source for the new top-level Meetings sidebar page, alongside the
	existing per-record Meetings tab.

	Extended in place rather than adding a separate get_all_meetings():
	checked first whether this repo has an existing global-vs-per-record API
	pairing convention to follow (it doesn't - every function in
	activities.py is per-record only, e.g. get_activities(name), and
	telnyx.py has no listing endpoints at all, so there's no local precedent
	either way). Given that, extending in place was chosen because (a) the
	join/participant-merge logic below is otherwise identical between the two
	cases - a separate function would either duplicate it or immediately call
	back into this one, and (b) the frontend already calls this one method
	name from both MeetingsListView.vue and MeetingsCalendarView.vue, so one
	flexible endpoint lets the new global page reuse those same components
	with a parameter change rather than needing a second endpoint name wired
	through them too.
	"""
	# "Event DocType Link" only exists as a table once frappe_appointment is
	# installed - it's that app's own doctype, not core Frappe's. Unlike
	# book_meeting() (which lazily imports frappe_appointment and would fail
	# loudly if it isn't there), this function had no equivalent guard - it
	# would throw a raw "table doesn't exist" SQL error instead of a clean
	# response. In normal use the frontend never calls this when
	# is_meetings_enabled() is false, but this function shouldn't rely on
	# that alone to stay safe if ever called directly. Same installed-apps
	# check is_meetings_enabled() itself uses, checked first and before any
	# permission check - if the feature isn't installed at all, there's
	# nothing to permission-check against yet either.
	if "frappe_appointment" not in frappe.get_installed_apps():
		return []

	if reference_doctype or reference_name:
		if not (reference_doctype and reference_name):
			frappe.throw(_("Both reference_doctype and reference_name are required together"))
		if not frappe.has_permission(reference_doctype, "read", reference_name):
			frappe.throw(_("Not permitted"), frappe.PermissionError)
	else:
		# Global mode: there's no single record to permission-check against,
		# so this gates on doctype-level read permission for the CRM
		# doctypes meetings actually link to instead - the same level Frappe's
		# own list views check before a user can open the list at all, before
		# any row-level check happens.
		if not (frappe.has_permission("CRM Lead", "read") or frappe.has_permission("CRM Deal", "read")):
			frappe.throw(_("Not permitted"), frappe.PermissionError)

	EventLink = frappe.qb.DocType("Event DocType Link")
	Event = frappe.qb.DocType("Event")

	# event_participants is a child table (Frappe core's "Event Participants"
	# doctype, istable=1) - not a column on Event's own row - so it can't be
	# selected directly here the way the rest of these fields can. Fetched as
	# a second, separate query below and merged in per event, same
	# two-query-then-merge shape get_linked_calls uses for CRM Call Log's
	# Dynamic Link rows (query the base rows first, then a child/related
	# table filtered by those rows' names, then combine in Python).
	query = (
		frappe.qb.from_(EventLink)
		.join(Event, JoinType.inner)
		.on(Event.name == EventLink.parent)
		.select(
			Event.name,
			Event.subject,
			Event.starts_on,
			Event.ends_on,
			Event.all_day,
			Event.status,
			Event.meeting_type,
			Event.custom_meeting_provider,
			Event.custom_meet_link,
			Event.owner,
			Event.creation,
			Event.modified,
		)
		.where(EventLink.parenttype == "Event")
		.orderby(Event.starts_on, order=Order.desc)
	)
	if reference_doctype and reference_name:
		query = query.where(EventLink.reference_doctype == reference_doctype).where(
			EventLink.reference_docname == reference_name
		)

	meetings = query.run(as_dict=True)
	if not meetings:
		return meetings

	event_names = [m.name for m in meetings]

	Participant = frappe.qb.DocType("Event Participants")
	participant_query = (
		frappe.qb.from_(Participant)
		.select(
			Participant.parent,
			Participant.reference_doctype,
			Participant.reference_docname,
			Participant.email,
			Participant.attending,
		)
		.where(Participant.parenttype == "Event")
		.where(Participant.parent.isin(event_names))
	)
	participant_rows = participant_query.run(as_dict=True)

	participants_by_event = {}
	for row in participant_rows:
		participants_by_event.setdefault(row.parent, []).append(
			{
				"reference_doctype": row.reference_doctype,
				"reference_docname": row.reference_docname,
				"email": row.email,
				"attending": row.attending,
			}
		)

	for meeting in meetings:
		meeting["event_participants"] = participants_by_event.get(meeting.name, [])

	return meetings
