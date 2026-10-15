<template>
  <div class="stack-lg">
    <section v-if="loading" class="panel">
      <p class="muted">Loading API and dictionary payload...</p>
    </section>

    <section v-else-if="loadError" class="panel">
      <p class="muted">{{ loadError }}</p>
      <button class="btn subtle" @click="load">Retry</button>
    </section>

    <template v-else-if="payload">
      <section class="panel">
        <div class="section-header compact">
          <div>
            <div class="eyebrow">Platform scope</div>
            <h3>{{ PLATFORM_POSITIONING }}</h3>
            <p class="muted">Transcript sequence modules describe sequence-derived stoichiometric features and are separate from RNA-seq expression workflows.</p>
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="section-header">
          <div>
            <div class="eyebrow">Backend reference</div>
            <h3>API endpoints</h3>
          </div>
        </div>
        <ul class="clean-list compact-list">
          <li v-for="note in payload.api.notes" :key="note">{{ note }}</li>
        </ul>
        <div class="table-wrap" style="margin-top: 16px">
          <table class="table">
            <thead>
              <tr>
                <th>Method</th>
                <th>Path</th>
                <th>Summary</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in payload.api.endpoints" :key="row.path">
                <td>{{ row.method }}</td>
                <td>{{ row.path }}</td>
                <td>{{ row.summary }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section v-if="payload.id_mapping" class="panel">
        <div class="section-header">
          <div>
            <div class="eyebrow">ID Mapping Layer</div>
            <h3>Resolution endpoints and field semantics</h3>
            <p class="muted">Internal IDs remain platform keys; external IDs are searchable evidence aliases with confidence and status labels.</p>
          </div>
          <span class="badge">{{ payload.id_mapping.manifest?.runtime_index_scope || 'runtime index' }}</span>
        </div>
        <div class="grid grid-3">
          <div class="mini-card">
            <div class="label">Schema</div>
            <div class="metric-inline">{{ payload.id_mapping.schema?.schema_version || payload.id_mapping.manifest?.schema_version }}</div>
          </div>
          <div class="mini-card">
            <div class="label">Chain rows</div>
            <div class="metric-inline">{{ payload.id_mapping.manifest?.tables?.id_mapping_chain }}</div>
          </div>
          <div class="mini-card">
            <div class="label">Alias rows</div>
            <div class="metric-inline">{{ payload.id_mapping.manifest?.tables?.id_alias_index }}</div>
          </div>
        </div>
        <div class="table-wrap" style="margin-top: 14px">
          <table class="table compact-table">
            <thead><tr><th>Method</th><th>Endpoint</th><th>Purpose</th></tr></thead>
            <tbody>
              <tr v-for="row in payload.id_mapping.endpoints || []" :key="row.path">
                <td>{{ row.method }}</td>
                <td>{{ row.path }}</td>
                <td>{{ row.purpose }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="grid grid-2" style="margin-top: 14px">
          <article class="mini-card">
            <div class="label">Status semantics</div>
            <ul class="clean-list compact-list">
              <li v-for="(value, key) in payload.id_mapping.status_semantics" :key="key"><strong>{{ key }}</strong>: {{ value }}</li>
            </ul>
          </article>
          <article class="mini-card">
            <div class="label">Confidence semantics</div>
            <ul class="clean-list compact-list">
              <li v-for="(value, key) in payload.id_mapping.confidence_semantics" :key="key"><strong>{{ key }}</strong>: {{ value }}</li>
            </ul>
          </article>
        </div>
      </section>

      <section v-if="payload.functional_annotations" class="panel">
        <div class="section-header">
          <div>
            <div class="eyebrow">Functional Annotation Layer</div>
            <h3>GO/KEGG status, search, entity evidence, and enrichment</h3>
            <p class="muted">Only official standard records are loaded; unsupported species are explicit status rows.</p>
          </div>
          <span class="badge">{{ payload.functional_annotations.release?.schema_version }}</span>
        </div>
        <div class="grid grid-3">
          <div class="mini-card">
            <div class="label">Species tracked</div>
            <div class="metric-inline">{{ payload.functional_annotations.release?.species_total }}</div>
          </div>
          <div class="mini-card">
            <div class="label">GO rows</div>
            <div class="metric-inline">{{ payload.functional_annotations.release?.go_annotation_count }}</div>
          </div>
          <div class="mini-card">
            <div class="label">KEGG links</div>
            <div class="metric-inline">{{ payload.functional_annotations.release?.kegg_link_count }}</div>
          </div>
        </div>
        <div class="table-wrap" style="margin-top: 14px">
          <table class="table compact-table">
            <thead><tr><th>Method</th><th>Endpoint</th><th>Purpose</th></tr></thead>
            <tbody>
              <tr v-for="row in payload.functional_annotations.endpoints || []" :key="row.path">
                <td>{{ row.method }}</td>
                <td>{{ row.path }}</td>
                <td>{{ row.purpose }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section v-if="payload.phylogeny" class="panel">
        <div class="section-header">
          <div>
            <div class="eyebrow">Phylogeny Layer</div>
            <h3>Tree release, runtime statistics, and interpretation boundary</h3>
            <p class="muted">{{ payload.phylogeny.interpretation_boundary }}</p>
          </div>
          <span :class="['badge', payload.phylogeny.release?.p2?.analysis_readiness?.pgls_eligible ? 'status-ready' : 'status-muted']">
            {{ payload.phylogeny.release?.p2?.analysis_readiness?.pgls_eligible ? 'analysis-grade ready' : 'taxonomy topology only' }}
          </span>
        </div>
        <div class="grid grid-3">
          <div class="mini-card">
            <div class="label">Release</div>
            <div class="metric-inline">{{ payload.phylogeny.release?.release_id }}</div>
          </div>
          <div class="mini-card">
            <div class="label">Taxonomy tips</div>
            <div class="metric-inline">{{ payload.phylogeny.release?.summary?.tip_count }}</div>
          </div>
          <div class="mini-card">
            <div class="label">Analysis tips</div>
            <div class="metric-inline">{{ payload.phylogeny.release?.p2?.analysis_grade_tree?.tip_count || '-' }}</div>
          </div>
        </div>
        <div class="table-wrap" style="margin-top: 14px">
          <table class="table compact-table">
            <thead><tr><th>Method</th><th>Endpoint</th><th>Purpose</th></tr></thead>
            <tbody>
              <tr v-for="row in payload.phylogeny.endpoints || []" :key="row.path">
                <td>{{ row.method }}</td>
                <td>{{ row.path }}</td>
                <td>{{ row.purpose }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="table-wrap" style="margin-top: 14px">
          <table class="table compact-table">
            <thead><tr><th>Contract</th><th>Path</th><th>Purpose</th></tr></thead>
            <tbody>
              <tr v-for="row in payload.phylogeny.data_contracts || []" :key="row.path">
                <td>{{ row.name }}</td>
                <td>{{ row.path }}</td>
                <td>{{ row.purpose }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="panel">
        <div class="section-header">
          <div>
            <div class="eyebrow">Feature Dictionary</div>
            <h3>Field formulas, units, coverage, and missing rules</h3>
            <p class="muted">
              Schema {{ featureDictionary.schema_version || featureDictionary.version || '-' }} from {{ featureDictionary.dictionary_source || '-' }}.
            </p>
          </div>
          <span class="badge">{{ filteredFeatures.length }} / {{ featureRows.length }} fields</span>
        </div>
        <div class="toolbar-grid">
          <input v-model="featureQuery" class="input" placeholder="Search field, label, family, formula, or meaning" />
          <select v-model="featureOmics" class="input">
            <option value="">All omics</option>
            <option value="genome">Genome</option>
            <option value="transcriptome">Transcript sequence</option>
            <option value="proteome">Proteome</option>
          </select>
          <select v-model="featureFamily" class="input">
            <option value="">All modules/families</option>
            <option v-for="family in featureFamilies" :key="family" :value="family">{{ formatLabel(family) }}</option>
          </select>
        </div>
        <div class="grid grid-3" style="margin-top: 14px">
          <div class="mini-card">
            <div class="label">Fields</div>
            <div class="metric-inline">{{ featureDictionary.coverage_summary?.field_count || featureRows.length }}</div>
          </div>
          <div class="mini-card">
            <div class="label">Defined formulas</div>
            <div class="metric-inline">{{ featureDictionary.coverage_summary?.defined_formula_count || 0 }}</div>
          </div>
          <div class="mini-card">
            <div class="label">Pending formulas</div>
            <div class="metric-inline">{{ featureDictionary.coverage_summary?.pending_formula_count || 0 }}</div>
          </div>
        </div>
        <div class="table-wrap" style="margin-top: 14px">
          <table class="table compact-table">
            <thead>
              <tr>
                <th>Omics</th>
                <th>Field</th>
                <th>Module</th>
                <th>Unit</th>
                <th>Formula status</th>
                <th>Coverage</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in filteredFeatures.slice(0, 120)"
                :key="`${row.omics}-${row.field}`"
                :class="{ selected: selectedFeatureKey === `${row.omics}-${row.field}` }"
                @click="selectedFeatureKey = `${row.omics}-${row.field}`"
              >
                <td>{{ row.omics_label || row.omics }}</td>
                <td>{{ row.field }}</td>
                <td>{{ formatLabel(row.family) }}</td>
                <td>{{ row.unit || '-' }}</td>
                <td><span class="badge">{{ row.formula_status }}</span></td>
                <td>{{ formatPercent(row.coverage_ratio) }}</td>
              </tr>
              <tr v-if="!filteredFeatures.length"><td colspan="6">No feature matches the current filters.</td></tr>
            </tbody>
          </table>
        </div>
      </section>

      <section v-if="selectedFeature" class="panel">
        <div class="section-header compact">
          <div>
            <div class="eyebrow">{{ selectedFeature.omics_label || selectedFeature.omics }}</div>
            <h3>{{ selectedFeature.label || selectedFeature.field }}</h3>
            <p class="muted">{{ selectedFeature.scientific_meaning || 'No short field description is registered.' }}</p>
          </div>
        </div>
        <div class="grid grid-2">
          <article class="mini-card">
            <div class="label">Formula</div>
            <p class="muted">{{ selectedFeature.formula }}</p>
          </article>
          <article class="mini-card">
            <div class="label">Missing rule</div>
            <p class="muted">{{ selectedFeature.missing_rule }}</p>
          </article>
          <article class="mini-card">
            <div class="label">Normalization</div>
            <div class="metric-inline">{{ selectedFeature.normalization || 'none' }}</div>
          </article>
          <article class="mini-card">
            <div class="label">Coverage / missing</div>
            <div class="metric-inline">{{ formatPercent(selectedFeature.coverage_ratio) }} / {{ formatPercent(selectedFeature.missing_rate) }}</div>
          </article>
        </div>
      </section>

      <section class="grid grid-2">
        <article class="panel">
          <div class="section-header compact"><h3>Core models</h3></div>
          <ul class="clean-list compact-list">
            <li v-for="row in payload.dictionary.core_models" :key="row.name">
              <strong>{{ row.name }}</strong>: {{ row.description }}
            </li>
          </ul>
        </article>
        <article class="panel">
          <div class="section-header compact"><h3>Release fields</h3></div>
          <ul class="clean-list compact-list">
            <li v-for="field in payload.dictionary.release_fields" :key="field">{{ field }}</li>
          </ul>
        </article>
      </section>

      <section class="panel">
        <div class="section-header compact"><h3>Omics dictionary</h3></div>
        <div class="grid grid-3">
          <article class="feature-card" v-for="row in payload.dictionary.omics_dictionary" :key="row.omics">
            <div class="eyebrow">{{ row.display_name }}</div>
            <h4>{{ row.entity_label }}</h4>
            <p class="muted">{{ row.description }}</p>
            <ul class="clean-list compact-list">
              <li><strong>Primary ID:</strong> {{ row.primary_id }}</li>
              <li><strong>Browse columns:</strong> {{ row.browse_columns.join(', ') }}</li>
              <li><strong>Feature options:</strong> {{ row.feature_options.join(', ') }}</li>
            </ul>
          </article>
        </div>
      </section>

      <section class="panel">
        <div class="section-header compact"><h3>Data contracts</h3></div>
        <div class="table-wrap">
          <table class="table compact-table">
            <thead><tr><th>Name</th><th>Path</th><th>Purpose</th></tr></thead>
            <tbody>
              <tr v-for="row in payload.data_contracts || []" :key="row.path">
                <td>{{ row.name }}</td>
                <td>{{ row.path }}</td>
                <td>{{ row.purpose }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>

    <section v-else class="panel">
      <p class="muted">No docs payload is available.</p>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { getDocs } from '../api/stoichdb'
import { PLATFORM_POSITIONING } from '../constants/platformTerminology'

const payload = ref(null)
const loading = ref(true)
const loadError = ref('')
const featureQuery = ref('')
const featureOmics = ref('')
const featureFamily = ref('')
const selectedFeatureKey = ref('')

const featureDictionary = computed(() => payload.value?.feature_dictionary || {})
const featureRows = computed(() => featureDictionary.value?.items || [])
const featureFamilies = computed(() => [...new Set(featureRows.value.map((row) => row.family).filter(Boolean))].sort())
const filteredFeatures = computed(() => {
  const query = featureQuery.value.trim().toLowerCase()
  return featureRows.value.filter((row) => {
    if (featureOmics.value && row.omics !== featureOmics.value) return false
    if (featureFamily.value && row.family !== featureFamily.value) return false
    if (!query) return true
    return [row.field, row.label, row.family, row.formula, row.scientific_meaning]
      .some((value) => String(value || '').toLowerCase().includes(query))
  })
})
const selectedFeature = computed(() => {
  const selected = featureRows.value.find((row) => `${row.omics}-${row.field}` === selectedFeatureKey.value)
  return selected || filteredFeatures.value[0] || null
})

function formatLabel(value) {
  return String(value || '').replaceAll('_', ' ')
}

function formatPercent(value) {
  const num = Number(value)
  if (!Number.isFinite(num)) return '-'
  return `${(num * 100).toFixed(1)}%`
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    payload.value = await getDocs()
  } catch (error) {
    payload.value = null
    loadError.value =
      error?.response?.data?.error?.message ||
      error?.response?.data?.message ||
      error?.message ||
      'Failed to load docs payload.'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>
