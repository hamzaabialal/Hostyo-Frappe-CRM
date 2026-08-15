<template>
  <div class="flex items-end gap-2 px-3 py-2.5 sm:px-10" v-bind="$attrs">
    <div class="flex h-8 items-center gap-2">
      <Dropdown :options="templateOptions">
        <FeatherIcon
          name="file-text"
          class="size-4.5 cursor-pointer text-ink-gray-5"
        />
      </Dropdown>
    </div>
    <Textarea
      ref="textareaRef"
      v-model="content"
      type="textarea"
      class="min-h-8 w-full"
      :rows="rows"
      :placeholder="__('Type your SMS here...')"
      @focus="rows = 6"
      @blur="rows = 1"
      @keydown.enter.stop="(e) => sendTextMessage(e)"
    />
  </div>
</template>

<script setup>
import { Textarea, Dropdown, createResource, toast } from 'frappe-ui'
import { ref, nextTick, onMounted, computed } from 'vue'

const props = defineProps({
  doctype: { type: String, default: '' },
})

const doc = defineModel({ type: Object, default: () => ({}) })
const sms = defineModel('sms', { type: Object, default: () => ({}) })

const rows = ref(1)
const textareaRef = ref(null)
const content = ref('')

function show() {
  nextTick(() => textareaRef.value.el.focus())
}

const templates = createResource({
  url: 'whatsapp_integration.api.get_sms_templates',
  auto: false,
})

onMounted(() => templates.fetch())

const templateOptions = computed(() => {
  const list = templates.data || []
  if (!list.length) {
    return [{ label: __('No templates found'), onClick: () => {} }]
  }
  return list.map((t) => ({
    label: t.title,
    onClick: () => {
      content.value = t.message
      nextTick(() => textareaRef.value?.el?.focus())
    },
  }))
})

function sendTextMessage(event) {
  if (event.shiftKey) return
  sendSMSMessage()
  textareaRef.value.el?.blur()
}

function getPhoneNumber() {
  if (props.doctype === 'CRM Deal') {
    return doc.value.primaryContact?.mobile_no || ''
  }
  return doc.value.mobile_no || doc.value.phone
}

async function sendSMSMessage() {
  const to = getPhoneNumber()
  if (!to) {
    toast.error(__('No phone number found on this record'))
    return
  }
  if (!content.value?.trim()) {
    toast.error(__('Please write a message'))
    return
  }

  let args = {
    reference_doctype: props.doctype,
    reference_name: doc.value.name,
    message: content.value,
    to: to,
  }
  const sentMessage = content.value
  content.value = ''

  createResource({
    url: 'whatsapp_integration.api.create_sms_message',
    params: args,
    auto: true,
    onSuccess: () => sms.value.reload(),
    onError: (error) => {
      content.value = sentMessage
      sms.value.reload()
      toast.error(error.messages?.[0] || __('Failed to send SMS message'))
    },
  })
}

defineExpose({ show })
</script>
