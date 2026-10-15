<template>
  <div class="evidence-badges" v-if="evidence.length">
    <span
      v-for="item in evidence.slice(0, limit)"
      :key="`${item.module_id}-${item.source_path}`"
      class="badge"
      :class="classFor(item.severity_level)"
    >
      {{ item.module_id }} · {{ item.severity_level }}
    </span>
  </div>
  <p v-else class="muted">No G/T/P/X candidate evidence is currently linked to this entity.</p>
</template>

<script setup>
defineProps({
  evidence: { type: Array, default: () => [] },
  limit: { type: Number, default: 12 },
})

function classFor(severity = '') {
  const level = String(severity).toLowerCase()
  if (level === 'extreme' || level === 'high') return 'hot-badge'
  if (level === 'medium') return 'cool-badge'
  return 'muted-badge'
}
</script>

<style scoped>
.evidence-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
</style>
