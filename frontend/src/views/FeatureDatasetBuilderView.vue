<template>
  <div class="stack-lg">
    <section class="panel">
      <div class="section-header">
        <div>
          <div class="eyebrow">Builder</div>
          <h3>Core ML dataset builder</h3>
          <p class="muted">Scope is fixed to Core. Full fields are unavailable for ML Builder by design.</p>
        </div>
        <button class="btn" @click="createExport" :disabled="loading || !selected.length">Create ML package</button>
      </div>
      <div class="grid grid-2">
        <SpeciesSelector v-model="speciesId" />
        <div class="stack-sm">
          <div class="toolbar-grid">
            <select class="input" v-model="omics" @change="loadCatalog"><option value="genome">Genome</option><option value="transcriptome">Transcriptome</option><option value="proteome">Proteome</option></select>
            <button class="btn subtle" @click="selectRecommended">Select recommended Core</button>
            <button class="btn subtle" @click="runQc">Run QC</button>
          </div>
          <div class="annotation">Selected {{ selected.length }} Core fields. Species ID remains metadata and is not directly used as X.</div>
          <div v-if="error" class="annotation">{{ error }}</div>
        </div>
      </div>
    </section>

    <section class="panel">
      <div class="section-header compact">
        <div>
          <div class="eyebrow">Field selection</div>
          <h3>Core registry fields</h3>
        </div>
      </div>
      <FeatureTree :fields="fields" v-model:selected="selected" />
    </section>

    <section v-if="qcReport.n_rows" class="stack-lg">
      <QcSummary :report="qcReport" />
    </section>

    <ExportManifest v-if="exportState.export_id" :export-state="exportState" />
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { createFeatureHubExport, getFeatureHubCatalog, getFeatureHubExport, runFeatureHubQc } from '../api/stoichdb'
import ExportManifest from '../components/featurehub/ExportManifest.vue'
import FeatureTree from '../components/featurehub/FeatureTree.vue'
import QcSummary from '../components/featurehub/QcSummary.vue'
import SpeciesSelector from '../components/featurehub/SpeciesSelector.vue'

const speciesId = ref('saccharomyces_cerevisiae')
const omics = ref('genome')
const fields = ref([])
const selected = ref([])
const qcReport = ref({})
const exportState = ref({})
const loading = ref(false)
const error = ref('')

async function loadCatalog() {
  const data = await getFeatureHubCatalog({ omics: omics.value, scope: 'core' })
  fields.value = data.items || []
  selected.value = fields.value.filter(row => row.ml_default).slice(0, 24).map(row => row.field)
}

function selectRecommended() {
  selected.value = fields.value.filter(row => row.ml_default).map(row => row.field)
}

async function runQc() {
  error.value = ''
  try {
    qcReport.value = await runFeatureHubQc({ species_id: speciesId.value, omics: omics.value, fields: selected.value })
  } catch (err) {
    error.value = err?.response?.data?.error || err.message || 'QC failed.'
  }
}

async function createExport() {
  loading.value = true
  error.value = ''
  try {
    exportState.value = await createFeatureHubExport({ species_id: speciesId.value, omics: omics.value, scope: 'core', mode: 'ml_package', fields: selected.value })
    pollExport()
  } catch (err) {
    error.value = err?.response?.data?.error || err.message || 'Export failed.'
  } finally {
    loading.value = false
  }
}

async function pollExport() {
  if (!exportState.value.export_id || ['completed', 'failed'].includes(exportState.value.status)) return
  setTimeout(async () => {
    exportState.value = await getFeatureHubExport(exportState.value.export_id)
    pollExport()
  }, 1500)
}

onMounted(loadCatalog)
</script>

