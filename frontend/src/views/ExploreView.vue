<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ArrowRight, ArrowUpDown, RotateCcw, Search, SlidersHorizontal, Sparkles, X } from 'lucide-vue-next'
import { useRoute } from 'vue-router'
import { api } from '../api'
import CocktailParticleScene from '../components/CocktailParticleScene.vue'
import RecipeTile from '../components/RecipeTile.vue'
import { emitMotion } from '../motion'

const isDemo = import.meta.env.MODE === 'demo'
const defaults = { q: '', category: '', base_spirit: '', alcoholic: '', flavor: '', abv_min: '', abv_max: '', available_only: false, favorites_only: false, sort: '', page: 1, page_size: 24 }
const route = useRoute()
const filters = reactive({ ...defaults, q: typeof route.query.q === 'string' ? route.query.q : '' })
const items = ref([]), total = ref(0), loading = ref(true), error = ref(''), favorites = ref(new Set())
const previewRecipe = ref(null), previewUnavailable = ref(false)
let searchTimer
const pages = computed(() => Math.max(1, Math.ceil(total.value / filters.page_size)))
const activeCount = computed(() => ['q', 'category', 'base_spirit', 'alcoholic', 'flavor', 'abv_min', 'abv_max', 'available_only', 'favorites_only'].filter(key => filters[key] !== defaults[key]).length)
const baseOptions = [['gin', '金酒'], ['vodka', '伏特加'], ['rum', '朗姆'], ['tequila', '龙舌兰'], ['whiskey', '威士忌'], ['brandy', '白兰地']]
const quickFilters = [{ label: '清爽', flavor: 'aroma', abv_max: 25 }, { label: '偏甜', flavor: 'sweet' }, { label: '低酒精', abv_max: 15 }, { label: '无酒精', alcoholic: 'false' }]

async function load() {
  loading.value = true; error.value = ''
  try {
    const { favorites_only, ...selected } = filters
    const params = { ...selected, ...(isDemo ? { favorites_only } : {}), alcoholic: filters.alcoholic === '' ? null : filters.alcoholic === 'true' }
    const [data, favs] = await Promise.all([api.recipes.list(params), api.me.favorites()])
    items.value = data.items; total.value = data.total; favorites.value = new Set(favs.items.map(item => item.name))
  } catch (e) { error.value = e.message } finally { loading.value = false }
}
function activeFilterLabel() { return [filters.q, filters.base_spirit, filters.flavor, filters.category].filter(Boolean).join('-') || 'all' }
function search() { filters.page = 1; emitMotion('filter', { label: activeFilterLabel() }); load() }
function schedule() { clearTimeout(searchTimer); searchTimer = setTimeout(search, 300) }
function reset() { Object.assign(filters, defaults); load() }
function applyQuick(item) { filters.flavor = item.flavor || ''; filters.abv_max = item.abv_max || ''; filters.alcoholic = item.alcoholic || ''; search() }
async function favorite(recipe) {
  if (favorites.value.has(recipe.name)) { await api.me.removeFavorite(recipe.name); favorites.value.delete(recipe.name) }
  else { await api.me.addFavorite(recipe); favorites.value.add(recipe.name) }
  favorites.value = new Set(favorites.value)
  emitMotion('favorite', { label: recipe.id || recipe.name })
  if (isDemo && filters.favorites_only) load()
}
function openPreview(recipe) { previewRecipe.value = recipe; previewUnavailable.value = false; document.body.style.overflow = 'hidden'; emitMotion('preview', { label: recipe.id || recipe.name }) }
function interact(recipe) { emitMotion('recipe-motion', { label: recipe.id || recipe.name }) }
function closePreview() { previewRecipe.value = null; document.body.style.overflow = '' }
function handleKeydown(event) { if (event.key === 'Escape' && previewRecipe.value) closePreview() }
watch(() => filters.page, () => { emitMotion('filter', { label: `page-${filters.page}` }); load() })
onMounted(() => { window.addEventListener('keydown', handleKeydown); load() })
onBeforeUnmount(() => { window.removeEventListener('keydown', handleKeydown); document.body.style.overflow = '' })
</script>

<template>
  <div class="page">
    <header class="page-head"><div><h1>配方探索</h1><p>从口味、基酒和手边材料出发，找到今晚真正能调的一杯。</p></div><span class="result-count"><strong>{{ total }}</strong><small>款配方</small></span></header>
    <section class="discovery-tools">
      <div class="search-wrap"><Search :size="19"/><input v-model="filters.q" placeholder="搜索酒名或材料，例如：金酒 柠檬" @input="schedule"/></div>
      <div class="quick-row"><span>快速选择</span><button v-for="item in quickFilters" :key="item.label" @click="applyQuick(item)">{{ item.label }}</button></div>
      <div class="filter-row"><SlidersHorizontal :size="17"/><select v-model="filters.base_spirit" @change="search"><option value="">全部基酒</option><option v-for="item in baseOptions" :key="item[0]" :value="item[0]">{{ item[1] }}</option></select><select v-if="!isDemo" v-model="filters.category" @change="search"><option value="">全部类别</option><option value="Cocktail">鸡尾酒</option><option value="Ordinary Drink">经典与日常</option><option value="Shot">短饮与烈酒杯</option><option value="Punch / Party Drink">宾治与聚会酒</option><option value="Homemade Liqueur">自制利口酒</option></select><select v-model="filters.flavor" @change="search"><option value="">全部风味</option><option value="sweet">偏甜</option><option value="sour">偏酸</option><option value="bitter">偏苦</option><option value="strong">酒感强</option><option value="aroma">香气突出</option></select><select v-model="filters.alcoholic" @change="search"><option value="">含酒精与零酒</option><option value="true">含酒精</option><option value="false">无酒精</option></select><label v-if="isDemo" class="inventory-toggle"><input type="checkbox" v-model="filters.favorites_only" @change="search"/><span>仅看收藏</span></label><label class="inventory-toggle"><input type="checkbox" v-model="filters.available_only" @change="search"/><span>酒柜可调</span></label></div>
      <div class="range-row"><label>酒精度</label><input type="number" min="0" max="100" v-model="filters.abv_min" placeholder="最低" @change="search"/><span>至</span><input type="number" min="0" max="100" v-model="filters.abv_max" placeholder="最高" @change="search"/><label class="sort-label"><ArrowUpDown :size="14"/>排序</label><select v-model="filters.sort" @change="search"><option value="">默认顺序</option><option value="name">名称</option><option value="abv_asc">酒精度从低到高</option><option value="abv_desc">酒精度从高到低</option><option value="sweet">甜度优先</option><option value="sour">酸度优先</option><option value="aroma">香气优先</option></select><button v-if="activeCount" class="reset" @click="reset"><RotateCcw :size="14"/>清除 {{ activeCount }} 项筛选</button></div>
    </section>
    <div v-if="loading" class="state">正在整理配方...</div><div v-else-if="error" class="state"><div><strong>配方加载失败</strong>{{ error }}<br/><button class="btn" @click="load">重试</button></div></div><div v-else-if="!items.length" class="state"><div><strong>没有符合条件的配方</strong>试试减少筛选条件，或换一个材料关键词。<br/><button class="btn" @click="reset">查看全部配方</button></div></div>
    <section v-else class="grid grid-4 recipe-grid"><RecipeTile v-for="recipe in items" :key="recipe.id" :recipe="recipe" :favorite="favorites.has(recipe.name)" @favorite="favorite" @preview="openPreview" @interact="interact"/></section>
    <nav v-if="pages > 1" class="pagination"><button class="btn" :disabled="filters.page <= 1" @click="filters.page--">上一页</button><span>第 {{ filters.page }} / {{ pages }} 页</span><button class="btn" :disabled="filters.page >= pages" @click="filters.page++">下一页</button></nav>
    <Teleport to="body"><Transition name="spirit-preview"><div v-if="previewRecipe" class="preview-overlay" @click.self="closePreview"><section class="preview-shell" role="dialog" aria-modal="true" :aria-label="`${previewRecipe.name_cn || previewRecipe.name} 3D 粒子预览`"><div class="preview-stage"><CocktailParticleScene v-if="!previewUnavailable" :recipe="previewRecipe" @unavailable="previewUnavailable=true"/><div v-else class="preview-fallback"><Sparkles :size="28"/><span>当前设备无法创建 3D 场景</span></div><button class="preview-close" title="关闭预览" aria-label="关闭 3D 预览" @click="closePreview"><X :size="19"/></button></div><div class="preview-copy"><small>LIVE RECIPE / {{ previewRecipe.category }}</small><h2>{{ previewRecipe.name_cn || previewRecipe.name }}</h2><p>{{ previewRecipe.name }}</p><dl><div><dt>调制</dt><dd>{{ previewRecipe.method }}</dd></div><div><dt>杯具</dt><dd>{{ previewRecipe.glass }}</dd></div><div><dt>酒精度</dt><dd>{{ previewRecipe.alcoholic ? `约 ${previewRecipe.abv || 0}% ABV` : '无酒精' }}</dd></div></dl><div class="preview-flavors"><span v-for="(value,key) in previewRecipe.flavor" :key="key">{{ {sweet:'甜',sour:'酸',bitter:'苦',strong:'酒感',body:'酒体',aroma:'香气'}[key] || key }} {{ value }}</span></div><router-link class="preview-link" :to="`/recipes/${previewRecipe.id}`">进入完整配方<ArrowRight :size="17"/></router-link></div></section></div></Transition></Teleport>
  </div>
</template>

<style scoped>
.result-count{display:flex;align-items:baseline;gap:5px;color:var(--green)}.result-count strong{font-size:28px}.result-count small{color:var(--muted)}.discovery-tools{border-top:1px solid var(--line);border-bottom:1px solid var(--line);padding:18px 0;margin-bottom:24px}.search-wrap{position:relative;max-width:760px}.search-wrap svg{position:absolute;left:13px;top:12px;color:var(--muted)}.search-wrap input{width:100%;height:43px;border:1px solid #c9cfca;border-radius:6px;padding:0 14px 0 41px;background:#fff;font-size:14px;outline:0}.search-wrap input:focus{border-color:var(--green);box-shadow:0 0 0 3px #1f76531a}.quick-row{display:flex;align-items:center;gap:7px;margin:11px 0 15px}.quick-row>span{font-size:11px;color:var(--muted);margin-right:3px}.quick-row button{border:1px solid var(--line);background:#fff;border-radius:4px;padding:5px 9px;font-size:11px;color:#46504a}.quick-row button:hover{border-color:var(--green);color:var(--green)}.filter-row,.range-row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.filter-row select,.range-row select,.range-row input{height:36px;border:1px solid var(--line);border-radius:5px;background:#fff;padding:0 10px;color:var(--ink)}.filter-row select{min-width:132px}.inventory-toggle{height:36px;display:flex;align-items:center;gap:6px;border:1px solid var(--line);border-radius:5px;padding:0 10px;background:#fff;font-size:12px}.range-row{margin-top:9px;font-size:12px;color:var(--muted)}.range-row input{width:76px}.sort-label{display:flex;align-items:center;gap:4px;margin-left:8px}.reset{margin-left:auto;display:flex;align-items:center;gap:5px;border:0;background:transparent;color:#9a5f19;font-size:11px}.recipe-grid{align-items:start}.pagination{display:flex;justify-content:center;align-items:center;gap:14px;margin-top:26px;font-size:13px;color:var(--muted)}.preview-overlay{position:fixed;z-index:200;inset:0;background:#06100ded;display:grid;place-items:center;padding:24px}.preview-shell{width:min(1080px,calc(100vw - 48px));height:min(680px,calc(100vh - 48px));display:grid;grid-template-columns:minmax(0,1.55fr) minmax(280px,.7fr);overflow:hidden;border:1px solid #9fdcc54d;border-radius:8px;background:#f7f6f2;box-shadow:0 28px 90px #0009}.preview-stage{position:relative;min-height:0;background:#102d29}.preview-close{position:absolute;z-index:5;right:16px;top:16px;width:38px;height:38px;border:1px solid #ffffff66;border-radius:5px;background:#081d1acc;color:#fff;display:grid;place-items:center;backdrop-filter:blur(8px)}.preview-close:hover{background:#f1b84a;color:#17322c}.preview-fallback{position:absolute;inset:0;display:grid;place-content:center;justify-items:center;gap:9px;color:#dce7e1;font-size:12px}.preview-copy{padding:48px 38px;align-self:center;min-width:0}.preview-copy>small{color:#a26a1c;font-size:10px;font-weight:800}.preview-copy h2{font-size:34px;line-height:1.1;margin:16px 0 4px;overflow-wrap:anywhere}.preview-copy>p{color:var(--muted);margin:0}.preview-copy dl{display:grid;gap:10px;margin:30px 0 20px}.preview-copy dl div{display:grid;grid-template-columns:58px 1fr;gap:10px;border-bottom:1px solid var(--line);padding-bottom:9px}.preview-copy dt{font-size:10px;color:var(--muted)}.preview-copy dd{margin:0;font-size:12px;font-weight:650}.preview-flavors{display:flex;flex-wrap:wrap;gap:5px}.preview-flavors span{background:#e9efeb;color:#345444;padding:5px 7px;border-radius:3px;font-size:10px}.preview-link{display:flex;align-items:center;justify-content:space-between;border-top:1px solid var(--line);margin-top:28px;padding-top:16px;color:var(--green);font-size:13px;font-weight:750}.spirit-preview-enter-active,.spirit-preview-leave-active{transition:opacity .24s}.spirit-preview-enter-active .preview-shell,.spirit-preview-leave-active .preview-shell{transition:transform .34s cubic-bezier(.2,.8,.2,1),opacity .24s}.spirit-preview-enter-from,.spirit-preview-leave-to{opacity:0}.spirit-preview-enter-from .preview-shell{transform:translateY(24px) scale(.97);opacity:0}.spirit-preview-leave-to .preview-shell{transform:translateY(12px) scale(.985);opacity:0}@media(max-width:760px){.filter-row>svg{display:none}.filter-row select{flex:1;min-width:calc(50% - 5px)}.range-row .sort-label{margin-left:0}.range-row .reset{width:100%;margin-top:5px}.quick-row{overflow-x:auto}.quick-row button{white-space:nowrap}.preview-overlay{padding:10px}.preview-shell{width:100%;height:calc(100vh - 20px);grid-template-columns:1fr;grid-template-rows:minmax(300px,58%) 1fr}.preview-copy{padding:24px;overflow-y:auto}.preview-copy h2{font-size:27px}.preview-copy dl{grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;margin:18px 0 14px}.preview-copy dl div{display:block;border:0}.preview-copy dd{margin-top:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.preview-link{margin-top:17px}}@media(prefers-reduced-motion:reduce){.spirit-preview-enter-active,.spirit-preview-leave-active,.spirit-preview-enter-active .preview-shell,.spirit-preview-leave-active .preview-shell{transition:none}}
</style>
