<template>
  <div>
    <div class="mb-1 flex items-center justify-stretch gap-2 py-1 text-base">
      <div class="inline-flex items-center flex-wrap gap-1 text-ink-gray-5">
        <span class="font-medium text-ink-gray-8">
          {{ meeting.subject || __('Meeting') }}
        </span>
      </div>
      <div class="ml-auto whitespace-nowrap">
        <TimelineTimestamp :date="meeting.starts_on" />
      </div>
    </div>
    <div
      class="flex flex-col gap-2 border border-outline-elevation-2 rounded-md bg-surface-elevation-1 px-3 py-2.5 text-ink-gray-9"
    >
      <div class="flex items-center justify-between">
        <div class="inline-flex gap-2 items-center text-base-medium">
          <!-- Colored circular icon badge, keyed off meeting_type - matches
               the reference design's colored-dot style. Falls back to the
               "Other" entry (generic calendar icon, neutral gray) when
               meeting_type is unset, which is every meeting booked through
               the current UI right now - see the note in the <script>
               block on BookMeetingModal.vue not yet collecting this field. -->
          <div
            class="flex h-6 w-6 shrink-0 items-center justify-center rounded-full"
            :style="{ backgroundColor: meetingTypeInfo.color }"
          >
            <component :is="meetingTypeInfo.icon" class="size-3.5 text-white" />
          </div>
          <div>{{ meeting.subject || __('Meeting') }}</div>
        </div>
        <div class="flex items-center gap-1">
          <Badge :label="statusLabel" :theme="statusColorMap[meeting.status] || 'gray'" />
          <!-- Per-row context menu - matches CallLogDetailModal.vue's exact
               Dropdown pattern (ghost more-horizontal trigger, grouped
               hidden-label items). STUB: onClick handlers do nothing yet -
               there's no update_meeting/cancel_meeting endpoint in
               meetings.py, and adding one was explicitly optional/
               time-permitting for this pass. Menu renders and opens for
               real; the actions themselves are placeholders only. -->
          <Dropdown
            :options="[
              {
                group: __('Options'),
                hideLabel: true,
                items: [
                  { label: __('Edit'), icon: 'edit-2', onClick: editMeeting },
                  { label: __('Cancel Meeting'), icon: 'x-circle', onClick: cancelMeeting },
                ],
              },
            ]"
          >
            <template #default>
              <Button variant="ghost" icon="lucide-more-horizontal" />
            </template>
          </Dropdown>
        </div>
      </div>
      <div class="flex items-center flex-wrap gap-2">
        <Badge :label="formatDate(meeting.starts_on, 'MMM D, dddd')">
          <template #prefix>
            <CalendarIcon class="size-3" />
          </template>
        </Badge>
        <Badge :label="timeRangeLabel">
          <template #prefix>
            <DurationIcon class="size-3" />
          </template>
        </Badge>
        <Badge
          v-if="meeting.custom_meeting_provider"
          :label="meeting.custom_meeting_provider"
        />
      </div>
      <!-- Attendee avatars - replaces the previous plain-text "With: a, b, c"
           list. Reuses MultipleAvatar (already used elsewhere in this app,
           e.g. CallArea.vue's caller/receiver pair) rather than a new
           component. No :image is available for participants (Event
           Participants only carries an email, not a resolved User/Contact
           image), so these render as initials-only circles - which is what
           "small circular initials avatars" asked for anyway.
           meeting.event_participants shape same as before: defensively
           handled as a possibly-empty/undefined array. -->
      <MultipleAvatar
        v-if="participantAvatars.length"
        :avatars="participantAvatars"
        size="sm"
      />
    </div>
  </div>
</template>
<script setup>
import CalendarIcon from '@/components/Icons/CalendarIcon.vue'
import DurationIcon from '@/components/Icons/DurationIcon.vue'
import PhoneIcon from '@/components/Icons/PhoneIcon.vue'
import CameraIcon from '@/components/Icons/CameraIcon.vue'
import PeopleIcon from '@/components/Icons/PeopleIcon.vue'
import TimelineTimestamp from '@/components/Activities/TimelineTimestamp.vue'
import MultipleAvatar from '@/components/MultipleAvatar.vue'
import { formatDate } from '@/utils'
import { Badge, Dropdown, Button } from 'frappe-ui'
import { computed } from 'vue'

// Frappe core's actual Event.status options (verified against
// frappe/frappe's event.json rather than assumed) - "Open" is the
// upcoming/scheduled state, there is no literal "Rescheduled" status;
// rescheduling in frappe_appointment is an action (reschedule_url), not a
// status value.
const statusColorMap = {
  Open: 'blue',
  Completed: 'green',
  Closed: 'gray',
  Cancelled: 'red',
}

// meeting_type -> {icon, color}. Icon choices reuse real, existing icons
// from this app's Icons folder (confirmed via the base repo's actual file
// listing) rather than inventing new ones: PhoneIcon for call-shaped
// meetings, CameraIcon as the closest existing analog to a "video/Zoom"
// icon (no dedicated VideoIcon exists), PeopleIcon for the one clearly
// in-person type, CalendarIcon as the generic "Other" fallback. Colors for
// the 4 types shown in the reference screenshot's legend were matched to
// that legend (blue/green/orange/purple in that order); the other 4 types
// have no reference to match against, so their colors were chosen only to
// stay visually distinct from the first 4 and each other - not verified
// against any design source.
const meetingTypeMap = {
  'Property Viewing': { icon: PeopleIcon, color: '#3b82f6' },
  'Onboarding Call': { icon: PhoneIcon, color: '#22c55e' },
  'Follow-up Call': { icon: PhoneIcon, color: '#f97316' },
  'Negotiation Call': { icon: PhoneIcon, color: '#a855f7' },
  'Product Demo': { icon: CameraIcon, color: '#14b8a6' },
  'Technical Review': { icon: CameraIcon, color: '#ec4899' },
  'Introductory Meeting': { icon: PhoneIcon, color: '#6366f1' },
  Other: { icon: CalendarIcon, color: '#9ca3af' },
}

const props = defineProps({
  meeting: { type: Object, default: () => ({}) },
})

const meetingTypeInfo = computed(
  () => meetingTypeMap[props.meeting.meeting_type] || meetingTypeMap.Other,
)

const statusLabel = computed(() => __(props.meeting.status || 'Open'))

const timeRangeLabel = computed(() => {
  if (!props.meeting.starts_on) return ''
  if (props.meeting.all_day) return __('All day')
  const start = formatDate(props.meeting.starts_on, 'h:mm a')
  if (!props.meeting.ends_on) return start
  const end = formatDate(props.meeting.ends_on, 'h:mm a')
  return `${start} - ${end}`
})

const participantAvatars = computed(() => {
  const participants = props.meeting.event_participants
  if (!Array.isArray(participants)) return []
  return participants
    .map((p) => p.email || p.reference_docname)
    .filter(Boolean)
    .map((label) => ({ label, name: label }))
})

// STUB - see the Dropdown comment in the template above. Neither function
// calls any backend method; they exist only so the menu items have a
// no-op onClick rather than throwing.
function editMeeting() {}
function cancelMeeting() {}
</script>
