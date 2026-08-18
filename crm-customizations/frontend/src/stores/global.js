import { defineStore } from 'pinia'
import { getCurrentInstance, ref } from 'vue'
import { call, toast } from 'frappe-ui'

export const globalStore = defineStore('crm-global', () => {
  const app = getCurrentInstance()
  const { $dialog, $socket } = app.appContext.config.globalProperties

  let callMethod = () => {}
  // Set the moment a call is placed so the Telnyx call popup can show the
  // lead's name right away, instead of waiting on the webhook/socket round-trip.
  const pendingCall = ref(null)

  function setMakeCall(value) {
    callMethod = value
  }

  function not_empty(v) {
    return v && String(v).trim().length > 0
  }

  // Work out which record the call belongs to from the current URL.
  //
  // The router is deliberately NOT imported here: global.js -> router.js ->
  // pages/*.vue -> global.js is a circular import, which can resolve to
  // undefined at runtime under Vite. Reading the path avoids that entirely
  // and gives the same value as the :leadId / :dealId route params.
  function getCallReference() {
    try {
      const match = window.location.pathname.match(/\/(leads|deals)\/([^/?#]+)/)
      if (!match) return { doctype: '', name: '' }

      const kind = match[1]
      const id = match[2]

      // /crm/leads/view/list is the list view, not a record
      if (id === 'view') return { doctype: '', name: '' }

      return {
        doctype: kind === 'leads' ? 'CRM Lead' : 'CRM Deal',
        name: decodeURIComponent(id),
      }
    } catch (e) {
      return { doctype: '', name: '' }
    }
  }

  // reference is optional: pass { doctype, name } explicitly to link a call
  // from a list view, otherwise it is derived from the open record.
  function makeCall(number, reference = null) {
    if (!not_empty(number)) {
      toast.error('No phone number available')
      return
    }

    const ref = reference || getCallReference()

    call('pbx_integration.telnyx.create_click2call', {
      to: number,
      reference_doctype: ref.doctype || '',
      reference_name: ref.name || '',
    })
      .then((res) => {
        pendingCall.value = {
          number,
          lead_name: res?.lead_name || '',
          reference_doctype: res?.reference_doctype || '',
          reference_docname: res?.reference_docname || '',
        }
        toast.success('Calling ' + number + ' - answer your softphone')
      })
      .catch((e) => {
        toast.error('Call failed: ' + (e.messages ? e.messages[0] : e))
      })
  }

  return {
    $dialog,
    $socket,
    makeCall,
    setMakeCall,
    pendingCall,
  }
})
