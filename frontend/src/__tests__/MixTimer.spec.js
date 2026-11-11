import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import MixTimer from '../components/MixTimer.vue'

describe('MixTimer', () => {
  afterEach(() => vi.useRealTimers())

  it('publishes running progress and completes from an accurate deadline', async () => {
    vi.useFakeTimers()
    const wrapper = mount(MixTimer, { props: { seconds: 1, label: '摇和计时' } })

    expect(wrapper.attributes('data-running')).toBe('false')
    expect(wrapper.attributes('data-progress')).toBe('0.000')
    await wrapper.get('[aria-label="开始计时"]').trigger('click')
    expect(wrapper.attributes('data-running')).toBe('true')

    await vi.advanceTimersByTimeAsync(1100)
    await nextTick()

    expect(wrapper.attributes('data-running')).toBe('false')
    expect(wrapper.attributes('data-progress')).toBe('1.000')
    expect(wrapper.attributes('data-complete')).toBe('true')
    expect(wrapper.emitted('complete')).toHaveLength(1)
    expect(wrapper.get('[role="timer"]').text()).toBe('00:00')
  })

  it('pauses and resets without losing stable control dimensions', async () => {
    vi.useFakeTimers()
    const wrapper = mount(MixTimer, { props: { seconds: 12 } })

    await wrapper.get('[aria-label="开始计时"]').trigger('click')
    await vi.advanceTimersByTimeAsync(1200)
    await wrapper.get('[aria-label="暂停计时"]').trigger('click')
    const paused = Number(wrapper.attributes('data-progress'))
    expect(paused).toBeGreaterThan(0)
    expect(paused).toBeLessThan(1)

    await wrapper.get('[aria-label="重置计时"]').trigger('click')
    expect(wrapper.attributes('data-running')).toBe('false')
    expect(wrapper.attributes('data-progress')).toBe('0.000')
    expect(wrapper.get('[role="timer"]').text()).toBe('00:12')
  })
})
