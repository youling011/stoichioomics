<template>
  <div class="comparison-stack">
    <div v-if="loading" class="comparison-skeleton" aria-live="polite">
      <span v-for="item in 4" :key="item"></span>
    </div>
    <div v-else-if="error" class="comparison-state" role="alert">
      <h3>Comparison could not be loaded</h3>
      <p>{{ error }}</p>
      <button type="button" class="btn secondary" @click="load">Retry comparison</button>
    </div>
    <div v-else-if="!hasResults"><div class="comparison-state">
      <h3>{{ stateTitle }}</h3>
      <p>{{ summary.reason || 'No reliable gene-level Genome, Transcriptome or Proteome Core feature block was available.' }}</p>
      <small>Status: {{ comparisonStatus }}<template v-if="summary.error_id"> · Error ID: {{ summary.error_id }}</template></small>
    </div>
      <div class="comparison-grid"><article v-for="(title,index) in ['Largest distribution differences','Effect and global FDR','Feature-family evidence','Raw and adjusted evidence']" :key="title" class="card"><h3>{{title}}</h3><WorkflowChart :slot-id="'hvg.native.empty.'+['original_forest','original_omics_effect','original_family_heatmap','original_raw_adjusted'][index]" resource="hvg" :identifier="identifier" chart-id="H29" :params="{...visualParams,panel_profile:['original_forest','original_omics_effect','original_family_heatmap','original_raw_adjusted'][index]}" :height="420"><p class="muted">{{summary.reason || 'No finite saved comparison data for this original chart.'}}</p><small>Status: {{comparisonStatus}}</small></WorkflowChart></article></div>
    </div>
    <template v-else>
      <div class="comparison-note">
        <strong>Interpretation boundary</strong>
        <span>These are direct group associations. Effect size, confidence interval and FDR do not establish a causal mechanism and are not model importance.</span>
      </div>

      <section class="comparison-summary" aria-label="HVG versus non-HVG comparison summary">
        <div v-for="card in summaryCards" :key="card.label" class="comparison-metric">
          <span>{{ card.label }}</span>
          <strong>{{ card.value }}</strong>
          <small>{{ card.note }}</small>
        </div>
      </section>

      <div v-if="isLegacyV1" class="comparison-note historical-note">
        <strong>Historical comparison</strong>
        <span>This result uses the readable v1 comparison artifacts. Genome: Not computed in historical v1 result. New runs use the v2 multi-omics context and provenance contract.</span>
      </div>

      <section v-if="blockCoverage.length || hasMappingSummary" class="comparison-traceability">
        <article v-if="hasMappingSummary" class="comparison-panel source-panel">
          <header><h3>Source and gene mapping</h3><p>Source identity is species-scoped and resolved in batches. Ambiguous mappings remain explicit.</p></header>
          <dl><dt>Status</dt><dd>{{ mappingSummary.status || mappingSummary.mapping_status || '-' }}</dd><dt>Comparison source</dt><dd>{{ summary.scope?.source_mode || '-' }}</dd><dt>Requested blocks</dt><dd>{{ (summary.requested_omics || []).join(' + ') || '-' }}</dd><dt>Registry</dt><dd>{{ mappingSummary.registry_version || summary.registry_version || '-' }}</dd><dt>Builder</dt><dd>{{ mappingSummary.builder_version || '-' }}</dd><dt>Gate</dt><dd>{{ mappingGateText }}</dd></dl>
        </article>
        <article v-if="blockCoverage.length" class="comparison-panel">
          <header><h3>Core feature coverage</h3><p>Coverage is reported per requested omics block. Missing blocks remain visible in the audit.</p></header>
          <div class="comparison-table-wrap">
            <table class="table compact-table"><thead><tr><th>Omics</th><th>Status</th><th>Mapped genes</th><th>Raw match</th><th>Applicable match</th><th>Registered</th><th>Eligible</th><th>Materialized</th><th>Tested</th><th>Significant</th></tr></thead>
              <tbody><tr v-for="row in blockCoverage" :key="row.omics"><td>{{ row.omics }}</td><td><span class="comparison-status" :data-status="row.block_status">{{ row.block_status }}</span></td><td>{{ formatInteger(row.mapped_gene_count) }} / {{ formatInteger(row.expression_gene_count) }}</td><td>{{ formatP(row.raw_match_rate) }}</td><td>{{ formatP(row.applicable_match_rate) }}</td><td>{{ formatInteger(row.registered_core_fields) }}</td><td>{{ formatInteger(row.eligible_fields) }}</td><td>{{ formatInteger(row.materialized_eligible_fields) }}</td><td>{{ formatInteger(row.tested_fields) }}</td><td>{{ formatInteger(row.significant_fields) }}</td></tr></tbody>
            </table>
          </div>
        </article>
      </section>

      <section class="comparison-grid">
        <article class="comparison-panel">
          <header><h3>Largest distribution differences</h3><p>Cliff’s delta with 95% confidence intervals. Select a point to inspect its audit trail.</p></header>
          <WorkflowChart slot-id="hvg.native.HvgGroupComparisonPanel.2" resource="hvg" :identifier="identifier" chart-id="H29" :params="{...visualParams,panel_profile:'original_forest'}" :height="390" @inspect="({row})=>row.feature_key && showFeature(row)"><EChart :option="forestOption" :height="390" @chart-click="showFeatureByChart" /></WorkflowChart>
        </article>
        <article class="comparison-panel">
          <header><h3>Effect and global FDR</h3><p>All tested numeric Core features; color identifies the resolved omics layer.</p></header>
          <WorkflowChart slot-id="hvg.native.HvgGroupComparisonPanel.3" resource="hvg" :identifier="identifier" chart-id="H29" :params="{...visualParams,panel_profile:'original_omics_effect'}" :height="390" @inspect="({row})=>row.feature_key && showFeature(row)"><EChart :option="effectFdrOption" :height="390" @chart-click="showFeatureByChart" /></WorkflowChart>
        </article>
        <article class="comparison-panel">
          <header><h3>Feature-family evidence</h3><p>Each point is a saved omics family: tested fields on x, significant fields on y.</p></header>
          <WorkflowChart slot-id="hvg.native.HvgGroupComparisonPanel.4" resource="hvg" :identifier="identifier" chart-id="H29" :params="{...visualParams,panel_profile:'original_family_heatmap'}" :height="390" @inspect="({row})=>row.feature_key && showFeature(row)"><EChart :option="familyHeatmapOption" :height="390" /></WorkflowChart>
        </article>
        <article class="comparison-panel">
          <header><h3>Raw and adjusted evidence</h3><p>Raw and adjusted estimands remain distinct. When adjusted fits are unavailable, saved quantile-range evidence and the actual fit reasons are shown.</p></header>
          <WorkflowChart slot-id="hvg.native.HvgGroupComparisonPanel.5" resource="hvg" :identifier="identifier" chart-id="H29" :params="{...visualParams,panel_profile:'original_raw_adjusted'}" :height="390" @inspect="({row})=>row.feature_key && showFeature(row)"><EChart :option="rawAdjustedOption" :height="390" @chart-click="showFeatureByChart" /></WorkflowChart>
        </article>
      </section>

      <section class="comparison-panel">
        <header class="comparison-table-header">
          <div><h3>Core feature audit and statistics</h3><p>Every field in each resolved block is tested, described, skipped or excluded with a reason.</p></div>
          <span>{{ featurePayload.total || 0 }} fields</span>
        </header>
        <div class="comparison-filters">
          <label>Search<input v-model.trim="filters.search" type="search" placeholder="Feature name or key" /></label>
          <label>Omics<select v-model="filters.omics"><option value="">All</option><option v-for="value in omicsOptions" :key="value" :value="value">{{ value }}</option></select></label>
          <label>Family<select v-model="filters.family"><option value="">All</option><option v-for="value in familyOptions" :key="value" :value="value">{{ value }}</option></select></label>
          <label>Status<select v-model="filters.status"><option value="">All</option><option v-for="value in statusOptions" :key="value" :value="value">{{ value }}</option></select></label>
          <label>Evidence<select v-model="filters.evidence"><option value="">All</option><option v-for="value in evidenceOptions" :key="value" :value="value">{{ humanize(value) }}</option></select></label>
          <label>Direction<select v-model="filters.direction"><option value="">All</option><option v-for="value in directionOptions" :key="value" :value="value">{{ humanize(value) }}</option></select></label>
          <label>Adjustment<select v-model="filters.adjustment"><option value="">All</option><option v-for="value in adjustmentOptions" :key="value" :value="value">{{ humanize(value) }}</option></select></label>
          <label>Significance<select v-model="filters.significant"><option value="">All</option><option value="true">FDR &lt; 0.05</option><option value="false">FDR ≥ 0.05</option></select></label>
          <label>Sort<select v-model="sortBy"><option value="abs_effect">Absolute effect</option><option value="global_fdr">Global FDR</option><option value="missing_rate_hvg">HVG missingness</option><option value="feature_key">Feature key</option></select></label>
          <button type="button" class="btn" @click="applyFilters">Apply filters</button>
        </div>
        <div class="comparison-table-wrap">
          <table class="table compact-table comparison-table">
            <thead><tr><th>Feature</th><th>Omics</th><th>Family</th><th>Status</th><th>n HVG / non-HVG</th><th>Effect</th><th>95% CI</th><th>Global FDR</th><th>Adjusted OR</th><th>Adjusted FDR</th><th>Warnings / reason</th><th></th></tr></thead>
            <tbody>
              <tr v-for="row in featurePayload.rows || []" :key="row.feature_key">
                <td><strong>{{ row.display_name || row.feature_name }}</strong><small>{{ row.feature_key }}</small></td>
                <td>{{ row.omics_layer }}</td><td>{{ row.family }}</td><td><span class="comparison-status" :data-status="row.status">{{ row.status }}</span></td>
                <td>{{ formatInteger(row.n_hvg) }} / {{ formatInteger(row.n_nonhvg) }}</td>
                <td>{{ formatNumber(row.effect_value) }}<small>{{ humanize(row.effect_type) }}</small></td><td>{{ formatInterval(row.effect_ci_low, row.effect_ci_high) }}</td>
                <td>{{ formatP(row.global_fdr) }}</td><td>{{ formatNumber(row.adjusted_odds_ratio) }}</td><td>{{ formatP(row.adjusted_global_fdr) }}</td>
                <td>{{ row.warnings || row.reason || row.adjusted_reason || '-' }}</td>
                <td><button type="button" class="feature-detail-button" @click="showFeature(row)">View feature</button></td>
              </tr>
              <tr v-if="!(featurePayload.rows || []).length"><td colspan="12">No fields match the current filters.</td></tr>
            </tbody>
          </table>
        </div>
        <footer class="comparison-pagination">
          <button type="button" class="btn secondary" :disabled="page <= 1" @click="changePage(page - 1)">Previous page</button>
          <span>Page {{ page }} of {{ pageCount }}</span>
          <button type="button" class="btn secondary" :disabled="page >= pageCount" @click="changePage(page + 1)">Next page</button>
        </footer>
      </section>

      <section v-if="detail" class="comparison-panel feature-detail" aria-live="polite">
        <header class="comparison-table-header"><div><h3>{{ detail.feature?.display_name || detail.feature?.feature_name }}</h3><p>{{ detail.feature?.feature_key }} · {{ detail.feature?.unit || 'unit not specified' }}</p></div><button type="button" class="btn secondary" @click="detail = null">Close detail</button></header>
        <div class="feature-detail-grid">
          <WorkflowChart slot-id="hvg.native.HvgGroupComparisonPanel.6" resource="hvg" :identifier="identifier" chart-id="H29" :params="{...visualParams,panel_profile:'original_quantiles',feature_key:detail?.feature?.feature_key}" :height="330" @inspect="({row})=>row.feature_key && showFeature(row)"><EChart :option="detailDistributionOption" :height="330" /></WorkflowChart>
          <dl>
            <template v-for="item in detailMetadata" :key="item.label"><dt>{{ item.label }}</dt><dd>{{ item.value }}</dd></template>
          </dl>
        </div>
      </section>

      <section v-if="downloadItems.length" class="comparison-downloads">
        <strong>Comparison files</strong>
        <a v-for="item in downloadItems" :key="item.label" :href="item.url" target="_blank" rel="noopener">{{ item.label }}</a>
      </section>
    </template>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import EChart from './EChart.vue'
import WorkflowChart from './workflow/WorkflowChart.vue'
import {
  buildHvgDownloadUrl,
  getHvgGroupComparisonFeature,
  getHvgGroupComparisonFeatures,
  getHvgGroupComparisonSummary,
} from '../api/hvg'

const props = defineProps({
  identifier: { type: String, required: true },
  visualParams: { type:Object, default:()=>({}) },
  isCase5: { type: Boolean, default: false },
  embeddedComparison: { type: Object, default: null },
  case5Comparison: { type: Object, default: null },
})

const loading = ref(false)
const error = ref('')
const summary = ref({})
const featurePayload = ref({ total: 0, rows: [] })
const detail = ref(null)
const page = ref(1)
const pageSize = 50
const sortBy = ref('abs_effect')
const filters = ref({ search: '', omics: '', family: '', status: '', evidence: '', direction: '', adjustment: '', significant: '' })
const appliedFilters = ref({ ...filters.value })

const comparisonStatus = computed(() => summary.value.comparison_status || summary.value.status || 'legacy_not_generated')
const hasResults = computed(() => ['complete', 'partial'].includes(comparisonStatus.value) && Number(summary.value.counts?.tested_fields || 0) > 0)
const isLegacyV1 = computed(() => String(summary.value.comparison_schema_version || summary.value.schema_version || '').toLowerCase() === 'hvg_nonhvg_v1')
const mappingSummary = computed(() => summary.value.mapping_summary || summary.value.hvg_multiomics_mapping_summary || {})
const blockCoverage = computed(() => summary.value.block_coverage || summary.value.hvg_nonhvg_block_coverage || [])
const hasMappingSummary = computed(() => Object.keys(mappingSummary.value || {}).length > 0)
const mappingGateText = computed(() => {
  const blocks = mappingSummary.value.blocks || {}
  const values = Object.values(blocks).map(item => `${item.omics || '-'} ${formatP(item.gate_match_rate_used ?? item.raw_match_rate)} / ${formatInteger(item.min_required_mapped_genes)} genes`)
  return values.join('; ') || 'Per-block threshold: 70% and 40 mapped genes'
})
const stateTitle = computed(() => ({
  unavailable: 'Comparison is unavailable for this input',
  failed: 'Comparison branch failed',
  legacy_not_generated: 'Comparison has not been generated for this historical result',
}[comparisonStatus.value] || 'No comparison result available'))
const pageCount = computed(() => Math.max(1, Math.ceil(Number(featurePayload.value.total || 0) / pageSize)))

const summaryCards = computed(() => {
  const counts = summary.value.counts || {}
  return [
    { label: 'Genes compared', value: `${formatInteger(summary.value.n_hvg)} / ${formatInteger(summary.value.n_nonhvg)}`, note: 'HVG / non-HVG' },
    { label: 'Resolved blocks', value: (summary.value.resolved_blocks || []).join(' + ') || '-', note: `${(summary.value.requested_omics || []).length || 3} requested Core blocks` },
    { label: 'Core fields audited', value: formatInteger(counts.audited_core_fields ?? counts.registry_fields), note: `${formatInteger(counts.eligible_candidate_fields)} eligible · ${formatInteger(counts.conditional_fields)} conditional` },
    { label: 'Eligible candidates', value: formatInteger(counts.eligible_candidate_fields), note: `${formatInteger(counts.materialized_candidate_fields)} materialized` },
    { label: 'Materialized fields', value: formatInteger(counts.materialized_candidate_fields), note: `${formatInteger(counts.discovered_fields)} discovered` },
    { label: 'Tested fields', value: formatInteger(counts.tested_fields), note: 'Primary global-BH hypotheses' },
    { label: 'Descriptive / skipped', value: `${formatInteger(counts.descriptive_only_fields)} / ${formatInteger(counts.skipped_candidate_fields ?? counts.skipped_fields)}`, note: 'Descriptive-only / candidate skipped' },
    { label: 'Global FDR < 0.05', value: formatInteger(counts.global_fdr_lt_0_05), note: `${formatInteger(counts.moderate_strong_fields)} moderate or strong` },
    { label: 'Adjusted robust', value: formatInteger(counts.adjusted_robust_fields), note: `registry ${summary.value.registry_version || '-'}` },
    { label: 'Contract version', value: summary.value.comparison_schema_version || summary.value.schema_version || '-', note: `evidence ${summary.value.evidence_rule_version || '-'}` },
  ]
})

const validNumeric=value=>value!==null&&value!==undefined&&value!==''&&Number.isFinite(Number(value))
const plotPayload = computed(() => summary.value.plots || {})
const filterPlotRows = rows => (rows || []).filter(row =>
  (!appliedFilters.value.omics || row.omics_layer === appliedFilters.value.omics) &&
  (!appliedFilters.value.family || row.family === appliedFilters.value.family) &&
  (!appliedFilters.value.evidence || row.evidence_level === appliedFilters.value.evidence) &&
  (!appliedFilters.value.direction || row.direction === appliedFilters.value.direction)
)
const forestRows = computed(() => filterPlotRows(plotPayload.value.effect_forest || summary.value.top_features || []))
const forestOption = computed(() => {
  const rows = forestRows.value.filter(r=>validNumeric(r.effect_value)).slice(0, 18).reverse()
  return {
    tooltip: { trigger: 'item', formatter: ({ data }) => traceTooltip(data.raw, `Cliff’s delta: ${formatNumber(data.raw?.effect_value)}<br/>95% CI: ${formatInterval(data.raw?.effect_ci_low, data.raw?.effect_ci_high)}`) },
    grid: { left: 150, right: 34, top: 24, bottom: 48 },
    xAxis: { type: 'value', name: 'Cliff’s delta', min: -1, max: 1, splitLine: { lineStyle: { color: '#e4edf5' } } },
    yAxis: { type: 'category', data: rows.map(row => row.display_name || row.feature_name), axisLabel: { width: 136, overflow: 'truncate' } },
    series: [{ type: 'custom', encode:{x:[1,2],y:0}, silent: true, renderItem: (params, api) => { if(!validNumeric(api.value(1))||!validNumeric(api.value(2)))return; const y = api.coord([0, api.value(0)])[1]; const low = api.coord([api.value(1), api.value(0)])[0]; const high = api.coord([api.value(2), api.value(0)])[0]; return { type: 'line', shape: { x1: low, y1: y, x2: high, y2: y }, style: { stroke: '#7594ad', lineWidth: 2 } } }, data: rows.map((row, index) => [index, validNumeric(row.effect_ci_low)?Number(row.effect_ci_low):null, validNumeric(row.effect_ci_high)?Number(row.effect_ci_high):null]) }, { type: 'scatter', symbolSize: 9, itemStyle: { color: '#1f5d9a' }, data: rows.map((row, index) => ({ name: row.display_name || row.feature_name, value: [Number(row.effect_value || 0), index], raw: row })) }],
  }
})

const effectFdrOption = computed(() => {
  const rows = filterPlotRows(plotPayload.value.effect_fdr_scatter || []).filter(r=>validNumeric(r.effect_value)&&validNumeric(r.global_fdr))
  const colors = { genome: '#2c7a63', transcriptome: '#1f6fae', proteome: '#b44e3a' }
  const omics = [...new Set(rows.map(row => row.omics_layer).filter(Boolean))]
  return {
    tooltip: { trigger: 'item', formatter: ({ data }) => traceTooltip(data.raw, `${humanize(data.raw.effect_type)}: ${formatNumber(data.raw.effect_value)}`) },
    legend: { data: omics, bottom: 0 }, grid: { left: 62, right: 24, top: 24, bottom: 58 },
    xAxis: { type: 'value', name: 'Effect size', splitLine: { lineStyle: { color: '#e4edf5' } } }, yAxis: { type: 'value', name: '-log10(FDR)' },
    series: omics.map(layer => ({ name: layer, type: 'scatter', symbolSize: 9, itemStyle: { color: colors[layer] || '#536f87' }, data: rows.filter(row => row.omics_layer === layer).map(row => ({ name: row.display_name || row.feature_key, value: [Number(row.effect_value || 0), -Math.log10(Math.max(Number(row.global_fdr ?? 1), 1e-300))], raw: row })) })),
  }
})

const familyHeatmapOption = computed(() => {
  const rows = (plotPayload.value.family_heatmap || summary.value.family_summary || []).filter(row =>
    validNumeric(row.median_effect) && (!appliedFilters.value.omics || row.omics_layer === appliedFilters.value.omics) &&
    (!appliedFilters.value.family || row.family === appliedFilters.value.family)
  )
  const omics = [...new Set(rows.map(row => row.omics_layer))]
  const families = [...new Set(rows.map(row => row.family))]
  return { tooltip: { formatter: ({ data }) => `${data.raw.omics_layer} / ${data.raw.family}<br/>Median tested effect: ${formatNumber(data.raw.median_effect)}<br/>Tested: ${formatInteger(data.raw.tested_fields)} · significant: ${formatInteger(data.raw.significant_fields)}<br/>Scope: display summary of the persisted global-BH results` }, grid: { left: 128, right: 24, top: 28, bottom: 48 }, xAxis: { type: 'category', data: omics }, yAxis: { type: 'category', data: families, axisLabel: { width: 116, overflow: 'truncate' } }, visualMap: { min: -0.5, max: 0.5, calculable: true, orient: 'horizontal', left: 'center', bottom: 0, inRange: { color: ['#b44e3a', '#f5f7f9', '#1f6fae'] } }, series: [{ type: 'heatmap', data: rows.map(row => ({ value: [omics.indexOf(row.omics_layer), families.indexOf(row.family), Number(row.median_effect || 0)], raw: row })) }] }
})

const rawAdjustedOption = computed(() => {
  const rows = filterPlotRows(plotPayload.value.raw_vs_adjusted || []).filter(r=>validNumeric(r.effect_value)&&validNumeric(r.coefficient_per_sd)).filter(row => !appliedFilters.value.adjustment || appliedFilters.value.adjustment === 'tested')
  return { tooltip: { formatter: ({ data }) => traceTooltip(data.raw, `Raw ${humanize(data.raw.effect_type)}: ${formatNumber(data.raw.effect_value)}<br/>Adjusted coefficient per SD: ${formatNumber(data.raw.coefficient_per_sd)}<br/>Adjusted FDR: ${formatP(data.raw.adjusted_global_fdr)}<br/>Adjusted scope: all successfully fitted target coefficients`) }, grid: { left: 64, right: 24, top: 24, bottom: 50 }, xAxis: { type: 'value', name: 'Raw effect size', splitLine: { lineStyle: { color: '#e4edf5' } } }, yAxis: { type: 'value', name: 'Adjusted coefficient' }, series: [{ type: 'scatter', symbolSize: 9, itemStyle: { color: '#536f87' }, data: rows.map(row => ({ name: row.display_name || row.feature_key, value: [Number(row.effect_value || 0), Number(row.coefficient_per_sd || 0)], raw: row })) }] }
})

const omicsOptions = computed(() => [...new Set([...(summary.value.requested_omics || []), ...(summary.value.resolved_blocks || []), ...blockCoverage.value.map(row => row.omics)].filter(Boolean))])
const familyOptions = computed(() => [...new Set((summary.value.family_summary || []).map(row => row.family).filter(Boolean))].sort())
const statusOptions = computed(() => [...new Set(['tested', 'descriptive_only', 'skipped', 'excluded', ...((props.isCase5 || props.embeddedComparison) ? mergeCase5Rows(summary.value) : (featurePayload.value.rows || [])).map(row => row.status).filter(Boolean)])])
const optionSourceRows = computed(() => [...(plotPayload.value.effect_fdr_scatter || []), ...((props.isCase5 || props.embeddedComparison) ? mergeCase5Rows(summary.value) : (featurePayload.value.rows || []))])
const evidenceOptions = computed(() => [...new Set(optionSourceRows.value.map(row => row.evidence_level).filter(Boolean))].sort())
const directionOptions = computed(() => [...new Set(optionSourceRows.value.map(row => row.direction).filter(Boolean))].sort())
const adjustmentOptions = computed(() => [...new Set(['tested', 'skipped', 'failed', ...((props.isCase5 || props.embeddedComparison) ? mergeCase5Rows(summary.value) : (featurePayload.value.rows || [])).map(row => row.adjusted_status).filter(Boolean)])])
const downloadItems = computed(() => {
  if (props.embeddedComparison) return []
  if (props.isCase5) return Object.entries(props.case5Comparison?.downloads || {}).map(([label, url]) => ({ label: label.replaceAll('_', ' '), url }))
  return [
    ['Feature audit', 'hvg_nonhvg_feature_audit'], ['Feature comparison', 'hvg_nonhvg_feature_comparison'],
    ['Adjusted comparison', 'hvg_nonhvg_adjusted_comparison'], ['Distribution quantiles', 'hvg_nonhvg_distribution_quantiles'],
    ['Family summary', 'hvg_nonhvg_family_summary'], ['Plots payload', 'hvg_nonhvg_plots'],
    ['Summary', 'hvg_nonhvg_summary'], ['Run manifest', 'hvg_nonhvg_manifest'],
    ['Multi-omics Core context', 'hvg_multiomics_core_features'],
    ['Feature provenance', 'hvg_multiomics_feature_provenance'],
    ['Mapping table', 'hvg_multiomics_mapping_table'],
    ['Mapping summary', 'hvg_multiomics_mapping_summary'],
    ['Assembly manifest', 'hvg_multiomics_assembly_manifest'],
    ['Block coverage', 'hvg_nonhvg_block_coverage'],
  ].map(([label, kind]) => ({ label, url: buildHvgDownloadUrl(props.identifier, kind) }))
})

const detailMetadata = computed(() => {
  const row = detail.value?.feature || {}
  return [
    ['Description', row.description], ['Omics / source block', `${row.omics_layer || '-'} / ${row.source_block || '-'}`],
    ['Family / semantic type', `${row.family || '-'} / ${row.semantic_type || '-'}`], ['Unit', row.unit],
    ['Source column', row.source_column], ['Provenance resolution', row.provenance_resolution],
    ['Applicability', row.applicability], ['Zero semantics', row.zero_semantics],
    ['Applicable n total / HVG / non-HVG', `${formatInteger(row.n_applicable_total)} / ${formatInteger(row.n_applicable_hvg)} / ${formatInteger(row.n_applicable_non_hvg)}`],
    ['Valid n HVG / non-HVG', `${formatInteger(row.n_valid_hvg)} / ${formatInteger(row.n_valid_non_hvg)}`],
    ['Composition / redundancy group', `${row.composition_group || '-'} / ${row.redundancy_group || '-'}`],
    ['Composition interpretation', row.composition_group ? 'Sum-constrained components; interpret jointly.' : '-'],
    ['Scaling / transform hint', `${row.scaling_hint || '-'} / ${row.transform_hint || '-'}`],
    ['Audit status / reason', `${row.status || '-'} / ${row.reason || '-'}`],
    ['HVG n / missing', `${formatInteger(row.n_hvg)} / ${formatP(row.missing_rate_hvg)}`],
    ['Non-HVG n / missing', `${formatInteger(row.n_nonhvg)} / ${formatP(row.missing_rate_nonhvg)}`],
    ['HVG mean / median', `${formatNumber(row.mean_hvg)} / ${formatNumber(row.median_hvg)}`],
    ['Non-HVG mean / median', `${formatNumber(row.mean_nonhvg)} / ${formatNumber(row.median_nonhvg)}`],
    ['Mean / median difference', `${formatNumber(row.mean_diff)} / ${formatNumber(row.median_diff)}`],
    ['Effect definition / value', `${humanize(row.effect_type)} / ${formatNumber(row.effect_value)}`],
    ['Effect 95% CI', formatInterval(row.effect_ci_low, row.effect_ci_high)],
    ['Test / statistic', `${row.test_name || '-'} / ${formatNumber(row.statistic)}`],
    ['P / global FDR', `${formatP(row.p_value)} / ${formatP(row.global_fdr)}`],
    ['Omics / family FDR', `${formatP(row.omics_fdr)} / ${formatP(row.family_fdr)}`],
    ['Evidence / direction', `${humanize(row.evidence_level)} / ${humanize(row.direction)}`],
    ['Adjusted status / reason', `${row.adjusted_status || row.fit_status || '-'} / ${row.adjusted_reason || row.failure_reason || '-'}`],
    ['Adjusted n / covariates', `${formatInteger(row.n_used)} / ${row.adjusted_covariates || row.covariates_used || row.covariates || '-'}`],
    ['Adjusted OR / 95% CI', `${formatNumber(row.adjusted_odds_ratio)} / ${formatInterval(row.adjusted_ci_low, row.adjusted_ci_high)}`],
    ['Adjusted p / FDR', `${formatP(row.adjusted_p_value)} / ${formatP(row.adjusted_global_fdr)}`],
    ['Adjustment policy / transform', `${row.policy_version || '-'} / ${row.adjustment_transform || '-'}`],
    ['Collinearity action', row.collinearity_action], ['Warnings', [row.warnings, row.adjusted_warnings].filter(Boolean).join('; ') || '-'],
  ].map(([label, value]) => ({ label, value: value ?? '-' }))
})

const detailDistributionOption = computed(() => {
  const quantiles = detail.value?.quantiles || []
  const byGroup = Object.fromEntries(quantiles.map(row => [row.group, row]))
  const groups = ['nonhvg', 'hvg'].filter(group => byGroup[group])
  return { tooltip: { trigger: 'item' }, grid: { left: 64, right: 24, top: 24, bottom: 50 }, xAxis: { type: 'category', data: groups.map(group => group === 'hvg' ? 'HVG' : 'non-HVG') }, yAxis: { type: 'value', name: detail.value?.feature?.unit || '' }, series: [{ type: 'boxplot', itemStyle: { color: '#d9e9f6', borderColor: '#1f5d9a' }, data: groups.map(group => { const row = byGroup[group]; return [Number(row.min), Number(row.q25), Number(row.median), Number(row.q75), Number(row.max)] }) }] }
})

function mergeCase5Rows(payload) {
  const comparison = Object.fromEntries((payload.features || []).map(row => [row.feature_key, row]))
  const adjusted = Object.fromEntries((payload.adjusted || []).map(row => [row.feature_key, row]))
  return (payload.audit || []).map(row => {
    const adjustedRow = adjusted[row.feature_key] || {}
    return {
      ...row,
      ...(comparison[row.feature_key] || {}),
      ...Object.fromEntries(Object.entries(adjustedRow).map(([key, value]) => {
        const aliases = { effect_ci_low: 'adjusted_ci_low', effect_ci_high: 'adjusted_ci_high', p_value: 'adjusted_p_value', reason: 'adjusted_reason', warnings: 'adjusted_warnings', covariates: 'adjusted_covariates' }
        return [aliases[key] || key, value]
      })),
    }
  })
}

async function load() {
  loading.value = true
  error.value = ''
  detail.value = null
  try {
    if ((props.isCase5 || props.embeddedComparison)) {
      summary.value = props.embeddedComparison || props.case5Comparison || { status: 'legacy_not_generated', comparison_status: 'legacy_not_generated' }
      loadCase5Page()
    } else {
      summary.value = await getHvgGroupComparisonSummary(props.identifier)
      await loadFeatures()
    }
  } catch (cause) {
    error.value = cause?.response?.data?.error?.message || cause?.message || 'Failed to load comparison results.'
  } finally {
    loading.value = false
  }
}

async function loadFeatures() {
  featurePayload.value = await getHvgGroupComparisonFeatures(props.identifier, { page: page.value, page_size: pageSize, sort_by: sortBy.value, sort_order: 'desc', ...appliedFilters.value })
}

function loadCase5Page() { const active = appliedFilters.value; const rows = mergeCase5Rows(summary.value).filter(row => (!active.search || [row.feature_key, row.feature_name, row.display_name].some(value => String(value || '').toLowerCase().includes(active.search.toLowerCase()))) && (!active.omics || row.omics_layer === active.omics) && (!active.family || row.family === active.family) && (!active.status || row.status === active.status) && (!active.evidence || row.evidence_level === active.evidence) && (!active.direction || row.direction === active.direction) && (!active.adjustment || row.adjusted_status === active.adjustment) && (!active.significant || (active.significant === 'true' ? Number(row.global_fdr) < 0.05 : Number(row.global_fdr) >= 0.05))); const start = (page.value - 1) * pageSize; featurePayload.value = { total: rows.length, rows: rows.slice(start, start + pageSize) } }
async function applyFilters() { appliedFilters.value = { ...filters.value }; page.value = 1; if ((props.isCase5 || props.embeddedComparison)) loadCase5Page(); else await loadFeatures() }
async function changePage(next) { page.value = next; if ((props.isCase5 || props.embeddedComparison)) loadCase5Page(); else await loadFeatures() }
async function showFeature(row) { if ((props.isCase5 || props.embeddedComparison)) { const quantiles = (summary.value.quantiles || []).filter(item => item.feature_key === row.feature_key); detail.value = { feature: row, quantiles } } else detail.value = await getHvgGroupComparisonFeature(props.identifier, row.feature_key) }
async function showFeatureByChart(event) { const row = event?.data?.raw; if (row?.feature_key) await showFeature(row) }

function traceTooltip(row = {}, effectLine = '') { return `${row.display_name || row.feature_name || row.feature_key}<br/>${row.omics_layer || '-'} / ${row.family || '-'}<br/>${effectLine}<br/>n HVG / non-HVG: ${formatInteger(row.n_hvg)} / ${formatInteger(row.n_nonhvg)}<br/>Missingness: ${formatP(row.missing_rate_hvg)} / ${formatP(row.missing_rate_nonhvg)}<br/>Global FDR: ${formatP(row.global_fdr)}<br/>Scope: BH across all tested hypotheses` }
function humanize(value) { return value ? String(value).replaceAll('_', ' ') : '-' }

function formatNumber(value) { if(!validNumeric(value))return '—';const number = Number(value); return Number.isFinite(number) ? number.toFixed(4).replace(/0+$/, '').replace(/\.$/, '') : '-' }
function formatInteger(value) { if(!validNumeric(value))return '—';const number = Number(value); return Number.isFinite(number) ? Math.round(number).toLocaleString() : '-' }
function formatP(value) { if(!validNumeric(value))return '—';const number = Number(value); if (!Number.isFinite(number)) return '-'; return number < 0.0001 ? number.toExponential(2) : number.toFixed(4) }
function formatInterval(low, high) { return `${formatNumber(low)} to ${formatNumber(high)}` }

watch(() => [props.identifier, props.case5Comparison, props.embeddedComparison], load, { immediate: true, deep: true })
</script>

<style scoped>
.comparison-stack { display: flex; flex-direction: column; gap: 18px; }
.comparison-skeleton { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }
.comparison-skeleton span { min-height: 104px; border-radius: 12px; background: #eaf1f6; animation: comparison-pulse 1.2s ease-in-out infinite alternate; }
@keyframes comparison-pulse { to { background: #f5f8fa; } }
.comparison-summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; }
.comparison-metric { min-height: 106px; padding: 15px; border: 1px solid #d6e2ec; border-radius: 12px; background: #fff; display: flex; flex-direction: column; gap: 6px; }
.comparison-metric span, .comparison-metric small { color: #5d7182; }
.comparison-metric strong { color: #173d59; font-size: 1.35rem; }
.comparison-note { display: flex; gap: 10px; align-items: baseline; padding: 12px 14px; border: 1px solid #d6e2ec; border-radius: 10px; background: #f5f8fb; color: #334f64; }
.comparison-note strong { color: #173d59; white-space: nowrap; }
.comparison-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.comparison-traceability { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(280px, .65fr); gap: 16px; }
.comparison-traceability .comparison-panel { min-width: 0; }
.source-panel dl { display: grid; grid-template-columns: minmax(120px, .65fr) minmax(0, 1.35fr); margin: 0; }
.source-panel dt, .source-panel dd { margin: 0; padding: 8px 4px; border-bottom: 1px solid #e5edf3; }
.source-panel dt { color: #5c7385; font-weight: 700; }.source-panel dd { color: #213f55; overflow-wrap: anywhere; }
.historical-note { background: #fff8ea; border-color: #ead7a8; }
.comparison-panel { padding: 18px; border: 1px solid #d6e2ec; border-radius: 12px; background: #fff; }
.comparison-panel header h3 { margin: 0; color: #173d59; }
.comparison-panel header p { margin: 5px 0 14px; color: #607789; }
.comparison-table-header { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }
.comparison-table-header > span { color: #405f76; font-weight: 700; white-space: nowrap; }
.comparison-filters { display: flex; flex-wrap: wrap; gap: 10px; align-items: end; margin: 14px 0; }
.comparison-filters label { display: flex; flex-direction: column; gap: 5px; color: #405f76; font-size: .82rem; font-weight: 700; }
.comparison-filters input, .comparison-filters select { min-width: 145px; min-height: 38px; border: 1px solid #bdccd8; border-radius: 8px; background: #fff; color: #173d59; padding: 7px 9px; }
.comparison-filters input:focus-visible, .comparison-filters select:focus-visible, .feature-detail-button:focus-visible { outline: 3px solid rgba(31,93,154,.24); outline-offset: 1px; }
.comparison-table-wrap { max-width: 100%; overflow: auto; }
.comparison-table { min-width: 1320px; }
.comparison-table td:first-child { max-width: 250px; }
.comparison-table td:first-child small { display: block; margin-top: 3px; color: #677e90; overflow-wrap: anywhere; }
.comparison-table td:nth-child(6) small { display: block; margin-top: 3px; color: #677e90; white-space: nowrap; }
.comparison-status { display: inline-flex; padding: 3px 7px; border-radius: 999px; background: #edf3f7; color: #385a71; font-size: .78rem; font-weight: 700; }
.comparison-status[data-status="tested"] { background: #e4f3ec; color: #17633f; }
.comparison-status[data-status="skipped"], .comparison-status[data-status="excluded"] { background: #f7efe2; color: #76521e; }
.comparison-status[data-status="failed"], .comparison-status[data-status="unavailable"] { background: #f9e8e8; color: #8b2f2f; }
.feature-detail-button { border: 0; background: transparent; color: #175d94; font-weight: 700; cursor: pointer; white-space: nowrap; }
.comparison-pagination { display: flex; justify-content: flex-end; align-items: center; gap: 12px; margin-top: 14px; color: #536b7d; }
.comparison-state { padding: 24px; border: 1px solid #d6e2ec; border-radius: 12px; background: #f7f9fb; color: #405f76; }
.comparison-state h3 { margin-top: 0; color: #173d59; }
.feature-detail-grid { display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(260px, .8fr); gap: 18px; }
.feature-detail dl { display: grid; grid-template-columns: minmax(110px, .7fr) minmax(0, 1.3fr); align-content: start; margin: 0; }
.feature-detail dt, .feature-detail dd { margin: 0; padding: 8px 6px; border-bottom: 1px solid #e5edf3; }
.feature-detail dt { color: #5c7385; font-weight: 700; }.feature-detail dd { color: #213f55; overflow-wrap: anywhere; }
.comparison-downloads { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }.comparison-downloads a { color: #175d94; font-weight: 700; }
@media (max-width: 900px) { .comparison-grid, .comparison-traceability, .feature-detail-grid { grid-template-columns: 1fr; }.comparison-note { align-items: flex-start; flex-direction: column; }.comparison-table-header { flex-direction: column; } }
@media (prefers-reduced-motion: reduce) { .comparison-skeleton span { animation: none; } }
</style>
