import { createResource } from 'frappe-ui'
import { ref } from 'vue'

export const meetingsEnabled = ref(false)

createResource({
  url: 'crm.api.meetings.is_meetings_enabled',
  cache: 'Is Meetings Enabled',
  auto: true,
  onSuccess: (data) => {
    meetingsEnabled.value = Boolean(data)
  },
})
