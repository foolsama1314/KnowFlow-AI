<script setup lang="ts">
defineProps<{
  label: string
  value: string | number
  hint?: string
  accent?: boolean
}>()
</script>

<template>
  <div class="stat" :class="{ accent }">
    <span class="label">{{ label }}</span>
    <strong class="value">{{ value }}</strong>
    <span v-if="hint" class="hint">{{ hint }}</span>
  </div>
</template>

<style scoped>
.stat {
  background: var(--kf-panel);
  border: 1px solid var(--kf-line);
  border-radius: 14px;
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.stat.accent {
  background: linear-gradient(140deg, #1f7a6b, #14574f);
  border-color: transparent;
  color: #eafff9;
}

.stat.accent .label,
.stat.accent .hint {
  color: rgba(234, 255, 249, 0.72);
}

.label {
  font-size: 13px;
  color: var(--kf-muted);
  letter-spacing: 0.02em;
}

.value {
  font-size: 30px;
  font-weight: 650;
  line-height: 1.15;
  font-variant-numeric: tabular-nums;
}

.hint {
  font-size: 12px;
  color: #93a5ac;
}
</style>
