import { createRouter, createWebHistory } from 'vue-router'
import { usersStore } from '@/stores/users'
import { sessionStore } from '@/stores/session'
import { viewsStore } from '@/stores/views'

const routes = [
  {
    path: '/',
    name: 'Home',
  },
  {
    path: '/notifications',
    name: 'Notifications',
    component: () => import('@/pages/MobileNotification.vue'),
  },
  {
    path: '/dashboard',
    name: 'Dashboard',
    component: () => import('@/pages/Dashboard.vue'),
  },
  {
    alias: '/leads',
    path: '/leads/view/:viewType?',
    name: 'Leads',
    component: () => import('@/pages/Leads.vue'),
  },
  {
    path: '/leads/:leadId',
    name: 'Lead',
    component: () => import(`@/pages/${handleMobileView('Lead')}.vue`),
    props: true,
  },
  {
    alias: '/deals',
    path: '/deals/view/:viewType?',
    name: 'Deals',
    component: () => import('@/pages/Deals.vue'),
  },
  {
    path: '/deals/:dealId',
    name: 'Deal',
    component: () => import(`@/pages/${handleMobileView('Deal')}.vue`),
    props: true,
  },
  {
    alias: '/notes',
    path: '/notes/view/:viewType?',
    name: 'Notes',
    component: () => import('@/pages/Notes.vue'),
  },
  {
    alias: '/tasks',
    path: '/tasks/view/:viewType?',
    name: 'Tasks',
    component: () => import('@/pages/Tasks.vue'),
  },
  {
    alias: '/contacts',
    path: '/contacts/view/:viewType?',
    name: 'Contacts',
    component: () => import('@/pages/Contacts.vue'),
  },
  {
    path: '/contacts/:contactId',
    name: 'Contact',
    component: () => import(`@/pages/${handleMobileView('Contact')}.vue`),
    props: true,
  },
  {
    alias: '/organizations',
    path: '/organizations/view/:viewType?',
    name: 'Organizations',
    component: () => import('@/pages/Organizations.vue'),
  },
  {
    path: '/organizations/:organizationId',
    name: 'Organization',
    component: () => import(`@/pages/${handleMobileView('Organization')}.vue`),
    props: true,
  },
  {
    alias: '/call-logs',
    path: '/call-logs/view/:viewType?',
    name: 'Call Logs',
    component: () => import('@/pages/CallLogs.vue'),
  },
  {
    // Hostyo customization: top-level "Meetings" sidebar section (CRM
    // meetings booked via frappe_appointment, linked to Leads/Deals).
    //
    // The stock /calendar route that normally sits here (name: 'Calendar',
    // component: @/pages/Calendar.vue) was DELIBERATELY REMOVED from this
    // file, not just left out - the production deploy that included the
    // full-upstream-develop version of this file failed with:
    //   ENOENT: no such file or directory,
    //   open '.../apps/crm/frontend/src/pages/Calendar.vue'
    // Investigated before assuming anything: found the exact upstream
    // frappe/crm commit matching this fork's own frappe-ui pin
    // (0.1.261 in package.json/yarn.lock - commit bf7fc05e40, the commit
    // that bumped frappe-ui to that exact version, one hour after
    // frappe-ui@0.1.261 itself was published) and confirmed Calendar.vue
    // existed continuously in frappe/crm's own history for the entire
    // month-plus window where their package.json also pinned frappe-ui to
    // 0.1.261 (until the next bump, a97626ea4e). So this isn't a
    // wrong-upstream-version problem - at the exact dependency version this
    // fork matches, upstream always had this file. The most likely
    // explanation is that Calendar.vue was removed directly on this
    // specific server at some point outside of any git history I have
    // access to (this deploy pipeline never updates the base crm app's own
    // files - only crm-customizations' and pbx_integration's - so the base
    // app's actual file tree here is whatever it was at original install,
    // plus whatever's changed on it since, none of which is tracked
    // anywhere I can inspect without server access). Given that, the safe
    // fix is to not depend on this file's existence at all, rather than
    // guess at which upstream version might or might not have it.
    //
    // The rest of this file's routes/beforeEach logic were also rebuilt
    // from that same verified bf7fc05e40 commit rather than kept from
    // develop's current (much newer/more complex) version - develop's
    // beforeEach relies on usersStore functions (isCrmUser, isAdminUser)
    // and a persona-capture flow that don't exist at this fork's actual
    // dependency era (bf7fc05e40 uses isWebsiteUser() instead) - keeping
    // develop's newer logic risked a second, less obvious failure (a
    // missing named export, which Vite/Rollup can also fail the build on)
    // on top of the Calendar.vue one.
    path: '/meetings',
    name: 'Meetings',
    component: () => import('@/pages/Meetings.vue'),
  },
  {
    path: '/data-import',
    name: 'DataImportList',
    component: () => import('@/pages/DataImport.vue'),
  },
  {
    path: '/data-import/doctype/:doctype',
    name: 'NewDataImport',
    component: () => import('@/pages/DataImport.vue'),
    props: true,
  },
  {
    path: '/data-import/:importName',
    name: 'DataImport',
    component: () => import('@/pages/DataImport.vue'),
    props: true,
  },
  {
    path: '/welcome',
    name: 'Welcome',
    component: () => import('@/pages/Welcome.vue'),
  },
  {
    path: '/:invalidpath',
    name: 'Invalid Page',
    component: () => import('@/pages/InvalidPage.vue'),
  },
  {
    path: '/not-permitted',
    name: 'Not Permitted',
    component: () => import('@/pages/NotPermitted.vue'),
  },
]

const handleMobileView = (componentName) => {
  return window.innerWidth < 768 ? `Mobile${componentName}` : componentName
}

let router = createRouter({
  history: createWebHistory('/crm'),
  routes,
})

router.beforeEach(async (to, from, next) => {
  const { isLoggedIn } = sessionStore()
  const { users, isWebsiteUser } = usersStore()

  if (isLoggedIn && !users.fetched) {
    try {
      await users.promise
    } catch (error) {
      console.error('Error loading users', error)
    }
  }

  if (isLoggedIn && to.name !== 'Not Permitted' && isWebsiteUser()) {
    next({ name: 'Not Permitted' })
  } else if (to.name === 'Home' && isLoggedIn) {
    const { views, getDefaultView } = viewsStore()
    await views.promise

    let defaultView = getDefaultView()
    if (!defaultView) {
      next({ name: 'Leads' })
      return
    }

    let { route_name, type, name, is_standard } = defaultView
    route_name = route_name || 'Leads'

    if (name && !is_standard) {
      next({
        name: route_name,
        params: { viewType: type },
        query: { view: name },
      })
    } else {
      next({ name: route_name, params: { viewType: type } })
    }
  } else if (!isLoggedIn) {
    window.location.href = '/login?redirect-to=/crm'
  } else if (to.matched.length === 0) {
    next({ name: 'Invalid Page' })
  } else if (['Deal', 'Lead'].includes(to.name) && !to.hash) {
    let storageKey = to.name === 'Deal' ? 'lastDealTab' : 'lastLeadTab'
    const activeTab = localStorage.getItem(storageKey) || 'activity'
    const hash = '#' + activeTab
    next({ ...to, hash })
  } else {
    next()
  }
})

export default router
