import { createRouter, createWebHistory } from 'vue-router'

import Overview from '@/views/Overview.vue'
import WorkbenchView from '@/views/WorkbenchView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'overview', component: Overview },
    { path: '/file_intake/import', name: 'file-intake-import', component: WorkbenchView, props: { moduleKey: 'file_intake' } },
    { path: '/file_intake/manifests', name: 'file-intake-manifests', component: WorkbenchView, props: { moduleKey: 'file_intake' } },
    { path: '/:moduleKey', name: 'module', component: WorkbenchView, props: true },
  ],
})

export default router
