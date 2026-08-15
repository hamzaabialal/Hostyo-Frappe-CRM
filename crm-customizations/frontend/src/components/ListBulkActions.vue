<template>
  <EditValueModal
    v-if="showEditModal"
    v-model="showEditModal"
    :doctype="doctype"
    :selectedValues="selectedValues"
    @reload="reload"
  />

  <AssignmentModal
    v-if="showAssignmentModal"
    v-model="showAssignmentModal"
    v-model:assignees="bulkAssignees"
    :docs="selectedValues"
    :doctype="doctype"
    @reload="reload"
  />

  <!-- ❌ DELETE MODALS REMOVED (to fix build errors) -->

  <!-- ================= WHATSAPP MODAL ================= -->
  <div
    v-if="showWhatsAppModal"
    class="fixed inset-0 bg-black/40 flex items-center justify-center z-50"
  >
    <div class="bg-white w-[500px] p-5 rounded-lg shadow-lg">

      <h2 class="text-lg font-bold mb-3">Send WhatsApp Message</h2>

      <div class="text-sm text-gray-500 mb-2">
        {{ selectedLeads.length }} lead(s) selected
      </div>

      <textarea
        v-model="whatsappMessage"
        rows="6"
        placeholder="Type your message..."
        class="w-full border p-2 rounded"
      ></textarea>

      <div class="flex justify-end gap-2 mt-4">
        <button
          class="px-3 py-1 border rounded"
          @click="showWhatsAppModal = false"
        >
          Cancel
        </button>

        <button
          class="px-3 py-1 bg-green-600 text-white rounded"
          @click="sendWhatsAppMessage"
        >
          Send
        </button>
      </div>

    </div>
  </div>
</template>

<script setup>
import EditValueModal from '@/components/Modals/EditValueModal.vue'
import AssignmentModal from '@/components/Modals/AssignmentModal.vue'

import { setupListCustomizations } from '@/utils'
import { globalStore } from '@/stores/global'
import { useTelemetry } from 'frappe-ui/frappe'
import { call, toast } from 'frappe-ui'
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'

/* ================= PROPS ================= */
const props = defineProps({
  doctype: { type: String, default: '' },
  options: {
    type: Object,
    default: () => ({
      hideEdit: false,
      hideDelete: false,
      hideAssign: false,
    }),
  },
})

const list = defineModel({ type: Object })
const router = useRouter()

const { $dialog, $socket } = globalStore()
const { capture } = useTelemetry()

/* ================= STATE ================= */
const showEditModal = ref(false)
const selectedValues = ref([])
const unselectAllAction = ref(() => {})

const showAssignmentModal = ref(false)
const bulkAssignees = ref([])

/* ================= WHATSAPP STATE ================= */
const showWhatsAppModal = ref(false)
const whatsappMessage = ref('')
const selectedLeads = ref([])

/* ================= EDIT ================= */
function editValues(selections, unselectAll) {
  selectedValues.value = selections
  showEditModal.value = true
  unselectAllAction.value = unselectAll
}

/* ================= WHATSAPP ================= */
function openWhatsAppModal(selections, unselectAll) {
  selectedLeads.value = Array.from(selections)
  whatsappMessage.value = ''
  showWhatsAppModal.value = true
  unselectAllAction.value = unselectAll
}

function sendWhatsAppMessage() {
  selectedLeads.value.forEach((name) => {
    call('whatsapp_integration.api.send_whatsapp', {
      lead: name,
      message: whatsappMessage.value,
    })
  })

  toast.success(__('WhatsApp sent'))

  showWhatsAppModal.value = false
  whatsappMessage.value = ''

  list.value?.reload()
}

/* ================= DELETE (SAFE SIMPLE VERSION) ================= */
function deleteValues(selections, unselectAll) {
  $dialog({
    title: __('Delete'),
    message: __('Are you sure you want to delete selected records?'),
    actions: [
      {
        label: __('Delete'),
        onClick: (close) => {
          selections.forEach((name) => {
            call('frappe.client.delete', {
              doctype: props.doctype,
              name,
            })
          })

          toast.success(__('Deleted'))
          reload(unselectAll)
          close()
        },
      },
    ],
  })
}

/* ================= ASSIGN ================= */
function assignValues(selections, unselectAll) {
  showAssignmentModal.value = true
  selectedValues.value = selections
  unselectAllAction.value = unselectAll
}

/* ================= CLEAR ASSIGN ================= */
function clearAssignments(selections, unselectAll) {
  $dialog({
    title: __('Clear Assignment'),
    message: __('Clear assignments?'),
    actions: [
      {
        label: __('Clear'),
        onClick: (close) => {
          call('frappe.desk.form.assign_to.remove_multiple', {
            doctype: props.doctype,
            names: JSON.stringify(Array.from(selections)),
          }).then(() => {
            toast.success(__('Cleared'))
            reload(unselectAll)
            close()
          })
        },
      },
    ],
  })
}

/* ================= BULK ACTIONS ================= */
function bulkActions(selections, unselectAll) {
  let actions = []

  if (!props.options.hideEdit) {
    actions.push({
      label: __('Edit'),
      onClick: () => editValues(selections, unselectAll),
    })
  }

  if (!props.options.hideDelete) {
    actions.push({
      label: __('Delete'),
      onClick: () => deleteValues(selections, unselectAll),
    })
  }

  if (!props.options.hideAssign) {
    actions.push({
      label: __('Assign To'),
      onClick: () => assignValues(selections, unselectAll),
    })

    actions.push({
      label: __('Clear Assignment'),
      onClick: () => clearAssignments(selections, unselectAll),
    })
  }

  if (props.doctype === 'CRM Lead') {
    actions.push({
      label: __('WhatsApp'),
      onClick: () => openWhatsAppModal(selections, unselectAll),
    })
  }

  return actions
}

/* ================= RELOAD ================= */
function reload(unselectAll) {
  unselectAllAction.value?.()
  unselectAll?.()
  list.value?.reload()
}

/* ================= CUSTOMIZATION ================= */
const customBulkActions = ref([])

onMounted(async () => {
  if (!list.value?.data) return

  let customization = await setupListCustomizations(list.value.data, {
    list: list.value,
    call,
    toast,
    $dialog,
    $socket,
    router,
  })

  customBulkActions.value =
    customization?.bulkActions || list.value?.data?.bulkActions || []
})

defineExpose({
  bulkActions,
})
</script>
