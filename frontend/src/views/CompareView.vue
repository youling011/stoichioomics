<template>
  <div class="stack-lg">
    <section class="panel">
      <div class="section-header">
        <div>
          <div class="eyebrow">Global atlas</div>
          <h3>Cross-species stoichiometric atlas and ranking panels</h3>
          <p class="muted">Select species and omics scope to build clustered fingerprint heatmaps, pairwise-distance maps, and feature-ranking views from the current PostgreSQL registry.</p>
        </div>
      </div>
      <div class="compare-control-stack">
        <div class="toolbar-grid wide">
          <div class="compare-search-box">
            <label class="control-label" for="compare-species-search">Species search</label>
            <div class="compare-search-row">
              <input id="compare-species-search" v-model="speciesSearch" class="input" type="search" placeholder="Search species ID, name, clade, or habitat" @keyup.enter="loadSpeciesCandidates" />
              <button class="btn subtle" type="button" :disabled="speciesLoading" @click="loadSpeciesCandidates">Search</button>
            </div>
          </div>
          <select v-model="omicsFocus" class="input" aria-label="Omics focus">
            <option value="">All metrics</option>
            <option value="genome">Genome-focused atlas</option>
            <option value="transcriptome">Transcript sequence-focused atlas</option>
            <option value="proteome">Proteome-focused atlas</option>
          </select>
          <select v-model="normalizationMode" class="input" aria-label="Normalization mode">
            <option value="raw">Normalization: raw</option>
            <option value="zscore">Normalization: z-score</option>
            <option value="robust_zscore">Normalization: robust z-score</option>
          </select>
          <button class="btn" :disabled="loading || selectionLimitExceeded" @click="loadCompare">Build atlas</button>
        </div>
        <div class="toolbar-grid">
          <select v-model="adjustmentMode" class="input" aria-label="Adjustment mode">
            <option value="none">Adjustment: none</option>
            <option value="length_gc_adjusted">Adjustment: length/GC aware</option>
            <option value="taxonomy_stratified">Adjustment: taxonomy stratified</option>
          </select>
          <select v-model="distanceMethod" class="input" aria-label="Distance method">
            <option value="euclidean">Distance: Euclidean</option>
            <option value="cosine">Distance: cosine</option>
            <option value="correlation">Distance: correlation</option>
          </select>
          <select v-model="groupBy" class="input" aria-label="Grouping field">
            <option value="">Grouping: none</option>
            <option value="domain">Grouping: domain</option>
            <option value="clade">Grouping: clade</option>
            <option value="habitat">Grouping: habitat</option>
          </select>
          <select v-model="rankFeature" class="input" aria-label="Ranking feature">
            <option value="">Ranking feature</option>
            <option v-for="row in (compareData?.atlas?.rankings || [])" :key="row.feature" :value="row.feature">{{ formatFeature(row.feature) }}</option>
          </select>
        </div>
        <div class="compare-picker-grid">
          <div>
            <div class="compare-picker-title">Candidate species, lightweight list</div>
            <select multiple class="input multi-select compare-candidate-select" v-model="selectedIds">
              <option v-for="species in allSpecies" :key="species.species_id" :value="species.species_id">{{ species.display_name || species.species_id }}</option>
            </select>
            <p class="annotation">Loaded {{ allSpecies.length }} candidates. Search adds a new lightweight page instead of loading the full registry.</p>
          </div>
          <div>
            <div class="compare-picker-title">Selected for this batch</div>
            <div class="compare-selected-list" aria-live="polite">
              <button v-for="species in selectedSpeciesRows" :key="species.species_id" type="button" class="compare-chip" @click="removeSpecies(species.species_id)">
                {{ species.display_name || species.species_id }} <span aria-hidden="true">?</span>
              </button>
              <p v-if="!selectedSpeciesRows.length" class="annotation">No species selected. Use the candidate list or search first.</p>
            </div>
            <div class="compare-batch-actions">
              <button class="btn subtle" type="button" @click="resetDefaultSpecies" :disabled="speciesLoading">Reset default batch</button>
              <button class="btn subtle" type="button" @click="clearSelection" :disabled="!selectedIds.length">Clear selection</button>
            </div>
            <p class="annotation">Selected {{ selectedIds.length }}/{{ COMPARE_MAX_SPECIES }}. Pairwise distance is quadratic, so large comparisons must be split into batches.</p>
          </div>
        </div>
      </div>
      <p v-if="compareData" class="annotation">{{ methodAnnotation }}</p>
      <p v-if="compareData?.atlas?.selection_policy" class="annotation">Compare policy: max {{ compareData.atlas.selection_policy.max_species_per_request }} species per request; default batch {{ compareData.atlas.selection_policy.default_species_limit }} species.</p>
      <p v-if="compareDirty && compareData" class="annotation">Controls changed. Click Build atlas to refresh; the page no longer auto-runs heavy compare requests.</p>
      <p v-if="selectionLimitExceeded" class="annotation">Selection exceeds the safe batch limit. Remove species or split the comparison.</p>
      <p v-if="compareData?.adjustment_info?.caveat" class="annotation">{{ compareData.adjustment_info.caveat }}</p>
      <p v-if="loadError" class="annotation">{{ loadError }}</p>
      <p v-else-if="loading" class="annotation">Loading compare atlas for the selected batch...</p>
      <p v-else-if="speciesLoading" class="annotation">Loading lightweight species candidates...</p>
    </section>

    <section v-if="!loading && !loadError && !compareData" class="panel">
      <p class="muted">No compare payload is available for the current selection.</p>
    </section>

    <PhylogenyInsightPanel
      v-if="compareData"
      title="Phylogeny coverage for selected species"
      subtitle="Descriptive distance charts use the selected species. PGLS uses the active subset30 branch-length tree and reports selected-species coverage separately."
      :selected-species="selectedIds"
    />

    <ResultBlock
      v-if="compareData"
      title="X0 match-quality table"
      question="Are the selected species comparable enough for fingerprint distances and cross-omics rankings?"
      :finding="compareX0Finding"
      method="Selected-species cross-omics join quality from current compare payload."
      normalization="raw row counts and match rates"
      missing-policy="available cross_omics_payload / join_summary fields"
      :n="matchQualityRows.length"
      caveat="Lower mapping coverage, higher missing fields or ID conflicts should reduce confidence in downstream distance and concordance charts."
      :downloads="compareX0Downloads"
      :empty-reason="matchQualityRows.length ? '' : 'No match-quality rows are available for the current species selection.'"
    >
      <div class="table-wrap">
        <table class="table compact-table">
          <thead>
            <tr>
              <th>Species</th>
              <th>Genome</th>
              <th>Transcript sequence</th>
              <th>Proteome</th>
              <th>Matched all three</th>
              <th>Match rate</th>
              <th>Conflicts</th>
              <th>Missing fields</th>
              <th>Scope</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in matchQualityRows" :key="row.species_id">
              <td>{{ row.display_name || row.species_id }}</td>
              <td>{{ row.genome_rows }}</td>
              <td>{{ row.transcriptome_rows }}</td>
              <td>{{ row.proteome_rows }}</td>
              <td>{{ row.matched_all_three }}</td>
              <td>{{ formatPercent(row.match_rate_all_three) }}</td>
              <td>{{ row.mapping_conflict_count || 0 }}</td>
              <td>{{ row.missing_field_count }}</td>
              <td>{{ row.data_scope }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <button class="btn subtle" style="margin-top: 10px" @click="exportMatchQualityCsv" :disabled="!matchQualityRows.length">Download CSV</button>
      <p class="annotation">This table is the X0 precondition for X7 comparison: selected species with lower match quality or more missing fields should be interpreted more cautiously.</p>
    </ResultBlock>

    <section v-if="compareData" class="grid grid-2">
      <article class="panel chart-panel">
        <div class="section-header compact">
          <div>
            <div class="eyebrow">X7 selected-species fingerprint</div>
            <h3>Species x fingerprint features</h3>
          </div>
          <button class="btn subtle" @click="exportFingerprintMatrixCsv">Download matrix</button>
        </div>
        <EChart :option="fingerprintHeatmapChart" :height="460" />
        <MethodBadge
          method="species fingerprint matrix"
          :normalization="compareData.normalization || normalizationMode"
          missing-policy="available fingerprint metrics only"
          :n="selectedIds.length"
          :n-features="compareData.atlas?.metrics?.length || ''"
        />
      </article>
      <article class="panel chart-panel">
        <div class="section-header compact">
          <div>
            <div class="eyebrow">X7 selected-species distance</div>
            <h3>Pairwise separation matrix</h3>
          </div>
          <button class="btn subtle" @click="exportDistanceMatrixCsv">Download matrix</button>
        </div>
        <EChart :option="distanceHeatmapChart" :height="460" />
        <MethodBadge
          :method="compareData.atlas?.distance_info?.method || distanceMethod"
          :normalization="compareData.normalization || normalizationMode"
          missing-policy="pairwise complete fingerprint metrics"
          :n="distancePairCount"
          :n-features="compareData.atlas?.metrics?.length || ''"
          :note="distanceConfidenceNote"
        />
      </article>
    </section>

    <section v-if="compareData" class="grid grid-2">
      <article class="panel chart-panel">
        <div class="section-header compact">
          <div>
            <div class="eyebrow">Feature ranking</div>
            <h3>{{ formatFeature(rankFeature || defaultRankFeature) }}</h3>
          </div>
          <button class="btn subtle" @click="exportRankingCsv" :disabled="!selectedRanking">Download CSV</button>
        </div>
        <EChart :option="rankingChart" :height="360" />
      </article>
      <article class="panel">
        <div class="section-header compact">
          <div>
            <div class="eyebrow">Distribution summary</div>
            <h3>Metric-level cross-species stats</h3>
          </div>
        </div>
        <div class="table-wrap">
          <table class="table compact-table">
            <thead>
              <tr>
                <th>Feature</th>
                <th>Min</th>
                <th>P25</th>
                <th>P50</th>
                <th>P75</th>
                <th>Max</th>
                <th>Mean</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in compareData.atlas.metric_distributions || []" :key="row.feature">
                <td>{{ formatFeature(row.feature) }}</td>
                <td>{{ row.min }}</td>
                <td>{{ row.p25 }}</td>
                <td>{{ row.p50 }}</td>
                <td>{{ row.p75 }}</td>
                <td>{{ row.max }}</td>
                <td>{{ row.mean }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </article>
    </section>

    <section v-if="compareData" class="grid grid-2">
      <article class="panel chart-panel">
        <div class="section-header compact">
          <div>
            <div class="eyebrow">Fingerprint radar</div>
            <h3>Integrated species summary</h3>
          </div>
        </div>
        <EChart v-if="radarEligible" :option="radarChart" :height="380" />
        <EmptyState
          v-else
          eyebrow="Radar limit"
          title="Radar view hidden by scientific guard"
          message="Radar is shown only for 2-6 species with at least three finite standardized metrics. Use heatmap, distance matrix, and parallel coordinates otherwise."
        />
      </article>
      <article class="panel chart-panel">
        <div class="section-header compact">
          <div>
            <div class="eyebrow">Feature panel</div>
            <h3>Parallel metric view</h3>
          </div>
        </div>
        <EChart :option="parallelChart" :height="380" />
      </article>
    </section>

    <section v-if="compareData" class="grid grid-2">
      <article class="panel chart-panel">
        <div class="section-header compact">
          <div>
            <div class="eyebrow">X7 selected-species ordination</div>
            <h3>Species ordination map</h3>
          </div>
          <select class="input select-inline" v-model="ordinationMode">
            <option value="umap">UMAP</option>
            <option value="pca">PCA</option>
          </select>
        </div>
        <EChart :option="ordinationChart" :height="380" />
        <MethodBadge
          :method="`${selectedOrdination.method} species ordination`"
          :normalization="compareData.normalization || normalizationMode"
          :missing-policy="compareData.atlas?.ordination?.missing_policy || 'complete fingerprint metrics from compare payload'"
          :n="selectedIds.length"
          :n-features="compareData.atlas?.metrics?.length || ''"
          :note="ordinationSummary"
          exploratory
        />
      </article>
      <article class="panel chart-panel">
        <div class="section-header compact">
          <div>
            <div class="eyebrow">X7/X8 selected-species consistency</div>
            <h3>Cross-omics consistency ranking</h3>
          </div>
        </div>
        <EChart :option="concordanceChart" :height="380" />
        <MethodBadge
          method="negative mean discordance or sign-concordance fallback"
          :normalization="compareData.normalization || normalizationMode"
          missing-policy="top_transformations when full matched residuals are unavailable"
          :n="matchQualityRows.length"
          note="Higher score means lower average discordance in the selected species set; this is descriptive rather than phylogenetic."
          exploratory
        />
      </article>
    </section>

    <section v-if="groupSummaryRows.length" class="panel">
      <div class="section-header compact">
        <div>
          <div class="eyebrow">Grouped summary</div>
          <h3>{{ groupBy || 'group' }} level means</h3>
        </div>
        <button class="btn subtle" @click="exportGroupSummaryCsv">Download CSV</button>
      </div>
      <div class="table-wrap">
        <table class="table compact-table">
          <thead>
            <tr>
              <th>Group</th>
              <th>Count</th>
              <th v-for="metric in previewGroupMetrics" :key="metric">{{ formatFeature(metric) }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in groupSummaryRows" :key="row.group">
              <td>{{ row.group }}</td>
              <td>{{ row.count }}</td>
              <td v-for="metric in previewGroupMetrics" :key="`${row.group}-${metric}`">{{ row[metric] }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section v-if="clusterRows.length" class="panel">
      <div class="section-header compact">
        <div>
          <div class="eyebrow">Species clusters</div>
          <h3>K-means cluster membership</h3>
        </div>
        <button class="btn subtle" @click="exportClustersCsv">Download CSV</button>
      </div>
      <div class="table-wrap">
        <table class="table compact-table">
          <thead>
            <tr>
              <th>Species</th>
              <th>Cluster</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in clusterRows" :key="row.species_id">
              <td>{{ row.display_name || row.species_id }}</td>
              <td>{{ row.cluster }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import EChart from '../components/EChart.vue'
import EmptyState from '../components/EmptyState.vue'
import MethodBadge from '../components/MethodBadge.vue'
import PhylogenyInsightPanel from '../components/PhylogenyInsightPanel.vue'
import ResultBlock from '../components/result/ResultBlock.vue'
import { compareSpecies, listSpecies } from '../api/stoichdb'
import { buildOrdinationOption, matrixHeatmapOption, parallelOption, radarOption, rankLollipopOption } from '../utils/charts'

const allSpecies = ref([])
const selectedIds = ref([])
const omicsFocus = ref('')
const normalizationMode = ref('robust_zscore')
const adjustmentMode = ref('none')
const distanceMethod = ref('euclidean')
const groupBy = ref('')
const rankFeature = ref('')
const ordinationMode = ref('umap')
const compareData = ref(null)
const loading = ref(false)
const speciesLoading = ref(false)
const loadError = ref('')
const speciesSearch = ref('')
const compareDirty = ref(false)
const COMPARE_DEFAULT_COUNT = 6
const COMPARE_CANDIDATE_PAGE_SIZE = 12
const COMPARE_MAX_SPECIES = 24
let compareAbortController = null

const defaultRankFeature = computed(() => compareData.value?.atlas?.rankings?.[0]?.feature || '')

const selectedRanking = computed(() => {
  const key = rankFeature.value || defaultRankFeature.value
  return (compareData.value?.atlas?.rankings || []).find((row) => row.feature === key) || null
})

const methodAnnotation = computed(() => {
  const payload = compareData.value
  if (!payload) return ''
  const norm = payload?.normalization || payload?.atlas?.normalization_info?.mode || normalizationMode.value
  const adjustment = payload?.adjustment || payload?.atlas?.adjustment_info?.mode || adjustmentMode.value
  const dist = payload?.distance_method || payload?.atlas?.distance_info?.method || distanceMethod.value
  const grouping = payload?.group_by || groupBy.value || 'none'
  return `Fingerprint chart values use "${norm}" normalization, adjustment "${adjustment}", pairwise distance "${dist}", grouping dimension: ${grouping}. Raw values remain available in ranking table fields.`
})

const compareFingerprints = computed(() => compareData.value?.fingerprints || [])
const compareMetricKeys = computed(() => compareData.value?.atlas?.metrics || [])
const compareNormalization = computed(() => compareData.value?.normalization || compareData.value?.atlas?.normalization_info?.mode || normalizationMode.value)

const radarEligible = computed(() => {
  const rows = compareFingerprints.value
  const metrics = compareMetricKeys.value.filter((key) => rows.some((row) => Number.isFinite(Number(row?.[key]))))
  return rows.length >= 2 && rows.length <= 6 && metrics.length >= 3 && !String(compareNormalization.value || '').toLowerCase().includes('raw')
})

const radarChart = computed(() => radarOption(compareFingerprints.value, {
  mode: 'normalize',
  metrics: compareMetricKeys.value,
  maxMetrics: 6,
  exportName: 'compare_standardized_fingerprint_radar',
}))

const parallelChart = computed(() =>
  parallelOption(
    compareFingerprints.value,
    compareData.value?.atlas?.metrics || ['genome_gc', 'promoter_gc', 'transcript_entropy', 'proteome_n_per_aa', 'proteome_pi'],
  ),
)

const fingerprintHeatmapChart = computed(() => {
  const payload = compareData.value?.atlas?.fingerprint_heatmap || { x_labels: [], y_labels: [], values: [] }
  const values = (payload.values || []).map((row) => Number(row?.[2])).filter((value) => Number.isFinite(value))
  const min = values.length ? Math.min(...values) : -1
  const max = values.length ? Math.max(...values) : 1
  return matrixHeatmapOption(payload.x_labels || [], payload.y_labels || [], payload.values || [], {
    min,
    max,
    scaleType: String(compareNormalization.value || '').toLowerCase().includes('z') ? 'zscore' : 'effect',
    exportName: 'compare_fingerprint_heatmap',
  })
})

const distanceHeatmapChart = computed(() => {
  const payload = compareData.value?.atlas?.distance_heatmap || { x_labels: [], y_labels: [], values: [] }
  const values = (payload.values || []).map((row) => Number(row?.[2])).filter((value) => Number.isFinite(value))
  const max = values.length ? Math.max(...values) : 1
  return matrixHeatmapOption(payload.x_labels || [], payload.y_labels || [], payload.values || [], {
    min: 0,
    max: max || 1,
    scaleType: 'distance',
    exportName: 'compare_distance_heatmap',
  })
})

const distancePairCount = computed(() => {
  const values = compareData.value?.atlas?.distance_heatmap?.values || []
  return values.filter((row) => row[0] < row[1]).length
})

const distanceConfidenceNote = computed(() => {
  const metricCount = compareData.value?.atlas?.metrics?.length || 0
  if (metricCount < 4) return 'Low confidence: fewer than four shared fingerprint metrics are available.'
  return 'Interpret distances as descriptive separation, not phylogenetic distance.'
})

const rankingChart = computed(() => {
  const rows = selectedRanking.value?.top || []
  return rankLollipopOption(
    rows.map((row) => ({ name: row.display_name, value: row.value })),
    'name',
    'value',
    formatFeature(selectedRanking.value?.feature || ''),
  )
})

const selectedOrdination = computed(() => {
  const payload = compareData.value?.atlas?.ordination || {}
  const umapPayload = payload?.umap || {}
  if (ordinationMode.value === 'umap' && (umapPayload.points || []).length) {
    return {
      method: 'UMAP',
      points: umapPayload.points || [],
      xKey: 'x',
      yKey: 'y',
      axisLabels: ['UMAP1', 'UMAP2'],
      summary: `UMAP with n_neighbors=${umapPayload?.params?.n_neighbors ?? '-'}, min_dist=${umapPayload?.params?.min_dist ?? '-'}, random_state=${umapPayload?.params?.random_state ?? '-'} on the compare fingerprint matrix.`,
    }
  }
  const ratios = payload?.explained_variance_ratio || []
  return {
    method: 'PCA',
    points: payload?.points || [],
    xKey: 'x',
    yKey: 'y',
    axisLabels: [
      ratios.length ? `PC1 (${(Number(ratios[0] || 0) * 100).toFixed(1)}%)` : 'PC1',
      ratios.length ? `PC2 (${(Number(ratios[1] || 0) * 100).toFixed(1)}%)` : 'PC2',
    ],
    summary: ratios.length
      ? `Explained variance PC1 ${(Number(ratios[0] || 0) * 100).toFixed(1)}%, PC2 ${(Number(ratios[1] || 0) * 100).toFixed(1)}%.`
      : 'Explained variance ratio is not available in this payload.',
  }
})

const ordinationChart = computed(() => {
  const points = (selectedOrdination.value?.points || []).map((row) => ({
    ...row,
    entity_id: row.display_name || row.species_id,
  }))
  return buildOrdinationOption(points, selectedOrdination.value.xKey, selectedOrdination.value.yKey, ordinationAxisLabels.value[0], ordinationAxisLabels.value[1], {
    title: 'Optional selected-species ordination',
    subtitle: `${selectedOrdination.value.summary || ''} Use the distance matrix as the primary view when few species are selected.`,
  })
})

const ordinationAxisLabels = computed(() => selectedOrdination.value?.axisLabels || ['PC1', 'PC2'])

const ordinationSummary = computed(() => selectedOrdination.value?.summary || '')

const concordanceChart = computed(() => {
  const rows = compareData.value?.atlas?.concordance_ranking || []
  return rankLollipopOption(
    rows.map((row) => ({ name: row.display_name || row.species_id, value: row.concordance_score })),
    'name',
    'value',
    'Concordance score',
  )
})

const matchQualityRows = computed(() => compareData.value?.atlas?.match_quality || [])
const groupSummaryRows = computed(() => compareData.value?.atlas?.group_summary || [])
const clusterRows = computed(() => compareData.value?.atlas?.clusters || [])
const compareX0Finding = computed(() => {
  const rows = matchQualityRows.value || []
  if (!rows.length) return 'No selected species have cross-omics match-quality rows in this payload.'
  const meanRate = rows.reduce((sum, row) => sum + (Number(row.match_rate_all_three) || 0), 0) / rows.length
  const conflicts = rows.reduce((sum, row) => sum + (Number(row.mapping_conflict_count) || 0), 0)
  return `Mean all-three match rate is ${(meanRate * 100).toFixed(2)}%; ${conflicts} mapping conflict(s) are reported across selected species.`
})
const compareX0Downloads = computed(() => [
  { label: 'Preview JSON', filename: 'compare_x0_match_quality.json', payload: { rows: matchQualityRows.value, adjustment: compareData.value?.adjustment_info } },
])

const previewGroupMetrics = computed(() => {
  const row = groupSummaryRows.value?.[0] || {}
  return Object.keys(row).filter((key) => !['group', 'count'].includes(key)).slice(0, 5)
})

const selectedSpeciesRows = computed(() => selectedIds.value.map((id) => speciesById.value.get(id) || { species_id: id, display_name: id }))
const speciesById = computed(() => new Map(allSpecies.value.map((row) => [row.species_id, row])))
const selectionLimitExceeded = computed(() => selectedIds.value.length > COMPARE_MAX_SPECIES)

function mergeSpeciesRows(rows = []) {
  const byId = new Map(allSpecies.value.map((row) => [row.species_id, row]))
  rows.forEach((row) => {
    if (row?.species_id) byId.set(row.species_id, { ...(byId.get(row.species_id) || {}), ...row })
  })
  allSpecies.value = [...byId.values()].sort((a, b) => String(a.display_name || a.species_id).localeCompare(String(b.display_name || b.species_id)))
}

function defaultComparableSpecies() {
  const eligible = allSpecies.value.filter((row) => row.default_compare_eligible !== false && !['C', 'Fail'].includes(row.qc_grade))
  return (eligible.length ? eligible : allSpecies.value).slice(0, COMPARE_DEFAULT_COUNT).map((row) => row.species_id)
}

function normalizeSpeciesPayload(payload) {
  if (Array.isArray(payload)) return payload
  return payload?.items || payload?.results || payload?.species || []
}

async function loadSpeciesCandidates() {
  speciesLoading.value = true
  loadError.value = ''
  try {
    const payload = await listSpecies({
      query: speciesSearch.value || '',
      page: 1,
      page_size: COMPARE_CANDIDATE_PAGE_SIZE,
      has_all_omics: 'true',
      compare_default: '1',
      include_aggregate: 'false',
      sort_by: 'display_name',
      sort_order: 'asc',
    })
    mergeSpeciesRows(normalizeSpeciesPayload(payload))
    if (!selectedIds.value.length) selectedIds.value = defaultComparableSpecies()
  } catch (error) {
    loadError.value = error?.response?.data?.error?.message || error?.message || 'Failed to load lightweight species candidates.'
  } finally {
    speciesLoading.value = false
  }
}

function removeSpecies(speciesId) {
  selectedIds.value = selectedIds.value.filter((id) => id !== speciesId)
  compareDirty.value = true
}

function clearSelection() {
  selectedIds.value = []
  compareDirty.value = true
}

function resetDefaultSpecies() {
  selectedIds.value = defaultComparableSpecies()
  compareDirty.value = true
}

function csvEscape(value) {
  if (value === null || value === undefined) return ''
  const text = String(value)
  if (text.includes(',') || text.includes('"') || text.includes('\n')) {
    return `"${text.replaceAll('"', '""')}"`
  }
  return text
}

function downloadCsv(filename, rows) {
  if (!rows?.length) return
  const headers = Array.from(
    rows.reduce((set, row) => {
      Object.keys(row || {}).forEach((key) => set.add(key))
      return set
    }, new Set()),
  )
  const lines = [headers.join(',')]
  rows.forEach((row) => {
    lines.push(headers.map((header) => csvEscape(row?.[header])).join(','))
  })
  const blob = new Blob([`\uFEFF${lines.join('\n')}`], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

function exportRankingCsv() {
  const ranking = selectedRanking.value
  if (!ranking) return
  const rows = [
    ...(ranking.top || []).map((row) => ({ bucket: 'top', ...row })),
    ...(ranking.bottom || []).map((row) => ({ bucket: 'bottom', ...row })),
  ]
  downloadCsv(`compare_ranking_${ranking.feature || 'feature'}.csv`, rows)
}

function matrixRows(payload) {
  const xLabels = payload?.x_labels || []
  const yLabels = payload?.y_labels || []
  return (payload?.values || []).map((item) => ({
    row: yLabels[item[1]] || item[1],
    column: xLabels[item[0]] || item[0],
    value: item[2],
  }))
}

function exportFingerprintMatrixCsv() {
  downloadCsv('compare_fingerprint_matrix.csv', matrixRows(compareData.value?.atlas?.fingerprint_heatmap || {}))
}

function exportDistanceMatrixCsv() {
  downloadCsv('compare_pairwise_distance_matrix.csv', matrixRows(compareData.value?.atlas?.distance_heatmap || {}))
}

function exportGroupSummaryCsv() {
  downloadCsv(`compare_group_summary_${groupBy.value || 'none'}.csv`, groupSummaryRows.value || [])
}

function exportClustersCsv() {
  downloadCsv('compare_clusters.csv', clusterRows.value || [])
}

function formatFeature(key) {
  return String(key || '').replaceAll('_', ' ')
}

function formatPercent(value) {
  const num = Number(value)
  if (!Number.isFinite(num)) return ''
  return `${(num * 100).toFixed(2)}%`
}

function exportMatchQualityCsv() {
  downloadCsv('compare_x0_match_quality.csv', matchQualityRows.value || [])
}

const loadCompare = async () => {
  if (!selectedIds.value.length && allSpecies.value.length) selectedIds.value = defaultComparableSpecies()
  if (!selectedIds.value.length) {
    compareData.value = null
    rankFeature.value = ''
    loadError.value = 'Select at least one species before building the atlas.'
    return
  }
  if (selectionLimitExceeded.value) {
    loadError.value = `Compare supports at most ${COMPARE_MAX_SPECIES} species per batch.`
    return
  }

  if (compareAbortController) compareAbortController.abort()
  compareAbortController = new AbortController()
  const controller = compareAbortController
  loading.value = true
  loadError.value = ''
  try {
    compareData.value = await compareSpecies(selectedIds.value, {
      omics: omicsFocus.value,
      normalization: normalizationMode.value,
      adjustment: adjustmentMode.value,
      distance: distanceMethod.value,
      group_by: groupBy.value,
    }, { signal: controller.signal })
    compareDirty.value = false
    const rankings = compareData.value?.atlas?.rankings || []
    if (!rankings.length) {
      rankFeature.value = ''
      return
    }
    if (!rankFeature.value || !rankings.some((row) => row.feature === rankFeature.value)) rankFeature.value = rankings[0].feature
  } catch (error) {
    if (error?.code === 'ERR_CANCELED' || error?.name === 'CanceledError') return
    compareData.value = null
    loadError.value =
      error?.response?.data?.error?.message ||
      error?.response?.data?.message ||
      error?.message ||
      'Failed to load compare atlas payload.'
  } finally {
    if (controller === compareAbortController) loading.value = false
  }
}

watch([selectedIds, omicsFocus, normalizationMode, adjustmentMode, distanceMethod, groupBy], () => {
  if (compareData.value) compareDirty.value = true
}, { deep: true })

onMounted(async () => {
  await loadSpeciesCandidates()
  if (selectedIds.value.length) await loadCompare()
})
</script>
