<template>
  <div class="msg" :class="msg.role">
    <div class="bubble" :class="{ error: msg.error }">
      <div class="content">{{ msg.content }}</div>
      <RecipeCard v-if="msg.recipe" :recipe="msg.recipe" :user-id="userId" />
      <div v-if="msg.references && msg.references.length" class="refs">
        <el-tag v-for="r in msg.references.slice(0, 5)" :key="r" size="small" type="info"
                effect="plain">📄 {{ r }}</el-tag>
      </div>
    </div>
  </div>
</template>

<script setup>
import RecipeCard from './RecipeCard.vue'
defineProps({
  msg: { type: Object, required: true },
  userId: { type: String, default: 'guest' },
})
</script>

<style scoped>
.msg { display: flex; margin: 12px 0; }
.msg.user { justify-content: flex-end; }
.bubble {
  max-width: 72%; padding: 10px 14px; border-radius: 12px;
  line-height: 1.7; font-size: 14px; white-space: pre-wrap; word-break: break-word;
}
.msg.user .bubble { background: #5b8c5a; color: #fff; border-bottom-right-radius: 4px; }
.msg.assistant .bubble { background: #fff; border: 1px solid #eee; border-bottom-left-radius: 4px; }
.bubble.error { background: #fdf0f0; border-color: #f5c2c2; color: #b54949; }
.refs { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 4px; }
</style>
