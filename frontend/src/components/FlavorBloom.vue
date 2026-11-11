<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  sweetness: { type: Number, default: 5 },
  sourness: { type: Number, default: 5 },
  strong: { type: Number, default: 5 },
})

const host = ref(null), canvas = ref(null)
const colors = ['#ef6548', '#65c7e8', '#ffcc39', '#39a875', '#f75d86', '#e68b29']
const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
let context, observer, frame = 0, width = 1, height = 1, dpr = 1, started = 0
let pointer = { x: 0, y: 0 }, burst = 0, interactionCount = 0, pageVisible = !document.hidden
let current = [5, 5, 5], target = [5, 5, 5]

function clamp(value) { return Math.max(1, Math.min(10, Number(value) || 5)) }
function derivedValues() {
  const [sweet, sour, spirit] = current
  return [sweet, sour, spirit, (sweet + spirit) / 2, 10 - Math.abs(sweet - sour) * .7, (sour + 10 - spirit) / 2]
}
function schedule() {
  if (!context || !pageVisible) return
  if (reducedMotion) { draw(performance.now()); return }
  if (!frame) frame = requestAnimationFrame(draw)
}
function petal(angle, length, spread, color, time, index) {
  const wobble = reducedMotion ? 0 : Math.sin(time * 1.3 + index * 1.7) * 2.4
  context.save(); context.rotate(angle + pointer.x * .025); context.translate(pointer.x * 3, pointer.y * 2)
  context.beginPath(); context.moveTo(0, 0)
  context.bezierCurveTo(spread + wobble, -length * .34, spread * .7, -length * .78, 0, -length)
  context.bezierCurveTo(-spread * .7, -length * .78, -spread - wobble, -length * .34, 0, 0)
  context.closePath(); context.fillStyle = `${color}42`; context.fill()
  context.strokeStyle = color; context.globalAlpha = .82; context.lineWidth = 1.7; context.stroke()
  context.beginPath(); context.moveTo(0, -5); context.quadraticCurveTo(wobble * 1.4, -length * .48, 0, -length + 5)
  context.globalAlpha = .38; context.lineWidth = 1; context.stroke(); context.restore()
}
function draw(timestamp = 0) {
  frame = 0
  if (!context || !canvas.value || !pageVisible) return
  const time = (timestamp - started) * .001
  current = current.map((value, index) => value + (target[index] - value) * (reducedMotion ? 1 : .09))
  context.clearRect(0, 0, width, height)
  const centerX = width / 2, centerY = height * .55
  context.save(); context.translate(centerX, centerY)
  const values = derivedValues()
  values.forEach((value, index) => {
    const length = 34 + value * Math.min(5.3, width / 70) + burst * 12
    const spread = 13 + value * 1.25
    petal(index / values.length * Math.PI * 2, length, spread, colors[index], time, index)
  })
  const pulse = reducedMotion ? 0 : Math.sin(time * 2.2) * 2
  context.beginPath(); context.arc(0, 0, 12 + pulse + burst * 7, 0, Math.PI * 2)
  context.fillStyle = '#17241f'; context.globalAlpha = .9; context.fill()
  context.strokeStyle = '#ffcc39'; context.lineWidth = 2; context.globalAlpha = .9; context.stroke()
  for (let index = 0; index < 12; index += 1) {
    const angle = index / 12 * Math.PI * 2 + time * .09
    const radius = 24 + (index % 3) * 6 + burst * 22
    context.fillStyle = colors[index % colors.length]; context.globalAlpha = .42
    context.fillRect(Math.cos(angle) * radius - 1.5, Math.sin(angle) * radius - 1.5, 3, 3)
  }
  context.restore()
  burst *= .91
  canvas.value.dataset.animationReady = 'true'
  canvas.value.dataset.values = target.map(value => Math.round(value)).join('-')
  canvas.value.dataset.interactionCount = String(interactionCount)
  canvas.value.dataset.petals = '6'
  canvas.value.setAttribute('aria-label', `口味花谱：甜度 ${Math.round(target[0])}，酸度 ${Math.round(target[1])}，酒精感 ${Math.round(target[2])}`)
  if (!reducedMotion) frame = requestAnimationFrame(draw)
}
function resize() {
  const rect = host.value?.getBoundingClientRect(); if (!rect || !context) return
  width = Math.max(1, rect.width); height = Math.max(1, rect.height); dpr = Math.min(window.devicePixelRatio || 1, 1.75)
  canvas.value.width = Math.round(width * dpr); canvas.value.height = Math.round(height * dpr)
  canvas.value.style.width = `${width}px`; canvas.value.style.height = `${height}px`
  context.setTransform(dpr, 0, 0, dpr, 0, 0); schedule()
}
function pointerMove(event) {
  const rect = host.value.getBoundingClientRect()
  pointer = { x: (event.clientX - rect.left) / Math.max(1, rect.width) - .5, y: (event.clientY - rect.top) / Math.max(1, rect.height) - .5 }
  if (reducedMotion) schedule()
}
function resetPointer() { pointer = { x: 0, y: 0 }; if (reducedMotion) schedule() }
function activate() { interactionCount += 1; burst = 1; if (reducedMotion) schedule() }
function visibilityChange() { pageVisible = !document.hidden; if (pageVisible) schedule(); else { cancelAnimationFrame(frame); frame = 0 } }

onMounted(() => {
  target = [clamp(props.sweetness), clamp(props.sourness), clamp(props.strong)]; current = [...target]
  context = canvas.value.getContext('2d'); started = performance.now()
  observer = new ResizeObserver(resize); observer.observe(host.value)
  document.addEventListener('visibilitychange', visibilityChange); resize()
})
watch(() => [props.sweetness, props.sourness, props.strong], (values) => { target = values.map(clamp); burst = Math.max(burst, .45); schedule() })
onBeforeUnmount(() => { cancelAnimationFrame(frame); observer?.disconnect(); document.removeEventListener('visibilitychange', visibilityChange) })
</script>

<template>
  <div ref="host" class="flavor-bloom" @pointermove="pointerMove" @pointerleave="resetPointer" @click="activate">
    <canvas ref="canvas" role="img" />
  </div>
</template>

<style scoped>
.flavor-bloom{width:100%;height:190px;min-width:0;overflow:hidden;cursor:crosshair;touch-action:manipulation}.flavor-bloom canvas{display:block;width:100%;height:100%}@media(max-width:760px){.flavor-bloom{height:175px}}@media(prefers-reduced-motion:reduce){.flavor-bloom{cursor:default}}
</style>
