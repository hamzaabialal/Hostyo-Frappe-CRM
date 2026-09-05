"""Self-contained personal-meeting booking, replacing our dependency on
frappe_appointment's book_time_slot -> create_dummy_appointment_group ->
_create_event_for_appointment_group -> is_valid_time_slots chain entirely.

Added 2026-09-04, after finding and fixing three separate pre-existing bugs
in that chain in a row (wrong attendee email in event_participants, wrong
dict keys - doctype/name instead of reference_doctype/reference_docname -
in the custom_doctype_link_with_event dedup check, and an inverted
user_timezone_offset sign convention feeding is_valid_time_slots), and then
hitting a 4th "Invalid attendee email" 400 from Google Calendar's API even
with all three fixes applied, confirmed via a live bench execute test with
a fresh process (so not a caching artifact). Rather than keep patching
someone else's library bug by bug, this reimplements only what booking a
personal meeting actually needs, built from pieces individually tested and
confirmed working live on this site in this session:

- frappe.get_doc("Appointment Slot Duration", duration_id) and
  frappe.get_all("User Appointment Availability", filters={"name": ...})
  for looking up the organizer - no dummy Appointment Group object needed,
  since none of frappe_appointment's own slot-validation functions
  (is_valid_time_slots, vaild_date, check_availability,
  get_booking_frequency_reached, is_member_on_leave_or_is_holiday, the
  whole appointment_group.py chain) are called from here at all.
- frappe.integrations.doctype.google_calendar.google_calendar.
  get_google_calendar_object(calendar_name) - confirmed working, used only
  to read the organizer's google_calendar_id; the actual push to Google
  happens the same way it always did, via Frappe's own after_insert hook
  (insert_event_in_google_calendar_override, registered by
  frappe_appointment on the Event doctype) - not called from here directly,
  and not something this rewrite touches or needed to touch.
- A plain frappe.get_doc({"doctype": "Event", ...}).insert(ignore_permissions=True)
  with event_participants as a plain list of dicts using the correct
  reference_doctype/reference_docname/email keys - confirmed working, and
  confirmed the organizer's real email survives both immediately after
  insert and after a fresh reload from DB.
- frappe_appointment.helpers.utils.utc_to_sys_time and duration_to_string -
  kept, deliberately: both are plain, stateless conversion/formatting
  helpers with no DB queries or validation logic of their own, not part of
  the buggy chain being replaced here.

Deliberate scope decision, not a silent omission: this does its OWN simple
double-booking check (overlapping Event query against the organizer's
google_calendar) but does NOT reimplement frappe_appointment's
weekly-availability-window/day-slot-grid logic (which weekdays/hours the
organizer is actually available). That logic lives entirely in
appointment_group.py, which this file no longer calls at all. The
assumption is that the frontend's duration-based slot picker
(BookMeetingModal.vue) is the only gate on "is this a sensible time to
offer" - this backend only prevents two meetings from landing on the exact
same organizer at overlapping times, it does not enforce business hours.
If BookMeetingModal.vue is ever changed to let an agent pick a truly
arbitrary date/time (not driven by frappe_appointment's own slot-generation
UI, which isn't wired into this CRM's frontend at all today), that gap
would need revisiting.

pbx_integration/overrides/personal_meet.py (the frappe_appointment fork
with the first three fixes) is left in place, unused - not deleted, in case
this rewrite ever needs to cross-check what upstream does for something not
reimplemented here.

Bug #4, found even after this rewrite (confirmed live, 2026-09-04): the
same "Invalid attendee email" 400 still happened with a correctly-built
event_participants list, because frappe_appointment's OWN
EventOverride.before_insert() has:

    elif self.custom_user_calendar:
        self.user_calendar = frappe.get_doc(USER_APPOINTMENT_AVAILABILITY, self.custom_user_calendar)
        ...
        self.update_attendees_for_appointment_group()

Setting custom_user_calendar on the Event doc (which this file originally
did, to preserve metadata the old chain also set) triggers
update_attendees_for_appointment_group(), which overwrites our correctly-
built event_participants before insert - confirmed via a live isolated
test: identical Event dicts insert successfully with correct attendee
emails when custom_user_calendar/custom_appointment_slot_duration are
omitted, and fail the exact same way when they're included.

Fix: don't set custom_user_calendar or custom_appointment_slot_duration on
the Event doc at all - not a patch to that before_insert branch (we don't
control that file, same reasoning as every other bug in this chain), just
not triggering it in the first place. Their only purpose was
meeting-provider/Zoom/Meet-link setup (moot - this site's Meeting Provider
is "None") and powering the reschedule_url property (unused - no reschedule
UI exists anywhere in this CRM's frontend). Losing them costs nothing this
app actually uses.

The organizer self-link entry that used to be appended to
custom_doctype_link_with_event is also gone as of this fix - it only ever
existed to mirror upstream's own book_time_slot, was never read by
get_meetings/MeetingArea.vue (both only care about the CRM Lead/Deal
reference), and was dead weight independent of bug #4.
"""

import json
import re

import frappe
from frappe import _
from frappe.integrations.doctype.google_calendar.google_calendar import get_google_calendar_object
from frappe_appointment.helpers.utils import duration_to_string, utc_to_sys_time

EMAIL_RE = re.compile(r"[^@]+@[^@]+\.[^@]+")


def book_personal_meeting(
	duration_id: str,
	date: str,
	start_time: str,
	end_time: str,
	user_timezone_offset: str,
	user_name: str,
	user_email: str,
	other_participants: str = None,
	custom_doctype_link_with_event: str = None,
):
	"""Book a personal meeting directly, without going through
	frappe_appointment's own book_time_slot chain. See this module's
	docstring for why, and for the explicit slot-conflict-checking scope
	decision.

	Same parameter shape book_time_slot took, for a drop-in replacement at
	the one call site (crm.api.meetings.book_meeting) - user_timezone_offset
	is kept for that reason but is NOT used internally: nothing in this
	function's own logic runs through pytz.FixedOffset (the thing that
	needed a sign-corrected copy of this value for frappe_appointment's own
	validation - see meetings.py's _frappe_appointment_timezone_offset,
	which this function no longer needs since that validation chain isn't
	called from here). start_time/end_time already arrive as UTC datetime
	strings (crm.api.meetings._local_to_utc_iso's job), so no timezone math
	happens in this function at all.
	"""
	duration = frappe.get_doc("Appointment Slot Duration", duration_id)

	user_availability = frappe.get_all(
		"User Appointment Availability", filters={"name": duration.parent}, fields=["*"]
	)
	if not user_availability:
		frappe.throw(_("No organizer availability found for this booking."))
	user_availability = user_availability[0]

	starts_on = utc_to_sys_time(start_time)
	ends_on = utc_to_sys_time(end_time)

	# Deliberate, minimal conflict check - see module docstring's scope
	# decision. Excludes Cancelled events (a cancelled event doesn't
	# represent real calendar-busy time), but not Completed/Closed - those
	# would be unusual for a future slot, and this isn't the place to guess
	# at what those statuses should mean here.
	conflicting_events = frappe.get_all(
		"Event",
		filters={
			"google_calendar": user_availability.google_calendar,
			"status": ["!=", "Cancelled"],
			"starts_on": ["<", ends_on],
			"ends_on": [">", starts_on],
		},
		limit=1,
	)
	if conflicting_events:
		frappe.throw(_("This slot is not available, please book another slot."))

	organizer_email = frappe.get_value("User", user_availability.user, "email") or user_availability.user
	organizer_full_name = frappe.get_value("User", user_availability.user, "full_name")

	event_participants = [
		{
			"reference_doctype": "User Appointment Availability",
			"reference_docname": user_availability.name,
			"email": organizer_email,
		},
		{"email": user_email},
	]

	if other_participants:
		for participant in other_participants.split(","):
			participant = participant.strip()
			if EMAIL_RE.match(participant):
				event_participants.append({"email": participant})

	# No organizer self-link appended here (see module docstring, bug #4) -
	# get_meetings/MeetingArea.vue only ever query/read "Event DocType Link"
	# rows for the CRM Lead/Deal reference, never for "User Appointment
	# Availability" - confirmed by grepping this whole frontend/backend for
	# both terms. That self-link was already dead weight before bug #4 was
	# even found (it's custom_user_calendar alone that triggers
	# EventOverride.before_insert's buggy branch, not this field) - just no
	# longer worth adding back now that we know it serves nothing here.
	doctype_links = json.loads(custom_doctype_link_with_event) if custom_doctype_link_with_event else []

	duration_str = duration_to_string(duration.duration)
	subject = f"Meet: {user_name} <> {organizer_full_name} ({duration_str})"

	_google_calendar_api_obj, google_calendar_account = get_google_calendar_object(user_availability.google_calendar)

	event = frappe.get_doc(
		{
			"doctype": "Event",
			"subject": subject,
			"starts_on": starts_on,
			"ends_on": ends_on,
			"sync_with_google_calendar": 1,
			"google_calendar": user_availability.google_calendar,
			"google_calendar_id": google_calendar_account.google_calendar_id,
			"pulled_from_google_calendar": 0,
			"custom_sync_participants_google_calendars": 1,
			"event_participants": event_participants,
			"custom_doctype_link_with_event": doctype_links,
			"send_reminder": 0,
			"event_type": "Private",
		}
	)
	event.insert(ignore_permissions=True)
	frappe.db.commit()

	# Reload rather than trust the in-memory object post-insert - the same
	# caution already confirmed necessary for event_participants' email
	# during testing (checked both immediately after insert and after a
	# fresh reload) applies here too, for whatever
	# insert_event_in_google_calendar_override's after_insert hook fills in.
	event = frappe.get_doc("Event", event.name)

	return {
		"message": _("Event has been created"),
		"event_id": event.name,
		"meeting_provider": event.custom_meeting_provider,
		"meet_link": event.custom_meet_link,
		"google_calendar_event_url": event.custom_google_calendar_event_url,
	}
