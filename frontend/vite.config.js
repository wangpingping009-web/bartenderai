import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  test: {
    environment: 'jsdom',
    include: ['src/**/*.spec.js'],
  },
  server: {
    port: 5173,
    proxy: {
      // 开发环境：前端 5173 → 后端 8000，避免跨域
      '/api': { target: process.env.VITE_API_PROXY || 'http://127.0.0.1:8001', changeOrigin: true }
    }
  }
})
