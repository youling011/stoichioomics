<template>
  <span class="badge" :class="badgeClass">{{ text }}</span>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  role: { type: String, default: '' },
  scope: { type: String, default: 'core' },
  text: { type: String, default: '' },
})

const badgeClass = computed(() => {
  if (props.scope === 'full') return 'warning-badge'
  if (props.role === 'eligible') return 'success-badge'
  if (props.role === 'conditional') return 'cool-badge'
  return ''
})
</script>

