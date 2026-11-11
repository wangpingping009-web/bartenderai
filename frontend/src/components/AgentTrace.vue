<template>
  <div class="trace">
    <div class="head">
      <el-icon class="spin" :size="14"><Loading /></el-icon>
      多 Agent 协同中...
    </div>
    <el-timeline class="tl">
      <el-timeline-item
        v-for="(t, i) in trace" :key="i"
        :type="t.kind === 'agent' ? 'primary' : 'info'"
        :hollow="t.kind === 'status'"
        size="small"
      >
        <span class="evt" :class="t.kind">
          <b v-if="t.agent" class="agent-tag">{{ t.agent }}</b>
          {{ t.message }}
        </span>
      </el-timeline-item>
    </el-timeline>
  </div>
</template>

<script setup>
import { Loading } from '@element-plus/icons-vue'
defineProps({ trace: { type: Array, default: () => [] } })
</script>

<style scoped>
.trace { margin: 14px 0; background: #fdfcf9; border: 1px dashed #ddd; border-radius: 10px; padding: 12px 16px; }
.head { font-size: 13px; color: #5b8c5a; font-weight: 600; margin-bottom: 8px; display: flex; align-items: center; gap: 6px; }
.spin { animation: rotate 1s linear infinite; }
@keyframes rotate { to { transform: rotate(360deg); } }
.tl { padding-left: 4px; }
.evt { font-size: 13px; color: #555; }
.evt.status { color: #999; font-size: 12px; }
.agent-tag {
  display: inline-block; background: #e8f0e6; color: #5b8c5a;
  border-radius: 4px; padding: 0 6px; margin-right: 6px; font-size: 12px;
}
</style>
