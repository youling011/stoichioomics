<template>
  <div class="stack-lg">
    <section v-if="loading" class="panel">
      <p class="muted">Loading visualization hub payload...</p>
    </section>

    <section v-else-if="loadError" class="panel">
      <p class="muted">{{ loadError }}</p>
      <button class="btn subtle" @click="load">Retry</button>
    </section>

    <template v-else-if="meta">
      <section class="panel">
        <div class="section-header">
          <div>
            <div class="eyebrow">Visualization branches</div>
            <h3>Basic stoichiometric visualization modules</h3>
            <p class="muted">This branch sits in parallel with deep analysis. It exposes the raw structure of the feature tables before moving into higher-level interpretation.</p>
          </div>
        </div>
        <div class="grid grid-3">
          <article class="feature-card" v-for="(item, key) in meta.omics_meta" :id="key" :key="key">
            <div class="eyebrow">{{ item.display_name }}</div>
            <h4>{{ item.entity_label }}-centric basic layer</h4>
            <p class="muted">{{ item.description }}</p>
            <ul class="clean-list compact-list">
              <li>Distribution landscapes for core stoichiometric features</li>
              <li>Cross-feature scatter maps and density structure</li>
              <li>Correlation surfaces and representative entities</li>
              <li>Scrollable feature-table view with row drill-down</li>
            </ul>
          </article>
        </div>
      </section>

      <section class="grid grid-2">
        <article class="panel chart-panel">
          <div class="section-header compact">
            <div>
              <div class="eyebrow">Registry coverage</div>
              <h3>Domain ? omics availability in filtered registry</h3>
            </div>
          </div>
          <EChart :option="omicsChart" :height="340" />
          <div class="annotation">The public deployment target is much larger, but the same page logic scales from the loaded registry to the full site.</div>
        </article>
        <article class="panel chart-panel">
          <div class="section-header compact">
            <div>
              <div class="eyebrow">Display schema</div>
              <h3>Key feature families</h3>
            </div>
          </div>
          <KeyFeatureMap :schema="meta.feature_display_schema" />
          <MethodBadge
            method="feature display schema"
            normalization="none"
            missing-policy="schema metadata; release coverage is shown below"
            note="Field names are grouped for navigation and do not encode species values."
          />
        </article>
      </section>

      <section v-if="annotationStatus" class="panel">
        <div class="section-header compact">
          <div>
            <div class="eyebrow">Functional annotation visuals</div>
            <h3>GO/KEGG coverage entry points</h3>
            <p class="muted">Open a supported species to inspect functional summaries next to stoichiometric visual modules.</p>
          </div>
          <router-link class="btn subtle" to="/analysis">Open enrichment hub</router-link>
        </div>
        <div class="grid grid-4">
          <div class="card"><div class="label">Species tracked</div><div class="kpi">{{ annotationStatus.summary?.species_total }}</div></div>
          <div class="card"><div class="label">GO species</div><div class="kpi">{{ annotationStatus.summary?.go_species_count }}</div></div>
          <div class="card"><div class="label">KEGG species</div><div class="kpi">{{ annotationStatus.summary?.kegg_species_count }}</div></div>
          <div class="card"><div class="label">Policy</div><div class="kpi small-kpi">standard only</div></div>
        </div>
      </section>

      <section class="panel chart-panel">
        <div class="section-header compact">
          <div>
            <div class="eyebrow">Feature availability atlas</div>
            <h3>Omics × feature-family coverage</h3>
          </div>
        </div>
        <EChart :option="featureAvailabilityChart" :height="360" @chart-click="selectCoverageCell" />
        <div class="annotation">
          Counts are generated from the shared feature display schema and indicate how many fields in each family are available for basic visualization.
        </div>
        <div v-if="activeCoverageCell" class="table-wrap" style="margin-top: 14px">
          <table class="table compact-table">
            <thead>
              <tr>
                <th>Selected omics</th>
                <th>Feature family</th>
                <th>Fields</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>{{ activeCoverageCell.omicsLabel }}</td>
                <td>{{ formatLabel(activeCoverageCell.family) }}</td>
                <td>
                  <span v-for="item in activeCoverageFields" :key="item.field" class="badge" style="margin: 3px">
                    {{ item.label || item.field }}
                  </span>
                  <span v-if="!activeCoverageFields.length" class="muted">No fields in this cell.</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="panel">
        <div class="section-header">
          <div>
            <div class="eyebrow">Initial-plan implementation coverage</div>
            <h3>Planned visual modules vs current release fields</h3>
            <p class="muted">These rows map the initial optimization plan to fields that are actually present in the loaded data. Missing rows are placeholders for future imports, not computed results.</p>
          </div>
          <span class="badge">{{ implementedModuleCount }} / {{ plannedVisualModules.length }} implemented</span>
        </div>
        <div class="table-wrap">
          <table class="table compact-table">
            <thead>
              <tr>
                <th>Omics</th>
                <th>Module</th>
                <th>Status</th>
                <th>Coverage</th>
                <th>Visual</th>
                <th>Missing fields</th>
                <th>Purpose</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in plannedVisualModules" :key="`${item.omics}-${item.module}`">
                <td>{{ item.omics_label || item.omics }}</td>
                <td>{{ item.module }}</td>
                <td>{{ item.implementation_status }}</td>
                <td>{{ percent(item.coverage_ratio) }}</td>
                <td>{{ item.recommended_visual }}</td>
                <td>{{ (item.missing_required_fields || []).join(', ') || '-' }}</td>
                <td>{{ item.purpose }}</td>
              </tr>
              <tr v-if="!plannedVisualModules.length">
                <td colspan="7">No planned visual modules are exposed by the API.</td>
              </tr>
            </tbody>
          </table>
        </div>
        <MethodBadge
          method="initial optimization plan requirement mapping"
          normalization="field presence only"
          missing-policy="missing required fields are shown as unimplemented modules"
          :n="plannedVisualModules.length"
          note="Open a species page for real distributions, scatter plots, and example entity values."
        />
      </section>

      <section class="panel">
        <div class="section-header">
          <div>
            <div class="eyebrow">Feature browser</div>
            <h3>All-field explorer</h3>
            <p class="muted">Search by field, label, family, omics branch, recommended chart, or scientific meaning.</p>
          </div>
          <span class="badge">{{ filteredFeatureCatalog.length }} / {{ featureCatalogRows.length }} fields</span>
        </div>
        <div class="toolbar-grid">
          <input v-model="fieldQuery" class="input" placeholder="Search field, family, unit, or meaning" />
          <select v-model="selectedFamily" class="input">
            <option value="">All families</option>
            <option v-for="family in catalogFamilies" :key="family" :value="family">{{ formatLabel(family) }}</option>
          </select>
          <select v-model="selectedCatalogOmics" class="input">
            <option value="">All omics</option>
            <option value="genome">Genome</option>
            <option value="transcriptome">Transcript sequence</option>
            <option value="proteome">Proteome</option>
          </select>
        </div>
        <div class="table-wrap" style="margin-top: 14px">
          <table class="table compact-table">
            <thead>
              <tr>
                <th>Omics</th>
                <th>Field</th>
                <th>Family</th>
                <th>Unit</th>
                <th>Core/full</th>
                <th>Recommended chart</th>
                <th>Evidence</th>
                <th>Scientific meaning</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in filteredFeatureCatalog.slice(0, 80)" :key="`${item.omics}-${item.field}`">
                <td>{{ item.omics_label || item.omics }}</td>
                <td>{{ item.label || item.field }}<br /><span class="muted">{{ item.field }}</span></td>
                <td>{{ formatLabel(item.family) }}</td>
                <td>{{ item.unit || '-' }}</td>
                <td>{{ (item.available_scopes || []).join(' / ') || item.scope }}</td>
                <td>{{ item.recommended_chart }}</td>
                <td>{{ item.evidence_level }}</td>
                <td>{{ item.scientific_meaning || '-' }}</td>
              </tr>
              <tr v-if="!filteredFeatureCatalog.length">
                <td colspan="8">No fields match the current filters.</td>
              </tr>
            </tbody>
          </table>
        </div>
        <MethodBadge
          :method="featureCatalog?.method_metadata?.source || 'feature schema'"
          :normalization="featureCatalog?.method_metadata?.normalization || 'none'"
          :missing-policy="featureCatalog?.method_metadata?.missing_policy || 'schema only'"
          :n="featureCatalogRows.length"
          note="Select a species page to inspect actual distributions, top/bottom rankings, or pairwise scatter for these fields."
        />
      </section>

      <section class="panel">
        <div class="section-header">
          <div>
            <div class="eyebrow">Open a visual explorer</div>
            <h3>Species entry points</h3>
          </div>
        </div>
        <div class="grid grid-3">
          <router-link class="species-card" v-for="species in speciesRows" :key="species.species_id" :to="`/species/${species.species_id}`">
            <div class="section-header compact">
              <div>
                <h4>{{ species.short_name }}</h4>
                <p class="muted">{{ species.source_context || 'Local registry dataset' }}</p>
              </div>
              <span class="badge">Explorer</span>
            </div>
            <div class="grid grid-3 dense-grid">
              <div class="mini-card">
                <div class="label">Genome GC</div>
                <div class="metric-inline">{{ species.fingerprint.genome_gc }}</div>
              </div>
              <div class="mini-card">
                <div class="label">RNA entropy</div>
                <div class="metric-inline">{{ species.fingerprint.transcript_entropy }}</div>
              </div>
              <div class="mini-card">
                <div class="label">Proteome pI</div>
                <div class="metric-inline">{{ species.fingerprint.proteome_pi }}</div>
              </div>
            </div>
          </router-link>
        </div>
      </section>
    </template>

    <section v-else class="panel">
      <p class="muted">No visualization payload is available.</p>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import EChart from '../components/EChart.vue'
import KeyFeatureMap from '../components/KeyFeatureMap.vue'
import MethodBadge from '../components/MethodBadge.vue'
import { getAnnotationStatus, getFeatureCatalog, getPlatformMeta, listSpecies } from '../api/stoichdb'
import { matrixHeatmapOption } from '../utils/charts'

const meta = ref(null)
const speciesRows = ref([])
const registryAggregate = ref(null)
const featureCatalog = ref(null)
const annotationStatus = ref(null)
const loading = ref(true)
const loadError = ref('')
const fieldQuery = ref('')
const selectedFamily = ref('')
const selectedCatalogOmics = ref('')
const activeCoverageCell = ref(null)
const coverageAxes = ref({ families: [], omicsOrder: [], yLabels: [] })

const omicsChart = computed(() => {
  const matrix = registryAggregate.value?.domain_omics_matrix
  if (matrix?.x_labels?.length && matrix?.y_labels?.length) {
    return matrixHeatmapOption(matrix.x_labels, matrix.y_labels, matrix.values || [], {
      min: 0,
      max: Math.max(1, ...(matrix.values || []).map((item) => Number(item?.[2]) || 0)),
      scaleType: 'coverage',
      showLabel: true,
    })
  }
  const counts = registryAggregate.value?.omics_counts || { genome: 0, transcriptome: 0, proteome: 0 }
  return matrixHeatmapOption(Object.keys(counts), ['Registry'], Object.entries(counts).map(([key, value], index) => [index, 0, value]), {
    min: 0,
    max: Math.max(1, ...Object.values(counts).map((value) => Number(value) || 0)),
    scaleType: 'coverage',
    showLabel: true,
  })
})

const featureCatalogRows = computed(() => featureCatalog.value?.items || [])

const plannedVisualModules = computed(() => featureCatalog.value?.planned_visual_modules || [])

const implementedModuleCount = computed(() =>
  plannedVisualModules.value.filter((item) => item.implementation_status === 'implemented').length,
)

const catalogFamilies = computed(() => {
  const values = new Set(featureCatalogRows.value.map((item) => item.family).filter(Boolean))
  return [...values].sort()
})

const filteredFeatureCatalog = computed(() => {
  const q = fieldQuery.value.trim().toLowerCase()
  return featureCatalogRows.value.filter((item) => {
    if (selectedFamily.value && item.family !== selectedFamily.value) return false
    if (selectedCatalogOmics.value && item.omics !== selectedCatalogOmics.value) return false
    if (!q) return true
    const text = [
      item.omics,
      item.omics_label,
      item.field,
      item.label,
      item.family,
      item.unit,
      item.recommended_chart,
      item.evidence_level,
      item.scientific_meaning,
    ].join(' ').toLowerCase()
    return text.includes(q)
  })
})

const featureAvailabilityChart = computed(() => {
  const schemaOmics = meta.value?.feature_display_schema?.omics || {}
  const omicsOrder = ['genome', 'transcriptome', 'proteome'].filter((key) => schemaOmics[key])
  if (!omicsOrder.length) return matrixHeatmapOption([], [], [])
  const familySet = new Set()
  for (const omicsKey of omicsOrder) {
    for (const item of schemaOmics[omicsKey] || []) {
      if (item?.family) familySet.add(item.family)
    }
  }
  const families = [...familySet]
  coverageAxes.value = {
    families,
    omicsOrder,
    yLabels: omicsOrder.map((key) => meta.value?.omics_meta?.[key]?.display_name || key),
  }
  const values = []
  omicsOrder.forEach((omicsKey, rowIndex) => {
    const rows = schemaOmics[omicsKey] || []
    const counts = {}
    rows.forEach((item) => {
      const family = item?.family || 'other'
      counts[family] = (counts[family] || 0) + 1
    })
    families.forEach((family, colIndex) => {
      values.push([colIndex, rowIndex, counts[family] || 0])
    })
  })
  const yLabels = omicsOrder.map((key) => meta.value?.omics_meta?.[key]?.display_name || key)
  return matrixHeatmapOption(families, yLabels, values, { min: 0, max: Math.max(1, ...values.map((item) => Number(item[2]) || 0)), showLabel: true })
})

const activeCoverageFields = computed(() => {
  if (!activeCoverageCell.value) return []
  return featureCatalogRows.value.filter(
    (item) => item.omics === activeCoverageCell.value.omics && item.family === activeCoverageCell.value.family,
  )
})

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const [metaData, speciesData, featureCatalogData, annotationStatusData] = await Promise.all([getPlatformMeta(), listSpecies({ page: 1, page_size: 48 }), getFeatureCatalog(), getAnnotationStatus({ page_size: 1 })])
    meta.value = metaData
    speciesRows.value = Array.isArray(speciesData) ? speciesData : (speciesData?.items || [])
    registryAggregate.value = Array.isArray(speciesData) ? null : (speciesData?.aggregate || null)
    featureCatalog.value = featureCatalogData
    annotationStatus.value = annotationStatusData
  } catch (error) {
    meta.value = null
    speciesRows.value = []
    registryAggregate.value = null
    featureCatalog.value = null
    annotationStatus.value = null
    loadError.value =
      error?.response?.data?.error?.message ||
      error?.response?.data?.message ||
      error?.message ||
      'Failed to load visualization hub payload.'
  } finally {
    loading.value = false
  }
}

function formatLabel(value) {
  return String(value || '').replaceAll('_', ' ')
}

function percent(value) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return '-'
  return `${Math.round(numeric * 100)}%`
}

function selectCoverageCell(params) {
  const value = params?.data || params?.value || []
  const family = coverageAxes.value.families?.[value[0]]
  const omics = coverageAxes.value.omicsOrder?.[value[1]]
  if (!family || !omics) return
  activeCoverageCell.value = {
    family,
    omics,
    omicsLabel: coverageAxes.value.yLabels?.[value[1]] || omics,
  }
  selectedFamily.value = family
  selectedCatalogOmics.value = omics
}

onMounted(load)
</script>
