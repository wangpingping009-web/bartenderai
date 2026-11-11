<template>
  <div class="panel">
    <div class="quick">
      <div v-for="g in groups" :key="g.label" class="group">
        <div class="label">{{ g.label }}（点一下添加）</div>
        <div class="chips">
          <el-tag v-for="s in g.items" :key="s" class="chip" effect="plain" @click="add(s)">
            +{{ s }}
          </el-tag>
        </div>
      </div>

      <div class="label combos-label">🍹 一键加齐经典配方</div>
      <div class="chips">
        <el-tag v-for="c in combos" :key="c.label" class="chip combo" effect="dark" @click="addCombo(c)">
          {{ c.label }}
        </el-tag>
      </div>
    </div>

    <el-input v-model="newItem" placeholder="手动添加，如 苦艾酒" size="small"
              @keyup.enter="add(newItem)">
      <template #append>
        <el-button @click="add(newItem)">添加</el-button>
      </template>
    </el-input>

    <div v-if="items.length" class="list">
      <el-tag v-for="(it, i) in items" :key="i" closable class="item" @close="remove(it)">
        {{ it }}
      </el-tag>
    </div>
    <div v-else class="empty">库存为空，先添加你手头的酒水配料吧</div>
  </div>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'
import { api } from '../api'

const props = defineProps({ userId: { type: String, required: true } })
const emit = defineEmits(['changed'])

// 按类别分组展示，找起来快
const groups = [
  { label: '基酒', items: ['威士忌', '金酒', '朗姆', '伏特加', '龙舌兰', '白兰地'] },
  { label: '利口酒 / 苦精', items: ['甜味美思', '干味美思', '苦精', '君度', '杏仁利口酒'] },
  { label: '新鲜 / 配料', items: ['柠檬', '青柠', '薄荷', '糖浆', '蛋清', '汤力水', '苏打水', '橙皮'] },
]
// 一键加齐：经典配方所需材料（点击自动全加）
const combos = [
  { label: '莫吉托', items: ['朗姆', '青柠', '薄荷', '糖浆', '苏打水'] },
  { label: '威士忌酸', items: ['威士忌', '柠檬', '糖浆', '蛋清'] },
  { label: '金汤力', items: ['金酒', '汤力水', '青柠'] },
  { label: '玛格丽特', items: ['龙舌兰', '君度', '青柠'] },
]

const items = ref([])
const newItem = ref('')

async function load() {
  try { items.value = (await api.inventory.get(props.userId)).items }
  catch (_) { /* 后端未启动 */ }
}

async function add(name) {
  name = (name || '').trim()
  if (!name) return
  newItem.value = ''
  await api.inventory.add(props.userId, name)
  await load()
  emit('changed')
}

async function addCombo(c) {
  for (const n of c.items) {
    if (!items.value.includes(n)) {
      await api.inventory.add(props.userId, n).catch(() => {})
    }
  }
  await load()
  emit('changed')
}

async function remove(name) {
  await api.inventory.remove(props.userId, name)
  await load()
  emit('changed')
}

watch(() => props.userId, load)
onMounted(load)
</script>

<style scoped>
.panel { padding: 4px; }
.group { margin-bottom: 8px; }
.label { font-size: 12px; color: #999; margin-bottom: 5px; }
.combos-label { margin-top: 12px; }
.chips { display: flex; flex-wrap: wrap; gap: 4px; }
.chip { cursor: pointer; margin: 0; }
.combo { background: #5b8c5a !important; border-color: #5b8c5a !important; }
.list { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }
.item { margin: 0; }
.empty { font-size: 12px; color: #bbb; margin-top: 12px; text-align: center; padding: 12px 0; }
</style>
