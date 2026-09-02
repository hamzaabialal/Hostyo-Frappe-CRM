import hashlib
import hmac
import json

import frappe
import requests
from frappe import _

SIGNWELL_API_BASE = "https://www.signwell.com/api/v1"

# Per-language template configuration. The placeholder_name values and field
# api_ids below were read directly off the live SignWell templates via
# GET /api/v1/document_templates/{id} - not guessed from the template
# builder's UI labels. Both templates' "Document Sender" placeholder
# (HOSTYO LTD / Andreas Pelekanos) is pre-filled and pre-signed in the
# template itself - but SignWell still requires a recipient entry for
# every placeholder, so its name/email are recorded here too even though
# no template_fields are ever sent for it.
TEMPLATES = {
	"en": {
		"config_key": "signwell_template_en",
		"placeholder_name": "Client",
		"full_name_api_id": "TextField_1",
		"property_address_api_id": "TextField_2",
		"sender_placeholder_name": "Document Sender",
		"sender_name": "Hostyo",
		"sender_email": "support@hostyo.com",
	},
	"gr": {
		"config_key": "signwell_template_gr",
		"placeholder_name": "Ιδιοκτήτης",
		"full_name_api_id": "TextField_1",
		"property_address_api_id": "TextField_2",
		"sender_placeholder_name": "Document Sender",
		"sender_name": "Hostyo",
		"sender_email": "support@hostyo.com",
	},
}


def _api_key():
	key = frappe.conf.get("signwell_api_key")
	if not key:
		frappe.throw("signwell_api_key not set in site_config.json")
	return key


def _webhook_id():
	webhook_id = frappe.conf.get("signwell_webhook_id")
	if not webhook_id:
		frappe.throw("signwell_webhook_id not set in site_config.json")
	return webhook_id


def _template_config(language):
	config = TEMPLATES.get(language)
	if not config:
		frappe.throw(f"Unknown contract language {language!r}. Use 'en' or 'gr'.")

	template_id = frappe.conf.get(config["config_key"])
	if not template_id:
		frappe.throw(f"{config['config_key']} not set in site_config.json")

	return {**config, "template_id": template_id}


def _headers():
	return {
		"X-Api-Key": _api_key(),
		"Content-Type": "application/json",
	}


def _post(path, body):
	resp = requests.post(f"{SIGNWELL_API_BASE}{path}", headers=_headers(), json=body, timeout=20)
	try:
		data = resp.json()
	except ValueError:
		data = {"raw": resp.text}
	if resp.status_code >= 300:
		frappe.log_error("SignWell API", f"[{resp.status_code}] {path}: {data}")
		frappe.throw(f"SignWell API error: {data}")
	return data


def _deal_status_or_throw(status_name):
	"""Never create a missing CRM Deal Status - just fail loudly. Both
	"Contract Sent" and "Won" are expected to already exist on the site;
	this guard only fires if that ever stops being true.
	"""
	if not frappe.db.exists("CRM Deal Status", status_name):
		frappe.throw(
			f"CRM Deal Status {status_name!r} does not exist. "
			"Create it in the CRM before this action can run."
		)
	return status_name


def _primary_contact(deal):
	for row in deal.contacts:
		if row.is_primary:
			return row
	return None


@frappe.whitelist()
def send_contract(deal_name, language):
	deal = frappe.get_doc("CRM Deal", deal_name)
	deal.check_permission("write")

	contact = _primary_contact(deal)
	if not contact or not contact.email:
		frappe.throw(_("This deal has no primary contact with an email address - cannot send a contract."))
	if not contact.full_name:
		frappe.throw(_("This deal's primary contact has no full name set - cannot send a contract."))
	if not deal.property_address:
		frappe.throw(_("This deal has no property address set - cannot send a contract."))

	template = _template_config(language)
	contract_sent_status = _deal_status_or_throw("Contract Sent")

	data = _post(
		"/document_templates/documents",
		{
			"template_id": template["template_id"],
			"recipients": [
				{
					"id": "customer",
					"name": contact.full_name,
					"email": contact.email,
					"placeholder_name": template["placeholder_name"],
				},
				{
					"id": "sender",
					"name": template["sender_name"],
					"email": template["sender_email"],
					"placeholder_name": template["sender_placeholder_name"],
				},
			],
			"template_fields": [
				{"api_id": template["full_name_api_id"], "value": contact.full_name},
				{"api_id": template["property_address_api_id"], "value": deal.property_address},
			],
			"metadata": {"crm_deal": deal.name},
		},
	)

	document_id = data.get("id")
	if not document_id:
		frappe.throw(_("SignWell did not return a document id: {0}").format(data))

	# Persist signwell_document_id via db.set_value (not part of the same
	# save() as the status change below) and mirror it onto the in-memory
	# doc so save()'s own before/after diff sees no change for this field.
	# CRM Deal has track_changes=1, and the activity timeline
	# (crm.api.activities.get_deal_activities) only ever renders the FIRST
	# entry of each Version's "changed" list - if both fields changed in
	# the same save(), the status change (the one that actually matters
	# for the timeline) could silently lose that race depending on field
	# order. Keeping this as its own write guarantees the status save()
	# below produces a Version whose only changed field is "status".
	frappe.db.set_value("CRM Deal", deal.name, "signwell_document_id", document_id)
	deal.signwell_document_id = document_id

	deal.status = contract_sent_status
	deal.save()

	return {"status": "sent", "document_id": document_id, "deal": deal.name}


def _verify_event(event):
	"""HMAC-SHA256(webhook_id, "{type}@{time}") must match event["hash"],
	per SignWell's own documented verification method. Never raises - a
	missing config value or a bad signature must reject the event, not
	crash the request.
	"""
	webhook_id = frappe.conf.get("signwell_webhook_id")
	if not webhook_id:
		frappe.log_error("SignWell Webhook", "signwell_webhook_id not set in site_config.json - rejecting event")
		return False

	event_type = event.get("type")
	event_time = event.get("time")
	received_hash = event.get("hash")
	if not event_type or event_time is None or not received_hash:
		frappe.log_error("SignWell Webhook", f"Event missing type/time/hash: {event}")
		return False

	message = f"{event_type}@{event_time}"
	calculated_hash = hmac.new(webhook_id.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()

	if not hmac.compare_digest(calculated_hash, received_hash):
		frappe.log_error(
			"SignWell Webhook",
			f"Hash mismatch for event_type={event_type} time={event_time} - rejecting event",
		)
		return False

	return True


def _mark_deal_won(document_id):
	if not document_id:
		frappe.log_error("SignWell Webhook", "document_completed event with no document id in payload")
		return

	deal_name = frappe.db.get_value("CRM Deal", {"signwell_document_id": document_id}, "name")
	if not deal_name:
		frappe.log_error(
			"SignWell Webhook",
			f"document_completed for document_id={document_id} - no matching CRM Deal found",
		)
		return

	won_status = _deal_status_or_throw("Won")

	deal = frappe.get_doc("CRM Deal", deal_name)
	if deal.status == won_status:
		# Already Won - a duplicate/retried webhook delivery, not an error.
		return

	deal.status = won_status
	deal.save(ignore_permissions=True)


@frappe.whitelist(allow_guest=True)
def handle_signwell_webhook():
	try:
		body = frappe.request.get_data(as_text=True)
		payload_root = json.loads(body) if body else {}
	except Exception:
		frappe.log_error("SignWell webhook: could not parse JSON body", "SignWell Webhook")
		return {"success": False}

	event = payload_root.get("event", {})
	event_type = event.get("type")
	document_id = payload_root.get("data", {}).get("object", {}).get("id")

	if not event_type:
		return {"success": False, "msg": "No event type"}

	if not _verify_event(event):
		return {"success": False, "msg": "Verification failed"}

	try:
		if event_type == "document_completed":
			_mark_deal_won(document_id)
		# every other event type (document_sent, document_viewed, document_signed
		# for a single recipient, document_declined, etc.) is deliberately ignored
	except Exception:
		frappe.log_error("SignWell Webhook CRASH", frappe.get_traceback())

	return {"success": True}
