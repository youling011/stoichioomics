<template>
  <div class="feature-strip">
    <div class="feature-strip-head">
      <strong>{{ label }}</strong>
      <span class="badge" :class="tailClass">{{ feature.tail_label || 'non-numeric' }}</span>
    </div>
    <div class="feature-strip-values">
      <span>value {{ format(feature.value) }}</span>
      <span>median {{ format(feature.median) }}</span>
      <span>percentile {{ format(feature.percentile) }}</span>
      <span>robust z {{ format(feature.robust_z) }}</span>
      <span>n {{ feature.valid_n || 0 }}</span>
    </div>
    <div class="percentile-track" v-if="Number.isFinite(Number(feature.percentile))">
      <div class="percentile-band"></div>
      <div class="percentile-marker" :style="{ left: `${Math.max(0, Math.min(100, Number(feature.percentile)))}%` }"></div>
    </div>
    <p class="annotation">{{ feature.description }} Missing rate: {{ formatPercent(feature.missing_rate) }}.</p>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  feature: { type: Object, required: true },
})

const label = computed(() => String(props.feature.feature || props.feature.source_field || '').replaceAll('_', ' '))
const tailClass = computed(() => {
  const label = String(props.feature.tail_label || '').toLowerCase()
  if (label.includes('99') || label.includes('95')) return 'hot-badge'
  if (label.includes('01') || label.includes('05')) return 'cool-badge'
  return 'muted-badge'
})

function format(value) {
  const num = Number(value)
  if (!Number.isFinite(num)) return value ?? '-'
  if (Math.abs(num) >= 1000) return num.toLocaleString(undefined, { maximumFractionDigits: 1 })
  return num.toFixed(2).replace(/\.00$/, '')
}

function formatPercent(value) {
  const num = Number(value)
  if (!Number.isFinite(num)) return '-'
  return `${(num * 100).toFixed(1)}%`
}
</script>

<style scoped>
.feature-strip {
  border: 1px solid rgba(42, 89, 140, 0.14);
  border-radius: 8px;
  padding: 12px;
  background: #fff;
}

.feature-strip-head,
.feature-strip-values {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
  align-items: center;
}

.feature-strip-values {
  margin-top: 8px;
  color: #4f6b86;
  font-size: 13px;
}

.percentile-track {
  position: relative;
  height: 10px;
  margin-top: 10px;
  border-radius: 99px;
  background: linear-gradient(90deg, #93c5fd 0 5%, #dbeafe 5% 95%, #fca5a5 95% 100%);
}

.percentile-marker {
  position: absolute;
  top: -4px;
  width: 3px;
  height: 18px;
  border-radius: 2px;
  background: #123c69;
  transform: translateX(-1px);
}
</style>
