import base64
import json
import os
import re

import frappe
import requests
import werkzeug.utils
from frappe import _

TELNYX_API_BASE = "https://api.telnyx.com/v2"

# How long (seconds) an inbound ring-group leaves an agent's leg ringing
# before Telnyx auto-hangs it up as unanswered.
RING_TIMEOUT_SECS = 25

# Safety-net TTL (seconds) for the ring-group routing state kept in
# frappe.cache() - comfortably longer than RING_TIMEOUT_SECS so a slow
# last-agent timeout can't outlive its own bookkeeping.
RING_GROUP_CACHE_TTL = 120

# How long (seconds) to remember which CRM Call Log / agent a bridged
# inbound call's customer leg belongs to. The customer's own Telnyx leg is
# never tagged with our client_state (we don't originate it), so once the
# ring-group cache entry is cleared at bridge time there'd be no way to
# resolve its call log when that leg later hangs up - long enough to
# comfortably outlive any real call.
CUSTOMER_CALL_STATE_TTL = 4 * 60 * 60


def _api_key():
    key = frappe.conf.get("telnyx_api_key")
    if not key:
        frappe.throw("telnyx_api_key not set in site_config.json")
    return key


def _connection_id():
    cid = frappe.conf.get("telnyx_connection_id")
    if not cid:
        frappe.throw("telnyx_connection_id not set in site_config.json")
    return cid


def _caller_id():
    cid = frappe.conf.get("telnyx_caller_id")
    if not cid:
        frappe.throw("telnyx_caller_id not set in site_config.json")
    return cid


def _agent_caller_id(user):
    """Per-agent outbound caller ID: the agent's own telnyx_did if set,
    otherwise the site-wide fallback. Deliberately reuses telnyx_did rather
    than a new field - the same number then works in both directions, so a
    customer calling back reaches the same agent who called them (see
    _agents_for_inbound_number, which routes inbound calls the same way).
    """
    did = frappe.db.get_value("User", user, "telnyx_did")
    return did or _caller_id()


def _sip_domain():
    return frappe.conf.get("telnyx_sip_domain") or "sip.telnyx.com"


def _headers():
    return {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
    }


def _post(path, body):
    resp = requests.post(f"{TELNYX_API_BASE}{path}", headers=_headers(), json=body, timeout=20)
    try:
        data = resp.json()
    except ValueError:
        data = {"raw": resp.text}
    if resp.status_code >= 300:
        frappe.log_error("Telnyx API", f"[{resp.status_code}] {path}: {data}")
        frappe.throw(f"Telnyx API error: {data}")
    return data


def _encode_state(d):
    return base64.b64encode(json.dumps(d).encode()).decode()


def _decode_state(s):
    if not s:
        return {}
    try:
        return json.loads(base64.b64decode(s).decode())
    except Exception:
        return {}


def _agent_sip_username(user):
    username = frappe.db.get_value("User", user, "pbx_extension")
    if not username:
        frappe.throw(
            "No Telnyx SIP username set for your user. "
            "Add it in the pbx_extension field on your User record."
        )
    return username


def _ring_group_cache_key(customer_call_id):
    return f"telnyx_ring_group:{customer_call_id}"


def _customer_leg_state_cache_key(customer_call_id):
    return f"telnyx_customer_leg:{customer_call_id}"


def _normalize_phone(number):
    """Strip everything but digits so differently-formatted numbers compare
    equal (+357 9776 1711 / +35797761711 / 35797761711 / 00357-9776-1711 all
    normalize to the same digit string).
    """
    return re.sub(r"\D", "", number or "")


def _find_caller_reference(caller_number):
    """Best-effort reverse lookup: does this caller's number match an
    existing CRM Lead or Contact? Both sides are normalized before comparing
    since Telnyx's caller ID format rarely matches how the number happens to
    be stored.
    """
    normalized_caller = _normalize_phone(caller_number)
    if not normalized_caller:
        frappe.log_error(
            "Telnyx Caller Lookup",
            f"caller_number={caller_number!r} normalized to empty - nothing to search",
        )
        return None, None

    # Deliberately unfiltered (no or_filters "is set" trick) - fetch every
    # lead and compare in Python so there's no ambiguity about whether a
    # server-side filter is silently excluding rows.
    leads = frappe.get_all("CRM Lead", fields=["name", "mobile_no", "phone"])
    for lead in leads:
        if normalized_caller in (_normalize_phone(lead.mobile_no), _normalize_phone(lead.phone)):
            # TEMPORARY DEBUG LOGGING - remove once inbound caller-name resolution is confirmed working
            frappe.log_error(
                "Telnyx Caller Lookup",
                f"MATCH caller={caller_number!r} normalized={normalized_caller!r} -> "
                f"CRM Lead {lead.name} (mobile_no={lead.mobile_no!r}, phone={lead.phone!r})",
            )
            return "CRM Lead", lead.name

    contact_phones = frappe.get_all("Contact Phone", fields=["phone", "parent"])
    for row in contact_phones:
        if normalized_caller == _normalize_phone(row.phone):
            frappe.log_error(
                "Telnyx Caller Lookup",
                f"MATCH caller={caller_number!r} normalized={normalized_caller!r} -> Contact {row.parent}",
            )
            return "Contact", row.parent

    # TEMPORARY DEBUG LOGGING - remove once inbound caller-name resolution is confirmed working
    frappe.log_error(
        "Telnyx Caller Lookup",
        f"NO MATCH caller={caller_number!r} normalized={normalized_caller!r} - "
        f"checked {len(leads)} leads, {len(contact_phones)} contact phones. "
        f"Lead numbers on file: {[(l.name, l.mobile_no, l.phone) for l in leads][:20]}",
    )
    return None, None


@frappe.whitelist()
def create_click2call(to, reference_doctype=None, reference_name=None):
    if not to:
        frappe.throw("No destination number provided.")

    agent_user = frappe.session.user
    sip_username = _agent_sip_username(agent_user)
    caller_id = _agent_caller_id(agent_user)

    call_log = frappe.get_doc(
        {
            "doctype": "CRM Call Log",
            "from": caller_id,
            "to": to,
            "type": "Outgoing",
            "status": "Initiated",
            "telephony_medium": "Manual",
            "medium": "Telnyx",
            "start_time": frappe.utils.now_datetime(),
            "caller": agent_user,
        }
    )
    if reference_doctype and reference_name:
        call_log.reference_doctype = reference_doctype
        call_log.reference_docname = reference_name

    call_log.insert(ignore_permissions=True)

    client_state = _encode_state(
        {
            "leg": "A",
            "call_log": call_log.name,
            "destination": to,
            "agent_user": agent_user,
        }
    )

    data = _post(
        "/calls",
        {
            "connection_id": _connection_id(),
            "to": f"sip:{sip_username}@{_sip_domain()}",
            "from": caller_id,
            "client_state": client_state,
            "custom_headers": [{"name": "X-Call-Direction", "value": "outbound"}],
        },
    )

    call_control_id = data.get("data", {}).get("call_control_id")

    return {
        "status": "initiated",
        "call_log": call_log.name,
        "call_control_id": call_control_id,
        "destination": to,
        "lead_name": _display_name_for_reference(reference_doctype, reference_name),
        "reference_doctype": reference_doctype,
        "reference_docname": reference_name,
    }


@frappe.whitelist(allow_guest=True)
def handle_telnyx_webhook():
    try:
        body = frappe.request.get_data(as_text=True)
        payload_root = json.loads(body) if body else {}
    except Exception:
        frappe.log_error("Telnyx webhook: could not parse JSON body", "Telnyx Webhook")
        return {"success": False}

    event = payload_root.get("data", {})
    event_type = event.get("event_type")
    payload = event.get("payload", {})
    call_control_id = payload.get("call_control_id")
    state = _decode_state(payload.get("client_state"))
    leg = state.get("leg")
    call_log_name = state.get("call_log")

    if not event_type:
        return {"success": False, "msg": "No event_type"}

    # TEMPORARY DEBUG LOGGING - remove once flow is confirmed working
    frappe.log_error(
        "Telnyx Webhook Debug",
        f"event={event_type} leg={leg} call_log={call_log_name} "
        f"call_control_id={call_control_id} full_payload={payload}",
    )

    # The customer's own leg on an inbound ring group is never tagged with our
    # client_state (we don't originate it), so it's tracked by call_control_id
    # in frappe.cache() instead. Agent legs (leg == "ring_group") always carry
    # client_state and don't need this lookup.
    ring_group = None
    if not leg and call_control_id:
        ring_group = frappe.cache().get_value(_ring_group_cache_key(call_control_id))

    # The customer leg of a bridged inbound call still has no client_state of
    # its own at this point (see _customer_leg_state_cache_key), so once the
    # ring-group cache entry above is gone (already bridged), call_log_name
    # would otherwise stay unresolved for the rest of that call - including
    # its final call.hangup, which is what actually finalizes the CRM Call
    # Log (status/duration). Fall back to the longer-lived mapping written in
    # _ring_group_agent_answered.
    if not leg and call_control_id and not call_log_name:
        customer_state = frappe.cache().get_value(_customer_leg_state_cache_key(call_control_id))
        if customer_state:
            call_log_name = customer_state.get("call_log")
            state = {**state, **customer_state}

    try:
        if event_type == "call.initiated" and not leg and not ring_group and payload.get("direction") == "incoming":
            _start_ring_group(call_control_id, payload)

        elif event_type == "call.answered" and leg == "A":
            _agent_answered(call_control_id, state, call_log_name)

        elif event_type == "call.answered" and leg == "B":
            _lead_answered(call_control_id, state, call_log_name)

        elif event_type == "call.answered" and leg == "ring_group":
            _ring_group_agent_answered(call_control_id, state, call_log_name)

        elif event_type == "call.answered" and ring_group:
            _ring_group_bridge(call_control_id, ring_group)

        elif event_type == "call.hangup" and leg == "ring_group":
            _ring_group_agent_hangup(call_control_id, state, call_log_name)

        elif event_type == "call.hangup" and ring_group:
            _ring_group_customer_hangup(call_control_id, ring_group)

        elif event_type == "call.hangup" and leg == "B":
            _lead_hangup(call_control_id, state, call_log_name)

        elif event_type == "call.hangup":
            _call_ended(call_control_id, leg, state, call_log_name)

        elif event_type == "call.recording.saved" and leg == "recording":
            _save_recording(call_log_name, payload)
    except Exception:
        frappe.log_error("Telnyx Webhook CRASH", frappe.get_traceback())

    # call.answered/leg B is published explicitly inside _lead_answered
    # itself now, not through this generic path - see the comment there for
    # why. Skip it here so the frontend doesn't get the same "lead answered"
    # signal twice (which would reset its call-duration timer a second time).
    if call_log_name and state.get("agent_user") and not (event_type == "call.answered" and leg == "B"):
        to_number, call_status, ref_doctype, ref_name = frappe.db.get_value(
            "CRM Call Log", call_log_name, ["to", "status", "reference_doctype", "reference_docname"]
        )
        lead_name = _display_name_for_reference(ref_doctype, ref_name)
        # TEMPORARY DEBUG LOGGING - remove once inbound caller-name resolution is confirmed working.
        # This block fires for BOTH the ring-time event (call.initiated on a
        # ring_group agent leg, published to that one agent as soon as their
        # leg starts ringing) and the later call.answered/call.hangup events -
        # event_type below tells you which.
        frappe.log_error(
            "Telnyx Realtime Publish",
            f"event={event_type} leg={leg} call_log={call_log_name} agent_user={state.get('agent_user')} "
            f"to={to_number} status={call_status} reference={ref_doctype}/{ref_name} lead_name={lead_name!r}",
        )
        frappe.publish_realtime(
            "telnyx_call_event",
            {
                "event": event_type,
                "leg": leg,
                "call_log": call_log_name,
                "call_control_id": call_control_id,       
                "to": to_number,
                "status": call_status,
                "lead_name": lead_name,
                "reference_doctype": ref_doctype,
                "reference_docname": ref_name,
            },
            user=state.get("agent_user"),
        )

    return {"success": True}


def _leg_b_pending_cache_key(leg_b_id):
    return f"telnyx_leg_b_pending:{leg_b_id}"


def _agent_answered(leg_a_id, state, call_log_name):
    destination = state.get("destination")
    agent_user = state.get("agent_user")

    if call_log_name:
        frappe.db.set_value("CRM Call Log", call_log_name, "status", "In Progress")
        frappe.db.commit()

    leg_b_state = _encode_state(
        {
            "leg": "B",
            "call_log": call_log_name,
            "leg_a_id": leg_a_id,
            "agent_user": agent_user,
        }
    )

    data = _post(
        "/calls",
        {
            "connection_id": _connection_id(),
            "to": destination,
            "from": _agent_caller_id(agent_user),
            "client_state": leg_b_state,
            "timeout_secs": RING_TIMEOUT_SECS,
        },
    )

    # Marks leg B as "ringing, not yet answered" - deleted the moment it's
    # answered (_lead_answered). Still present at leg B's own hangup means
    # the lead never picked up, distinct from a normal call that connected
    # and later ended (see _lead_hangup).
    leg_b_id = data.get("data", {}).get("call_control_id")
    if leg_b_id:
        frappe.cache().set_value(_leg_b_pending_cache_key(leg_b_id), 1, expires_in_sec=RING_GROUP_CACHE_TTL)


def _lead_answered(leg_b_id, state, call_log_name):
    leg_a_id = state.get("leg_a_id")
    if not leg_a_id:
        frappe.log_error(f"Telnyx: leg B answered but no leg_a_id in state: {state}", "Telnyx Webhook")
        return

    frappe.cache().delete_value(_leg_b_pending_cache_key(leg_b_id))

    _post(f"/calls/{leg_a_id}/actions/bridge", {"call_control_id": leg_b_id})
    _start_recording(leg_a_id, call_log_name, state.get("agent_user"))

    if call_log_name:
        frappe.db.set_value("CRM Call Log", call_log_name, "status", "In Progress")
        frappe.db.commit()

    # Publish "the lead answered" directly here, with everything already in
    # hand, instead of relying solely on the generic catch-all at the bottom
    # of handle_telnyx_webhook. A live call (call_log 79054ad6e8d7) showed
    # that generic path can silently fail to publish this one event even
    # though _lead_answered ran successfully end to end (bridge + recording
    # both happened, the call log reached Completed) - so whatever caused
    # that, this signal no longer depends on it. This is the ONLY event
    # TelnyxCallUI.vue listens for to stop the outbound ringtone and flip to
    # "On Call" - it needs to be unconditionally reliable.
    agent_user = state.get("agent_user")
    if call_log_name and agent_user:
        to_number, ref_doctype, ref_name = frappe.db.get_value(
            "CRM Call Log", call_log_name, ["to", "reference_doctype", "reference_docname"]
        )
        lead_name = _display_name_for_reference(ref_doctype, ref_name)
        # TEMPORARY DEBUG LOGGING - remove once this is confirmed reliable
        frappe.log_error(
            "Telnyx Realtime Publish",
            f"event=call.answered leg=B (explicit, from _lead_answered) call_log={call_log_name} "
            f"agent_user={agent_user} to={to_number} reference={ref_doctype}/{ref_name} lead_name={lead_name!r}",
        )
        frappe.publish_realtime(
            "telnyx_call_event",
            {
                "event": "call.answered",
                "leg": "B",
                "call_log": call_log_name,
                "call_control_id": leg_b_id,
                "to": to_number,
                "status": "In Progress",
                "lead_name": lead_name,
                "reference_doctype": ref_doctype,
                "reference_docname": ref_name,
            },
            user=agent_user,
        )


def _lead_hangup(leg_b_id, state, call_log_name):
    """Leg B (the lead's phone) hung up. If it was never answered (still
    marked pending), this is a genuine "No Answer" - timeout, busy, or
    declined - not a normal call end, so it's marked distinctly and the
    agent's now-orphaned leg A (nothing left to bridge it to) is hung up too.
    """
    cache_key = _leg_b_pending_cache_key(leg_b_id)
    was_pending = frappe.cache().get_value(cache_key)
    frappe.cache().delete_value(cache_key)

    if not was_pending:
        _call_ended(leg_b_id, "B", state, call_log_name)
        return

    leg_a_id = state.get("leg_a_id")
    if leg_a_id:
        _post(f"/calls/{leg_a_id}/actions/hangup", {})

    if call_log_name:
        frappe.db.set_value("CRM Call Log", call_log_name, "status", "No Answer")
        frappe.db.set_value("CRM Call Log", call_log_name, "end_time", frappe.utils.now_datetime())
        frappe.db.commit()


def _call_ended(call_control_id, leg, state, call_log_name):
    if call_log_name:
        # Don't downgrade a more specific terminal status (e.g. the "No
        # Answer" _lead_hangup just set) back to a generic "Completed" -
        # this fires again when the leg-A hangup that _lead_hangup triggers
        # comes back through as its own webhook event.
        current_status, start_time = frappe.db.get_value(
            "CRM Call Log", call_log_name, ["status", "start_time"]
        )
        if current_status == "No Answer":
            return

        end_time = frappe.utils.now_datetime()
        frappe.db.set_value("CRM Call Log", call_log_name, "status", "Completed")
        frappe.db.set_value("CRM Call Log", call_log_name, "end_time", end_time)
        # Nothing computes this from start_time/end_time on its own - the
        # doctype controller has no such hook - and CallLogDetailModal.vue
        # reads it directly, so without this every call would show "0s".
        if start_time:
            frappe.db.set_value(
                "CRM Call Log", call_log_name, "duration", (end_time - start_time).total_seconds()
            )
        frappe.db.commit()

    # No-op if call_control_id isn't a customer leg (never set under this
    # key) - always safe to clear once a call is done with it.
    frappe.cache().delete_value(_customer_leg_state_cache_key(call_control_id))


def _start_recording(call_control_id, call_log_name, agent_user=None):
    """Start recording a just-bridged call. Best-effort: a failure here
    shouldn't take down the call itself, so it's caught and logged locally
    rather than left to the webhook's outer try/except.

    Carries agent_user forward into the recording-tagged client_state -
    without it, every later webhook for this leg (crucially, its own
    eventual hangup) would fail the "state.get('agent_user')" check in the
    realtime-publish block at the bottom of handle_telnyx_webhook, and the
    frontend would never hear about anything that happens after this point.
    """
    if not call_log_name:
        return
    client_state = _encode_state({"leg": "recording", "call_log": call_log_name, "agent_user": agent_user})
    try:
        _post(
            f"/calls/{call_control_id}/actions/record_start",
            {
                "format": "mp3",
                "channels": "dual",
                "client_state": client_state,
            },
        )
    except Exception:
        frappe.log_error(
            "Telnyx Webhook", f"Failed to start recording for call_log {call_log_name}: {frappe.get_traceback()}"
        )


def _save_recording(call_log_name, payload):
    """call.recording.saved: download the recording immediately and attach a
    permanent copy to its CRM Call Log, following the same recording_url
    field CRM's Twilio/Exotel integrations use - the Activity tab's player
    and CallLogDetailModal.vue are provider-agnostic off that field alone.

    Per Telnyx's own schema, recording_urls is only valid for 10 minutes
    after saving, and public_recording_urls (no expiry) requires Telnyx
    support to activate per-account - not something this integration can
    assume is on. Storing either URL directly means playback silently stops
    working once it expires: the recording still shows as "attached" (the
    field has a value), but the player can no longer load it. Fetching the
    file now, while the link is still guaranteed fresh, and re-hosting it as
    our own private Frappe File sidesteps the expiry entirely.
    """
    if not call_log_name:
        frappe.log_error("Telnyx Webhook", f"call.recording.saved with no call_log in state: {payload}")
        return

    # Prefer the no-expiry public URL when the account has it activated;
    # otherwise the 10-minute one, which is why this must be fetched now.
    urls = payload.get("public_recording_urls") or payload.get("recording_urls") or {}
    if urls.get("mp3"):
        source_url, file_ext = urls.get("mp3"), "mp3"
    elif urls.get("wav"):
        source_url, file_ext = urls.get("wav"), "wav"
    else:
        source_url, file_ext = None, None

    # TEMPORARY DEBUG LOGGING - remove once recording capture is confirmed working
    frappe.log_error(
        "Telnyx Recording Saved",
        f"call_log={call_log_name} source_url={source_url!r} file_ext={file_ext} raw_payload={payload}",
    )

    if not source_url:
        return

    recording_url = source_url
    try:
        resp = requests.get(source_url, timeout=30)
        resp.raise_for_status()
    except Exception:
        # Fall back to Telnyx's own URL - works until it expires, better
        # than nothing if the download itself is what failed.
        frappe.log_error(
            "Telnyx Webhook",
            f"Failed to download recording for call_log {call_log_name} from {source_url}: "
            f"{frappe.get_traceback()}",
        )
    else:
        file_doc = frappe.get_doc(
            {
                "doctype": "File",
                "file_name": f"{call_log_name}-recording.{file_ext}",
                "attached_to_doctype": "CRM Call Log",
                "attached_to_name": call_log_name,
                "attached_to_field": "recording_url",
                "content": resp.content,
                # Private, not public: with attached_to_doctype/name set,
                # Frappe's own /private/files/ route (frappe.utils.response.
                # download_private_file) rejects Guest outright and, for
                # everyone else, checks permission via File.has_permission
                # -> CRM Call Log's own has_permission("read") - the same
                # rule the rest of the CRM already relies on for this
                # doctype. Serves the bytes straight from disk either way
                # (werkzeug send_file, conditional=True gives Range support
                # for free) - no re-fetch, so no self-fetch/NAT risk either.
                "is_private": 1,
            }
        )
        file_doc.insert(ignore_permissions=True)
        # Absolute URL, not the bare /private/files/... path - the
        # crm_call_log.py override below matches on the site's own host to
        # decide whether to skip the get_recording_url proxy.
        recording_url = frappe.utils.get_url(file_doc.file_url)
        # TEMPORARY DEBUG LOGGING - remove once recording capture is confirmed working
        frappe.log_error(
            "Telnyx Recording Saved",
            f"call_log={call_log_name} re-hosted as {file_doc.file_url} -> {recording_url}",
        )

    frappe.db.set_value("CRM Call Log", call_log_name, "recording_url", recording_url)
    frappe.db.commit()

    # TEMPORARY DEBUG LOGGING - remove once recording capture is confirmed working.
    # This is the URL actually stored, regardless of which branch above ran -
    # open it directly in a browser (logged out) to check it's independently
    # reachable, separate from whether the CRM's own player can load it.
    frappe.log_error(
        "Telnyx Recording Saved",
        f"call_log={call_log_name} FINAL recording_url={recording_url!r}",
    )


@frappe.whitelist()
def get_recording(call_log_name):
    """Stream a locally re-hosted Telnyx recording straight from disk,
    gated on the requesting user's own read permission for the CRM Call Log
    it's attached to.

    A dedicated endpoint rather than pointing recording_url_path at
    Frappe's own /private/files/ route: that route works the same way
    security-wise (it delegates to the identical File.has_permission ->
    CRM Call Log.has_permission("read") chain used below) but it's
    unmodified core code with nowhere to add TEMPORARY DEBUG LOGGING when
    something needs diagnosing on a live site - which is exactly why this
    exists instead.
    """
    user = frappe.session.user

    if not call_log_name or not frappe.db.exists("CRM Call Log", call_log_name):
        # TEMPORARY DEBUG LOGGING - remove once recording playback is confirmed working
        frappe.log_error(
            "Telnyx Recording Access",
            f"user={user} call_log_name={call_log_name!r} - call log not found",
        )
        frappe.throw(_("Call log not found"), frappe.DoesNotExistError)

    log = frappe.get_doc("CRM Call Log", call_log_name)

    try:
        log.check_permission("read")
    except frappe.PermissionError:
        # TEMPORARY DEBUG LOGGING - remove once recording playback is confirmed working
        frappe.log_error(
            "Telnyx Recording Access",
            f"user={user} call_log_name={call_log_name} status=DENIED - check_permission('read') raised "
            f"(reference={log.reference_doctype}/{log.reference_docname})",
        )
        raise

    # TEMPORARY DEBUG LOGGING - remove once recording playback is confirmed working
    frappe.log_error(
        "Telnyx Recording Access",
        f"user={user} call_log_name={call_log_name} status=GRANTED recording_url={log.recording_url!r}",
    )

    if not log.recording_url:
        frappe.throw(_("Recording not found"), frappe.DoesNotExistError)

    file_name = frappe.db.get_value(
        "File",
        {
            "attached_to_doctype": "CRM Call Log",
            "attached_to_name": call_log_name,
            "attached_to_field": "recording_url",
        },
        "name",
    )
    if not file_name:
        # TEMPORARY DEBUG LOGGING - remove once recording playback is confirmed working
        frappe.log_error(
            "Telnyx Recording Access",
            f"call_log_name={call_log_name} - recording_url is set but no matching File record found",
        )
        frappe.throw(_("Recording file not found"), frappe.DoesNotExistError)

    file_doc = frappe.get_doc("File", file_name)
    file_path = file_doc.get_full_path()

    if not os.path.exists(file_path):
        # TEMPORARY DEBUG LOGGING - remove once recording playback is confirmed working
        frappe.log_error(
            "Telnyx Recording Access",
            f"call_log_name={call_log_name} file={file_name} - resolved path missing on disk: {file_path}",
        )
        frappe.throw(_("Recording file missing"), frappe.DoesNotExistError)

    return werkzeug.utils.send_file(
        file_path,
        environ=frappe.local.request.environ,
        conditional=True,
        mimetype="audio/mpeg",
        download_name=file_doc.file_name,
    )


def _agents_for_inbound_number(our_number):
    """Which agent(s) should ring for a call to this DID?

    If a User has telnyx_did set to this exact number, only they ring - the
    ring-group is skipped entirely (one leg, not many). Otherwise every agent
    with a pbx_extension set rings, as before. Both sides are normalized
    before comparing for the same reason phone numbers are normalized
    elsewhere in this file: formatting rarely matches exactly.
    """
    all_agents = frappe.get_all(
        "User",
        filters={"pbx_extension": ["is", "set"], "enabled": 1},
        fields=["name", "pbx_extension", "telnyx_did"],
    )

    normalized_number = _normalize_phone(our_number)
    if normalized_number:
        for agent in all_agents:
            if agent.telnyx_did and _normalize_phone(agent.telnyx_did) == normalized_number:
                # TEMPORARY DEBUG LOGGING - remove once DID routing is confirmed working
                frappe.log_error(
                    "Telnyx DID Routing",
                    f"to={our_number!r} normalized={normalized_number!r} -> assigned agent {agent.name}",
                )
                return [agent]

    # TEMPORARY DEBUG LOGGING - remove once DID routing is confirmed working
    frappe.log_error(
        "Telnyx DID Routing",
        f"to={our_number!r} normalized={normalized_number!r} - no DID assignment, "
        f"ringing all {len(all_agents)} agent(s) with a pbx_extension",
    )
    return all_agents


def validate_unique_telnyx_did(doc, method=None):
    """Block the same telnyx_did being assigned to two enabled users -
    _agents_for_inbound_number assumes at most one enabled agent owns a given
    DID, so a duplicate would make inbound routing for that number ambiguous.
    Same digits-only comparison as _agents_for_inbound_number, since
    formatting rarely matches exactly.
    """
    if not doc.telnyx_did or not doc.enabled:
        return

    normalized = _normalize_phone(doc.telnyx_did)
    if not normalized:
        return

    other_agents = frappe.get_all(
        "User",
        filters={"telnyx_did": ["is", "set"], "enabled": 1, "name": ["!=", doc.name]},
        fields=["name", "telnyx_did"],
    )
    for other in other_agents:
        if _normalize_phone(other.telnyx_did) == normalized:
            frappe.throw(
                _("Telnyx number {0} is already assigned to another agent ({1}).").format(
                    doc.telnyx_did, other.name
                )
            )


def _start_ring_group(call_control_id, payload):
    """A brand-new inbound call landed on our number - ring the assigned agent
    if this DID has one (see _agents_for_inbound_number), otherwise every
    agent with a pbx_extension at once. Whoever answers first gets bridged in
    _ring_group_agent_answered / _ring_group_bridge; the rest get cancelled.
    """
    customer_number = payload.get("from")
    our_number = payload.get("to")
    reference_doctype, reference_name = _find_caller_reference(customer_number)

    call_log = frappe.get_doc(
        {
            "doctype": "CRM Call Log",
            "from": customer_number,
            "to": our_number,
            "type": "Incoming",
            "status": "Initiated",
            "telephony_medium": "Manual",
            "medium": "Telnyx",
            "start_time": frappe.utils.now_datetime(),
        }
    )
    if reference_doctype and reference_name:
        call_log.reference_doctype = reference_doctype
        call_log.reference_docname = reference_name

    call_log.insert(ignore_permissions=True)
    # Commit before dialing anyone: dialing is an external HTTP call to Telnyx,
    # which can trigger a webhook back to a *different* worker almost
    # immediately (the agent leg's own call.initiated). Without this, that
    # webhook's read of reference_doctype/reference_docname can race ahead of
    # this transaction's commit and see nothing - the call log looks
    # unlinked at ring-time even though it's correctly linked moments later.
    frappe.db.commit()

    agents = _agents_for_inbound_number(our_number)

    agent_legs = {}
    for agent in agents:
        leg_state = _encode_state(
            {
                "leg": "ring_group",
                "call_log": call_log.name,
                "customer_call_id": call_control_id,
                "agent_user": agent.name,
            }
        )
        try:
            data = _post(
                "/calls",
                {
                    "connection_id": _connection_id(),
                    "to": f"sip:{agent.pbx_extension}@{_sip_domain()}",
                    "from": customer_number,
                    "timeout_secs": RING_TIMEOUT_SECS,
                    "client_state": leg_state,
                    "custom_headers": [{"name": "X-Call-Direction", "value": "inbound"}],
                },
            )
        except Exception:
            frappe.log_error("Telnyx Webhook", f"Failed to ring agent {agent.name}: {frappe.get_traceback()}")
            continue

        agent_leg_id = data.get("data", {}).get("call_control_id")
        if agent_leg_id:
            agent_legs[agent_leg_id] = agent.name

    if not agent_legs:
        frappe.log_error("Telnyx Webhook", f"Inbound call {call_control_id}: no agent legs could be started.")
        _post(f"/calls/{call_control_id}/actions/hangup", {})
        frappe.db.set_value("CRM Call Log", call_log.name, "status", "No Answer")
        frappe.db.set_value("CRM Call Log", call_log.name, "end_time", frappe.utils.now_datetime())
        frappe.db.commit()
        return

    frappe.cache().set_value(
        _ring_group_cache_key(call_control_id),
        {
            "call_log": call_log.name,
            "agent_legs": agent_legs,
            "winner": None,
        },
        expires_in_sec=RING_GROUP_CACHE_TTL,
    )


def _ring_group_agent_answered(agent_leg_id, state, call_log_name):
    """One agent's leg was answered. If they're first, claim the ring group,
    cancel everyone else, and answer the customer's leg (bridged once its own
    call.answered webhook lands, in _ring_group_bridge). If someone already
    won, this agent was too late - hang their leg back up.
    """
    customer_call_id = state.get("customer_call_id")
    agent_user = state.get("agent_user")
    cache_key = _ring_group_cache_key(customer_call_id)
    ring_group = frappe.cache().get_value(cache_key)

    # TEMPORARY DEBUG LOGGING - remove once the inbound answered/No-Answer flow is confirmed working
    frappe.log_error(
        "Telnyx Ring Group Answered",
        f"agent_leg_id={agent_leg_id} agent_user={agent_user} customer_call_id={customer_call_id} "
        f"call_log={call_log_name} cache_key={cache_key} ring_group_found={bool(ring_group)} "
        f"existing_winner={ring_group.get('winner') if ring_group else None}",
    )

    if not ring_group or ring_group.get("winner"):
        frappe.log_error(
            "Telnyx Ring Group Answered",
            f"agent_leg_id={agent_leg_id} too late or ring group already gone - hanging this leg back up "
            f"(ring_group_found={bool(ring_group)}, winner={ring_group.get('winner') if ring_group else None})",
        )
        _post(f"/calls/{agent_leg_id}/actions/hangup", {})
        return

    ring_group["winner"] = agent_leg_id
    # Carried through to _ring_group_bridge, which otherwise has no way to
    # know which agent answered - it only gets called with the cache dict.
    ring_group["winner_agent_user"] = agent_user
    frappe.cache().set_value(cache_key, ring_group, expires_in_sec=RING_GROUP_CACHE_TTL)

    for leg_id in ring_group["agent_legs"]:
        if leg_id != agent_leg_id:
            _post(f"/calls/{leg_id}/actions/hangup", {})

    if call_log_name:
        # CRM Call Log models "caller" (Outgoing) and "receiver" (Incoming) as
        # distinct fields - "receiver" is who answered an inbound call, and
        # it's what CallLogDetailModal.vue reads for the agent's avatar/name
        # on this call's Incoming side. "caller" would just sit unused.
        frappe.db.set_value("CRM Call Log", call_log_name, "receiver", agent_user)
        frappe.db.commit()

        # See _customer_leg_state_cache_key: this is a fallback record of
        # which call log/agent the customer's leg belongs to, independent of
        # the client_state tagged on the answer action below. Without it, a
        # call the customer hangs up first (the common case) could go
        # unfinalized once the ring-group cache clears at bridge time, if
        # that client_state is ever lost or not echoed back as expected.
        frappe.cache().set_value(
            _customer_leg_state_cache_key(customer_call_id),
            {"call_log": call_log_name, "agent_user": agent_user},
            expires_in_sec=CUSTOMER_CALL_STATE_TTL,
        )

    # Tag the customer leg's own client_state too (previously left unset) so
    # its call.answered confirmation - and everything after it until
    # _start_recording re-tags it - still passes the realtime-publish
    # block's agent_user check instead of silently going unpublished. This
    # is the primary path; the cache entry above is the fallback.
    answer_state = _encode_state({"call_log": call_log_name, "agent_user": agent_user})
    try:
        _post(f"/calls/{customer_call_id}/actions/answer", {"client_state": answer_state})
    except Exception:
        frappe.log_error(
            "Telnyx Ring Group Answered",
            f"Failed to answer customer leg {customer_call_id} for call_log {call_log_name}: "
            f"{frappe.get_traceback()}",
        )
        raise


def _ring_group_bridge(customer_call_id, ring_group):
    """The customer's leg is now answered - bridge it to the winning agent."""
    winner_leg_id = ring_group.get("winner")
    call_log_name = ring_group.get("call_log")
    agent_user = ring_group.get("winner_agent_user")

    # TEMPORARY DEBUG LOGGING - remove once the inbound answered/No-Answer flow is confirmed working
    frappe.log_error(
        "Telnyx Ring Group Bridge",
        f"customer_call_id={customer_call_id} winner_leg_id={winner_leg_id} "
        f"call_log={call_log_name} agent_user={agent_user}",
    )

    if not winner_leg_id:
        frappe.log_error("Telnyx Webhook", f"Ring group {customer_call_id} answered with no winner on record.")
        return

    try:
        _post(f"/calls/{customer_call_id}/actions/bridge", {"call_control_id": winner_leg_id})
    except Exception:
        # Bridge itself failed (e.g. the winning leg was already gone) - the
        # call never actually connected despite being "answered", so leaving
        # status at "Initiated" would be misleading and skipping straight to
        # recording/"In Progress" below would be flat wrong. Mark it plainly.
        frappe.log_error(
            "Telnyx Ring Group Bridge",
            f"BRIDGE FAILED customer_call_id={customer_call_id} winner_leg_id={winner_leg_id} "
            f"call_log={call_log_name}: {frappe.get_traceback()}",
        )
        if call_log_name:
            frappe.db.set_value("CRM Call Log", call_log_name, "status", "Failed")
            frappe.db.set_value("CRM Call Log", call_log_name, "end_time", frappe.utils.now_datetime())
            frappe.db.commit()
        frappe.cache().delete_value(_ring_group_cache_key(customer_call_id))
        return

    _start_recording(customer_call_id, call_log_name, agent_user)

    if call_log_name:
        frappe.db.set_value("CRM Call Log", call_log_name, "status", "In Progress")
        frappe.db.commit()

    # TEMPORARY DEBUG LOGGING - remove once the inbound answered/No-Answer flow is confirmed working
    frappe.log_error(
        "Telnyx Ring Group Bridge",
        f"bridge succeeded customer_call_id={customer_call_id} winner_leg_id={winner_leg_id} "
        f"call_log={call_log_name} - status set to In Progress, recording started",
    )

    frappe.cache().delete_value(_ring_group_cache_key(customer_call_id))


def _ring_group_agent_hangup(agent_leg_id, state, call_log_name):
    """An agent leg tagged "ring_group" hung up. Two cases:
    - The ring group is still open (no winner yet): this agent declined or
      timed out. Drop them from the pool; if nobody's left, nobody answered.
    - The ring group is already gone (winner picked, bridged, cache cleared):
      this is the winning agent's own leg ending the now-real call.
    """
    customer_call_id = state.get("customer_call_id")
    cache_key = _ring_group_cache_key(customer_call_id)
    ring_group = frappe.cache().get_value(cache_key)

    # TEMPORARY DEBUG LOGGING - remove once the inbound answered/No-Answer flow is confirmed working
    frappe.log_error(
        "Telnyx Ring Group Agent Hangup",
        f"agent_leg_id={agent_leg_id} customer_call_id={customer_call_id} call_log={call_log_name} "
        f"ring_group_found={bool(ring_group)} winner={ring_group.get('winner') if ring_group else None} "
        f"agent_legs_remaining={list(ring_group.get('agent_legs', {}).keys()) if ring_group else None}",
    )

    if not ring_group:
        # Cache is gone - normally means it already bridged successfully and
        # this is the real, post-conversation hangup. Hand off to the
        # ordinary end-of-call handling rather than treating it as No Answer.
        _call_ended(agent_leg_id, state.get("leg"), state, call_log_name)
        return

    if ring_group.get("winner"):
        # One of the legs we just cancelled hanging up - already handled.
        return

    agent_legs = ring_group.get("agent_legs", {})
    agent_legs.pop(agent_leg_id, None)
    ring_group["agent_legs"] = agent_legs

    if agent_legs:
        frappe.cache().set_value(cache_key, ring_group, expires_in_sec=RING_GROUP_CACHE_TTL)
        return

    # Every agent leg declined or timed out - nobody answered.
    frappe.log_error(
        "Telnyx Ring Group Agent Hangup",
        f"customer_call_id={customer_call_id} call_log={call_log_name} - "
        f"every agent leg is gone with no winner - marking No Answer",
    )
    frappe.cache().delete_value(cache_key)
    _post(f"/calls/{customer_call_id}/actions/hangup", {})
    if call_log_name:
        frappe.db.set_value("CRM Call Log", call_log_name, "status", "No Answer")
        frappe.db.set_value("CRM Call Log", call_log_name, "end_time", frappe.utils.now_datetime())
        frappe.db.commit()


def _ring_group_customer_hangup(customer_call_id, ring_group):
    """The customer abandoned the call before any agent answered."""
    call_log_name = ring_group.get("call_log")

    # TEMPORARY DEBUG LOGGING - remove once the inbound answered/No-Answer flow is confirmed working.
    # If "winner" shows up set here, that's a real bug: it means a call
    # already claimed by an agent is being treated as abandoned-before-answer.
    frappe.log_error(
        "Telnyx Ring Group Customer Hangup",
        f"customer_call_id={customer_call_id} call_log={call_log_name} "
        f"winner={ring_group.get('winner')} agent_legs={list(ring_group.get('agent_legs', {}).keys())}",
    )

    for leg_id in ring_group.get("agent_legs", {}):
        _post(f"/calls/{leg_id}/actions/hangup", {})

    frappe.cache().delete_value(_ring_group_cache_key(customer_call_id))

    if call_log_name:
        frappe.db.set_value("CRM Call Log", call_log_name, "status", "No Answer")
        frappe.db.set_value("CRM Call Log", call_log_name, "end_time", frappe.utils.now_datetime())
        frappe.db.commit()


@frappe.whitelist()
def get_webrtc_credentials():
    """Return this agent's Telnyx WebRTC login credentials.
    Only callable by a logged-in session - never embedded in the JS bundle.
    """
    username = _agent_sip_username(frappe.session.user)
    password = frappe.conf.get("telnyx_sip_password")
    if not password:
        frappe.throw("telnyx_sip_password not set in site_config.json")
    return {"username": username, "password": password}


def _display_name_for_reference(reference_doctype, reference_name):
    """Look up a Lead/Deal/Contact's display name given its doctype + name."""
    if not reference_doctype or not reference_name:
        return None
    try:
        title_field = frappe.get_meta(reference_doctype).get_title_field()
        if title_field and title_field != "name":
            return frappe.db.get_value(reference_doctype, reference_name, title_field)
    except Exception:
        pass
    return None
