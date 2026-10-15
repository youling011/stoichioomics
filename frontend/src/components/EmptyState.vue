<template>
  <div class="empty-state">
    <div>
      <div v-if="eyebrow" class="eyebrow">{{ eyebrow }}</div>
      <h4>{{ title }}</h4>
      <p class="muted">{{ message }}</p>
    </div>
  </div>
</template>

<script setup>
defineProps({
  eyebrow: { type: String, default: 'No data' },
  title: { type: String, default: 'No result available' },
  message: { type: String, default: 'This block has no rows for the current release or selection.' },
})
</script>
