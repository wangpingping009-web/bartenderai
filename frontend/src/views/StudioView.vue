<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ArrowUpRight, Check, CheckCircle2, LoaderCircle, RefreshCw, Sparkles } from 'lucide-vue-next'
import { api } from '../api'
import AgentMixingStage from '../components/AgentMixingStage.vue'
import FlavorRadar from '../components/FlavorRadar.vue'
import { emitMotion } from '../motion'

const isDemo = import.meta.env.MODE === 'demo'
const personas = ref([]), persona = ref('classic'), preferences = ref(''), bases = ref([]), result = ref(null), creations = ref([]), inventory = ref([])
const busy = ref(false), error = ref(''), stages = ref([]), useInventory = ref(false)
const baseOptions = [['gin', '金酒'], ['vodka', '伏特加'], ['rum', '朗姆'], ['tequila', '龙舌兰'], ['whiskey', '威士忌'], ['brandy', '白兰地']]
const latestStages = computed(() => {
  const byStage = new Map()
  for (const event of stages.value) byStage.set(event.stage, event)
  return [...byStage.values()]
})
const agentNames = { brief: '需求分析', evidence: '参考检索', create: '配方构建', revise: '定向修订', rules: '规则质检', review: '出品复核', ready: '最终确认' }
function agentName(stage) { return agentNames[stage] || '协作环节' }
function creationMode(mode) { if (isDemo) return '本地模板试调'; return mode === 'local_rules' ? '本地规则创作' : mode === 'model_rules_review' ? '模型创作 · 规则复核' : '多 Agent 原创' }
function reviewMode(mode) { if (isDemo) return '沿用示例配方'; return mode === 'local_rules' ? '规则复核通过' : mode === 'model_rules_review' ? '本地复核通过' : '独立审校通过' }
function stageInteract(event) { emitMotion('agent', { label: event.agent || 'field' }) }

watch([persona, () => bases.value.join(',')], ([selectedPersona, selectedBases]) => {
  emitMotion('agent-config', { label: `${selectedPersona}-${selectedBases || 'open'}` })
})

onMounted(async () => {
  try {
    const [p, c, stock] = await Promise.all([api.recipes.personas(), api.recipes.creations(), api.me.inventory()])
    personas.value = p.personas; creations.value = c.items; inventory.value = stock.items
  } catch (e) { error.value = e.message }
})
async function generate() {
  busy.value = true; error.value = ''; result.value = null; stages.value = []
  let requestText = preferences.value.trim()
  if (useInventory.value && inventory.value.length) requestText += `；优先使用我的酒柜材料：${inventory.value.join('、')}`
  try {
    await api.recipes.generateStream({ preferences: requestText, persona: persona.value, base_spirits: bases.value }, event => {
      if (event.type === 'status') { stages.value.push(event); emitMotion('agent', { label: event.stage || 'stage' }) }
      else if (event.type === 'done') { result.value = event.result; emitMotion('complete', { label: event.result?.recipe?.name || 'creation' }) }
      else if (event.type === 'error') throw new Error(event.message)
    })
    if (result.value?.ok) creations.value = (await api.recipes.creations()).items
  } catch (e) { error.value = e.message; emitMotion('error', { label: 'creation' }) } finally { busy.value = false }
}
</script>

<template>
  <div class="page">
    <header class="page-head"><div><h1>AI 创作室</h1><p>{{ isDemo ? '用浏览器规则匹配一款示例配方，生成可保存的试调档案。' : '说出你想喝的味道，创作、复核和修订会围绕同一个目标协作。' }}</p></div></header>
    <div class="studio-grid">
      <section class="creation-form">
        <h2>设定这杯酒</h2>
        <div class="field"><label>创作方向</label><textarea class="textarea" v-model="preferences" rows="4" placeholder="例如：夏夜慢饮，低甜，柑橘和草本香，入口清爽但不要太酸"></textarea></div>
        <div class="field"><label>调酒风格</label><div class="persona-grid"><button v-for="item in personas" :key="item.key" :class="{ active: persona === item.key }" @click="persona = item.key"><span>{{ item.emoji }}</span><b>{{ item.name }}</b><Check v-if="persona === item.key" :size="15"/></button></div></div>
        <div class="field"><label>指定基酒</label><div class="base-options"><label v-for="item in baseOptions" :key="item[0]"><input type="checkbox" :value="item[0]" v-model="bases"/><span>{{ item[1] }}</span></label></div></div>
        <label v-if="inventory.length" class="inventory-option"><input type="checkbox" v-model="useInventory"/><span><b>优先使用我的酒柜</b><small>当前有 {{ inventory.length }} 种材料</small></span></label>
        <button class="btn amber create" :disabled="busy || !preferences.trim()" @click="generate"><RefreshCw v-if="busy" :size="17" class="spin"/><Sparkles v-else :size="17"/>{{ busy ? '正在协作创作' : '开始创作' }}</button>
        <div v-if="error" class="error-box">{{ error }}</div>
      </section>

      <section class="creation-output">
        <AgentMixingStage :stages="latestStages" :persona="persona" :bases="bases" :brief="preferences" :busy="busy" @interact="stageInteract"/>
        <div v-if="busy || stages.length" class="collaboration"><div class="collaboration-head"><h3>创作协作现场</h3><span>{{ latestStages.length }} 个环节已接力</span></div><ol><li v-for="(stage, index) in latestStages" :key="stage.stage" :class="stage.status" :style="{'--order':index}"><span><LoaderCircle v-if="stage.status === 'working' && busy" :size="15" class="spin"/><CheckCircle2 v-else :size="15"/></span><div><em>{{ agentName(stage.stage) }}</em><b>{{ stage.title }}</b><small>{{ stage.detail }}</small></div></li></ol></div>
        <div v-if="busy && !result" class="working-copy"><LoaderCircle :size="22" class="spin"/><span>每个阶段完成后会在上方留下真实结果。</span></div>
        <article v-else-if="result?.ok" class="result-card">
          <header><div><small>{{ creationMode(result.capability_mode) }} · {{ result.attempts > 1 ? `经过 ${result.attempts - 1} 次修订` : '初稿通过' }}</small><h2>{{ result.recipe.name_cn || result.recipe.name }}</h2><p>{{ result.recipe.description }}</p></div><span class="approved"><CheckCircle2 :size="16"/>{{ reviewMode(result.capability_mode) }}</span></header>
          <section v-if="result.brief" class="brief-strip"><b>需求交接单</b><span v-for="(value,key) in result.brief.flavor_targets" :key="key">{{ {sweet:'甜',sour:'酸',strong:'酒感',body:'酒体',aroma:'香气'}[key] || key }} {{ value }}/10</span><span v-for="item in result.brief.avoid" :key="item">避开 {{ item }}</span></section>
          <section class="why"><h3>为什么适合你</h3><p>{{ result.review?.intent_match }}</p><small>{{ result.review?.feasibility }}</small></section>
          <div class="result-body"><div><h3>材料</h3><ul class="ingredients"><li v-for="item in result.recipe.ingredients" :key="item.name"><span>{{ item.name }}</span><strong>{{ item.amount || '适量' }}</strong></li></ul><h3>分步调制</h3><ol class="steps"><li v-for="(step, index) in result.recipe.steps" :key="index"><span>{{ index + 1 }}</span><p>{{ step }}</p></li></ol><p v-if="result.recipe.tips" class="tips">{{ result.recipe.tips }}</p></div><FlavorRadar :flavor="result.recipe.flavor"/></div>
          <footer><template v-if="result.references?.length"><b>创作参考结构</b><span v-for="item in result.references" :key="item.id">{{ item.name_cn || item.name }} · {{ item.method }}</span></template><router-link v-if="result.creation_id" class="btn open-creation" :to="`/studio/creations/${result.creation_id}`">打开创作档案<ArrowUpRight :size="16"/></router-link></footer>
        </article>
        <div v-else-if="result && !result.ok" class="state"><div><strong>这版没有达到可执行标准</strong>{{ result.error }}<br/><button class="btn" @click="generate">重新创作</button></div></div>
        <div v-else class="empty-result"><Sparkles :size="32"/><strong>等待你的创作命题</strong><span>完成后会得到材料、完整步骤和复核依据。</span></div>
      </section>
    </div>

    <section class="history"><div class="history-head"><h2>{{ isDemo ? '我的试调档案' : '我的原创配方' }}</h2><span>{{ creations.length }} 杯</span></div><div v-if="!creations.length" class="muted">{{ isDemo ? '还没有保存的试调档案。' : '还没有保存的原创配方。' }}</div><div v-else class="grid grid-3"><router-link v-for="(item,index) in creations" :key="item.id" :to="`/studio/creations/${item.id}`" class="creation-item" :style="{'--order':index}"><div><small>{{ item.created_at?.slice(0, 10) }}</small><ArrowUpRight :size="17"/></div><h3>{{ item.recipe.name_cn || item.recipe.name }}</h3><p>{{ item.recipe.description || item.recipe.tips || item.recipe.steps?.[0] }}</p><span>{{ item.recipe.ingredients?.length || 0 }} 种材料 · {{ item.recipe.steps?.length || 0 }} 步</span></router-link></div></section>
  </div>
</template>

<style scoped>
.studio-grid{display:grid;grid-template-columns:minmax(300px,.68fr) minmax(0,1.32fr);gap:24px;border-top:1px solid var(--line);padding-top:22px}.creation-form{display:grid;gap:18px;align-content:start}.creation-form h2{font-size:17px;margin:0}.persona-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:7px}.persona-grid button{height:44px;border:1px solid var(--line);background:#fff;border-radius:5px;padding:0 10px;display:flex;align-items:center;gap:8px;color:var(--ink)}.persona-grid button.active{border-color:var(--green);background:#e9f3ed}.persona-grid button span{width:22px;height:22px;display:grid;place-items:center;background:#edf0ed;border-radius:4px;font-size:10px}.persona-grid button b{font-size:12px;margin-right:auto}.base-options{display:flex;flex-wrap:wrap;gap:7px}.base-options label input{display:none}.base-options span{display:block;border:1px solid var(--line);border-radius:4px;padding:7px 10px;font-size:12px}.base-options input:checked+span{background:var(--charcoal);color:#fff;border-color:var(--charcoal)}.inventory-option{display:flex;align-items:center;gap:9px;border-top:1px solid var(--line);border-bottom:1px solid var(--line);padding:12px 2px}.inventory-option>span{display:grid}.inventory-option b{font-size:12px}.inventory-option small{font-size:10px;color:var(--muted);margin-top:2px}.create{width:100%}.spin{animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
.creation-output{min-height:540px;border-left:1px solid var(--line);padding-left:24px}.creation-output>.agent-mixing-stage{margin-bottom:20px;border-bottom:4px solid #ef6548;box-shadow:7px 7px 0 #c9e8dd}.collaboration{border:1px solid #b8ded0;border-left:4px solid #20a474;background:#effaf5;padding:15px 16px;margin-bottom:20px;box-shadow:4px 4px 0 #d9eee6}.collaboration-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px}.collaboration h3{font-size:12px;margin:0;color:#174f3b}.collaboration-head>span{font-size:10px;color:#33715a}.collaboration ol{list-style:none;padding:0;margin:0;display:grid;gap:8px}.collaboration li{display:grid;grid-template-columns:23px 1fr;gap:8px;animation:agent-arrive .36s both;animation-delay:calc(var(--order) * 55ms)}.collaboration li>span{width:21px;height:21px;border-radius:50%;display:grid;place-items:center;background:#d5f1e4;color:#16835d}.collaboration li.working>span{background:#ffe2ad;color:#b85f00;box-shadow:0 0 0 4px #fff3d9}.collaboration li div{display:grid;grid-template-columns:auto 1fr;align-items:baseline;column-gap:7px}.collaboration li em{font-size:9px;font-style:normal;font-weight:800;color:#d95336;text-transform:uppercase}.collaboration li b{font-size:12px}.collaboration li small{grid-column:1/-1;font-size:10px;color:#4e7164;line-height:1.45;margin-top:2px}.working-copy,.empty-result{min-height:220px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:9px;color:var(--muted);text-align:center}.empty-result strong{color:var(--ink)}.empty-result span{font-size:12px}.result-card{animation:result-rise .5s both}.result-card>header{display:flex;justify-content:space-between;gap:18px;align-items:flex-start;border-bottom:1px solid var(--line);padding-bottom:17px}.result-card header small{color:var(--amber)}.result-card h2{font-size:30px;margin:7px 0 4px}.result-card header p{margin:0;color:var(--muted)}.approved{display:flex;align-items:center;gap:5px;color:var(--green);font-size:11px;white-space:nowrap}.brief-strip{display:flex;flex-wrap:wrap;gap:6px;padding:13px 0;border-bottom:1px solid var(--line)}.brief-strip b{width:100%;font-size:10px;color:var(--muted)}.brief-strip span{background:#ffe3d9;color:#8e3423;padding:5px 8px;border:1px solid #f3b9a9;border-radius:4px;font-size:10px}.why{padding:16px 0;border-bottom:1px solid var(--line)}.why h3,.result-body h3{font-size:12px;margin:0 0 8px}.why p{margin:0 0 4px;line-height:1.6}.why small{color:var(--muted)}.result-body{display:grid;grid-template-columns:1fr 260px;gap:24px;padding-top:18px}.ingredients{list-style:none;padding:0;margin:0 0 20px}.ingredients li{display:flex;justify-content:space-between;border-bottom:1px solid #edf0ed;padding:8px 0;font-size:12px}.steps{list-style:none;padding:0;margin:0;display:grid;gap:9px}.steps li{display:grid;grid-template-columns:22px 1fr;gap:7px}.steps li>span{width:21px;height:21px;border-radius:50%;display:grid;place-items:center;background:var(--green);color:#fff;font-size:10px}.steps p{font-size:12px;line-height:1.55;margin:1px 0}.tips{background:#fff7e9;border-left:2px solid var(--amber);padding:9px;font-size:11px;line-height:1.5}.result-card>footer{display:flex;flex-wrap:wrap;align-items:center;gap:6px;border-top:1px solid var(--line);padding-top:13px;margin-top:18px}.result-card>footer b{width:100%;font-size:10px;color:var(--muted)}.result-card>footer span{background:#eef2ee;padding:5px 7px;border-radius:3px;font-size:10px}.open-creation{margin-left:auto}.history{margin-top:34px;border-top:1px solid var(--line);padding-top:22px}.history-head{display:flex;justify-content:space-between;align-items:center}.history-head h2{font-size:17px}.history-head span{font-size:11px;color:var(--muted)}.creation-item{color:var(--ink);background:#fff;border:1px solid var(--line);border-top:4px solid #f06445;padding:15px;min-height:155px;box-shadow:4px 4px 0 #f7c8bc;animation:item-in .4s both;animation-delay:calc(min(var(--order),8) * 45ms);transition:transform .18s,box-shadow .18s}.creation-item:nth-child(3n+2){border-top-color:#16a47a;box-shadow-color:#bde8da}.creation-item:nth-child(3n){border-top-color:#2f82c8;box-shadow-color:#bfdcf3}.creation-item:hover{transform:translate(-2px,-3px);box-shadow:7px 8px 0 #f7c8bc}.creation-item:nth-child(3n+2):hover{box-shadow-color:#bde8da}.creation-item:nth-child(3n):hover{box-shadow-color:#bfdcf3}.creation-item>div{display:flex;align-items:center;justify-content:space-between}.creation-item small{color:var(--muted)}.creation-item h3{margin:12px 0 6px;font-size:17px}.creation-item p{color:var(--muted);font-size:12px;line-height:1.5;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.creation-item>span{font-size:10px;color:var(--green)}@keyframes agent-arrive{from{opacity:0;transform:translateX(-10px)}to{opacity:1;transform:none}}@keyframes result-rise{from{opacity:0;transform:translateY(18px) scale(.985)}to{opacity:1;transform:none}}@keyframes item-in{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}@media(max-width:900px){.studio-grid{grid-template-columns:1fr}.creation-output{border-left:0;border-top:1px solid var(--line);padding:20px 0 0}.result-body{grid-template-columns:1fr}.result-body svg{margin:auto}}@media(max-width:480px){.persona-grid{grid-template-columns:1fr}.result-card h2{font-size:24px}.collaboration{padding:13px}.collaboration-head{align-items:flex-start;flex-direction:column}.creation-item{min-height:135px}}@media(prefers-reduced-motion:reduce){.collaboration li,.result-card,.creation-item{animation:none}.creation-item{transition:none}}
</style>
