<script setup>
import { computed, ref, watch } from 'vue'
import { Check, Heart, ScanLine } from 'lucide-vue-next'

const props = defineProps({ recipe: { type: Object, required: true }, favorite: { type: Boolean, default: false } })
const emit = defineEmits(['favorite', 'preview', 'interact'])
const tile = ref(null), imageLoaded = ref(false), imageFailed = ref(false), interactionCount = ref(0)
let touchStart = null
const flavorLabels = { sweet: '甜', sour: '酸', bitter: '苦', strong: '酒感', aroma: '香气' }
const glassLabels = {
  'cocktail glass': '鸡尾酒杯', 'martini glass': '马天尼杯', 'highball glass': '高球杯',
  'collins glass': '柯林杯', 'shot glass': '烈酒杯', 'old-fashioned glass': '古典杯',
  'champagne flute': '香槟笛形杯', 'wine glass': '葡萄酒杯', 'coffee mug': '咖啡杯',
  'mason jar': '玻璃罐杯', 'punch bowl': '宾治碗', 'pitcher': '壶', 'beer mug': '啤酒杯',
}

function hashText(text = '') {
  let value = 2166136261
  for (const char of text) value = Math.imul(value ^ char.charCodeAt(0), 16777619)
  return value >>> 0
}
function ingredientNames() {
  return (props.recipe.ingredients || []).map(item => String(item.name_zh || item.name || '').toLowerCase())
}
function ingredientColor(name) {
  const mappings = [
    [/蓝|blue cura|蓝橙/, '#25a7ff'], [/蔓越莓|石榴|grenadine|cranberry|莓/, '#ff4178'],
    [/金巴利|阿佩罗|campari|aperol/, '#ff5848'], [/咖啡|可乐|coffee|cola/, '#9d5845'],
    [/奶|cream|milk|coconut/, '#fff0c7'], [/菠萝|pineapple/, '#ffd52f'],
    [/百香果|passion fruit/, '#ff8b32'], [/桃|peach/, '#ff9672'],
    [/青柠|lime/, '#6fe36e'], [/柠檬|lemon/, '#ffe55c'], [/橙|orange/, '#ff9e28'],
    [/薄荷|罗勒|香草|mint|basil|herb/, '#47d69a'],
    [/威士忌|白兰地|朗姆|whisk|brandy|cognac|dark rum/, '#dc8a3d'],
    [/葡萄|香槟|vermouth|wine|champagne/, '#f4ca64'],
    [/汤力|苏打|气泡|tonic|soda|sparkling/, '#9cecff'],
    [/金酒|伏特加|gin|vodka/, '#c2ebff'],
  ]
  return mappings.find(([pattern]) => pattern.test(name))?.[1]
}

const topFlavors = computed(() => Object.entries(props.recipe.flavor || {}).filter(([key]) => flavorLabels[key]).sort((a, b) => b[1] - a[1]).slice(0, 2))
const thumbnail = computed(() => {
  const url = props.recipe.image || ''
  return url.includes('thecocktaildb.com') && !url.endsWith('/preview') ? `${url}/preview` : url
})
const seed = computed(() => hashText(`${props.recipe.id}-${props.recipe.name}-${props.recipe.method}`))
const fallbackTone = computed(() => `tone-${seed.value % 4}`)
const glassLabel = computed(() => glassLabels[(props.recipe.glass || '').toLowerCase()] || props.recipe.glass || '合适杯具')
const motionProfile = computed(() => {
  const method = String(props.recipe.method || '').toLowerCase(), names = ingredientNames().join(' ')
  const flavor = props.recipe.flavor || {}
  if (/layer|分层|漂浮/.test(method)) return 'strata'
  if (/blend|搅打|电动/.test(method)) return 'frost'
  if (/shake|摇/.test(method) && /奶|蛋清|cream|milk|egg white|coconut/.test(names)) return 'velvet'
  if (/shake|摇/.test(method)) return 'shake'
  if (/stir|搅拌/.test(method)) return 'vortex'
  if (/汤力|苏打|气泡|香槟|啤酒|可乐|tonic|soda|sparkling|champagne|beer|cola/.test(names)) return 'bubble'
  if (Number(flavor.aroma || 0) >= 6 || /薄荷|罗勒|香草|mint|basil|herb/.test(names)) return 'botanical'
  if (Number(flavor.strong || 0) >= 7) return 'flare'
  return 'pour'
})
const motionStyle = computed(() => {
  const flavor = props.recipe.flavor || {}, baseHue = (flavor.sour >= 7 ? 50 : flavor.sweet >= 7 ? 338 : flavor.bitter >= 6 ? 16 : flavor.aroma >= 7 ? 145 : 188) + seed.value % 31 - 15
  const found = ingredientNames().map(ingredientColor).filter(Boolean)
  const speed = 2.25 + (seed.value % 90) / 100
  return {
    '--tone-a': found[0] || `hsl(${baseHue},94%,58%)`,
    '--tone-b': found[1] || `hsl(${(baseHue + 54) % 360},98%,69%)`,
    '--tone-c': found[2] || (Number(flavor.aroma || 0) >= 6 ? '#7df0a7' : '#ffd166'),
    '--motion-speed': `${speed}s`,
    '--motion-fast': `${speed * .68}s`,
  }
})
const motionSignature = computed(() => `${motionProfile.value}-${seed.value % 5}`)
function particleStyle(index) {
  return {
    '--i': index,
    '--x': `${7 + index * 10.5}%`,
    '--y': `${8 + index * 8.5}%`,
    '--delay': `${index * -.15}s`,
    '--offset': `${(index - 4) * 3}px`,
    '--orbit': `${22 + index * 5}px`,
    '--angle': `${index * 40}deg`,
    '--particle-size': `${4 + index * .5}px`,
    '--line-width': `${38 + index * 5}%`,
    '--line-length': `${20 + index * 5}%`,
  }
}

function pointerMove(event) {
  if (!tile.value || event.pointerType === 'touch') return
  const rect = tile.value.getBoundingClientRect()
  const x = Math.min(1, Math.max(0, (event.clientX - rect.left) / Math.max(1, rect.width)))
  const y = Math.min(1, Math.max(0, (event.clientY - rect.top) / Math.max(1, rect.height)))
  tile.value.style.setProperty('--tilt-x', `${(.5 - y) * 3.8}deg`)
  tile.value.style.setProperty('--tilt-y', `${(x - .5) * 4.8}deg`)
  tile.value.style.setProperty('--image-x', `${(x - .5) * -7}px`)
  tile.value.style.setProperty('--image-y', `${(y - .5) * -5}px`)
}
function resetPointer() {
  if (!tile.value) return
  tile.value.style.setProperty('--tilt-x', '0deg'); tile.value.style.setProperty('--tilt-y', '0deg')
  tile.value.style.setProperty('--image-x', '0px'); tile.value.style.setProperty('--image-y', '0px')
}
function activateMotion() {
  interactionCount.value += 1
  emit('interact', props.recipe)
}
function pointerDown(event) {
  touchStart = { x: event.clientX, y: event.clientY, type: event.pointerType }
  if (event.pointerType !== 'touch') activateMotion()
}
function pointerUp(event) {
  if (touchStart?.type === 'touch' && Math.hypot(event.clientX - touchStart.x, event.clientY - touchStart.y) < 12) activateMotion()
  touchStart = null
}
function cancelPointer() { touchStart = null; resetPointer() }

watch(() => props.recipe.image, () => { imageLoaded.value = false; imageFailed.value = false })
</script>

<template>
  <article
    ref="tile"
    class="recipe-tile panel"
    :class="`motion-${motionProfile}`"
    :style="motionStyle"
    :data-motion-profile="motionProfile"
    :data-motion-signature="motionSignature"
    :data-interaction-count="interactionCount"
    @pointermove="pointerMove"
    @pointerleave="cancelPointer"
    @pointerdown="pointerDown"
    @pointerup="pointerUp"
    @pointercancel="cancelPointer"
  >
    <div class="recipe-visual">
      <router-link :to="`/recipes/${recipe.id}`" class="recipe-image">
        <span class="image-fallback" :class="fallbackTone"><strong>{{ recipe.name_cn || recipe.name }}</strong><small>{{ thumbnail && !imageFailed ? '正在加载配方图片' : '配方预览' }}</small></span>
        <img v-if="thumbnail && !imageFailed" :class="{ loaded: imageLoaded }" :src="thumbnail" :alt="`${recipe.name_cn || recipe.name} 成品图`" loading="lazy" decoding="async" @load="imageLoaded = true" @error="imageFailed = true" />
        <span class="motion-field" aria-hidden="true"><i v-for="index in 9" :key="index" :style="particleStyle(index - 1)" /></span>
        <span v-if="recipe.available" class="ready"><Check :size="12" />酒柜可调</span>
      </router-link>
      <button class="preview-button" title="3D 粒子预览" :aria-label="`预览 ${recipe.name_cn || recipe.name} 的 3D 粒子酒体`" @click="$emit('preview', recipe)"><ScanLine :size="17" /></button>
    </div>
    <div class="recipe-body"><div><small>{{ recipe.method || recipe.category }}</small><h3><router-link :to="`/recipes/${recipe.id}`">{{ recipe.name_cn || recipe.name }}</router-link></h3><p>{{ recipe.name_cn !== recipe.name ? recipe.name : '' }}</p></div><button class="heart" :class="{ active: favorite }" :aria-label="favorite ? '取消收藏' : '收藏'" @click="$emit('favorite', recipe)"><Heart :size="18" :fill="favorite ? 'currentColor' : 'none'" /></button></div>
    <div class="flavors"><span v-for="item in topFlavors" :key="item[0]">{{ flavorLabels[item[0]] }} {{ item[1] }}/10</span></div>
    <div class="recipe-meta"><span>{{ glassLabel }}</span><span>{{ recipe.alcoholic ? `约 ${recipe.abv || 0}% ABV` : '无酒精' }}</span></div>
  </article>
</template>

<style scoped>
.recipe-tile{--tilt-x:0deg;--tilt-y:0deg;--image-x:0px;--image-y:0px;overflow:hidden;min-width:0}.recipe-visual{position:relative;transform:perspective(700px) rotateX(var(--tilt-x)) rotateY(var(--tilt-y));transform-style:preserve-3d;transition:transform .18s ease-out}.recipe-image{display:block;aspect-ratio:4/3;background:#dfe8e1;overflow:hidden;position:relative}.recipe-image img{position:absolute;z-index:0;inset:-4%;width:108%;height:108%;object-fit:cover;opacity:0;transform:translate(var(--image-x),var(--image-y)) scale(1.01);transition:opacity .2s,transform .2s ease-out,filter .28s}.recipe-image img.loaded{opacity:1}.recipe-tile:hover img.loaded,.recipe-tile:focus-within img.loaded{filter:saturate(1.38) contrast(1.08) brightness(1.04)}.motion-field{position:absolute;z-index:1;inset:0;overflow:hidden;pointer-events:none;opacity:.18;mix-blend-mode:screen;transition:opacity .25s}.recipe-tile:hover .motion-field,.recipe-tile:focus-within .motion-field{opacity:.76}.motion-field i{position:absolute;display:block;background:var(--tone-a);box-shadow:0 0 9px color-mix(in srgb,var(--tone-b) 72%,transparent)}
.motion-bubble .motion-field i{left:var(--x);bottom:-12%;width:var(--particle-size);aspect-ratio:1;border:1px solid var(--tone-b);border-radius:50%;background:transparent;animation:thumb-bubble var(--motion-speed) var(--delay) ease-in infinite}.motion-vortex .motion-field i{left:50%;top:50%;width:5px;height:5px;border-radius:50%;transform-origin:0 0;animation:thumb-vortex var(--motion-speed) var(--delay) linear infinite}.motion-strata .motion-field i{left:8%;top:var(--y);width:var(--line-width);height:2px;border-radius:2px;background:var(--tone-a);animation:thumb-strata var(--motion-speed) var(--delay) ease-in-out infinite}.motion-shake .motion-field i,.motion-velvet .motion-field i{left:var(--x);top:var(--y);width:18%;height:3px;border-radius:8px;transform:rotate(-24deg);animation:thumb-shake var(--motion-fast) var(--delay) ease-in-out infinite}.motion-velvet .motion-field i{height:7px;filter:blur(1px);border-radius:50%;background:var(--tone-b)}.motion-frost .motion-field i{left:var(--x);top:var(--y);width:8px;height:8px;background:transparent;border:1.5px solid var(--tone-b);transform:rotate(45deg);animation:thumb-frost var(--motion-speed) var(--delay) ease-in-out infinite}.motion-botanical .motion-field i{left:var(--x);bottom:var(--y);width:8px;height:16px;border-radius:90% 12% 90% 12%;background:var(--tone-c);animation:thumb-botanical var(--motion-speed) var(--delay) ease-in-out infinite}.motion-flare .motion-field i{left:var(--x);bottom:0;width:3px;height:var(--line-length);transform-origin:bottom;background:var(--tone-a);animation:thumb-flare var(--motion-fast) var(--delay) ease-in-out infinite}.motion-pour .motion-field i{left:var(--x);top:var(--y);width:6px;height:6px;border-radius:50% 50% 58% 42%;background:var(--tone-b);animation:thumb-pour var(--motion-speed) var(--delay) ease-in-out infinite}
.preview-button{position:absolute;z-index:3;right:9px;top:9px;width:34px;height:34px;border:1px solid #ffffff66;border-radius:5px;background:#102d29d9;color:#fff;display:grid;place-items:center;backdrop-filter:blur(8px);transition:transform .2s,background .2s}.preview-button:hover,.preview-button:focus-visible{background:#f1b84a;color:#17322c;transform:scale(1.07) rotate(4deg)}.image-fallback{position:absolute;z-index:0;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:7px;color:#30463b;text-align:center;padding:16px}.image-fallback strong{font-size:13px}.image-fallback small{font-size:10px;opacity:.72}.image-fallback.tone-0{background:#dfe8e1}.image-fallback.tone-1{background:#efe2cb;color:#60451f}.image-fallback.tone-2{background:#dce6ea;color:#294957}.image-fallback.tone-3{background:#eadeda;color:#654139}.ready{position:absolute;z-index:2;left:9px;bottom:9px;background:#fff;color:var(--green);padding:5px 7px;border-radius:4px;display:flex;align-items:center;gap:3px;font-size:10px;font-weight:700;box-shadow:0 2px 10px #0002}.recipe-body{padding:13px 13px 7px;display:flex;justify-content:space-between;gap:10px;min-height:78px}.recipe-body small{color:var(--amber);font-weight:700}.recipe-body h3{font-size:16px;margin:3px 0 0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.recipe-body p{font-size:11px;color:var(--muted);margin:3px 0}.heart{border:0;background:none;color:#87908b;padding:4px;align-self:flex-start;transition:transform .18s,color .18s}.heart:hover{transform:scale(1.14) rotate(-8deg)}.heart.active{color:#b8493c}.flavors{display:flex;gap:6px;padding:0 13px 10px}.flavors span{background:#eef2ee;color:#456052;border-radius:3px;padding:4px 6px;font-size:10px}.recipe-meta{border-top:1px solid #edf0ed;padding:9px 13px;display:flex;justify-content:space-between;gap:8px;color:var(--muted);font-size:11px}.recipe-meta span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
@keyframes thumb-bubble{0%{transform:translateY(0) scale(.6);opacity:0}18%{opacity:.9}100%{transform:translate(var(--offset),-185px) scale(1.25);opacity:0}}@keyframes thumb-vortex{from{transform:rotate(var(--angle)) translateX(var(--orbit)) scale(.7)}to{transform:rotate(calc(360deg + var(--angle))) translateX(var(--orbit)) scale(1.15)}}@keyframes thumb-strata{50%{transform:translateX(var(--offset)) scaleX(.72);background:var(--tone-b)}}@keyframes thumb-shake{0%,100%{transform:translate(-8px,7px) rotate(-24deg);opacity:.25}50%{transform:translate(12px,-9px) rotate(-18deg);opacity:1}}@keyframes thumb-frost{50%{transform:translateY(-18px) rotate(135deg) scale(1.35);border-color:var(--tone-c)}}@keyframes thumb-botanical{50%{transform:translate(var(--offset),-25px) rotate(28deg);background:var(--tone-a)}}@keyframes thumb-flare{50%{transform:scaleY(1.55) skewX(-5deg);background:var(--tone-b);opacity:.9}}@keyframes thumb-pour{50%{transform:translate(15px,28px) rotate(35deg) scale(1.3);background:var(--tone-a)}}
@media(max-width:760px){.recipe-image{aspect-ratio:16/9}.motion-field{opacity:.28}}@media(prefers-reduced-motion:reduce){.recipe-visual,.recipe-image img,.preview-button,.heart,.motion-field{transition:none}.recipe-visual{transform:none}.recipe-image img{transform:none}.motion-field i{animation:none!important}.recipe-tile:hover .motion-field,.recipe-tile:focus-within .motion-field{opacity:.28}}
</style>
