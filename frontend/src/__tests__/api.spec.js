import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, request, setAccessToken } from '../api'

afterEach(() => { vi.unstubAllGlobals(); setAccessToken('') })

describe('unified API client', () => {
  it('keeps the access token in memory and sends it as a bearer header', async () => {
    setAccessToken('memory-only-token')
    const fetchMock = vi.fn(async (_url, options) => ({
      ok: true, status: 200, json: async () => ({ authorization: options.headers.get('Authorization') }),
    }))
    vi.stubGlobal('fetch', fetchMock)
    const result = await request('/api/me')
    expect(result.authorization).toBe('Bearer memory-only-token')
    expect(fetchMock.mock.calls[0][1].credentials).toBe('include')
  })

  it('exposes the backend request id when an API call fails', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: false, status: 422, json: async () => ({ code: 'validation_error', message: '请求参数不正确', request_id: 'trace-1' }),
    })))
    await expect(request('/api/auth/login', { method: 'POST' })).rejects.toMatchObject({
      name: 'ApiError', code: 'validation_error', requestId: 'trace-1', status: 422,
    })
  })

  it('uses a typed error class', () => {
    expect(new ApiError('bad', 400)).toBeInstanceOf(Error)
  })
})
