<template>
  <div class="stack-lg">
    <section class="panel">
      <div class="section-header">
        <div>
          <div class="eyebrow">Exports</div>
          <h3>Feature Hub export center</h3>
          <p class="muted">Open a generated export by ID and download the ZIP package after completion.</p>
        </div>
        <button class="btn" @click="load">Load export</button>
      </div>
      <div class="toolbar-grid">
        <input class="input" v-model="exportId" placeholder="fh_YYYYMMDD_HHMMSS_xxxxxxxx" />
      </div>
      <div v-if="error" class="annotation">{{ error }}</div>
    </section>
    <ExportManifest :export-state="exportState" />
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { getFeatureHubExport } from '../api/stoichdb'
import ExportManifest from '../components/featurehub/ExportManifest.vue'

const exportId = ref('')
const exportState = ref({})
const error = ref('')

async function load() {
  error.value = ''
  try {
    exportState.value = await getFeatureHubExport(exportId.value)
  } catch (err) {
    error.value = err?.response?.data?.error || err.message || 'Failed to load export.'
  }
}
</script>

