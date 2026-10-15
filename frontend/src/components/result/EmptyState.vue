<template>
  <div class="result-empty-state" role="status">
    <div>
      <div v-if="reason" class="label">Unavailable</div>
      <h4>{{ title }}</h4>
      <p class="muted">{{ messageText }}</p>
      <p v-if="suggestion" class="muted">{{ suggestion }}</p>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  title: { type: String, default: 'No result available' },
  reason: { type: String, default: '' },
  suggestion: { type: String, default: '' },
})

const messageText = computed(() => props.reason || 'The current payload has no renderable rows for this chart or table.')
</script>
