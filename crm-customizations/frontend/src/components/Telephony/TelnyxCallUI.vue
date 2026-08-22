<template>
  <div v-if="visible" class="telnyx-dock">
    <audio ref="remoteAudioEl" autoplay playsinline style="display: none"></audio>
    <div class="telnyx-dock__bar">
      <div class="telnyx-dock__status">
        <span class="telnyx-dock__dot" :class="statusClass"></span>
        <span>{{ statusLabel }}</span>
      </div>
      <span v-if="status === 'active'" class="telnyx-dock__timer">{{ formattedDuration }}</span>
    </div>

    <div class="telnyx-dock__number-row">
      <div class="telnyx-dock__avatar">
        <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 22 16.92z" />
        </svg>
      </div>
      <div
        class="telnyx-dock__number"
        :class="{ 'telnyx-dock__number--link': leadReference }"
        @click="goToReference"
      >{{ displayNumber }}</div>
    </div>

    <div v-if="status === 'ringing'" class="telnyx-dock__body">
      <button class="telnyx-dock__btn telnyx-dock__btn--answer" @click="answerCall">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 22 16.92z" />
        </svg>
        <span>Answer</span>
      </button>

      <button class="telnyx-dock__btn telnyx-dock__btn--hangup" @click="declineCall">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" stroke="none">
          <path d="M12 9c-1.6 0-3.15.25-4.6.72v3.1a1 1 0 0 1-.7.95c-.98.32-1.87.77-2.67 1.32a1 1 0 0 1-1.41-.13l-2.35-2.9a1 1 0 0 1 .15-1.4C3.85 8.4 7.72 7 12 7s8.15 1.4 11.58 3.66a1 1 0 0 1 .15 1.4l-2.35 2.9a1 1 0 0 1-1.41.13c-.8-.55-1.7-1-2.67-1.32a1 1 0 0 1-.7-.95v-3.1A15.6 15.6 0 0 0 12 9z" />
        </svg>
        <span>Decline</span>
      </button>
    </div>

    <div v-else class="telnyx-dock__body">
      <button
        class="telnyx-dock__btn"
        :class="{ active: isMuted }"
        @click="toggleMute"
        :disabled="!activeCall"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path v-if="!isMuted" d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
          <path v-if="!isMuted" d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v4M8 23h8" />
          <template v-else>
            <line x1="1" y1="1" x2="23" y2="23" />
            <path d="M9 9v3a3 3 0 0 0 5.12 2.12M15 9.34V4a3 3 0 0 0-5.94-.6" />
            <path d="M17 16.95A7 7 0 0 1 5 12v-2M19 10v2a7 7 0 0 1-.11 1.23" />
            <path d="M12 19v4M8 23h8" />
          </template>
        </svg>
        <span>{{ isMuted ? 'Unmute' : 'Mute' }}</span>
      </button>

      <button
        class="telnyx-dock__btn"
        :class="{ active: isHeld }"
        @click="toggleHold"
        :disabled="!activeCall"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <rect v-if="!isHeld" x="6" y="4" width="4" height="16" rx="1" />
          <rect v-if="!isHeld" x="14" y="4" width="4" height="16" rx="1" />
          <polygon v-else points="5 3 19 12 5 21 5 3" />
        </svg>
        <span>{{ isHeld ? 'Resume' : 'Hold' }}</span>
      </button>

      <button class="telnyx-dock__btn telnyx-dock__btn--hangup" @click="hangup" :disabled="!activeCall">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" stroke="none">
          <path d="M12 9c-1.6 0-3.15.25-4.6.72v3.1a1 1 0 0 1-.7.95c-.98.32-1.87.77-2.67 1.32a1 1 0 0 1-1.41-.13l-2.35-2.9a1 1 0 0 1 .15-1.4C3.85 8.4 7.72 7 12 7s8.15 1.4 11.58 3.66a1 1 0 0 1 .15 1.4l-2.35 2.9a1 1 0 0 1-1.41.13c-.8-.55-1.7-1-2.67-1.32a1 1 0 0 1-.7-.95v-3.1A15.6 15.6 0 0 0 12 9z" />
        </svg>
        <span>Hang Up</span>
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, computed, inject } from 'vue'
import { useRouter } from 'vue-router'
import { call as frappeCall } from 'frappe-ui'
import { globalStore } from '@/stores/global'
import { TelnyxRTC } from '@telnyx/webrtc'

const session = inject('session')
const gStore = globalStore()
const { $socket } = gStore
const router = useRouter()

// TEMPORARY DEBUG LOGGING - remove once the ringtone stop-on-answer bug is
// confirmed fixed. Tags every log this instance emits, so two accidental
// mounts of this component (which would each run their own independent
// ringtone/WebRTC/socket logic) show up as clearly distinct in the console
// instead of looking like one instance behaving inconsistently.
const instanceId = Math.random().toString(36).slice(2, 8)

const client = ref(null)
const remoteAudioEl = ref(null)
const activeCall = ref(null)
const visible = ref(false)
const isMuted = ref(false)
const isHeld = ref(false)
const status = ref('idle')
const leadNumber = ref('')
const leadName = ref('')
const leadReference = ref(null) // { doctype, name } once a Lead/Deal/Contact is resolved
const callDirection = ref('')
const durationSeconds = ref(0)
let timerHandle = null

// Route name + param key for each doctype the name/number can link to.
const REFERENCE_ROUTES = {
  'CRM Lead': { name: 'Lead', param: 'leadId' },
  'CRM Deal': { name: 'Deal', param: 'dealId' },
  Contact: { name: 'Contact', param: 'contactId' },
}

function setReference(doctype, name) {
  const route = doctype && name && REFERENCE_ROUTES[doctype]
  leadReference.value = route ? { doctype, name } : null
}

function goToReference() {
  const ref = leadReference.value
  const route = ref && REFERENCE_ROUTES[ref.doctype]
  if (!route) return
  router.push({ name: route.name, params: { [route.param]: ref.name } })
}

// Telnyx echoes back whatever custom_headers we set when originating the SIP
// leg (see telnyx.py: X-Call-Direction is "outbound" for click-to-call agent
// legs, "inbound" for ring-group legs). Confirmed against the @telnyx/webrtc
// source (VertoHandler.ts): the wire-format `dialogParams.custom_headers`
// (snake_case) gets parsed into `callOptions.customHeaders` (camelCase),
// which ends up as the call's public `options.customHeaders` - NOT
// `options.custom_headers`, which was the earlier (wrong) guess that made
// every inbound call fall through to auto-answer.
function getCallDirection(call) {
  const headers = call?.options?.customHeaders || []
  const entry = headers.find((h) => (h.name || '').toLowerCase() === 'x-call-direction')
  return (entry?.value || '').toLowerCase()
}

const statusLabel = computed(() => {
  return {
    idle: 'Idle',
    ringing: 'Incoming...',
    connecting: 'Connecting...',
    dialing: 'Calling...',
    active: 'On Call',
    ended: 'Call Ended',
    no_answer: 'No Answer',
  }[status.value]
})

const statusClass = computed(() => ({
  'telnyx-dock__dot--live': status.value === 'active',
  'telnyx-dock__dot--ringing':
    status.value === 'ringing' || status.value === 'connecting' || status.value === 'dialing',
}))

const displayNumber = computed(() => leadName.value || leadNumber.value || 'Unknown number')

const formattedDuration = computed(() => {
  const m = Math.floor(durationSeconds.value / 60)
  const s = durationSeconds.value % 60
  return `${m}:${s.toString().padStart(2, '0')}`
})

function startTimer() {
  stopTimer()
  durationSeconds.value = 0
  timerHandle = setInterval(() => {
    durationSeconds.value += 1
  }, 1000)
}

function stopTimer() {
  if (timerHandle) {
    clearInterval(timerHandle)
    timerHandle = null
  }
}

// Generated tone (no external audio file, so nothing to license) - a classic
// two-beep ring cadence, repeating every 2s while a call is ringing/dialing.
//
// This is NOT "play one tone and let it finish" - it's a recursive schedule:
// setInterval re-invokes ringOnce() every 2s, and each invocation itself
// schedules two Web Audio oscillators ahead of time on the AudioContext's
// own timeline (osc.start/stop at now+offset). Stopping it correctly means
// two distinct things, not one:
//   1. Cancel *future* setInterval ticks - clearInterval.
//   2. Make sure a tick that's already been dispatched (queued on the JS
//      event loop a moment before stopRingtone() runs) can't produce sound
//      either, and that closing the AudioContext actually lands before any
//      oscillator already scheduled on it fires.
// The token below covers both: every scheduled tick checks it's still the
// current generation *before* touching the audio graph, so a stale tick is
// always a no-op - independent of timing, of what triggered the stop, or of
// whether clearInterval/close() alone would have been enough on their own.
let ringtoneCtx = null
let ringtoneHandle = null
let ringtoneToken = 0

// TEMPORARY DEBUG LOGGING - remove once the ringtone stop-on-answer bug is
// confirmed fixed against a real test call. Timestamped so start/stop calls
// can be correlated against the WebRTC and telnyx_call_event logs below.
const ts = () => new Date().toISOString()

function playRingtone(source) {
  stopRingtone(`superseded-by:${source}`)
  const AudioCtx = window.AudioContext || window.webkitAudioContext
  if (!AudioCtx) return

  const myToken = ++ringtoneToken
  const ctx = new AudioCtx()
  ringtoneCtx = ctx
  ctx.resume?.().catch(() => {})

  console.log(`[${ts()}] [${instanceId}] RINGTONE PLAY token=${myToken} source=${source}`)

  const ringOnce = () => {
    // Stale-tick guard - see comment above. Covers both "stopRingtone already
    // ran" and "a newer playRingtone already superseded this one".
    if (myToken !== ringtoneToken || ctx !== ringtoneCtx) {
      console.log(`[${ts()}] [${instanceId}] RINGTONE TICK SKIPPED (stale) token=${myToken} currentToken=${ringtoneToken}`)
      return
    }
    const now = ctx.currentTime
    ;[0, 0.4].forEach((offset) => {
      const osc = ctx.createOscillator()
      const gain = ctx.createGain()
      osc.frequency.value = 440
      gain.gain.setValueAtTime(0, now + offset)
      gain.gain.linearRampToValueAtTime(0.15, now + offset + 0.02)
      gain.gain.setValueAtTime(0.15, now + offset + 0.35)
      gain.gain.linearRampToValueAtTime(0, now + offset + 0.4)
      osc.connect(gain)
      gain.connect(ctx.destination)
      osc.start(now + offset)
      osc.stop(now + offset + 0.4)
    })
  }

  ringOnce()
  ringtoneHandle = setInterval(ringOnce, 2000)
}

function stopRingtone(source) {
  const wasPlaying = !!ringtoneCtx
  ringtoneToken++ // invalidate any tick already queued/dispatched before this line, immediately
  console.log(`[${ts()}] [${instanceId}] RINGTONE STOP source=${source} wasPlaying=${wasPlaying} newToken=${ringtoneToken}`)
  if (ringtoneHandle) {
    clearInterval(ringtoneHandle)
    ringtoneHandle = null
  }
  if (ringtoneCtx) {
    const ctx = ringtoneCtx
    ringtoneCtx = null
    ctx.close().catch(() => {})
  }
}

// Shared teardown for both end-of-call signals: the WebRTC client's own
// hangup/destroy notification, and the telnyx_call_event socket message.
// They aren't guaranteed to arrive in a particular order, so a more specific
// reason ("no_answer") is never downgraded back to a generic "ended" by
// whichever signal happens to land second.
function endCall(reason) {
  if (status.value === reason) return // already handled - e.g. both legs' hangups reporting the same outcome
  if (status.value === 'no_answer' && reason !== 'no_answer') return

  status.value = reason
  activeCall.value = null
  isMuted.value = false
  isHeld.value = false
  stopTimer()
  stopRingtone(`endCall:${reason}`)

  // Give the agent a moment longer to actually read "No Answer" before the
  // dock disappears, versus the brief flash for a normal call ending.
  const delay = reason === 'no_answer' ? 2500 : 1500
  setTimeout(() => {
    visible.value = false
    status.value = 'idle'
    leadNumber.value = ''
    leadName.value = ''
    callDirection.value = ''
    leadReference.value = null
  }, delay)
}

async function setupClient() {
  let creds
  try {
    creds = await frappeCall('pbx_integration.telnyx.get_webrtc_credentials')
  } catch (e) {
    console.error('Telnyx: could not fetch WebRTC credentials', e)
    return
  }
  if (!creds?.username || !creds?.password) return

  client.value = new TelnyxRTC({
    login: creds.username,
    password: creds.password,
  })

  client.value.on('telnyx.ready', () => {
    console.log('Telnyx WebRTC client ready')
  })

  client.value.on('telnyx.error', (err) => {
    console.error('Telnyx WebRTC error', err)
  })

  client.value.on('telnyx.notification', (notification) => {
    if (notification.type !== 'callUpdate') return
    const call = notification.call
    if (!call) return

    // TEMPORARY DEBUG LOGGING - remove once the ringtone stop-on-answer bug
    // is confirmed fixed. Correlate against the RINGTONE PLAY/STOP and
    // TELNYX EVENT RECEIVED logs by timestamp to see the real order events
    // arrive in on a live call.
    console.log(`[${ts()}] [${instanceId}] WEBRTC call.state=${call.state} direction=${callDirection.value} status=${status.value}`)

    if (call.state === 'ringing') {
      activeCall.value = call
      visible.value = true
      // TEMPORARY DEBUG LOGGING - remove once the customHeaders shape above
      // is confirmed against a real inbound call.
      console.log('TELNYX RINGING call.options:', JSON.stringify(call.options))
      callDirection.value = getCallDirection(call)

      if (callDirection.value === 'inbound') {
        // A real inbound call - show Answer/Decline and wait for the agent.
        status.value = 'ringing'
        leadNumber.value = call.options?.remoteCallerNumber || ''
        leadName.value = call.options?.remoteCallerName || ''
        setReference(null, null) // filled in by the telnyx_call_event socket update, if it matches a lead
        playRingtone('inbound-ringing')
      } else {
        // Outbound click-to-call: this is our own softphone leg ringing back
        // to us, so auto-answer it exactly like before. It connects almost
        // instantly, so a ringtone here would just be a jarring blip - skip it.
        status.value = 'connecting'
        if (gStore.pendingCall) {
          leadNumber.value = gStore.pendingCall.number || ''
          leadName.value = gStore.pendingCall.lead_name || ''
          setReference(gStore.pendingCall.reference_doctype, gStore.pendingCall.reference_docname)
          gStore.pendingCall = null
        }
        call.answer()
      }
    } else if (call.state === 'active') {
      stopRingtone('webrtc-active-event')
      if (remoteAudioEl.value && call.remoteStream) {
        remoteAudioEl.value.srcObject = call.remoteStream
        remoteAudioEl.value.play().catch((e) => console.error('Telnyx: audio play failed', e))
      }

      if (callDirection.value === 'outbound' && status.value !== 'active') {
        // Our own leg just connected - Telnyx now dials the lead (leg B)
        // server-side. Stay off 'active'/the timer, and play the ringtone,
        // until leg B actually answers (telnyx_call_event, handled below).
        //
        // Guarded on status !== 'active': Telnyx's WebRTC client can re-fire
        // this same 'active' notification on leg A later (e.g. a mid-call
        // renegotiation once the server-side bridge to the lead completes).
        // Without the guard, that second firing would unconditionally redo
        // this branch - flipping back to 'dialing' and restarting the
        // ringtone - even though the lead already answered. Nothing would
        // stop it a second time, since the telnyx_call_event for leg B's
        // call.answered only ever fires once.
        status.value = 'dialing'
        playRingtone('outbound-leg-a-active')
      } else if (callDirection.value !== 'outbound') {
        status.value = 'active'
        startTimer()
      }
    } else if (call.state === 'hangup' || call.state === 'destroy') {
      endCall('ended')
    }
  })

  client.value.connect()
}

function toggleMute() {
  if (!activeCall.value) return
  if (isMuted.value) {
    activeCall.value.unmuteAudio()
  } else {
    activeCall.value.muteAudio()
  }
  isMuted.value = !isMuted.value
}

function toggleHold() {
  if (!activeCall.value) return
  if (isHeld.value) {
    activeCall.value.unhold()
  } else {
    activeCall.value.hold()
  }
  isHeld.value = !isHeld.value
}

function hangup() {
  if (!activeCall.value) return
  activeCall.value.hangup()
}

function answerCall() {
  if (!activeCall.value) return
  stopRingtone('answerCall')
  activeCall.value.answer()
  status.value = 'connecting'
}

function declineCall() {
  if (!activeCall.value) return
  stopRingtone('declineCall')
  activeCall.value.hangup()
}

function onTelnyxCallEvent(data) {
  // TEMPORARY DEBUG LOGGING - remove once the ringtone stop-on-answer bug is
  // confirmed fixed. This is the ONLY signal that stops the outbound
  // ringtone once the lead answers (leg B's call.answered) - if this log
  // never appears with leg==='B' on a live call where the lead genuinely
  // picked up, the socket event itself is the problem, not the audio code.
  console.log(`[${ts()}] [${instanceId}] TELNYX EVENT RECEIVED event=${data?.event} leg=${data?.leg} status=${data?.status}`, data)
  if (!data) return
  visible.value = true
  if (data.to) {
    leadNumber.value = data.to
  }
  if (data.lead_name) {
    leadName.value = data.lead_name
  }
  if (data.reference_doctype && data.reference_docname) {
    setReference(data.reference_doctype, data.reference_docname)
  }
  if (data.event === 'call.answered' && data.leg === 'B') {
    // The lead just picked up - this is the real start of the conversation.
    stopRingtone('socket:leg-B-answered')
    status.value = 'active'
    startTimer()
  }
  if (data.event === 'call.hangup') {
    endCall(data.status === 'No Answer' ? 'no_answer' : 'ended')
  }
}

onMounted(() => {
  // TEMPORARY DEBUG LOGGING - remove once the ringtone stop-on-answer bug is
  // confirmed fixed. If TWO different instanceIds ever appear in the console
  // for what should be a single dock, this component is mounted more than
  // once - each copy runs its own independent WebRTC client/ringtone/socket
  // listener, which would explain a ringtone one instance can't stop because
  // another instance is the one still playing it.
  console.error(`[${ts()}] [${instanceId}] TELNYX MOUNT TEST - this component IS mounting`)
  setupClient()
  console.log('TELNYX DEBUG - socket instance:', $socket)
  console.log('TELNYX DEBUG - socket connected?:', $socket?.connected)
  $socket.on('telnyx_call_event', onTelnyxCallEvent)
  console.log('TELNYX DEBUG - listener registered')
})

onBeforeUnmount(() => {
  if (client.value) {
    client.value.disconnect()
  }
  $socket.off('telnyx_call_event', onTelnyxCallEvent)
  stopTimer()
  stopRingtone('unmount')
})
</script>

<style scoped>
.telnyx-dock {
  position: fixed;
  right: 24px;
  bottom: 90px;
  width: 300px;
  z-index: 2147483000;
  background: #fff;
  border-radius: 14px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.18);
  overflow: hidden;
  font-family: inherit;
}

.telnyx-dock__bar {
  padding: 14px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #1a1a1a;
  color: #fff;
}

.telnyx-dock__status {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
}

.telnyx-dock__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #737373;
  flex-shrink: 0;
}
.telnyx-dock__dot--ringing {
  background: #f59e0b;
  animation: pulse 1s infinite;
}
.telnyx-dock__dot--live {
  background: #22c55e;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}

.telnyx-dock__timer {
  font-size: 13px;
  color: #a3a3a3;
  font-variant-numeric: tabular-nums;
}

.telnyx-dock__number-row {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 24px 16px;
  background: #fafafa;
  border-bottom: 1px solid #eee;
}

.telnyx-dock__avatar {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  background: #171717;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.telnyx-dock__number {
  font-size: 17px;
  font-weight: 600;
  color: #171717;
}
.telnyx-dock__number--link {
  cursor: pointer;
  color: #2563eb;
  text-decoration: underline;
  text-underline-offset: 2px;
}

.telnyx-dock__body {
  display: flex;
  gap: 10px;
  padding: 16px;
}

.telnyx-dock__btn {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 12px 4px;
  border-radius: 10px;
  border: 1px solid #e5e5e5;
  background: #fff;
  font-size: 11px;
  color: #404040;
  cursor: pointer;
  transition: background 0.15s;
}
.telnyx-dock__btn:hover:not(:disabled) {
  background: #f5f5f5;
}
.telnyx-dock__btn.active {
  background: #171717;
  color: #fff;
  border-color: #171717;
}
.telnyx-dock__btn--hangup {
  background: #dc2626;
  color: #fff;
  border-color: #dc2626;
}
.telnyx-dock__btn--hangup:hover:not(:disabled) {
  background: #b91c1c;
}
.telnyx-dock__btn--answer {
  background: #22c55e;
  color: #fff;
  border-color: #22c55e;
}
.telnyx-dock__btn--answer:hover:not(:disabled) {
  background: #16a34a;
}
.telnyx-dock__btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
</style>
