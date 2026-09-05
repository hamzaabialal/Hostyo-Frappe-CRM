import frappe
import requests

OPENAI_API_BASE = "https://api.openai.com/v1"

# Fallback if openai_model isn't set in site_config.json - kept low-cost.
# Override via frappe.conf.get("openai_model") to swap models without a
# code deploy (e.g. when a model is sunset, as gpt-4o-mini now is).
DEFAULT_MODEL = "gpt-5-nano"

# Below this, a transcript is too short to summarize meaningfully (e.g. a
# 0-second "Initiated" call that never connected, or a few words of
# voicemail/hangup) - skip the OpenAI call entirely and leave ai_summary
# blank rather than force a summary out of nothing.
MIN_CALL_DURATION_SECS = 15
MIN_TRANSCRIPT_WORDS = 20

SUMMARY_SYSTEM_PROMPT = (
    "You are a sales-call analyst for a property-management CRM. You are given "
    "a raw call transcript that may be in Greek or English. Write a concise "
    "summary IN ENGLISH, 2-4 short sentences, no headings or bullet points, in "
    "this exact style: begin with 'Call Outcome:' and a short verdict (e.g. "
    "positive/advancing, neutral, negative). Then briefly state what was "
    "discussed. If the customer raised a concern, add 'Objection:' and it. If a "
    "next step or promise was agreed, add 'Commitment:' and it. Omit any part "
    "that didn't occur. Keep it under 60 words. Do not invent anything not in "
    "the transcript."
)


def _api_key():
    key = frappe.conf.get("openai_api_key")
    if not key:
        frappe.throw("openai_api_key not set in site_config.json")
    return key


def _model():
    return frappe.conf.get("openai_model") or DEFAULT_MODEL


def should_summarize(transcript, duration):
    """Whether a transcript is worth spending an OpenAI call on. `duration`
    may be None (field not yet set when this runs) - only skip on duration
    when it's actually known to be short, never skip just because it's
    unknown.
    """
    if not transcript or not transcript.strip():
        return False
    if duration is not None and duration < MIN_CALL_DURATION_SECS:
        return False
    if len(transcript.split()) < MIN_TRANSCRIPT_WORDS:
        return False
    return True


def generate_call_summary(call_log_name, transcript):
    """Enqueued job (see pbx_integration.telnyx._save_transcript) - calls
    OpenAI to summarize `transcript` and stores the result on CRM Call Log
    `call_log_name`.ai_summary. Best-effort: any failure here is logged and
    left with a blank ai_summary - the already-saved full transcript is
    never affected.
    """
    try:
        resp = requests.post(
            f"{OPENAI_API_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {_api_key()}",
                "Content-Type": "application/json",
            },
            json={
                "model": _model(),
                "messages": [
                    {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                    {"role": "user", "content": transcript},
                ],
            },
            timeout=60,
        )
        resp.raise_for_status()
        summary = resp.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        frappe.log_error(
            "OpenAI Call Summary",
            f"Failed to generate AI summary for call_log {call_log_name}: {frappe.get_traceback()}",
        )
        return

    if not summary:
        return

    frappe.db.set_value("CRM Call Log", call_log_name, "ai_summary", summary)
    frappe.db.commit()
