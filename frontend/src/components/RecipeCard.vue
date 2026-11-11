<template>
  <div class="card">
    <div class="head">
      <div class="name">{{ recipe.name || '配方' }}</div>
      <el-button v-if="!readonly" :type="saved ? 'warning' : 'default'" size="small" circle
                 :icon="saved ? StarFilled : Star" @click.stop="toggleFavorite" />
    </div>

    <div class="tags">
      <el-tag v-if="recipe.spirit_base" size="small" type="success">🥃 {{ recipe.spirit_base }}</el-tag>
      <el-tag v-if="recipe.glass" size="small" type="info">🍸 {{ recipe.glass }}</el-tag>
      <el-tag v-if="recipe.garnish" size="small" type="info">🌿 {{ recipe.garnish }}</el-tag>
      <el-tag :type="recipe.is_alcoholic ? 'danger' : 'success'" size="small">
        {{ recipe.is_alcoholic ? `${alcoholText} 含酒精` : '零酒精' }}
      </el-tag>
    </div>

    <div class="body">
      <div class="flavor">
        <svg :viewBox="`0 0 120 120`" class="radar">
          <polygon :points="gridPoints(1.0)" fill="none" stroke="#eee" />
          <polygon :points="gridPoints(0.5)" fill="none" stroke="#f0f0f0" stroke-dasharray="3,3" />
          <polygon :points="gridPoints(1.0)" fill="none" stroke="#ddd" />
          <polygon :points="valuePoints" fill="rgba(91,140,90,.25)" stroke="#5b8c5a" stroke-width="1.5" />
          <circle v-for="(p, i) in axisPoints(1.0)" :key="i" :cx="p[0]" :cy="p[1]" r="1.5" fill="#ccc" />
          <text v-for="(p, i) in axisPoints(1.18)" :key="'t'+i" :x="p[0]" :y="p[1]"
                text-anchor="middle" font-size="8" fill="#888">{{ axisLabels[i] }}</text>
        </svg>
      </div>

      <div class="recipe-info">
        <div v-if="recipe.ingredients.length" class="block">
          <div class="label">材料</div>
          <ul>
            <li v-for="(ing, i) in recipe.ingredients" :key="i">
              <span>{{ ing.name }}</span><em>{{ ing.amount }}</em>
            </li>
          </ul>
        </div>
        <div v-if="recipe.steps.length" class="block">
          <div class="label">步骤</div>
          <ol>
            <li v-for="(s, i) in recipe.steps" :key="i">{{ s }}</li>
          </ol>
        </div>
        <div v-if="recipe.tips" class="block tip">💡 {{ recipe.tips }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Star, StarFilled } from '@element-plus/icons-vue'
import { api } from '../api'

const props = defineProps({
  recipe: { type: Object, required: true },
  userId: { type: String, default: 'guest' },
  readonly: { type: Boolean, default: false },
})

const axisLabels = ['甜', '酸', '苦', '烈', '酒体', '香气']
const saved = ref(false)

const alcoholText = computed(() => {
  const u = props.recipe.alcohol_units
  return u ? `${u} 单位` : ''
})

// 六轴坐标：角度 -90° 起，每 60° 一轴
function points(r, values) {
  const cx = 60, cy = 60
  return axisLabels.map((_, i) => {
    const v = values ? (values[i] ?? 0) : 1
    const ang = -Math.PI / 2 + (i * Math.PI) / 3
    return [cx + r * v * Math.cos(ang), cy + r * v * Math.sin(ang)]
  })
}
function gridPoints(scale) {
  return points(50 * scale, null).map(p => p.join(',')).join(' ')
}
function axisPoints(scale) {
  return points(50 * scale, null)
}
const valuePoints = computed(() => {
  const f = props.recipe.flavor || {}
  const vals = [f.sweet, f.sour, f.bitter, f.strong, f.body, f.aroma].map(n => (n ?? 0) / 10)
  return points(50, vals).map(p => p.join(',')).join(' ')
})

async function checkSaved() {
  if (props.readonly) return
  try {
    const favs = await api.favorites.list(props.userId)
    saved.value = favs.some(f => f.name === props.recipe.name)
  } catch (_) { saved.value = false }
}
async function toggleFavorite() {
  try {
    if (saved.value) {
      await api.favorites.remove(props.userId, props.recipe.name)
      saved.value = false
      ElMessage.success('已取消收藏')
    } else {
      await api.favorites.add(props.userId, props.recipe)
      saved.value = true
      ElMessage.success('已收藏到「我的收藏」')
    }
  } catch (e) { ElMessage.error(e.message) }
}

watch(() => props.recipe?.name, checkSaved, { immediate: true })
</script>

<style scoped>
.card {
  background: #fff; border: 1px solid #eee; border-radius: 12px; padding: 14px 16px;
  margin-top: 10px; box-shadow: 0 2px 6px rgba(0,0,0,.04);
}
.head { display: flex; justify-content: space-between; align-items: center; }
.name { font-size: 17px; font-weight: 700; color: #333; }
.tags { display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0; }
.body { display: flex; gap: 16px; }
.flavor { flex-shrink: 0; width: 130px; }
.radar { width: 130px; height: 130px; }
.recipe-info { flex: 1; min-width: 0; }
.block { margin-bottom: 10px; }
.label { font-size: 12px; color: #999; margin-bottom: 4px; font-weight: 600; }
.block ul, .block ol { margin: 0; padding-left: 18px; font-size: 13px; color: #444; line-height: 1.8; }
.block ul li { display: flex; justify-content: space-between; border-bottom: 1px dashed #f0f0f0; }
.block ul em { font-style: normal; color: #5b8c5a; }
.tip { color: #8a6d3b; background: #fdf8e8; border-radius: 6px; padding: 6px 8px; font-size: 12px; }
@media (max-width: 560px) { .body { flex-direction: column; } }
</style>
