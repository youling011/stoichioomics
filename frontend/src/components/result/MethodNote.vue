<template>
  <div v-if="hasContent" class="result-note method-note">
    <strong>Method</strong>
    <p v-if="text">{{ text }}</p>
    <div class="badge-row" v-if="normalization || missingPolicy || nText">
      <span v-if="normalization" class="badge">Norm: {{ normalization }}</span>
      <span v-if="missingPolicy" class="badge">Missing: {{ missingPolicy }}</span>
      <span v-if="nText" class="badge">{{ nText }}</span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  text: { type: String, default: '' },
  normalization: { type: String, default: '' },
  missingPolicy: { type: String, default: '' },
  n: { type: [Number, String], default: '' },
  nFeatures: { type: [Number, String], default: '' },
})

const nText = computed(() => {
  const parts = []
  if (props.n !== '' && props.n !== null && props.n !== undefined) parts.push(`n=${props.n}`)
  if (props.nFeatures !== '' && props.nFeatures !== null && props.nFeatures !== undefined) parts.push(`features=${props.nFeatures}`)
  return parts.join(' / ')
})

const hasContent = computed(() => props.text || props.normalization || props.missingPolicy || nText.value)
</script>
