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

    <div
      v-if="meetings.loading"
      class="flex flex-1 flex-col items-center justify-center gap-3 text-xl font-medium text-ink-gray-4"
    >
      <LoadingIndicator class="h-6 w-6" />
      <span>{{ __('Loading...') }}</span>
    </div>

    <div v-else-if="meetings.data?.length" class="flex flex-col gap-5 px-3 pb-3 sm:px-10 sm:pb-5">
      <div v-if="groupedMeetings.today.length" class="flex flex-col gap-2">
        <div class="text-sm font-medium text-ink-gray-5">{{ __('Today') }}</div>
        <div class="flex flex-col gap-3">
          <MeetingArea
            v-for="meeting in groupedMeetings.today"
            :key="meeting.name"
            :meeting="meeting"
          />
        </div>
      </div>

      <div v-if="groupedMeetings.thisWeek.length" class="flex flex-col gap-2">
        <div class="text-sm font-medium text-ink-gray-5">{{ __('Upcoming') }}</div>
        <div class="flex flex-col gap-3">
          <MeetingArea
            v-for="meeting in groupedMeetings.thisWeek"
            :key="meeting.name"
            :meeting="meeting"
          />
        </div>
      </div>

      <div v-if="groupedMeetings.past.length" class="flex flex-col gap-2">
        <div class="text-sm font-medium text-ink-gray-5">{{ __('Past') }}</div>
        <div class="flex flex-col gap-3">
          <MeetingArea
            v-for="meeting in groupedMeetings.past"
            :key="meeting.name"
            :meeting="meeting"
          />
        </div>
      </div>
    </div>

    <EmptyState
      v-else
      :title="__('No Meetings Found')"
      :description="__('No meetings have been scheduled yet.')"
      :icon="emptyIcon"
    />

    <!-- Known gap, not fixed here (out of this turn's file scope): in global
         mode (docname empty), this passes an empty doctype/docname through
         to BookMeetingModal.vue, whose submit calls crm.api.meetings.book_meeting
         - a function that still requires reference_doctype/reference_name
         (only get_meetings was asked to gain a global variant this round).
         Clicking "Schedule Meeting" from the new global Meetings page will
         currently fail there. Needs a follow-up decision: add a Lead/Deal
         picker to the modal for the global case, or make book_meeting's
         reference genuinely optional too. -->
    <BookMeetingModal
      v-model="showBookModal"
      :doctype="doctype"
      :docname="docname"
      @booked="meetings.reload()"
    />
  </div>
</template>
<script setup>
import MeetingArea from '@/components/Meetings/MeetingArea.vue'
import MeetingsIcon from '@/components/Icons/MeetingsIcon.vue'
import LoadingIndicator from '@/components/Icons/LoadingIndicator.vue'
import EmptyState from '@/components/ListViews/EmptyState.vue'
import BookMeetingModal from '@/components/Modals/BookMeetingModal.vue'
import { createResource, Button } from 'frappe-ui'
import { computed, h, ref } from 'vue'

// doctype/docname, not reference_doctype/reference_name - matches the prop
// names Activities.vue itself receives and passes down to its own child
// view/box components (SMSBox, DataFields, etc.), even though the backend
// method's own params are named reference_doctype/reference_name.
//
// doctype now defaults to '' rather than 'CRM Lead' - this component is now
// shared between the per-record Meetings tab (Activities.vue always passes
// real doctype/docname values there) and the new global Meetings sidebar
// page (pages/Meetings.vue, which passes neither). Defaulting doctype to
// 'CRM Lead' was harmless when only the per-record caller existed, but
// would be actively wrong here - it would make the "no reference" case
// silently look like a real, empty-named CRM Lead reference instead of
// "no reference at all". Whether to hit get_meetings in global vs
// per-record mode is decided below purely off whether docname is present.
const props = defineProps({
  doctype: { type: String, default: '' },
  docname: { type: String, default: '' },
})

const emptyIcon = h(MeetingsIcon, { class: 'text-ink-gray-4' })
const showBookModal = ref(false)

const meetings = createResource({
  url: 'crm.api.meetings.get_meetings',
  params: props.docname
    ? { reference_doctype: props.doctype, reference_name: props.docname }
    : {},
  cache: props.docname ? ['meetings', props.docname] : ['meetings', 'all'],
  auto: true,
})

// Plain JS Date comparison - no date library is a dependency in this repo
// (checked package.json directly; frappe-ui's own formatDate is used
// elsewhere purely for display formatting, not comparison logic).
//
// Bucket definitions:
// - past: starts_on before the start of today
// - today: starts_on falls on today's calendar date
// - thisWeek: everything from tomorrow onward
//
// The "thisWeek" bucket is, as implemented, actually unbounded upward - it
// is NOT clipped to the end of the current calendar week. There's no fourth
// "Later"/"Upcoming" section specified, and silently dropping meetings
// further out felt worse than a slightly imprecise label - a meeting three
// weeks out will still show, just grouped under "This Week". Worth deciding
// explicitly (add a real week upper-bound + a "Later" section, or rename
// this bucket) rather than something to leave as an unflagged assumption.
const groupedMeetings = computed(() => {
  const groups = { today: [], thisWeek: [], past: [] }
  const data = meetings.data || []

  const now = new Date()
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const startOfTomorrow = new Date(startOfToday)
  startOfTomorrow.setDate(startOfToday.getDate() + 1)

  for (const meeting of data) {
    if (!meeting.starts_on) {
      groups.thisWeek.push(meeting)
      continue
    }
    const startsOn = new Date(meeting.starts_on)
    if (startsOn < startOfToday) {
      groups.past.push(meeting)
    } else if (startsOn < startOfTomorrow) {
      groups.today.push(meeting)
    } else {
      groups.thisWeek.push(meeting)
    }
  }

  return groups
})
</script>
