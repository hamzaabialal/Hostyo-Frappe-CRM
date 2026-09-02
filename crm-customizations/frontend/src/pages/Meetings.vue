<template>
  <LayoutHeader>
    <template #left-header>
      <!-- Plain heading, not ViewBreadcrumbs.vue - that component was only
           ever confirmed via fetching Calendar.vue (a file now known to be
           missing on the actual production server), never against any
           pre-existing, already-successfully-deployed file in this repo.
           Matches MeetingsListView.vue's own header text/style exactly. -->
      <div class="text-lg font-semibold text-ink-gray-9">{{ __('Meetings') }}</div>
    </template>
  </LayoutHeader>
  <div class="flex flex-1 flex-col overflow-hidden">
    <div class="flex items-center gap-1 px-3 pt-2.5 sm:px-10">
      <Button
        :variant="meetingsView == 'list' ? 'solid' : 'subtle'"
        :label="__('List')"
        size="sm"
        @click="meetingsView = 'list'"
      />
      <Button
        :variant="meetingsView == 'calendar' ? 'solid' : 'subtle'"
        :label="__('Calendar')"
        size="sm"
        @click="meetingsView = 'calendar'"
      />
    </div>
    <!-- No doctype/docname passed - global mode. MeetingsListView.vue/
         MeetingsCalendarView.vue now default both to '' rather than
         assuming 'CRM Lead', and only send reference_doctype/reference_name
         to get_meetings when a docname is actually present - see the
         comment on that prop change in either file for why. -->
    <MeetingsListView v-if="meetingsView == 'list'" />
    <MeetingsCalendarView v-else />
  </div>
</template>
<script setup>
import LayoutHeader from '@/components/LayoutHeader.vue'
import MeetingsListView from '@/components/Meetings/MeetingsListView.vue'
import MeetingsCalendarView from '@/components/Meetings/MeetingsCalendarView.vue'
import { Button } from 'frappe-ui'
import { ref } from 'vue'

const meetingsView = ref('list')
</script>
