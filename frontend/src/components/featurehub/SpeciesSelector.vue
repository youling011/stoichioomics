<template>
  <div class="stack-sm">
    <div class="toolbar-grid">
      <input class="input" v-model="query" placeholder="Search scientific name, species_id, or TaxID" @keyup.enter="load" />
      <button class="btn" @click="load" :disabled="loading">Search species</button>
    </div>
    <div v-if="error" class="annotation">{{ error }}</div>
    <div class="feature-species-list">
      <label v-for="item in rows" :key="item.species_id" class="checkbox-inline feature-species-row">
        <input type="radio" :checked="modelValue === item.species_id" @change="$emit('update:modelValue', item.species_id)" />
        <span>
          <strong>{{ item.display_name }}</strong>
          <small>{{ item.species_id }} · {{ availability(item) }}</small>
        </span>
      </label>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { getFeatureHubSpecies } from '../../api/stoichdb'

defineProps({ modelValue: { type: String, default: '' } })
defineEmits(['update:modelValue'])

const query = ref('')
const rows = ref([])
const loading = ref(false)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await getFeatureHubSpecies({ query: query.value, limit: 30 })
    rows.value = data.items || []
  } catch (err) {
    error.value = err?.response?.data?.error || err.message || 'Failed to load species.'
  } finally {
    loading.value = false
  }
}

function availability(item) {
  return Object.entries(item.omics || {}).map(([key, value]) => `${key}: ${value.core_rows || 0}`).join(' · ')
}

onMounted(load)
</script>

