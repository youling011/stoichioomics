<template>
  <div class="stack-lg">
    <section class="panel">
      <div class="section-header">
        <div>
          <div class="eyebrow">Catalog</div>
          <h3>Complete Core and Full feature registry</h3>
        </div>
        <button class="btn" @click="load" :disabled="loading">Apply filters</button>
      </div>
      <div class="toolbar-grid wide">
        <select v-model="filters.omics" class="input"><option value="">All omics</option><option value="genome">Genome</option><option value="transcriptome">Transcriptome</option><option value="proteome">Proteome</option></select>
        <select v-model="filters.scope" class="input"><option value="">Core and Full</option><option value="core">Core</option><option value="full">Full</option></select>
        <select v-model="filters.ml_role" class="input"><option value="">All ML roles</option><option value="eligible">Eligible</option><option value="conditional">Conditional</option><option value="exclude">Exclude</option></select>
        <select v-model="filters.family" class="input"><option value="">All families</option><option v-for="item in facets.families || []" :key="item" :value="item">{{ format(item) }}</option></select>
        <input v-model="filters.search" class="input" placeholder="Search field, label, or description" @keyup.enter="load" />
      </div>
      <div v-if="error" class="annotation">{{ error }}</div>
    </section>

    <section class="panel">
      <div class="section-header compact">
        <div>
          <div class="eyebrow">Fields</div>
          <h3>{{ rows.length }} registered fields</h3>
        </div>
      </div>
      <div class="table-wrap">
        <table class="table compact-table">
          <thead>
            <tr><th>Field</th><th>Omics</th><th>Scope</th><th>Family</th><th>Type</th><th>ML</th><th>Unit</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="`${row.omics}-${row.scope}-${row.field}`" @click="selected = row">
              <td><strong>{{ row.field }}</strong><div class="muted">{{ row.label }}</div></td>
              <td>{{ row.omics }}</td>
              <td><FieldBadge :scope="row.scope" :role="row.ml_role" :text="row.scope" /></td>
              <td>{{ format(row.family) }}</td>
              <td>{{ row.semantic_type }}</td>
              <td><FieldBadge :scope="row.scope" :role="row.ml_role" :text="row.scope === 'full' ? 'Browse only' : row.ml_role" /></td>
              <td>{{ row.unit || '-' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section v-if="selected" class="panel">
      <div class="section-header compact">
        <div>
          <div class="eyebrow">Field detail</div>
          <h3>{{ selected.field }}</h3>
          <p class="muted">{{ selected.description }}</p>
        </div>
      </div>
      <div class="grid grid-3">
        <div class="mini-card"><div class="label">Applicability</div><div>{{ selected.applicability }}</div></div>
        <div class="mini-card"><div class="label">Composition</div><div>{{ selected.composition_group || 'none' }}</div></div>
        <div class="mini-card"><div class="label">Transform</div><div>{{ selected.transform_hint }}</div></div>
        <div class="mini-card"><div class="label">Scaling</div><div>{{ selected.scaling_hint }}</div></div>
        <div class="mini-card"><div class="label">Zero semantics</div><div>{{ selected.zero_semantics }}</div></div>
        <div class="mini-card"><div class="label">Redundancy</div><div>{{ selected.redundancy_group || 'none' }}</div></div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { getFeatureHubCatalog } from '../api/stoichdb'
import FieldBadge from '../components/featurehub/FieldBadge.vue'

const filters = reactive({ omics: '', scope: '', family: '', ml_role: '', search: '' })
const rows = ref([])
const facets = ref({})
const selected = ref(null)
const loading = ref(false)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await getFeatureHubCatalog(filters)
    rows.value = data.items || []
    facets.value = data.facets || {}
    if (!selected.value && rows.value.length) selected.value = rows.value[0]
  } catch (err) {
    error.value = err?.response?.data?.error || err.message || 'Failed to load catalog.'
  } finally {
    loading.value = false
  }
}

function format(value) {
  return String(value || '').replaceAll('_', ' ')
}

onMounted(load)
</script>

