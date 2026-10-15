<template>
  <div class="stack-lg">
    <section class="panel">
      <div class="section-header">
        <div>
          <div class="eyebrow">Browser</div>
          <h3>Real feature table preview</h3>
          <p class="muted">Preview uses server-side paging and only returns the selected columns.</p>
        </div>
        <button class="btn" @click="loadPreview" :disabled="loading">Load preview</button>
      </div>
      <div class="toolbar-grid wide">
        <input class="input" v-model="speciesId" placeholder="species_id, for example saccharomyces_cerevisiae" />
        <select class="input" v-model="omics" @change="loadCatalog"><option value="genome">Genome</option><option value="transcriptome">Transcriptome</option><option value="proteome">Proteome</option></select>
        <select class="input" v-model="scope" @change="loadCatalog"><option value="core">Core</option><option value="full">Full</option></select>
        <input class="input" v-model="fieldText" placeholder="Comma-separated fields" />
        <input class="input" v-model="query" placeholder="Optional row search" />
        <input class="input" v-model.number="pageSize" type="number" min="1" max="200" />
      </div>
      <details class="feature-browser-species-picker">
        <summary>
          <span>Search all registered species</span>
          <small>{{ speciesId || 'No species selected' }}</small>
        </summary>
        <SpeciesSelector v-model="speciesId" />
      </details>
      <div v-if="error" class="annotation">{{ error }}</div>
    </section>

    <section class="panel">
      <div class="section-header compact">
        <div>
          <div class="eyebrow">Field selector</div>
          <h3>{{ catalogRows.length }} fields available</h3>
          <p class="muted">Click a field to add or remove it from the preview columns.</p>
        </div>
        <span class="badge">{{ selectedFields.length }} selected</span>
      </div>
      <div class="feature-chip-strip">
        <button
          v-for="row in catalogRows"
          :key="row.field"
          class="btn subtle feature-field-chip"
          :class="{ active: selectedFields.includes(row.field) }"
          :title="row.description || row.semantic_type || row.field"
          @click="toggleField(row.field)"
        >
          {{ row.field }}
        </button>
      </div>
    </section>

    <section v-if="preview.rows" class="panel">
      <div class="section-header compact">
        <div>
          <div class="eyebrow">Preview</div>
          <h3>{{ preview.displayed_rows }} / {{ preview.total_rows }} rows</h3>
        </div>
        <div class="row">
          <button class="btn subtle" :disabled="page <= 1" @click="page--; loadPreview()">Previous</button>
          <span class="badge">Page {{ page }}</span>
          <button class="btn subtle" @click="page++; loadPreview()">Next</button>
        </div>
      </div>
      <div class="table-wrap">
        <table class="table compact-table">
          <thead><tr><th v-for="col in preview.columns" :key="col" @click="profileField(col)">{{ col }}</th></tr></thead>
          <tbody>
            <tr v-for="(row, idx) in preview.rows" :key="idx">
              <td v-for="col in preview.columns" :key="col">{{ row[col] }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="(preview.warnings || []).length" class="annotation">{{ preview.warnings.join(' ') }}</div>
    </section>

    <section v-if="profile.field" class="panel">
      <div class="section-header compact">
        <div>
          <div class="eyebrow">Field profile</div>
          <h3>{{ profile.field }}</h3>
          <p class="muted">n={{ profile.n_rows }} missing={{ profile.missing_n }} numeric={{ profile.numeric_n }}</p>
        </div>
      </div>
      <div class="grid grid-4">
        <div v-for="key in ['min','p25','median','p75','max','mean','std','zero_rate']" :key="key" class="mini-card">
          <div class="label">{{ key }}</div>
          <div>{{ formatNumber(profile.summary?.[key]) }}</div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { getFeatureHubCatalog, getFeatureHubFieldProfile, getFeatureHubPreview } from '../api/stoichdb'
import SpeciesSelector from '../components/featurehub/SpeciesSelector.vue'

const speciesId = ref('saccharomyces_cerevisiae')
const omics = ref('genome')
const scope = ref('core')
const fieldText = ref('species_id,gene_id,locus_gc_percent,exon_gc_percent')
const query = ref('')
const page = ref(1)
const pageSize = ref(50)
const catalogRows = ref([])
const preview = ref({})
const profile = ref({})
const loading = ref(false)
const error = ref('')
const selectedFields = computed(() => parseFields(fieldText.value))

async function loadCatalog() {
  const data = await getFeatureHubCatalog({ omics: omics.value, scope: scope.value })
  catalogRows.value = data.items || []
  const preferred = catalogRows.value
    .filter(row => ['identifier', 'continuous', 'count', 'composition', 'binary'].includes(row.semantic_type))
    .slice(0, 6)
    .map(row => row.field)
  if (preferred.length) fieldText.value = preferred.join(',')
}

async function loadPreview() {
  loading.value = true
  error.value = ''
  try {
    preview.value = await getFeatureHubPreview({ species_id: speciesId.value, omics: omics.value, scope: scope.value, fields: fieldText.value, query: query.value, page: page.value, page_size: pageSize.value })
  } catch (err) {
    error.value = err?.response?.data?.error || err.message || 'Failed to load preview.'
  } finally {
    loading.value = false
  }
}

function toggleField(field) {
  const fields = parseFields(fieldText.value)
  const next = fields.includes(field)
    ? fields.filter(item => item !== field)
    : [...fields, field]
  fieldText.value = next.join(',')
}

function parseFields(value) {
  return String(value || '').split(',').map(item => item.trim()).filter(Boolean)
}

async function profileField(field) {
  profile.value = await getFeatureHubFieldProfile({ species_id: speciesId.value, omics: omics.value, scope: scope.value, field })
}

function formatNumber(value) {
  const n = Number(value)
  return Number.isFinite(n) ? n.toPrecision(5) : '-'
}

onMounted(async () => {
  await loadCatalog()
})
</script>
