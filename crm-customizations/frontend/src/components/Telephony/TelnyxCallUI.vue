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
      <div class="telnyx-dock__number">{{ displayNumber }}</div>
    </div>

    <div class="telnyx-dock__body">
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
import { call as frappeCall } from 'frappe-ui'
import { globalStore } from '@/stores/global'
import { TelnyxRTC } from '@telnyx/webrtc'

const session = inject('session')
const { $socket } = globalStore()

const client = ref(null)
const remoteAudioEl = ref(null)
const activeCall = ref(null)
const visible = ref(false)
const isMuted = ref(false)
const isHeld = ref(false)
const status = ref('idle')
const leadNumber = ref('')
const leadName = ref('')
const durationSeconds = ref(0)
let timerHandle = null

const statusLabel = computed(() => {
  return {
    idle: 'Idle',
    ringing: 'Incoming...',
    connecting: 'Connecting...',
    active: 'On Call',
    ended: 'Call Ended',
  }[status.value]
})

const statusClass = computed(() => ({
  'telnyx-dock__dot--live': status.value === 'active',
  'telnyx-dock__dot--ringing': status.value === 'ringing' || status.value === 'connecting',
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

    if (call.state === 'ringing') {
      activeCall.value = call
      visible.value = true
      status.value = 'connecting'
      call.answer()
    } else if (call.state === 'active') {
      status.value = 'active'
      startTimer()
      if (remoteAudioEl.value && call.remoteStream) {
        remoteAudioEl.value.srcObject = call.remoteStream
        remoteAudioEl.value.play().catch((e) => console.error('Telnyx: audio play failed', e))
      }
    } else if (call.state === 'hangup' || call.state === 'destroy') {
      status.value = 'ended'
      activeCall.value = null
      isMuted.value = false
      isHeld.value = false
      stopTimer()
      setTimeout(() => {
        visible.value = false
        status.value = 'idle'
        leadNumber.value = ''
        leadName.value = ''
      }, 1500)
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

function onTelnyxCallEvent(data) {
  console.log('TELNYX EVENT RECEIVED:', data)
  if (!data) return
  visible.value = true
  if (data.to) {
    leadNumber.value = data.to
  }
  if (data.lead_name) {
    leadName.value = data.lead_name
  }
  if (data.event === 'call.hangup') {
    status.value = 'ended'
    stopTimer()
    setTimeout(() => {
      visible.value = false
      status.value = 'idle'
      leadNumber.value = ''
    }, 1500)
  }
}

onMounted(() => {
  console.error('TELNYX MOUNT TEST - this component IS mounting')
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
.telnyx-dock__btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
</style>
