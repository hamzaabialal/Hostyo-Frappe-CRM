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
      v-if="meetings.loading && !allMeetings.length"
      class="flex flex-1 flex-col items-center justify-center gap-3 text-xl font-medium text-ink-gray-4"
    >
      <LoadingIndicator class="h-6 w-6" />
      <span>{{ __('Loading...') }}</span>
    </div>

    <div
      v-else-if="allMeetings.length"
      class="flex flex-1 flex-col gap-5 overflow-y-auto px-3 pb-3 sm:px-10 sm:pb-5"
    >
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
        <div class="text-sm font-medium text-ink-gray-5">{{ __('This Week') }}</div>
        <div class="flex flex-col gap-3">
          <MeetingArea
            v-for="meeting in groupedMeetings.thisWeek"
            :key="meeting.name"
            :meeting="meeting"
          />
        </div>
      </div>

      <div v-if="groupedMeetings.later.length" class="flex flex-col gap-2">
        <div class="text-sm font-medium text-ink-gray-5">{{ __('Later') }}</div>
        <div class="flex flex-col gap-3">
          <MeetingArea
            v-for="meeting in groupedMeetings.later"
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

      <!-- "Load More" rather than numbered pages - matches this CRM's own
           Leads/Deals list convention (frappe/crm's Leads.vue: a 20-row page
           fetched incrementally via a loadMore trigger, not paged
           numerically). hasMore is inferred from the last fetched page's
           length rather than a separate total-count query - simpler, and
           sufficient for a "is there more" check. -->
      <div v-if="hasMore" class="flex justify-center pt-1">
        <Button
          :label="__('Load More')"
          :loading="meetings.loading"
          @click="loadMore"
        />
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
      @booked="resetAndFetch"
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
import { computed, h, onMounted, ref } from 'vue'

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

// Pagination: 20 rows per page, fetched via "Load More" rather than
// numbered pages - matches this CRM's own Leads/Deals list convention
// (frappe/crm's Leads.vue: updatedPageCount defaults to 20, loaded
// incrementally). allMeetings accumulates every page fetched so far;
// meetings.data only ever holds the LATEST fetched page. hasMore is
// inferred from whether the last page came back full-sized, rather than a
// separate total-count query - simpler, and sufficient for a "load more or
// not" decision.
//
// auto:false + an explicit fetch on mount, same shape SMSBox.vue already
// uses for its own on-mount-only resource - params can't just be a static
// object here (start changes between pages), so each fetchPage() call
// passes its own params explicitly rather than relying on the resource's
// own stored params being re-read.
const PAGE_LENGTH = 20
const start = ref(0)
const allMeetings = ref([])
const hasMore = ref(false)

const meetings = createResource({
  url: 'crm.api.meetings.get_meetings',
  auto: false,
  onSuccess: (data) => {
    const page = data || []
    allMeetings.value = start.value === 0 ? page : [...allMeetings.value, ...page]
    hasMore.value = page.length === PAGE_LENGTH
  },
  // Distinct cache key from MeetingsCalendarView.vue's own ['meetings', ...]
  // - that view fetches this same endpoint unpaginated (it needs every
  // meeting in view for the calendar grid), so sharing a cache key would
  // mean whichever view fetches last overwrites the other's differently-
  // shaped data under the same shared resource.
  cache: props.docname ? ['meetings-list', props.docname] : ['meetings-list', 'all'],
})

function fetchPage() {
  meetings.fetch({
    ...(props.docname ? { reference_doctype: props.doctype, reference_name: props.docname } : {}),
    start: start.value,
    page_length: PAGE_LENGTH,
  })
}

function loadMore() {
  start.value += PAGE_LENGTH
  fetchPage()
}

// Called after a new booking - re-fetch from the top rather than append, so
// the just-booked meeting actually shows up in its correct group (it may
// belong in Today/This Week, ahead of everything already loaded).
function resetAndFetch() {
  start.value = 0
  allMeetings.value = []
  fetchPage()
}

onMounted(fetchPage)

// Plain JS Date comparison - no date library is a dependency in this repo
// (checked package.json directly; frappe-ui's own formatDate is used
// elsewhere purely for display formatting, not comparison logic).
//
// Bucket definitions:
// - past: starts_on before the start of today
// - today: starts_on falls on today's calendar date
// - thisWeek: tomorrow through 7 days from today (exclusive)
// - later: everything from 7 days out onward
//
// thisWeek is now capped (previously unbounded, flagged as an open decision
// - resolved: cap at 7 days, add a 4th "Later" section, no relabeling of
// the bucket names themselves needed since "thisWeek" was already accurate
// once capped).
const groupedMeetings = computed(() => {
  const groups = { today: [], thisWeek: [], later: [], past: [] }
  const data = allMeetings.value

  const now = new Date()
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const startOfTomorrow = new Date(startOfToday)
  startOfTomorrow.setDate(startOfToday.getDate() + 1)
  const weekCutoff = new Date(startOfToday)
  weekCutoff.setDate(startOfToday.getDate() + 7)

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
    } else if (startsOn < weekCutoff) {
      groups.thisWeek.push(meeting)
    } else {
      groups.later.push(meeting)
    }
  }

  return groups
})
</script>
