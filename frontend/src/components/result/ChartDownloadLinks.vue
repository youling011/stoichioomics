<template>
  <div v-if="links.length" class="result-downloads" aria-label="result downloads">
    <a
      v-for="link in links"
      :key="link.label || link.href || link.filename"
      class="btn subtle"
      :href="link.href || '#'"
      :download="link.filename || null"
      @click="handleClick($event, link)"
    >
      {{ link.label || 'Download' }}
    </a>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  downloads: { type: Array, default: () => [] },
})

const links = computed(() => props.downloads || [])

function saveJson(filename, payload) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

function handleClick(event, link) {
  if (!link.payload) return
  event.preventDefault()
  saveJson(link.filename || 'result_payload.json', link.payload)
}
</script>
