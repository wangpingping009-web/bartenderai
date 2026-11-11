<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  stages: { type: Array, default: () => [] },
  persona: { type: String, default: 'classic' },
  bases: { type: Array, default: () => [] },
  brief: { type: String, default: '' },
  busy: { type: Boolean, default: false },
})
const emit = defineEmits(['interact'])

const host = ref(null), canvas = ref(null)
const nodeSpecs = [
  { key: 'brief', label: '需求' }, { key: 'evidence', label: '证据' },
  { key: 'create', label: '构建' }, { key: 'rules', label: '规则' },
  { key: 'review', label: '审校' }, { key: 'ready', label: '出品' },
]
const layouts = {
  classic: [[.10, .56], [.27, .28], [.46, .60], [.64, .30], [.81, .57], [.93, .30]],
  molecular: [[.08, .51], [.25, .25], [.43, .44], [.58, .72], [.76, .43], [.93, .25]],
  japanese: [[.08, .62], [.25, .39], [.43, .27], [.61, .34], [.78, .56], [.93, .39]],
  playful: [[.08, .30], [.25, .68], [.43, .31], [.60, .69], [.77, .29], [.93, .62]],
}
const stageOrder = { brief: 0, evidence: 1, create: 2, revise: 2, rules: 3, review: 4, ready: 5 }
const baseColors = {
  gin: ['#49d39a', '#c9f36a'], vodka: ['#83d8ff', '#e2f6ff'],
  rum: ['#ffb34e', '#ef6548'], tequila: ['#d7dc4b', '#69c48d'],
  whiskey: ['#f49a3f', '#f2d06b'], brandy: ['#d96e55', '#f2af66'],
}
const personaColors = {
  classic: ['#ef6548', '#ffcc39', '#55d5a2'], molecular: ['#65c7e8', '#ef6ca6', '#ffe25d'],
  japanese: ['#e05b57', '#78c59b', '#f1d785'], playful: ['#ff8f4d', '#65c7e8', '#ef6ca6'],
}

let context, observer, visibilityObserver, frame = 0, width = 1, height = 1, dpr = 1
let pointer = { x: -999, y: -999, active: false }, focusIndex = -1, hoverIndex = -1, burst = 0
let interactionCount = 0, pageVisible = !document.hidden, sceneVisible = true, disposed = false
let touchStart = null
const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
const particles = Array.from({ length: 72 }, (_, index) => ({
  edge: index % (nodeSpecs.length - 1), offset: (index * .173) % 1,
  speed: .09 + (index % 9) * .012, size: 1.2 + (index % 5) * .34,
}))

function hashText(text = '') {
  let value = 2166136261
  for (const char of text) value = Math.imul(value ^ char.charCodeAt(0), 16777619)
  return value >>> 0
}
function topology() { return layouts[props.persona] ? props.persona : 'classic' }
function nodes() {
  const points = layouts[topology()]
  return nodeSpecs.map((node, index) => ({ ...node, x: points[index][0], y: points[index][1] }))
}
function palette() {
  const colors = props.bases.flatMap(base => baseColors[base] || []).slice(0, 5)
  return colors.length ? colors : (personaColors[props.persona] || personaColors.classic)
}
function stageDetails() {
  const details = new Map()
  for (const item of props.stages || []) details.set(item.stage === 'revise' ? 'create' : item.stage, item)
  return details
}
function currentState() {
  const details = stageDetails(), state = new Map([...details].map(([key, item]) => [key, item.status || 'done']))
  const indices = [...state.keys()].map(key => stageOrder[key]).filter(Number.isFinite)
  const progress = indices.length ? Math.max(...indices) : (props.busy ? 0 : -1)
  const working = [...state.entries()].find(([, status]) => status === 'working')?.[0]
  return { details, state, progress, working: working ? stageOrder[working] : (props.busy ? progress : -1) }
}
function position(node) { return { x: node.x * width, y: node.y * height } }
function controlPoint(a, b, edge) {
  const persona = topology()
  if (persona === 'molecular') return { x: (a.x + b.x) / 2 + (edge % 2 ? -18 : 18), y: (a.y + b.y) / 2 }
  if (persona === 'japanese') return { x: (a.x + b.x) / 2, y: Math.min(a.y, b.y) - 34 }
  if (persona === 'playful') return { x: (a.x + b.x) / 2 + (edge % 2 ? 24 : -24), y: (a.y + b.y) / 2 }
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 + (a.y < b.y ? 30 : -30) }
}
function curvePoint(a, b, t, edge) {
  const control = controlPoint(a, b, edge), one = 1 - t
  return {
    x: one * one * a.x + 2 * one * t * control.x + t * t * b.x,
    y: one * one * a.y + 2 * one * t * control.y + t * t * b.y,
  }
}
function roundedRect(x, y, w, h, radius) { context.beginPath(); context.roundRect(x, y, w, h, radius) }
function drawConnection(a, b, edge, color, reached) {
  const control = controlPoint(a, b, edge)
  context.beginPath(); context.moveTo(a.x, a.y); context.quadraticCurveTo(control.x, control.y, b.x, b.y)
  context.strokeStyle = reached ? `${color}9a` : '#b9d6cb20'; context.lineWidth = reached ? 2 : 1; context.stroke()
}
function drawParticle(point, particle, color, enabled) {
  context.save(); context.translate(point.x, point.y)
  context.fillStyle = enabled ? color : '#bdd4cb35'; context.strokeStyle = context.fillStyle
  context.globalAlpha = enabled ? .8 : .22
  if (particle.edge === 1) {
    context.rotate(Math.PI / 4); context.fillRect(-particle.size, -particle.size, particle.size * 2, particle.size * 2)
  } else if (particle.edge === 2) {
    context.beginPath(); context.moveTo(-particle.size * 2.2, 0); context.lineTo(particle.size * 2.2, 0); context.lineWidth = 1.4; context.stroke()
  } else if (particle.edge === 3) {
    context.strokeRect(-particle.size, -particle.size, particle.size * 2, particle.size * 2)
  } else if (particle.edge === 4) {
    context.beginPath(); context.moveTo(0, -particle.size * 1.6); context.lineTo(particle.size * 1.4, particle.size); context.lineTo(-particle.size * 1.4, particle.size); context.closePath(); context.fill()
  } else {
    context.beginPath(); context.arc(0, 0, particle.size, 0, Math.PI * 2); context.fill()
  }
  context.restore()
}
function drawStageAura(index, point, color, elapsed, active, reached) {
  if (!active && !reached) return
  const alpha = active ? .62 : .16, phase = elapsed * (1.4 + index * .13)
  context.save(); context.translate(point.x, point.y); context.strokeStyle = color; context.fillStyle = color
  context.globalAlpha = alpha; context.lineWidth = active ? 1.8 : 1
  if (index === 0) {
    context.beginPath(); context.arc(0, 0, 24 + Math.sin(phase) * 3, -.4, Math.PI * 1.4); context.stroke()
  } else if (index === 1) {
    const scan = -24 + ((phase * 16) % 48)
    context.beginPath(); context.moveTo(-24, scan); context.lineTo(24, scan); context.stroke()
    context.strokeRect(-22, -22, 44, 44)
  } else if (index === 2) {
    for (let orbit = 0; orbit < 3; orbit += 1) {
      const angle = phase * (orbit % 2 ? -1 : 1) + orbit * 2.1
      context.beginPath(); context.arc(Math.cos(angle) * (22 + orbit * 4), Math.sin(angle) * (13 + orbit * 2), 2 + orbit * .5, 0, Math.PI * 2); context.fill()
    }
  } else if (index === 3) {
    for (let cell = 0; cell < 4; cell += 1) context.strokeRect(-23 + (cell % 2) * 27, -23 + Math.floor(cell / 2) * 27, 19, 19)
  } else if (index === 4) {
    context.beginPath(); context.ellipse(0, 0, 27 + Math.sin(phase) * 3, 13, 0, 0, Math.PI * 2); context.stroke()
    context.beginPath(); context.arc(0, 0, 4 + Math.sin(phase * 1.4) * 1.5, 0, Math.PI * 2); context.fill()
  } else {
    context.rotate(phase * .14)
    context.beginPath()
    for (let spoke = 0; spoke < 8; spoke += 1) {
      const angle = spoke / 8 * Math.PI * 2
      context.moveTo(Math.cos(angle) * 22, Math.sin(angle) * 22); context.lineTo(Math.cos(angle) * 31, Math.sin(angle) * 31)
    }
    context.stroke()
  }
  context.restore()
}
function drawNodeGlyph(index, status, reached) {
  context.strokeStyle = reached ? '#10241f' : '#a8c0b7'; context.fillStyle = context.strokeStyle
  context.lineWidth = 1.5; context.lineCap = 'round'; context.lineJoin = 'round'
  if (status === 'done') {
    context.beginPath(); context.moveTo(-5, 0); context.lineTo(-1, 4); context.lineTo(6, -5); context.stroke(); return
  }
  if (index === 0) { context.beginPath(); context.arc(0, -1, 5, .2, Math.PI * 1.75); context.stroke() }
  else if (index === 1) { context.strokeRect(-5, -6, 10, 12); context.beginPath(); context.moveTo(-2, -2); context.lineTo(3, -2); context.moveTo(-2, 2); context.lineTo(3, 2); context.stroke() }
  else if (index === 2) { context.beginPath(); context.moveTo(0, -6); context.lineTo(6, 5); context.lineTo(-6, 5); context.closePath(); context.stroke() }
  else if (index === 3) { context.strokeRect(-6, -6, 12, 12); context.beginPath(); context.moveTo(-3, 0); context.lineTo(-1, 3); context.lineTo(4, -3); context.stroke() }
  else if (index === 4) { context.beginPath(); context.ellipse(0, 0, 7, 4, 0, 0, Math.PI * 2); context.stroke(); context.beginPath(); context.arc(0, 0, 1.5, 0, Math.PI * 2); context.fill() }
  else { context.beginPath(); context.moveTo(0, -7); context.lineTo(7, 0); context.lineTo(0, 7); context.lineTo(-7, 0); context.closePath(); context.stroke() }
}
function drawTooltip(node, index, flow) {
  const point = position(node), detail = flow.details.get(node.key)
  const title = detail?.title || `${node.label}环节`, status = detail?.status === 'working' ? '正在协作' : detail ? '已经接力' : '等待接力'
  context.font = '700 11px Inter, Microsoft YaHei, sans-serif'
  const boxWidth = Math.min(176, Math.max(108, context.measureText(title).width + 24))
  const x = Math.min(width - boxWidth - 8, Math.max(8, point.x - boxWidth / 2))
  const y = point.y > height * .52 ? point.y - 65 : point.y + 47
  roundedRect(x, y, boxWidth, 43, 5); context.fillStyle = '#071b17e8'; context.fill(); context.strokeStyle = `${palette()[index % palette().length]}99`; context.lineWidth = 1; context.stroke()
  context.fillStyle = '#ecfff8'; context.textAlign = 'left'; context.fillText(title.slice(0, 16), x + 11, y + 17)
  context.font = '500 9px Inter, Microsoft YaHei, sans-serif'; context.fillStyle = '#8ec5b1'; context.fillText(status, x + 11, y + 32)
}
function draw(time = 0) {
  if (disposed || !context || !canvas.value) return
  const elapsed = time * .001, colors = palette(), flow = currentState(), currentNodes = nodes()
  context.clearRect(0, 0, width, height)
  const wash = context.createLinearGradient(0, 0, width, height)
  wash.addColorStop(0, '#102d29'); wash.addColorStop(.55, '#173833'); wash.addColorStop(1, '#101c1a')
  context.fillStyle = wash; context.fillRect(0, 0, width, height)

  const briefSeed = hashText(props.brief), specks = Math.max(35, Math.floor(width / 13))
  for (let index = 0; index < specks; index += 1) {
    const x = ((index * (61.3 + briefSeed % 13)) % width + Math.sin(elapsed * .16 + index) * 5 + width) % width
    const y = (index * (31.7 + briefSeed % 7)) % height
    context.fillStyle = index % 4 ? '#d8eee50c' : `${colors[index % colors.length]}1c`
    context.beginPath(); context.arc(x, y, 1 + index % 3 * .35, 0, Math.PI * 2); context.fill()
  }

  for (let edge = 0; edge < currentNodes.length - 1; edge += 1) {
    drawConnection(position(currentNodes[edge]), position(currentNodes[edge + 1]), edge, colors[edge % colors.length], edge < flow.progress)
  }
  for (const particle of particles) {
    const enabled = particle.edge <= Math.max(flow.progress, 0)
    if (!enabled && !props.busy) continue
    const speed = props.busy ? particle.speed : particle.speed * .22
    const t = (particle.offset + elapsed * speed + burst * .018) % 1
    const point = curvePoint(position(currentNodes[particle.edge]), position(currentNodes[particle.edge + 1]), t, particle.edge)
    const dx = point.x - pointer.x, dy = point.y - pointer.y, distance = Math.hypot(dx, dy)
    if (pointer.active && distance < 70) { point.x += dx / Math.max(distance, 1) * 9; point.y += dy / Math.max(distance, 1) * 9 }
    drawParticle(point, particle, colors[(particle.edge + Math.floor(particle.offset * 10)) % colors.length], enabled)
  }

  currentNodes.forEach((node, index) => {
    const point = position(node), status = flow.state.get(node.key), reached = index <= flow.progress
    const active = index === flow.working || index === focusIndex || index === hoverIndex
    drawStageAura(index, point, colors[index % colors.length], elapsed, active, reached)
    const pulse = active && !reduceMotion ? 1 + Math.sin(elapsed * 4.2) * .08 : 1
    context.save(); context.translate(point.x, point.y); context.scale(pulse, pulse)
    context.fillStyle = reached ? colors[index % colors.length] : '#244840'; context.strokeStyle = reached ? '#edfff8aa' : '#92b5a744'; context.lineWidth = 1.2
    context.beginPath(); context.arc(0, 0, 16, 0, Math.PI * 2); context.fill(); context.stroke()
    drawNodeGlyph(index, status, reached); context.restore()
    context.font = '700 11px Inter, Microsoft YaHei, sans-serif'; context.textAlign = 'center'; context.fillStyle = reached ? '#f0fbf6' : '#8eaaa0'; context.fillText(node.label, point.x, point.y + 35)
  })
  if (focusIndex >= 0) drawTooltip(currentNodes[focusIndex], focusIndex, flow)

  const label = props.busy ? '协作创作进行中' : flow.progress >= 5 ? '协作创作已完成' : props.brief.trim() ? '创作命题已就绪' : '等待创作命题'
  context.font = '800 10px Inter, Microsoft YaHei, sans-serif'; context.textAlign = 'left'
  roundedRect(16, 15, context.measureText(label).width + 18, 24, 4); context.fillStyle = '#0b211dcc'; context.fill()
  context.fillStyle = '#a8d8c7'; context.fillText(label, 25, 31)

  canvas.value.dataset.animationReady = 'true'
  canvas.value.dataset.activeStage = String(flow.working)
  canvas.value.dataset.progress = String(flow.progress)
  canvas.value.dataset.palette = colors.join(',')
  canvas.value.dataset.topology = topology()
  canvas.value.dataset.briefSignature = String(briefSeed % 1009)
  canvas.value.dataset.stageCount = String(flow.details.size)
  canvas.value.dataset.focusedAgent = focusIndex >= 0 ? currentNodes[focusIndex].key : 'none'
  canvas.value.dataset.flowSignature = `${topology()}-${briefSeed % 1009}-${colors.join('').replaceAll('#', '')}-${flow.details.size}`
  burst *= .94
}
function canAnimate() { return !reduceMotion && pageVisible && sceneVisible && !disposed }
function renderFrame(time) { frame = 0; draw(time); schedule() }
function schedule() { if (canAnimate() && !frame) frame = requestAnimationFrame(renderFrame); else if (reduceMotion && !disposed) draw(performance.now()) }
function resize() {
  if (!host.value || !canvas.value) return
  const rect = host.value.getBoundingClientRect(); width = Math.max(1, rect.width); height = Math.max(1, rect.height)
  dpr = Math.min(window.devicePixelRatio || 1, 2); canvas.value.width = Math.round(width * dpr); canvas.value.height = Math.round(height * dpr)
  canvas.value.style.width = `${width}px`; canvas.value.style.height = `${height}px`; context.setTransform(dpr, 0, 0, dpr, 0, 0)
  draw(performance.now()); schedule()
}
function nearestNode(x, y, limit = 38) {
  return nodes().reduce((best, node, index) => {
    const point = position(node), distance = Math.hypot(point.x - x, point.y - y)
    return distance < best.distance ? { index, distance } : best
  }, { index: -1, distance: limit }).index
}
function pointerMove(event) {
  if (event.pointerType === 'touch') return
  const rect = canvas.value.getBoundingClientRect(); pointer = { x: event.clientX - rect.left, y: event.clientY - rect.top, active: true }
  hoverIndex = nearestNode(pointer.x, pointer.y, 34)
  if (reduceMotion) draw(performance.now())
}
function pointerLeave() { pointer.active = false; hoverIndex = -1; touchStart = null; if (reduceMotion) draw(performance.now()) }
function activateAt(event) {
  const rect = canvas.value.getBoundingClientRect(), x = event.clientX - rect.left, y = event.clientY - rect.top
  focusIndex = nearestNode(x, y)
  burst = 1.3; interactionCount += 1; canvas.value.dataset.interactionCount = String(interactionCount)
  emit('interact', { agent: focusIndex >= 0 ? nodeSpecs[focusIndex].key : 'field', index: focusIndex })
  if (reduceMotion) draw(performance.now())
}
function pointerDown(event) {
  touchStart = { x: event.clientX, y: event.clientY, type: event.pointerType }
  if (event.pointerType !== 'touch') activateAt(event)
}
function pointerUp(event) {
  if (touchStart?.type === 'touch' && Math.hypot(event.clientX - touchStart.x, event.clientY - touchStart.y) < 12) activateAt(event)
  touchStart = null
}
function keydown(event) {
  if (!['ArrowRight', 'ArrowLeft', 'Enter', ' '].includes(event.key)) return
  event.preventDefault()
  if (event.key === 'ArrowRight') focusIndex = (focusIndex + 1 + nodeSpecs.length) % nodeSpecs.length
  else if (event.key === 'ArrowLeft') focusIndex = (focusIndex - 1 + nodeSpecs.length) % nodeSpecs.length
  else { burst = 1.3; interactionCount += 1; emit('interact', { agent: focusIndex >= 0 ? nodeSpecs[focusIndex].key : 'field', index: focusIndex }) }
  canvas.value.dataset.interactionCount = String(interactionCount); draw(performance.now()); schedule()
}
function visibilityChange() {
  pageVisible = !document.hidden
  if (pageVisible) schedule(); else { cancelAnimationFrame(frame); frame = 0 }
}

onMounted(() => {
  context = canvas.value.getContext('2d', { alpha: false }); canvas.value.dataset.interaction = 'pointer-flow'; canvas.value.dataset.interactionCount = '0'
  observer = new ResizeObserver(resize); observer.observe(host.value)
  visibilityObserver = new IntersectionObserver(([entry]) => {
    sceneVisible = entry?.isIntersecting !== false
    if (sceneVisible) schedule(); else { cancelAnimationFrame(frame); frame = 0 }
  }, { threshold: .01 })
  visibilityObserver.observe(host.value); document.addEventListener('visibilitychange', visibilityChange); resize()
})
watch(() => [props.stages, props.persona, props.bases, props.brief, props.busy], () => { burst = .9; draw(performance.now()); schedule() }, { deep: true })
onBeforeUnmount(() => {
  disposed = true; cancelAnimationFrame(frame); observer?.disconnect(); visibilityObserver?.disconnect(); document.removeEventListener('visibilitychange', visibilityChange)
})
</script>

<template>
  <div ref="host" class="agent-mixing-stage">
    <canvas
      ref="canvas"
      tabindex="0"
      :aria-label="`创作 Agent 协作轨迹，${stages.length} 个环节已有状态`"
      @pointermove="pointerMove"
      @pointerleave="pointerLeave"
      @pointerdown="pointerDown"
      @pointerup="pointerUp"
      @pointercancel="pointerLeave"
      @keydown="keydown"
    />
  </div>
</template>

<style scoped>
.agent-mixing-stage{position:relative;width:100%;height:230px;overflow:hidden;background:#102d29;touch-action:pan-y}.agent-mixing-stage canvas{display:block;width:100%;height:100%;cursor:crosshair;outline:0}.agent-mixing-stage canvas:focus-visible{box-shadow:inset 0 0 0 3px #65c7e8}@media(max-width:600px){.agent-mixing-stage{height:220px}}@media(prefers-reduced-motion:reduce){.agent-mixing-stage canvas{cursor:default}}
</style>
