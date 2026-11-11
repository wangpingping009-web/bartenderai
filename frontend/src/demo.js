import { ApiError } from './api'
import recipes from './demo-recipes'
import { banquet, chooseRecipe, deconstruct, matchRecipes, missingIngredients, mocktail, personas, substitute, themes } from './demo-mixology'

const storageKey = 'bartenderai-pages-demo'

function readState() {
  const initial = {
    favorites: [], feedback: {}, inventory: [], creations: [], conversations: [],
    user: { display_name: '演示访客', profile: {} },
  }
  try {
    return { ...initial, ...JSON.parse(localStorage.getItem(storageKey)) }
  } catch {
    return initial
  }
}

let state = readState()

function save(next) {
  state = next
  try { localStorage.setItem(storageKey, JSON.stringify(state)) } catch { /* Keep the session usable. */ }
}

function listRecipes(query) {
  const words = (query.get('q') || '').toLowerCase().trim().split(/\s+/).filter(Boolean)
  const items = recipes.filter(recipe => {
    const text = [recipe.name, recipe.name_cn, ...recipe.ingredients.flatMap(item => [item.name, item.name_zh])].join(' ').toLowerCase()
    return words.every(word => text.includes(word))
      && (!query.has('category') || recipe.category === query.get('category'))
      && (!query.has('base_spirit') || recipe.base_spirit === query.get('base_spirit'))
      && (!query.has('alcoholic') || String(recipe.alcoholic) === query.get('alcoholic'))
      && (!query.has('flavor') || recipe.flavor[query.get('flavor')] >= 6)
      && (!query.has('abv_min') || recipe.abv >= Number(query.get('abv_min')))
      && (!query.has('abv_max') || recipe.abv <= Number(query.get('abv_max')))
      && (query.get('available_only') !== 'true' || !missingIngredients(recipe, state.inventory).length)
      && (query.get('favorites_only') !== 'true' || state.favorites.includes(recipe.name))
  })
  const sort = query.get('sort')
  if (sort === 'name') items.sort((a, b) => a.name.localeCompare(b.name))
  else if (sort === 'abv_asc') items.sort((a, b) => a.abv - b.abv)
  else if (sort === 'abv_desc') items.sort((a, b) => b.abv - a.abv)
  else if (['sweet', 'sour', 'aroma'].includes(sort)) items.sort((a, b) => b.flavor[sort] - a.flavor[sort])
  const page = Number(query.get('page') || 1)
  const page_size = Number(query.get('page_size') || 24)
  return { items: items.slice((page - 1) * page_size, page * page_size).map(recipe => ({ ...recipe, available: !missingIngredients(recipe, state.inventory).length })), total: items.length, page, page_size }
}

const progress = () => {
  const count = state.favorites.length + state.creations.length + Object.keys(state.feedback).length
  return {
    xp: count * 10,
    level: { name: count >= 5 ? '吧台练习生' : '配方探索者', xp_to_next: Math.max(0, 50 - count * 10) },
    badges: [
      { id: 'favorite', emoji: '♡', name: '初次收藏', desc: '收藏第一款配方', progress: Math.min(1, state.favorites.length), threshold: 1, earned: !!state.favorites.length },
      { id: 'create', emoji: '✦', name: '首次创作', desc: '保存第一杯试调配方', progress: Math.min(1, state.creations.length), threshold: 1, earned: !!state.creations.length },
    ],
  }
}

const lookupRecipe = name => recipes.find(recipe => recipe.name === name || recipe.id === name)
const favorites = () => recipes.filter(recipe => state.favorites.includes(recipe.name)).map(recipe => ({ name: recipe.name, recipe }))
const timestamp = () => new Date().toISOString()

function conversationRoute(pathname, method, options) {
  const [, , , id, resource] = pathname.split('/')
  if (!id) {
    if (method === 'GET') return { items: state.conversations.map(({ messages, ...item }) => item) }
    const item = { id: crypto.randomUUID(), title: JSON.parse(options.body).title, updated_at: timestamp(), messages: [] }
    save({ ...state, conversations: [item, ...state.conversations] })
    return item
  }
  const item = state.conversations.find(entry => entry.id === id)
  if (!item) throw new ApiError('找不到这条会话', 404)
  if (resource === 'messages') return { items: item.messages }
  if (method === 'PATCH') item.title = JSON.parse(options.body).title
  save({ ...state, conversations: method === 'DELETE' ? state.conversations.filter(entry => entry !== item) : state.conversations })
  return null
}

export async function demoChat(id, text, onEvent, signal) {
  const item = state.conversations.find(entry => entry.id === id)
  if (!item) throw new ApiError('找不到这条会话', 404)
  signal?.throwIfAborted()
  onEvent({ type: 'status', agent: 'retriever', message: '正在匹配演示配方' })
  const recipe = chooseRecipe(text)
  const answer = recipe
    ? `试试${recipe.name_cn}（${recipe.name}）。\n\n${recipe.ingredients.map(ingredient => `${ingredient.name_zh} ${ingredient.amount}`).join('、')}。\n\n${recipe.steps.map((step, index) => `${index + 1}. ${step}`).join('\n')}`
    : '当前示例库没有符合条件的配方，可以试试按酒名、材料或无酒精筛选。'
  const metadata = { recipe: recipe || null, capability_mode: 'local_retrieval', trace: [{ agent: 'retriever', message: '浏览器匹配示例配方' }] }
  onEvent({ type: 'partial', text: answer })
  await new Promise(resolve => setTimeout(resolve, 180))
  signal?.throwIfAborted()
  item.messages = [...item.messages, { role: 'user', content: text }, { role: 'assistant', content: answer, metadata }]
  if (item.title === '新对话') item.title = text.slice(0, 24)
  item.updated_at = timestamp()
  save({ ...state, conversations: [item, ...state.conversations.filter(entry => entry !== item)] })
  onEvent({ type: 'done', answer, ...metadata })
}

export async function demoCreate(payload, onEvent, signal) {
  signal?.throwIfAborted()
  const template = chooseRecipe(payload.preferences, payload.base_spirits)
  if (!template) {
    onEvent({ type: 'done', result: { ok: false, error: '当前示例库没有这种基酒的配方，请试试金酒、朗姆或龙舌兰。' } })
    return
  }
  const style = personas.find(item => item.key === payload.persona) || personas[0]
  const stage = { type: 'status', stage: 'create', status: 'working', title: '匹配调制结构', detail: `以${template.name_cn}作为本地模板` }
  onEvent(stage)
  await new Promise(resolve => setTimeout(resolve, 200))
  signal?.throwIfAborted()
  const recipe = {
    ...template, name_cn: `${style.name} · ${template.name_cn}`,
    description: `基于${template.name_cn}的试调档案，保留原配方比例供对照。`,
    tips: payload.persona === 'japanese' ? '量取每项材料，记录摇和或搅拌时间。' : '先按原比例调一小杯，再逐项调整。',
  }
  const ready = { type: 'status', stage: 'ready', status: 'done', title: '试调档案已生成', detail: recipe.tips }
  onEvent(ready)
  const record = {
    id: crypto.randomUUID(), created_at: timestamp(), recipe, capability_mode: 'local_rules',
    brief: { summary: payload.preferences, flavor_targets: {}, avoid: [] },
    review: { review_mode: 'rules', intent_match: `示例模板为${template.name_cn}，所选风格为${style.name}。`, feasibility: '沿用示例配方的材料、用量与调法。' },
    collaboration: [{ ...stage, status: 'done' }, ready],
  }
  save({ ...state, creations: [record, ...state.creations] })
  onEvent({ type: 'done', result: { ...record, ok: true, attempts: 1, creation_id: record.id, references: [template] } })
}

export const visionExample = () => ({
  observations: ['高球杯', '青柠装饰', '薄荷叶', '带气泡'],
  candidates: [
    { name: 'Mojito', confidence: 'medium', reason: '薄荷、青柠与气泡是莫吉托常见的外观组合。', recipe: lookupRecipe('mojito') },
    { name: 'Mint Lime Soda', confidence: 'medium', reason: '无酒精青柠苏打可以呈现相同外观。', recipe: lookupRecipe('mint-lime-soda') },
  ],
  disclaimer: '以上为固定样例，用来展示识方结果页。真实识别需要部署视觉服务。',
})

export function demoRequest(path, options) {
  const { pathname, searchParams } = new URL(path, location.origin)
  const method = options.method || 'GET'
  if (pathname === '/api/capabilities') return { llm: { available: false, configured: false }, vision: { available: false } }
  if (pathname.startsWith('/api/conversations')) return conversationRoute(pathname, method, options)
  if (pathname === '/api/me') {
    if (method === 'PATCH') save({ ...state, user: { ...state.user, ...JSON.parse(options.body) } })
    return { ...state.user, progress: progress() }
  }
  if (pathname === '/api/me/export') return state
  if (pathname === '/api/me/inventory') {
    if (method === 'PUT') save({ ...state, inventory: JSON.parse(options.body).items })
    return { items: state.inventory }
  }
  if (pathname === '/api/me/inventory/matches') return matchRecipes(state.inventory)
  if (pathname === '/api/recipes/personas') return { personas }
  if (pathname === '/api/recipes/creations') return { items: state.creations }
  if (pathname.startsWith('/api/recipes/creations/')) {
    const id = pathname.split('/').at(-1)
    const item = state.creations.find(record => record.id === id)
    if (!item) throw new ApiError('找不到这个创作档案', 404)
    if (method === 'DELETE') save({ ...state, creations: state.creations.filter(record => record !== item) })
    return item
  }
  if (pathname === '/api/recipes/substitute') return substitute(searchParams.get('q') || '')
  if (pathname === '/api/recipes/deconstruct') return deconstruct(JSON.parse(options.body))
  if (pathname === '/api/fun/mocktail') {
    const recipe = lookupRecipe(searchParams.get('name'))
    if (!recipe) throw new ApiError('没有找到这款演示配方', 404)
    return mocktail(recipe)
  }
  if (pathname === '/api/fun/progress') return progress()
  if (pathname === '/api/fun/daily') {
    const date = new Date()
    const index = Math.floor(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()) / 86400000) % recipes.length
    return { date: date.toLocaleDateString('zh-CN'), recipe: recipes[index] }
  }
  if (pathname === '/api/fun/challenge') return { title: '青柠与薄荷', description: '用一杯清爽饮品比较柑橘酸度与薄荷香气。', ingredients: ['青柠汁', '薄荷', '苏打水'] }
  if (pathname === '/api/themes') return { themes }
  if (pathname.startsWith('/api/themes/')) return themes.find(theme => theme.key === pathname.split('/').at(-1))
  if (pathname === '/api/fun/context') {
    if (searchParams.get('time') === 'morning') return { keywords: ['薄荷青柠苏打'], summary: '早晨试试无酒精薄荷苏打，清爽且容易调制。' }
    if (searchParams.get('weather') === 'hot') return { keywords: ['青柠', '苏打水'], summary: '炎热天气可以从冷藏气泡水和鲜榨青柠开始。' }
    if (searchParams.get('weather') === 'cold' || searchParams.get('weather') === 'rain') return { keywords: ['橙皮'], summary: '试试橙皮和苦甜层次突出的配方。' }
    if (searchParams.get('mood') === 'tired' || searchParams.get('mood') === 'stressed') return { keywords: ['橙香姜汁气泡饮'], summary: '试试无酒精姜汁气泡饮，备料和调制都很简单。' }
    return { keywords: ['青柠'], summary: '用青柠的酸度平衡甜味，再按喜好选择气泡或摇和风格。' }
  }
  if (pathname === '/api/fun/banquet') {
    const payload = JSON.parse(options.body)
    if (!Number.isInteger(payload.headcount) || payload.headcount < 1 || payload.headcount > 100) throw new ApiError('请输入 1 到 100 之间的整数人数', 400)
    if (!payload.names.length) throw new ApiError('请输入至少一款配方名称', 400)
    return banquet(payload)
  }
  if (pathname === '/api/admin/overview') return { usage: { totals: { calls: 0 } } }
  if (pathname === '/api/admin/prompts') return { versions: [] }
  if (pathname === '/api/admin/knowledge') return {}
  if (pathname === '/api/admin/jobs') return { items: [] }
  if (pathname === '/api/recipes') return listRecipes(searchParams)
  if (pathname.startsWith('/api/recipes/')) {
    const recipe = recipes.find(item => item.id === pathname.split('/').at(-1))
    if (recipe) return recipe
    throw new ApiError('没有找到这款演示配方', 404)
  }
  if (pathname === '/api/me/favorites') {
    if (method === 'POST') {
      const { recipe } = JSON.parse(options.body)
      save({ ...state, favorites: [...new Set([...state.favorites, recipe.name])] })
      return null
    }
    return { items: favorites() }
  }
  if (method === 'DELETE' && pathname.startsWith('/api/me/favorites/')) {
    const name = decodeURIComponent(pathname.split('/').at(-1))
    save({ ...state, favorites: state.favorites.filter(item => item !== name) })
    return null
  }
  if (method === 'POST' && pathname === '/api/feedback') {
    const feedback = JSON.parse(options.body)
    save({ ...state, feedback: { ...state.feedback, [feedback.recipe_id]: feedback } })
    return null
  }
  throw new ApiError('在线演示暂未开放此功能', 404)
}
