# Hostyo Frappe CRM - Custom Integrations

## Structure

- `/pbx_integration` — Custom Frappe app: Telnyx click-to-call + WebRTC webhook backend
  - `pbx_integration/telnyx.py` — main backend (call trigger, webhook handler, WebRTC credentials endpoint)
  - `.env.example` — required config keys (copy to `.env`, or set via `bench set-config`)

- `/crm-customizations` — Modified files from the official `frappe/crm` app (NOT a full copy of that repo).
  These are overlaid onto a fresh `crm` app clone at the same relative paths:
  - `frontend/src/App.vue` — registers TelnyxCallUI + RavenChat globally
  - `frontend/src/stores/global.js` — Make a Call button now calls `pbx_integration.telnyx.create_click2call`
  - `frontend/src/components/Telephony/TelnyxCallUI.vue` — in-CRM call widget (WebRTC, mute/hold/hangup, live caller name)
  - `frontend/src/components/RavenChat.vue` — custom Raven chat dock (repositioned, Hostyo branding)
  - `frontend/vite.config.js` — PWA `selfDestroying: true` (fixes stale service-worker cache bug)

## Setup on a fresh environment

1. Install the `pbx_integration` app into your bench: `bench get-app <this-repo-path>` then `bench --site <site> install-app pbx_integration`
2. Copy `pbx_integration/.env.example` to `.env`, fill in real values, and set them on the site via `bench set-config <key> <value>` for each (telnyx_api_key, telnyx_connection_id, telnyx_caller_id, telnyx_sip_domain, telnyx_sip_password)
3. Copy each file under `crm-customizations/` to the matching path inside your `crm` app's frontend
4. Set `pbx_extension` on each agent's User record to their Telnyx SIP Credential Connection username
5. Rebuild: `bench build --app crm` (or `yarn build` inside `apps/crm/frontend`)

## Known context / history
This app previously integrated with PBX.im (removed in favor of Telnyx — PBX.im lacked webhook support for real-time call status). See git history if that code is ever needed for reference.
