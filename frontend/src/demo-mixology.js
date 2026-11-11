import recipes from './demo-recipes'
import substitutions from '../../backend/data/knowledge/substitutions.json'

const aliases = {
  '白朗姆': 'rum', '朗姆': 'rum', '朗姆酒': 'rum', 'white rum': 'rum',
  '波本威士忌': 'whiskey', bourbon: 'whiskey', '威士忌': 'whiskey',
  '糖浆': 'simple syrup', '味美思': 'sweet vermouth', '甜味美思': 'sweet vermouth',
  '君度': 'triple sec', '橙味利口酒': 'triple sec',
}
const normalize = value => aliases[value.trim().toLowerCase()] || value.trim().toLowerCase()

export function missingIngredients(recipe, inventory) {
  const stock = new Set(inventory.map(normalize))
  return recipe.ingredients.filter(item => ![item.name, item.name_zh].some(name => stock.has(normalize(name))))
}

export function matchRecipes(inventory) {
  const results = recipes.map(recipe => {
    const missing = missingIngredients(recipe, inventory)
    return { ...recipe, available: !missing.length, missing_ingredients: missing.map(item => item.name_zh), match_ratio: 1 - missing.length / recipe.ingredients.length }
  }).sort((a, b) => b.match_ratio - a.match_ratio)
  return { ready: results.filter(recipe => recipe.available), nearby: results.filter(recipe => !recipe.available) }
}

export function chooseRecipe(text, bases = []) {
  const normalized = text.toLowerCase()
  const zero = /无酒精|零酒|mocktail/.test(normalized)
  const candidates = recipes.filter(recipe => zero ? !recipe.alcoholic : !bases.length || bases.includes(recipe.base_spirit))
  const spirits = [...new Set(candidates.map(recipe => recipe.base_spirit).filter(Boolean))]
  const namedSpirits = spirits.filter(spirit => normalized.includes(spirit) || candidates.some(recipe => recipe.base_spirit === spirit && normalized.includes(recipe.ingredients[0].name_zh)))
  const matches = namedSpirits.length ? candidates.filter(recipe => namedSpirits.includes(recipe.base_spirit)) : candidates
  const named = candidates.find(recipe => [recipe.name.toLowerCase(), recipe.name_cn].some(name => normalized.includes(name)))
  if (named) return named
  const ingredients = recipe => recipe.ingredients.filter(item => [item.name, item.name_zh].some(name => normalized.includes(name.toLowerCase()))).length
  if (/低甜|不太甜|少甜/.test(normalized)) return [...matches].sort((a,b) => a.flavor.sweet - b.flavor.sweet)[0]
  if (/低酒精|低度/.test(normalized)) return [...matches].filter(recipe => recipe.alcoholic).sort((a,b) => a.abv - b.abv)[0]
  return [...matches].sort((a,b) => ingredients(b) - ingredients(a))[0]
}

export const personas = [
  { key: 'classic', name: '经典平衡', emoji: 'C' },
  { key: 'molecular', name: '现代实验', emoji: 'M' },
  { key: 'japanese', name: '日式精细', emoji: 'J' },
  { key: 'playful', name: '轻松创意', emoji: 'P' },
]

export function substitute(text) {
  const q = text.toLowerCase()
  const matched = substitutions.filter(item => [item.title, item.title_cn].some(title =>
    title.toLowerCase().split(/\s*↔\s*|\s*\/\s*/).some(name => name.length > 1 && q.includes(name))
  )).slice(0, 3).map(item => ({ ...item, content: item.content_cn }))
  return { matched, explanation: matched.length ? { summary: matched[0].content, caution: '先用小份试调，根据酸甜平衡调整。' } : null }
}

export function deconstruct(recipe) {
  const citrus = recipe.ingredients.some(item => /lemon juice|lime juice/.test(item.name))
  const balance = citrus ? '柑橘酸度与甜味材料平衡' : '以基酒、苦甜材料与稀释取得平衡'
  return { deconstruction: {
    base_spirit: recipe.alcoholic ? recipe.ingredients[0].name_zh : '无酒精',
    balance, signature: recipe.ingredients.at(-1).name_zh,
    skeleton: recipe.ingredients.map(item => `${item.name_zh} ${item.amount}`).join(' · '),
    ideas: [{ name: '小份试调', change: citrus ? '先保留基酒和酸源，减去少量甜味材料' : '保持原配方比例，调整搅拌时间', why: citrus ? '可比较糖量变化对酸度的影响。' : '可比较冰块稀释对酒感的影响。' }],
  } }
}

const zeroReplacements = {
  gin: ['无酒精金酒', '保留草本香气'],
  campari: ['无酒精苦味开胃饮料', '保留苦甜层次'],
  'sweet vermouth': ['红葡萄汁', '提供果香和甜度'],
  'white rum': ['冷泡红茶', '补充香气与酒体'],
  tequila: ['无酒精龙舌兰风味基底', '保留草本风格'],
  'triple sec': ['橙汁', '保留柑橘方向'],
  bourbon: ['冷泡红茶', '带来茶香和涩感'],
  vodka: ['苏打水', '保留清爽口感'],
  'ginger beer': ['无酒精姜汁汽水', '保留姜香与气泡'],
}

export function mocktail(recipe) {
  const replaced = []
  const ingredients = recipe.ingredients.map(item => {
    const swap = recipe.alcoholic && zeroReplacements[item.name]
    if (!swap) return { name: item.name_zh, amount: item.amount }
    const [name, why] = swap
    replaced.push({ from: item.name_zh, to: name, why })
    return { name, amount: item.amount }
  })
  return { ingredients, replaced, mocktail_name: recipe.alcoholic ? `零酒版${recipe.name_cn}` : recipe.name_cn, note: '如需严格无酒精，请选择标明 0.0% 的替代材料。' }
}

const theme = (key, name, emoji, vibe, tips, ids) => ({
  key, name, emoji, vibe, tips,
  recommendations: ids.map(id => {
    const recipe = recipes.find(item => item.id === id)
    return { name: recipe.name, why: recipe.ingredients.slice(0, 3).map(item => item.name_zh).join(' · '), spirit: recipe.alcoholic ? recipe.ingredients[0].name_zh : '无酒精', glass: recipe.glass }
  }),
})

export const themes = [
  theme('summer', '夏日清爽', '☀', '薄荷、青柠与气泡', '预先冷藏气泡水，最后加入以保留气泡。', ['mojito', 'daiquiri', 'mint-lime-soda']),
  theme('classic', '经典吧台', '◆', '从酸甜结构到苦甜层次', '对比不同调法的稀释与口感。', ['negroni', 'margarita', 'whiskey-sour']),
  theme('zero', '零酒聚会', '✿', '柑橘与香草也能做主角', '提前准备足量冰块与新鲜柑橘。', ['mint-lime-soda', 'orange-ginger-fizz']),
]

export function banquet({ names, headcount, mocktail: zero }) {
  const guests = Number(headcount)
  const cocktails = []
  const unknown = []
  for (const name of [...new Set(names)]) {
    const recipe = recipes.find(item => item.name.toLowerCase() === name.toLowerCase() || item.name_cn === name)
    if (!recipe) { unknown.push(name); continue }
    const ingredients = zero ? mocktail(recipe).ingredients : recipe.ingredients.map(item => ({ name: item.name_zh, amount: item.amount }))
    cocktails.push({ name: zero ? mocktail(recipe).mocktail_name : recipe.name_cn,
      ingredients: ingredients.map(item => {
        const volume = item.amount.match(/^([\d.]+)\s*ml$/i)
        return volume
          ? { name: item.name, for_n: Number(volume[1]) * guests }
          : { name: item.name, amount_text: `每杯 ${item.amount}` }
      }),
    })
  }
  return { cocktails, unknown }
}
