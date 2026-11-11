<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowLeft, Check, ChevronRight, Download, Heart, Image as ImageIcon, RotateCcw, Sparkles, Star } from 'lucide-vue-next'
import { api } from '../api'
import FlavorRadar from '../components/FlavorRadar.vue'
import MixTimer from '../components/MixTimer.vue'
import CocktailParticleScene from '../components/CocktailParticleScene.vue'
import { emitMotion } from '../motion'

const route = useRoute()
const recipe = ref(null), loading = ref(true), error = ref(''), favorite = ref(false), rating = ref(0), tags = ref([]), note = ref(''), saved = ref(false)
const imageLoaded = ref(false), imageFailed = ref(false)
const mediaMode = ref('particles'), sceneUnavailable = ref(false)
const activeStep = ref(0), completed = ref(new Set()), ingredientsReady = ref(new Set())
const highlightedIngredient = ref(-1)
const timerState = ref({ running: false, left: 0, progress: 0, complete: false })
const categoryLabels = { Cocktail: '鸡尾酒', 'Ordinary Drink': '经典与日常', Shot: '短饮', 'Punch / Party Drink': '宾治与聚会酒', 'Homemade Liqueur': '自制利口酒' }
const glassLabels = { 'cocktail glass': '鸡尾酒杯', 'martini glass': '马天尼杯', 'highball glass': '高球杯', 'collins glass': '柯林杯', 'shot glass': '烈酒杯', 'old-fashioned glass': '古典杯', 'champagne flute': '香槟笛形杯', 'wine glass': '葡萄酒杯' }
const steps = computed(() => recipe.value?.steps?.length ? recipe.value.steps : (recipe.value?.instructions || '').split(/[。.!]\s*/).filter(Boolean))
const progress = computed(() => steps.value.length ? Math.round(completed.value.size / steps.value.length * 100) : 0)
const categoryLabel = computed(() => categoryLabels[recipe.value?.category] || recipe.value?.category || '其他配方')
const glassLabel = computed(() => glassLabels[(recipe.value?.glass || '').toLowerCase()] || recipe.value?.glass || '合适杯具')

onMounted(async () => {
  try {
    const [item, favs] = await Promise.all([api.recipes.get(route.params.id), api.me.favorites()])
    recipe.value = item; favorite.value = favs.items.some(entry => entry.name === item.name)
  } catch (e) { error.value = e.message } finally { loading.value = false }
})
async function toggleFavorite() { if (favorite.value) await api.me.removeFavorite(recipe.value.name); else await api.me.addFavorite(recipe.value); favorite.value = !favorite.value }
async function feedback() { await api.feedback({ recipe_id: recipe.value.id, recipe_name: recipe.value.name, rating: rating.value, tags: tags.value, note: note.value }); saved.value = true }
function toggleIngredient(index) { ingredientsReady.value.has(index) ? ingredientsReady.value.delete(index) : ingredientsReady.value.add(index); ingredientsReady.value = new Set(ingredientsReady.value) }
function resetTimerState() { timerState.value = { running: false, left: 0, progress: 0, complete: false } }
function onTimerUpdate(next) {
  const previous = timerState.value
  timerState.value = next
  const detail = { label: recipe.value?.timer_label || '调制计时', progress: next.progress, step: activeStep.value }
  if (next.running && !previous.running) emitMotion('timer', detail)
  else if (!next.running && previous.running && !next.complete) emitMotion('timer-pause', detail)
  else if (!next.running && next.progress === 0 && previous.progress > 0) emitMotion('timer-reset', detail)
}
function onTimerComplete(next) {
  timerState.value = next
  emitMotion('timer-complete', { label: recipe.value?.timer_label || '调制计时', progress: 1, step: activeStep.value })
}
function completeStep(index) { completed.value.add(index); completed.value = new Set(completed.value); resetTimerState(); activeStep.value = Math.min(index + 1, steps.value.length - 1) }
function resetGuide() { completed.value = new Set(); activeStep.value = 0; resetTimerState() }
function download() {
  const r = recipe.value, c = document.createElement('canvas'); c.width = 1080; c.height = 1350; const x = c.getContext('2d')
  x.fillStyle = '#f5f4f0'; x.fillRect(0, 0, c.width, c.height); x.fillStyle = '#1d2421'; x.fillRect(0, 0, c.width, 175); x.fillStyle = '#d99235'; x.font = 'bold 34px sans-serif'; x.fillText('BartenderAI 配方卡', 70, 95)
  x.fillStyle = '#171a18'; x.font = 'bold 58px sans-serif'; x.fillText(r.name_cn || r.name, 70, 270); x.font = '28px sans-serif'; x.fillStyle = '#69716d'; x.fillText(r.name, 70, 318); x.fillStyle = '#171a18'; x.font = 'bold 32px sans-serif'; x.fillText('材料', 70, 390); x.font = '25px sans-serif'; let y = 438
  r.ingredients.slice(0, 9).forEach(item => { x.fillText(`• ${item.name_zh || item.name}  ${item.amount || ''}`, 80, y); y += 42 })
  x.font = 'bold 32px sans-serif'; x.fillText('分步调制', 70, y + 28); x.font = '23px sans-serif'; x.fillStyle = '#353b38'; let sy = y + 72
  steps.value.slice(0, 6).forEach((step, index) => { const lines = step.match(/.{1,31}/g) || []; lines.slice(0, 2).forEach((line, lineIndex) => x.fillText(`${lineIndex ? '   ' : `${index + 1}. `}${line}`, 80, sy + lineIndex * 31)); sy += Math.max(45, lines.slice(0, 2).length * 31 + 8) })
  x.fillStyle = '#8a5a19'; x.font = '22px sans-serif'; x.fillText('理性饮酒 · 酒后勿驾车', 70, 1280); const a = document.createElement('a'); a.download = `${r.name || 'recipe'}.png`; a.href = c.toDataURL('image/png'); a.click()
}
</script>

<template>
  <div class="page"><router-link class="back" to="/explore"><ArrowLeft :size="17"/>返回配方探索</router-link>
    <div v-if="loading" class="state">正在读取配方...</div><div v-else-if="error" class="state"><div><strong>配方不存在或加载失败</strong>{{ error }}</div></div>
    <template v-else>
      <section class="recipe-hero"><div class="hero-image"><div class="media-switch" role="tablist" aria-label="配方视觉模式"><button :class="{active:mediaMode==='particles'}" role="tab" :aria-selected="mediaMode==='particles'" title="粒子酒体" @click="mediaMode='particles'"><Sparkles :size="15"/>粒子酒体</button><button :class="{active:mediaMode==='photo'}" v-if="recipe.image" role="tab" :aria-selected="mediaMode==='photo'" title="成品图" @click="mediaMode='photo'"><ImageIcon :size="15"/>成品图</button></div><CocktailParticleScene v-if="mediaMode==='particles' && !sceneUnavailable" :recipe="recipe" :active-step="activeStep" :prepared-indices="[...ingredientsReady]" :highlight-ingredient="highlightedIngredient" :timer-progress="timerState.progress" :timer-running="timerState.running" @unavailable="sceneUnavailable=true;mediaMode='photo'"/><template v-else><div class="hero-image-fallback"><strong>{{ recipe.name_cn || recipe.name }}</strong><span>{{ imageFailed || !recipe.image ? '成品图片暂不可用' : '正在准备成品图片' }}</span></div><img v-if="recipe.image && !imageFailed" :class="{ loaded: imageLoaded }" :src="recipe.image" :alt="`${recipe.name_cn || recipe.name} 成品图`" @load="imageLoaded = true" @error="imageFailed = true"/></template></div><div class="hero-copy"><div class="toolbar"><span class="chip amber">{{ categoryLabel }}</span><span class="chip" :class="recipe.alcoholic ? '' : 'green'">{{ recipe.alcoholic ? `约 ${recipe.abv}% ABV` : '无酒精' }}</span></div><h1>{{ recipe.name_cn || recipe.name }}</h1><p class="english">{{ recipe.name }}</p><div class="recipe-facts"><span><b>方法</b>{{ recipe.method }}</span><span><b>杯具</b>{{ glassLabel }}</span><span><b>准备</b>{{ recipe.ingredients.length }} 种材料</span></div><div class="toolbar actions"><button class="btn primary" @click="toggleFavorite"><Heart :size="17" :fill="favorite ? 'currentColor' : 'none'"/>{{ favorite ? '已收藏' : '收藏' }}</button><button class="btn" @click="download"><Download :size="17"/>下载配方卡</button></div></div></section>
      <section class="detail-grid"><div>
        <div class="panel panel-pad"><div class="section-head"><h2 class="section-title">备料清单</h2><small>{{ ingredientsReady.size }} / {{ recipe.ingredients.length }} 已备好</small></div><ul class="ingredients"><li v-for="(item, index) in recipe.ingredients" :key="`${item.name}-${index}`" :class="{ checked: ingredientsReady.has(index) }" @pointerenter="highlightedIngredient=index" @pointerleave="highlightedIngredient=-1" @focusin="highlightedIngredient=index" @focusout="highlightedIngredient=-1" @click="toggleIngredient(index)"><button :aria-label="`${item.name_zh || item.name} ${ingredientsReady.has(index) ? '已备好' : '标记备好'}`"><Check :size="14"/></button><span>{{ item.name_zh || item.name }}<small>{{ item.name }}</small></span><strong>{{ item.amount || '适量' }}</strong></li></ul><div class="equipment"><b>需要的工具</b><span v-for="item in recipe.equipment" :key="item">{{ item }}</span></div></div>
        <div class="panel panel-pad steps"><div class="section-head"><div><h2 class="section-title">跟着步骤调制</h2><small>完成一步后继续，进度会保留在本页</small></div><button v-if="completed.size" class="reset-guide" @click="resetGuide"><RotateCcw :size="14"/>重新开始</button></div><div class="progress"><span :style="{ width: `${progress}%` }"></span></div><ol><li v-for="(step, index) in steps" :key="index" :class="{ active: activeStep === index, done: completed.has(index) }"><button class="step-number" @click="completeStep(index)"><Check v-if="completed.has(index)" :size="15"/><span v-else>{{ index + 1 }}</span></button><div><p>{{ step }}</p><MixTimer v-if="activeStep === index && recipe.timer_seconds && (step.includes('秒') || index === 2)" :seconds="recipe.timer_seconds" :label="recipe.timer_label" @update="onTimerUpdate" @complete="onTimerComplete"/><button v-if="activeStep === index && !completed.has(index)" class="next-step" @click="completeStep(index)">完成这一步<ChevronRight :size="15"/></button></div></li></ol><div v-if="progress === 100" class="complete-note"><Check :size="18"/>调制完成。先观察香气和温度，再小口试饮。</div></div>
      </div><aside><div class="panel panel-pad radar"><h2 class="section-title">风味轮廓</h2><FlavorRadar :flavor="recipe.flavor"/></div><div class="panel panel-pad feedback"><h2 class="section-title">喝后评分</h2><div class="stars"><button v-for="n in 5" :key="n" @click="rating = n" :class="{ active: n <= rating }"><Star :size="22" :fill="n <= rating ? 'currentColor' : 'none'"/></button></div><div class="tag-list"><label v-for="item in [['too_sweet','太甜'],['too_sour','太酸'],['too_strong','太烈'],['too_weak','太淡'],['just_right','刚好']]" :key="item[0]"><input type="checkbox" :value="item[0]" v-model="tags"/>{{ item[1] }}</label></div><textarea class="textarea" v-model="note" maxlength="500" placeholder="可选备注"></textarea><button class="btn amber" :disabled="!rating" @click="feedback">{{ saved ? '已记录' : '提交评分' }}</button></div><p class="safety">配方酒精度为估算值。请根据个人情况适量饮用，未成年人请勿饮酒。</p></aside></section>
    </template>
  </div>
</template>

<style scoped>
.back{display:inline-flex;align-items:center;gap:5px;color:var(--muted);font-size:13px;margin-bottom:20px}.recipe-hero{display:grid;grid-template-columns:minmax(300px,48%) 1fr;min-height:410px;background:#202824;color:#fff;margin:0 -34px 28px;overflow:hidden}.hero-image{min-height:410px;position:relative;background:#102d29;overflow:hidden}.hero-image-fallback{position:absolute;inset:0;display:grid;place-content:center;justify-items:center;gap:10px;color:#dce7e1;font-size:12px}.hero-image img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:0;transition:opacity .25s}.hero-image img.loaded{opacity:1}.media-switch{position:absolute;z-index:3;left:16px;top:16px;display:flex;background:#081d1acc;border:1px solid #bdefff44;padding:3px;border-radius:5px;backdrop-filter:blur(8px)}.media-switch button{height:30px;border:0;background:transparent;color:#c6d8d2;padding:0 9px;display:flex;align-items:center;gap:5px;border-radius:3px;font-size:10px}.media-switch button.active{background:#f7c54a;color:#17322c}.hero-copy{padding:52px;align-self:center}.hero-copy h1{font-size:44px;margin:20px 0 2px}.english{color:#bdc8c2;font-size:18px;margin:0}.recipe-facts{display:flex;flex-wrap:wrap;gap:18px;margin:28px 0;color:#e5eae7;font-size:13px}.recipe-facts span{display:grid;gap:4px}.recipe-facts b{color:#9eaaa4;font-size:10px;text-transform:uppercase}.actions{margin-top:30px}.detail-grid{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(280px,.8fr);gap:18px}.detail-grid>div,.detail-grid>aside{display:grid;align-content:start;gap:18px}.section-head{display:flex;justify-content:space-between;align-items:start;gap:15px}.section-head small{color:var(--muted);font-size:11px}.ingredients{list-style:none;padding:0;margin:0}.ingredients li{display:grid;grid-template-columns:27px 1fr auto;align-items:center;gap:9px;padding:11px 0;border-bottom:1px solid #edf0ed;cursor:pointer}.ingredients li:last-child{border:0}.ingredients li>button{width:21px;height:21px;border:1px solid #bdc6c0;background:#fff;border-radius:4px;color:transparent;display:grid;place-items:center}.ingredients li.checked>button{background:var(--green);border-color:var(--green);color:#fff}.ingredients li.checked>span{text-decoration:line-through;color:var(--muted)}.ingredients small{display:block;color:var(--muted);font-size:10px;margin-top:3px}.ingredients strong{font-size:13px}.equipment{border-top:1px solid var(--line);padding-top:13px;display:flex;flex-wrap:wrap;gap:6px;align-items:center}.equipment b{font-size:11px;margin-right:4px}.equipment span{background:#edf2ee;color:#345444;padding:5px 7px;border-radius:4px;font-size:10px}.progress{height:4px;background:#e5e9e6;margin:13px 0 20px;overflow:hidden}.progress span{display:block;height:100%;background:var(--green);transition:width .25s}.steps ol{list-style:none;padding:0;margin:0}.steps li{display:grid;grid-template-columns:32px 1fr;gap:10px;opacity:.62;padding-bottom:18px}.steps li.active,.steps li.done{opacity:1}.step-number{width:28px;height:28px;border-radius:50%;display:grid;place-items:center;border:1px solid #bec8c1;background:#fff;color:#59645e;font-weight:800;font-size:11px}.steps li.active .step-number{border-color:var(--green);color:var(--green)}.steps li.done .step-number{background:var(--green);border-color:var(--green);color:#fff}.steps li p{margin:3px 0 10px;line-height:1.65}.next-step{display:flex;align-items:center;gap:4px;border:0;background:transparent;color:var(--green);font-size:11px;padding:2px 0}.reset-guide{border:0;background:transparent;color:var(--muted);display:flex;align-items:center;gap:4px;font-size:11px}.complete-note{display:flex;align-items:center;gap:7px;background:#e9f3ed;color:#24583f;padding:11px;border-radius:5px;font-size:12px}.radar{text-align:center}.feedback{display:grid;gap:12px}.stars button{border:0;background:none;color:#c7cbc8;padding:2px}.stars button.active{color:var(--amber)}.tag-list{display:flex;flex-wrap:wrap;gap:8px}.tag-list label{font-size:12px;display:flex;align-items:center;gap:4px}.feedback .btn{width:100%}@media(max-width:850px){.recipe-hero{grid-template-columns:1fr;margin-left:-16px;margin-right:-16px}.hero-image{min-height:300px;aspect-ratio:4/3}.hero-copy{padding:28px}.hero-copy h1{font-size:32px}.detail-grid{grid-template-columns:1fr}}@media(max-width:420px){.media-switch{left:10px;top:10px}.hero-copy{padding:24px 20px}.hero-copy h1{font-size:30px}}
</style>
