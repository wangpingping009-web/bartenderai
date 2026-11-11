<script setup>
import { computed, ref } from 'vue'
import { AlertTriangle, ArrowRight, CheckCircle2, FlaskConical, Replace, Split } from 'lucide-vue-next'
import { api } from '../api'
import archiveImage from '../assets/vintage-popular-drinks-pdm.jpg'
import { emitMotion } from '../motion'

const tab = ref('substitute'), query = ref('青柠汁可以用什么替代？'), context = ref(''), result = ref(null), busy = ref(false), error = ref(''), recipeName = ref('Margarita')
const deconstruction = computed(() => result.value?.deconstruction || null)
const skeleton = computed(() => result.value?.skeleton || {})
async function run() {
  busy.value = true; error.value = ''; result.value = null
  try {
    if (tab.value === 'substitute') result.value = await api.recipes.substitute(query.value, context.value)
    else if (tab.value === 'deconstruct') {
      const list = await api.recipes.list({ q: recipeName.value, page_size: 1 })
      if (!list.items.length) throw new Error('没有找到这杯酒，请尝试中文名或英文名。')
      result.value = await api.recipes.deconstruct(list.items[0])
    } else {
      const list = await api.recipes.list({ q: recipeName.value, page_size: 1 })
      if (!list.items.length) throw new Error('没有找到这杯酒，请尝试中文名或英文名。')
      result.value = await api.fun.mocktail(list.items[0].name)
    }
    emitMotion('experiment', { label: `${tab.value}-ready` })
  } catch (e) { error.value = e.message } finally { busy.value = false }
}
function switchTab(value) { tab.value = value; result.value = null; error.value = ''; emitMotion('experiment', { label: value }) }
function moveArchive(event) {
  const rect = event.currentTarget.getBoundingClientRect()
  const x = (event.clientX - rect.left) / Math.max(1, rect.width) - .5
  const y = (event.clientY - rect.top) / Math.max(1, rect.height) - .5
  event.currentTarget.style.setProperty('--archive-shift-x', `${x * -18}px`)
  event.currentTarget.style.setProperty('--archive-shift-y', `${y * -10}px`)
  event.currentTarget.style.setProperty('--archive-frame-x', `${x * -16}px`)
  event.currentTarget.style.setProperty('--archive-frame-y', `${y * -10}px`)
  event.currentTarget.style.setProperty('--archive-line-scale', String(.55 + (x + .5) * .35))
}
function resetArchive(event) {
  event.currentTarget.style.setProperty('--archive-shift-x', '0px'); event.currentTarget.style.setProperty('--archive-shift-y', '0px')
  event.currentTarget.style.setProperty('--archive-frame-x', '0px'); event.currentTarget.style.setProperty('--archive-frame-y', '0px')
  event.currentTarget.style.setProperty('--archive-line-scale', '.55')
}
</script>

<template>
  <div class="page">
    <header class="page-head"><div><h1>配方实验室</h1><p>替换材料、理解经典结构，或把喜欢的配方改成无酒精版本。</p></div></header>
    <figure class="archive-strip" :class="`archive-${tab}`" aria-hidden="true" @pointermove="moveArchive" @pointerleave="resetArchive">
      <img :src="archiveImage" alt="" />
    </figure>
    <div class="segmented lab-tabs"><button :class="{ active: tab === 'substitute' }" @click="switchTab('substitute')"><Replace :size="15"/>材料替代</button><button :class="{ active: tab === 'deconstruct' }" @click="switchTab('deconstruct')"><Split :size="15"/>解构重组</button><button :class="{ active: tab === 'mocktail' }" @click="switchTab('mocktail')"><FlaskConical :size="15"/>零酒改造</button></div>
    <div class="lab-grid">
      <section class="lab-form">
        <template v-if="tab === 'substitute'"><div class="field"><label>你想替换什么</label><textarea class="textarea" v-model="query" rows="3" placeholder="例如：青柠汁可以换成柠檬汁吗？"></textarea></div><div class="field"><label>用在哪杯酒里（可选）</label><input class="input" v-model="context" placeholder="例如：玛格丽特，希望保持低甜"/></div></template>
        <template v-else><div class="field"><label>{{ tab === 'deconstruct' ? '选择要解构的配方' : '选择要改造的配方' }}</label><input class="input" v-model="recipeName" placeholder="例如：Margarita / Mojito / 玛格丽特"/></div><p class="form-note">{{ tab === 'deconstruct' ? '会找出这杯酒的核心结构，并给出可直接尝试的重组方案。' : '会替换酒精材料，同时解释每项替换如何保留原有风味。' }}</p></template>
        <button class="btn primary" :disabled="busy || (tab === 'substitute' ? !query.trim() : !recipeName.trim())" @click="run">{{ busy ? '正在分析' : tab === 'substitute' ? '获取替代建议' : tab === 'deconstruct' ? '分析配方结构' : '生成零酒版本' }}</button>
        <div v-if="error" class="error-box">{{ error }}</div>
      </section>

      <section class="lab-output">
        <div v-if="busy" class="empty-result"><FlaskConical :size="31"/><strong>正在分析这次改动</strong><span>结果会说明改变了什么，以及为什么可行。</span></div>
        <div v-else-if="!result" class="empty-result"><FlaskConical :size="31"/><strong>选择一项实验开始</strong><span>这里会呈现可直接操作的建议。</span></div>

        <article v-else-if="tab === 'substitute'" class="substitution-result">
          <header><span :class="result.explanation?.can_substitute !== false && result.matched?.length ? 'success' : 'warning'"><CheckCircle2 v-if="result.matched?.length" :size="17"/><AlertTriangle v-else :size="17"/></span><div><small>材料替代结论</small><h2>{{ result.explanation?.can_substitute === false ? '不建议直接替代' : result.matched?.length ? '可以替代，但要调整比例' : '暂时没有可靠替代依据' }}</h2></div></header>
          <p class="summary">{{ result.explanation?.summary || result.error || '当前知识库没有匹配到足够可靠的替代关系。' }}</p>
          <div v-if="result.explanation" class="impact-grid"><div><small>建议比例</small><strong>{{ result.explanation.ratio || '从少量开始调整' }}</strong></div><div><small>风味变化</small><p>{{ result.explanation.flavor_impact || '需要边尝边调整。' }}</p></div><div><small>注意事项</small><p>{{ result.explanation.caution || '先制作小份测试。' }}</p></div></div>
          <section v-if="result.matched?.length" class="evidence"><h3>可依据的替代关系</h3><div v-for="item in result.matched" :key="item.id"><b>{{ item.title_cn || `${item.a} 与 ${item.b}` }}</b><p>{{ item.content }}</p></div></section>
        </article>

        <article v-else-if="tab === 'deconstruct'" class="deconstruct-result">
          <header><small>配方结构</small><h2>{{ recipeName }}</h2><p>{{ deconstruction?.skeleton || '已从原配方材料中提取基础结构。' }}</p></header>
          <div class="structure"><div><small>核心基酒</small><strong>{{ deconstruction?.base_spirit || skeleton.base_spirit || '未明确' }}</strong></div><div><small>平衡方式</small><strong>{{ deconstruction?.balance || skeleton.balance || '待判断' }}</strong></div><div><small>标志元素</small><strong>{{ deconstruction?.signature || skeleton.signature || recipeName }}</strong></div></div>
          <section v-if="deconstruction?.ideas?.length" class="ideas"><h3>可以这样重组</h3><article v-for="(idea, index) in deconstruction.ideas" :key="idea.name"><span>{{ index + 1 }}</span><div><h4>{{ idea.name }}</h4><b>{{ idea.change }}</b><p>{{ idea.why }}</p></div></article></section>
          <p v-else class="limited"><AlertTriangle :size="15"/>智能解构暂时不可用，以上基础结构仍来自真实材料分析。</p>
        </article>

        <article v-else class="mocktail-result">
          <header><span class="success"><CheckCircle2 :size="17"/></span><div><small>无酒精改造</small><h2>{{ result.mocktail_name || result.name }}</h2><p>{{ result.note }}</p></div></header>
          <div class="mocktail-grid"><section><h3>新配方材料</h3><ul><li v-for="item in result.ingredients" :key="item.name"><span>{{ item.name }}</span><strong>{{ item.amount || '适量' }}</strong></li></ul></section><section><h3>替换说明</h3><div v-for="item in result.replaced" :key="`${item.from}-${item.to}`" class="swap"><div><b>{{ item.from }}</b><ArrowRight :size="14"/><strong>{{ item.to }}</strong></div><p>{{ item.why }}</p></div></section></div>
        </article>
      </section>
    </div>
  </div>
</template>

<style scoped>
.archive-strip{--archive-shift-x:0px;--archive-shift-y:0px;--archive-frame-x:0px;--archive-frame-y:0px;--archive-line-scale:.55;position:relative;height:clamp(142px,16vw,210px);margin:0 0 20px;overflow:hidden;border-top:4px solid var(--coral);border-bottom:4px solid var(--cyan);background:#ef6548;cursor:crosshair}.archive-strip:before,.archive-strip:after{content:"";position:absolute;z-index:1;pointer-events:none}.archive-strip:before{left:5%;right:5%;top:18%;height:2px;background:#fff;opacity:.65;transform:scaleX(var(--archive-line-scale));transform-origin:left;transition:transform .18s}.archive-strip:after{width:11%;height:22%;right:3%;bottom:8%;border-right:2px solid #ffcc39;border-bottom:2px solid #ffcc39;transform:translate(var(--archive-frame-x),var(--archive-frame-y)) rotate(-1.2deg);transition:transform .18s}.archive-strip img{width:112%;height:116%;object-fit:cover;object-position:50% 13%;filter:saturate(1.18) contrast(1.07) brightness(1.03);transform:translate(var(--archive-shift-x),var(--archive-shift-y)) scale(1.04);transition:transform .18s,object-position .45s cubic-bezier(.2,.8,.2,1),filter .35s}.archive-deconstruct img{object-position:50% 19%;filter:saturate(1.28) contrast(1.1)}.archive-mocktail img{object-position:50% 8%;filter:saturate(1.15) contrast(1.04) hue-rotate(5deg)}
.lab-tabs{margin-bottom:22px}.lab-tabs button{display:flex;align-items:center;gap:6px}.lab-grid{display:grid;grid-template-columns:minmax(280px,.62fr) minmax(0,1.38fr);gap:24px;border-top:1px solid var(--line);padding-top:22px}.lab-form{display:grid;gap:18px;align-content:start}.form-note{font-size:12px;color:var(--muted);line-height:1.6;border-left:2px solid var(--amber);padding-left:10px}.lab-output{border-left:1px solid var(--line);padding-left:24px;min-height:470px}.empty-result{height:430px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;color:var(--muted);text-align:center}.empty-result strong{color:var(--ink)}.empty-result span{font-size:12px}.lab-output article>header{display:flex;align-items:flex-start;gap:10px;border-bottom:1px solid var(--line);padding-bottom:16px}.lab-output header>span{width:32px;height:32px;border-radius:50%;display:grid;place-items:center;flex:0 0 32px}.success{background:#e5f2e9;color:var(--green)}.warning{background:#fff0dc;color:#a86416}.lab-output header small{color:var(--muted);font-size:10px}.lab-output h2{font-size:24px;margin:4px 0}.lab-output header p{color:var(--muted);margin:4px 0 0;line-height:1.55}.summary{font-size:14px;line-height:1.75;margin:18px 0}.impact-grid{display:grid;grid-template-columns:.55fr 1fr 1fr;gap:15px;border-top:1px solid var(--line);border-bottom:1px solid var(--line);padding:15px 0}.impact-grid small,.structure small{display:block;color:var(--muted);font-size:10px;margin-bottom:5px}.impact-grid strong{color:var(--green)}.impact-grid p{font-size:12px;line-height:1.55;margin:0}.evidence,.ideas{margin-top:20px}.evidence h3,.ideas h3,.mocktail-grid h3{font-size:12px}.evidence>div{padding:10px 0;border-bottom:1px solid #edf0ed}.evidence b{font-size:12px}.evidence p{font-size:11px;color:var(--muted);line-height:1.55;margin:5px 0}.structure{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:18px 0}.structure>div{background:#eef2ee;padding:12px;border-radius:5px}.structure strong{font-size:12px}.ideas>article{display:grid;grid-template-columns:29px 1fr;gap:9px;border:0;border-top:1px solid var(--line);padding:13px 0}.ideas>article>span{width:25px;height:25px;border-radius:50%;display:grid;place-items:center;background:var(--green);color:#fff;font-size:10px}.ideas h4{margin:0 0 5px}.ideas b{font-size:11px;color:var(--amber)}.ideas p{font-size:12px;line-height:1.55;margin:5px 0;color:var(--muted)}.limited{display:flex;gap:6px;align-items:center;background:#fff7e9;padding:10px;font-size:11px}.mocktail-result>header p{max-width:620px}.mocktail-grid{display:grid;grid-template-columns:.8fr 1.2fr;gap:24px;margin-top:18px}.mocktail-grid ul{list-style:none;padding:0;margin:0}.mocktail-grid li{display:flex;justify-content:space-between;padding:9px 0;border-bottom:1px solid #edf0ed;font-size:12px}.swap{padding:9px 0;border-bottom:1px solid #edf0ed}.swap>div{display:flex;align-items:center;gap:7px;font-size:12px}.swap strong{color:var(--green)}.swap p{font-size:11px;color:var(--muted);line-height:1.5;margin:5px 0}@media(max-width:850px){.lab-grid{grid-template-columns:1fr}.lab-output{border-left:0;border-top:1px solid var(--line);padding:20px 0 0}.lab-tabs{display:flex;overflow-x:auto}.lab-tabs button{white-space:nowrap}.impact-grid,.structure,.mocktail-grid{grid-template-columns:1fr}}
@media(max-width:520px){.archive-strip{height:132px}.archive-strip img{width:126%;object-position:68% 53%}.archive-strip:after{width:34%;right:5%}}@media(prefers-reduced-motion:reduce){.archive-strip:before,.archive-strip:after,.archive-strip img{transition:none;transform:none}}
</style>
