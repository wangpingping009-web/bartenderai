<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Pause, Play, RotateCcw } from 'lucide-vue-next'

const props = defineProps({
  seconds: { type: Number, default: 15 },
  label: { type: String, default: '摇匀计时' },
})
const emit = defineEmits(['update', 'complete'])

const totalMs = computed(() => Math.max(1, Number(props.seconds) || 15) * 1000)
const remainingMs = ref(totalMs.value)
const running = ref(false)
const complete = ref(false)
let frame = 0, finishHandle = 0, deadline = 0, lastPaint = 0

const left = computed(() => Math.max(0, Math.ceil(remainingMs.value / 1000)))
const progress = computed(() => Math.min(1, Math.max(0, 1 - remainingMs.value / totalMs.value)))
const display = computed(() => `${String(Math.floor(left.value / 60)).padStart(2, '0')}:${String(left.value % 60).padStart(2, '0')}`)
const circumference = 2 * Math.PI * 33
const dashOffset = computed(() => circumference * (1 - progress.value))

function snapshot() {
  return {
    running: running.value,
    left: left.value,
    progress: Number(progress.value.toFixed(4)),
    complete: complete.value,
  }
}
function publish() { emit('update', snapshot()) }
function clearAnimations() {
  cancelAnimationFrame(frame); frame = 0
  window.clearTimeout(finishHandle); finishHandle = 0
}
function finish() {
  if (!running.value) return
  clearAnimations()
  remainingMs.value = 0
  running.value = false
  complete.value = true
  publish()
  emit('complete', snapshot())
}
function tick(now) {
  frame = 0
  if (!running.value) return
  const next = Math.max(0, deadline - now)
  if (next <= 0) { finish(); return }
  if (now - lastPaint >= 50) {
    remainingMs.value = next
    lastPaint = now
    publish()
  }
  frame = requestAnimationFrame(tick)
}
function start() {
  if (complete.value || remainingMs.value <= 0) remainingMs.value = totalMs.value
  complete.value = false
  running.value = true
  deadline = performance.now() + remainingMs.value
  lastPaint = 0
  publish()
  finishHandle = window.setTimeout(finish, remainingMs.value + 30)
  frame = requestAnimationFrame(tick)
}
function pause() {
  remainingMs.value = Math.max(0, deadline - performance.now())
  running.value = false
  clearAnimations()
  publish()
}
function toggle() { running.value ? pause() : start() }
function reset() {
  clearAnimations()
  running.value = false
  complete.value = false
  remainingMs.value = totalMs.value
  publish()
}
function syncVisibility() {
  if (running.value && !document.hidden) {
    cancelAnimationFrame(frame); frame = 0
    tick(performance.now())
  }
}

watch(() => props.seconds, reset)
onMounted(() => {
  document.addEventListener('visibilitychange', syncVisibility)
  publish()
})
onBeforeUnmount(() => {
  clearAnimations()
  document.removeEventListener('visibilitychange', syncVisibility)
})
</script>

<template>
  <div
    class="mix-timer"
    :class="{ running, complete }"
    :style="{ '--timer-progress': progress }"
    :data-running="String(running)"
    :data-progress="progress.toFixed(3)"
    :data-complete="String(complete)"
  >
    <div class="timer-dial">
      <svg viewBox="0 0 84 84" aria-hidden="true">
        <circle class="dial-track" cx="42" cy="42" r="33" />
        <circle
          class="dial-progress"
          cx="42"
          cy="42"
          r="33"
          :style="{ strokeDasharray: circumference, strokeDashoffset: dashOffset }"
        />
        <circle class="dial-orbit" cx="42" cy="9" r="3" />
      </svg>
      <strong role="timer" :aria-label="`${label}，剩余 ${left} 秒`">{{ display }}</strong>
    </div>
    <div class="timer-copy">
      <small>{{ label }}</small>
      <span>{{ complete ? '时间到，可以检查酒液状态' : running ? '酒体正在响应这个步骤' : progress > 0 ? '已暂停，节奏会从这里继续' : '准备好后开始' }}</span>
    </div>
    <div class="timer-actions">
      <button class="timer-action primary" type="button" @click="toggle" :aria-label="running ? '暂停计时' : '开始计时'" :title="running ? '暂停计时' : '开始计时'">
        <Pause v-if="running" :size="18" />
        <Play v-else :size="18" />
      </button>
      <button class="timer-action" type="button" @click="reset" aria-label="重置计时" title="重置计时"><RotateCcw :size="17" /></button>
    </div>
  </div>
</template>

<style scoped>
.mix-timer{--timer-color:#ef6548;position:relative;display:grid;grid-template-columns:76px minmax(0,1fr) auto;align-items:center;gap:12px;min-height:92px;padding:8px 10px 8px 7px;border:1px solid #e3e9e4;background:linear-gradient(105deg,#f8faf8 0 62%,#fff6df 100%);overflow:hidden}.mix-timer::after{content:"";position:absolute;left:78px;right:76px;bottom:0;height:3px;transform:scaleX(var(--timer-progress));transform-origin:left;background:var(--timer-color)}.mix-timer.running{--timer-color:#2f9b6b;box-shadow:inset 0 0 0 1px #47b98428}.mix-timer.complete{--timer-color:#ed9f20;background:linear-gradient(105deg,#fffaf0,#edf8f1)}.timer-dial{position:relative;width:76px;height:76px;display:grid;place-items:center}.timer-dial svg{position:absolute;inset:0;width:100%;height:100%;transform:rotate(-90deg);overflow:visible}.timer-dial circle{fill:none}.dial-track{stroke:#dce4df;stroke-width:5}.dial-progress{stroke:var(--timer-color);stroke-width:5;stroke-linecap:round;transition:stroke-dashoffset .08s linear,stroke .2s}.dial-orbit{fill:var(--timer-color);stroke:#fff;stroke-width:2;transform-origin:42px 42px;transform:rotate(calc(var(--timer-progress) * 360deg));transition:transform .08s linear}.timer-dial strong{position:relative;font-size:15px;font-variant-numeric:tabular-nums;color:#202824}.timer-copy{min-width:0;display:grid;gap:4px}.timer-copy small{font-weight:800;color:#293a32}.timer-copy span{color:var(--muted);font-size:10px;line-height:1.45}.timer-actions{display:flex;gap:6px}.timer-action{width:35px;height:35px;border:1px solid #d9e1dc;background:#fff;color:#4b5c54;display:grid;place-items:center;border-radius:50%;transition:transform .18s,background .18s,color .18s}.timer-action:hover{transform:translateY(-2px) rotate(-3deg);color:var(--timer-color)}.timer-action.primary{background:var(--timer-color);border-color:var(--timer-color);color:#fff}.mix-timer.running .timer-dial{animation:timer-breathe 1.3s ease-in-out infinite}.mix-timer.complete .timer-dial{animation:timer-finish .65s ease-out both}@keyframes timer-breathe{50%{transform:scale(1.035)}}@keyframes timer-finish{45%{transform:scale(1.12) rotate(4deg)}100%{transform:scale(1)}}@media(max-width:480px){.mix-timer{grid-template-columns:68px minmax(0,1fr);padding-right:8px}.timer-dial{width:68px;height:68px}.timer-actions{grid-column:2;justify-self:start}.timer-copy span{max-width:25ch}}@media(prefers-reduced-motion:reduce){.mix-timer.running .timer-dial,.mix-timer.complete .timer-dial{animation:none}.dial-progress,.dial-orbit,.timer-action{transition:none}.timer-action:hover{transform:none}}
</style>
