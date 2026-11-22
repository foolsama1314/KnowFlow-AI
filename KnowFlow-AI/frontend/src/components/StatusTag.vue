<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ status: string }>()

const map: Record<string, { text: string; type: 'success' | 'info' | 'warning' | 'danger' }> = {
  uploaded: { text: '已上传', type: 'info' },
  processing: { text: '处理中', type: 'warning' },
  completed: { text: '可检索', type: 'success' },
  failed: { text: '处理失败', type: 'danger' },
  pending: { text: '等待执行', type: 'info' },
  running: { text: '执行中', type: 'warning' },
}

const current = computed(() => map[props.status] ?? { text: props.status, type: 'info' as const })
</script>

<template>
  <el-tag :type="current.type" effect="light" round size="small">{{ current.text }}</el-tag>
</template>
