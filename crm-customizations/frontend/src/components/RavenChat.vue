<template>
  <div class="raven-dock" :class="{ 'is-open': open }">
    <!-- Header bar (hamesha visible, bottom-left mein docked) -->
    <div class="raven-dock__bar" @click="toggle">
      <div class="raven-dock__brand">
        <img :src="logoUrl" alt="Hostyo" class="raven-dock__wordmark-logo" />
        <a
          :href="ravenUrl"
          target="_blank"
          rel="noopener noreferrer"
          class="raven-dock__ext"
          title="Open Raven in new tab"
          @click.stop
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
            <polyline points="15 3 21 3 21 9" />
            <line x1="10" y1="14" x2="21" y2="3" />
          </svg>
        </a>
      </div>

      <button class="raven-dock__toggle" :title="open ? 'Collapse' : 'Expand'" @click.stop="toggle">
        <svg v-if="!open" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="18 15 12 9 6 15" />
        </svg>
        <svg v-else width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <line x1="18" y1="6" x2="6" y2="18" />
          <line x1="6" y1="6" x2="18" y2="18" />
        </svg>
      </button>
    </div>

    <!-- Body: sirf open hone pe, upar ki taraf grow karta hai -->
    <div class="raven-dock__body">
      <iframe
        v-if="loaded"
        :src="ravenUrl"
        class="raven-dock__frame"
        title="Raven Chat"
        allow="clipboard-read; clipboard-write; microphone; camera; autoplay"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import logoUrl from '../assets/hostyo-logo.jpg'

const props = defineProps({
  ravenUrl: { type: String, default: '/raven' },
})

const open = ref(false)
const loaded = ref(false)

function toggle() {
  open.value = !open.value
  if (open.value) loaded.value = true
}
function onKey(e) {
  if (e.key === 'Escape' && open.value) open.value = false
}

onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<style scoped>
.raven-dock {
  position: fixed;
  right: 24px;
  bottom: 0;
  width: 400px;
  max-width: calc(100vw - 48px);
  z-index: 2147483000;

  display: flex;
  flex-direction: column;

  background: #fff;
  border: 1px solid #e2e2e2;
  border-bottom: none;
  border-radius: 10px 10px 0 0;
  box-shadow: 0 -4px 24px rgba(0, 0, 0, 0.12);
  overflow: hidden;
}

/* Bar */
.raven-dock__bar {
  flex: 0 0 auto;
  height: 48px;
  padding: 0 12px 0 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  user-select: none;
  background: #fff;
}
.raven-dock__bar:hover {
  background: #fafafa;
}

.raven-dock__brand {
  display: flex;
  align-items: center;
  gap: 10px;
}
.raven-dock__wordmark {
  font-size: 17px;
  font-weight: 700;
  letter-spacing: -0.01em;
  color: #171717;
}
.raven-dock__wordmark-logo {
  height: 24px;
  width: auto;
  display: block;
}
.raven-dock__ext {
  display: flex;
  align-items: center;
  color: #737373;
  text-decoration: none;
}
.raven-dock__ext:hover {
  color: #171717;
}

.raven-dock__toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: #404040;
  cursor: pointer;
}
.raven-dock__toggle:hover {
  background: #ededed;
  color: #171717;
}

/* Body — height animate hoti hai, isliye panel upar khulta hai */
.raven-dock__body {
  height: 0;
  overflow: hidden;
  transition: height 0.22s ease;
  border-top: 1px solid transparent;
}
.raven-dock.is-open .raven-dock__body {
  height: min(620px, 74vh);
  border-top-color: #ededed;
}

.raven-dock__frame {
  width: 100%;
  height: 100%;
  border: none;
  display: block;
}

/* Mobile */
@media (max-width: 640px) {
  .raven-dock {
    left: 12px;
    right: 12px;
    width: auto;
    max-width: none;
  }
  .raven-dock.is-open .raven-dock__body {
    height: 68vh;
  }
}
</style>
