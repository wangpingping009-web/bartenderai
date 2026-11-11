<template>
  <div class="panel">
    <div v-for="t in themes" :key="t.key" class="theme" @click="expanded = expanded === t.key ? '' : t.key">
      <div class="row">
        <span class="emoji">{{ t.emoji }}</span>
        <div class="meta">
          <div class="name">{{ t.name }} <el-tag size="small" effect="plain">{{ t.count }} 款</el-tag></div>
          <div class="vibe">{{ t.vibe }}</div>
        </div>
      </div>

      <div v-if="expanded === t.key" class="detail" @click.stop>
        <div v-for="r in detail?.recommendations || []" :key="r.name" class="rec">
          <div class="rec-head"><b>{{ r.name }}</b><em>{{ r.spirit }} · {{ r.glass }}</em></div>
          <div class="why">💬 {{ r.why }}</div>
          <div class="tags">
            <el-tag v-for="f in r.flavor" :key="f" size="small" type="success" effect="plain">{{ f }}</el-tag>
          </div>
        </div>
        <div v-if="detail?.tips" class="tips">📌 {{ detail.tips }}</div>
        <el-button type="primary" size="small" class="ask" @click="ask(t)">
          发给调酒师定制完整酒单
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'

const emit = defineEmits(['ask'])
const themes = ref([])
const expanded = ref('')
const detail = ref(null)

async function load() {
  try { themes.value = await api.themes.list() }
  catch (_) { themes.value = [] }
}

async function expand(key) {
  if (expanded.value === key) { expanded.value = ''; return }
  expanded.value = key
  detail.value = await api.themes.get(key)
}

function ask(t) {
  emit('ask', `来一份「${t.name}」主题酒单，帮我按 ${t.count} 款安排，结合我的库存和口味调整`)
}

onMounted(load)
</script>

<style scoped>
.panel { padding: 4px; }
.theme { border: 1px solid #eee; border-radius: 10px; padding: 10px 12px; margin-bottom: 10px; cursor: pointer; }
.theme:hover { border-color: #5b8c5a; }
.row { display: flex; gap: 10px; align-items: center; }
.emoji { font-size: 26px; }
.meta { flex: 1; }
.name { font-size: 14px; font-weight: 600; }
.vibe { font-size: 12px; color: #999; margin-top: 2px; }
.detail { margin-top: 10px; border-top: 1px dashed #eee; padding-top: 10px; }
.rec { margin-bottom: 10px; }
.rec-head { display: flex; justify-content: space-between; font-size: 13px; }
.rec-head em { font-style: normal; color: #999; font-size: 12px; }
.why { font-size: 12px; color: #666; margin: 3px 0; }
.tags { display: flex; gap: 4px; }
.tips { font-size: 12px; color: #8a6d3b; background: #fdf8e8; border-radius: 6px; padding: 6px 8px; margin: 8px 0; }
.ask { width: 100%; }
</style>
