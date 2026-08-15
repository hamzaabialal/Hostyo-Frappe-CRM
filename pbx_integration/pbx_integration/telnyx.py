import base64
import json

import frappe
import requests

TELNYX_API_BASE = "https://api.telnyx.com/v2"


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
        },
    )

    call_control_id = data.get("data", {}).get("call_control_id")

    return {
        "status": "initiated",
        "call_log": call_log.name,
        "call_control_id": call_control_id,
        "destination": to,
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

    try:
        if event_type == "call.answered" and leg == "A":
            _agent_answered(call_control_id, state, call_log_name)

        elif event_type == "call.answered" and leg == "B":
            _lead_answered(call_control_id, state, call_log_name)

        elif event_type == "call.hangup":
            _call_ended(call_control_id, leg, state, call_log_name)
    except Exception:
        frappe.log_error("Telnyx Webhook CRASH", frappe.get_traceback())

    if call_log_name and state.get("agent_user"):
        to_number = frappe.db.get_value("CRM Call Log", call_log_name, "to")
        lead_name = _lead_display_name(call_log_name)
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


def _lead_display_name(call_log_name):
    """Look up the linked Lead/Deal/Contact's display name for a call log."""
    ref_doctype, ref_name = frappe.db.get_value(
        "CRM Call Log", call_log_name, ["reference_doctype", "reference_docname"]
    )
    if not ref_doctype or not ref_name:
        return None
    try:
        title_field = frappe.get_meta(ref_doctype).get_title_field()
        if title_field and title_field != "name":
            return frappe.db.get_value(ref_doctype, ref_name, title_field)
    except Exception:
        pass
    return None
