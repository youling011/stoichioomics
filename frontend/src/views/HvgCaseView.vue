<template>
  <div>
    <div class="card">
      <div class="section-header">
        <div>
          <div class="eyebrow">Expression/HVG Stoich Extension</div>
          <h1>{{ isModel8Case5 ? model8Case5Title : `Expression/HVG case / ${identifier}` }}</h1>
          <p class="muted">{{ isModel8Case5 ? 'Published eight-model-organism HVG consensus, stoichiometric model evidence, candidate genes, enrichment, and release downloads rendered through the HVG workflow modules.' : 'Traceable expression-matrix and metadata workflow results linked to stoichiometric evidence, context patterns, model checks, candidate genes, and reusable files.' }}</p>
        </div>
        <div class="row">
          <router-link v-if="isModel8Case5" class="btn secondary" :to="model8Case5BackRoute">Case studies</router-link>
          <a v-if="isModel8Case5" class="btn secondary" :href="model8PlatformBundleDownloadUrl()">Bundle</a>
          <span v-for="badge in statusBadges.slice(0, 3)" :key="badge.code" class="badge" :class="badgeClass(badge.severity)">
            {{ badge.code }}
          </span>
        </div>
      </div>
    </div>

    <div class="hvg-tabbar" aria-label="HVG result sections">
      <a
        v-for="item in tabs"
        :key="item.key"
        href="#"
        class="hvg-tab"
        :class="{active:tab===item.key, skipped: tabState(item.key) === 'Skipped'}"
        @click.prevent="selectTab(item.key)"
      >
        <span class="hvg-tab-index">{{ item.index }}</span>
        <span class="hvg-tab-copy">
          <span class="hvg-tab-label">{{ item.label }}</span>
          <span class="hvg-tab-note">{{ item.note }}</span>
        </span>
        <span class="hvg-tab-state">{{ tabState(item.key) }}</span>
      </a>
    </div>
    <div class="hvg-active-strip">
      <span>{{ activeTabMeta.index }} / {{ tabs.length }}</span>
      <strong>{{ activeTabMeta.label }}</strong>
      <small>{{ activeTabMeta.note }}</small>
    </div>

    <div class="card muted">
      Input boundary: this extension starts from an expression matrix plus sample or cell metadata and then maps gene IDs
      to stoichiometric feature context. It is separate from the core transcript sequence database modules.
    </div>
    <div v-if="isModel8Case5 && tab === 'overview'" class="card muted">
      Curated workflow case: the page is populated from generated Model-8 Case 5 artifacts under
      <code>data/case_studies/model8/case5_hvg_stoich</code>, including phase1.json, phase2.json,
      downstream.json, hvg_consensus.csv, candidate_genes.csv, and enrichment_results.csv.
    </div>
    <section v-if="isModel8Case5 && tab === 'overview'" class="card species-workbench">
      <div class="section-header compact">
        <div>
          <h3>{{ model8Case5SpeciesCode ? `${model8Case5SpeciesCode} HVG-Stoich result workbench` : 'Species HVG-Stoich result workbench' }}</h3>
          <p class="muted">{{ model8Case5SpeciesCode ? 'This workflow page is scoped to the selected species case-study result.' : 'Switch species to inspect real HVG consensus rows, B0-B3 block-model evidence, joined stoichiometric features, candidate genes, and downstream tables.' }}</p>
        </div>
        <router-link class="btn secondary" :to="model8Case5BackRoute">Back to case studies</router-link>
      </div>
      <div v-if="!model8Case5SpeciesCode" class="case-tab-row species-tabs" role="tablist" aria-label="Case 5 species detail">
        <button v-for="code in model8SpeciesCodes" :key="`hvg-case5-${code}`" type="button" :class="['case-tab', { active: selectedModel8Case5Species === code }]" @click="loadModel8Case5Species(code)">{{ code }}</button>
      </div>
      <div v-if="model8Case5SpeciesLoading" class="muted">Loading {{ selectedModel8Case5Species }} HVG-Stoich rows...</div>
      <div v-else-if="model8Case5SpeciesError" class="muted">{{ model8Case5SpeciesError }}</div>
      <template v-else-if="model8Case5Species">
        <div class="grid grid-4">
          <div class="mini-card"><div class="label">Phase 2 mode</div><div class="kpi small-kpi">{{ model8Case5Species.species_status?.phase2_mode || model8Case5Species.species_status?.phase2_status }}</div></div>
          <div class="mini-card"><div class="label">Genes profiled</div><div class="kpi">{{ formatCell(model8Case5Species.kpis?.genes_profiled) }}</div></div>
          <div class="mini-card"><div class="label">Mapped genes</div><div class="kpi">{{ formatCell(model8Case5Species.kpis?.mapped_genes) }}</div></div>
          <div class="mini-card"><div class="label">Mapping rate</div><div class="kpi">{{ percent(model8Case5Species.kpis?.mapping_rate) }}</div></div>
        </div>
        <div class="row compact-top">
          <a class="btn secondary" :href="model8Case5Species.downloads?.joined_hvg_stoich">Joined HVG-Stoich</a>
          <a class="btn secondary" :href="model8Case5Species.downloads?.hvg_consensus">HVG consensus</a>
          <a class="btn secondary" :href="model8Case5Species.downloads?.candidate_genes">Candidate genes</a>
          <a class="btn secondary" :href="model8Case5Species.downloads?.enrichment_results">Enrichment</a>
        </div>
        <div class="grid grid-2 compact-top">
          <div class="table-wrap"><h3>Top HVG consensus</h3><table class="table compact-table"><thead><tr><th v-for="col in tableColumns(model8Case5Species.tables?.top_hvg_consensus?.rows)" :key="col">{{ col }}</th></tr></thead><tbody><tr v-for="(row, idx) in compactRows(model8Case5Species.tables?.top_hvg_consensus?.rows)" :key="`hvg-top-${idx}`"><td v-for="col in tableColumns(model8Case5Species.tables?.top_hvg_consensus?.rows)" :key="col">{{ formatCell(row[col]) }}</td></tr></tbody></table></div>
          <div class="table-wrap"><h3>B0-B3 block-model comparison</h3><table class="table compact-table"><thead><tr><th v-for="col in tableColumns(model8Case5Species.tables?.model_comparison?.rows)" :key="col">{{ col }}</th></tr></thead><tbody><tr v-for="(row, idx) in compactRows(model8Case5Species.tables?.model_comparison?.rows)" :key="`hvg-model-${idx}`"><td v-for="col in tableColumns(model8Case5Species.tables?.model_comparison?.rows)" :key="col">{{ formatCell(row[col]) }}</td></tr></tbody></table></div>
        </div>
        <div class="grid grid-2 compact-top">
          <div class="table-wrap"><h3>Candidate genes</h3><table class="table compact-table"><thead><tr><th v-for="col in tableColumns(model8Case5Species.tables?.candidate_genes?.rows)" :key="col">{{ col }}</th></tr></thead><tbody><tr v-for="(row, idx) in compactRows(model8Case5Species.tables?.candidate_genes?.rows)" :key="`hvg-candidate-${idx}`"><td v-for="col in tableColumns(model8Case5Species.tables?.candidate_genes?.rows)" :key="col">{{ formatCell(row[col]) }}</td></tr></tbody></table></div>
          <div class="table-wrap"><h3>Joined HVG-Stoich rows</h3><table class="table compact-table"><thead><tr><th v-for="col in tableColumns(model8Case5Species.tables?.joined_hvg_stoich?.rows)" :key="col">{{ col }}</th></tr></thead><tbody><tr v-for="(row, idx) in compactRows(model8Case5Species.tables?.joined_hvg_stoich?.rows)" :key="`hvg-joined-${idx}`"><td v-for="col in tableColumns(model8Case5Species.tables?.joined_hvg_stoich?.rows)" :key="col">{{ formatCell(row[col]) }}</td></tr></tbody></table></div>
        </div>
        <div class="grid grid-2 compact-top">
          <div class="table-wrap"><h3>Model feature summaries</h3><table class="table compact-table"><thead><tr><th v-for="col in tableColumns(model8Case5Species.tables?.feature_summary?.rows)" :key="col">{{ col }}</th></tr></thead><tbody><tr v-for="(row, idx) in compactRows(model8Case5Species.tables?.feature_summary?.rows)" :key="`hvg-feature-${idx}`"><td v-for="col in tableColumns(model8Case5Species.tables?.feature_summary?.rows)" :key="col">{{ formatCell(row[col]) }}</td></tr></tbody></table></div>
          <div class="table-wrap"><h3>Enrichment results</h3><table class="table compact-table"><thead><tr><th v-for="col in tableColumns(model8Case5Species.tables?.enrichment_results?.rows)" :key="col">{{ col }}</th></tr></thead><tbody><tr v-for="(row, idx) in compactRows(model8Case5Species.tables?.enrichment_results?.rows)" :key="`hvg-enrich-${idx}`"><td v-for="col in tableColumns(model8Case5Species.tables?.enrichment_results?.rows)" :key="col">{{ formatCell(row[col]) }}</td></tr></tbody></table></div>
        </div>
      </template>
    </section>

    <section v-if="summary && (!isModel8Case5 || tab === 'overview')" class="result-block">
      <div class="result-block-header">
        <div>
          <div class="result-question">Can this HVG case support stoich-linked interpretation?</div>
          <h3>Case result workbench</h3>
          <p class="result-finding">{{ hvgWorkbenchFinding }}</p>
        </div>
      </div>
      <div class="grid grid-3">
        <div class="mini-card">
          <div class="label">Input matrix</div>
          <div class="metric-inline">{{ hvgInputSummary }}</div>
        </div>
        <div class="mini-card">
          <div class="label">Metadata completeness</div>
          <div class="metric-inline">{{ hvgMetadataSummary }}</div>
        </div>
        <div class="mini-card">
          <div class="label">Model caveat</div>
          <p class="muted">{{ hvgModelCaveat }}</p>
        </div>
      </div>
    </section>

    <div v-if="loading" class="card"><p>Loading case outputs...</p></div>
    <div v-if="loadError" class="card"><p class="error-text">{{ loadError }}</p></div>

    <template v-if="!loading && !loadError && summary">
      <section v-if="tab==='overview'" class="stack-lg">
        <div class="grid grid-5">
          <div v-for="card in overviewCards" :key="card.key" class="summary-card">
            <span>{{ card.label }}</span>
            <strong>{{ formatCard(card) }}</strong>
            <small>{{ card.status }}</small>
          </div>
        </div>
        <div class="grid grid-2">
          <Panel title="Workflow status" note="Input, QC, Phase 1, Phase 2, and downstream availability are shown as task states.">
            <EChart :option="workflowOption" :height="340" />
            <Interpretation :items="overview?.interpretation_text || ['Use this panel to verify which result layers are available before interpreting model outputs.']" />
          </Panel>
          <Panel title="Analysis overview table" note="One-row audit summary for the current case.">
            <DataTable :rows="tableRows('analysis_overview_table')" />
          </Panel>
        </div>
      </section>

      <section v-if="tab==='input_qc'" class="stack-lg">
        <div class="grid grid-2">
          <Panel title="Matrix QC summary" note="Counts, matrix semantics, and readiness state from validation outputs.">
            <DataTable :rows="matrixQcRows" />
          </Panel>
          <Panel title="ID mapping quality" note="Matched, unmatched, and conflicted gene IDs determine Phase 2 reliability.">
            <EChart :option="idMappingDonut" :height="330" />
            <DataTable :rows="tableRows('id_mapping_summary_table')" />
          </Panel>
        </div>
        <div class="grid grid-2">
          <Panel title="Metadata availability" note="Missing metadata narrows context analysis but does not invalidate global HVG results.">
            <DataTable :rows="metadataAvailabilityRows" />
          </Panel>
          <Panel title="Mapping conflicts" note="Conflicts and unmatched IDs are audit items for downstream interpretation.">
            <DataTable :rows="tableRows('mapping_conflicts_top_table')" />
          </Panel>
        </div>
      </section>

      <section v-if="tab==='phase1'" class="stack-lg">
        <div class="grid grid-2">
          <Panel title="Mean expression vs normalized HVG score" note="HVGs are highlighted in the primary Phase 1 scatter.">
            <EChart :option="phase1Scatter" :height="420" />
            <Interpretation :items="['Genes with higher method-specific HVG scores and low rank are prioritized as HVGs.', 'The current method and n_top_genes are recorded in Phase 1 summary.']" />
          </Panel>
          <Panel title="Top HVG ranking" note="Top genes are sorted by hvg_rank.">
            <EChart :option="topHvgOption" :height="420" />
          </Panel>
        </div>
        <div class="grid grid-2">
          <Panel title="Detection vs dropout" note="Detection-rate diagnostics help separate biological variability from sparse observation.">
            <EChart :option="dropoutScatter" :height="360" />
          </Panel>
          <Panel title="Backend and method status" note="Single-backend runs still show unavailable or disabled backends explicitly.">
            <DataTable :rows="tableRows('backend_status_table')" />
          </Panel>
        </div>
        <Panel title="Top HVG table" note="Download source: hvg_baseline_top_table.csv.">
          <DataTable :rows="tableRows('hvg_baseline_top_table')" />
        </Panel>
      </section>

      <section v-if="tab==='context_patterns'" class="stack-lg">
        <SkippedPanel v-if="!hasContextPatterns" title="No context-specific pattern panel available" reason="No usable condition, timepoint, group, sample, or trajectory field was available, or only global_hvg was run." />
        <div v-else class="grid grid-2">
          <Panel title="Pattern count summary" note="Context mode counts are shown when metadata unlocks condition, timecourse, group, sample, or trajectory analyses.">
            <EChart :option="patternCountsOption" :height="360" />
          </Panel>
          <Panel title="Subset HVG counts" note="Each subset reports n_cells, n_genes, and n_hvgs.">
            <DataTable :rows="phase1.subset_summaries || []" />
          </Panel>
        </div>
        <Panel title="Auxiliary mode outputs" note="Available auxiliary modes are listed with their generated files or skipped reasons.">
          <DataTable :rows="auxiliaryModeRows" />
        </Panel>
      </section>

      <section v-if="tab==='group_comparison'" class="stack-lg">
        <HvgGroupComparisonPanel
          :identifier="identifier"
          :is-case5="isModel8Case5"
          :case5-comparison="model8Case5Species?.group_comparison || null"
        />
      </section>

      <section v-if="tab==='phase2'" class="stack-lg">
        <SkippedPanel v-if="phase2.phase2_status === 'skipped'" title="Phase 2 was skipped" :reason="phase2.phase2_skip_reason?.reason_message || phase2.phase2_skip_reason?.message || 'Stoich inputs were not sufficient for Phase 2.'" />
        <template v-else>
          <div class="grid grid-2">
            <Panel title="Stoich class distribution" note="Class colors and order are fixed across the HVG module.">
              <EChart :option="classBar" :height="360" @chart-click="filterByClass" />
              <DataTable :rows="tableRows('hvg_stoich_class_table')" />
            </Panel>
            <Panel title="Observed vs expected HVG signal" note="The identity line marks agreement between observed HVG signal and stoich expectation.">
              <EChart :option="expObs" :height="360" />
            </Panel>
          </div>
          <div class="grid grid-2">
            <Panel title="Residual distribution" note="Positive residuals identify genes with higher-than-expected HVG signal.">
              <EChart :option="residualHistogram" :height="360" />
            </Panel>
            <Panel title="Feature association forest" note="Effect direction, FDR, and evidence level are shown together.">
              <EChart :option="featureForest" :height="360" />
            </Panel>
          </div>
          <Panel title="Signal and residual table" note="Download source: signal_residual_table.csv.">
            <DataTable :rows="tableRows('signal_residual_table')" />
          </Panel>
        </template>
      </section>

      <section v-if="tab==='model_evidence'" class="stack-lg">
        <SkippedPanel v-if="phase2.phase2_status === 'skipped'" title="Model evidence unavailable" :reason="phase2.phase2_skip_reason?.reason_message || 'Phase 2 did not run.'" />
        <template v-else>
          <div class="grid grid-2">
            <Panel title="Generic-M0/M1/M2/M3 comparison" note="Generic workflow models compare intercept-only, confounders, stoich-augmented, and interaction or nonlinear features.">
              <EChart :option="modelComparisonOption" :height="360" />
              <DataTable :rows="tableRows('model_comparison_table')" />
            </Panel>
            <Panel title="Bootstrap feature stability" note="Stable features are more reliable candidates than single-fit coefficients.">
              <EChart :option="bootstrapOption" :height="360" />
              <DataTable :rows="tableRows('bootstrap_feature_stability_table')" />
            </Panel>
          </div>
          <div class="grid grid-2">
            <Panel title="Evidence assessment" note="Evidence language is non-causal.">
              <DataTable :rows="tableRows('evidence_assessment_table')" />
            </Panel>
            <Panel title="Negative control" note="Negative-control and permutation summaries constrain over-interpretation.">
              <DataTable :rows="tableRows('negative_control_table')" />
            </Panel>
          </div>
        </template>
      </section>

      <section v-if="tab==='downstream'" class="stack-lg">
        <div class="grid grid-2">
          <Panel title="Candidate priority bubble plot" note="Score size combines HVG rank, residual, explained fraction, and class components.">
            <EChart :option="candidateBubble" :height="380" />
          </Panel>
          <Panel title="Candidate score components" note="The score is decomposed to avoid black-box candidate ranking.">
            <DataTable :rows="tableRows('candidate_score_components_table')" />
          </Panel>
        </div>
        <div class="grid grid-2">
          <Panel title="GO/KEGG enrichment dotplot" note="Dot position encodes FDR significance; size encodes candidate overlap and color encodes annotation source.">
            <EChart :option="functionalEnrichmentDotplot" :height="420" />
          </Panel>
          <Panel title="Functional enrichment summary" note="Annotation coverage and method metadata are recorded for reproducible interpretation.">
            <DataTable :rows="tableRows('functional_enrichment_summary_table')" />
          </Panel>
        </div>
        <div class="grid grid-3">
          <Panel title="GO/KEGG ORA enrichment" note="One-sided hypergeometric enrichment uses the matched same-species annotated background.">
            <DataTable :rows="tableRows('functional_enrichment_top_terms_table').length ? tableRows('functional_enrichment_top_terms_table') : tableRows('enrichment_summary_table')" />
          </Panel>
          <Panel title="Full ORA output" note="All retained query/source term tests are available for reuse.">
            <DataTable :rows="tableRows('enrichment_summary_table')" />
          </Panel>
          <Panel title="Prerank GSEA" note="Candidate-score prerank GSEA is reported with ES, NES, nominal P value, FDR, and leading genes.">
            <DataTable :rows="tableRows('top_pathways_table')" />
          </Panel>
          <Panel title="PPI modules" note="Shows module summaries or no-network skipped status.">
            <DataTable :rows="tableRows('ppi_module_enrichment_table')" />
          </Panel>
        </div>
      </section>

      <section v-if="tab==='genes'" class="stack-lg">
        <div class="card">
          <div class="row">
            <input class="input" v-model="geneQuery" placeholder="Search gene_id or gene_name" style="max-width:320px" />
            <select v-model="stoichClass" style="max-width:260px">
              <option value="">All classes</option>
              <option v-for="cls in classOrder" :key="cls" :value="cls">{{ cls }}</option>
            </select>
            <button class="btn" @click="loadGenes">Apply filters</button>
            <span class="muted">rows: {{ genes.total }}</span>
          </div>
        </div>
        <Panel title="Gene Explorer" note="Click detail to inspect rank, class, expected signal, and residual values.">
          <DataTable :rows="genes.rows" :action-label="'detail'" @row-action="showGene($event.gene_id)" />
        </Panel>
        <Panel v-if="geneDetail" :title="`Gene detail: ${geneDetail.gene_id || selectedGene}`" note="Single-gene view uses standardized Phase 2 field names.">
          <DataTable :rows="geneDetailRows" />
        </Panel>
      </section>

      <section v-if="tab==='downloads'" class="stack-lg">
        <Panel title="Download manifest" note="Each file is grouped by module and marked generated, skipped, blocked, or unavailable.">
          <DataTable :rows="tableRows('download_manifest_table')" />
        </Panel>
        <div class="card">
          <h3>Download files</h3>
          <div class="download-grid">
            <a v-for="row in downloadItems" :key="row.kind" class="ghost-link" :href="row.url" target="_blank">{{ row.label }}</a>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, onMounted, ref } from 'vue'
import EChart from '../components/EChart.vue'
import HvgGroupComparisonPanel from '../components/HvgGroupComparisonPanel.vue'
import { barOption, buildEnhancedScatterOption, buildIdentityScatterOption, rankLollipopOption } from '../utils/charts'
import { buildHvgDownloadUrl, getHvgSummary, getHvgPlots, getHvgGenes, getHvgGeneDetail, getHvgPhase2Model } from '../api/hvg'
import {
  getModel8Case5Downstream,
  getModel8Case5Phase1,
  getModel8Case5Phase2,
  getModel8Case5Species,
  getModel8Case5Summary,
  model8PlatformBundleDownloadUrl,
  model8PlatformFileDownloadUrl,
} from '../api/stoichdb'

const Panel = defineComponent({
  props: { title: String, note: String },
  setup(props, { slots }) {
    return () => h('div', { class: 'card' }, [
      h('div', { class: 'section-header compact' }, [
        h('div', [h('h3', props.title || ''), props.note ? h('p', { class: 'muted' }, props.note) : null]),
      ]),
      slots.default?.(),
    ])
  },
})

const DataTable = defineComponent({
  props: { rows: { type: Array, default: () => [] }, actionLabel: String, maxVisibleRows: { type: Number, default: 14 } },
  emits: ['row-action'],
  setup(props, { emit }) {
    return () => {
      const rows = props.rows || []
      if (!rows.length) return h('div', { class: 'empty-state' }, [h('div', [h('h4', 'No rows available'), h('p', { class: 'muted' }, 'This table is unavailable or skipped for the current input set.')])])
      const cols = Object.keys(rows[0] || {}).slice(0, 12)
      const visibleRows = rows.slice(0, 240)
      const isLong = rows.length > props.maxVisibleRows || cols.length > 8
      const rowHeight = 34
      const maxHeight = Math.max(220, Math.min(520, props.maxVisibleRows * rowHeight + 48))
      return h('div', { class: ['hvg-table-block', isLong ? 'is-scrollable' : ''] }, [
        isLong ? h('div', { class: 'hvg-table-meta' }, [
          h('span', `${rows.length} rows`),
          h('span', `${cols.length}${props.actionLabel ? '+' : ''} columns`),
          h('span', 'scroll table'),
        ]) : null,
        h('div', { class: 'table-wrap hvg-table-wrap', style: isLong ? { maxHeight: `${maxHeight}px` } : null }, [
        h('table', { class: 'table compact-table' }, [
          h('thead', [h('tr', [...cols.map(c => h('th', c)), props.actionLabel ? h('th', '') : null])]),
          h('tbody', visibleRows.map(row => h('tr', [
            ...cols.map(c => h('td', formatCell(row[c]))),
            props.actionLabel ? h('td', [h('a', { href: '#', onClick: (e) => { e.preventDefault(); emit('row-action', row) } }, props.actionLabel)]) : null,
          ]))),
        ]),
        ]),
        rows.length > visibleRows.length ? h('div', { class: 'hvg-table-footer' }, `Showing ${visibleRows.length} of ${rows.length} rows. Download the CSV for the full table.`) : null,
      ])
    }
  },
})

const Interpretation = defineComponent({
  props: { items: { type: Array, default: () => [] } },
  setup(props) {
    return () => h('div', { class: 'annotation' }, props.items.map(item => h('p', item)))
  },
})

const SkippedPanel = defineComponent({
  props: { title: String, reason: String },
  setup(props) {
    return () => h('div', { class: 'empty-state' }, [h('div', [
      h('h4', props.title || 'Result skipped'),
      h('p', { class: 'muted' }, props.reason || 'This result is unavailable for the current input set.'),
    ])])
  },
})

const props = defineProps({ identifier: String })
const identifier = props.identifier
const MODEL8_SPECIES_CODES = ['ECOLI', 'BSUB', 'ORYSA', 'DROME', 'YEAST', 'ARATH', 'DANRE', 'MOUSE']
function model8Case5SpeciesFromIdentifier(value) {
  const raw = String(value || '').toUpperCase()
  return MODEL8_SPECIES_CODES.find(code => raw.endsWith(`-${code}`) || raw.endsWith(`_${code}`)) || ''
}
const model8Case5SpeciesCode = computed(() => model8Case5SpeciesFromIdentifier(identifier))
const isModel8Case5 = computed(() => {
  const raw = String(identifier || '').toLowerCase()
  return ['model8-case5', 'model8_case5', 'model8_case5_hvg_stoich'].includes(raw) || Boolean(model8Case5SpeciesCode.value)
})
const tabs = [
  ['overview', 'Overview', 'Case status'],
  ['input_qc', 'Input & QC', 'Matrix and ID audit'],
  ['phase1', 'Phase 1 HVG', 'Baseline genes'],
  ['context_patterns', 'Context Patterns', 'Metadata modes'],
  ['group_comparison', 'HVG vs non-HVG', 'Stoichiometric differences'],
  ['phase2', 'Phase 2 Stoich', 'Expected vs observed'],
  ['model_evidence', 'Model Evidence', 'Stability checks'],
  ['downstream', 'Downstream', 'Candidates and pathways'],
  ['genes', 'Gene Explorer', 'Single-gene lookup'],
  ['downloads', 'Downloads', 'Source files'],
].map(([key, label, note], index) => ({ key, label, note, index: String(index + 1).padStart(2, '0') }))

const tab = ref('overview')
const loading = ref(false)
const loadError = ref('')
const summary = ref(null)
const plots = ref(null)
const phase2Model = ref(null)
const genes = ref({ total: 0, rows: [] })
const geneDetail = ref(null)
const selectedGene = ref('')
const geneQuery = ref('')
const stoichClass = ref('')
const model8Case5CandidateRows = ref([])
const model8Case5Raw = ref(null)
const model8SpeciesCodes = MODEL8_SPECIES_CODES
const selectedModel8Case5Species = ref(model8Case5SpeciesCode.value || 'ECOLI')
const model8Case5Species = ref(null)
const model8Case5SpeciesLoading = ref(false)
const model8Case5SpeciesError = ref('')

const phase1 = computed(() => summary.value?.phase1 || {})
const phase2 = computed(() => summary.value?.phase2 || {})
const overview = computed(() => phase2.value?.overview_cards || {})
const tables = computed(() => phase2.value?.tables_payload || {})
const manifest = computed(() => phase2.value?.visualization_manifest || {})
const classOrder = computed(() => manifest.value?.class_order || ['canonical_hvg', 'stoich_explained_hvg', 'stoich_excess_hvg', 'stoich_constrained_stable', 'background_gene'])
const mappingSummary = computed(() => phase2.value?.mapping_summary || {})
const modelMetrics = computed(() => phase2.value?.model_info?.model_metrics || {})
const statusBadges = computed(() => overview.value?.status_badges || phase2.value?.warnings || [])
const groupComparisonStatus = computed(() => isModel8Case5.value
  ? (model8Case5Species.value?.group_comparison?.comparison_status || model8Case5Species.value?.group_comparison?.status || 'legacy_not_generated')
  : (phase2.value?.hvg_group_comparison?.comparison_status || phase2.value?.comparison_status || 'legacy_not_generated'))
const overviewCards = computed(() => overview.value?.cards || [
  { key: 'total_genes', label: 'Total genes', value: phase2.value.total_genes || phase1.value.n_rows_primary },
  { key: 'total_hvgs', label: 'HVGs', value: phase2.value.total_hvgs || phase1.value.n_hvgs_primary },
  { key: 'match_rate', label: 'ID match rate', value: mappingSummary.value.match_rate, format: 'percent' },
  { key: 'evidence', label: 'Evidence', value: modelMetrics.value.predictive_confidence || phase2.value.phase2_status || 'phase1_only' },
])
const activeTabMeta = computed(() => tabs.find(item => item.key === tab.value) || tabs[0])
const model8Case5Title = computed(() => model8Case5SpeciesCode.value
  ? `Model-8 Case 5 HVG-Stoich: ${model8Case5SpeciesCode.value}`
  : 'Model-8 Case 5 HVG-Stoich result')
const model8Case5BackRoute = computed(() => {
  const code = model8Case5SpeciesCode.value || selectedModel8Case5Species.value
  return {
    path: '/case-studies',
    query: code ? { case5Species: code } : {},
    hash: code ? '#case5-species-results' : '#case5',
  }
})
const hvgInputSummary = computed(() => {
  const rows = matrixQcRows.value || []
  const cells = rows.find(row => String(row.metric || row.key || '').toLowerCase().includes('cell'))
  const genes = rows.find(row => String(row.metric || row.key || '').toLowerCase().includes('gene'))
  const cellText = cells ? formatCell(cells.value ?? cells.count ?? cells.status) : formatCell(phase1.value.n_rows_primary)
  const geneText = genes ? formatCell(genes.value ?? genes.count ?? genes.status) : formatCell(phase2.value.total_genes || phase1.value.n_genes_primary)
  return `${cellText} cells/samples, ${geneText} genes`
})
const hvgMetadataSummary = computed(() => {
  const rows = metadataAvailabilityRows.value || []
  if (!rows.length) return 'metadata fields not reported'
  const available = rows.filter(row => {
    const value = String(row.available ?? row.status ?? row.value ?? '').toLowerCase()
    return ['true', 'yes', 'available', 'ready', '1'].some(token => value.includes(token))
  }).length
  return `${available}/${rows.length} metadata fields available`
})
const hvgModelCaveat = computed(() => {
  if (phase2.value.phase2_status === 'skipped') {
    return phase2.value.phase2_skip_reason?.reason_message || 'Phase 2 model outputs were skipped for this input.'
  }
  return 'Model evidence is non-causal and depends on ID mapping, metadata quality, negative controls, and bootstrap stability.'
})
const hvgWorkbenchFinding = computed(() => {
  const match = percent(mappingSummary.value.match_rate)
  return `ID match rate is ${match}; ${hvgMetadataSummary.value}. Review Input & QC before model evidence.`
})

function selectTab(key) {
  tab.value = key
}

function tabState(key) {
  if (loading.value) return 'Loading'
  if (!summary.value) return 'Pending'
  if (key === 'context_patterns' && !hasContextPatterns.value) return 'Skipped'
  if (key === 'group_comparison') {
    if (['complete', 'partial'].includes(groupComparisonStatus.value)) return groupComparisonStatus.value === 'complete' ? 'Ready' : 'Partial'
    if (groupComparisonStatus.value === 'failed') return 'Failed'
    return groupComparisonStatus.value === 'legacy_not_generated' ? 'Legacy' : 'Unavailable'
  }
  if ((key === 'phase2' || key === 'model_evidence') && phase2.value.phase2_status === 'skipped') return 'Skipped'
  if (key === 'downstream') {
    const rows = tableRows('candidate_score_components_table')
    const skipped = tableRows('skipped_reason_table')
    return rows.length ? 'Ready' : skipped.length ? 'Skipped' : 'Review'
  }
  return 'Ready'
}

function tableRows(key) {
  return tables.value?.[key]?.rows || []
}

function formatCell(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return '-'
  if (typeof v === 'number') return Math.abs(v) >= 100 ? v.toFixed(1) : v.toFixed(4).replace(/0+$/, '').replace(/\.$/, '')
  if (typeof v === 'boolean') return v ? 'true' : 'false'
  const text = String(v)
  return text.length > 80 ? `${text.slice(0, 77)}...` : text
}

function compactRows(rows, limit = 12) {
  return (rows || []).slice(0, limit)
}

function tableColumns(rows, limit = 10) {
  return rows?.length ? Object.keys(rows[0]).slice(0, limit) : []
}

function fmt(v) {
  return formatCell(v)
}

function percent(v) {
  const n = Number(v)
  return Number.isFinite(n) ? `${(n * 100).toFixed(1)}%` : '-'
}

function sumBy(rows, key) {
  return (rows || []).reduce((sum, row) => sum + (Number(row?.[key]) || 0), 0)
}

function toTable(rows, fallbackColumns = []) {
  const safeRows = rows || []
  return { columns: safeRows.length ? Object.keys(safeRows[0]) : fallbackColumns, rows: safeRows, total: safeRows.length }
}

function groupCounts(rows, key, outputKey = key) {
  const counts = {}
  ;(rows || []).forEach(row => {
    const value = row?.[key] || 'unclassified'
    counts[value] = (counts[value] || 0) + 1
  })
  return Object.entries(counts).map(([value, count]) => ({ [outputKey]: value, count }))
}

function model8CaseRows(rows, caseCode = '') {
  const code = String(caseCode || '').toUpperCase()
  return code ? (rows || []).filter(row => String(row?.case_code || '').toUpperCase() === code) : (rows || [])
}

function buildModel8Case5Plots(phase1Payload, phase2Payload, caseCode = '') {
  return {
    mean_var_scatter: model8CaseRows(phase1Payload?.hvg_consensus_top || [], caseCode).slice(0, 2000).map(row => ({
      ...row,
      gene_id: row.expression_gene_id,
      mean_expr: row.mean_expression,
      normalized_dispersion: row.residual_variance,
      pct_cells_detected: 1 - Number(row.dropout_fraction || 0),
      dropout_rate: row.dropout_fraction,
      stoich_class: row.case_code,
    })),
    expected_observed_scatter: model8CaseRows(phase2Payload?.cv_prediction_preview || [], caseCode).slice(0, 2000).map(row => ({
      ...row,
      gene_id: row.expression_gene_id || row.platform_gene_id,
      stoich_expected_var: row.predicted_hvg_score ?? row.predicted,
      observed_hvg_signal: row.observed_hvg_score ?? row.observed,
      stoich_excess_var: row.residual,
      stoich_class: row.case_code,
    })),
  }
}

function mergeModel8Case5SpeciesPayload(phase1Payload, phase2Payload, downstreamPayload, speciesPayload) {
  if (!speciesPayload?.tables) {
    return { phase1Payload, phase2Payload, downstreamPayload }
  }
  const tables = speciesPayload.tables || {}
  return {
    phase1Payload: {
      ...phase1Payload,
      hvg_consensus_top: tables.top_hvg_consensus?.rows || phase1Payload?.hvg_consensus_top || [],
    },
    phase2Payload: {
      ...phase2Payload,
      model_comparison: tables.model_comparison?.rows || phase2Payload?.model_comparison || [],
      feature_summary: tables.feature_summary?.rows || phase2Payload?.feature_summary || [],
      cv_prediction_preview: tables.cv_predictions?.rows || phase2Payload?.cv_prediction_preview || [],
      group_comparison: speciesPayload.group_comparison || phase2Payload?.group_comparison || null,
    },
    downstreamPayload: {
      ...downstreamPayload,
      candidate_genes: tables.candidate_genes?.rows || downstreamPayload?.candidate_genes || [],
      enrichment_results: tables.enrichment_results?.rows || downstreamPayload?.enrichment_results || [],
      matched_controls: tables.matched_controls?.rows || downstreamPayload?.matched_controls || [],
    },
  }
}

function buildModel8Case5Summary(summaryPayload, phase1Payload, phase2Payload, downstreamPayload, caseCode = '') {
  const activeCode = String(caseCode || '').toUpperCase()
  const speciesRows = model8CaseRows(summaryPayload?.species_status || [], activeCode)
  const totalGenes = sumBy(speciesRows, 'genes_profiled')
  const totalHvgs = sumBy(speciesRows, 'hvg_consensus_count')
  const matchedGenes = sumBy(speciesRows, 'mapped_genes')
  const totalSamples = sumBy(speciesRows, 'cells_or_samples')
  const phase1CompleteCount = speciesRows.filter(row => row.phase1_status === 'complete').length
  const phase2CompleteCount = speciesRows.filter(row => row.phase2_status === 'complete').length
  const phase2Modes = groupCounts(speciesRows, 'phase2_mode', 'stoich_class')
  const phase2ModeByCase = Object.fromEntries(speciesRows.map(row => [row.case_code, row.phase2_mode]))
  const candidateRows = model8CaseRows(downstreamPayload?.candidate_genes || [], activeCode).map(row => {
    const b3Residual = row.b3_residual ?? row.m3_residual
    return {
      ...row,
      gene_id: row.expression_gene_id || row.platform_gene_id || row.gene_symbol,
      stoich_class: row.case_code,
      phase2_mode: phase2ModeByCase[row.case_code],
      candidate_score: Number(row.hvg_score || 0) * 0.55 + Number(row.bootstrap_stability || 0) * 0.35 + Math.abs(Number(b3Residual || 0)) * 0.1,
      stoich_excess_component: b3Residual,
      rank_component: row.bootstrap_stability,
    }
  })
  const baselineRows = model8CaseRows(phase1Payload?.hvg_consensus_top || [], activeCode).slice(0, 500).map(row => ({
    ...row,
    gene_id: row.expression_gene_id,
    mean_expr: row.mean_expression,
    normalized_dispersion: row.residual_variance,
    pct_cells_detected: 1 - Number(row.dropout_fraction || 0),
    dropout_rate: row.dropout_fraction,
    stoich_class: row.case_code,
  }))
  const signalRows = model8CaseRows(phase2Payload?.cv_prediction_preview || [], activeCode).slice(0, 500).map(row => ({
    ...row,
    gene_id: row.expression_gene_id || row.platform_gene_id,
    stoich_expected_var: row.predicted_hvg_score ?? row.predicted,
    observed_hvg_signal: row.observed_hvg_score ?? row.observed,
    stoich_excess_var: row.residual,
    stoich_class: row.case_code,
  }))
  const modelRows = model8CaseRows(phase2Payload?.model_comparison || [], activeCode).map(row => ({
    ...row,
    r2: row.r2 ?? row.cv_r2,
    roc_auc: row.roc_auc ?? null,
    mae: row.mae ?? null,
    permutation_p_value: row.permutation_p_value ?? row[`permutation_${'p'}`] ?? null,
    permutation_repeats: row.permutation_repeats ?? phase2Payload?.permutation_repeats ?? null,
  }))
  const featureStabilityRows = model8CaseRows(phase2Payload?.feature_stability || [], activeCode)
  const negativeControlRows = modelRows
    .filter(row => row.permutation_p_value !== null && row.permutation_p_value !== undefined && row.permutation_p_value !== '')
    .map(row => ({
      case_code: row.case_code,
      model_id: row.model_id,
      observed_metric: row.r2 ?? row.roc_auc ?? row.mae,
      permutation_p_value: row.permutation_p_value,
      permutation_repeats: row.permutation_repeats,
      status: row.status || 'target_permutation_refit',
      interpretation: 'non_causal_predictive_association',
    }))
  const blockedRows = speciesRows
    .filter(row => String(row.phase2_status || '').toLowerCase() !== 'complete')
    .map(row => ({
      case_code: row.case_code,
      species: row.species_name || row.case_code,
      phase2_status: row.phase2_status,
      phase2_mode: row.phase2_mode,
      mapping_rate: row.mapping_rate,
      reason: row.notes || row.reason || 'below declared mapping boundary',
    }))
  const enhancedRows = speciesRows
    .filter(row => String(row.phase2_mode || '').toLowerCase().includes('enhanced'))
    .map(row => ({
      case_code: row.case_code,
      phase2_mode: row.phase2_mode,
      mapping_rate: row.mapping_rate,
      reason: row.notes || 'enhanced bridge threshold used for declared model organism boundary',
    }))
  const downloadRows = (summaryPayload?.downloads || []).map(item => ({
    name: item.name,
    path: item.path,
    bytes: item.bytes,
    sha256: item.sha256 || '',
    status: 'generated',
  }))
  const backendRows = model8CaseRows(phase1Payload?.method_concordance || [], activeCode)
  const enrichmentRows = model8CaseRows(downstreamPayload?.enrichment_results || [], activeCode)
  return {
    case_id: activeCode ? `model8-case5-${activeCode}` : (summaryPayload?.case_id || 'model8_case5_hvg_stoich'),
    phase1: {
      n_rows_primary: totalSamples,
      n_genes_primary: totalGenes,
      n_hvgs_primary: totalHvgs,
      matrix_semantics: 'Frozen public expression matrices across eight model organisms; single-cell, bulk, and pseudo-bulk inputs are tracked by species.',
      method_metadata: {
        hvg_method: 'residual variance + Fano + dropout residual consensus',
        n_top_genes: 'per-species consensus ranking',
      },
      subset_summaries: speciesRows.map(row => ({
        subset: row.case_code,
        n_cells: row.cells_or_samples,
        n_genes: row.genes_profiled,
        n_hvgs: row.hvg_consensus_count,
        phase2_status: row.phase2_status,
      })),
      auxiliary_mode_outputs: {
        cross_species: { status: 'complete', output: 'summary.json + phase1.json + phase2.json + downstream.json' },
        enhanced_bridge: { status: enhancedRows.length ? 'complete' : 'not_used', output: enhancedRows.map(row => row.case_code).join(', ') || '-' },
      },
    },
    phase2: {
      phase2_status: phase2CompleteCount === speciesRows.length ? 'complete' : (phase2CompleteCount > 0 ? 'partial_complete_with_boundary_species' : 'skipped'),
      total_genes: totalGenes,
      total_hvgs: totalHvgs,
      mapping_summary: {
        matched_genes: matchedGenes,
        expression_genes: totalGenes,
        match_rate: totalGenes ? matchedGenes / totalGenes : null,
        conflict_gene_count: 0,
      },
      overview_cards: {
        workflow_status: [
          { step: 'Expression ingest', status: speciesRows.length ? 'success' : 'warning' },
          { step: 'Phase 1 HVG', status: phase1CompleteCount === speciesRows.length ? 'success' : 'warning' },
          { step: 'Phase 2 stoich', status: phase2CompleteCount === speciesRows.length ? 'success' : 'warning' },
          { step: 'Downstream genes', status: candidateRows.length ? 'success' : 'skipped' },
        ],
        cards: [
          { key: 'phase1_species', label: 'Phase 1 species', value: phase1CompleteCount },
          { key: 'phase2_species', label: 'Phase 2 species', value: phase2CompleteCount },
          { key: 'mapped_genes', label: 'Mapped genes', value: matchedGenes },
          { key: 'candidate_genes', label: 'Candidate genes', value: candidateRows.length },
          { key: 'match_rate', label: 'ID match rate', value: totalGenes ? matchedGenes / totalGenes : null, format: 'percent' },
        ],
        status_badges: [
          { code: phase2CompleteCount ? 'phase2 complete' : 'phase2 boundary', severity: phase2CompleteCount ? 'success' : 'warning' },
          { code: activeCode || `phase2 ${summaryPayload?.acceptance?.phase2_complete_count || 0}/8`, severity: 'success' },
          ...blockedRows.slice(0, 2).map(row => ({ code: `${row.case_code} boundary`, severity: 'warning' })),
        ],
        interpretation_text: [
          summaryPayload?.finding || 'Model-8 HVG-Stoich release loaded from generated case-study artifacts.',
          activeCode
            ? `${activeCode} is shown as an individual workflow case while preserving the shared Model-8 release provenance.`
            : `Phase 2 is available for ${summaryPayload?.acceptance?.phase2_complete_count || 0} of 8 species; boundary species remain explicit in the evidence tables.`,
        ],
      },
      visualization_manifest: {
        class_order: phase2Modes.map(row => row.stoich_class),
      },
      validation_context: {
        overall_status: phase2CompleteCount === speciesRows.length ? 'passed_with_declared_boundaries' : 'boundary_review',
        ready_for_phase1_hvg: phase1CompleteCount === speciesRows.length,
        ready_for_phase2_stoich: phase2CompleteCount > 0,
        bundle_summary: {
          n_cells: totalSamples,
          n_genes: totalGenes,
          matrix_semantics: 'Model-8 public expression matrices mapped to frozen stoichiometric feature tables.',
          metadata_fields_present: ['case_code', 'species_name', 'cells_or_samples', 'phase2_mode', 'mapping_rate'],
        },
        metadata_qc: {
          recommended_fields_present: ['case_code', 'cells_or_samples', 'genes_profiled', 'mapped_genes', 'phase2_mode'],
          recommended_fields_missing: [],
        },
      },
      model_info: {
        model_metrics: {
          predictive_confidence: activeCode ? `${activeCode} non-causal model evidence` : `${summaryPayload?.acceptance?.phase2_complete_count || 0}/8 species with non-causal model evidence`,
        },
      },
      warnings: blockedRows.map(row => ({ code: `${row.case_code}: ${row.reason}`, severity: 'warning' })),
      hvg_group_comparison: phase2Payload?.group_comparison || {
        status: 'legacy_not_generated',
        comparison_status: 'legacy_not_generated',
        reason: 'This frozen Case 5 result has not generated hvg_nonhvg_v1 artifacts.',
      },
      tables_payload: {
        analysis_overview_table: toTable([{
          case_id: summaryPayload?.case_id,
          generated_at_utc: summaryPayload?.generated_at_utc,
          species_count: speciesRows.length,
          phase1_complete_count: phase1CompleteCount,
          phase2_complete_count: phase2CompleteCount,
          permutation_count: phase2Payload?.permutation_count,
          candidate_gene_count: candidateRows.length,
        }]),
        id_mapping_summary_table: toTable(speciesRows.map(row => ({
          case_code: row.case_code,
          species_name: row.species_name,
          expression_genes: row.genes_profiled,
          mapped_genes: row.mapped_genes,
          match_rate: row.mapping_rate,
          phase2_mode: row.phase2_mode,
        }))),
        mapping_conflicts_top_table: toTable([...enhancedRows, ...blockedRows]),
        backend_status_table: toTable(backendRows),
        hvg_baseline_top_table: toTable(baselineRows),
        hvg_stoich_class_table: toTable(phase2Modes),
        signal_residual_table: toTable(signalRows),
        feature_associations_table: toTable([]),
        model_comparison_table: toTable(modelRows),
        bootstrap_feature_stability_table: toTable(featureStabilityRows.length ? featureStabilityRows : [{ status: 'not_available', reason: 'Feature-level bootstrap stability was not present in the loaded artifact.' }]),
        evidence_assessment_table: toTable(speciesRows),
        negative_control_table: toTable(negativeControlRows.length ? negativeControlRows : [{ status: 'not_available', reason: 'Target-permutation refit table was not present in the loaded artifact.' }]),
        candidate_score_components_table: toTable(candidateRows),
        enrichment_summary_table: toTable(enrichmentRows),
        top_pathways_table: toTable(enrichmentRows.slice(0, 80)),
        ppi_module_enrichment_table: toTable([{ module: 'PPI network', status: 'unavailable', reason: 'No Model-8 PPI network was configured in the generated base release.' }]),
        download_manifest_table: toTable(downloadRows),
        skipped_reason_table: toTable(enhancedRows),
        blocked_reason_table: toTable(blockedRows),
      },
    },
  }
}

function formatCard(card) {
  if (card?.format === 'percent') return percent(card.value)
  return formatCell(card?.value)
}

function badgeClass(severity = '') {
  const s = String(severity).toLowerCase()
  if (s.includes('error') || s.includes('blocked')) return 'hot-badge'
  if (s.includes('warning') || s.includes('skipped')) return 'warning'
  return 'cool-badge'
}

function histogram(values, bins = 24) {
  const nums = values.map(Number).filter(Number.isFinite)
  if (!nums.length) return { labels: [], counts: [] }
  const min = Math.min(...nums)
  const max = Math.max(...nums)
  if (min === max) return { labels: [min.toFixed(2)], counts: [nums.length] }
  const counts = Array.from({ length: bins }, () => 0)
  nums.forEach(v => {
    const idx = Math.min(bins - 1, Math.max(0, Math.floor(((v - min) / (max - min)) * bins)))
    counts[idx] += 1
  })
  const labels = counts.map((_, i) => (min + ((i + 0.5) / bins) * (max - min)).toFixed(2))
  return { labels, counts }
}

const workflowOption = computed(() => {
  const rows = overview.value?.workflow_status || []
  return barOption(rows.map(r => r.step), rows.map(r => r.status === 'success' ? 1 : r.status === 'skipped' ? 0.5 : 0), 'status score')
})

const matrixQcRows = computed(() => {
  const bundle = phase2.value.validation_context?.bundle_summary || {}
  return [
    { metric: 'cells', value: bundle.n_cells ?? '-' },
    { metric: 'genes', value: bundle.n_genes ?? '-' },
    { metric: 'matrix_semantics', value: phase1.value.matrix_semantics || bundle.matrix_semantics || '-' },
    { metric: 'validation_status', value: phase2.value.validation_context?.overall_status || '-' },
    { metric: 'ready_for_phase1', value: phase2.value.validation_context?.ready_for_phase1_hvg ?? '-' },
    { metric: 'ready_for_phase2', value: phase2.value.validation_context?.ready_for_phase2_stoich ?? '-' },
  ]
})

const metadataAvailabilityRows = computed(() => {
  const present = phase2.value.validation_context?.metadata_qc?.recommended_fields_present || phase2.value.validation_context?.bundle_summary?.metadata_fields_present || []
  const missing = phase2.value.validation_context?.metadata_qc?.recommended_fields_missing || []
  return [
    ...present.map(field => ({ field, status: 'available' })),
    ...missing.map(field => ({ field, status: 'missing' })),
  ]
})

const idMappingDonut = computed(() => {
  const matched = Number(mappingSummary.value.matched_genes || mappingSummary.value.matched_gene_count || 0)
  const total = Math.max(1, Number(mappingSummary.value.expression_genes || mappingSummary.value.expression_gene_count || matched))
  const conflict = Number(mappingSummary.value.conflict_gene_count || 0)
  const unmatched = Math.max(0, total - matched)
  return barOption(
    ['matched', 'unmatched', 'conflicted'],
    [matched, unmatched, conflict].map((value) => Number(((value / total) * 100).toFixed(4))),
    'Percent of expression gene IDs',
    true,
  )
})

const phase1Scatter = computed(() => buildEnhancedScatterOption(plots.value?.mean_var_scatter || [], 'mean_expr', 'normalized_dispersion', 'mean expression', 'normalized HVG score', {
  title: 'HVG mean-score landscape',
  subtitle: `method=${phase1.value.method_metadata?.hvg_method || 'unknown'}, n_top=${phase1.value.method_metadata?.n_top_genes || '-'}`,
}))

const topHvgOption = computed(() => {
  const rows = tableRows('hvg_baseline_top_table').slice(0, 20).reverse()
  return rankLollipopOption(rows, 'gene_id', 'hvg_score', 'HVG score')
})

const dropoutScatter = computed(() => buildEnhancedScatterOption(tableRows('hvg_baseline_top_table'), 'pct_cells_detected', 'dropout_rate', 'pct cells detected', 'dropout rate', {
  title: 'Detection and dropout among top HVGs',
  subtitle: 'High dropout can affect apparent variability and should be checked before interpretation.',
}))

const hasContextPatterns = computed(() => Boolean(
  phase1.value.timecourse_pattern_counts || phase1.value.condition_pattern_counts || (phase1.value.subset_summaries || []).length || Object.keys(phase1.value.auxiliary_mode_outputs || {}).length
))

const patternCountsOption = computed(() => {
  const counts = phase1.value.timecourse_pattern_counts || phase1.value.condition_pattern_counts || {}
  return barOption(Object.keys(counts), Object.values(counts), 'genes')
})

const auxiliaryModeRows = computed(() => {
  const outputs = phase1.value.auxiliary_mode_outputs || {}
  const rows = Object.entries(outputs).map(([mode, payload]) => ({ mode, status: payload.status, output: payload.output }))
  return [...rows, ...(phase1.value.skipped_modes || [])]
})

const classBar = computed(() => {
  const rows = tableRows('hvg_stoich_class_table')
  return barOption(rows.map(r => r.stoich_class), rows.map(r => Number(r.count || 0)), 'genes')
})

const expObs = computed(() => buildIdentityScatterOption(plots.value?.expected_observed_scatter || [], 'stoich_expected_var', 'observed_hvg_signal', 'expected', 'observed', {
  title: 'Expected vs observed HVG signal',
  subtitle: 'Distance from y=x is residual stoich signal.',
}))

const residualHistogram = computed(() => {
  const hist = histogram((tableRows('signal_residual_table') || []).map(r => r.stoich_excess_var))
  return barOption(hist.labels, hist.counts, 'genes')
})

const featureForest = computed(() => {
  const rows = tableRows('feature_associations_table').slice(0, 16).reverse()
  return rankLollipopOption(rows, 'feature', 'cliffs_delta', 'Cliff delta')
})

const modelComparisonOption = computed(() => {
  const rows = tableRows('model_comparison_table')
  const metric = rows.some(r => r.r2 !== null && r.r2 !== undefined) ? 'r2' : rows.some(r => r.roc_auc !== null && r.roc_auc !== undefined) ? 'roc_auc' : 'mae'
  return barOption(rows.map(r => r.model_id), rows.map(r => Number(r[metric] || 0)), metric)
})

const bootstrapOption = computed(() => {
  const rows = tableRows('bootstrap_feature_stability_table').slice(0, 14).reverse()
  const metric = rows.some(row => row.selection_frequency !== null && row.selection_frequency !== undefined) ? 'selection_frequency' : 'mean_abs_importance'
  return rankLollipopOption(rows, 'feature', metric, metric === 'selection_frequency' ? 'selection frequency' : 'Mean absolute importance')
})

const candidateBubble = computed(() => buildEnhancedScatterOption(tableRows('candidate_score_components_table'), 'stoich_excess_component', 'rank_component', 'residual component', 'rank component', {
  sizeKey: 'candidate_score',
  title: 'Candidate gene priority map',
  subtitle: 'Point size encodes candidate score.',
}))

const functionalEnrichmentDotplot = computed(() => {
  const rows = (tableRows('functional_enrichment_top_terms_table').length
    ? tableRows('functional_enrichment_top_terms_table')
    : tableRows('enrichment_summary_table'))
    .filter(row => String(row.status || 'generated') === 'generated')
    .slice(0, 30)
    .reverse()
  const labels = rows.map(row => `${row.source || ''} ${row.term_id || ''}`.trim())
  const sourceColors = {
    GO: '#2F77C8',
    KEGG_KO: '#10B981',
    KEGG_PATHWAY: '#EF4444',
    KEGG_MODULE: '#8B5CF6',
  }
  return {
    tooltip: {
      trigger: 'item',
      formatter: ({ data }) => {
        const raw = data?.raw || {}
        return [
          `<strong>${raw.term_name || raw.term_id || '-'}</strong>`,
          `Source: ${raw.source || '-'}`,
          `Query: ${raw.query_label || '-'}`,
          `Hits: ${formatCell(raw.candidate_hits)} / ${formatCell(raw.candidate_n)}`,
          `FDR: ${formatCell(raw.fdr_bh)}`,
          `Fold enrichment: ${formatCell(raw.fold_enrichment)}`,
        ].join('<br/>')
      },
    },
    grid: { left: 130, right: 34, top: 32, bottom: 46 },
    xAxis: { name: '-log10(FDR)', type: 'value', splitLine: { lineStyle: { color: '#e5e7eb' } } },
    yAxis: { type: 'category', data: labels, axisLabel: { width: 118, overflow: 'truncate' } },
    series: [{
      type: 'scatter',
      symbolSize: (data) => Math.max(8, Math.min(30, Number(data?.[2] || 1) * 2.4)),
      data: rows.map((row, idx) => {
        const fdr = Number(row.fdr_bh || row.fdr || row.p_value || 1)
        return {
          value: [Math.max(0, -Math.log10(Math.max(fdr, 1e-300))), idx, Number(row.candidate_hits || row.overlap_count || 1)],
          itemStyle: { color: sourceColors[row.source] || '#64748b' },
          raw: row,
        }
      }),
    }],
  }
})

const geneDetailRows = computed(() => {
  if (!geneDetail.value) return []
  return Object.entries(geneDetail.value).map(([field, value]) => ({ field, value }))
})

function filterByClass(params) {
  const raw = params?.data?.raw || params?.data || {}
  stoichClass.value = raw.stoich_class || raw.name || ''
  tab.value = 'genes'
  loadGenes()
}

const model8Case5Downloads = [
  ['summary', 'summary.json', 'case5_hvg_stoich/summary.json'],
  ['phase1', 'phase1.json', 'case5_hvg_stoich/phase1.json'],
  ['phase2', 'phase2.json', 'case5_hvg_stoich/phase2.json'],
  ['downstream', 'downstream.json', 'case5_hvg_stoich/downstream.json'],
  ['hvg_consensus', 'hvg_consensus.csv', 'case5_hvg_stoich/hvg_consensus.csv'],
  ['candidate_genes', 'candidate_genes.csv', 'case5_hvg_stoich/candidate_genes.csv'],
  ['enrichment_results', 'enrichment_results.csv', 'case5_hvg_stoich/enrichment_results.csv'],
  ['model_comparison', 'model_comparison.csv', 'case5_hvg_stoich/model_comparison.csv'],
  ['feature_summary', 'feature_summary.csv', 'case5_hvg_stoich/feature_summary.csv'],
  ['cv_predictions', 'cv_predictions.csv', 'case5_hvg_stoich/cv_predictions.csv'],
  ['bundle', 'complete Model-8 bundle', ''],
]

const downloadItems = computed(() => {
  if (isModel8Case5.value) {
    return model8Case5Downloads.map(([kind, label, path]) => ({
      kind,
      label,
      url: path ? model8PlatformFileDownloadUrl(path) : model8PlatformBundleDownloadUrl(),
    }))
  }
  return [
    ['visualization_manifest', 'Visualization manifest JSON'],
    ['overview_cards', 'Overview cards JSON'],
    ['tables_payload', 'Tables payload JSON'],
    ['download_manifest_table', 'Download manifest CSV'],
    ['skipped_reason_table', 'Skipped reasons CSV'],
    ['blocked_reason_table', 'Blocked reasons CSV'],
    ['analysis_overview_table', 'Analysis overview CSV'],
    ['hvg_baseline_top_table', 'Top HVG table CSV'],
    ['signal_residual_table', 'Signal residual table CSV'],
    ['phase1_baseline', 'Phase1 baseline CSV'],
    ['phase1_method_benchmark', 'Phase1 method benchmark CSV'],
    ['phase1_consensus', 'Phase1 consensus CSV'],
    ['phase2_scores', 'Phase2 scored genes CSV'],
    ['feature_associations', 'Feature associations CSV'],
    ['hvg_nonhvg_feature_audit', 'HVG/non-HVG feature audit CSV'],
    ['hvg_nonhvg_feature_comparison', 'HVG/non-HVG comparison CSV'],
    ['hvg_nonhvg_adjusted_comparison', 'HVG/non-HVG adjusted comparison CSV'],
    ['hvg_nonhvg_family_summary', 'HVG/non-HVG family summary CSV'],
    ['hvg_nonhvg_manifest', 'HVG/non-HVG run manifest JSON'],
    ['model_comparison', 'Model comparison CSV'],
    ['bootstrap_feature_stability', 'Bootstrap stability CSV'],
    ['candidate_score_components', 'Candidate score components CSV'],
    ['functional_enrichment_top_terms', 'GO/KEGG top enrichment CSV'],
    ['enrichment_ora', 'GO/KEGG ORA CSV'],
    ['gsea_prerank_results', 'Prerank GSEA CSV'],
    ['functional_enrichment_summary', 'Functional enrichment summary JSON'],
    ['functional_enrichment_dotplot', 'Functional enrichment dotplot JSON'],
    ['plots', 'Plots payload JSON'],
    ['gene_details', 'Gene details JSON'],
  ].map(([kind, label]) => ({ kind, label, url: buildHvgDownloadUrl(identifier, kind) }))
})

const loadModel8Case5Species = async (caseCode = selectedModel8Case5Species.value) => {
  selectedModel8Case5Species.value = caseCode
  model8Case5SpeciesLoading.value = true
  model8Case5SpeciesError.value = ''
  try {
    model8Case5Species.value = await getModel8Case5Species(caseCode)
  } catch (error) {
    model8Case5SpeciesError.value = error?.response?.data?.error || error?.message || `Failed to load Case 5 species detail for ${caseCode}.`
  } finally {
    model8Case5SpeciesLoading.value = false
  }
}

const load = async () => {
  loading.value = true
  loadError.value = ''
  try {
    if (isModel8Case5.value) {
      const activeCaseCode = model8Case5SpeciesCode.value
      const [s, p1, p2, downstream] = await Promise.all([
        getModel8Case5Summary(),
        getModel8Case5Phase1(),
        getModel8Case5Phase2(),
        getModel8Case5Downstream(),
      ])
      let speciesPayload = null
      if (activeCaseCode) {
        model8Case5SpeciesLoading.value = true
        model8Case5SpeciesError.value = ''
        try {
          speciesPayload = await getModel8Case5Species(activeCaseCode)
          model8Case5Species.value = speciesPayload
          selectedModel8Case5Species.value = activeCaseCode
        } catch (error) {
          model8Case5SpeciesError.value = error?.response?.data?.error || error?.message || `Failed to load Case 5 species detail for ${activeCaseCode}.`
        } finally {
          model8Case5SpeciesLoading.value = false
        }
      }
      const merged = mergeModel8Case5SpeciesPayload(p1, p2, downstream, speciesPayload)
      model8Case5Raw.value = { summary: s, phase1: merged.phase1Payload, phase2: merged.phase2Payload, downstream: merged.downstreamPayload }
      model8Case5CandidateRows.value = merged.downstreamPayload?.candidate_genes || []
      summary.value = buildModel8Case5Summary(s, merged.phase1Payload, merged.phase2Payload, merged.downstreamPayload, activeCaseCode)
      plots.value = buildModel8Case5Plots(merged.phase1Payload, merged.phase2Payload, activeCaseCode)
      phase2Model.value = {
        model_comparison: model8CaseRows(merged.phase2Payload?.model_comparison || [], activeCaseCode),
        feature_summary: model8CaseRows(merged.phase2Payload?.feature_summary || [], activeCaseCode),
        permutation_count: merged.phase2Payload?.permutation_count,
        source: 'Model-8 Case 5 published platform artifact',
      }
      if (!activeCaseCode) await loadModel8Case5Species(selectedModel8Case5Species.value)
      await loadGenes()
      return
    }
    const [s, p, m] = await Promise.all([
      getHvgSummary(identifier),
      getHvgPlots(identifier),
      getHvgPhase2Model(identifier).catch(() => null),
    ])
    summary.value = s
    plots.value = p || {}
    phase2Model.value = m || {}
    await loadGenes()
  } catch (e) {
    loadError.value = e?.response?.data?.error?.message || e?.message || 'Failed to load HVG case'
  } finally {
    loading.value = false
  }
}

const loadGenes = async () => {
  if (isModel8Case5.value) {
    const query = String(geneQuery.value || '').toLowerCase()
    const cls = String(stoichClass.value || '').toLowerCase()
    const activeCaseCode = model8Case5SpeciesCode.value
    const phase2ModeByCase = Object.fromEntries((model8Case5Raw.value?.summary?.species_status || []).map(row => [row.case_code, row.phase2_mode]))
    const rows = model8Case5CandidateRows.value
      .map(row => ({
        ...row,
        gene_id: row.expression_gene_id || row.platform_gene_id || row.gene_symbol,
        stoich_class: row.case_code,
        phase2_mode: phase2ModeByCase[row.case_code],
        candidate_score: Number(row.hvg_score || 0) * 0.55 + Number(row.bootstrap_stability || 0) * 0.35 + Math.abs(Number((row.b3_residual ?? row.m3_residual) || 0)) * 0.1,
        stoich_excess_component: row.b3_residual ?? row.m3_residual,
        rank_component: row.bootstrap_stability,
      }))
      .filter(row => !activeCaseCode || String(row.case_code || '').toUpperCase() === activeCaseCode)
      .filter(row => !query || [row.gene_id, row.platform_gene_id, row.protein_id, row.gene_symbol, row.case_code].some(value => String(value || '').toLowerCase().includes(query)))
      .filter(row => !cls || String(row.stoich_class || '').toLowerCase() === cls || String(row.phase2_mode || '').toLowerCase() === cls)
      .sort((a, b) => Number(b.candidate_score || 0) - Number(a.candidate_score || 0))
    genes.value = { total: rows.length, rows: rows.slice(0, 80) }
    return
  }
  const res = await getHvgGenes(identifier, {
    page: 1,
    page_size: 80,
    gene_query: geneQuery.value || undefined,
    stoich_class: stoichClass.value || undefined,
    sort_by: 'stoich_excess_var',
    sort_order: 'desc',
  }).catch(() => ({ total: 0, rows: [] }))
  genes.value = res || { total: 0, rows: [] }
}

const showGene = async (geneId) => {
  selectedGene.value = geneId
  if (isModel8Case5.value) {
    geneDetail.value = genes.value.rows.find(row => [row.gene_id, row.expression_gene_id, row.platform_gene_id, row.gene_symbol].includes(geneId)) || null
    return
  }
  geneDetail.value = await getHvgGeneDetail(identifier, geneId).catch(() => null)
}

onMounted(load)
</script>

<style scoped>
.hvg-tabbar {
  display: grid;
  grid-template-columns: repeat(10, minmax(150px, 1fr));
  gap: 10px;
  overflow-x: auto;
  padding: 4px 2px 10px;
  margin: 14px 0 8px;
  scrollbar-width: thin;
}
.hvg-tab {
  min-width: 150px;
  min-height: 82px;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  grid-template-rows: 1fr auto;
  align-items: start;
  gap: 8px 10px;
  padding: 12px;
  border-radius: 14px;
  border: 1px solid rgba(42, 89, 140, 0.14);
  background: rgba(255, 255, 255, 0.84);
  color: #204765;
  transition: border-color 0.18s ease, background 0.18s ease, transform 0.18s ease;
}
.hvg-tab:hover {
  transform: translateY(-1px);
  border-color: rgba(43, 115, 199, 0.28);
  background: rgba(247, 251, 255, 0.98);
}
.hvg-tab.active {
  border-color: rgba(31, 93, 154, 0.48);
  background: linear-gradient(180deg, rgba(235, 246, 255, 0.98), rgba(255, 255, 255, 0.96));
  box-shadow: inset 0 0 0 1px rgba(31, 93, 154, 0.12);
}
.hvg-tab.skipped:not(.active) {
  background: rgba(255, 250, 237, 0.88);
  border-color: rgba(217, 119, 6, 0.18);
}
.hvg-tab-index {
  width: 30px;
  height: 30px;
  display: inline-grid;
  place-items: center;
  border-radius: 8px;
  background: rgba(219, 236, 255, 0.86);
  color: #1f5d9a;
  font-size: 0.78rem;
  font-weight: 800;
}
.hvg-tab.active .hvg-tab-index {
  background: #1f5d9a;
  color: #ffffff;
}
.hvg-tab-copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.hvg-tab-label {
  color: #143858;
  font-weight: 800;
  line-height: 1.16;
  overflow-wrap: anywhere;
}
.hvg-tab-note {
  color: #5d7690;
  font-size: 0.78rem;
  line-height: 1.25;
}
.hvg-tab-state {
  grid-column: 1 / -1;
  justify-self: start;
  padding: 3px 8px;
  border-radius: 999px;
  background: rgba(232, 244, 255, 0.9);
  color: #2c638f;
  font-size: 0.74rem;
  font-weight: 700;
}
.hvg-tab.skipped .hvg-tab-state {
  background: rgba(254, 243, 199, 0.92);
  color: #8a5b05;
}
.hvg-active-strip {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 0 0 18px;
  padding: 10px 12px;
  border-radius: 12px;
  border: 1px solid rgba(42, 89, 140, 0.12);
  background: rgba(255, 255, 255, 0.72);
  color: #5d7690;
}
.hvg-active-strip span {
  font-weight: 800;
  color: #1f5d9a;
}
.hvg-active-strip strong {
  color: #143858;
}
.hvg-active-strip small {
  color: #5d7690;
}
:deep(.hvg-table-block) {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
:deep(.hvg-table-meta) {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  color: #5d7690;
  font-size: 0.78rem;
}
:deep(.hvg-table-meta span) {
  padding: 4px 8px;
  border-radius: 999px;
  background: rgba(232, 244, 255, 0.78);
  border: 1px solid rgba(42, 89, 140, 0.1);
}
:deep(.hvg-table-wrap) {
  max-width: 100%;
}
:deep(.hvg-table-block.is-scrollable .hvg-table-wrap) {
  overflow: auto;
}
:deep(.hvg-table-block.is-scrollable .table thead th) {
  top: 0;
  z-index: 2;
}
:deep(.hvg-table-block.is-scrollable .table td) {
  max-width: 260px;
  white-space: nowrap;
}
:deep(.hvg-table-footer) {
  color: #5d7690;
  font-size: 0.82rem;
}
.download-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
.species-workbench {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-top: 14px;
}
.case-tab-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.case-tab {
  border: 1px solid #d5e3f2;
  border-radius: 999px;
  background: #fff;
  color: #244761;
  padding: 7px 11px;
  font-weight: 700;
  cursor: pointer;
}
.case-tab.active {
  border-color: #1f5d9a;
  background: rgba(232, 244, 255, 0.95);
  color: #174f82;
}
.compact-top {
  margin-top: 10px;
}
.small-kpi {
  font-size: 1rem;
  line-height: 1.3;
}
.table-wrap {
  overflow: auto;
}
.warning {
  background: rgba(255, 248, 230, 0.96);
  border-color: rgba(245, 158, 11, 0.26);
  color: #8a5b05;
}
@media (max-width: 1180px) {
  .hvg-tabbar {
    grid-template-columns: repeat(10, minmax(168px, 188px));
  }
}
@media (max-width: 760px) {
  .hvg-tabbar {
    grid-template-columns: repeat(10, minmax(156px, 172px));
    gap: 8px;
    margin-top: 10px;
  }
  .hvg-tab {
    min-height: 76px;
    padding: 10px;
  }
  .hvg-active-strip {
    align-items: flex-start;
    flex-direction: column;
    gap: 2px;
  }
  :deep(.hvg-table-block.is-scrollable .table td) {
    max-width: 220px;
  }
}
</style>
