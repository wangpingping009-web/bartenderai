import { createRouter, createWebHistory, createWebHashHistory } from 'vue-router'
import { useAuthStore } from './stores/auth'

const routes = [
  { path: '/login', name: 'login', component: () => import('./views/AuthView.vue'), meta: { public: true } },
  { path: '/verify', name: 'verify', component: () => import('./views/VerifyView.vue'), meta: { public: true } },
  { path: '/reset-password', name: 'reset', component: () => import('./views/ResetPasswordView.vue'), meta: { public: true } },
  { path: '/', redirect: '/chat' },
  { path: '/chat', component: () => import('./views/ChatView.vue'), meta: { title: 'AI 调酒台' } },
  { path: '/explore', component: () => import('./views/ExploreView.vue'), meta: { title: '配方探索' } },
  { path: '/recipes/:id', component: () => import('./views/RecipeDetailView.vue'), meta: { title: '配方详情' } },
  { path: '/studio', component: () => import('./views/StudioView.vue'), meta: { title: 'AI 创作室' } },
  { path: '/studio/creations/:id', component: () => import('./views/CreationDetailView.vue'), meta: { title: '原创配方' } },
  { path: '/lab', component: () => import('./views/LabView.vue'), meta: { title: '配方实验室' } },
  { path: '/inventory', component: () => import('./views/InventoryView.vue'), meta: { title: '我的酒柜' } },
  { path: '/moments', component: () => import('./views/MomentsView.vue'), meta: { title: '场景酒单' } },
  { path: '/vision', component: () => import('./views/VisionView.vue'), meta: { title: '拍照识方' } },
  { path: '/me', component: () => import('./views/ProfileView.vue'), meta: { title: '收藏与个人中心' } },
  { path: '/admin', component: () => import('./views/AdminView.vue'), meta: { title: 'AI 控制台', admin: true } },
  { path: '/:pathMatch(.*)*', redirect: '/chat' },
]
const isDemo = import.meta.env.MODE === 'demo'
const demoRoutes = [
  { path: '/', redirect: '/explore' },
  ...routes.filter(route => ['/explore', '/recipes/:id'].includes(route.path)),
  { path: '/:pathMatch(.*)*', redirect: '/explore' },
]
const router = createRouter({
  history: isDemo ? createWebHashHistory(import.meta.env.BASE_URL) : createWebHistory(),
  routes: isDemo ? demoRoutes : routes,
  scrollBehavior: () => ({ top: 0 }),
})
router.beforeEach((to) => {
  if (isDemo) {
    document.title = `${to.meta.title || '在线演示'} · BartenderAI`
    return
  }
  const auth = useAuthStore()
  if (!to.meta.public && !auth.authenticated) return { name: 'login', query: { next: to.fullPath } }
  if (to.meta.admin && !auth.isAdmin) return '/chat'
  if (to.name === 'login' && auth.authenticated) return '/chat'
  document.title = `${to.meta.title || 'BartenderAI'} · BartenderAI`
})
export default router
