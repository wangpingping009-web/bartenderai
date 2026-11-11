<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { onMotion } from '../motion'

const route = useRoute(), host = ref(null), canvas = ref(null)
const themes = {
  chat: { colors: ['#ef6548', '#65c7e8', '#ffcc39'], motif: 'conversation' },
  explore: { colors: ['#ffb72f', '#39a875', '#ef6548'], motif: 'citrus' },
  recipes: { colors: ['#57d7ac', '#ffcf4a', '#ff6b58'], motif: 'pour' },
  studio: { colors: ['#f75d86', '#55cfe8', '#ffd34e'], motif: 'network' },
  lab: { colors: ['#6bd69e', '#ff6b58', '#70c9ed'], motif: 'experiment' },
  inventory: { colors: ['#e68b29', '#49ad78', '#f3cd4f'], motif: 'shelf' },
  moments: { colors: ['#f15f62', '#ffcb38', '#57cce6'], motif: 'celebration' },
  vision: { colors: ['#58c8e8', '#f16973', '#8ed36c'], motif: 'focus' },
  me: { colors: ['#4ab683', '#ffb641', '#e96a61'], motif: 'portrait' },
  admin: { colors: ['#58c9e7', '#f5c84c', '#6fc58c'], motif: 'signal' },
}
const themeKey = computed(() => route.path.split('/').filter(Boolean)[0] || 'chat')
const activeTheme = computed(() => themes[themeKey.value] || themes.chat)
let context, observer, frame = 0, width = 1, height = 1, dpr = 1, start = 0
let pointer = { x: .5, y: .5 }, scrollProgress = 0, interactionCount = 0
let marks = [], bursts = [], signals = [], reducedMotion = false, pageVisible = true
let businessInteractionCount = 0, lastBusinessEvent = 'idle', stopMotionListener = null

function hash(text = '') { let value = 2166136261; for (const char of text) value = Math.imul(value ^ char.charCodeAt(0), 16777619); return value >>> 0 }
function randomFactory(seed) { let state = seed || 1; return () => ((state = Math.imul(state ^ (state >>> 15), 1 | state) + 0x6d2b79f5) >>> 0) / 4294967296 }
function rebuildMarks() {
  const random = randomFactory(hash(route.path))
  const count = width < 600 ? 14 : Math.min(34, Math.max(20, Math.floor(width / 48)))
  marks = Array.from({ length: count }, (_, index) => ({
    x: random(), y: random(), size: 20 + random() * 54,
    angle: random() * Math.PI * 2, speed: .08 + random() * .22,
    phase: random() * Math.PI * 2, color: index % activeTheme.value.colors.length,
    kind: index % 4,
  }))
}
function strokePath(draw, color, widthValue = 1.3, alpha = .13) {
  context.save(); context.strokeStyle = color; context.lineWidth = widthValue
  context.globalAlpha = alpha; context.lineCap = 'round'; context.lineJoin = 'round'
  context.beginPath(); draw(); context.stroke(); context.restore()
}
function signalLifetime(kind) {
  if (kind === 'agent' || kind === 'stream') return 1500
  if (String(kind).startsWith('timer')) return kind === 'timer-complete' ? 1450 : 1250
  return 1100
}
function drawMark(mark, time) {
  const theme = activeTheme.value, color = theme.colors[mark.color]
  const drift = reducedMotion ? 0 : Math.sin(time * mark.speed + mark.phase) * 7
  const parallaxX = (pointer.x - .5) * (8 + mark.kind * 3), parallaxY = (pointer.y - .5) * 7
  const x = mark.x * width + drift + parallaxX, y = mark.y * height + Math.cos(time * mark.speed + mark.phase) * 5 + parallaxY
  const size = mark.size, motif = theme.motif
  context.save(); context.translate(x, y); context.rotate(mark.angle + Math.sin(time * .08 + mark.phase) * .08)
  if (motif === 'citrus' || motif === 'celebration') {
    strokePath(() => { context.arc(0, 0, size * .42, 0, Math.PI * 2); for (let i = 0; i < 6; i += 1) { const angle = i / 6 * Math.PI * 2; context.moveTo(0, 0); context.lineTo(Math.cos(angle) * size * .38, Math.sin(angle) * size * .38) } }, color, 1.5, .15)
  } else if (motif === 'network' || motif === 'signal') {
    strokePath(() => { context.moveTo(-size * .5, size * .2); context.bezierCurveTo(-size * .2, -size * .55, size * .16, size * .55, size * .5, -size * .2) }, color, 1.5, .16)
    for (const point of [-.5, 0, .5]) { context.fillStyle = color; context.globalAlpha = .19; context.fillRect(point * size - 2, (point ? -.2 : .05) * size - 2, 4, 4) }
  } else if (motif === 'experiment' || motif === 'focus') {
    strokePath(() => { context.moveTo(-size * .45, 0); for (let i = 0; i <= 12; i += 1) { const px = -size * .45 + i / 12 * size * .9; context.lineTo(px, Math.sin(i * 1.7 + mark.phase) * size * .12) } }, color, 1.4, .15)
    strokePath(() => context.arc(0, 0, size * .28, -.3, Math.PI * 1.2), color, 1, .09)
  } else if (motif === 'shelf' || motif === 'portrait') {
    strokePath(() => { context.moveTo(-size * .45, size * .34); context.lineTo(size * .45, size * .34); context.moveTo(-size * .2, size * .32); context.lineTo(-size * .14, -size * .35); context.quadraticCurveTo(0, -size * .5, size * .14, -size * .35); context.lineTo(size * .2, size * .32) }, color, 1.5, .14)
  } else if (motif === 'pour') {
    strokePath(() => { context.moveTo(-size * .46, -size * .34); context.bezierCurveTo(-size * .18, -size * .05, size * .12, size * .12, size * .42, size * .38) }, color, 1.8, .17)
    strokePath(() => context.arc(size * .42, size * .42, size * .08, 0, Math.PI * 1.65), color, 1.2, .12)
  } else {
    strokePath(() => { context.moveTo(-size * .5, 0); context.bezierCurveTo(-size * .2, -size * .38, size * .18, size * .4, size * .5, 0) }, color, 1.4, .14)
    strokePath(() => context.arc(size * .25, -size * .2, size * .12, .2, Math.PI * 1.7), color, 1.1, .1)
  }
  context.restore()
}
function drawSignal(signal, timestamp) {
  const lifetime = signalLifetime(signal.kind)
  const progress = Math.min(1, Math.max(0, (timestamp - signal.started) / lifetime))
  const fade = 1 - progress
  const color = activeTheme.value.colors[signal.color % activeTheme.value.colors.length]
  context.save()
  context.lineCap = 'round'; context.lineJoin = 'round'
  if (signal.kind === 'profile') {
    const source = String(signal.label || '5-5-5').split('-').map(Number)
    const scores = [source[0] || 5, source[1] || 5, source[2] || 5, ((source[0] || 5) + (source[2] || 5)) / 2, 10 - Math.abs((source[0] || 5) - (source[1] || 5)), ((source[1] || 5) + 10 - (source[2] || 5)) / 2]
    const values = scores.map(score => 24 + score * 5 + progress * 18)
    context.translate(signal.x, signal.y); context.rotate(progress * .22)
    strokePath(() => {
      values.forEach((radius, index) => {
        const angle = index / values.length * Math.PI * 2 - Math.PI / 2
        const x = Math.cos(angle) * radius, y = Math.sin(angle) * radius
        if (!index) context.moveTo(x, y); else context.lineTo(x, y)
      })
      context.closePath()
    }, color, 2, .36 * fade)
    values.forEach((radius, index) => {
      const angle = index / values.length * Math.PI * 2 - Math.PI / 2
      context.fillStyle = activeTheme.value.colors[index % activeTheme.value.colors.length]; context.globalAlpha = .45 * fade
      context.fillRect(Math.cos(angle) * radius - 2, Math.sin(angle) * radius - 2, 4, 4)
    })
  } else if (signal.kind === 'focus') {
    const radius = 22 + progress * 86
    context.translate(signal.x, signal.y)
    strokePath(() => { context.arc(0, 0, radius, 0, Math.PI * 2); context.arc(0, 0, radius * .55, 0, Math.PI * 2) }, color, 1.7, .32 * fade)
    strokePath(() => {
      context.moveTo(-radius - 14, 0); context.lineTo(-radius + 8, 0)
      context.moveTo(radius - 8, 0); context.lineTo(radius + 14, 0)
      context.moveTo(0, -radius - 14); context.lineTo(0, -radius + 8)
      context.moveTo(0, radius - 8); context.lineTo(0, radius + 14)
    }, activeTheme.value.colors[(signal.color + 1) % activeTheme.value.colors.length], 2, .42 * fade)
  } else if (signal.kind === 'recipe-motion') {
    const radius = 18 + progress * 78
    context.translate(signal.x, signal.y); context.rotate(progress * 1.2)
    for (let orbit = 0; orbit < 3; orbit += 1) {
      const scaleX = 1 + orbit * .18, scaleY = .42 + orbit * .16
      strokePath(() => context.ellipse(0, 0, radius * scaleX, radius * scaleY, orbit * .55, 0, Math.PI * 2), activeTheme.value.colors[(signal.color + orbit) % activeTheme.value.colors.length], 1.4 + orbit * .25, (.34 - orbit * .06) * fade)
      const angle = progress * Math.PI * (3.5 + orbit) + orbit * 2
      context.fillStyle = activeTheme.value.colors[(signal.color + orbit + 1) % activeTheme.value.colors.length]
      context.globalAlpha = .58 * fade; context.beginPath()
      context.arc(Math.cos(angle) * radius * scaleX, Math.sin(angle) * radius * scaleY, 3 + orbit, 0, Math.PI * 2); context.fill()
    }
  } else if (signal.kind === 'filter' || signal.kind === 'preview' || signal.kind === 'favorite') {
    const radius = 18 + progress * (signal.kind === 'preview' ? 105 : 72)
    context.translate(signal.x, signal.y); context.rotate(progress * .7)
    strokePath(() => {
      context.arc(0, 0, radius, 0, Math.PI * 2)
      for (let index = 0; index < 8; index += 1) {
        const angle = index / 8 * Math.PI * 2
        context.moveTo(radius * .28 * Math.cos(angle), radius * .28 * Math.sin(angle))
        context.lineTo(radius * .9 * Math.cos(angle), radius * .9 * Math.sin(angle))
      }
    }, color, 2.2, .32 * fade)
  } else if (signal.kind === 'experiment') {
    const radius = 16 + progress * 84
    context.translate(signal.x, signal.y)
    strokePath(() => {
      context.arc(0, 0, radius, -.7, Math.PI * (1.25 + progress * .45))
      context.arc(0, 0, radius * .58, Math.PI * .3, Math.PI * 1.7)
    }, color, 1.8, .33 * fade)
    strokePath(() => {
      context.moveTo(-radius, 0)
      for (let index = 0; index <= 18; index += 1) {
        const x = -radius + index / 18 * radius * 2
        context.lineTo(x, Math.sin(index * 1.45 + progress * 14) * (5 + progress * 13))
      }
    }, activeTheme.value.colors[(signal.color + 1) % activeTheme.value.colors.length], 2, .38 * fade)
  } else if (signal.kind === 'shelf-in' || signal.kind === 'shelf-out') {
    const direction = signal.kind === 'shelf-in' ? progress : 1 - progress
    const travel = direction * direction * (height * .5)
    const x = signal.x + Math.sin(progress * Math.PI * 2) * 24
    const y = Math.max(38, signal.y - height * .34) + travel
    strokePath(() => {
      context.moveTo(signal.x, Math.max(28, signal.y - height * .34))
      context.quadraticCurveTo(signal.x + 58, signal.y - 24, x, y)
    }, color, 1.4, .22 * fade)
    context.translate(x, y); context.rotate(Math.sin(progress * 8) * .12)
    context.fillStyle = color; context.globalAlpha = .19 + fade * .23
    context.fillRect(-7, -17, 14, 28); context.fillRect(-3, -23, 6, 7)
    context.strokeStyle = color; context.globalAlpha = .5 * fade; context.lineWidth = 1.5
    context.strokeRect(-7, -17, 14, 28); context.strokeRect(-3, -23, 6, 7)
  } else if (signal.kind === 'guest-count') {
    const count = Math.min(12, Math.max(1, Number(signal.label) || 1)), spacing = Math.min(18, width * .18 / count)
    context.translate(signal.x - (count - 1) * spacing / 2, signal.y)
    for (let index = 0; index < count; index += 1) {
      const rise = Math.sin(progress * Math.PI + index * .45) * (14 + index % 3 * 3)
      const x = index * spacing, y = -rise
      context.fillStyle = activeTheme.value.colors[(signal.color + index) % activeTheme.value.colors.length]
      context.globalAlpha = .55 * fade; context.beginPath(); context.arc(x, y - 7, 3.2, 0, Math.PI * 2); context.fill()
      context.fillRect(x - 3.8, y - 2, 7.6, 12)
    }
  } else if (['theme-open', 'context-ready', 'banquet-ready'].includes(signal.kind)) {
    for (const spark of signal.sparks) {
      const fall = progress * (55 + spark.speed * 120)
      const x = signal.x + spark.x * (35 + progress * 135)
      const y = signal.y + spark.y * 22 + fall
      context.save(); context.translate(x, y); context.rotate(spark.angle + progress * 5)
      context.strokeStyle = activeTheme.value.colors[spark.color]
      context.globalAlpha = fade * .65; context.lineWidth = 2
      context.beginPath(); context.moveTo(-spark.size, 0); context.lineTo(spark.size, 0); context.stroke(); context.restore()
    }
  } else if (signal.kind === 'agent' || signal.kind === 'stream' || signal.kind === 'agent-config') {
    const spread = Math.min(170, width * .2), pulse = .5 + Math.sin(progress * Math.PI * 7) * .5
    const nodes = [[signal.x - spread, signal.y + 24], [signal.x, signal.y - 28], [signal.x + spread, signal.y + 18]]
    strokePath(() => {
      context.moveTo(nodes[0][0], nodes[0][1]); context.quadraticCurveTo(signal.x - 42, signal.y - 55, nodes[1][0], nodes[1][1])
      context.quadraticCurveTo(signal.x + 45, signal.y - 48, nodes[2][0], nodes[2][1])
    }, color, 1.5 + pulse, .18 + fade * .25)
    nodes.forEach(([x, y], index) => {
      context.fillStyle = activeTheme.value.colors[(signal.color + index) % activeTheme.value.colors.length]
      context.globalAlpha = .28 + fade * .32; context.beginPath(); context.arc(x, y, 3 + pulse * 4, 0, Math.PI * 2); context.fill()
    })
    if (signal.kind === 'stream') {
      strokePath(() => {
        context.moveTo(signal.x - spread, signal.y + 50)
        for (let index = 0; index <= 22; index += 1) {
          const x = signal.x - spread + index / 22 * spread * 2
          context.lineTo(x, signal.y + 50 + Math.sin(index * 1.35 + progress * 18) * (4 + pulse * 7))
        }
      }, activeTheme.value.colors[(signal.color + 1) % activeTheme.value.colors.length], 1.8, .28 * fade)
    }
  } else if (String(signal.kind).startsWith('timer')) {
    const stateProgress = signal.kind === 'timer-complete' ? 1 : signal.kind === 'timer-reset' ? 0 : Math.min(1, Math.max(0, Number(signal.value) || 0) + progress * .16)
    const radius = 24 + progress * 34
    const handAngle = -Math.PI / 2 + stateProgress * Math.PI * 2
    context.translate(signal.x, signal.y); context.rotate(Math.sin(progress * Math.PI) * .05)
    strokePath(() => {
      context.arc(0, 0, radius, 0, Math.PI * 2)
      context.moveTo(radius * .68, 0); context.arc(0, 0, radius * .68, 0, Math.PI * 2)
    }, color, 1.6, .22 * fade)
    strokePath(() => context.arc(0, 0, radius, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * stateProgress), activeTheme.value.colors[(signal.color + 1) % activeTheme.value.colors.length], 3, .54 * fade)
    strokePath(() => {
      for (let index = 0; index < 12; index += 1) {
        const angle = index / 12 * Math.PI * 2
        context.moveTo(Math.cos(angle) * radius * .78, Math.sin(angle) * radius * .78)
        context.lineTo(Math.cos(angle) * radius * .91, Math.sin(angle) * radius * .91)
      }
      context.moveTo(0, 0)
      context.lineTo(Math.cos(handAngle) * radius * .58, Math.sin(handAngle) * radius * .58)
    }, color, 1.8, .44 * fade)
    context.fillStyle = activeTheme.value.colors[(signal.color + 2) % activeTheme.value.colors.length]
    context.globalAlpha = .55 * fade; context.beginPath(); context.arc(0, 0, 4, 0, Math.PI * 2); context.fill()
    if (signal.kind === 'timer-complete') {
      signal.sparks.slice(0, 12).forEach((spark, index) => {
        const angle = index / 12 * Math.PI * 2 + progress * .35
        const distance = radius + progress * (18 + spark.speed * 24)
        context.fillStyle = activeTheme.value.colors[spark.color]
        context.globalAlpha = fade * .55; context.fillRect(Math.cos(angle) * distance - 2, Math.sin(angle) * distance - 2, 4, 4)
      })
    }
  } else if (signal.kind === 'complete' || signal.kind === 'error') {
    const spokes = signal.kind === 'complete' ? 12 : 7
    context.translate(signal.x, signal.y)
    strokePath(() => {
      for (let index = 0; index < spokes; index += 1) {
        const angle = index / spokes * Math.PI * 2
        const inner = 12 + progress * 26, outer = inner + 16 + progress * 45
        context.moveTo(Math.cos(angle) * inner, Math.sin(angle) * inner)
        context.lineTo(Math.cos(angle) * outer, Math.sin(angle) * outer)
      }
    }, signal.kind === 'error' ? '#ef6548' : color, 2, .38 * fade)
  }
  context.restore()
}
function scheduleDraw() {
  if (!context || !canvas.value || !pageVisible) return
  if (reducedMotion) { draw(performance.now()); return }
  if (!frame) frame = requestAnimationFrame(draw)
}
function draw(timestamp = 0) {
  frame = 0
  if (!context || !canvas.value || !pageVisible) return
  const time = (timestamp - start) * .001
  context.clearRect(0, 0, width, height)
  for (const mark of marks) drawMark(mark, time)
  bursts = bursts.filter(burst => timestamp - burst.started < 900)
  for (const burst of bursts) {
    const progress = Math.min(1, (timestamp - burst.started) / 900)
    const radius = 10 + progress * 72
    strokePath(() => context.arc(burst.x, burst.y, radius, -.4, Math.PI * (1.2 + progress * .5)), activeTheme.value.colors[burst.color], 1.8 - progress, .24 * (1 - progress))
  }
  signals = signals.filter(signal => timestamp - signal.started < signalLifetime(signal.kind))
  for (const signal of signals) drawSignal(signal, timestamp)
  canvas.value.dataset.animationReady = 'true'
  canvas.value.dataset.theme = activeTheme.value.motif
  canvas.value.dataset.doodleCount = String(marks.length)
  canvas.value.dataset.interactionCount = String(interactionCount)
  canvas.value.dataset.businessInteractionCount = String(businessInteractionCount)
  canvas.value.dataset.lastBusinessEvent = lastBusinessEvent
  canvas.value.dataset.activeSignals = String(signals.length)
  if (!reducedMotion) frame = requestAnimationFrame(draw)
}
function resize() {
  if (!host.value || !canvas.value) return
  const rect = host.value.getBoundingClientRect(); width = Math.max(1, rect.width); height = Math.max(1, rect.height)
  dpr = Math.min(window.devicePixelRatio || 1, 2); canvas.value.width = Math.round(width * dpr); canvas.value.height = Math.round(height * dpr)
  canvas.value.style.width = `${width}px`; canvas.value.style.height = `${height}px`
  context.setTransform(dpr, 0, 0, dpr, 0, 0); rebuildMarks(); scheduleDraw()
}
function pointerMove(event) { pointer = { x: event.clientX / Math.max(1, window.innerWidth), y: event.clientY / Math.max(1, window.innerHeight) }; if (reducedMotion) scheduleDraw() }
function pointerDown(event) { const rect = host.value.getBoundingClientRect(); interactionCount += 1; bursts.push({ x: event.clientX - rect.left, y: event.clientY - rect.top, started: performance.now(), color: interactionCount % activeTheme.value.colors.length }); if (reducedMotion) scheduleDraw() }
function scroll() { const max = Math.max(1, document.documentElement.scrollHeight - window.innerHeight); scrollProgress = Math.min(1, window.scrollY / max); host.value?.style.setProperty('--scroll-progress', String(scrollProgress)) }
function businessMotion(event) {
  const detail = event.detail || {}, kind = detail.kind || 'interaction'
  const random = randomFactory(hash(`${kind}-${detail.label || ''}-${businessInteractionCount}`))
  businessInteractionCount += 1; lastBusinessEvent = kind
  signals.push({
    kind, label: detail.label || '', value: Number(detail.progress || 0), started: performance.now(), color: businessInteractionCount % activeTheme.value.colors.length,
    x: width * (.28 + random() * .44), y: height * (.18 + random() * .35),
    sparks: Array.from({ length: width < 600 ? 12 : 22 }, (_, index) => ({
      x: random() * 2 - 1, y: random() * 2 - 1, speed: .25 + random(),
      angle: random() * Math.PI * 2, size: 2 + random() * 5,
      color: index % activeTheme.value.colors.length,
    })),
  })
  if (signals.length > 8) signals.splice(0, signals.length - 8)
  scheduleDraw()
}
function visibilityChange() {
  pageVisible = !document.hidden
  if (pageVisible) scheduleDraw()
  else { cancelAnimationFrame(frame); frame = 0 }
}

onMounted(() => {
  reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  context = canvas.value.getContext('2d'); start = performance.now()
  observer = new ResizeObserver(resize); observer.observe(host.value)
  window.addEventListener('pointermove', pointerMove, { passive: true }); window.addEventListener('pointerdown', pointerDown, { passive: true }); window.addEventListener('scroll', scroll, { passive: true })
  document.addEventListener('visibilitychange', visibilityChange); stopMotionListener = onMotion(businessMotion)
  resize(); scroll()
})
watch(() => route.fullPath, () => { rebuildMarks(); bursts = []; signals = []; scheduleDraw() })
onBeforeUnmount(() => { cancelAnimationFrame(frame); observer?.disconnect(); stopMotionListener?.(); document.removeEventListener('visibilitychange', visibilityChange); window.removeEventListener('pointermove', pointerMove); window.removeEventListener('pointerdown', pointerDown); window.removeEventListener('scroll', scroll) })
</script>

<template>
  <div ref="host" class="mixology-atmosphere" aria-hidden="true">
    <canvas ref="canvas" />
    <span class="motion-rail"><i /></span>
  </div>
</template>

<style scoped>
.mixology-atmosphere{--scroll-progress:0;position:fixed;inset:0 0 0 232px;z-index:0;pointer-events:none;overflow:hidden}.mixology-atmosphere canvas{display:block;width:100%;height:100%}.motion-rail{position:absolute;right:9px;top:12vh;width:2px;height:76vh;background:#19231f12}.motion-rail i{display:block;width:2px;height:calc(var(--scroll-progress) * 100%);min-height:10px;background:#ef6548;box-shadow:0 7px 0 #ffcc39;transition:height .12s linear}@media(max-width:720px){.mixology-atmosphere{left:0;bottom:64px}.motion-rail{right:3px}}@media(prefers-reduced-motion:reduce){.motion-rail i{transition:none}}
</style>
