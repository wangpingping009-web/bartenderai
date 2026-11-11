<template>
  <div class="panel">
    <div v-if="favorites.length" class="list">
      <RecipeCard v-for="f in favorites" :key="f.name" :recipe="f.recipe"
                  :user-id="userId" readonly />
    </div>
    <div v-else class="empty">
      还没有收藏。<br />聊天里出现配方卡时，点右上角 ★ 收藏。
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'
import { api } from '../api'
import RecipeCard from './RecipeCard.vue'

const props = defineProps({ userId: { type: String, required: true } })
const favorites = ref([])

async function load() {
  try { favorites.value = await api.favorites.list(props.userId) }
  catch (_) { favorites.value = [] }
}

watch(() => props.userId, load)
onMounted(load)
</script>

<style scoped>
.panel { padding: 4px; }
.list { display: flex; flex-direction: column; gap: 12px; }
.empty { font-size: 12px; color: #bbb; text-align: center; padding: 20px 0; line-height: 1.8; }
</style>
