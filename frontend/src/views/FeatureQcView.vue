<template>
  <div class="stack-lg">
    <section class="panel">
      <div class="section-header">
        <div>
          <div class="eyebrow">QC</div>
          <h3>Core feature quality audit</h3>
          <p class="muted">Audits missingness, non-finite values, constant fields, exact duplicates, high correlation, composition constraints, and applicability.</p>
        </div>
        <button class="btn" @click="run" :disabled="loading">Run QC</button>
      </div>
      <div class="toolbar-grid wide">
        <input class="input" v-model="speciesId" placeholder="species_id" />
        <select class="input" v-model="omics" @change="loadCatalog"><option value="genome">Genome</option><option value="transcriptome">Transcriptome</option><option value="proteome">Proteome</option></select>
        <input class="input" v-model="fieldText" placeholder="Comma-separated Core fields" />
      </div>
      <div v-if="error" class="annotation">{{ error }}</div>
    </section>

    <section class="panel">
      <div class="section-header compact">
        <div>
          <div class="eyebrow">Core fields</div>
          <h3>Select fields for QC</h3>
        </div>
      </div>
      <div class="metric-band compact-band">
        <button v-for="row in catalogRows.slice(0, 80)" :key="row.field" class="btn subtle" @click="add(row.field)">{{ row.field }}</button>
      </div>
    </section>

    <QcSummary v-if="report.n_rows" :report="report" />

    <section v-if="report.missingness" class="panel">
      <div class="table-wrap">
        <table class="table compact-table">
          <thead><tr><th>Field</th><th>Missing</th><th>Missing rate</th><th>Non-finite</th></tr></thead>
          <tbody>
            <tr v-for="(row, field) in report.missingness" :key="field">
              <td>{{ field }}</td>
              <td>{{ row.missing_n }}</td>
              <td>{{ row.missing_rate }}</td>
              <td>{{ row.non_finite_n }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { getFeatureHubCatalog, runFeatureHubQc } from '../api/stoichdb'
import QcSummary from '../components/featurehub/QcSummary.vue'

const speciesId = ref('saccharomyces_cerevisiae')
const omics = ref('genome')
const fieldText = ref('locus_gc_percent,exon_gc_percent,exon_length_bp')
const catalogRows = ref([])
const report = ref({})
const loading = ref(false)
const error = ref('')

async function loadCatalog() {
  const data = await getFeatureHubCatalog({ omics: omics.value, scope: 'core', ml_role: 'eligible' })
  catalogRows.value = data.items || []
  fieldText.value = catalogRows.value.slice(0, 6).map(row => row.field).join(',')
}

function add(field) {
  const fields = fieldText.value.split(',').map(item => item.trim()).filter(Boolean)
  if (!fields.includes(field)) fields.push(field)
  fieldText.value = fields.join(',')
}

async function run() {
  loading.value = true
  error.value = ''
  try {
    report.value = await runFeatureHubQc({ species_id: speciesId.value, omics: omics.value, fields: fieldText.value.split(',') })
  } catch (err) {
    error.value = err?.response?.data?.error || err.message || 'QC failed.'
  } finally {
    loading.value = false
  }
}

onMounted(loadCatalog)
</script>
