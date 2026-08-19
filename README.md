# Hostyo Frappe CRM - Custom Integrations

## Structure

- `/pbx_integration` — Custom Frappe app: Telnyx click-to-call + WebRTC webhook backend, plus inbound ring-group routing
  - `pbx_integration/telnyx.py` — main backend (click-to-call trigger, webhook handler, WebRTC credentials endpoint, inbound ring-group, DID routing, recordings)
  - `pbx_integration/patches/add_telnyx_did_field.py` — adds the `telnyx_did` custom field to User (DID→agent routing)
  - `.env.example` — required config keys (copy to `.env`, or set via `bench set-config`)

- `/crm-customizations` — Modified/added files from the official `frappe/crm` app (NOT a full copy of that repo).
  These are overlaid onto a fresh `crm` app clone at the same relative paths:

  **Backend:**
  - `crm/api/activities.py` — activity/timeline logic (SMS support added)
  - `crm/fcrm/doctype/crm_lead/crm_lead.json` + `.py` — Lead doctype (custom fields/logic)

  **Frontend:**
  - `frontend/src/App.vue` — registers TelnyxCallUI + RavenChat globally
  - `frontend/src/stores/global.js` — Make a Call button calls `pbx_integration.telnyx.create_click2call`
  - `frontend/src/components/Telephony/TelnyxCallUI.vue` — in-CRM call widget (WebRTC, mute/hold/hangup, live caller name as a clickable link to the Lead/Deal/Contact, inbound Answer/Decline UI with a generated ringtone)
  - `frontend/src/components/Modals/CallLogDetailModal.vue` — the "Call Details" popup opened from a call in the Calls/Activity tab (Lead/Deal/Contact-aware reference link; everything else — direction, participants, date, duration, status, recording player, notes — was already provider-agnostic in the stock component)
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
4. `bench --site <site> migrate` — runs `patches/add_telnyx_did_field.py`, which adds the `telnyx_did` custom field to User
5. Set `pbx_extension` on each agent's User record to their Telnyx SIP Credential Connection username. Optionally also set `telnyx_did` (E.164) on any agent who should get their own direct number instead of the shared ring-group — see "Inbound calling" below
6. In the Telnyx portal, assign your inbound phone number(s) to the same Voice API / Call Control connection as `telnyx_connection_id`, with its webhook URL pointed at `<site>/api/method/pbx_integration.telnyx.handle_telnyx_webhook` — inbound ring-group routing (below) relies on webhooks for that connection reaching this same endpoint. Also enable that connection for Call Control's recording feature if you haven't already (needed for `record_start` to succeed)
7. Rebuild: `bench build --app crm` (or `yarn build` inside `apps/crm/frontend`)

## Outbound calling

Agent clicks "Make a Call" → `create_click2call` dials the agent's own SIP softphone (leg A, tagged `X-Call-Direction: outbound`). The WebRTC client auto-answers leg A instantly (it's just their own softphone ringing back to them), so the call UI goes straight to "Connecting...". Once leg A is truly connected, `_agent_answered` dials the lead's number (leg B, `timeout_secs=RING_TIMEOUT_SECS`) — the frontend shows "Calling..." with the ringtone playing (same generated tone as inbound) while leg B rings, since leg A connecting is not the same as the lead picking up.

- **Lead answers**: `_lead_answered` clears leg B's pending marker, bridges the two legs, and starts recording. The `telnyx_call_event` for leg B's `call.answered` is what actually flips the frontend to "On Call" and starts the timer (the WebRTC client's own `active` event only tells us leg A connected, not that the lead did).
- **Lead doesn't answer** (times out, busy, or declined): `_lead_hangup` checks whether leg B was ever marked answered (`telnyx_leg_b_pending:<leg_b_id>` in `frappe.cache()`, set when leg B is dialed and cleared the moment it's answered — still present at hangup means it never was). If so, it hangs up the now-orphaned leg A and marks the `CRM Call Log` status `No Answer` instead of letting it fall through to a generic `Completed` — `_call_ended` won't downgrade that back to `Completed` when leg A's own hangup webhook follows moments later. The frontend shows a distinct "No Answer" state (from the `status` field now included in the `telnyx_call_event` payload) for a couple of seconds before the dock closes.

Once bridged, `_start_recording` starts a dual-channel recording on leg A.

Known gap: if the agent hangs up leg A themselves while leg B is still ringing, leg B currently keeps ringing the lead's phone independently — there's no cancel-the-other-leg wiring for that direction (only for "leg B failed → hang up leg A"). Not hit by normal use, but worth knowing.

## Inbound calling

A call to our Telnyx number rings either one specific agent or every agent, depending on whether that number is assigned:

1. `call.initiated` (direction `incoming`, no `client_state` — we didn't originate it) → `_start_ring_group` creates a `CRM Call Log` (type `Incoming`), looks up the caller against CRM Lead/Contact phone numbers (`_find_caller_reference`, normalized digit comparison) to link the call log and resolve a name, then calls `_agents_for_inbound_number` to decide who rings:
   - If a `User.telnyx_did` matches the dialed number (normalized comparison), only that agent's SIP leg is dialed — the ring-group is skipped entirely.
   - Otherwise every enabled agent with a `pbx_extension` rings simultaneously, same as before.

   Each leg is tagged `X-Call-Direction: inbound` via `custom_headers` and `timeout_secs=RING_TIMEOUT_SECS` (25s) so Telnyx auto-cancels unanswered legs. The set of ringing legs is tracked in `frappe.cache()` under `telnyx_ring_group:<customer_call_control_id>` (short TTL, since it only needs to survive the ring window).
2. Each agent's `TelnyxCallUI.vue` dock sees the leg come in as `ringing`, reads the `X-Call-Direction` custom header off the WebRTC call object (`call.options.customHeaders`, confirmed against the `@telnyx/webrtc` SDK source), and — because it's `inbound` — does **not** auto-answer. Instead it shows a distinct "Incoming Call" state with the caller's number/name, a generated ringtone (Web Audio API, no external file), and Answer/Decline buttons.
3. First agent to click Answer wins: `_ring_group_agent_answered` claims the ring group in cache, hangs up every other agent's leg, and answers the customer's leg. Once Telnyx confirms the customer's leg is answered, `_ring_group_bridge` bridges it to the winning agent, starts recording (`_start_recording`), and clears the cache entry.
4. If every agent leg times out or is declined before anyone answers, `_ring_group_agent_hangup` hangs up the customer's leg and marks the `CRM Call Log` status `No Answer`. Same outcome if the customer abandons the call first (`_ring_group_customer_hangup`).

## Caller name / clickable link

`_find_caller_reference` (outbound: passed in from whichever Lead/Deal page the call was made from; inbound: reverse phone lookup) sets `reference_doctype`/`reference_docname` on the `CRM Call Log`, exactly like CRM's own telephony integrations do. That reference travels to the frontend two ways — the `create_click2call` response (outbound, prefills instantly) and the `telnyx_call_event` realtime payload (both directions, fires at ring-time and again at answer-time) — and `TelnyxCallUI.vue` renders the resolved name as a link to `/crm/leads/<id>`, `/crm/deals/<id>`, or `/crm/contacts/<id>` (via named Vue Router routes `Lead`/`Deal`/`Contact`), navigable mid-call without dropping the dock.

## Call recording

`_start_recording` fires `record_start` (mp3, dual-channel) right after each bridge — leg A for outbound, the customer's leg for inbound — tagged with `client_state` so the eventual `call.recording.saved` webhook can be traced back to its `CRM Call Log`. `_save_recording` writes the recording URL (preferring Telnyx's `public_recording_urls`, which need no further auth, over the authenticated `recording_urls`) into the standard `recording_url` field. Nothing else needed on the frontend: CRM's own `CallArea.vue`/`AudioPlayer.vue` and the `get_recording_url` proxy already render and stream any call log with `recording_url` set, regardless of provider — confirmed against the `frappe/crm` source, since `_get_recording_credentials` explicitly falls back to no-auth for a `telephony_medium` it doesn't recognize (this integration uses `"Manual"`).

## Call Details modal

`crm/components/Modals/CallLogDetailModal.vue` (the popup opened from a call row in the Calls/Activity tab) is core CRM, shared across every telephony provider — it already renders direction, caller↔receiver avatars, a Lead/Deal link, date, duration, status, a recording player, and a notes section, all off plain `CRM Call Log` fields. Checked it directly against the `frappe/crm` source before touching it, since it's exactly the kind of thing worth verifying rather than assuming:

- **Notes**: no new field needed. The "Add Note" button already creates/edits an `FCRM Note` linked to the call log (`crm.integrations.api.add_note_to_call_log`) and renders it in a "Details"-style block — this is provider-agnostic already and works for Telnyx calls with zero changes.
- **Recording player**: also already generic (`<audio controls :src="recording_url_path">` with a graceful "Recording not available" fallback on error) — confirms the earlier recording work needs no frontend changes, only that `recording_url` gets set, which it does.
- **Reference link gap (fixed)**: the stock component only ever showed a Lead/Deal link, because upstream's Twilio/Exotel flows never link a bare Contact. Our inbound caller-ID lookup (`_find_caller_reference`) can resolve a Contact when no Lead/Deal matches, so the stock component would silently drop that link. Copied into `crm-customizations` with a third case added, driven off `reference_doctype`/`reference_docname` directly.
- **Duration field (fixed)**: `telnyx.py` set `start_time`/`end_time` but never `duration` itself, and the CRM Call Log controller has no hook that derives one — every Telnyx call was showing "0s" regardless of actual length. `_call_ended` now computes it from the two timestamps.
- **Caller/receiver field (fixed)**: `CRM Call Log` models these as two distinct fields depending on call type (`receiver` = who answered an Incoming call, `caller` = who placed an Outgoing one — confirmed in the doctype JSON's `depends_on`). `_ring_group_agent_answered` was setting `caller` for inbound calls, which the modal never reads for that direction — the agent's avatar/name would render blank. Now sets `receiver`.
- **Known nuance, not a bug**: the caller↔receiver avatar row's *external-party* side is resolved by a separate, independent lookup — core's own `get_contact_by_phone_number`, which only checks the `Contact` doctype — not by our `reference_doctype`/`reference_docname`. So a call linked to a Lead with no associated Contact record can show "Unknown" in that top row while the Lead link/badge below is still correct. This is identical behavior for Twilio/Exotel calls today, not something specific to this integration, so it was left alone rather than changing shared core behavior.

## Known context / history
This app previously integrated with PBX.im (removed in favor of Telnyx — PBX.im lacked webhook support for real-time call status). See git history if that code is ever needed for reference.

SMS/WhatsApp activity tabs and Lead doctype customizations were added in an earlier session and are included here for completeness, alongside the Telnyx integration.
