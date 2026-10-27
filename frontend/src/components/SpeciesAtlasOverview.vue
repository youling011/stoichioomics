<template>
  <section class="atlas-overview stack-lg">
    <ModuleState
      v-if="loading"
      state="loading"
      title="Loading Species Atlas"
      message="Computing registry-wide coverage, genome-size distributions, and Core completeness summaries."
    />
    <ModuleState
      v-else-if="error"
      state="error"
      title="Atlas summary unavailable"
      :message="error"
      suggestion="Retry the atlas summary request. The species filters and registry list remain available."
      :retry="() => emit('retry')"
    />
    <template v-else-if="payload">
      <div class="atlas-main-grid">
        <article class="panel atlas-large-card"><div class="atlas-card-frame">
<div class="atlas-size-budget" aria-hidden="true" inert>
          <div class="atlas-card-header">
            <div>
              <h3>Domain x Omics Coverage Overview <span class="atlas-info">i</span></h3>
              <p class="muted">Coverage of core features across domains and omics layers <button class="atlas-link" type="button">How to read this?</button></p>
            </div>
            <div class="atlas-toggle" role="tablist" aria-label="Coverage display mode">
              <button :class="{ active: coverageMode === 'pct' }" type="button" @click="coverageMode = 'pct'">% Coverage</button>
              <button :class="{ active: coverageMode === 'count' }" type="button" @click="coverageMode = 'count'">Record Count</button>
            </div>
          </div>
          <div class="atlas-coverage-table">
            <div class="atlas-coverage-head domain-col">Domain <span>(Phylum-level)</span></div>
            <div class="atlas-coverage-head" v-for="omicsKey in omicsKeys" :key="omicsKey">
              <div>{{ omicsLabel(omicsKey) }}</div>
              <span>({{ coreFieldCount(omicsKey) }} features)</span>
            </div>
            <div class="atlas-coverage-head">Overall<br><span>Coverage (3 omics)</span></div>
            <template v-for="row in coverageRows" :key="row.domain">
              <div class="atlas-domain-cell">
                <span class="atlas-domain-dot" :style="{ background: domainColor(row.domain) }"></span>
                <strong>{{ row.domain }}</strong>
                <span>({{ formatInt(row.species_count) }})</span>
              </div>
              <button
                v-for="omicsKey in omicsKeys"
                :key="`${row.domain}-${omicsKey}`"
                type="button"
                class="atlas-heat-cell"
                :style="{ background: heatColor(cellValue(row, omicsKey), coverageMode) }"
                :title="coverageCellTitle(row, omicsKey)"
                :aria-label="coverageCellTitle(row, omicsKey)"
                @click="$emit('coverage-cell-click', { domain: row.domain === 'All Domains' ? '' : row.domain, omics: omicsKey, allThree: false })"
              >
                <span class="sr-only">{{ formatCell(row, omicsKey) }}</span>
              </button>
              <button
                type="button"
                class="atlas-overall-cell"
                :title="overallCellTitle(row)"
                :aria-label="overallCellTitle(row)"
                @click="$emit('coverage-cell-click', { domain: row.domain === 'All Domains' ? '' : row.domain, omics: '', allThree: true })"
              >
                <strong>{{ formatPct(row.all_three?.coverage_pct) }}</strong>
                <span class="atlas-progress"><i :style="{ width: progressWidth(row.all_three?.coverage_pct) }"></i></span>
              </button>
            </template>
          </div>
          <div class="atlas-legend-row">
            <div class="atlas-gradient-legend" :class="coverageMode">
              <span>{{ coverageMode === 'pct' ? 'Coverage (%)' : 'Count' }}</span>
              <i></i>
              <small>{{ coverageMode === 'pct' ? '0' : '0' }}</small>
              <small>{{ coverageMode === 'pct' ? '25' : '' }}</small>
              <small>{{ coverageMode === 'pct' ? '50' : formatInt(maxCoverageCount / 2) }}</small>
              <small>{{ coverageMode === 'pct' ? '75' : '' }}</small>
              <small>{{ coverageMode === 'pct' ? '100' : formatInt(maxCoverageCount) }}</small>
            </div>
            <div class="atlas-updated">Last updated: {{ formatDate(budgetPayload.meta?.generated_at) }} <span>-</span></div>
          </div>
          <div class="atlas-info-strip">Coverage (%) = Species with available core features / Total species in domain. Click a cell to view species list.</div>
        </div>
<HomeAtlasCard id="D1" :card="payload.cards.D1" :meta="payload.meta" v-model:coverageMode="visualCoverageMode" v-model:genomeMode="visualGenomeMode" :retry="() => emit('retry')" @coverage-cell-click="emit('coverage-cell-click', $event)" />
</div></article>

        <article class="panel atlas-large-card"><div class="atlas-card-frame">
<div class="atlas-size-budget" aria-hidden="true" inert>
          <div class="atlas-card-header">
            <div>
              <h3>Genome Size Distribution by Domain <span class="atlas-info">i</span></h3>
              <p class="muted">Distribution of genome sizes (Mb) for species in each domain</p>
            </div>
            <div class="atlas-toggle" role="tablist" aria-label="Genome distribution display mode">
              <button :class="{ active: genomeMode === 'box' }" type="button" @click="genomeMode = 'box'">Box Plot</button>
              <button :class="{ active: genomeMode === 'violin' }" type="button" @click="genomeMode = 'violin'">Violin Plot</button>
            </div>
          </div>
          <div class="atlas-genome-layout">
            <div class="atlas-genome-chart">
              <div class="echart-shell"><div class="chart-host" style="height:320px"></div></div>
            </div>
            <div class="atlas-species-counts">
              <strong>Species<br>Count</strong>
              <span v-for="row in genomeRows" :key="row.domain">{{ formatInt(row.n || 0) }}</span>
            </div>
          </div>
          <div class="atlas-box-explain">
            <div class="atlas-mini-box" aria-hidden="true">
              <svg viewBox="0 0 150 68">
                <line x1="18" y1="34" x2="132" y2="34" />
                <line x1="18" y1="26" x2="18" y2="42" />
                <line x1="132" y1="26" x2="132" y2="42" />
                <rect x="52" y="20" width="52" height="28" />
                <line x1="76" y1="20" x2="76" y2="48" class="median" />
              </svg>
            </div>
            <div class="atlas-box-copy">
              <span>Box: 25% ~ 75% (IQR)</span>
              <span>Line: Median</span>
              <span>Whisker: 1.5 x IQR</span>
              <span>Dots: Outliers</span>
            </div>
            <div class="atlas-median-list">
              <strong>Domain Median (Mb)</strong>
              <span v-for="row in genomeRows.slice(0, 6)" :key="`median-${row.domain}`">
                <i :style="{ background: domainColor(row.domain) }"></i>{{ row.domain }} <b>{{ formatNumber(row.median, 4) }}</b>
              </span>
            </div>
          </div>
          <div class="atlas-info-strip">Genome sizes depend on assembly quality and annotation completeness.</div>
        </div>
<HomeAtlasCard id="D2" :card="payload.cards.D2" :meta="payload.meta" v-model:coverageMode="visualCoverageMode" v-model:genomeMode="visualGenomeMode" :retry="() => emit('retry')" @coverage-cell-click="emit('coverage-cell-click', $event)" />
</div></article>
      </div>

      <div class="atlas-secondary-grid">
        <article class="panel atlas-secondary-card"><div class="atlas-card-frame">
<div class="atlas-size-budget" aria-hidden="true" inert>
          <h3>Omics Data Availability (All Domains)</h3>
          <div class="atlas-donut-layout">
            <div class="atlas-donut-wrap">
              <div class="echart-shell"><div class="chart-host" style="height:320px"></div></div>
              <div class="atlas-donut-center"><strong>Total<br>{{ formatInt(totalSpecies) }}</strong><span>species</span></div>
            </div>
            <div class="atlas-availability-legend">
              <button v-for="item in availabilityRows" :key="item.key" type="button" @click="highlightAvailability = highlightAvailability === item.key ? '' : item.key" :class="{ dimmed: highlightAvailability && highlightAvailability !== item.key }">
                <i :style="{ background: item.color }"></i>
                <span>{{ item.label }}</span>
                <strong>{{ formatInt(item.value) }} ({{ formatPct(item.pct) }})</strong>
              </button>
            </div>
          </div>
        </div>
<HomeAtlasCard id="D3" :card="payload.cards.D3" :meta="payload.meta" v-model:coverageMode="visualCoverageMode" v-model:genomeMode="visualGenomeMode" :retry="() => emit('retry')" @coverage-cell-click="emit('coverage-cell-click', $event)" />
</div></article>

        <article class="panel atlas-secondary-card"><div class="atlas-card-frame">
<div class="atlas-size-budget" aria-hidden="true" inert>
          <h3>Average Core Feature Completeness</h3>
          <div class="atlas-rings-wrap">
            <div class="echart-shell"><div class="chart-host" style="height:320px"></div></div>
            <div class="atlas-ring-labels">
              <div v-for="omicsKey in omicsKeys" :key="omicsKey">
                <strong>{{ formatPct(completeness[omicsKey]?.pct) }}</strong>
                <span>{{ omicsLabel(omicsKey) }}</span>
                <small>({{ coreFieldCount(omicsKey) }} features)</small>
              </div>
            </div>
          </div>
        </div>
<HomeAtlasCard id="D4" :card="payload.cards.D4" :meta="payload.meta" v-model:coverageMode="visualCoverageMode" v-model:genomeMode="visualGenomeMode" :retry="() => emit('retry')" @coverage-cell-click="emit('coverage-cell-click', $event)" />
</div></article>

        <article class="panel atlas-secondary-card atlas-top-table-card"><div class="atlas-card-frame">
<div class="atlas-size-budget" aria-hidden="true" inert>
          <h3>Model Species Data Completeness (All 3 Omics)</h3>
          <div class="table-wrap atlas-table-wrap" style="height:300px"></div>
</div>
<HomeAtlasCard id="D5" :card="payload.cards.D5" :meta="payload.meta" v-model:coverageMode="visualCoverageMode" v-model:genomeMode="visualGenomeMode" :retry="() => emit('retry')" @coverage-cell-click="emit('coverage-cell-click', $event)" />
</div></article>
      </div>

      <div class="atlas-tip-strip">
        <span class="atlas-tip-icon">i</span>
        <strong>Tips:</strong>
        Use filters above to explore specific domains or feature ranges. Click any coverage cell to drill down into species lists and details.
      </div>
    </template>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'
import EChart from './EChart.vue'
import ModuleState from './ModuleState.vue'
import HomeAtlasCard from './HomeAtlasCard.vue'

const props = defineProps({
  payload: { type: Object, default: null },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
})
const emit = defineEmits(['coverage-cell-click', 'retry'])

const visualCoverageMode = ref('count'), visualGenomeMode = ref('violin')
const coverageMode = ref('pct')
const genomeMode = ref('box')
const highlightAvailability = ref('')
const omicsKeys = ['genome', 'transcriptome', 'proteome']

// These values size the old responsive typography only. They are inert/aria-hidden,
// never exported, and are not used in any new scientific calculation.
const budgetPayload = computed(() => {
  const p = props.payload, cards = p?.cards || {}, d1 = cards.D1?.data, d3 = cards.D3?.data
  const make = r => ({ domain: r.group || 'All Domains', species_count: r.species_count,
    ...Object.fromEntries(omicsKeys.map(m => [m, { available:r.layers[m].ready_species, coverage_pct:r.layers[m].coverage_pct, core_feature_count:p?.meta?.legacy_layout_field_counts?.[m] || 0 }])),
    all_three: { available:0, coverage_pct:100 } })
  const counts = Object.fromEntries((d3?.core_ready_counts || []).map(x => [x.n_ready_layers,x.n_species]))
  return { meta:{...p?.meta,species_total:cards.D1?.n_source || 0},
    domain_omics_coverage:{rows:(d1?.rows || []).map(make),all_domains:d1 ? make(d1.all_groups) : null},
    genome_size_distribution:(cards.D2?.data.groups || []).map(r => ({domain:r.group,n:r.n_valid,median:r.median_mb})),
    omics_availability:{all_3:counts[3] || 0,two_omics:counts[2] || 0,one_omic:counts[1] || 0,no_omics:counts[0] || 0},
    core_feature_completeness:Object.fromEntries(omicsKeys.map(m => [m,{pct:100,field_count:p?.meta?.legacy_layout_field_counts?.[m] || 0}])),
    top_species_completeness:[] }
})

const domainPalette = {
  Bacteria: '#2FBF9B',
  Fungi: '#F39A18',
  Metazoa: '#7C5CE5',
  Plants: '#54B96B',
  Protists: '#19B6C8',
  Vertebrates: '#3D7FE6',
  Unclassified: '#94A3B8',
  'All Domains': '#1F5D9A',
}

const coverageRows = computed(() => {
  const rows = budgetPayload.value?.domain_omics_coverage?.rows || []
  const all = budgetPayload.value?.domain_omics_coverage?.all_domains
  return all ? [...rows, all] : rows
})
const genomeRows = computed(() => budgetPayload.value?.genome_size_distribution || [])
const totalSpecies = computed(() => Number(budgetPayload.value?.meta?.species_total || budgetPayload.value?.domain_omics_coverage?.all_domains?.species_count || 0))
const completeness = computed(() => budgetPayload.value?.core_feature_completeness || {})
const topSpecies = computed(() => budgetPayload.value?.top_species_completeness || [])
const maxCoverageCount = computed(() => Math.max(1, ...coverageRows.value.flatMap((row) => omicsKeys.map((key) => Number(row?.[key]?.available || 0)))))
const availabilityRows = computed(() => {
  const data = budgetPayload.value?.omics_availability || {}
  const rows = [
    { key: 'all_3', label: 'All 3 omics', value: Number(data.all_3 || 0), color: '#48C9A5' },
    { key: 'two_omics', label: '2 omics', value: Number(data.two_omics || 0), color: '#3D8AF5' },
    { key: 'one_omics', label: '1 omic', value: Number(data.one_omics || 0), color: '#F59E0B' },
    { key: 'no_omics', label: 'No omics', value: Number(data.no_omics || 0), color: '#F04452' },
  ]
  return rows.map((row) => ({ ...row, pct: totalSpecies.value ? (row.value * 100 / totalSpecies.value) : 0 }))
})

function omicsLabel(key) {
  return { genome: 'Genome', transcriptome: 'Transcriptome', proteome: 'Proteome' }[key] || key
}

function coreFieldCount(key) {
  const all = budgetPayload.value?.domain_omics_coverage?.all_domains || {}
  return Number(all?.[key]?.core_feature_count || completeness.value?.[key]?.field_count || 0)
}

function domainColor(domain) {
  return domainPalette[domain] || '#94A3B8'
}

function cellValue(row, omicsKey) {
  return coverageMode.value === 'pct' ? Number(row?.[omicsKey]?.coverage_pct || 0) : Number(row?.[omicsKey]?.available || 0)
}

function heatColor(value, mode) {
  const n = Number(value)
  if (!Number.isFinite(n)) return 'rgba(148,163,184,0.14)'
  if (mode === 'count') {
    const t = Math.max(0, Math.min(1, n / maxCoverageCount.value))
    return `rgba(${Math.round(231 - t * 190)}, ${Math.round(244 - t * 88)}, ${Math.round(255 - t * 111)}, ${0.72 + t * 0.2})`
  }
  if (n >= 95) return 'rgba(99, 215, 129, 0.52)'
  if (n >= 80) return 'rgba(178, 229, 139, 0.52)'
  if (n >= 60) return 'rgba(252, 219, 94, 0.52)'
  if (n >= 35) return 'rgba(249, 151, 61, 0.44)'
  return 'rgba(244, 72, 84, 0.38)'
}

function formatCell(row, omicsKey) {
  const item = row?.[omicsKey] || {}
  return coverageMode.value === 'pct' ? formatPct(item.coverage_pct) : formatInt(item.available || 0)
}

function coverageCellTitle(row, omicsKey) {
  const value = formatCell(row, omicsKey)
  return `${row?.domain || 'Domain'} ${omicsLabel(omicsKey)} ${coverageMode.value === 'pct' ? 'coverage' : 'records'}: ${value}`
}

function overallCellTitle(row) {
  const value = formatPct(row?.all_three?.coverage_pct)
  const count = formatInt(row?.all_three?.available || 0)
  return `${row?.domain || 'Domain'} all-three-omics coverage: ${value} (${count} species)`
}

function formatPct(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return '-'
  if (Math.abs(n - 100) < 0.05) return '100%'
  return `${n.toFixed(1)}%`
}

function formatNumber(value, digits = 2) {
  const n = Number(value)
  if (!Number.isFinite(n)) return '-'
  return n.toLocaleString(undefined, { maximumFractionDigits: digits })
}

function formatInt(value) {
  return Number(value || 0).toLocaleString()
}

function progressWidth(value) {
  const n = Math.max(0, Math.min(100, Number(value || 0)))
  return `${n}%`
}

function formatDate(value) {
  if (!value) return 'not registered'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toISOString().slice(0, 16).replace('T', ' ')
}
</script>



<style scoped>
.atlas-card-frame { position:relative; }
.atlas-size-budget { visibility:hidden;pointer-events:none;user-select:none; }
</style>
