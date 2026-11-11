<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as THREE from 'three'

const props = defineProps({
  recipe: { type: Object, required: true },
  background: { type: String, default: '#102d29' },
  activeStep: { type: Number, default: 0 },
  preparedIndices: { type: Array, default: () => [] },
  highlightIngredient: { type: Number, default: -1 },
  timerProgress: { type: Number, default: 0 },
  timerRunning: { type: Boolean, default: false },
})
const emit = defineEmits(['ready', 'unavailable'])
const host = ref(null)
let renderer, scene, camera, cocktail, liquid, bubbles, foam, crystals, aroma, frame, observer, visibilityObserver
let contourRings = [], visualIdentity = null
let pointerX = 0, pointerY = 0, burst = 0, mixImpulse = 0, disposed = false
let dragging = false, lastPointerX = 0, lastPointerY = 0, interactionCount = 0
let sceneVisible = true, pageVisible = !document.hidden
const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

function hashText(text = '') {
  let value = 2166136261
  for (const char of text) value = Math.imul(value ^ char.charCodeAt(0), 16777619)
  return value >>> 0
}
function randomFactory(seed) {
  let state = seed || 1
  return () => ((state = Math.imul(state ^ (state >>> 15), 1 | state) + 0x6d2b79f5) >>> 0) / 4294967296
}
function particleBudget() {
  const viewport = window.innerWidth
  const base = viewport <= 420 ? 900 : viewport <= 768 ? 1500 : 2600
  const hardwareScale = (navigator.hardwareConcurrency || 8) <= 4 ? .78 : 1
  return Math.round(base * hardwareScale)
}
function glassShape(glass = '') {
  const name = glass.toLowerCase()
  if (name.includes('coupe') || name.includes('saucer') || name.includes('浅碟')) return { kind: 'coupe', radius: 1.18, height: 1.25, stem: 1.05 }
  if (name.includes('martini') || name.includes('cocktail') || name.includes('马天尼') || name.includes('鸡尾')) return { kind: 'cone', radius: 1.18, height: 1.65, stem: 1.15 }
  if (name.includes('flute') || name.includes('champagne') || name.includes('香槟')) return { kind: 'flute', radius: .52, height: 2.75, stem: .75 }
  if (name.includes('hurricane') || name.includes('飓风')) return { kind: 'hurricane', radius: .86, height: 2.65, stem: .45 }
  if (name.includes('wine') || name.includes('葡萄酒')) return { kind: 'wine', radius: .9, height: 2.15, stem: .75 }
  if (name.includes('highball') || name.includes('collins') || name.includes('高球') || name.includes('柯林')) return { kind: 'highball', radius: .72, height: 2.8, stem: 0 }
  if (name.includes('shot') || name.includes('烈酒杯')) return { kind: 'shot', radius: .62, height: 1.5, stem: 0 }
  return { kind: 'rocks', radius: .96, height: 1.8, stem: 0 }
}
function radiusAt(shape, normalizedY) {
  if (shape.kind === 'cone') return Math.max(.08, shape.radius * normalizedY)
  if (shape.kind === 'flute') return shape.radius * (.72 + normalizedY * .28)
  if (shape.kind === 'coupe') return shape.radius * Math.max(.14, Math.sin(Math.min(1, normalizedY) * Math.PI * .54))
  if (shape.kind === 'hurricane') return shape.radius * (.56 + Math.sin(normalizedY * Math.PI * 1.45) * .23 + normalizedY * .18)
  if (shape.kind === 'wine') return shape.radius * (.42 + Math.sin(normalizedY * Math.PI) * .58)
  if (shape.kind === 'rocks') return shape.radius * (.88 + normalizedY * .12)
  if (shape.kind === 'shot') return shape.radius * (.82 + normalizedY * .18)
  return shape.radius
}
function palette() {
  const flavor = props.recipe.flavor || {}
  const seed = hashText(`${props.recipe.id}-${props.recipe.name}`)
  const offset = (seed % 31) - 15
  const hue = (flavor.sour >= 7 ? 50 : flavor.sweet >= 7 ? 338 : flavor.bitter >= 6 ? 16 : flavor.aroma >= 7 ? 145 : 188) + offset
  return {
    liquid: new THREE.Color(`hsl(${hue}, 94%, 58%)`),
    highlight: new THREE.Color(`hsl(${(hue + 54) % 360}, 98%, 69%)`),
    glass: new THREE.Color('#bdefff'),
    garnish: new THREE.Color(flavor.aroma >= 6 ? '#7df0a7' : '#ffd166'),
  }
}
function ingredientNames() {
  return (props.recipe.ingredients || []).map(item => String(item.name_zh || item.name || '').toLowerCase())
}
function ingredientColor(name, fallback) {
  const mappings = [
    [/蓝|blue cura|蓝橙/, '#25a7ff'], [/蔓越莓|石榴|grenadine|cranberry|莓/, '#ff4178'],
    [/金巴利|阿佩罗|campari|aperol/, '#ff5848'], [/咖啡|可乐|coffee|cola/, '#9d5845'],
    [/百利|bailey|奶|cream|milk|coconut/, '#fff0c7'], [/杏仁|amaretto/, '#e8a23e'],
    [/菠萝|pineapple/, '#ffd52f'], [/百香果|passion fruit/, '#ff8b32'],
    [/桃|peach/, '#ff9672'], [/青柠|lime/, '#6fe36e'],
    [/柠檬|lemon/, '#ffe55c'], [/橙|orange/, '#ff9e28'],
    [/薄荷|罗勒|香草|mint|basil|herb/, '#47d69a'],
    [/威士忌|白兰地|朗姆|whisk|brandy|cognac|dark rum/, '#dc8a3d'],
    [/葡萄|香槟|vermouth|wine|champagne/, '#f4ca64'],
    [/汤力|苏打|气泡|tonic|soda|sparkling/, '#9cecff'],
    [/金酒|伏特加|gin|vodka/, '#c2ebff'],
  ]
  const match = mappings.find(([pattern]) => pattern.test(name))
  return new THREE.Color(match?.[1] || fallback)
}
function compositionPalette() {
  const base = palette()
  const colors = [
    ...ingredientNames().map(name => ingredientColor(name, base.liquid)),
    base.liquid, base.highlight, base.garnish,
  ]
  const unique = []
  for (const color of colors) {
    if (!unique.some(item => item.getHexString() === color.getHexString())) unique.push(color)
  }
  return (unique.length ? unique : [base.liquid, base.highlight]).slice(0, 5)
}
function ingredientPalette() {
  const base = palette()
  const colors = ingredientNames().map(name => ingredientColor(name, base.liquid))
  if (!colors.length) return [base.liquid, base.highlight]
  if (colors.length === 1) return [colors[0], base.highlight]
  return colors
}
function technique() {
  const method = String(props.recipe.method || '').toLowerCase()
  if (/layer|分层|漂浮/.test(method)) return 'layer'
  if (/shake|摇/.test(method)) return 'shake'
  if (/stir|搅拌/.test(method)) return 'stir'
  if (/blend|搅打|电动/.test(method)) return 'blend'
  if (/build|直调/.test(method)) return 'build'
  return 'balanced'
}
function stepMotion() {
  const step = String((props.recipe.steps || [])[props.activeStep] || '').toLowerCase()
  if (/shake|摇|雪克/.test(step)) return 'shake'
  if (/stir|搅拌|吧勺/.test(step)) return 'stir'
  if (/blend|搅打|电动/.test(step)) return 'blend'
  if (/strain|过滤|滤入|滤出/.test(step)) return 'strain'
  if (/garnish|装饰|点缀|杯沿/.test(step)) return 'garnish'
  if (/pour|倒入|注入|加入|量取/.test(step)) return 'pour'
  return technique()
}
function carbonated() { return ingredientNames().some(name => /汤力|苏打|气泡|香槟|啤酒|可乐|tonic|soda|sparkling|champagne|beer|cola/.test(name)) }
function creamy() { return ingredientNames().some(name => /奶|蛋清|椰浆|cream|milk|egg white|coconut/.test(name)) }
function icy() { return ingredientNames().some(name => /冰|ice|frozen/.test(name)) || technique() === 'blend' }
function visualProfile() {
  const flavor = props.recipe.flavor || {}
  const mode = technique()
  const seed = hashText(`${props.recipe.id}-${props.recipe.name}-${props.recipe.glass}-${props.recipe.method}`)
  let topology = 'slow-pour'
  if (mode === 'layer') topology = 'density-strata'
  else if (mode === 'blend') topology = 'frozen-cloud'
  else if (mode === 'shake' && creamy()) topology = 'velvet-turbulence'
  else if (mode === 'shake') topology = 'bright-turbulence'
  else if (mode === 'stir') topology = flavor.strong >= 7 || flavor.bitter >= 6 ? 'amber-vortex' : 'clear-spiral'
  else if (carbonated()) topology = 'sparkling-column'
  else if (flavor.aroma >= 6) topology = 'botanical-drift'
  else if (flavor.strong >= 7) topology = 'spirit-flare'
  return {
    topology,
    variant: seed % 5,
    seed,
    turbulence: .55 + ((seed >>> 5) % 35) / 100,
    orbit: .7 + ((seed >>> 11) % 45) / 100,
    wave: 1.1 + ((seed >>> 17) % 80) / 100,
  }
}
function garnishKind() {
  const garnish = String(props.recipe.garnish || '').toLowerCase()
  if (!garnish || /无|none|不额外/.test(garnish)) return 'none'
  if (/樱桃|cherry|莓/.test(garnish)) return 'cherry'
  if (/薄荷|罗勒|香草|mint|basil|herb/.test(garnish)) return 'herb'
  return 'citrus'
}
function pointsObject(positions, color, size, opacity = 1, vertexColors = null) {
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
  if (vertexColors?.length) geometry.setAttribute('color', new THREE.Float32BufferAttribute(vertexColors, 3))
  const material = new THREE.PointsMaterial({
    color: vertexColors?.length ? '#ffffff' : color, vertexColors: Boolean(vertexColors?.length),
    size, transparent: true, opacity, depthWrite: false,
    blending: THREE.AdditiveBlending, sizeAttenuation: true,
  })
  return new THREE.Points(geometry, material)
}
function buildCocktail() {
  const seed = hashText(`${props.recipe.id}-${props.recipe.name}-${props.recipe.glass}`)
  const random = randomFactory(seed)
  const shape = glassShape(props.recipe.glass)
  const colors = palette()
  const layers = ingredientPalette()
  const mixTechnique = technique()
  visualIdentity = visualProfile()
  cocktail = new THREE.Group()
  cocktail.position.y = shape.stem ? .25 : 0
  scene.add(cocktail)

  const liquidPositions = []
  const liquidColors = []
  const ingredientIndices = []
  const phases = []
  const particleCount = particleBudget()
  for (let index = 0; index < particleCount; index += 1) {
    let ny = random() * .76 + .06
    let layerIndex = Math.floor(random() * layers.length)
    if (visualIdentity.topology === 'density-strata') {
      layerIndex = index % layers.length
      ny = .06 + ((layerIndex + .08 + random() * .82) / layers.length) * .76
    }
    const density = visualIdentity.topology === 'frozen-cloud' ? Math.cbrt(random()) : Math.sqrt(random())
    const radius = radiusAt(shape, ny) * .86 * density
    let angle = random() * Math.PI * 2
    if (/spiral|vortex/.test(visualIdentity.topology)) angle = ny * Math.PI * (4.5 + visualIdentity.variant * .45) + random() * 1.9
    if (/turbulence/.test(visualIdentity.topology)) angle += Math.sin(ny * 18 + visualIdentity.variant) * .34
    liquidPositions.push(Math.cos(angle) * radius, -shape.height / 2 + ny * shape.height, Math.sin(angle) * radius)
    ingredientIndices.push(layerIndex)
    phases.push(random() * Math.PI * 2)
    const particleColor = layers[layerIndex].clone().lerp(colors.highlight, .08 + random() * .24)
    liquidColors.push(particleColor.r, particleColor.g, particleColor.b)
  }
  const pointSize = visualIdentity.topology === 'frozen-cloud' ? .068 : creamy() ? .061 : .054
  liquid = pointsObject(liquidPositions, colors.liquid, pointSize, .94, liquidColors)
  liquid.material.blending = THREE.NormalBlending
  liquid.material.opacity = .96
  liquid.userData.base = Float32Array.from(liquidPositions)
  liquid.userData.baseColors = Float32Array.from(liquidColors)
  liquid.userData.ingredientIndices = Uint16Array.from(ingredientIndices)
  liquid.userData.phases = Float32Array.from(phases)
  liquid.userData.technique = mixTechnique
  cocktail.add(liquid)

  const highlightPositions = []
  for (let index = 0; index < Math.round(particleCount * .16); index += 1) {
    const ny = random() * .72 + .1
    const radius = radiusAt(shape, ny) * (.75 + random() * .1)
    const angle = random() * Math.PI * .5 - Math.PI * .25
    highlightPositions.push(Math.cos(angle) * radius, -shape.height / 2 + ny * shape.height, Math.sin(angle) * radius)
  }
  cocktail.add(pointsObject(highlightPositions, colors.highlight, .042, .8))

  const glassPositions = []
  const rings = 18
  for (let ring = 0; ring <= rings; ring += 1) {
    const ny = ring / rings
    const y = -shape.height / 2 + ny * shape.height
    const radius = radiusAt(shape, ny)
    for (let slice = 0; slice < 46; slice += 1) {
      const angle = slice / 46 * Math.PI * 2
      if (random() > .43) glassPositions.push(Math.cos(angle) * radius, y, Math.sin(angle) * radius)
    }
  }
  if (shape.stem) {
    for (let index = 0; index < 130; index += 1) {
      const y = -shape.height / 2 - random() * shape.stem
      const angle = random() * Math.PI * 2
      const radius = .035 + random() * .025
      glassPositions.push(Math.cos(angle) * radius, y, Math.sin(angle) * radius)
    }
    for (let index = 0; index < 150; index += 1) {
      const radius = Math.sqrt(random()) * .67
      const angle = random() * Math.PI * 2
      glassPositions.push(Math.cos(angle) * radius, -shape.height / 2 - shape.stem, Math.sin(angle) * radius * .48)
    }
  }
  cocktail.add(pointsObject(glassPositions, colors.glass, .025, .54))

  contourRings = []
  const ringCount = visualIdentity.topology === 'density-strata' ? Math.max(2, layers.length) : /spiral|vortex/.test(visualIdentity.topology) ? 4 : 1
  for (let index = 0; index < ringCount; index += 1) {
    const ny = visualIdentity.topology === 'density-strata' ? .1 + (index + 1) / (ringCount + 1) * .68 : .2 + index * .16
    const radius = radiusAt(shape, ny) * .83
    const points = Array.from({ length: 64 }, (_, slice) => {
      const angle = slice / 64 * Math.PI * 2
      return new THREE.Vector3(Math.cos(angle) * radius, -shape.height / 2 + ny * shape.height, Math.sin(angle) * radius)
    })
    const geometry = new THREE.BufferGeometry().setFromPoints(points)
    const ring = new THREE.LineLoop(geometry, new THREE.LineBasicMaterial({
      color: layers[index % layers.length], transparent: true,
      opacity: visualIdentity.topology === 'density-strata' ? .38 : .2,
      blending: THREE.AdditiveBlending, depthWrite: false,
    }))
    ring.rotation.x = visualIdentity.topology === 'density-strata' ? 0 : (index - 1.5) * .08
    contourRings.push(ring); cocktail.add(ring)
  }

  const bubblePositions = []
  const hasBubbles = carbonated()
  const bubbleCount = hasBubbles ? 330 : 42
  for (let index = 0; index < bubbleCount; index += 1) {
    const ny = random() * .68 + .08
    const radius = radiusAt(shape, ny) * .72 * Math.sqrt(random())
    const angle = random() * Math.PI * 2
    bubblePositions.push(Math.cos(angle) * radius, -shape.height / 2 + ny * shape.height, Math.sin(angle) * radius)
  }
  bubbles = pointsObject(bubblePositions, '#ffffff', .027, .72)
  bubbles.userData.speed = Float32Array.from({ length: bubblePositions.length / 3 }, () => (hasBubbles ? .004 : .001) + random() * (hasBubbles ? .01 : .002))
  bubbles.userData.floor = -shape.height / 2 + .08
  bubbles.userData.ceiling = shape.height * .27
  cocktail.add(bubbles)

  const foamPositions = []
  if (creamy()) {
    for (let index = 0; index < Math.round(particleCount * .18); index += 1) {
      const radius = radiusAt(shape, .8) * .82 * Math.sqrt(random())
      const angle = random() * Math.PI * 2
      foamPositions.push(Math.cos(angle) * radius, shape.height * .305 + random() * .11, Math.sin(angle) * radius)
    }
  }
  foam = foamPositions.length ? pointsObject(foamPositions, '#fff4d7', .058, .86) : null
  if (foam) { foam.userData.base = Float32Array.from(foamPositions); cocktail.add(foam) }

  const crystalPositions = []
  if (icy()) {
    for (let index = 0; index < Math.round(particleCount * .12); index += 1) {
      const ny = random() * .67 + .09
      const radius = radiusAt(shape, ny) * (.35 + random() * .52)
      const angle = random() * Math.PI * 2
      crystalPositions.push(Math.cos(angle) * radius, -shape.height / 2 + ny * shape.height, Math.sin(angle) * radius)
    }
  }
  crystals = crystalPositions.length ? pointsObject(crystalPositions, '#d9fbff', .075, .66) : null
  if (crystals) { crystals.userData.base = Float32Array.from(crystalPositions); cocktail.add(crystals) }

  const aromaPositions = []
  const aromaLevel = Number((props.recipe.flavor || {}).aroma || 0)
  if (aromaLevel >= 5 || garnishKind() !== 'none') {
    const count = 80 + aromaLevel * 14
    for (let index = 0; index < count; index += 1) {
      const progress = index / count
      const angle = progress * Math.PI * (4 + visualIdentity.variant) + random() * .4
      const radius = shape.radius * (1.05 + random() * .42)
      aromaPositions.push(Math.cos(angle) * radius, -.45 + progress * 2.9 + Math.sin(angle * 2) * .12, Math.sin(angle) * radius)
    }
  }
  aroma = aromaPositions.length ? pointsObject(aromaPositions, colors.garnish, .034, .48) : null
  if (aroma) { aroma.userData.base = Float32Array.from(aromaPositions); cocktail.add(aroma) }

  const garnishPositions = []
  const garnishY = shape.height / 2 + .05
  const garnishType = garnishKind()
  for (let index = 0; garnishType !== 'none' && index < 260; index += 1) {
    const angle = random() * Math.PI * 2
    if (garnishType === 'cherry') {
      const radius = Math.cbrt(random()) * .24
      garnishPositions.push(shape.radius * .48 + Math.cos(angle) * radius, garnishY + Math.sin(angle) * radius, Math.sin(random() * Math.PI * 2) * radius)
    } else if (garnishType === 'herb') {
      const height = random() * .68
      garnishPositions.push(shape.radius * .4 + Math.sin(height * 18) * .09, garnishY + height, (random() - .5) * .18)
    } else {
      const radius = shape.radius * (.72 + random() * .12)
      const arc = angle * .68 - Math.PI * .75
      garnishPositions.push(Math.cos(arc) * radius, garnishY + Math.sin(angle * 2) * .035, Math.sin(arc) * radius)
    }
  }
  if (garnishPositions.length) {
    const garnish = pointsObject(garnishPositions, colors.garnish, .032, .82)
    garnish.rotation.x = .18
    cocktail.add(garnish)
  }
}
function updateIngredientEmphasis() {
  if (!liquid?.geometry.attributes.color) return
  const target = Number(props.highlightIngredient)
  const prepared = new Set((props.preparedIndices || []).map(Number))
  const colors = liquid.geometry.attributes.color.array
  const base = liquid.userData.baseColors
  const indices = liquid.userData.ingredientIndices
  for (let index = 0; index < indices.length; index += 1) {
    const ingredientIndex = indices[index]
    const factor = target >= 0
      ? (ingredientIndex === target ? 1.35 : .28)
      : (prepared.has(ingredientIndex) ? 1.16 : .9)
    const offset = index * 3
    colors[offset] = Math.min(1, base[offset] * factor)
    colors[offset + 1] = Math.min(1, base[offset + 1] * factor)
    colors[offset + 2] = Math.min(1, base[offset + 2] * factor)
  }
  liquid.geometry.attributes.color.needsUpdate = true
}
function resize() {
  if (!renderer || !host.value) return
  const width = Math.max(1, host.value.clientWidth)
  const height = Math.max(1, host.value.clientHeight)
  renderer.setSize(width, height, false)
  camera.aspect = width / height
  camera.updateProjectionMatrix()
  renderer.render(scene, camera)
}
function reportPixels() {
  if (!renderer?.domElement) return
  const gl = renderer.getContext()
  const width = renderer.domElement.width, height = renderer.domElement.height
  const pixels = new Uint8Array(width * height * 4)
  try {
    gl.readPixels(0, 0, width, height, gl.RGBA, gl.UNSIGNED_BYTE, pixels)
    let lit = 0
    const colors = new Set()
    const stride = Math.max(4, Math.floor(pixels.length / 16000 / 4) * 4)
    for (let index = 0; index < pixels.length; index += stride) {
      const r = pixels[index], g = pixels[index + 1], b = pixels[index + 2]
      if (r + g + b > 58) lit += 1
      if (colors.size < 128) colors.add(`${r >> 4}-${g >> 4}-${b >> 4}`)
    }
    renderer.domElement.dataset.litPixels = String(lit)
    renderer.domElement.dataset.colorBuckets = String(colors.size)
    renderer.domElement.dataset.sceneReady = lit > 30 && colors.size > 3 ? 'true' : 'false'
    emit('ready', { litPixels: lit, colorBuckets: colors.size })
  } catch { emit('ready', { litPixels: -1, colorBuckets: -1 }) }
}
function canAnimate() { return !reduceMotion && sceneVisible && pageVisible && !disposed }
function renderFrame(time) { frame = 0; render(time) }
function scheduleRender() {
  if (canAnimate() && !frame) frame = requestAnimationFrame(renderFrame)
  else if (reduceMotion && !disposed) render(performance.now())
}
function handleVisibility() {
  pageVisible = !document.hidden
  if (pageVisible) scheduleRender()
  else { cancelAnimationFrame(frame); frame = 0 }
}
function render(time = 0) {
  if (disposed) return
  const elapsed = time * .001
  const timerDrive = props.timerRunning ? .45 + Math.min(1, Math.max(0, props.timerProgress)) * .55 : 0
  if (cocktail) {
    cocktail.rotation.y += (pointerX * .34 - cocktail.rotation.y) * .045
    cocktail.rotation.x += (-pointerY * .12 - cocktail.rotation.x) * .045
    const mode = stepMotion()
    const shakeOffset = mode === 'shake' ? Math.sin(elapsed * (22 + timerDrive * 8)) * (mixImpulse + timerDrive) * .18 : 0
    cocktail.position.x = shakeOffset
    const processTilt = mode === 'pour' ? -.12 : mode === 'strain' ? .1 : 0
    cocktail.rotation.z = processTilt + Math.sin(elapsed * .55) * .025 + (mode === 'shake' ? Math.cos(elapsed * (18 + timerDrive * 6)) * (mixImpulse + timerDrive) * .08 : 0)
    if (burst > .001) {
      cocktail.scale.setScalar(1 + burst * .055)
      burst *= .91
    } else cocktail.scale.setScalar(1)
    mixImpulse *= .94
  }
  if (liquid && !reduceMotion) {
    const positions = liquid.geometry.attributes.position.array
    const base = liquid.userData.base
    const phases = liquid.userData.phases
    const mode = stepMotion(), identity = visualIdentity || visualProfile()
    const activeKick = mode === 'shake'
      ? .018 + mixImpulse * .035 + timerDrive * .04
      : mode === 'blend'
        ? .012 + mixImpulse * .02 + timerDrive * .03
        : mode === 'stir' ? timerDrive * .009 : 0
    for (let index = 0; index < positions.length; index += 3) {
      const particle = index / 3, phase = phases[particle]
      const bx = base[index], by = base[index + 1], bz = base[index + 2]
      let x = bx, y = by, z = bz
      if (identity.topology === 'density-strata') {
        x += Math.sin(elapsed * identity.wave + phase + bz * 5) * .007
        y += Math.sin(elapsed * .75 + phase) * .003
      } else if (/spiral|vortex/.test(identity.topology)) {
        const turn = elapsed * (.16 + identity.orbit * .11) + by * .12
        x = bx * Math.cos(turn) - bz * Math.sin(turn)
        z = bx * Math.sin(turn) + bz * Math.cos(turn)
        y += Math.sin(elapsed * identity.wave + phase) * .008
      } else if (/turbulence/.test(identity.topology)) {
        const force = .012 + identity.turbulence * .014 + activeKick
        x += Math.sin(elapsed * 3.2 + phase + by * 5) * force
        y += Math.cos(elapsed * 2.7 + phase + bx * 6) * force * .7
        z += Math.sin(elapsed * 3.7 + phase + bz * 4) * force
      } else if (identity.topology === 'frozen-cloud') {
        const pulse = 1 + Math.sin(elapsed * 1.45 + phase) * (.009 + mixImpulse * .014)
        x = bx * pulse; z = bz * pulse
        y += Math.sin(elapsed * 2.1 + phase + bx * 3) * .012
      } else if (identity.topology === 'sparkling-column') {
        x += Math.sin(elapsed * 1.7 + phase + by * 3) * .008
        y += Math.sin(elapsed * .9 + phase) * .006
      } else if (identity.topology === 'botanical-drift') {
        x += Math.sin(elapsed * .8 + phase + by * 2) * .011
        z += Math.cos(elapsed * .65 + phase) * .008
        y += Math.sin(elapsed * 1.1 + phase) * .007
      } else if (identity.topology === 'spirit-flare') {
        const flare = 1 + Math.sin(elapsed * 1.9 + phase) * .014
        x = bx * flare; z = bz * flare
        y += Math.sin(elapsed * 2.4 + phase + bx * 4) * .01
      } else {
        y += Math.sin(elapsed * identity.wave + phase + bx * 3 + bz * 2) * .009
      }
      if (activeKick) {
        x += Math.sin(elapsed * 18 + phase) * activeKick
        y += Math.cos(elapsed * 16 + phase) * activeKick * .55
      }
      positions[index] = x; positions[index + 1] = y; positions[index + 2] = z
    }
    liquid.rotation.y = mode === 'stir'
      ? elapsed * (.08 + identity.orbit * .06 + timerDrive * .3)
      : mode === 'blend' ? elapsed * (.04 + timerDrive * .24) : 0
    liquid.geometry.attributes.position.needsUpdate = true
  }
  if (bubbles && !reduceMotion) {
    const positions = bubbles.geometry.attributes.position.array
    for (let index = 0; index < positions.length; index += 3) {
      positions[index + 1] += bubbles.userData.speed[index / 3] * (1 + burst * 8 + timerDrive * 2.2)
      if (positions[index + 1] > bubbles.userData.ceiling) positions[index + 1] = bubbles.userData.floor
    }
    bubbles.geometry.attributes.position.needsUpdate = true
  }
  if (foam && !reduceMotion) {
    const positions = foam.geometry.attributes.position.array, base = foam.userData.base
    for (let index = 0; index < positions.length; index += 3) {
      positions[index + 1] = base[index + 1] + Math.sin(elapsed * (1.55 + timerDrive * 2.6) + base[index] * 7 + base[index + 2] * 5) * (.008 + burst * .012 + timerDrive * .014)
    }
    foam.rotation.y = Math.sin(elapsed * .35) * .06
    foam.geometry.attributes.position.needsUpdate = true
  }
  if (crystals && !reduceMotion) {
    crystals.rotation.y = elapsed * (.07 + timerDrive * .16) * (visualIdentity?.variant % 2 ? 1 : -1)
    crystals.rotation.z = Math.sin(elapsed * .7) * .035
    crystals.material.opacity = .58 + Math.sin(elapsed * 1.8) * .12
  }
  if (aroma && !reduceMotion) {
    aroma.rotation.y = elapsed * (.035 + (visualIdentity?.variant || 0) * .006)
    aroma.position.y = Math.sin(elapsed * .55) * .045
  }
  contourRings.forEach((ring, index) => {
    ring.rotation.y = /spiral|vortex/.test(visualIdentity?.topology || '') ? elapsed * (.14 + index * .025 + timerDrive * .22) : Math.sin(elapsed * (.4 + timerDrive) + index) * (.025 + timerDrive * .025)
    ring.material.opacity = (/spiral|vortex/.test(visualIdentity?.topology || '') ? .14 : .28) + Math.sin(elapsed * 1.2 + index) * .05
  })
  renderer.render(scene, camera)
  if (canAnimate() && !frame) frame = requestAnimationFrame(renderFrame)
}
function pointerMove(event) {
  const rect = host.value.getBoundingClientRect()
  pointerX = ((event.clientX - rect.left) / rect.width - .5) * 2
  pointerY = ((event.clientY - rect.top) / rect.height - .5) * 2
  if (dragging) {
    const distance = Math.hypot(event.clientX - lastPointerX, event.clientY - lastPointerY)
    mixImpulse = Math.min(1.5, mixImpulse + distance / 95)
    burst = Math.min(1.2, burst + distance / 220)
    lastPointerX = event.clientX; lastPointerY = event.clientY
  }
  if (reduceMotion) render()
}
function resetPointer() { pointerX = 0; pointerY = 0; dragging = false }
function pointerDown(event) {
  dragging = true; lastPointerX = event.clientX; lastPointerY = event.clientY
  interactionCount += 1; burst = 1; mixImpulse = Math.max(mixImpulse, .35)
  renderer.domElement.dataset.interactionCount = String(interactionCount)
  host.value?.setPointerCapture?.(event.pointerId)
  if (reduceMotion) render()
}
function pointerUp(event) {
  dragging = false
  host.value?.releasePointerCapture?.(event.pointerId)
}
function activateBurst() {
  interactionCount += 1; burst = 1.45; mixImpulse = 1.2
  if (renderer?.domElement) renderer.domElement.dataset.interactionCount = String(interactionCount)
  if (reduceMotion) render()
}

function disposeCocktail() {
  if (!cocktail) return
  scene?.remove(cocktail)
  cocktail.traverse(object => { object.geometry?.dispose(); object.material?.dispose?.() })
  cocktail = null; liquid = null; bubbles = null; foam = null; crystals = null; aroma = null; contourRings = []
}
function rebuild() {
  if (!scene || disposed) return
  disposeCocktail()
  buildCocktail()
  const shape = glassShape(props.recipe.glass)
  renderer.domElement.dataset.glassKind = shape.kind
  renderer.domElement.dataset.technique = technique()
  renderer.domElement.dataset.carbonated = String(carbonated())
  renderer.domElement.dataset.garnishKind = garnishKind()
  const interactions = {
    'density-strata': 'drag-layer-ripple', 'frozen-cloud': 'drag-crystal-pulse',
    'velvet-turbulence': 'drag-velvet-shake', 'bright-turbulence': 'drag-shake-surge',
    'amber-vortex': 'drag-amber-vortex', 'clear-spiral': 'drag-clear-spiral',
    'sparkling-column': 'drag-bubble-rise', 'botanical-drift': 'drag-aroma-drift',
    'spirit-flare': 'drag-spirit-flare', 'slow-pour': 'drag-slow-pour',
  }
  renderer.domElement.dataset.interaction = interactions[visualIdentity.topology]
  renderer.domElement.dataset.interactionCount = String(interactionCount)
  renderer.domElement.dataset.visualProfile = visualIdentity.topology
  renderer.domElement.dataset.visualVariant = String(visualIdentity.variant)
  renderer.domElement.dataset.motionSignature = `${visualIdentity.topology}-${visualIdentity.variant}-${visualIdentity.turbulence.toFixed(2)}-${visualIdentity.orbit.toFixed(2)}-${visualIdentity.wave.toFixed(2)}`
  renderer.domElement.dataset.paletteSignature = compositionPalette().map(color => color.getHexString()).join('-')
  renderer.domElement.dataset.particleCount = String(liquid?.geometry?.attributes?.position?.count || 0)
  renderer.domElement.dataset.activeStep = String(props.activeStep)
  renderer.domElement.dataset.stepMotion = stepMotion()
  renderer.domElement.dataset.preparedCount = String((props.preparedIndices || []).length)
  renderer.domElement.dataset.highlightIngredient = String(props.highlightIngredient)
  renderer.domElement.dataset.timerRunning = String(props.timerRunning)
  renderer.domElement.dataset.timerProgress = Number(props.timerProgress || 0).toFixed(3)
  renderer.domElement.setAttribute('aria-label', `${props.recipe.name_cn || props.recipe.name} 粒子酒体`)
  updateIngredientEmphasis()
  render()
  requestAnimationFrame(reportPixels)
}

onMounted(() => {
  try {
    scene = new THREE.Scene()
    scene.background = new THREE.Color(props.background)
    scene.fog = new THREE.FogExp2(props.background, .075)
    camera = new THREE.PerspectiveCamera(38, 1, .1, 100)
    camera.position.set(0, .1, 7.2)
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, preserveDrawingBuffer: true, powerPreference: 'high-performance' })
    const pixelRatioCap = window.innerWidth <= 420 ? 1.25 : window.innerWidth <= 768 ? 1.45 : 1.75
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, pixelRatioCap))
    renderer.outputColorSpace = THREE.SRGBColorSpace
    renderer.domElement.className = 'particle-canvas'
    renderer.domElement.setAttribute('aria-label', `${props.recipe.name_cn || props.recipe.name} 粒子酒体`)
    host.value.appendChild(renderer.domElement)
    rebuild()
    observer = new ResizeObserver(resize)
    observer.observe(host.value)
    visibilityObserver = new IntersectionObserver(([entry]) => {
      sceneVisible = entry?.isIntersecting !== false
      if (sceneVisible) scheduleRender()
      else { cancelAnimationFrame(frame); frame = 0 }
    }, { threshold: .01 })
    visibilityObserver.observe(host.value)
    document.addEventListener('visibilitychange', handleVisibility)
    resize(); render(0)
    requestAnimationFrame(() => { renderer.render(scene, camera); reportPixels() })
  } catch (error) {
    emit('unavailable', error)
  }
})
watch(() => props.recipe, rebuild, { deep: true })
watch(
  () => [props.activeStep, (props.preparedIndices || []).join(','), props.highlightIngredient],
  () => {
    if (!renderer?.domElement) return
    renderer.domElement.dataset.activeStep = String(props.activeStep)
    renderer.domElement.dataset.stepMotion = stepMotion()
    renderer.domElement.dataset.preparedCount = String((props.preparedIndices || []).length)
    renderer.domElement.dataset.highlightIngredient = String(props.highlightIngredient)
    updateIngredientEmphasis()
    burst = Math.max(burst, .75)
    mixImpulse = Math.max(mixImpulse, stepMotion() === 'shake' ? 1 : .35)
    if (reduceMotion) render()
  },
)
watch(
  () => [props.timerRunning, props.timerProgress],
  ([running, progress], previous = []) => {
    if (!renderer?.domElement) return
    renderer.domElement.dataset.timerRunning = String(running)
    renderer.domElement.dataset.timerProgress = Number(progress || 0).toFixed(3)
    if (previous[0] && !running && progress >= .999) {
      burst = Math.max(burst, 1.45)
      mixImpulse = Math.max(mixImpulse, .8)
    }
    scheduleRender()
  },
)
onBeforeUnmount(() => {
  disposed = true
  cancelAnimationFrame(frame)
  observer?.disconnect()
  visibilityObserver?.disconnect()
  document.removeEventListener('visibilitychange', handleVisibility)
  disposeCocktail()
  renderer?.dispose()
  renderer?.domElement?.remove()
})
</script>

<template>
  <div ref="host" class="particle-scene" :style="{ background: props.background }" @pointermove="pointerMove" @pointerleave="resetPointer" @pointerdown="pointerDown" @pointerup="pointerUp" @pointercancel="pointerUp" @dblclick="activateBurst"></div>
</template>

<style scoped>
.particle-scene{position:absolute;inset:0;overflow:hidden;background:#102d29;cursor:grab;touch-action:pan-y}.particle-scene:active{cursor:grabbing}.particle-scene:deep(canvas){display:block;width:100%;height:100%;outline:0}@media(prefers-reduced-motion:reduce){.particle-scene{cursor:default}}
</style>
