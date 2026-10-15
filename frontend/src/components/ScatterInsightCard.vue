<template>
  <div class="scatter-insight">
    <div class="eyebrow">{{ eyebrow }}</div>
    <h4>{{ title }}</h4>
    <div class="metric-band compact">
      <span class="badge">n={{ stats.n ?? 0 }}</span>
      <span class="badge">Pearson {{ formatNumber(stats.pearson_r) }}</span>
      <span class="badge">Spearman {{ formatNumber(stats.spearman_r) }}</span>
      <span class="badge">{{ meta.recommended_view || meta.semantic_type || 'scatter' }}</span>
    </div>
    <p class="muted">{{ interpretation }}</p>
    <p class="annotation">{{ boundary }}</p>
  </div>
</template>

<script setup>
const props = defineProps({
  meta: { type: Object, default: () => ({}) },
  title: { type: String, default: 'Scatter interpretation' },
  eyebrow: { type: String, default: 'Scatter insight' },
})

const stats = props.meta?.stats || {}
const interpretation = props.meta?.explanation || 'Read trend, density, stratification and candidate outliers; do not infer causality from scatter alone.'
const boundary = props.meta?.evidence_level || 'descriptive / hypothesis-generating'

function formatNumber(value) {
  const num = Number(value)
  if (!Number.isFinite(num)) return '-'
  return num.toFixed(3)
}
</script>

<style scoped>
.scatter-insight {
  border: 1px solid rgba(42, 89, 140, 0.12);
  border-radius: 8px;
  padding: 12px;
  background: rgba(255, 255, 255, 0.78);
}

.scatter-insight h4 {
  margin: 2px 0 8px;
  font-size: 14px;
}

.metric-band.compact {
  gap: 6px;
  margin-bottom: 8px;
}
</style>
