<template>
  <article class="result-block" :class="{ 'is-loading': loading, 'has-error': Boolean(error) }">
    <div class="result-block-header">
      <div>
        <div v-if="question" class="result-question">{{ question }}</div>
        <h3>{{ title }}</h3>
        <p v-if="finding" class="result-finding">{{ finding }}</p>
      </div>
      <ChartDownloadLinks :downloads="downloads" />
    </div>

    <EmptyState v-if="loading" title="Loading result" reason="This result block is waiting for its payload." />
    <EmptyState v-else-if="error" title="Result unavailable" :reason="error" />
    <EmptyState v-else-if="emptyReason" title="No result to display" :reason="emptyReason" :suggestion="emptySuggestion" />
    <div v-else class="result-block-body">
      <slot />
    </div>

    <div class="result-block-footer">
      <MethodNote
        :text="method"
        :normalization="normalization"
        :missing-policy="missingPolicy"
        :n="n"
        :n-features="nFeatures"
      />
      <CaveatBox :text="caveat" />
    </div>
  </article>
</template>

<script setup>
import ChartDownloadLinks from './ChartDownloadLinks.vue'
import EmptyState from './EmptyState.vue'
import MethodNote from './MethodNote.vue'
import CaveatBox from './CaveatBox.vue'

defineProps({
  title: { type: String, required: true },
  question: { type: String, default: '' },
  finding: { type: String, default: '' },
  method: { type: String, default: '' },
  normalization: { type: String, default: '' },
  missingPolicy: { type: String, default: '' },
  caveat: { type: [String, Array], default: '' },
  downloads: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
  emptyReason: { type: String, default: '' },
  emptySuggestion: { type: String, default: '' },
  n: { type: [Number, String], default: '' },
  nFeatures: { type: [Number, String], default: '' },
})
</script>
