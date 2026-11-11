let accessToken = ''
let refreshPromise = null

export function setAccessToken(token) { accessToken = token || '' }

export class ApiError extends Error {
  constructor(message, status = 0, payload = null) {
    super(message); this.name = 'ApiError'; this.status = status
    this.code = payload?.code || 'request_failed'; this.details = payload?.details
    this.requestId = payload?.request_id
  }
}

async function parseError(response) {
  const payload = await response.json().catch(() => null)
  return new ApiError(payload?.message || payload?.detail || `请求失败（HTTP ${response.status}）`, response.status, payload)
}

async function refreshAccess() {
  if (!refreshPromise) {
    refreshPromise = fetch('/api/auth/refresh', { method: 'POST', credentials: 'include' })
      .then(async (response) => {
        if (!response.ok) throw await parseError(response)
        const data = await response.json(); setAccessToken(data.access_token); return data
      }).finally(() => { refreshPromise = null })
  }
  return refreshPromise
}

export async function request(path, options = {}, retry = true) {
  if (import.meta.env.MODE === 'demo') {
    const { demoRequest } = await import('./demo')
    return demoRequest(path, options)
  }
  const headers = new Headers(options.headers || {})
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  const response = await fetch(path, { ...options, headers, credentials: 'include' })
  if (response.status === 401 && retry && !path.startsWith('/api/auth/')) {
    try { await refreshAccess(); return request(path, options, false) }
    catch (_) { setAccessToken('') }
  }
  if (!response.ok) throw await parseError(response)
  if (response.status === 204) return null
  return response.json()
}

function query(params = {}) {
  const values = Object.entries(params).filter(([, value]) => value !== '' && value !== null && value !== undefined)
  return values.length ? `?${new URLSearchParams(values).toString()}` : ''
}

export async function streamConversation(conversationId, message, onEvent, signal) {
  if (import.meta.env.MODE === 'demo') {
    const { demoChat } = await import('./demo')
    return demoChat(conversationId, message, onEvent, signal)
  }
  const headers = new Headers({ 'Content-Type': 'application/json' })
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)
  const response = await fetch(`/api/conversations/${conversationId}/messages/stream`, {
    method: 'POST', headers, credentials: 'include', body: JSON.stringify({ message }), signal,
  })
  if (!response.ok || !response.body) throw await parseError(response)
  const reader = response.body.getReader(), decoder = new TextDecoder(); let buffer = ''
  while (true) {
    const { done, value } = await reader.read(); if (done) break
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
    let boundary
    while ((boundary = buffer.indexOf('\n\n')) >= 0) {
      const frame = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2)
      for (const line of frame.split('\n')) if (line.startsWith('data: ')) {
        let event
        try { event = JSON.parse(line.slice(6)) } catch (_) { continue }
        onEvent(event)
      }
    }
  }
}

export async function streamRecipeCreation(payload, onEvent, signal) {
  if (import.meta.env.MODE === 'demo') {
    const { demoCreate } = await import('./demo')
    return demoCreate(payload, onEvent, signal)
  }
  const headers = new Headers({ 'Content-Type': 'application/json' })
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)
  const response = await fetch('/api/recipes/generate/stream', {
    method: 'POST', headers, credentials: 'include', body: JSON.stringify(payload), signal,
  })
  if (!response.ok || !response.body) throw await parseError(response)
  const reader = response.body.getReader(), decoder = new TextDecoder(); let buffer = ''
  while (true) {
    const { done, value } = await reader.read(); if (done) break
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
    let boundary
    while ((boundary = buffer.indexOf('\n\n')) >= 0) {
      const frame = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2)
      for (const line of frame.split('\n')) if (line.startsWith('data: ')) {
        try { onEvent(JSON.parse(line.slice(6))) } catch (error) { if (!(error instanceof SyntaxError)) throw error }
      }
    }
  }
}

export const api = {
  auth: {
    register: (body) => request('/api/auth/register', { method: 'POST', body: JSON.stringify(body) }),
    verify: (token) => request('/api/auth/verify', { method: 'POST', body: JSON.stringify({ token }) }),
    login: (body) => request('/api/auth/login', { method: 'POST', body: JSON.stringify(body) }),
    refresh: refreshAccess, logout: () => request('/api/auth/logout', { method: 'POST' }),
    forgot: (email) => request('/api/auth/forgot-password', { method: 'POST', body: JSON.stringify({ email }) }),
    reset: (token, password) => request('/api/auth/reset-password', { method: 'POST', body: JSON.stringify({ token, password }) }),
  },
  capabilities: () => request('/api/capabilities'),
  me: {
    get: () => request('/api/me'), update: (body) => request('/api/me', { method: 'PATCH', body: JSON.stringify(body) }),
    remove: () => request('/api/me', { method: 'DELETE' }), export: () => request('/api/me/export'),
    inventory: () => request('/api/me/inventory'), setInventory: (items) => request('/api/me/inventory', { method: 'PUT', body: JSON.stringify({ items }) }),
    matches: () => request('/api/me/inventory/matches'), favorites: () => request('/api/me/favorites'),
    addFavorite: (recipe) => request('/api/me/favorites', { method: 'POST', body: JSON.stringify({ recipe }) }),
    removeFavorite: (name) => request(`/api/me/favorites/${encodeURIComponent(name)}`, { method: 'DELETE' }),
    changePassword: (body) => request('/api/me/change-password', { method: 'POST', body: JSON.stringify(body) }),
  },
  conversations: {
    list: () => request('/api/conversations'), create: (title = '新对话') => request('/api/conversations', { method: 'POST', body: JSON.stringify({ title }) }),
    rename: (id, title) => request(`/api/conversations/${id}`, { method: 'PATCH', body: JSON.stringify({ title }) }),
    remove: (id) => request(`/api/conversations/${id}`, { method: 'DELETE' }), messages: (id) => request(`/api/conversations/${id}/messages`),
  },
  recipes: {
    list: (params) => request(`/api/recipes${query(params)}`), get: (id) => request(`/api/recipes/${encodeURIComponent(id)}`),
    personas: () => request('/api/recipes/personas'), generate: (body) => request('/api/recipes/generate', { method: 'POST', body: JSON.stringify(body) }),
    generateStream: streamRecipeCreation,
    creations: () => request('/api/recipes/creations'),
    creation: (id) => request(`/api/recipes/creations/${encodeURIComponent(id)}`),
    removeCreation: (id) => request(`/api/recipes/creations/${encodeURIComponent(id)}`, { method: 'DELETE' }),
    substitute: (q, context = '') => request(`/api/recipes/substitute${query({ q, context })}`),
    deconstruct: (card) => request('/api/recipes/deconstruct', { method: 'POST', body: JSON.stringify(card) }),
  },
  feedback: (body) => request('/api/feedback', { method: 'POST', body: JSON.stringify(body) }),
  vision: (file) => { const form = new FormData(); form.append('file', file); return request('/api/vision/identify', { method: 'POST', body: form }) },
  themes: { list: () => request('/api/themes'), get: (key) => request(`/api/themes/${key}`) },
  fun: {
    daily: () => request('/api/fun/daily'), challenge: () => request('/api/fun/challenge'), mocktails: () => request('/api/fun/mocktail/list'),
    mocktail: (name) => request(`/api/fun/mocktail${query({ name })}`, { method: 'POST' }), banquet: (body) => request('/api/fun/banquet', { method: 'POST', body: JSON.stringify(body) }),
    context: (params) => request(`/api/fun/context${query(params)}`), progress: () => request('/api/fun/progress'),
  },
  admin: {
    overview: () => request('/api/admin/overview'), jobs: () => request('/api/admin/jobs'), prompts: () => request('/api/admin/prompts'), knowledge: () => request('/api/admin/knowledge'),
    reindex: () => request('/api/admin/knowledge/reindex', { method: 'POST' }), evaluate: () => request('/api/admin/rag/evaluations', { method: 'POST' }),
    activatePrompt: (task, version) => request(`/api/admin/prompts/${task}/versions/${version}/activate`, { method: 'POST' }),
  },
}
