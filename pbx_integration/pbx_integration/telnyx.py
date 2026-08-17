import base64
import json
import re

import frappe
import requests

TELNYX_API_BASE = "https://api.telnyx.com/v2"

# How long (seconds) an inbound ring-group leaves an agent's leg ringing
# before Telnyx auto-hangs it up as unanswered.
RING_TIMEOUT_SECS = 25

# Safety-net TTL (seconds) for the ring-group routing state kept in
# frappe.cache() - comfortably longer than RING_TIMEOUT_SECS so a slow
# last-agent timeout can't outlive its own bookkeeping.
RING_GROUP_CACHE_TTL = 120


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

    call_log = frappe.get_doc(
        {
            "doctype": "CRM Call Log",
            "from": sip_username,
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
            "from": _caller_id(),
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

        elif event_type == "call.hangup":
            _call_ended(call_control_id, leg, state, call_log_name)
    except Exception:
        frappe.log_error("Telnyx Webhook CRASH", frappe.get_traceback())

    if call_log_name and state.get("agent_user"):
        to_number, ref_doctype, ref_name = frappe.db.get_value(
            "CRM Call Log", call_log_name, ["to", "reference_doctype", "reference_docname"]
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
            f"to={to_number} reference={ref_doctype}/{ref_name} lead_name={lead_name!r}",
        )
        frappe.publish_realtime(
            "telnyx_call_event",
            {
                "event": event_type,
                "leg": leg,
                "call_log": call_log_name,
                "call_control_id": call_control_id,
                "to": to_number,
                "lead_name": lead_name,
            },
            user=state.get("agent_user"),
        )

    return {"success": True}


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

    _post(
        "/calls",
        {
            "connection_id": _connection_id(),
            "to": destination,
            "from": _caller_id(),
            "client_state": leg_b_state,
        },
    )


def _lead_answered(leg_b_id, state, call_log_name):
    leg_a_id = state.get("leg_a_id")
    if not leg_a_id:
        frappe.log_error(f"Telnyx: leg B answered but no leg_a_id in state: {state}", "Telnyx Webhook")
        return

    _post(f"/calls/{leg_a_id}/actions/bridge", {"call_control_id": leg_b_id})

    if call_log_name:
        frappe.db.set_value("CRM Call Log", call_log_name, "status", "In Progress")
        frappe.db.commit()


def _call_ended(call_control_id, leg, state, call_log_name):
    if call_log_name:
        frappe.db.set_value("CRM Call Log", call_log_name, "status", "Completed")
        frappe.db.set_value("CRM Call Log", call_log_name, "end_time", frappe.utils.now_datetime())
        frappe.db.commit()


def _start_ring_group(call_control_id, payload):
    """A brand-new inbound call landed on our number - ring every agent with a
    pbx_extension at once. Whoever answers first gets bridged in
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

    agents = frappe.get_all(
        "User",
        filters={"pbx_extension": ["is", "set"], "enabled": 1},
        fields=["name", "pbx_extension"],
    )

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

    if not ring_group or ring_group.get("winner"):
        _post(f"/calls/{agent_leg_id}/actions/hangup", {})
        return

    ring_group["winner"] = agent_leg_id
    frappe.cache().set_value(cache_key, ring_group, expires_in_sec=RING_GROUP_CACHE_TTL)

    for leg_id in ring_group["agent_legs"]:
        if leg_id != agent_leg_id:
            _post(f"/calls/{leg_id}/actions/hangup", {})

    if call_log_name:
        frappe.db.set_value("CRM Call Log", call_log_name, "caller", agent_user)
        frappe.db.commit()

    _post(f"/calls/{customer_call_id}/actions/answer", {})


def _ring_group_bridge(customer_call_id, ring_group):
    """The customer's leg is now answered - bridge it to the winning agent."""
    winner_leg_id = ring_group.get("winner")
    call_log_name = ring_group.get("call_log")

    if not winner_leg_id:
        frappe.log_error("Telnyx Webhook", f"Ring group {customer_call_id} answered with no winner on record.")
        return

    _post(f"/calls/{customer_call_id}/actions/bridge", {"call_control_id": winner_leg_id})

    if call_log_name:
        frappe.db.set_value("CRM Call Log", call_log_name, "status", "In Progress")
        frappe.db.commit()

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

    if not ring_group:
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
    frappe.cache().delete_value(cache_key)
    _post(f"/calls/{customer_call_id}/actions/hangup", {})
    if call_log_name:
        frappe.db.set_value("CRM Call Log", call_log_name, "status", "No Answer")
        frappe.db.set_value("CRM Call Log", call_log_name, "end_time", frappe.utils.now_datetime())
        frappe.db.commit()


def _ring_group_customer_hangup(customer_call_id, ring_group):
    """The customer abandoned the call before any agent answered."""
    call_log_name = ring_group.get("call_log")

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
