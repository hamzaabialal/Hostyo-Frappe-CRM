"""Fork of frappe_appointment's api.personal_meet.book_time_slot, forked
2026-09-04, with two bugfixes so far (both pre-existing upstream, both
found via live tracebacks, neither introduced by this fork).

Bug 1 (confirmed via a live 400 from Google Calendar's API, "Invalid
attendee email", on every personal-meeting booking through
crm.api.meetings.book_meeting): the organizer's event_participants entry
is built from user_availability.get("user") - a User docname (e.g.
"Administrator"), not an email address - instead of looking up that
User's actual email. See the fix inline below.

Bug 2 (confirmed via a live KeyError: 'doctype'): the
custom_doctype_link_with_event dedup check used link["doctype"]/
link["name"], but every dict in that list actually uses
reference_doctype/reference_docname - the original keys raised KeyError
the moment a caller supplied its own custom_doctype_link_with_event, which
crm.api.meetings.book_meeting does on every call. See the fix inline below.

Not vendored anywhere in this repo (frappe_appointment is installed
separately, its source lives at
rtCamp/frappe-appointment/frappe_appointment/api/personal_meet.py), and not
worth patching the installed file directly since that gets wiped on any
frappe_appointment upgrade - forked here instead, registered via
override_whitelisted_methods in hooks.py, and imported directly by
crm.api.meetings.book_meeting in place of the original (see that file's own
import - override_whitelisted_methods only intercepts calls dispatched
through Frappe's HTTP method-call layer, frappe.handler.execute_cmd; it has
no effect on a direct Python import-and-call like book_meeting's own, so
that import also has to point here for the actual reported bugs to be
fixed, not just the raw HTTP endpoint).

Everything else below is an exact copy of the original. Check upstream next
time frappe_appointment is upgraded, in case these have since been fixed
there - if so, this fork, hooks.py's override_whitelisted_methods entry,
and meetings.py's import of this module instead of the original can all be
removed.
"""

import json
import re

import frappe
import frappe.utils

from frappe_appointment.api.personal_meet import create_dummy_appointment_group
from frappe_appointment.helpers.overrides import add_response_code
from frappe_appointment.helpers.utils import duration_to_string
from frappe_appointment.overrides.event_override import _create_event_for_appointment_group


@frappe.whitelist(allow_guest=True, methods=["POST"])
@add_response_code
def book_time_slot(
	duration_id: str,
	date: str,
	start_time: str,
	end_time: str,
	user_timezone_offset: str,
	user_name: str,
	user_email: str,
	other_participants: str = None,
	**args,
):
	duration = frappe.get_doc("Appointment Slot Duration", duration_id)

	user_availability = frappe.get_all(
		"User Appointment Availability", filters={"name": duration.get("parent")}, fields=["*"]
	)

	if not user_availability:
		return {"error": "No user found"}, 404

	user_availability = user_availability[0]

	appointment_group_obj = create_dummy_appointment_group(duration, user_availability)

	appointment_group = frappe.get_doc(appointment_group_obj)

	event_participants = [
		{
			"reference_doctype": "User Appointment Availability",
			"reference_docname": user_availability.get("name"),
			# Bugfix (see module docstring): the original used
			# user_availability.get("user") directly here - a User docname
			# (e.g. "Administrator"), not an email, which Google Calendar's
			# API rejects with "Invalid attendee email". Falls back to the
			# docname only if the User genuinely has no email set, so this
			# still can't crash - but prefers the real address.
			"email": frappe.get_value("User", user_availability.get("user"), "email")
			or user_availability.get("user"),
		},
		{
			"email": user_email,
		},
	]

	if other_participants:
		other_participants = other_participants.split(",")
		for participant in other_participants:
			if not re.match(r"[^@]+@[^@]+\.[^@]+", participant):
				continue
			event_participants.append(
				{
					"email": participant.strip(),
				}
			)

	custom_doctype_link_with_event = [
		{
			"reference_doctype": "User Appointment Availability",
			"reference_docname": user_availability.get("name"),
			"value": user_availability.get("user"),
		}
	]

	if not args.get("custom_doctype_link_with_event", None):
		args["custom_doctype_link_with_event"] = json.dumps(custom_doctype_link_with_event)
	else:
		original_link = json.loads(args["custom_doctype_link_with_event"])
		for link in original_link:
			# Bugfix (second one in this fork - also pre-existing upstream, not
			# introduced here): the original checked link["doctype"]/
			# link["name"], but every dict in this list - both the one built
			# above and any caller-supplied one (e.g. meetings.py's own
			# {"reference_doctype": ..., "reference_docname": ..., "value": ...})
			# - actually uses reference_doctype/reference_docname. The original
			# keys always raised KeyError the moment a caller supplied its own
			# custom_doctype_link_with_event, which is exactly what
			# crm.api.meetings.book_meeting does on every call.
			if link["reference_doctype"] == "User Appointment Availability" and link["reference_docname"] == user_availability.get("name"):
				break
		else:
			original_link.append(custom_doctype_link_with_event[0])
			args["custom_doctype_link_with_event"] = json.dumps(original_link)

	if not args.get("Subject", None):
		name = frappe.get_value("User", user_availability.get("user"), "full_name")

		duration_str = duration_to_string(duration.duration)

		args["subject"] = f"Meet: {user_name} <> {name} ({duration_str})"

	args["personal"] = True
	args["user_calendar"] = user_availability.name
	args["appointment_slot_duration"] = duration.name
	args["user_slug"] = user_availability.slug

	success_message = ""

	if args.get("event_token"):
		success_message = "Appointment has been rescheduled."

	response = _create_event_for_appointment_group(
		appointment_group,
		date,
		start_time,
		end_time,
		user_timezone_offset,
		json.dumps(event_participants),
		success_message=success_message,
		return_event_id=True,
		**args,
	)

	return response
