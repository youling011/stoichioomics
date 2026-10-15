<template>
  <div v-if="items.length" class="result-note caveat-box">
    <strong>Caveat</strong>
    <ul class="clean-list compact-list">
      <li v-for="item in items" :key="item">{{ item }}</li>
    </ul>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  text: { type: [String, Array], default: '' },
})

const items = computed(() => {
  if (Array.isArray(props.text)) return props.text.filter(Boolean)
  return String(props.text || '')
    .split(/\n+/)
    .map(item => item.trim())
    .filter(Boolean)
})
</script>
