import { createRouter, createWebHistory } from 'vue-router'
import WizardView from '@/views/WizardView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'wizard',
      component: WizardView,
    },
  ],
})

export default router
