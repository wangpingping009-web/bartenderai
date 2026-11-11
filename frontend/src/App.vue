<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from './stores/auth'
import { api } from './api'
import { CAPABILITIES_EVENT, llmStatusLabel } from './capabilities'
import MixologyAtmosphere from './components/MixologyAtmosphere.vue'
import { Bot, BookOpen, FlaskConical, GlassWater, LayoutDashboard, LogOut, ScanLine, Sparkles, UserRound, Wine, WandSparkles } from 'lucide-vue-next'

const auth = useAuthStore(), route = useRoute(), router = useRouter()
const isDemo = import.meta.env.MODE === 'demo'
const capabilities = ref(null)
const publicPage = computed(() => route.meta.public)
const navigation = computed(() => isDemo ? [
  { to: '/explore', label: '配方探索', icon: BookOpen },
] : [
  { to: '/chat', label: 'AI 调酒台', icon: Bot }, { to: '/explore', label: '配方探索', icon: BookOpen },
  { to: '/studio', label: 'AI 创作室', icon: Sparkles }, { to: '/lab', label: '配方实验室', icon: FlaskConical },
  { to: '/inventory', label: '我的酒柜', icon: Wine }, { to: '/moments', label: '场景酒单', icon: WandSparkles },
  { to: '/vision', label: '拍照识方', icon: ScanLine }, { to: '/me', label: '个人中心', icon: UserRound },
  ...(auth.isAdmin ? [{ to: '/admin', label: 'AI 控制台', icon: LayoutDashboard }] : []),
])
let capabilityTimer
async function refreshCapabilities() {
  if (!auth.authenticated) return
  const value = await api.capabilities().catch(() => null)
  if (value) capabilities.value = value
}
function receiveCapabilities(event) {
  if (event.detail) capabilities.value = event.detail
}
function refreshWhenVisible() {
  if (document.visibilityState === 'visible') refreshCapabilities()
}
watch(() => auth.authenticated, (authenticated) => {
  if (authenticated) refreshCapabilities()
  else capabilities.value = null
}, { immediate: true })
onMounted(() => {
  window.addEventListener('focus', refreshCapabilities)
  window.addEventListener(CAPABILITIES_EVENT, receiveCapabilities)
  document.addEventListener('visibilitychange', refreshWhenVisible)
  capabilityTimer = window.setInterval(refreshCapabilities, 10000)
})
onBeforeUnmount(() => {
  window.clearInterval(capabilityTimer)
  window.removeEventListener('focus', refreshCapabilities)
  window.removeEventListener(CAPABILITIES_EVENT, receiveCapabilities)
  document.removeEventListener('visibilitychange', refreshWhenVisible)
})
async function logout() { await auth.logout(); router.push('/login') }
</script>

<template>
  <router-view v-if="publicPage" v-slot="{ Component }"><transition name="route-pop" mode="out-in"><component :is="Component" /></transition></router-view>
  <div v-else class="app-shell">
    <aside class="sidebar">
      <router-link :to="isDemo ? '/explore' : '/chat'" class="brand"><span class="brand-mark"><GlassWater :size="22" /></span><span>BartenderAI</span></router-link>
      <nav class="side-nav" aria-label="主导航">
        <router-link v-for="item in navigation" :key="item.to" :to="item.to" :title="item.label">
          <component :is="item.icon" :size="19" /><span>{{ item.label }}</span>
        </router-link>
      </nav>
      <div v-if="!isDemo" class="side-foot">
        <div class="capability" :class="capabilities?.llm?.available ? 'available' : 'limited'"><span></span>{{ llmStatusLabel(capabilities?.llm) }}</div>
        <button class="user-button" @click="router.push('/me')">
          <span class="avatar">{{ (auth.user?.display_name || auth.user?.email || 'U')[0].toUpperCase() }}</span>
          <span><strong>{{ auth.user?.display_name || '调酒爱好者' }}</strong><small>{{ auth.user?.email }}</small></span>
        </button>
        <button class="icon-text danger" @click="logout"><LogOut :size="17" />退出登录</button>
      </div>
    </aside>
    <main class="main-area"><MixologyAtmosphere/><div class="route-stage"><div v-if="isDemo" class="demo-notice">在线演示 · 体验配方探索与分步调制，收藏和评分保存在此浏览器。<a href="https://github.com/wangpingping009-web/bartenderai">查看项目</a></div><router-view v-slot="{ Component, route: activeRoute }"><transition name="route-pop" mode="out-in"><component :is="Component" :key="activeRoute.fullPath" /></transition></router-view></div></main>
    <nav class="bottom-nav" aria-label="移动导航">
      <router-link v-for="item in navigation" :key="item.to" :to="item.to">
        <component :is="item.icon" :size="20" /><span>{{ item.label.replace('AI ', '') }}</span>
      </router-link>
    </nav>
  </div>
</template>

<style scoped>
.demo-notice { display: flex; flex-wrap: wrap; gap: 4px 12px; padding: 12px clamp(16px, 4vw, 34px); background: #e8eee9; color: #315440; font-size: 13px; }
.demo-notice a { color: inherit; font-weight: 700; text-decoration: underline; }
</style>
