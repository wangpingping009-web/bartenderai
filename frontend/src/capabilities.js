export const CAPABILITIES_EVENT = 'bartender:capabilities'

export function llmStatusLabel(llm) {
  if (llm?.available) return 'AI 服务可用'
  if (llm?.configured && llm?.status === 'unverified') return 'AI 服务连接中'
  if (llm?.reason === 'insufficient_balance') return '模型余额不足'
  if (llm?.reason === 'authentication_failed') return '模型认证失败'
  if (llm?.reason === 'connection_failed') return '模型连接失败'
  if (llm?.configured) return 'AI 服务暂不可用'
  return '本地配方模式'
}

export function publishCapabilities(value) {
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent(CAPABILITIES_EVENT, { detail: value }))
  }
}
