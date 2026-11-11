<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, CheckCircle2, Download, Sparkles, Trash2 } from 'lucide-vue-next'
import { api } from '../api'
import CocktailParticleScene from '../components/CocktailParticleScene.vue'
import FlavorRadar from '../components/FlavorRadar.vue'

const route = useRoute(), router = useRouter()
const item = ref(null), loading = ref(true), error = ref(''), removing = ref(false)
const recipe = computed(() => item.value?.recipe || {})
const flavorLabels = { sweet: '甜', sour: '酸', bitter: '苦', strong: '酒感', body: '酒体', aroma: '香气' }
const agentNames = { brief: '需求分析', evidence: '参考检索', create: '配方构建', revise: '定向修订', rules: '规则质检', review: '出品复核', ready: '最终确认' }
const flavorSignals = computed(() => Object.entries(recipe.value.flavor || {}).filter(([key]) => flavorLabels[key]).sort((a, b) => b[1] - a[1]).slice(0, 3))
const collaboration = computed(() => {
  const byStage = new Map()
  for (const event of item.value?.collaboration || []) byStage.set(event.stage, event)
  return [...byStage.values()]
})
const isDemo = import.meta.env.MODE === 'demo'
const creationMode = computed(() => isDemo ? '本地模板试调' : item.value?.capability_mode === 'local_rules' ? '本地规则创作' : item.value?.capability_mode === 'model_rules_review' ? '模型创作 · 规则复核' : '多 Agent 原创配方')

onMounted(async () => {
  try { item.value = await api.recipes.creation(route.params.id) }
  catch (e) { error.value = e.message }
  finally { loading.value = false }
})

async function remove() {
  if (!window.confirm(`删除原创配方“${recipe.value.name_cn || recipe.value.name}”？`)) return
  removing.value = true
  try { await api.recipes.removeCreation(route.params.id); await router.push('/studio') }
  catch (e) { error.value = e.message; removing.value = false }
}

function download() {
  const r = recipe.value, canvas = document.createElement('canvas'); canvas.width = 1080; canvas.height = 1350
  const ctx = canvas.getContext('2d'); ctx.fillStyle = '#fff8ec'; ctx.fillRect(0, 0, 1080, 1350)
  ctx.fillStyle = '#173f35'; ctx.fillRect(0, 0, 1080, 190); ctx.fillStyle = '#ffcc39'; ctx.fillRect(0, 176, 1080, 14)
  ctx.fillStyle = '#ffffff'; ctx.font = 'bold 34px sans-serif'; ctx.fillText('BARTENDERAI ORIGINAL', 66, 92)
  ctx.fillStyle = '#17211d'; ctx.font = 'bold 58px sans-serif'; ctx.fillText(r.name_cn || r.name, 66, 285)
  ctx.font = '26px sans-serif'; ctx.fillStyle = '#617068'; ctx.fillText(r.name || '', 66, 330)
  ctx.fillStyle = '#17211d'; ctx.font = 'bold 30px sans-serif'; ctx.fillText('材料', 66, 405)
  ctx.font = '24px sans-serif'; let y = 452
  ;(r.ingredients || []).slice(0, 9).forEach(entry => { ctx.fillText(`${entry.name}  ${entry.amount || '适量'}`, 76, y); y += 39 })
  ctx.font = 'bold 30px sans-serif'; ctx.fillText('分步调制', 66, y + 28); ctx.font = '22px sans-serif'; let sy = y + 72
  ;(r.steps || []).slice(0, 6).forEach((step, index) => { const lines = step.match(/.{1,34}/g) || []; lines.slice(0, 2).forEach((line, i) => ctx.fillText(`${i ? '   ' : `${index + 1}. `}${line}`, 76, sy + i * 30)); sy += Math.max(42, lines.slice(0, 2).length * 30 + 7) })
  ctx.fillStyle = '#b94b35'; ctx.font = '22px sans-serif'; ctx.fillText('原创配方 · 理性饮酒 · 酒后勿驾车', 66, 1280)
  const link = document.createElement('a'); link.download = `${r.name || 'original-recipe'}.png`; link.href = canvas.toDataURL('image/png'); link.click()
}
</script>

<template>
  <div class="creation-page">
    <div v-if="loading" class="state">正在打开创作档案...</div>
    <div v-else-if="error && !item" class="state"><div><strong>原创配方无法打开</strong>{{ error }}<br/><router-link class="btn" to="/studio">返回创作室</router-link></div></div>
    <template v-else>
      <section class="creation-hero">
        <router-link class="back" to="/studio"><ArrowLeft :size="17"/>返回 AI 创作室</router-link>
        <div class="hero-grid"><div><span class="eyebrow"><Sparkles :size="15"/>{{ creationMode }} · {{ item.created_at?.slice(0,10) }}</span><h1>{{ recipe.name_cn || recipe.name }}</h1><p class="english">{{ recipe.name }}</p><p class="description">{{ recipe.description || recipe.tips }}</p><div class="signals"><span v-for="signal in flavorSignals" :key="signal[0]">{{ flavorLabels[signal[0]] }} {{ signal[1] }}/10</span></div></div><div class="hero-actions"><button class="btn light" @click="download"><Download :size="17"/>下载配方卡</button><button class="btn delete" :disabled="removing" @click="remove"><Trash2 :size="17"/>{{ removing ? '正在删除' : '删除' }}</button></div></div>
        <div class="creation-visual" aria-label="原创配方粒子酒体"><CocktailParticleScene :recipe="recipe" background="#173f35"/></div>
      </section>

      <div v-if="error" class="error-box">{{ error }}</div>
      <main class="creation-layout">
        <div class="recipe-workflow">
          <section class="materials"><div class="section-kicker">01 / PREP</div><h2>备料清单</h2><ul><li v-for="(ingredient,index) in recipe.ingredients || []" :key="`${ingredient.name}-${index}`"><span>{{ ingredient.name }}</span><strong>{{ ingredient.amount || '适量' }}</strong></li></ul><div class="facts"><span><b>基酒</b>{{ recipe.spirit_base || '自由结构' }}</span><span><b>杯具</b>{{ recipe.glass || '合适杯具' }}</span><span><b>装饰</b>{{ recipe.garnish || '无需额外装饰' }}</span></div></section>
          <section class="mixing"><div class="section-kicker">02 / BUILD</div><h2>分步调制</h2><ol><li v-for="(step,index) in recipe.steps || []" :key="index" :style="{'--order':index}"><span>{{ String(index + 1).padStart(2,'0') }}</span><p>{{ step }}</p></li></ol><p v-if="recipe.tips" class="tips">{{ recipe.tips }}</p></section>
        </div>

        <aside>
          <section class="flavor-panel"><div><span>FLAVOR MAP</span><h2>风味轮廓</h2></div><FlavorRadar :flavor="recipe.flavor || {}"/></section>
          <section v-if="item.brief" class="brief-panel"><span>需求分析交接单</span><h2>{{ item.brief.summary }}</h2><div><b v-for="(value,key) in item.brief.flavor_targets" :key="key">{{ flavorLabels[key] || key }} {{ value }}/10</b><b v-for="entry in item.brief.avoid" :key="entry">避开 {{ entry }}</b></div></section>
          <section v-if="item.review" class="review-panel"><CheckCircle2 :size="20"/><div><span>{{ item.review.review_mode === 'rules' ? '本地规则复核' : '独立审校结论' }}</span><p>{{ item.review.intent_match }}</p><small>{{ item.review.feasibility }}</small></div></section>
          <section v-if="collaboration.length" class="agent-panel"><div class="agent-head"><span>CREATION RELAY</span><b>{{ collaboration.length }} 个环节</b></div><ol><li v-for="(event,index) in collaboration" :key="event.stage" :style="{'--order':index}"><span>{{ String(index + 1).padStart(2,'0') }}</span><div><b>{{ agentNames[event.stage] || '协作环节' }}</b><p>{{ event.title }}</p></div></li></ol></section>
        </aside>
      </main>
    </template>
  </div>
</template>

<style scoped>
.creation-page{min-height:100vh;background:#fffaf1}.creation-hero{position:relative;min-height:410px;background:#173f35;color:#fff;padding:28px 42px 42px;border-bottom:8px solid #ffcc39;box-shadow:0 7px 0 #ef6548;overflow:hidden}.creation-visual{position:absolute;z-index:0;inset:0 0 0 auto;width:min(46vw,680px)}.back,.hero-grid{position:relative;z-index:1}.back{display:inline-flex;align-items:center;gap:6px;color:#cde8dc;font-size:12px;margin-bottom:42px}.hero-grid{display:grid;grid-template-columns:minmax(0,680px);gap:22px;align-items:end}.eyebrow{display:flex;align-items:center;gap:7px;color:#ffcc39;font-size:11px;font-weight:800}.creation-hero h1{font-size:56px;line-height:1;margin:18px 0 8px;letter-spacing:0;overflow-wrap:anywhere}.english{color:#a7d5c1;font-size:17px;margin:0}.description{max-width:680px;line-height:1.7;color:#e8f3ee;margin:22px 0 0}.signals{display:flex;flex-wrap:wrap;gap:7px;margin-top:22px}.signals span{padding:7px 10px;background:#ffcc39;color:#1f332b;border:2px solid #101b17;font-size:11px;font-weight:800;box-shadow:3px 3px 0 #ef6548}.signals span:nth-child(2){background:#ef6548;color:#fff;box-shadow-color:#65c7e8}.signals span:nth-child(3){background:#65c7e8;box-shadow-color:#ffcc39}.hero-actions{display:flex;gap:9px}.hero-actions .light{background:#fff;color:#173f35;border-color:#fff}.hero-actions .delete{background:transparent;color:#ffc4b7;border-color:#ef8069}.creation-layout{padding:48px 42px 70px;display:grid;grid-template-columns:minmax(0,1.45fr) minmax(290px,.55fr);gap:50px}.recipe-workflow{display:grid;gap:46px}.section-kicker{font-size:10px;color:#ef6548;font-weight:900}.recipe-workflow h2,.flavor-panel h2,.brief-panel h2{font-size:24px;margin:7px 0 22px}.materials ul{list-style:none;padding:0;margin:0;border-top:3px solid #17211d}.materials li{display:flex;justify-content:space-between;gap:20px;padding:14px 4px;border-bottom:1px solid #d7d8d0}.materials li strong{color:#166849}.facts{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:18px}.facts span{display:grid;background:#dff5e9;border:1px solid #aedbc7;padding:12px;font-size:12px}.facts b{font-size:9px;color:#3f7562;margin-bottom:5px}.mixing ol{list-style:none;padding:0;margin:0;display:grid;gap:12px}.mixing li{display:grid;grid-template-columns:50px 1fr;gap:14px;align-items:start;padding:15px;background:#fff;border:1px solid #d9d9d0;border-left:5px solid #ef6548;box-shadow:4px 4px 0 #ffd8cf;animation:step-in .42s both;animation-delay:calc(var(--order) * 55ms)}.mixing li:nth-child(even){border-left-color:#18a777;box-shadow-color:#c9edde}.mixing li>span{font-size:20px;font-weight:900;color:#ef6548}.mixing li:nth-child(even)>span{color:#14815f}.mixing p{margin:2px 0;line-height:1.65}.tips{background:#fff0bd;border-left:5px solid #ffbd18;padding:13px!important;font-size:12px}.creation-layout aside{display:grid;align-content:start;gap:16px}.flavor-panel,.brief-panel,.review-panel,.agent-panel{border:1px solid #cfd6d1;background:#fff;padding:18px}.flavor-panel{border-top:5px solid #65c7e8}.flavor-panel>div span,.brief-panel>span,.review-panel span,.agent-head span{font-size:9px;font-weight:900;color:#297da0}.flavor-panel h2{margin-bottom:5px}.brief-panel{border-top:5px solid #ffcc39}.brief-panel>span{color:#9a6b00}.brief-panel h2{font-size:14px;line-height:1.55;margin-bottom:12px}.brief-panel>div{display:flex;flex-wrap:wrap;gap:5px}.brief-panel b{font-size:9px;background:#fff1bc;padding:5px 7px}.review-panel{display:flex;gap:10px;border-top:5px solid #18a777;color:#166849}.review-panel p{color:#17211d;line-height:1.55;font-size:12px;margin:6px 0}.review-panel small{color:#68736d;line-height:1.45}.agent-panel{border-top:5px solid #ef6548}.agent-head{display:flex;align-items:center;justify-content:space-between}.agent-head span{color:#b8422c}.agent-head b{font-size:10px}.agent-panel ol{list-style:none;padding:14px 0 0;margin:0;display:grid;gap:10px}.agent-panel li{display:grid;grid-template-columns:25px 1fr;gap:8px;animation:agent-in .35s both;animation-delay:calc(var(--order) * 50ms)}.agent-panel li>span{font-size:9px;color:#ef6548;font-weight:900}.agent-panel li b{font-size:11px}.agent-panel li p{font-size:10px;color:#6b756f;margin:2px 0}.error-box{margin:22px 42px 0}@keyframes step-in{from{opacity:0;transform:translateX(-14px)}to{opacity:1;transform:none}}@keyframes agent-in{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}@media(max-width:900px){.creation-hero{padding:24px 20px 34px}.back{margin-bottom:28px}.hero-grid{grid-template-columns:1fr}.hero-actions{justify-content:flex-start}.creation-visual{position:relative;width:calc(100% + 40px);height:290px;margin:30px -20px -34px}.creation-layout{padding:38px 20px 70px;grid-template-columns:1fr;gap:34px}.facts{grid-template-columns:1fr}.creation-layout aside{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:560px){.creation-hero h1{font-size:38px}.hero-actions{flex-wrap:wrap}.creation-layout aside{grid-template-columns:1fr}.mixing li{grid-template-columns:38px 1fr;padding:12px}.creation-layout{padding-left:16px;padding-right:16px}}@media(prefers-reduced-motion:reduce){.mixing li,.agent-panel li{animation:none}}
</style>
