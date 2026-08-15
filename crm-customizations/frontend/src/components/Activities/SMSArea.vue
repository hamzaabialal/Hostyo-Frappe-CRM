<template>
  <div>
    <div
      v-for="sms in messages"
      :key="sms.name"
      class="activity group flex gap-2 mb-3"
      :class="[sms.type == 'Outgoing' ? 'flex-row-reverse' : '']"
    >
      <div
        class="relative max-w-[90%] rounded-md bg-surface-gray-1 text-ink-gray-9 p-1.5 pl-2 text-base shadow-sm"
      >
        <Badge
          v-if="sms.status == 'failed'"
          theme="red"
          :label="sms.status"
          class="absolute -top-2 right-0"
        />
        <div class="whitespace-pre-wrap">{{ sms.message }}</div>
        <div class="-mb-1 flex shrink-0 items-end gap-1 text-ink-gray-5 justify-end">
          <Tooltip :text="formatDate(sms.creation, 'ddd, MMM D, YYYY')">
            <div class="text-2xs">
              {{ formatDate(sms.creation, 'hh:mm a') }}
            </div>
          </Tooltip>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { formatDate } from '@/utils'
import { Tooltip, Badge } from 'frappe-ui'

defineProps({
  messages: { type: Array, default: () => [] },
})
</script>
