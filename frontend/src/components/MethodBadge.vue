<template>
  <div class="method-badge-row" aria-label="analysis method metadata">
    <span v-if="method" class="method-badge">Method: {{ method }}</span>
    <span v-if="normalization" class="method-badge">Norm: {{ normalization }}</span>
    <span v-if="missingPolicy" class="method-badge">Missing: {{ missingPolicy }}</span>
    <span v-if="nText" class="method-badge">{{ nText }}</span>
    <span v-if="thresholdsText" class="method-badge">Threshold: {{ thresholdsText }}</span>
    <span v-if="exploratory" class="method-badge warning">Exploratory</span>
    <span v-if="note" class="method-note">{{ note }}</span>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  method: { type: String, default: '' },
  normalization: { type: String, default: '' },
  missingPolicy: { type: String, default: '' },
  n: { type: [Number, String], default: '' },
  nFeatures: { type: [Number, String], default: '' },
  thresholds: { type: [String, Object], default: '' },
  exploratory: { type: Boolean, default: false },
  note: { type: String, default: '' },
})

const nText = computed(() => {
  const parts = []
  if (props.n !== '' && props.n !== null && props.n !== undefined) parts.push(`n=${props.n}`)
  if (props.nFeatures !== '' && props.nFeatures !== null && props.nFeatures !== undefined) parts.push(`features=${props.nFeatures}`)
  return parts.join(' / ')
})

const thresholdsText = computed(() => {
  if (!props.thresholds) return ''
  if (typeof props.thresholds === 'string') return props.thresholds
  return Object.entries(props.thresholds)
    .map(([key, value]) => `${key}=${value}`)
    .join(', ')
})
</script>
