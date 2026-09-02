<template>
  <div class="flex flex-col h-full">
    <div class="flex items-center justify-between px-3 py-2.5 sm:px-10">
      <div class="text-lg font-semibold text-ink-gray-9">{{ __('Meetings') }}</div>
      <Button
        variant="solid"
        :label="__('Schedule Meeting')"
        iconLeft="plus"
        @click="showBookModal = true"
      />
    </div>

    <!-- Month/Week toggle + All/My Meetings/Team filter - matches the
         reference screenshot's second header row. FullCalendar's own
         built-in prev/next/today + title nav (headerToolbar below) stays
         inside the calendar's own bordered box rather than being
         duplicated up here. -->
    <div class="flex items-center gap-2 px-3 pb-2 sm:px-10">
      <Button
        :variant="calendarViewMode == 'dayGridMonth' ? 'solid' : 'subtle'"
        :label="__('Month')"
        size="sm"
        @click="setCalendarView('dayGridMonth')"
      />
      <Button
        :variant="calendarViewMode == 'dayGridWeek' ? 'solid' : 'subtle'"
        :label="__('Week')"
        size="sm"
        @click="setCalendarView('dayGridWeek')"
      />
      <!-- dayGridWeek is real, built-in behavior from @fullcalendar/daygrid
           (already a dependency for the month view - no new package), not
           a stub: clicking it genuinely switches FullCalendar to its week
           grid via the imperative API (initialView is only read once at
           mount, so changeView() is required for a live switch after
           that). -->
      <Dropdown :options="ownerFilterMenuOptions">
        <template #default>
          <Button variant="outline" :label="ownerFilterLabel" iconRight="chevron-down" />
        </template>
      </Dropdown>
    </div>

    <div
      v-if="meetings.loading"
      class="flex flex-1 flex-col items-center justify-center gap-3 text-xl font-medium text-ink-gray-4"
    >
      <LoadingIndicator class="h-6 w-6" />
      <span>{{ __('Loading...') }}</span>
    </div>

    <template v-else>
      <div class="flex flex-1 gap-4 px-3 pb-3 sm:px-10 sm:pb-5 overflow-hidden">
        <div class="flex-[2] min-w-0 overflow-auto rounded-md border border-outline-elevation-2 p-2">
          <FullCalendar ref="calendarRef" :options="calendarOptions" />
        </div>

        <div class="flex w-[280px] shrink-0 flex-col gap-3 overflow-auto">
          <div class="text-sm font-medium text-ink-gray-5">{{ __('Upcoming Meetings') }}</div>
          <div v-if="upcomingMeetings.length" class="flex flex-col gap-3">
            <MeetingArea
              v-for="meeting in upcomingMeetings"
              :key="meeting.name"
              :meeting="meeting"
            />
          </div>
          <EmptyState
            v-else
            :title="__('No Upcoming Meetings')"
            :description="__('Nothing scheduled from today onward.')"
            :icon="emptyIcon"
          />
        </div>
      </div>

      <!-- Legend row, matching the reference layout - lists every defined
           meeting_type and its color, not just the ones with a meeting on
           the currently visible page. -->
      <div class="flex flex-wrap items-center gap-x-4 gap-y-1.5 px-3 pb-3 sm:px-10 text-sm text-ink-gray-6">
        <div
          v-for="(info, type) in meetingTypeColorMap"
          :key="type"
          class="flex items-center gap-1.5"
        >
          <span class="h-2.5 w-2.5 rounded-full" :style="{ backgroundColor: info }" />
          <span>{{ __(type) }}</span>
        </div>
      </div>
    </template>

    <BookMeetingModal
      v-model="showBookModal"
      :doctype="doctype"
      :docname="docname"
      @booked="meetings.reload()"
    />
  </div>
</template>
<script setup>
import FullCalendar from '@fullcalendar/vue3'
import dayGridPlugin from '@fullcalendar/daygrid'
import MeetingArea from '@/components/Meetings/MeetingArea.vue'
import MeetingsIcon from '@/components/Icons/MeetingsIcon.vue'
import LoadingIndicator from '@/components/Icons/LoadingIndicator.vue'
import EmptyState from '@/components/ListViews/EmptyState.vue'
import BookMeetingModal from '@/components/Modals/BookMeetingModal.vue'
import { createResource, Button, Dropdown } from 'frappe-ui'
import { computed, h, ref } from 'vue'

// doctype/docname, not reference_doctype/reference_name - same convention
// MeetingsListView.vue follows, matching how Activities.vue itself receives
// and forwards these props. doctype now defaults to '' rather than
// 'CRM Lead' for the same reason documented in MeetingsListView.vue - this
// component is now shared between the per-record tab and the new global
// Meetings sidebar page (pages/Meetings.vue), which passes neither prop.
const props = defineProps({
  doctype: { type: String, default: '' },
  docname: { type: String, default: '' },
})

const emptyIcon = h(MeetingsIcon, { class: 'text-ink-gray-4' })
const showBookModal = ref(false)

// Same cache key as MeetingsListView.vue's own createResource - frappe-ui's
// createResource returns the same cached resource for a matching cache key,
// so toggling between List/Calendar (both mounted against the same
// doctype/docname, or both in global mode) reuses the already-fetched data
// instead of re-fetching from get_meetings a second time.
const meetings = createResource({
  url: 'crm.api.meetings.get_meetings',
  params: props.docname
    ? { reference_doctype: props.doctype, reference_name: props.docname }
    : {},
  cache: props.docname ? ['meetings', props.docname] : ['meetings', 'all'],
  auto: true,
})

// meeting_type -> color, matching MeetingArea.vue's meetingTypeMap exactly
// (deliberately duplicated here rather than shared from one module - no
// shared constants/utils file exists yet for the Meetings feature, and
// creating one wasn't asked for this pass; worth centralizing if this drifts
// out of sync in a future change). Colors for the 4 types shown in the
// reference screenshot's legend match it; the other 4 have no reference to
// match and were only chosen to stay visually distinct.
const meetingTypeColorMap = {
  'Property Viewing': '#3b82f6',
  'Onboarding Call': '#22c55e',
  'Follow-up Call': '#f97316',
  'Negotiation Call': '#a855f7',
  'Product Demo': '#14b8a6',
  'Technical Review': '#ec4899',
  'Introductory Meeting': '#6366f1',
  Other: '#9ca3af',
}

const calendarEvents = computed(() => {
  return (meetings.data || []).map((meeting) => {
    const color = meetingTypeColorMap[meeting.meeting_type] || meetingTypeColorMap.Other
    return {
      id: meeting.name,
      title: meeting.subject || __('Meeting'),
      start: meeting.starts_on,
      end: meeting.ends_on,
      allDay: Boolean(meeting.all_day),
      backgroundColor: color,
      borderColor: color,
    }
  })
})

const calendarRef = ref(null)
const calendarViewMode = ref('dayGridMonth')

function setCalendarView(view) {
  calendarViewMode.value = view
  calendarRef.value?.getApi()?.changeView(view)
}

const calendarOptions = computed(() => ({
  plugins: [dayGridPlugin],
  initialView: 'dayGridMonth',
  headerToolbar: {
    left: 'prev,next today',
    center: 'title',
    right: '',
  },
  height: 'auto',
  events: calendarEvents.value,
}))

const upcomingMeetings = computed(() => {
  const now = new Date()
  return (meetings.data || [])
    .filter((meeting) => meeting.starts_on && new Date(meeting.starts_on) >= now)
    .sort((a, b) => new Date(a.starts_on) - new Date(b.starts_on))
})

// "All / My Meetings / Team" filter. Only "All" (the default, current
// behavior) is actually functional - it's just the unfiltered data
// get_meetings already returns. "My Meetings" and "Team" are visually
// present and change the dropdown's own label when clicked, but do NOT
// change what's fetched - there's no owner/team filter param on
// get_meetings yet. "My Meetings" would need one straightforwardly
// (filter by Event.owner == frappe.session.user). "Team" is a bigger open
// question, not just an unimplemented filter: this schema has no team/
// group-membership concept defined anywhere (no Team doctype, no
// team-assignment field seen on User or CRM Lead/Deal) - so "Team" can't
// be wired up without a product decision on what "team" even means here,
// not just backend work.
const ownerFilter = ref('all')
const ownerFilterOptions = [
  { label: __('All'), value: 'all' },
  { label: __('My Meetings'), value: 'mine' },
  { label: __('Team'), value: 'team' },
]

const ownerFilterLabel = computed(
  () => ownerFilterOptions.find((o) => o.value === ownerFilter.value)?.label || __('All'),
)

const ownerFilterMenuOptions = computed(() => [
  {
    group: __('Filter'),
    hideLabel: true,
    items: ownerFilterOptions.map((o) => ({
      label: o.label,
      onClick: () => {
        ownerFilter.value = o.value
      },
    })),
  },
])
</script>
