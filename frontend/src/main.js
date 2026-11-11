import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { useAuthStore } from './stores/auth'
import './styles.css'

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)

// Restore the short-lived access token before the first protected navigation.
// Otherwise a hard refresh can race the router guard and bounce to /login.
const auth = useAuthStore(pinia)
const ready = import.meta.env.MODE === 'demo' ? Promise.resolve() : auth.bootstrap()
ready.finally(() => {
  app.use(router)
  app.mount('#app')
})
