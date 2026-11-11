<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  active: { type: Boolean, default: false },
  phase: { type: String, default: 'idle' },
  seed: { type: String, default: '' },
  pulse: { type: Number, default: 0 },
})

const host = ref(null), canvas = ref(null)
const nodeLayout = [[.09, .22], [.31, .47], [.53, .24], [.73, .53], [.92, .28]]
const phaseIndex = {
  idle: -1, orchestrator: 0, system: 0, retriever: 1, evidence: 1,
  stock: 2, flavor: 2, tutor: 2, reviewer: 3, review: 3,
  stream: 4, complete: 4, done: 4, ready: 4,
}

let context, observer, frame = 0, width = 1, height = 1, dpr = 1
let particles = [], bursts = [], start = 0, reducedMotion = false, visible = true
let pointer = { x: .5, y: .5 }

function hash(text = '') {
  let value = 2166136261
  for (const char of text) value = Math.imul(value ^ char.charCodeAt(0), 16777619)
  return value >>> 0
}
function randomFactory(seed) {
  let state = seed || 1
  return () => ((state = Math.imul(state ^ (state >>> 15), 1 | state) + 0x6d2b79f5) >>> 0) / 4294967296
}
function palette() {
  const text = props.seed || ''
  if (/清爽|清新|爽口/.test(text) && /刺激|带劲|冲击|醒神/.test(text)) {
    return ['#20cfa0', '#36bff0', '#ff4f62', '#ffdc3f']
  }
  if (/清爽|清新|爽口/.test(text)) return ['#22c79a', '#38bde8', '#d8ef58', '#ff7a55']
  if (/刺激|带劲|冲击|醒神/.test(text)) return ['#ff5060', '#ffd436', '#29c4e8', '#59dd91']
  return ['#ef6548', '#65c7e8', '#ffcc39', '#55d5a2']
}
function rebuild() {
  const random = randomFactory(hash(`${props.seed}-${width}-${height}`))
  const count = reducedMotion ? 36 : (width < 640 ? 68 : 132)
  particles = Array.from({ length: count }, (_, index) => ({
    edge: index % 4,
    offset: random(),
    speed: .07 + random() * .14,
    size: 1.6 + random() * 3.4,
    lane: (random() - .5) * 28,
    color: index % 4,
    shape: index % 4,
    phase: random() * Math.PI * 2,
  }))
}
function point(index) {
  const [x, y] = nodeLayout[index]
  const compact = width < 640
  return {
    x: x * width + (pointer.x - .5) * (compact ? 5 : 14),
    y: (compact ? .12 + y * .72 : y) * height + (pointer.y - .5) * 8,
  }
}
function curve(edge, t, lane = 0) {
  const a = point(edge), b = point(edge + 1), one = 1 - t
  const cx = (a.x + b.x) / 2
  const cy = (a.y + b.y) / 2 + (edge % 2 ? -68 : 68) + lane
  return {
    x: one * one * a.x + 2 * one * t * cx + t * t * b.x,
    y: one * one * a.y + 2 * one * t * cy + t * t * b.y,
  }
}
function strokeCurve(edge, color, alpha, lineWidth = 1.4) {
  const a = point(edge), b = point(edge + 1)
  context.beginPath(); context.moveTo(a.x, a.y)
  context.quadraticCurveTo((a.x + b.x) / 2, (a.y + b.y) / 2 + (edge % 2 ? -68 : 68), b.x, b.y)
  context.strokeStyle = color; context.globalAlpha = alpha; context.lineWidth = lineWidth; context.stroke()
}
function drawParticle(particle, x, y, color, alpha, rotation) {
  context.save(); context.translate(x, y); context.rotate(rotation)
  context.fillStyle = color; context.strokeStyle = color; context.globalAlpha = alpha
  const size = particle.size * (props.active ? 1.18 : .88)
  if (particle.shape === 0) {
    context.beginPath(); context.arc(0, 0, size, 0, Math.PI * 2); context.fill()
  } else if (particle.shape === 1) {
    context.rotate(Math.PI / 4); context.fillRect(-size, -size, size * 2, size * 2)
  } else if (particle.shape === 2) {
    context.lineWidth = 1.8; context.beginPath(); context.moveTo(-size * 1.8, 0); context.lineTo(size * 1.8, 0); context.stroke()
  } else {
    context.lineWidth = 1.4; context.beginPath(); context.arc(0, 0, size * 1.5, -.8, 1.9); context.stroke()
  }
  context.restore()
}
function drawNode(index, elapsed, colors, reached, current) {
  const p = point(index), color = colors[index % colors.length]
  const pulse = current ? Math.sin(elapsed * 5.5) * 4 : 0
  context.save(); context.translate(p.x, p.y)
  context.strokeStyle = color; context.fillStyle = color
  context.globalAlpha = current ? .88 : reached ? .42 : .18
  context.lineWidth = current ? 2.4 : 1.3
  context.beginPath(); context.arc(0, 0, 14 + pulse, 0, Math.PI * 2); context.stroke()
  context.rotate(elapsed * (current ? .5 : .12) + index)
  for (let arm = 0; arm < 6; arm += 1) {
    const angle = arm / 6 * Math.PI * 2
    context.beginPath(); context.moveTo(Math.cos(angle) * 20, Math.sin(angle) * 20)
    context.lineTo(Math.cos(angle) * (current ? 33 : 27), Math.sin(angle) * (current ? 33 : 27)); context.stroke()
  }
  context.globalAlpha = current ? .95 : .46
  context.rotate(Math.PI / 4); context.fillRect(-4, -4, 8, 8)
  context.restore()
}
function draw(timestamp = 0) {
  frame = 0
  if (!context || !visible) return
  const elapsed = (timestamp - start) / 1000, colors = palette()
  const current = phaseIndex[props.phase] ?? (props.active ? 0 : -1)
  context.clearRect(0, 0, width, height)

  for (let edge = 0; edge < 4; edge += 1) {
    const reached = edge <= current
    strokeCurve(edge, colors[edge], reached ? (props.active ? .34 : .16) : .08, reached ? 2 : 1)
    strokeCurve(edge, colors[(edge + 1) % colors.length], reached ? .13 : .04, reached ? 6 : 3)
  }

  for (const particle of particles) {
    const enabled = particle.edge <= current || (props.active && current < 0)
    const motion = reducedMotion ? particle.offset : (particle.offset + elapsed * particle.speed * (props.active ? 2.15 : .55)) % 1
    const p = curve(particle.edge, motion, particle.lane * Math.sin(elapsed + particle.phase))
    const alpha = enabled ? (props.active ? .92 : .55) : .14
    drawParticle(particle, p.x, p.y, colors[particle.color], alpha, elapsed + particle.phase)
  }

  nodeLayout.forEach((_, index) => drawNode(index, elapsed, colors, index <= current, index === current && props.active))
  bursts = bursts.filter(burst => timestamp - burst.started < 1100)
  for (const burst of bursts) {
    const progress = Math.min(1, (timestamp - burst.started) / 1100), fade = 1 - progress
    const origin = point(burst.node)
    burst.bits.forEach((bit, index) => {
      const angle = bit.angle + progress * bit.spin
      const distance = 12 + progress * (45 + bit.travel)
      drawParticle(
        { size: bit.size, shape: index % 4 },
        origin.x + Math.cos(angle) * distance,
        origin.y + Math.sin(angle) * distance,
        colors[index % colors.length], fade * .9, angle,
      )
    })
  }
  canvas.value.dataset.particleCount = String(particles.length)
  canvas.value.dataset.phase = props.phase
  canvas.value.dataset.active = String(props.active)
  if (!reducedMotion) frame = requestAnimationFrame(draw)
}
function schedule() {
  if (!context || !visible) return
  if (reducedMotion) draw(performance.now())
  else if (!frame) frame = requestAnimationFrame(draw)
}
function resize() {
  if (!host.value || !canvas.value) return
  const rect = host.value.getBoundingClientRect()
  width = Math.max(1, rect.width); height = Math.max(1, rect.height)
  dpr = Math.min(window.devicePixelRatio || 1, 2)
  canvas.value.width = Math.round(width * dpr); canvas.value.height = Math.round(height * dpr)
  canvas.value.style.width = `${width}px`; canvas.value.style.height = `${height}px`
  context.setTransform(dpr, 0, 0, dpr, 0, 0); rebuild(); schedule()
}
function addBurst() {
  const random = randomFactory(hash(`${props.seed}-${props.phase}-${props.pulse}`))
  const node = Math.max(0, phaseIndex[props.phase] ?? 0)
  bursts.push({
    node, started: performance.now(),
    bits: Array.from({ length: width < 640 ? 18 : 34 }, () => ({
      angle: random() * Math.PI * 2, spin: (random() - .5) * 3,
      travel: random() * 90, size: 1.5 + random() * 3,
    })),
  })
  if (bursts.length > 4) bursts.shift()
  schedule()
}
function pointerMove(event) {
  pointer = { x: event.clientX / Math.max(1, window.innerWidth), y: event.clientY / Math.max(1, window.innerHeight) }
}
function visibilityChange() {
  visible = !document.hidden
  if (visible) schedule()
  else { cancelAnimationFrame(frame); frame = 0 }
}

watch(() => props.pulse, addBurst)
watch(() => props.seed, () => { rebuild(); addBurst() })
watch(() => props.phase, addBurst)
watch(() => props.active, schedule)
onMounted(() => {
  reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches || false
  context = canvas.value.getContext('2d'); start = performance.now()
  observer = new ResizeObserver(resize); observer.observe(host.value)
  window.addEventListener('pointermove', pointerMove, { passive: true })
  document.addEventListener('visibilitychange', visibilityChange)
  resize()
})
onBeforeUnmount(() => {
  cancelAnimationFrame(frame); observer?.disconnect()
  window.removeEventListener('pointermove', pointerMove)
  document.removeEventListener('visibilitychange', visibilityChange)
})
</script>

<template>
  <div ref="host" class="chat-particle-field" :class="{ active }" aria-hidden="true">
    <canvas ref="canvas" />
  </div>
</template>

<style scoped>
.chat-particle-field{position:absolute;inset:58px 0 76px;z-index:0;pointer-events:none;overflow:hidden;opacity:.78;transition:opacity .3s ease}.chat-particle-field.active{opacity:1}.chat-particle-field canvas{display:block;width:100%;height:100%}@media(max-width:720px){.chat-particle-field{inset:54px 0 70px;opacity:.68}.chat-particle-field.active{opacity:.94}}@media(prefers-reduced-motion:reduce){.chat-particle-field{transition:none;opacity:.54}}
</style>
