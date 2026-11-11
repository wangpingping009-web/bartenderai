import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import FlavorRadar from '../components/FlavorRadar.vue'

describe('FlavorRadar', () => {
  it('renders six stable axes and a value polygon', () => {
    const wrapper = mount(FlavorRadar, { props: { flavor: { sweet: 8, sour: 6, bitter: 2, strong: 4, body: 5, aroma: 7 } } })
    expect(wrapper.findAll('line')).toHaveLength(6)
    expect(wrapper.findAll('text').map((node) => node.text())).toEqual(['甜', '酸', '苦', '烈', '醇', '香'])
    expect(wrapper.find('polygon.value').attributes('points')).not.toContain('NaN')
  })
})
