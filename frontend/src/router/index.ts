import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '@/views/HomeView.vue'
import CaseDetailView from '@/views/CaseDetailView.vue'
import WizardView from '@/views/WizardView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'home',
      component: HomeView,
    },
    {
      path: '/cases/:caseId',
      name: 'case-detail',
      component: CaseDetailView,
    },
    // 舊的離線示範流程（走舊後端 /api/*）保留但不再是首頁，見協作設計 06 §6.4。
    {
      path: '/legacy-demo',
      name: 'wizard',
      component: WizardView,
    },
  ],
})

export default router
