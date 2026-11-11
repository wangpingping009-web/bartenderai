import { describe, expect, it } from 'vitest'
import { llmStatusLabel } from '../capabilities'

describe('LLM capability status copy', () => {
  it('does not describe a configured cold-start model as deterministic mode', () => {
    expect(llmStatusLabel({ configured: true, available: false, status: 'unverified' }))
      .toBe('AI 服务连接中')
  })

  it('shows the recovered model as available', () => {
    expect(llmStatusLabel({ configured: true, available: true, status: 'available' }))
      .toBe('AI 服务可用')
  })

  it('keeps connection and configuration failures distinct', () => {
    expect(llmStatusLabel({ configured: true, available: false, reason: 'connection_failed' }))
      .toBe('模型连接失败')
    expect(llmStatusLabel({ configured: false, available: false }))
      .toBe('本地配方模式')
  })
})
