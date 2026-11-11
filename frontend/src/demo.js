import { ApiError } from './api'
import recipes from './demo-recipes'

const storageKey = 'bartenderai-pages-demo'

function readState() {
  try {
    return JSON.parse(localStorage.getItem(storageKey)) || { favorites: [], feedback: {} }
  } catch {
    return { favorites: [], feedback: {} }
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
      && (query.get('favorites_only') !== 'true' || state.favorites.includes(recipe.name))
  })
  const sort = query.get('sort')
  if (sort === 'name') items.sort((a, b) => a.name.localeCompare(b.name))
  else if (sort === 'abv_asc') items.sort((a, b) => a.abv - b.abv)
  else if (sort === 'abv_desc') items.sort((a, b) => b.abv - a.abv)
  else if (['sweet', 'sour', 'aroma'].includes(sort)) items.sort((a, b) => b.flavor[sort] - a.flavor[sort])
  const page = Number(query.get('page') || 1)
  const page_size = Number(query.get('page_size') || 24)
  return { items: items.slice((page - 1) * page_size, page * page_size), total: items.length, page, page_size }
}

export function demoRequest(path, options) {
  const { pathname, searchParams } = new URL(path, location.origin)
  const method = options.method || 'GET'
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
    return { items: recipes.filter(recipe => state.favorites.includes(recipe.name)) }
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
