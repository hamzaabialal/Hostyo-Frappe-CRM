<template>
  <Dialog
    v-model="show"
    :options="{ title: __('Schedule Meeting'), size: 'lg' }"
  >
    <template #body-content>
      <div class="flex flex-col gap-4">
        <!-- Only shown in global mode (modal opened with no docname - the
             new sidebar Meetings page). The existing per-record flow
             (opened from a Lead/Deal's own Meetings tab) already knows its
             reference via props and skips this entirely - no behavior
             change there. -->
        <div v-if="isGlobalMode" class="flex flex-col gap-1.5">
          <label class="block text-xs text-ink-gray-5">{{ __('Lead / Deal') }}</label>
          <div class="flex gap-2">
            <Button
              :variant="pickerDoctype == 'CRM Lead' ? 'solid' : 'subtle'"
              :label="__('Lead')"
              size="sm"
              @click="setPickerDoctype('CRM Lead')"
            />
            <Button
              :variant="pickerDoctype == 'CRM Deal' ? 'solid' : 'subtle'"
              :label="__('Deal')"
              size="sm"
              @click="setPickerDoctype('CRM Deal')"
            />
          </div>
          <!-- Reusing Controls/Link.vue (already used elsewhere in this app,
               e.g. Deal.vue's contact picker) rather than building a new
               search component - it wraps Autocomplete against
               frappe.desk.search.search_link and its `doctype` prop is
               reactive, so switching the Lead/Deal toggle above re-searches
               against the right doctype automatically. One thing confirmed
               by reading its actual source rather than assuming: it renders
               nothing on its own - the #target slot below is required to
               get a visible, clickable field at all. Its v-model only ever
               exposes the picked record's plain name/docname, not a
               friendly title - showing the raw picked value below is a
               deliberate simplification, not an oversight; resolving a
               display label would need an extra lookup this task didn't
               ask for. -->
          <Link :doctype="pickerDoctype" v-model="pickerValue">
            <template #target="{ togglePopover }">
              <Button
                class="w-full !justify-start"
                variant="outline"
                @click="togglePopover()"
              >
                {{
                  pickerValue ||
                  __('Search {0}...', [pickerDoctype == 'CRM Lead' ? __('Lead') : __('Deal')])
                }}
              </Button>
            </template>
          </Link>
        </div>

        <div class="grid grid-cols-2 gap-4">
          <FormControl
            type="date"
            :label="__('Date')"
            v-model="form.date"
          />
          <FormControl
            type="time"
            :label="__('Start Time')"
            v-model="form.start_time"
          />
        </div>

        <!-- Options come from get_available_durations (organizer's real
             Appointment Slot Duration rows) - selecting one sets both
             form.duration_id (the FK frappe_appointment actually needs) and
             the row's own duration (seconds) used for computeEndTime(),
             from the same source. Replaces the old pairing of a hardcoded
             15/30/45/60-minute select with zero connection to real data,
             plus a separate free-text "Duration Slot ID" field the user had
             to know and type by hand (including two rows with
             auto-generated hash names, created via the Desk UI - not
             something anyone could reliably remember or retype). -->
        <FormControl
          type="select"
          :label="__('Duration')"
          v-model="form.duration_id"
          :options="durationOptions"
          :disabled="availableDurations.loading"
        />

        <FormControl
          type="select"
          :label="__('Meeting Type')"
          v-model="form.meeting_type"
          :options="meetingTypeOptions"
        />

        <div class="grid grid-cols-2 gap-4">
          <FormControl
            type="text"
            :label="__('Guest Name')"
            v-model="form.user_name"
          />
          <FormControl
            type="text"
            :label="__('Guest Email')"
            v-model="form.user_email"
          />
        </div>

        <FormControl
          type="text"
          :label="__('Additional Participants')"
          v-model="form.other_participants"
          :placeholder="__('comma-separated emails')"
        />

        <div v-if="errorMessage" class="text-sm text-ink-red-4">
          {{ errorMessage }}
        </div>
      </div>
    </template>
    <template #actions>
      <Button
        variant="solid"
        :label="__('Schedule')"
        :loading="bookMeeting.loading"
        @click="submit"
      />
    </template>
  </Dialog>
</template>
<script setup>
import Link from '@/components/Controls/Link.vue'
import { createResource, Dialog, FormControl, Button } from 'frappe-ui'
import { reactive, ref, computed, watch } from 'vue'

const props = defineProps({
  doctype: { type: String, default: 'CRM Lead' },
  docname: { type: String, default: '' },
})

const emit = defineEmits(['booked'])

const show = defineModel({ type: Boolean })

// Global mode: no docname was passed in (the sidebar Meetings page renders
// this modal that way) - the reference has to be picked manually instead of
// already being known from props.
const isGlobalMode = computed(() => !props.docname)

const pickerDoctype = ref('CRM Lead')
const pickerValue = ref('')

function setPickerDoctype(doctype) {
  pickerDoctype.value = doctype
  // A picked Lead's name isn't a valid Deal name (and vice versa) - clear
  // rather than carry a stale, wrong-doctype value across the switch.
  pickerValue.value = ''
}

// The reference actually sent to book_meeting - props in per-record mode
// (unchanged from before), the manual picker's selection in global mode.
// book_meeting itself still requires both, per instruction: every meeting
// stays tied to a real Lead/Deal, whether resolved automatically or by hand.
const effectiveReferenceDoctype = computed(() =>
  isGlobalMode.value ? pickerDoctype.value : props.doctype,
)
const effectiveReferenceName = computed(() =>
  isGlobalMode.value ? pickerValue.value : props.docname,
)

// Fetched once (auto: true), same "load once, cheap to keep around" shape
// composables/meetings.js already uses for is_meetings_enabled - this
// modal instance stays mounted across opens (see the show watcher below),
// so there's no need to re-fetch on every open; an organizer's configured
// durations aren't expected to change mid-session.
const availableDurations = createResource({
  url: 'crm.api.meetings.get_available_durations',
  auto: true,
})

// { label, value } for the "Duration" select, sourced from the organizer's
// real Appointment Slot Duration rows instead of the old hardcoded
// 15/30/45/60-minute list. value is each row's own name (its
// duration_id) - some of these are auto-generated hashes (created via the
// Desk UI, not console), never assumed readable, always taken from the
// API response itself.
const durationOptions = computed(() =>
  (availableDurations.data || []).map((row) => ({ label: row.title, value: row.name })),
)

// The selected row's own duration, in seconds as returned by
// get_available_durations (Frappe's standard Duration fieldtype storage
// unit - not minutes) - used by computeEndTime() below instead of the old
// form.duration_minutes * 60 math, so the end time actually sent always
// matches the real duration of whatever Appointment Slot Duration
// duration_id points at, rather than two separate, independently-editable
// fields that could disagree.
const selectedDurationSeconds = computed(() => {
  const row = (availableDurations.data || []).find((r) => r.name === form.duration_id)
  return row ? row.duration : 0
})

// Same 8 options as the meeting_type Custom Field itself
// (crm/patches/v1_0/add_meeting_type_field.py) - kept in sync manually
// since the field's options live in a Python patch, not something the
// frontend can introspect at runtime here.
const meetingTypeOptions = [
  { label: __('Property Viewing'), value: 'Property Viewing' },
  { label: __('Onboarding Call'), value: 'Onboarding Call' },
  { label: __('Follow-up Call'), value: 'Follow-up Call' },
  { label: __('Negotiation Call'), value: 'Negotiation Call' },
  { label: __('Product Demo'), value: 'Product Demo' },
  { label: __('Technical Review'), value: 'Technical Review' },
  { label: __('Introductory Meeting'), value: 'Introductory Meeting' },
  { label: __('Other'), value: 'Other' },
]

const form = reactive({
  date: '',
  start_time: '',
  duration_id: '',
  user_name: '',
  user_email: '',
  other_participants: '',
  meeting_type: '',
})

const errorMessage = ref('')

// Reset picker/error state each time the modal reopens, so a previous
// global booking's picked Lead/Deal (or a stale error message) doesn't
// silently carry over into the next one.
watch(show, (value) => {
  if (!value) return
  errorMessage.value = ''
  if (isGlobalMode.value) {
    pickerDoctype.value = 'CRM Lead'
    pickerValue.value = ''
  }
})

// book_time_slot's HH:mm:ss end_time is computed client-side from
// date + start_time + the selected duration's own length in seconds - the
// backend takes start_time/end_time as fully independent literal params
// (confirmed against its actual source), it doesn't derive one from
// duration_id itself. Requires a real selected duration (no default
// preselected, since the options load asynchronously) - returns '' until
// one's actually picked, same as the missing-date/start_time cases below.
function computeEndTime() {
  if (!form.date || !form.start_time || !selectedDurationSeconds.value) return ''
  const start = new Date(`${form.date}T${form.start_time}`)
  if (Number.isNaN(start.getTime())) return ''
  const end = new Date(start.getTime() + selectedDurationSeconds.value * 1000)
  return end.toTimeString().slice(0, 8)
}

const bookMeeting = createResource({
  url: 'crm.api.meetings.book_meeting',
  auto: false,
})

function submit() {
  errorMessage.value = ''

  const end_time = computeEndTime()
  if (!form.date || !form.start_time || !end_time || !form.duration_id || !form.user_email) {
    errorMessage.value = __('Date, start time, duration, and guest email are required.')
    return
  }
  if (!effectiveReferenceName.value) {
    errorMessage.value = __('Please select a Lead or Deal for this meeting.')
    return
  }

  bookMeeting.submit(
    {
      duration_id: form.duration_id,
      date: form.date,
      start_time: form.start_time,
      end_time,
      // Sent unmodified, on purpose - meetings.py's _local_to_utc_iso()
      // relies on exactly this raw JS convention (minutes, POSITIVE when
      // the local zone is BEHIND UTC) to convert the picked date/time to
      // UTC before it reaches book_time_slot. Confirmed against
      // frappe_appointment's source - see that function's docstring for
      // the full sign-convention writeup (including a separate, unrelated
      // mismatch inside frappe_appointment's own slot-validation code, that
      // this value is NOT flipped to work around). Do not negate this.
      user_timezone_offset: String(new Date().getTimezoneOffset()),
      user_name: form.user_name,
      user_email: form.user_email,
      reference_doctype: effectiveReferenceDoctype.value,
      reference_name: effectiveReferenceName.value,
      other_participants: form.other_participants || null,
      meeting_type: form.meeting_type || null,
    },
    {
      onSuccess: (data) => {
        // book_meeting passes frappe_appointment's response through as-is,
        // and that can be a plain dict OR a (dict, status_code) tuple
        // (confirmed for at least one error path in its own source) - and
        // whether @add_response_code's wrapping changes that shape again
        // before it reaches here wasn't confirmed either. Handled
        // defensively: an array-shaped response is treated as [body, status],
        // and either an explicit "error" key or a non-2xx status is treated
        // as a failure even though the HTTP call itself "succeeded".
        const [body, status] = Array.isArray(data) ? data : [data, 200]
        if (body?.error || (status && status >= 300)) {
          errorMessage.value = body?.error || body?.message || __('Failed to schedule meeting.')
          return
        }
        show.value = false
        emit('booked')
      },
      onError: (err) => {
        // Same defensiveness applied to the failure path - don't assume
        // err.messages exists just because that's the common Frappe
        // exception shape elsewhere in this app.
        errorMessage.value =
          err?.messages?.[0] || err?.message || __('Failed to schedule meeting. Please try again.')
      },
    },
  )
}
</script>
