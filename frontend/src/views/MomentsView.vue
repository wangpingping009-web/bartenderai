<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Award, CalendarDays, CloudSun, Minus, PartyPopper, Plus, Sparkles, Users, X } from 'lucide-vue-next'
import { api } from '../api'
import CocktailParticleScene from '../components/CocktailParticleScene.vue'
import { emitMotion } from '../motion'

const daily = ref(null), challenge = ref(null), themes = ref([]), theme = ref(null), progress = ref(null)
const context = ref(null), banquet = ref(null), error = ref(''), themeLoading = ref(false)
const previewRecipe = ref(null), previewUnavailable = ref(false)
const ctx = ref({ time: 'evening', weather: '', mood: '' })
const party = ref({ names: 'Mojito, Margarita', headcount: 4, mocktail: false })
let themeRequest = 0

const guestDots = computed(() => Array.from({ length: Math.min(24, Math.max(1, Number(party.value.headcount) || 1)) }, (_, index) => index))
const overflowGuests = computed(() => Math.max(0, Number(party.value.headcount || 0) - guestDots.value.length))

async function load() {
  try {
    const [d, c, t, p] = await Promise.all([api.fun.daily(), api.fun.challenge(), api.themes.list(), api.fun.progress()])
    daily.value = d; challenge.value = c; themes.value = t.themes; progress.value = p
  } catch (e) { error.value = e.message }
}
async function resolveRecommendation(item) {
  try {
    const data = await api.recipes.list({ q: item.name, page: 1, page_size: 6 })
    const normalized = String(item.name).toLowerCase()
    const recipe = data.items.find(entry => [entry.name, entry.name_cn, ...(entry.aliases || [])].some(name => String(name || '').toLowerCase() === normalized)) || data.items[0]
    return { ...item, recipe: recipe || null }
  } catch { return { ...item, recipe: null } }
}
async function openTheme(item) {
  const request = ++themeRequest
  themeLoading.value = true
  try {
    const loaded = await api.themes.get(item.key)
    if (request !== themeRequest) return
    theme.value = { ...loaded, key: item.key }
    emitMotion('theme-open', { label: item.key })
    const recommendations = await Promise.all((loaded.recommendations || []).map(resolveRecommendation))
    if (request === themeRequest && theme.value?.key === item.key) theme.value = { ...theme.value, recommendations }
  } catch (e) { error.value = e.message } finally { if (request === themeRequest) themeLoading.value = false }
}
function closeTheme() { themeRequest += 1; theme.value = null; themeLoading.value = false }
function openPreview(item) {
  if (!item.recipe) return
  previewRecipe.value = item.recipe; previewUnavailable.value = false; document.body.style.overflow = 'hidden'
  emitMotion('preview', { label: item.recipe.id || item.recipe.name })
}
function closePreview() { previewRecipe.value = null; document.body.style.overflow = '' }
async function recommend() {
  context.value = await api.fun.context(ctx.value)
  emitMotion('context-ready', { label: `${ctx.value.time}-${ctx.value.weather}-${ctx.value.mood}` })
}
function adjustGuests(change) {
  party.value.headcount = Math.min(100, Math.max(1, Number(party.value.headcount || 1) + change))
  emitMotion('guest-count', { label: String(party.value.headcount) })
}
async function plan() {
  banquet.value = await api.fun.banquet({ names: party.value.names.split(',').map(value => value.trim()).filter(Boolean), headcount: party.value.headcount, mocktail: party.value.mocktail })
  progress.value = await api.fun.progress()
  emitMotion('banquet-ready', { label: String(party.value.headcount) })
}
function handleKeydown(event) { if (event.key === 'Escape' && previewRecipe.value) closePreview() }

onMounted(() => { window.addEventListener('keydown', handleKeydown); load() })
onBeforeUnmount(() => { window.removeEventListener('keydown', handleKeydown); document.body.style.overflow = '' })
</script>

<template>
  <div class="page">
    <header class="page-head"><div><h1>场景酒单</h1><p>每日灵感、主题策展、情境推荐、晚宴换算与成长徽章。</p></div><span v-if="progress" class="chip green"><Award :size="14" />{{ progress.level.name }} · {{ progress.xp }} XP</span></header>
    <div v-if="error" class="error-box">{{ error }}</div>

    <section class="top-grid">
      <article class="daily panel"><div><span class="eyebrow"><CalendarDays :size="14" />每日一酒</span><h2>{{ daily?.recipe?.name_cn || daily?.recipe?.name || '读取中' }}</h2><p>{{ daily?.recipe?.category }} · {{ daily?.date }}</p><router-link v-if="daily?.recipe?.id" class="btn amber" :to="`/recipes/${daily.recipe.id}`">查看配方</router-link></div><img v-if="daily?.recipe?.image" :src="daily.recipe.image" :alt="daily.recipe.name" /></article>
      <article class="challenge panel panel-pad"><span class="eyebrow"><PartyPopper :size="14" />今日挑战</span><h2>{{ challenge?.title || '读取中' }}</h2><p>{{ challenge?.description || challenge?.challenge }}</p><div class="toolbar"><span v-for="item in challenge?.ingredients" :key="item" class="chip amber">{{ item }}</span></div><router-link class="btn" to="/studio">去创作室完成</router-link></article>
    </section>

    <section class="section themes-section">
      <h2>主题酒单</h2>
      <div class="grid grid-3"><button v-for="item in themes" :key="item.key" class="theme panel" :class="{ active: theme?.key === item.key }" @click="openTheme(item)"><b>{{ item.emoji }}</b><span><strong>{{ item.name }}</strong><small>{{ item.vibe }}</small></span></button></div>
      <div v-if="theme" class="theme-detail panel panel-pad" :data-theme-key="theme.key" :data-resolved-count="theme.recommendations.filter(item => item.recipe).length">
        <div class="theme-head"><div><span class="chip amber">{{ theme.name }}</span><h3>{{ theme.vibe }}</h3><p>{{ theme.tips }}</p></div><button class="icon-btn" @click="closeTheme" aria-label="关闭主题酒单"><X :size="17" /></button></div>
        <div class="grid grid-3 theme-recipes">
          <article v-for="(item, index) in theme.recommendations" :key="item.name" :class="{ resolved: item.recipe }" :style="{ '--theme-order': index }">
            <span class="recipe-orbit" aria-hidden="true"><i v-for="dot in 5" :key="dot" :style="{ '--dot': dot - 1 }" /></span>
            <div><h4>{{ item.name }}</h4><p>{{ item.why }}</p><span>{{ item.spirit }} · {{ item.glass }}</span></div>
            <button v-if="item.recipe" class="preview-recipe" :aria-label="`预览 ${item.name} 的粒子酒体`" title="粒子酒体预览" @click="openPreview(item)"><Sparkles :size="16" /></button>
          </article>
        </div>
        <span v-if="themeLoading" class="theme-loading">正在匹配完整配方...</span>
      </div>
    </section>

    <section class="grid grid-2 section">
      <div class="panel panel-pad"><h2 class="section-title"><CloudSun :size="18" />情境推荐</h2><div class="grid grid-3 context-fields"><select class="select" v-model="ctx.time"><option value="morning">早晨</option><option value="afternoon">午后</option><option value="evening">傍晚</option><option value="night">深夜</option></select><select class="select" v-model="ctx.weather"><option value="">天气不限</option><option value="hot">炎热</option><option value="cold">寒冷</option><option value="rain">雨天</option></select><select class="select" v-model="ctx.mood"><option value="">心情不限</option><option value="happy">开心</option><option value="tired">疲惫</option><option value="stressed">压力大</option><option value="curious">好奇</option></select></div><button class="btn primary" @click="recommend">生成风味方向</button><div v-if="context" class="context-result"><div class="toolbar"><span v-for="keyword in context.keywords" :key="keyword" class="chip green">{{ keyword }}</span></div><p>{{ context.summary || context.reason }}</p><router-link :to="`/explore?q=${encodeURIComponent(context.keywords?.[0] || '')}`">按方向找配方</router-link></div></div>
      <div class="panel panel-pad banquet-panel">
        <h2 class="section-title"><Users :size="18" />晚宴换算</h2>
        <div class="field"><label>配方英文名，用逗号分隔</label><input class="input" v-model="party.names" /></div>
        <div class="party-row"><div class="field guest-stepper"><label>人数</label><div><button type="button" aria-label="减少一位宾客" @click="adjustGuests(-1)"><Minus :size="15" /></button><input class="input" type="number" min="1" max="100" v-model.number="party.headcount" /><button type="button" aria-label="增加一位宾客" @click="adjustGuests(1)"><Plus :size="15" /></button></div></div><label><input type="checkbox" v-model="party.mocktail" />全部改为零酒</label></div>
        <div class="guest-field" :data-headcount="party.headcount" aria-hidden="true"><span v-for="guest in guestDots" :key="guest" :style="{ '--guest': guest }"><i /></span><b v-if="overflowGuests">+{{ overflowGuests }}</b></div>
        <button class="btn primary" @click="plan">计算备料</button>
        <div v-if="banquet" class="banquet"><article v-for="(cocktail, index) in banquet.cocktails" :key="cocktail.name" :style="{ '--pour-order': index }"><b>{{ cocktail.name }}</b><span v-for="item in cocktail.ingredients" :key="item.name">{{ item.name }} {{ item.for_n }}ml</span></article></div>
      </div>
    </section>

    <section v-if="progress" class="section"><h2>成长徽章</h2><div class="progress-line"><span :style="{ width: `${Math.min(100, progress.level.xp_to_next ? progress.xp / (progress.xp + progress.level.xp_to_next) * 100 : 100)}%` }" /></div><div class="grid grid-4 badges"><article v-for="badge in progress.badges" :key="badge.id" class="panel panel-pad" :class="{ locked: !badge.earned }"><b>{{ badge.emoji }}</b><strong>{{ badge.name }}</strong><small>{{ badge.desc }}</small><span>{{ badge.progress }} / {{ badge.threshold }}</span></article></div></section>

    <Teleport to="body"><Transition name="moment-preview"><div v-if="previewRecipe" class="moment-overlay" @click.self="closePreview"><section class="moment-shell" role="dialog" aria-modal="true" :aria-label="`${previewRecipe.name_cn || previewRecipe.name} 粒子酒体预览`"><div class="moment-stage"><CocktailParticleScene v-if="!previewUnavailable" :recipe="previewRecipe" @unavailable="previewUnavailable = true" /><div v-else class="moment-fallback">当前设备无法创建粒子场景</div><button class="moment-close" aria-label="关闭粒子预览" title="关闭" @click="closePreview"><X :size="19" /></button></div><div class="moment-copy"><small>主题酒单</small><h2>{{ previewRecipe.name_cn || previewRecipe.name }}</h2><p>{{ previewRecipe.name }}</p><div><span>{{ previewRecipe.method }}</span><span>{{ previewRecipe.glass }}</span><span>{{ previewRecipe.alcoholic ? `约 ${previewRecipe.abv || 0}% ABV` : '无酒精' }}</span></div><router-link class="btn primary" :to="`/recipes/${previewRecipe.id}`">查看完整配方</router-link></div></section></div></Transition></Teleport>
  </div>
</template>

<style scoped>
.top-grid{display:grid;grid-template-columns:1.4fr 1fr;gap:18px}.daily{display:grid;grid-template-columns:1fr 45%;overflow:hidden;background:#202824;color:#fff;min-height:270px}.daily>div{padding:28px}.daily img{width:100%;height:100%;object-fit:cover}.eyebrow{display:flex;align-items:center;gap:6px;color:var(--amber);font-size:12px;font-weight:800}.daily h2,.challenge h2{font-size:27px;margin:26px 0 5px}.daily p,.challenge p{color:#aab6af;line-height:1.6}.daily .btn{margin-top:22px}.challenge{display:grid;align-content:start}.challenge .btn{margin-top:auto;width:max-content}.section{margin-top:30px}.section>h2{font-size:19px}.theme{border:1px solid var(--line);padding:16px;text-align:left;display:flex;gap:12px;align-items:center}.theme.active{border-color:#ef6548;background:#fff4ee;box-shadow:4px 5px 0 #f5c7bb}.theme>b{font-size:28px}.theme span strong,.theme span small{display:block}.theme small{color:var(--muted);margin-top:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:260px}.theme-detail{margin-top:12px}.theme-head{display:flex;justify-content:space-between;gap:16px}.theme-head h3{margin:10px 0 3px}.theme-head p{color:var(--muted)}.theme-recipes article{position:relative;min-height:160px;border-left:2px solid var(--amber);padding:11px 42px 10px 12px;overflow:hidden;isolation:isolate}.theme-recipes article>div{position:relative;z-index:1}.theme-recipes article h4{margin:0}.theme-recipes article p{font-size:12px;color:var(--muted);line-height:1.5}.theme-recipes article div>span{font-size:11px}.preview-recipe{position:absolute;z-index:3;right:8px;top:8px;width:32px;height:32px;border:1px solid #9eb4a8;background:#fff;color:var(--green);display:grid;place-items:center;border-radius:50%;transition:transform .2s,background .2s}.preview-recipe:hover{transform:rotate(12deg) scale(1.08);background:#17322c;color:#fff}.recipe-orbit{position:absolute;z-index:0;right:-28px;bottom:-35px;width:116px;height:116px;border:1px solid #f4bb6b38;border-radius:50%;opacity:.45;transition:opacity .2s,transform .35s}.recipe-orbit i{--angle:calc(var(--dot) * 72deg);position:absolute;left:55px;top:55px;width:5px;height:5px;border-radius:50%;background:#ef6548;transform:rotate(var(--angle)) translateX(43px);animation:theme-orbit 4.2s linear infinite}.theme-recipes article:nth-child(2n) .recipe-orbit i{background:#28a87b;animation-direction:reverse}.theme-recipes article:hover .recipe-orbit{opacity:.9;transform:scale(1.08)}.theme-loading{display:block;margin-top:10px;color:var(--muted);font-size:10px}.section-title{display:flex;align-items:center;gap:7px}.context-fields{margin-bottom:12px}.context-result{margin-top:14px;border-top:1px solid var(--line);padding-top:13px}.context-result p{font-size:12px;color:var(--muted)}.context-result a{color:var(--green);font-size:12px;font-weight:700}.party-row{display:flex;align-items:end;gap:18px;margin:12px 0}.party-row>label{font-size:12px}.guest-stepper>div{display:grid;grid-template-columns:34px 70px 34px}.guest-stepper button{border:1px solid var(--line);background:#fff;display:grid;place-items:center;color:var(--green)}.guest-stepper button:first-child{border-radius:5px 0 0 5px}.guest-stepper button:last-child{border-radius:0 5px 5px 0}.guest-stepper .input{height:38px;border-radius:0;text-align:center;padding:0;border-left:0;border-right:0}.guest-field{display:flex;align-items:flex-end;gap:5px;min-height:50px;padding:9px 11px;margin:4px 0 12px;background:#eef7f2;border-left:3px solid #39a875;overflow:hidden}.guest-field>span{position:relative;width:12px;height:28px;flex:0 0 12px;animation:guest-arrive .34s both;animation-delay:calc(min(var(--guest),12) * 24ms)}.guest-field>span:before{content:"";position:absolute;left:3px;top:1px;width:7px;height:7px;border-radius:50%;background:#ef6548}.guest-field>span i{position:absolute;left:1px;bottom:0;width:11px;height:17px;border-radius:7px 7px 2px 2px;background:#38a879}.guest-field>span:nth-child(3n+2):before{background:#ffcc39}.guest-field>span:nth-child(3n+2) i{background:#55bde2}.guest-field>span:nth-child(3n):before{background:#65c7e8}.guest-field>span:nth-child(3n) i{background:#e66b57}.guest-field>b{font-size:11px;color:var(--green);align-self:center}.banquet{margin-top:12px;max-height:220px;overflow:auto}.banquet article{position:relative;padding:9px 0 9px 13px;border-top:1px solid var(--line);animation:pour-result .42s both;animation-delay:calc(var(--pour-order) * 70ms)}.banquet article:before{content:"";position:absolute;left:0;top:10px;width:5px;height:28px;background:#ef6548;transform-origin:bottom;animation:bottle-fill .6s .15s both}.banquet span{display:block;font-size:11px;color:var(--muted)}.progress-line{height:7px;background:#dfe3df;border-radius:5px;margin-bottom:14px}.progress-line span{display:block;height:100%;background:var(--green);border-radius:5px}.badges article{display:grid;grid-template-columns:32px 1fr;gap:4px}.badges b{font-size:24px;grid-row:1/4}.badges strong,.badges small,.badges span{display:block}.badges small{color:var(--muted);font-size:10px}.badges span{font-size:10px;color:var(--green)}.badges .locked{filter:grayscale(1);opacity:.55}
.moment-overlay{position:fixed;z-index:220;inset:0;background:#06100ded;display:grid;place-items:center;padding:22px}.moment-shell{width:min(920px,calc(100vw - 44px));height:min(570px,calc(100vh - 44px));display:grid;grid-template-columns:minmax(0,1.45fr) minmax(260px,.65fr);background:#f7f6f2;border:1px solid #8dd9bd55;overflow:hidden;border-radius:7px}.moment-stage{position:relative;min-height:0;background:#102d29}.moment-close{position:absolute;z-index:5;right:14px;top:14px;width:37px;height:37px;border:1px solid #ffffff66;background:#071c18c9;color:#fff;display:grid;place-items:center;border-radius:50%}.moment-copy{padding:34px;align-self:center}.moment-copy>small{color:#c05c3c;font-weight:800}.moment-copy h2{font-size:31px;margin:13px 0 3px}.moment-copy>p{color:var(--muted);margin:0}.moment-copy>div{display:grid;gap:7px;margin:25px 0}.moment-copy>div span{border-bottom:1px solid var(--line);padding-bottom:7px;font-size:11px}.moment-preview-enter-active,.moment-preview-leave-active{transition:opacity .24s}.moment-preview-enter-active .moment-shell,.moment-preview-leave-active .moment-shell{transition:transform .34s cubic-bezier(.2,.8,.2,1)}.moment-preview-enter-from,.moment-preview-leave-to{opacity:0}.moment-preview-enter-from .moment-shell{transform:scale(.96) translateY(20px)}
@keyframes theme-orbit{to{transform:rotate(calc(360deg + var(--angle))) translateX(43px)}}@keyframes guest-arrive{from{opacity:0;transform:translateY(18px) rotate(5deg)}to{opacity:1;transform:none}}@keyframes pour-result{from{opacity:0;transform:translateY(-10px)}to{opacity:1;transform:none}}@keyframes bottle-fill{from{transform:scaleY(0)}to{transform:scaleY(1)}}
@media(max-width:850px){.top-grid{grid-template-columns:1fr}.daily{grid-template-columns:1fr 42%}.moment-shell{grid-template-columns:1fr;grid-template-rows:minmax(285px,58%) 1fr}.moment-copy{padding:22px;overflow-y:auto}}@media(max-width:520px){.daily{grid-template-columns:1fr}.daily img{height:200px;grid-row:1}.daily>div{grid-row:2}.context-fields{grid-template-columns:1fr}.theme-recipes article{min-height:145px}.guest-field{gap:3px}.guest-field>span{transform:scale(.88);transform-origin:bottom}.moment-overlay{padding:10px}.moment-shell{width:100%;height:calc(100vh - 20px)}}@media(prefers-reduced-motion:reduce){.recipe-orbit i,.guest-field>span,.banquet article,.banquet article:before{animation:none}.preview-recipe,.recipe-orbit,.moment-preview-enter-active,.moment-preview-leave-active,.moment-preview-enter-active .moment-shell,.moment-preview-leave-active .moment-shell{transition:none}}
</style>
