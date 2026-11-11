<template>
  <div class="panel">
    <div class="slider-row" v-for="row in sliders" :key="row.key">
      <div class="row-head">
        <span>{{ row.label }}</span>
        <span class="val">{{ profile[row.key] ?? '未设置' }}</span>
      </div>
      <el-slider v-model="bindings[row.key]" :min="0" :max="10" :show-stops="false" size="small" />
    </div>

    <div class="tag-row">
      <div class="row-head"><span>偏好基酒</span></div>
      <el-tag v-for="(p, i) in profile.preferred_spirits" :key="i" closable size="small"
              class="tag" @close="profile.preferred_spirits.splice(i, 1)">{{ p }}</el-tag>
      <el-input v-model="newPreferred" size="small" placeholder="如 gin" class="mini"
                @keyup.enter="pushPreferred" />
    </div>

    <div class="tag-row">
      <div class="row-head"><span>忌口材料</span></div>
      <el-tag v-for="(d, i) in profile.disliked_ingredients" :key="i" closable size="small"
              type="danger" class="tag" @close="profile.disliked_ingredients.splice(i, 1)">{{ d }}</el-tag>
      <el-input v-model="newDisliked" size="small" placeholder="如 vodka" class="mini"
                @keyup.enter="pushDisliked" />
    </div>

    <el-button type="primary" class="save" @click="save">保存画像</el-button>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'

const props = defineProps({ userId: { type: String, required: true } })
const emit = defineEmits(['changed'])

const sliders = [
  { key: 'sweetness', label: '甜度偏好' },
  { key: 'sourness', label: '酸度偏好' },
  { key: 'strong', label: '酒精度偏好' },
]

// 滑块值映射：null（未设置）→ 0 显示；拖动即写入真实值
function slider(key) {
  return computed({
    get: () => profile.value[key] ?? 0,
    set: (v) => { profile.value[key] = v },
  })
}
const bindings = {
  sweetness: slider('sweetness'),
  sourness: slider('sourness'),
  strong: slider('strong'),
}
const profile = ref({ sweetness: null, sourness: null, strong: null, preferred_spirits: [], disliked_ingredients: [] })
const newPreferred = ref('')
const newDisliked = ref('')

function pushPreferred() {
  const v = newPreferred.value.trim()
  if (v && !profile.value.preferred_spirits.includes(v)) profile.value.preferred_spirits.push(v)
  newPreferred.value = ''
}
function pushDisliked() {
  const v = newDisliked.value.trim()
  if (v && !profile.value.disliked_ingredients.includes(v)) profile.value.disliked_ingredients.push(v)
  newDisliked.value = ''
}

async function load() {
  try {
    const p = await api.profile.get(props.userId)
    profile.value = { sweetness: null, sourness: null, strong: null,
                      preferred_spirits: [], disliked_ingredients: [], ...p }
  } catch (_) { /* 后端未启动 */ }
}

async function save() {
  try {
    await api.profile.update(props.userId, profile.value)
    ElMessage.success('画像已保存，之后的推荐会参考它')
    emit('changed')
  } catch (e) { ElMessage.error(e.message) }
}

watch(() => props.userId, load)
onMounted(load)
</script>

<style scoped>
.panel { padding: 4px; }
.slider-row { margin-bottom: 8px; }
.row-head { display: flex; justify-content: space-between; font-size: 13px; color: #555; margin-bottom: 4px; }
.row-head .val { color: #5b8c5a; font-weight: 600; }
.tag-row { margin: 12px 0; }
.tag { margin-right: 6px; margin-bottom: 6px; }
.mini { width: 110px; }
.save { margin-top: 12px; width: 100%; }
</style>
