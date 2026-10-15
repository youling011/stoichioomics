<template>
  <section class="home-section home-feature-spotlight">
    <div class="home-feature-title-row">
      <div>
        <h2><span>NEW</span> Feature Hub <em>Build ML-ready handcrafted feature matrices</em></h2>
      </div>
      <div class="home-feature-badges">
        <span class="home-badge success">Core for ML</span>
        <span class="home-badge blue">Full for browse/download</span>
        <router-link class="home-secondary-btn slim" to="/feature-hub">Launch Feature Hub <span aria-hidden="true">&gt;</span></router-link>
      </div>
    </div>

    <div class="home-feature-grid">
      <div class="home-feature-left">
        <div class="home-feature-controls">
          <label>
            <span>Species</span>
            <select v-model="selectedSpecies" @change="reloadPreview">
              <option v-for="item in speciesOptions" :key="item.species_id" :value="item.species_id">{{ displayName(item) }}</option>
            </select>
          </label>
          <label>
            <span>Omics Layer</span>
            <select v-model="selectedOmics" @change="reloadPreview">
              <option value="genome">Genome</option>
              <option value="transcriptome">Transcriptome</option>
              <option value="proteome">Proteome</option>
            </select>
          </label>
          <label>
            <span>Field Set</span>
            <select v-model="selectedScope" @change="reloadPreview">
              <option value="core">Core</option>
              <option value="full">Full</option>
            </select>
          </label>
          <label>
            <span>Feature Family</span>
            <select v-model="selectedFamily" @change="reloadPreview">
              <option value="">All Families</option>
              <option v-for="family in families" :key="family" :value="family">{{ family }}</option>
            </select>
          </label>
        </div>

        <div class="home-feature-table-wrap">
          <div class="home-feature-table-title">
            <strong>Feature Preview</strong>
            <span>Showing {{ previewRows.length }} of {{ fieldCount }} {{ selectedScope }} features</span>
          </div>
          <table class="home-feature-table">
            <thead>
              <tr>
                <th>Feature ID</th>
                <th>Feature Name</th>
                <th>Family</th>
                <th>Module</th>
                <th>Data Type</th>
                <th>Missingness</th>
                <th>IQR</th>
                <th>Notes</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in previewRows" :key="row.field">
                <td><router-link :to="`/feature-hub/catalog?search=${encodeURIComponent(row.field)}`">{{ row.field }}</router-link></td>
                <td>{{ row.label }}</td>
                <td>{{ row.family }}</td>
                <td>{{ row.module || row.semantic_type || '-' }}</td>
                <td>{{ row.dtype }}</td>
                <td>{{ formatNullable(row.missingness) }}</td>
                <td>{{ formatNullable(row.iqr) }}</td>
                <td>{{ row.notes ? row.notes : '-' }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="home-feature-links">
          <router-link to="/feature-hub/catalog">View all features <span aria-hidden="true">&gt;</span></router-link>
          <router-link to="/feature-hub/builder">Download sample matrix (CSV) <span aria-hidden="true">&gt;</span></router-link>
        </div>
      </div>

      <aside class="home-feature-qc">
        <h3>QC Summary <span>({{ speciesLabel }} / {{ selectedOmics }} / {{ selectedScope }})</span></h3>
        <dl>
          <div>
            <dt>Missingness (&gt; 20%)</dt>
            <dd>{{ qcValue(qc.missing_gt_20_count) }}</dd>
          </div>
          <div>
            <dt>Constant features</dt>
            <dd>{{ qcValue(qc.constant_count) }}</dd>
          </div>
          <div>
            <dt>High correlation (|r| &gt; 0.95)</dt>
            <dd>{{ qcValue(qc.high_corr_pair_count, 'pairs') }}</dd>
          </div>
          <div>
            <dt>Compositional groups</dt>
            <dd>{{ qcValue(qc.compositional_group_count, 'groups') }}</dd>
          </div>
          <div>
            <dt>Entities ({{ selectedOmics }})</dt>
            <dd>{{ entityCount.toLocaleString() }}</dd>
          </div>
          <div>
            <dt>Features</dt>
            <dd>{{ fieldCount.toLocaleString() }}</dd>
          </div>
        </dl>
        <p>{{ qc.message || 'Open the full QC page to compute field-level modeling checks.' }}</p>
        <router-link to="/feature-hub/qc">View full QC report <span aria-hidden="true">&gt;</span></router-link>
      </aside>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import {
  getFeatureHubCatalog,
  getFeatureHubDataset,
  getFeatureHubFieldProfile,
  getFeatureHubHomePreview,
  getFeatureHubSpecies,
  runFeatureHubQc,
} from '../../api/stoichdb'

const props = defineProps({
  spotlight: { type: Object, default: () => ({}) },
  representativeSpecies: { type: Array, default: () => [] },
})

const speciesOptions = ref([])
const selectedSpecies = ref(props.spotlight?.species?.species_id || '')
const selectedOmics = ref(props.spotlight?.omics || 'proteome')
const selectedScope = ref(props.spotlight?.table_level || 'core')
const selectedFamily = ref('')
const previewRows = ref(props.spotlight?.feature_rows || [])
const fieldCount = ref(props.spotlight?.field_count || 0)
const entityCount = ref(props.spotlight?.entity_count || 0)
const families = ref(props.spotlight?.facets?.families || [])
const qc = ref(props.spotlight?.qc || {})
const profiling = ref(false)
let controller

const speciesLabel = computed(() => displayName(speciesOptions.value.find(item => item.species_id === selectedSpecies.value) || props.spotlight?.species || {}))

function displayName(item) {
  return item?.preferred_display_name || item?.short_name || item?.display_name || item?.species_id || 'Selected species'
}

function formatNullable(value) {
  return value === null || value === undefined || value === '' ? '-' : value
}

function formatRate(value) {
  if (value === null || value === undefined || value === '') return null
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return value
  return `${(numeric * 100).toFixed(numeric > 0 && numeric < 0.01 ? 2 : 1)}%`
}

function formatNumber(value) {
  if (value === null || value === undefined || value === '') return null
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return value
  if (Math.abs(numeric) >= 100) return numeric.toFixed(1)
  if (Math.abs(numeric) >= 1) return numeric.toFixed(3)
  return numeric.toPrecision(3)
}

function qcValue(value, suffix = '') {
  if (profiling.value && (value === null || value === undefined || value === '')) return 'Profiling...'
  if (value === null || value === undefined || value === '') return 'Not profiled yet'
  return suffix ? `${value} ${suffix}` : value
}

function hasProfiledSpotlightData() {
  const sameSpecies = selectedSpecies.value === props.spotlight?.species?.species_id
  const sameOmics = selectedOmics.value === (props.spotlight?.omics || 'proteome')
  const sameScope = selectedScope.value === (props.spotlight?.table_level || 'core')
  const hasRows = previewRows.value.some(row => row.missingness !== null && row.missingness !== undefined && row.missingness !== '')
  const hasQc = qc.value?.profile_status === 'profiled_preview_fields'
  return sameSpecies && sameOmics && sameScope && !selectedFamily.value && (hasRows || hasQc)
}

function isNumericField(row) {
  if (row.ml_role === 'eligible') return true
  const dtype = String(row.dtype || '').toLowerCase()
  const semantic = String(row.semantic_type || '').toLowerCase()
  return (
    dtype.includes('float')
    || dtype.includes('double')
    || dtype.includes('int')
    || dtype.includes('number')
    || dtype.includes('numeric')
    || ['continuous', 'count', 'composition', 'binary'].includes(semantic)
  )
}

function pickPreviewRows(rows) {
  const numeric = rows.filter(row => isNumericField(row))
  const rest = rows.filter(row => !isNumericField(row))
  return [...numeric, ...rest].slice(0, 6)
}

function hasOmics(item, omics) {
  const value = item?.omics?.[omics]
  return Boolean(value && (value === true || value.core_available || value.full_available || value.core_rows || value.full_rows))
}

function applyHomePreview(payload) {
  previewRows.value = payload.feature_rows || []
  fieldCount.value = Number(payload.field_count || 0)
  entityCount.value = Number(payload.entity_count || 0)
  families.value = payload.facets?.families || families.value
  qc.value = payload.qc || {}
}

async function loadCachedHomePreview(config) {
  const payload = await getFeatureHubHomePreview({
    species_id: selectedSpecies.value,
    omics: selectedOmics.value,
    scope: selectedScope.value,
    family: selectedFamily.value,
  }, config)
  applyHomePreview(payload)
  return payload
}

async function enrichRows(rows, config) {
  if (!selectedSpecies.value || !rows.length) return rows
  const profiles = await Promise.allSettled(
    rows.map(row => getFeatureHubFieldProfile({
      species_id: selectedSpecies.value,
      omics: selectedOmics.value,
      scope: selectedScope.value,
      field: row.field,
    }, config))
  )
  return rows.map((row, index) => {
    const profile = profiles[index].status === 'fulfilled' ? profiles[index].value : null
    const p25 = profile?.summary?.p25
    const p75 = profile?.summary?.p75
    const iqr = p25 !== null && p25 !== undefined && p75 !== null && p75 !== undefined ? Number(p75) - Number(p25) : null
    return {
      ...row,
      missingness: formatRate(profile?.missing_rate),
      iqr: formatNumber(iqr),
      notes: profile ? `${Number(profile.numeric_n || 0).toLocaleString()} numeric / ${Number(profile.n_rows || 0).toLocaleString()} rows` : row.notes,
    }
  })
}

async function loadQcSummary(fields, config) {
  if (selectedScope.value !== 'core' || !selectedSpecies.value || !fields.length) return null
  const report = await runFeatureHubQc({
    species_id: selectedSpecies.value,
    omics: selectedOmics.value,
    fields,
  }, config)
  const missingRates = Object.values(report.missingness || {})
  return {
    profile_status: 'profiled_preview_fields',
    missing_gt_20_count: missingRates.filter(item => Number(item?.missing_rate || 0) > 0.2).length,
    constant_count: (report.constant || []).length,
    high_corr_pair_count: (report.high_correlation_pairs || []).length,
    compositional_group_count: Object.keys(report.composition_groups || {}).length,
    message: `Computed from ${Number(report.selected_features || fields.length).toLocaleString()} preview Core fields across ${Number(report.n_rows || 0).toLocaleString()} ${selectedOmics.value} rows.`,
  }
}

async function reloadPreview() {
  if (controller) controller.abort()
  controller = new AbortController()
  const config = { signal: controller.signal }
  profiling.value = true
  try {
    await loadCachedHomePreview(config)
    profiling.value = false
    return
  } catch (error) {
    if (error?.name === 'CanceledError' || error?.name === 'AbortError') {
      profiling.value = false
      return
    }
  }
  const catalog = await getFeatureHubCatalog({
    omics: selectedOmics.value,
    scope: selectedScope.value,
    family: selectedFamily.value,
  }, config)
  const rows = catalog.items || []
  const selectedRows = pickPreviewRows(rows).map(row => ({
    field: row.field,
    label: row.label,
    family: row.family,
    module: row.semantic_type || row.ml_role,
    dtype: row.dtype,
    ml_role: row.ml_role,
    missingness: 'Profiling...',
    iqr: 'Profiling...',
    notes: 'Waiting for field profile',
  }))
  previewRows.value = selectedRows
  fieldCount.value = rows.length
  families.value = catalog.facets?.families || families.value
  qc.value = {
    profile_status: 'not_profiled',
    missing_gt_20_count: null,
    constant_count: null,
    high_corr_pair_count: null,
    compositional_group_count: new Set(rows.map(row => row.composition_group).filter(Boolean)).size,
    message: 'Profiling selected preview fields from the registered Core matrix.',
  }
  if (selectedSpecies.value) {
    try {
      const dataset = await getFeatureHubDataset(selectedSpecies.value, selectedOmics.value, { scope: selectedScope.value }, config)
      entityCount.value = Number(dataset.row_count || 0)
    } catch (error) {
      entityCount.value = 0
    }
  }
  try {
    previewRows.value = await enrichRows(selectedRows, config)
  } catch (error) {
    if (error?.name === 'CanceledError' || error?.name === 'AbortError') {
      profiling.value = false
      return
    }
  }
  try {
    const summary = await loadQcSummary(selectedRows.map(row => row.field), config)
    if (summary) qc.value = summary
  } catch (error) {
    if (error?.name === 'CanceledError' || error?.name === 'AbortError') return
  } finally {
    profiling.value = false
  }
}

onMounted(async () => {
  const homepageSpecies = (props.representativeSpecies || []).filter(item => item?.species_id)
  if (homepageSpecies.length) {
    speciesOptions.value = homepageSpecies
    const preferred = homepageSpecies.find(item => hasOmics(item, selectedOmics.value)) || homepageSpecies[0]
    selectedSpecies.value = preferred.species_id
  } else {
    try {
      const payload = await getFeatureHubSpecies({ limit: 8, omics: selectedOmics.value })
      speciesOptions.value = payload.items || payload.species || []
      if (!selectedSpecies.value && speciesOptions.value.length) selectedSpecies.value = speciesOptions.value[0].species_id
    } catch (error) {
      speciesOptions.value = props.spotlight?.species ? [props.spotlight.species] : []
    }
  }
  if (!speciesOptions.value.length && props.spotlight?.species) {
    speciesOptions.value = [props.spotlight.species]
  }
  if (hasProfiledSpotlightData()) return
  await reloadPreview()
})
</script>
