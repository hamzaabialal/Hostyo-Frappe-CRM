import json
from datetime import datetime, timedelta, timezone

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


def _combine_date_time(date, time_str):
	"""frappe_appointment's book_time_slot eventually passes start_time/
	end_time into utc_to_sys_time(), which calls datetime.fromisoformat()
	directly on whatever it's given - date is never merged in on
	frappe_appointment's side (confirmed against its source: date is only
	used there for separate slot-validity checks). BookMeetingModal.vue
	sends bare clock times from an <input type="time"> ("17:55", no
	seconds) for start_time and a client-computed "18:25:00" (with seconds)
	for end_time - neither is a full datetime, and they aren't even
	consistent with each other on seconds - so this combines each with date
	here, padding on ":00" when seconds are missing. Just the local
	wall-clock combination - see _local_to_utc_iso for the UTC conversion
	that actually has to happen before either reaches book_time_slot.
	"""
	if not time_str or "T" in time_str:
		return time_str
	if time_str.count(":") == 1:
		time_str = f"{time_str}:00"
	return f"{date}T{time_str}"


def _local_to_utc_iso(date, time_str, user_timezone_offset):
	"""utc_to_sys_time() (see _combine_date_time's docstring) does no timezone
	conversion of its own - it strips tzinfo and assumes whatever it's given
	already IS UTC. _combine_date_time only produces a LOCAL wall-clock
	datetime (the agent's own browser time, from date + start_time/end_time
	as picked in the booking form), so that has to actually be converted to
	UTC before it reaches book_time_slot, or every meeting lands at the
	wrong wall-clock time for any agent not in UTC - silently, no crash.

	Sign convention for user_timezone_offset (confirmed, don't flip this):
	BookMeetingModal.vue sends it as the browser's raw, unmodified
	JS Date#getTimezoneOffset() value - minutes, POSITIVE when the local
	zone is BEHIND UTC (e.g. UTC-4 -> +240, matching a real failing request),
	NEGATIVE when ahead (e.g. UTC+5:30 -> -330). That's JS's own documented
	convention, and it's the OPPOSITE sign from the usual "+HH:MM east of
	UTC" notation. So: UTC = local + offset_minutes.

	Note frappe_appointment's OWN internal availability-window validation
	(is_valid_time_slots/hours_to_time_slot, via utc_to_given_time_zone ->
	pytz.FixedOffset(int(user_timezone_offset))) reads this same raw value
	with the OPPOSITE (conventional, east-of-UTC-positive) sign - a
	pre-existing mismatch inside frappe_appointment itself, not introduced
	here. This function's own math is UNAFFECTED by that and must stay
	exactly as it is below - it only controls what's actually stored as the
	event's start/end, using user_timezone_offset RAW, in its original
	(JS getTimezoneOffset) sign.

	As of 2026-09-04, that mismatch is moot for the actual call path -
	book_meeting now calls pbx_integration.personal_meetings.
	book_personal_meeting, which doesn't call is_valid_time_slots/
	hours_to_time_slot at all (see that module's docstring for why). The
	sign-flip helper this docstring used to point at
	(_frappe_appointment_timezone_offset, below) is left in place but
	unused for the same reason. Still worth keeping this note here: if that
	validation chain is ever called from this file again, do not fix its
	sign mismatch by touching this function's math - they are deliberately
	different conventions feeding two different pieces of code.

	Returned as a space-separated string with an explicit UTC offset (e.g.
	"2026-09-04 16:55:00+00:00"), not a bare T-separated one - confirmed via
	a live traceback that is_valid_time_slots (in the same book_time_slot ->
	_create_event_for_appointment_group chain this feeds) parses start_time/
	end_time with datetime.strptime(value, "%Y-%m-%d %H:%M:%S%z"), which
	needs both the space separator and an offset; a bare T-separated,
	offset-less string raises ValueError there. utc_to_sys_time's own
	fromisoformat() call (the other consumer of this same value, inside
	_create_event_for_appointment_group) accepts this format identically to
	the old one - verified empirically, not assumed: parsing this and then
	.replace(tzinfo=None) yields the exact same naive datetime either way,
	since the attached offset is +00:00 (no actual shift).
	"""
	combined = _combine_date_time(date, time_str)
	if not combined:
		return combined
	local_dt = datetime.fromisoformat(combined)
	utc_dt = (local_dt + timedelta(minutes=int(user_timezone_offset))).replace(tzinfo=timezone.utc)
	return utc_dt.isoformat(sep=" ")


def _frappe_appointment_timezone_offset(user_timezone_offset):
	"""UNUSED as of 2026-09-04 - book_meeting now calls
	pbx_integration.personal_meetings.book_personal_meeting instead of
	frappe_appointment's book_time_slot chain, which no longer runs
	is_valid_time_slots/hours_to_time_slot (the only consumers of this
	flipped value) at all. Left in place, not deleted, in case that
	validation chain is ever called from here again - same reasoning as
	leaving pbx_integration/overrides/personal_meet.py in place unused.

	Flip user_timezone_offset's sign for the SEPARATE copy of it passed
	straight through as book_time_slot's own user_timezone_offset parameter
	- NOT for _local_to_utc_iso above, which must keep using the raw value
	unflipped (see that function's docstring - two different conventions,
	deliberately, feeding two different pieces of code).

	frappe_appointment's own availability-window validation
	(is_valid_time_slots/hours_to_time_slot in appointment_group.py) feeds
	this value into pytz.FixedOffset(int(user_timezone_offset)) - a
	convention where positive means AHEAD of UTC. BookMeetingModal.vue sends
	the browser's raw JS Date#getTimezoneOffset() value instead - positive
	means BEHIND UTC, the opposite sign meaning. Left unflipped, this
	mismatch made is_valid_time_slots reject genuinely available slots
	outright, on every single booking - confirmed via a live traceback and
	reproduced offline against frappe_appointment's real functions: a real
	UTC-4 browser's raw offset ("240") computed a real, listed slot's own
	"local day" as one day later than it actually was (frappe_appointment's
	pytz.FixedOffset(240) reads as UTC+4, not the intended UTC-4), which
	then failed both the day-bucket selection AND the per-slot day filter
	inside that validation. Negating it here ("-240") made the same slot
	compute its correct local day and pass - verified the same way, not
	assumed.

	Do not "fix" this by touching _local_to_utc_iso's own math instead -
	that function already uses the correct, unflipped convention for what
	it does (computing the actual stored start/end), and flipping it there
	would make every meeting land at the wrong wall-clock time while
	leaving this validation-only mismatch untouched.
	"""
	return str(-int(user_timezone_offset))


@frappe.whitelist()
def get_available_durations(user="Administrator"):
	"""Return the given organizer's configured meeting-length options, for
	BookMeetingModal.vue's "Duration" select - previously a hardcoded
	15/30/45/60-minute list with no connection to any real backend data, and
	a separate free-text "Duration Slot ID" field the user had to know and
	type by hand (e.g. hostyo-30m, or the 15m/45m rows' auto-generated hash
	names, created via the Desk UI rather than console - not something
	anyone could reasonably remember or retype).

	available_durations is frappe_appointment's own child table
	(Appointment Slot Duration, a child of User Appointment Availability),
	fetched via frappe.get_doc rather than frappe.client.get_list -
	confirmed by testing that get_list hits check_parent_permission and
	throws PermissionError against this child table under the current
	user's permissions, where get_doc on the parent does not.

	duration is returned in seconds, exactly as stored - Frappe's standard
	Duration fieldtype convention (confirmed against the live site: e.g.
	the "15 Min Call" row stores 900, not 15) - deliberately not converted
	here, so the frontend's end-time math and this field's actual meaning
	can't quietly drift apart from what frappe_appointment itself uses this
	same stored value for (duration.duration is passed straight through
	into its own dummy Appointment Group's duration_for_event untouched).

	No permission check beyond the child-table access itself: this only
	exposes duration labels/lengths for an organizer's *personal meeting*
	booking page, the same information frappe_appointment's own
	get_meeting_windows already exposes to allow_guest callers - nothing
	sensitive.
	"""
	availability = frappe.get_doc("User Appointment Availability", user)
	return [
		{"name": row.name, "title": row.title, "duration": row.duration}
		for row in availability.available_durations
	]


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

	As of 2026-09-04, calls pbx_integration's own personal_meetings.
	book_personal_meeting instead of frappe_appointment's book_time_slot (via
	either the original or pbx_integration/overrides/personal_meet.py, our
	earlier bugfixed fork of it) - after three separate pre-existing bugs
	found and fixed in that upstream chain in a row, a 4th "Invalid attendee
	email" 400 still happened even with all three fixes applied. Rather than
	keep patching someone else's library bug by bug, book_personal_meeting
	reimplements only what booking a personal meeting actually needs, from
	pieces individually tested and confirmed working on this site. See that
	module's own docstring for the full reasoning, including a deliberate
	scope decision (a simple double-booking check, not a reimplementation of
	frappe_appointment's weekly-availability-window logic).
	The old fork is left in place, unused, in case it's needed for reference.
	"""
	if not frappe.has_permission(reference_doctype, "read", reference_name):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	from pbx_integration.personal_meetings import book_personal_meeting

	# TEMPORARY DEBUG LOGGING - remove once the reported booking time-shift
	# bug is confirmed fixed or root-caused. frappe.log_error proved
	# unreliable for tracing this specific bug this session (writes to the
	# DB-backed Error Log doctype, which is why); using frappe.logger's own
	# file-backed logger instead - writes real lines to
	# sites/<site>/logs/meeting_debug.log regardless of what else happens in
	# this request, tail-able directly. "[MEETING_DEBUG]" prefix on every
	# line keeps them greppable among anything else that log file might ever
	# contain.
	debug_logger = frappe.logger("meeting_debug", allow_site=True)
	debug_logger.info(
		f"[MEETING_DEBUG] raw input date={date!r} start_time={start_time!r} "
		f"end_time={end_time!r} user_timezone_offset={user_timezone_offset!r}"
	)

	custom_doctype_link_with_event = json.dumps(
		[
			{
				"reference_doctype": reference_doctype,
				"reference_docname": reference_name,
				"value": reference_name,
			}
		]
	)

	utc_start_time = _local_to_utc_iso(date, start_time, user_timezone_offset)
	utc_end_time = _local_to_utc_iso(date, end_time, user_timezone_offset)
	debug_logger.info(
		f"[MEETING_DEBUG] _local_to_utc_iso output start_time={utc_start_time!r} end_time={utc_end_time!r}"
	)

	response = book_personal_meeting(
		duration_id=duration_id,
		date=date,
		start_time=utc_start_time,
		end_time=utc_end_time,
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
	body = response[0] if isinstance(response, (list, tuple)) else response
	event_id = (body or {}).get("event_id")

	# TEMPORARY DEBUG LOGGING - see note above.
	if event_id:
		stored_starts_on, stored_ends_on = frappe.db.get_value("Event", event_id, ["starts_on", "ends_on"])
		debug_logger.info(
			f"[MEETING_DEBUG] Event {event_id} stored starts_on={stored_starts_on!r} ends_on={stored_ends_on!r}"
		)
	else:
		debug_logger.info(f"[MEETING_DEBUG] no event_id in response: {response!r}")

	if meeting_type and event_id:
		frappe.db.set_value("Event", event_id, "meeting_type", meeting_type)
		frappe.db.commit()

	# book_time_slot can return a plain dict (success, or some error paths)
	# or a (dict, status_code) tuple (confirmed for at least the "no user
	# found" 404 case in its own source) - pass either shape straight through
	# rather than assuming one, since the frontend caller needs to handle
	# whatever add_response_code's wrapping actually produces.
	return response


@frappe.whitelist()
def get_meetings(
	reference_doctype: str = None,
	reference_name: str = None,
	start: int = 0,
	page_length: int = None,
):
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

	start/page_length: pagination for MeetingsListView.vue, matching this
	CRM's own Leads/Deals list convention - a 20-row page fetched via
	"Load More" rather than numbered pages (confirmed against frappe/crm's
	own Leads.vue: updatedPageCount defaults to 20, loaded incrementally,
	not paged numerically). page_length defaults to None (no LIMIT at all,
	today's original behavior) rather than defaulting to 20 outright -
	MeetingsCalendarView.vue calls this same endpoint and needs every
	meeting in view to render the calendar grid and legend correctly, not
	just the first page; only MeetingsListView.vue actually passes these
	two params.
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
			Event.description,
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
	if page_length is not None:
		query = query.limit(page_length).offset(start)
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
