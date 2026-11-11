import { defineStore } from 'pinia'
import { api, setAccessToken } from '../api'

export const useAuthStore = defineStore('auth', {
  state: () => ({ user: null, ready: false }),
  getters: { authenticated: (state) => Boolean(state.user), isAdmin: (state) => state.user?.role === 'admin' },
  actions: {
    apply(data) { setAccessToken(data.access_token); this.user = data.user },
    async bootstrap() { try { this.apply(await api.auth.refresh()) } catch (_) { this.user = null; setAccessToken('') } finally { this.ready = true } },
    async login(credentials) { const data = await api.auth.login(credentials); this.apply(data); return data },
    async logout() { try { await api.auth.logout() } finally { this.user = null; setAccessToken('') } },
  },
})
