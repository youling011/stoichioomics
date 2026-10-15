<template>
  <div class="stack-lg">
    <section v-if="loading" class="panel">
      <p class="muted">Loading quality-control payload...</p>
    </section>

    <section v-else-if="loadError" class="panel">
      <p class="muted">{{ loadError }}</p>
      <button class="btn subtle" @click="load">Retry</button>
    </section>

    <template v-else-if="payload">
      <ActiveReleaseBanner :release="payload.release" :omics-coverage="payload.omics_coverage" />

      <section class="grid grid-3">
        <article class="feature-card">
          <div class="eyebrow">Registry completeness</div>
          <h3>{{ payload.summary.species_with_all_omics }} species with 3 omics</h3>
          <p class="muted">{{ payload.summary.species_count }} total species and {{ payload.summary.dataset_count }} datasets are currently registered.</p>
        </article>
        <article class="feature-card">
          <div class="eyebrow">File readiness</div>
          <h3>{{ payload.summary.feature_file_count }} source files</h3>
          <p class="muted">{{ payload.summary.artifact_count }} analysis artifacts are registered for reproducible download and review.</p>
        </article>
        <article class="feature-card">
          <div class="eyebrow">Entity scale</div>
          <h3>{{ payload.summary.entity_row_count }} indexed rows</h3>
          <p class="muted">QC is measured against the active release and current import manifest.</p>
        </article>
      </section>

      <section v-if="payload.id_mapping_qc" class="panel">
        <div class="section-header compact">
          <div>
            <div class="eyebrow">ID mapping QC</div>
            <h3>Resolution layer coverage and runtime index</h3>
            <p class="muted">Full CSV files are registered for download; the runtime lookup index is scoped in the manifest.</p>
          </div>
          <router-link class="btn subtle" to="/entity-search">Open ID search</router-link>
        </div>
        <div class="grid grid-4">
          <div class="card">
            <div class="label">Species summaries</div>
            <div class="kpi">{{ payload.id_mapping_qc.summary?.species_count || payload.id_mapping_qc.manifest?.species_count }}</div>
          </div>
          <div class="card">
            <div class="label">Runtime index</div>
            <div class="kpi small-kpi">{{ payload.id_mapping_qc.manifest?.runtime_index_scope || '-' }}</div>
          </div>
          <div class="card">
            <div class="label">Chain rows</div>
            <div class="kpi">{{ payload.id_mapping_qc.manifest?.tables?.id_mapping_chain }}</div>
          </div>
          <div class="card">
            <div class="label">Alias rows</div>
            <div class="kpi">{{ payload.id_mapping_qc.manifest?.tables?.id_alias_index }}</div>
          </div>
        </div>
        <div class="table-wrap compact-top">
          <table class="table compact-table">
            <thead><tr><th>Species</th><th>Complete chain</th><th>Conflict</th><th>UniProt</th><th>NCBI/INSDC</th><th>Grade</th></tr></thead>
            <tbody>
              <tr v-for="row in payload.id_mapping_qc.top_species || []" :key="row.species_id">
                <td>{{ row.species_id }}</td>
                <td>{{ formatRate(row.complete_chain_rate) }}</td>
                <td>{{ formatRate(row.conflict_rate) }}</td>
                <td>{{ formatRate(row.uniprot_coverage) }}</td>
                <td>{{ formatRate(row.ncbi_or_insdc_coverage) }}</td>
                <td><span class="badge">{{ row.grade }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section v-if="payload.functional_annotation_qc" class="panel">
        <div class="section-header compact">
          <div>
            <div class="eyebrow">Functional annotation QC</div>
            <h3>Official GO/KEGG coverage</h3>
            <p class="muted">Species without official standard records remain visible as no-standard-annotation.</p>
          </div>
          <router-link class="btn subtle" to="/analysis">Open analysis</router-link>
        </div>
        <div class="grid grid-4">
          <div class="card">
            <div class="label">Species tracked</div>
            <div class="kpi">{{ payload.functional_annotation_qc.coverage_summary?.species_total }}</div>
          </div>
          <div class="card">
            <div class="label">GO species</div>
            <div class="kpi">{{ payload.functional_annotation_qc.coverage_summary?.go_species_count }}</div>
          </div>
          <div class="card">
            <div class="label">KEGG species</div>
            <div class="kpi">{{ payload.functional_annotation_qc.coverage_summary?.kegg_species_count }}</div>
          </div>
          <div class="card">
            <div class="label">Downloads</div>
            <div class="kpi">{{ payload.functional_annotation_qc.downloads?.length || 0 }}</div>
          </div>
        </div>
        <div class="table-wrap compact-top">
          <table class="table compact-table">
            <thead><tr><th>Species</th><th>Status</th><th>GO rows</th><th>KEGG genes</th><th>KO</th><th>Pathways</th><th>Modules</th></tr></thead>
            <tbody>
              <tr v-for="row in payload.functional_annotation_qc.top_species || []" :key="row.species_id">
                <td>{{ row.tax_name || row.species_id }}</td>
                <td><span class="badge">{{ row.status }}</span></td>
                <td>{{ row.go_rows }}</td>
                <td>{{ row.kegg_gene_rows }}</td>
                <td>{{ row.kegg_ko_rows }}</td>
                <td>{{ row.kegg_pathway_rows }}</td>
                <td>{{ row.kegg_module_rows }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="grid grid-2">
        <article class="panel">
          <div class="section-header compact">
            <div>
              <div class="eyebrow">QC grade rules</div>
              <h3>Default comparison eligibility</h3>
            </div>
          </div>
          <div class="table-wrap">
            <table class="table compact-table">
              <thead><tr><th>Grade</th><th>Meaning</th><th>Rule</th></tr></thead>
              <tbody>
                <tr v-for="row in payload.qc_grade_rules || []" :key="row.grade">
                  <td><span class="badge">{{ row.grade }}</span></td>
                  <td>{{ row.meaning }}</td>
                  <td>{{ row.rule }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </article>
        <article class="panel chart-panel">
          <div class="section-header compact">
            <div>
              <div class="eyebrow">QC grade distribution</div>
              <h3>{{ payload.summary.default_compare_dataset_count || 0 }} datasets eligible for default comparison</h3>
            </div>
          </div>
          <EChart :option="qcGradeChart" :height="280" />
        </article>
      </section>

      <section class="grid grid-2">
        <article class="panel chart-panel">
          <div class="section-header compact"><h3>Omics coverage</h3></div>
          <EChart :option="omicsChart" :height="320" />
          <MethodBadge method="dataset count by omics" :n="payload.summary.dataset_count" normalization="count" missing-policy="registered datasets only" />
        </article>
        <article class="panel chart-panel">
          <div class="section-header compact"><h3>Source file types</h3></div>
          <EChart :option="fileChart" :height="320" />
          <MethodBadge method="FeatureFile grouped count" :n="payload.summary.feature_file_count" normalization="count" missing-policy="registered files only" />
        </article>
      </section>

      <section class="grid grid-2">
        <article class="panel chart-panel">
          <div class="section-header compact"><h3>Field coverage matrix</h3></div>
          <EChart :option="fieldCoverageChart" :height="420" @chart-click="selectQualityCell" />
          <MethodBadge
            :method="payload.field_coverage_matrix?.method_metadata?.method"
            :normalization="payload.field_coverage_matrix?.method_metadata?.normalization"
            :missing-policy="payload.field_coverage_matrix?.method_metadata?.missing_policy"
            :n="payload.field_coverage_matrix?.method_metadata?.n_entities_per_omics_max"
          />
        </article>
        <article class="panel chart-panel">
          <div class="section-header compact"><h3>Missingness matrix</h3></div>
          <EChart :option="missingnessChart" :height="420" @chart-click="selectQualityCell" />
          <MethodBadge
            :method="payload.missingness_matrix?.method_metadata?.method"
            :normalization="payload.missingness_matrix?.method_metadata?.normalization"
            :missing-policy="payload.missingness_matrix?.method_metadata?.missing_policy"
            :n="payload.missingness_matrix?.method_metadata?.n_entities_per_omics_max"
          />
        </article>
      </section>

      <section class="grid grid-2">
        <article class="panel chart-panel">
          <div class="section-header compact">
            <h3>Core/full row scope</h3>
            <select v-model="qualityScope" class="input select-inline">
              <option value="core">Core rows</option>
              <option value="full">Full rows</option>
              <option value="delta">Full-core gap</option>
            </select>
          </div>
          <EChart :option="coreFullScopeChart" :height="320" />
          <MethodBadge
            method="OmicsDataset row_count_core/full aggregation"
            :normalization="qualityScope"
            missing-policy="registered datasets only"
            :n="payload.summary.dataset_count"
          />
        </article>

        <article class="panel">
          <div class="section-header compact">
            <div>
              <h3>Selected matrix cell species</h3>
              <p class="muted">{{ selectedQualityCellLabel }}</p>
            </div>
          </div>
          <EmptyState
            v-if="!selectedQualityCell"
            eyebrow="Click matrix"
            title="Select a coverage or missingness cell"
            message="Click a matrix cell to list species carrying the selected omics branch. Field-level filtering is limited by the current indexed payload."
          />
          <div v-else class="table-wrap">
            <table class="table compact-table">
              <thead><tr><th>Species</th><th>Source</th><th></th></tr></thead>
              <tbody>
                <tr v-for="row in selectedCellSpecies" :key="row.species_id">
                  <td>{{ row.display_name }}</td>
                  <td>{{ row.source_context || '-' }}</td>
                  <td><router-link :to="`/species/${row.species_id}?panel=${selectedQualityCell.omics}`">Open</router-link></td>
                </tr>
                <tr v-if="!selectedCellSpecies.length"><td colspan="3">No species loaded for this omics branch.</td></tr>
              </tbody>
            </table>
          </div>
        </article>
      </section>

      <section class="grid grid-2">
        <article class="panel chart-panel">
          <div class="section-header compact"><h3>Join coverage flow</h3></div>
          <EChart :option="joinCoverageChart" :height="360" />
        </article>
        <article class="panel chart-panel">
          <div class="section-header compact"><h3>Provenance flow</h3></div>
          <EChart :option="provenanceFlowChart" :height="360" />
        </article>
      </section>

      <section class="panel chart-panel">
        <div class="section-header compact"><h3>Core vs full row-count gap (top datasets)</h3></div>
        <EChart v-if="(payload.core_full_gap || []).length" :option="coreFullGapChart" :height="380" />
        <EmptyState
          v-else
          eyebrow="Core/full parity"
          title="Current release has no core/full row-count gap"
          message="No dataset in the current release has a full row count greater than its core row count, so the gap ranking chart is not displayed."
        />
      </section>

      <section class="panel">
        <div class="section-header compact"><h3>Heaviest species by indexed rows</h3></div>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>Species</th>
                <th>Source context</th>
                <th>Datasets</th>
                <th>Rows</th>
                <th>Artifacts</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in payload.species_heaviest || []" :key="row.species_id">
                <td>{{ row.display_name }}</td>
                <td>{{ row.source_context || 'Local registry dataset' }}</td>
                <td>{{ row.dataset_count }}</td>
                <td>{{ row.entity_row_count }}</td>
                <td>{{ row.artifacts }}</td>
                <td><router-link :to="`/species/${row.species_id}`">Open</router-link></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>

    <section v-else class="panel">
      <p class="muted">No quality payload is available.</p>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import ActiveReleaseBanner from '../components/ActiveReleaseBanner.vue'
import EChart from '../components/EChart.vue'
import EmptyState from '../components/EmptyState.vue'
import MethodBadge from '../components/MethodBadge.vue'
import { getQuality, listSpecies } from '../api/stoichdb'
import { barOption, donutOption, matrixHeatmapOption, rankLollipopOption, sankeyOption } from '../utils/charts'

const payload = ref(null)
const loading = ref(true)
const loadError = ref('')
const qualityScope = ref('core')
const selectedQualityCell = ref(null)
const selectedCellSpecies = ref([])

const omicsChart = computed(() => {
  const rows = payload.value?.omics_coverage || []
  return matrixHeatmapOption(
    rows.map((row) => row.omics),
    ['Datasets'],
    rows.map((row, index) => [index, 0, row.dataset_count || 0]),
    {
      min: 0,
      max: Math.max(1, ...rows.map((row) => Number(row.dataset_count) || 0)),
      scaleType: 'coverage',
      showLabel: true,
    },
  )
})

const fileChart = computed(() =>
  barOption(
    (payload.value?.source_file_types || []).map((row) => row.file_type || 'unknown'),
    (payload.value?.source_file_types || []).map((row) => row.count || 0),
    'Files',
    true,
  ),
)

const fieldCoverageChart = computed(() => {
  const matrix = payload.value?.field_coverage_matrix || { x_labels: [], y_labels: [], values: [] }
  return matrixHeatmapOption(matrix.x_labels || [], matrix.y_labels || [], matrix.values || [], {
    min: 0,
    max: 1,
    showLabel: true,
    details: matrix.details || [],
  })
})

const missingnessChart = computed(() => {
  const matrix = payload.value?.missingness_matrix || { x_labels: [], y_labels: [], values: [] }
  return matrixHeatmapOption(matrix.x_labels || [], matrix.y_labels || [], matrix.values || [], {
    min: 0,
    max: 1,
    showLabel: true,
    details: matrix.details || [],
  })
})

const joinCoverageChart = computed(() =>
  sankeyOption(payload.value?.join_coverage_sankey?.links || []),
)

const provenanceFlowChart = computed(() =>
  sankeyOption(payload.value?.provenance_flow?.links || []),
)

const coreFullGapChart = computed(() =>
  rankLollipopOption(
    (payload.value?.core_full_gap || []).slice(0, 20).map((row) => ({
      name: `${row.species_name} / ${row.omics}`,
      value: row.delta,
    })),
    'name',
    'value',
    'Row gap',
  ),
)

const coreFullScopeChart = computed(() => {
  const rows = payload.value?.core_full_scope_rows || []
  const values = rows.map((row) => {
    if (qualityScope.value === 'full') return row.full_rows || 0
    if (qualityScope.value === 'delta') return row.delta || 0
    return row.core_rows || 0
  })
  const label = qualityScope.value === 'full' ? 'Full rows' : qualityScope.value === 'delta' ? 'Full-core gap' : 'Core rows'
  return barOption(rows.map((row) => row.omics), values, label, true)
})

const qcGradeChart = computed(() =>
  donutOption((payload.value?.qc_grade_summary || []).map((row) => ({
    name: row.grade,
    value: row.dataset_count,
  }))),
)

const selectedQualityCellLabel = computed(() => {
  if (!selectedQualityCell.value) return 'No matrix cell selected.'
  return `${selectedQualityCell.value.omics} / ${selectedQualityCell.value.field}`
})

function formatRate(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return '-'
  return `${(n * 100).toFixed(2)}%`
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    payload.value = await getQuality()
  } catch (error) {
    payload.value = null
    loadError.value =
      error?.response?.data?.error?.message ||
      error?.response?.data?.message ||
      error?.message ||
      'Failed to load quality payload.'
  } finally {
    loading.value = false
  }
}

async function selectQualityCell(params) {
  const value = params?.data || params?.value || []
  const matrix = payload.value?.field_coverage_matrix || {}
  const field = matrix.x_labels?.[value[0]]
  const omics = matrix.y_labels?.[value[1]]
  if (!field || !omics) return
  selectedQualityCell.value = { field, omics }
  try {
    selectedCellSpecies.value = await listSpecies({ omics, has_all_omics: '' })
  } catch (error) {
    selectedCellSpecies.value = []
  }
}

onMounted(load)
</script>
