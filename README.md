# Hostyo Frappe CRM - Custom Integrations

## Structure

- `/pbx_integration` — Custom Frappe app: Telnyx click-to-call + WebRTC webhook backend, plus inbound ring-group routing
  - `pbx_integration/telnyx.py` — main backend (click-to-call trigger, webhook handler, WebRTC credentials endpoint, inbound ring-group)
  - `.env.example` — required config keys (copy to `.env`, or set via `bench set-config`)

- `/crm-customizations` — Modified/added files from the official `frappe/crm` app (NOT a full copy of that repo).
  These are overlaid onto a fresh `crm` app clone at the same relative paths:

  **Backend:**
  - `crm/api/activities.py` — activity/timeline logic (SMS support added)
  - `crm/fcrm/doctype/crm_lead/crm_lead.json` + `.py` — Lead doctype (custom fields/logic)

  **Frontend:**
  - `frontend/src/App.vue` — registers TelnyxCallUI + RavenChat globally
  - `frontend/src/stores/global.js` — Make a Call button calls `pbx_integration.telnyx.create_click2call`
  - `frontend/src/components/Telephony/TelnyxCallUI.vue` — in-CRM call widget (WebRTC, mute/hold/hangup, live caller name, inbound Answer/Decline UI)
  - `frontend/src/components/RavenChat.vue` — custom Raven chat dock (repositioned, Hostyo branding)
  - `frontend/src/components/Activities/Activities.vue`, `SMSArea.vue`, `SMSBox.vue`, `WhatsAppBox.vue` — SMS/WhatsApp activity tabs
  - `frontend/src/components/Icons/SMSIcon.vue` — SMS icon
  - `frontend/src/components/Layouts/AppSidebar.vue` — sidebar (Chat/SMS nav entries)
  - `frontend/src/components/ListBulkActions.vue` — bulk actions (SMS-related)
  - `frontend/src/composables/telephony.js`, `sms.js` — telephony/SMS composables
  - `frontend/src/pages/Deal.vue`, `Lead.vue` — Deal/Lead detail pages
  - `frontend/src/assets/hostyo-logo.jpg` — Hostyo branding asset (used by RavenChat.vue)
  - `frontend/vite.config.js` — PWA `selfDestroying: true` (fixes stale service-worker cache bug)
  - `frontend/package.json`, `yarn.lock`, `auto-imports.d.ts` — dependency/build metadata (includes `@telnyx/webrtc`)

## Setup on a fresh environment

1. Install the `pbx_integration` app into your bench: `bench get-app <this-repo-path>` then `bench --site <site> install-app pbx_integration`
2. Copy `pbx_integration/.env.example` to `.env`, fill in real values, and set them on the site via `bench set-config <key> <value>` for each (telnyx_api_key, telnyx_connection_id, telnyx_caller_id, telnyx_sip_domain, telnyx_sip_password)
3. Copy each file under `crm-customizations/` to the matching path inside your `crm` app (both `crm/` backend and `frontend/` paths)
4. Set `pbx_extension` on each agent's User record to their Telnyx SIP Credential Connection username
5. In the Telnyx portal, assign your inbound phone number to the same Voice API / Call Control connection as `telnyx_connection_id`, with its webhook URL pointed at `<site>/api/method/pbx_integration.telnyx.handle_telnyx_webhook` — inbound ring-group routing (below) relies on webhooks for that connection reaching this same endpoint
6. Rebuild: `bench build --app crm` (or `yarn build` inside `apps/crm/frontend`)

## Outbound calling

Agent clicks "Make a Call" → `create_click2call` dials the agent's own SIP softphone (leg A, tagged `X-Call-Direction: outbound`), then once the agent answers, dials the lead's number (leg B) and bridges the two. The agent's WebRTC client auto-answers leg A instantly (it's just their own softphone ringing back to them), so the call UI goes straight to "Connecting..." then "On Call".

## Inbound calling

A call to our Telnyx number rings every agent with a `pbx_extension` set, simultaneously:

1. `call.initiated` (direction `incoming`, no `client_state` — we didn't originate it) → `_start_ring_group` creates a `CRM Call Log` (type `Incoming`) and dials every enabled agent's SIP address at once, each leg tagged `X-Call-Direction: inbound` via `custom_headers` and `timeout_secs=RING_TIMEOUT_SECS` (25s) so Telnyx auto-cancels unanswered legs. The set of ringing legs is tracked in `frappe.cache()` under `telnyx_ring_group:<customer_call_control_id>` (short TTL, since it only needs to survive the ring window).
2. Each agent's `TelnyxCallUI.vue` dock sees the leg come in as `ringing`, reads the `X-Call-Direction` custom header off the WebRTC call object, and — because it's `inbound` — does **not** auto-answer. Instead it shows a distinct "Incoming Call" state with the caller's number (and name, if Telnyx passes CNAM) and Answer/Decline buttons.
3. First agent to click Answer wins: `_ring_group_agent_answered` claims the ring group in cache, hangs up every other agent's leg, and answers the customer's leg. Once Telnyx confirms the customer's leg is answered, `_ring_group_bridge` bridges it to the winning agent and clears the cache entry.
4. If every agent leg times out or is declined before anyone answers, `_ring_group_agent_hangup` hangs up the customer's leg and marks the `CRM Call Log` status `No Answer`. Same outcome if the customer abandons the call first (`_ring_group_customer_hangup`).

Frontend caveat: the mapping from Telnyx's `custom_headers` to the `@telnyx/webrtc` call object (`call.options.custom_headers`, matched case-insensitively on `name`/`value`) hasn't been confirmed against a live call yet — verify on first real inbound test and adjust `getCallDirection()` in `TelnyxCallUI.vue` if the SDK surfaces it under a different shape.

## Known context / history
This app previously integrated with PBX.im (removed in favor of Telnyx — PBX.im lacked webhook support for real-time call status). See git history if that code is ever needed for reference.

SMS/WhatsApp activity tabs and Lead doctype customizations were added in an earlier session and are included here for completeness, alongside the Telnyx integration.
