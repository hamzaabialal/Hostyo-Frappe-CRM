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
  - `crm/fcrm/doctype/crm_call_log/crm_call_log.py` — `CRMCallLog.as_dict()` serves locally re-hosted recordings directly instead of through the provider-fetch proxy (see "Call recording" below)

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
7. Rebuild: `bench build --app crm` (or `yarn build` inside `apps/crm/frontend`), then `bench restart` (or restart the site's workers) — the `crm_call_log.py` controller change needs a Python process restart to take effect, not just a rebuild

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

### Debugged: a genuinely-answered inbound call showing as "No Answer" / 0s / no recording

Traced end-to-end after a report of exactly this. Two confirmed, fixed bugs:

- **Ring-time name race (explains the popup showing the raw number, correct in the modal afterward)**: `_start_ring_group` never committed after inserting the `CRM Call Log`, before dialing agent legs. Dialing is an external HTTP call to Telnyx that can trigger a webhook back to a *different* worker almost immediately (the agent leg's own `call.initiated`) — that webhook's read of `reference_doctype`/`reference_docname` could race ahead of the insert's commit and see nothing yet, even though it's correctly linked moments later once the original request naturally commits. Added an explicit `frappe.db.commit()` right after the insert, before any dialing starts.
- **`agent_user` silently dropped from every event after `record_start`**: `_start_recording`'s `client_state` only ever carried `{"leg": "recording", "call_log": ...}` — once set (right after bridging, on the customer's leg for inbound / leg A for outbound), every later webhook for that leg — crucially its own real end-of-call hangup — failed the realtime-publish block's `state.get("agent_user")` check and went unpublished. `_start_recording` now takes an `agent_user` param and carries it through; `_ring_group_agent_answered` also stashes `winner_agent_user` in the ring-group cache dict so `_ring_group_bridge` has it to pass along, and now tags the customer leg's own `answer` action with `client_state` too (previously left unset), so the bridge-confirmation event isn't silently dropped either.

Also added: if the `bridge` action itself throws (e.g. the winning leg is already gone), `_ring_group_bridge` now marks the call `Failed` and cleans up the cache instead of leaving the call log stuck at `Initiated` with no trace of what happened.

Despite a thorough trace, no deterministic code path was found where a call that successfully reached `_ring_group_bridge` (cache deleted, status `In Progress`) could later be downgraded back to `No Answer` — every place that sets `No Answer` is gated behind the ring-group cache still being present, i.e. no winner ever bridged. So if the reported symptom persists after these two fixes, the likely next suspect is the `answer` or `bridge` Telnyx API call itself failing silently for that specific call. `TEMPORARY DEBUG LOGGING` was added at every decision point in this chain (`_ring_group_agent_answered`, `_ring_group_bridge`, `_ring_group_agent_hangup`, `_ring_group_customer_hangup`) — each logs the ring-group cache state (found/not, winner, remaining legs) it's acting on, so a live re-test can be traced call-log-name by call-log-name through Frappe's Error Log to find exactly where it diverges.

## Caller name / clickable link

`_find_caller_reference` (outbound: passed in from whichever Lead/Deal page the call was made from; inbound: reverse phone lookup) sets `reference_doctype`/`reference_docname` on the `CRM Call Log`, exactly like CRM's own telephony integrations do. That reference travels to the frontend two ways — the `create_click2call` response (outbound, prefills instantly) and the `telnyx_call_event` realtime payload (both directions, fires at ring-time and again at answer-time) — and `TelnyxCallUI.vue` renders the resolved name as a link to `/crm/leads/<id>`, `/crm/deals/<id>`, or `/crm/contacts/<id>` (via named Vue Router routes `Lead`/`Deal`/`Contact`), navigable mid-call without dropping the dock.

## Call recording

`_start_recording` fires `record_start` (mp3, dual-channel) right after each bridge — leg A for outbound, the customer's leg for inbound — tagged with `client_state` so the eventual `call.recording.saved` webhook can be traced back to its `CRM Call Log`. Nothing else needed on the frontend: CRM's own `CallArea.vue`/`CallLogDetailModal.vue` and the `get_recording_url` proxy already render and stream any call log with `recording_url` set, regardless of provider — confirmed against the `frappe/crm` source, since `_get_recording_credentials` explicitly falls back to no-auth for a `telephony_medium` it doesn't recognize (this integration uses `"Manual"`).

### Debugged: recording saved but the player won't load it

Checked both the field names (`recording_url` written by the backend vs. `recording_url_path` read by the frontend) and the extraction logic (`public_recording_urls`/`recording_urls`, `.mp3`/`.wav` keys) against Telnyx's own OpenAPI schema (`CallRecordingSaved` in `team-telnyx/openapi`, fetched directly rather than assumed) — both were already correct; `recording_url_path` is deliberately a *different*, derived field (core's `CRMCallLog.as_dict()` computes it as a proxy URL from `recording_url`), not a naming bug.

The actual cause, confirmed by that same schema: `recording_urls` is **"valid for 10 minutes"** after the recording is saved, and the non-expiring `public_recording_urls` **"is activated on a per request basis" via Telnyx support** — not on by default, so it's very likely absent from this account's payloads entirely. Storing either URL directly means the field looks correctly "attached" immediately, but playback silently stops working the moment the link expires — indistinguishable from a real bug unless you happen to test within that 10-minute window.

Fixed by having `_save_recording` download the file immediately (server-side, while the link is still guaranteed fresh — this is the very webhook telling us it just became available) and re-host it as a permanent, public Frappe `File` attached to the call log; `recording_url` is then set to that file's own absolute URL (`frappe.utils.get_url(file_doc.file_url)` — must be absolute, not the bare `/files/...` path, since `get_recording_url`'s own fetch validates for a scheme+host) rather than Telnyx's. This sidesteps the expiry entirely and doesn't depend on Telnyx support activating anything. Falls back to storing Telnyx's URL directly (previous behavior) only if the download itself fails.

Recording format was also double-checked: `_start_recording` requests `"format": "mp3"` explicitly, which every major browser's `<audio>` element plays natively — not the cause.

### Debugged (part 2): still "Recording not available" after re-hosting the file

The re-hosting fix above stores a working, permanent file — but the player still routes through it via `recording_url_path`, which core's `CRMCallLog.as_dict()` *always* computes as the `get_recording_url` proxy URL, unconditionally, for any provider. That proxy makes *this server* fetch whatever `recording_url` holds over plain HTTP — including, now, its own public URL. Plenty of hosts can't loop a request back through their own public IP (no hairpin NAT/NAT reflection) — the self-fetch can hang or fail even though the file is sitting there correctly, and the failure looks identical from the browser's side: `<audio>`'s `@error` fires, "Recording not available".

Fixed by customizing `CRMCallLog.as_dict()` (`crm-customizations/crm/fcrm/doctype/crm_call_log/crm_call_log.py`) to detect when `recording_url` is already this site's own URL (`recording_url.startswith(frappe.utils.get_url())`) and, only then, point `recording_url_path` straight at it — no proxy round-trip, no fetch-your-own-IP risk. Twilio/Exotel recordings (genuinely external provider URLs) are completely unaffected and still go through the original proxy exactly as before; the rest of `crm_call_log.py` is byte-for-byte the upstream file.

**Nothing needed in the Telnyx dashboard for this.** `record_start`/`call.recording.saved` are driven entirely by the Call Control API calls this integration already makes — there's no separate recording toggle to enable for that mechanism. The one Telnyx-side option that *would* help (though no longer required, since recordings are now re-hosted immediately) is asking Telnyx support to activate `public_recording_urls` on the account, which removes the 10-minute expiry window entirely rather than racing it.

### Debugged (part 3): locking recordings down to permissioned users only

Part 2 initially stored the re-hosted file as a *public* Frappe File — reachable by anyone with the direct link, not just logged-in CRM users with read access to that call log. Fixed by switching to a private file and routing through Frappe's own permission-checked file route instead of a public URL or a hand-rolled endpoint.

Read Frappe core's actual file-serving path (`frappe/app.py` → `frappe.utils.response.download_private_file` → `frappe.core.doctype.file.utils.find_file_by_url` → `File.has_permission`) before building anything, rather than assume how `/private/files/` behaves. It turns out this already does everything a custom streaming endpoint would need to:

- **Rejects Guest outright** — `download_private_file` checks `frappe.session.user == "Guest"` before anything else.
- **Checks real permission, not just "logged in"** — `File.has_permission` special-cases files with `attached_to_doctype`/`attached_to_name` set (which `_save_recording` already sets, to `CRM Call Log`) and defers straight to that document's own `has_permission("read")` — the exact same permission rule the rest of the CRM already uses for that doctype (role-based, ownership, sharing, whatever it resolves to), not a separately-invented check.
- **Serves bytes straight from disk** — `werkzeug.utils.send_file(filepath, ..., conditional=True)`, no HTTP re-fetch of any kind, so the hairpin-NAT/self-fetch failure mode from part 2 can't recur either.
- **Range requests for free** — `conditional=True` gives seeking/duration support automatically, more robust than the original proxy's own hand-rolled `Range` forwarding.

Writing a custom whitelisted method would have meant re-implementing permission checks, path safety, and Range handling that Frappe already ships and has already hardened — more code, more surface area to get wrong, for a result no more secure than just using the built-in route. So `_save_recording` now creates the File with `is_private: 1` instead of `0`; no other code changed, since `crm_call_log.py`'s routing logic already only checks "is this our own site's URL" — true for both `/files/...` and `/private/files/...` — so it transparently starts pointing at the permission-checked path.

**Verification**: I confirmed this logic by reading Frappe's actual source for the permission chain and file-serving mechanics described above, and both files compile cleanly. I don't have access to this bench or a live Telnyx account from here, so I could not personally place a real call and click play, or send a live logged-out request against the deployed site — once this is deployed, please:
1. Make a real inbound or outbound call, open its Call Details modal, and confirm the recording plays for a normal logged-in user.
2. Check Frappe's Error Log for the `Telnyx Recording Saved` entries — the final one logs the exact stored URL (`FINAL recording_url=...`), which will now be a `/private/files/...` path.
3. Copy that URL and open it in a logged-out/incognito browser tab (or `curl` it without a session cookie) — it should be rejected, not play.

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
