<template>
  <div class="page-stack">
    <p v-if="loading" class="muted">Loading entity report...</p>
    <section v-else-if="error" class="panel">
      <h2>Entity report unavailable</h2>
      <p class="error-text">{{ error }}</p>
      <router-link class="btn subtle" to="/entity-search">Back to Entity Explorer</router-link>
    </section>

    <template v-else-if="report">
      <EntityReportHeader :identity="report.entity_identity" :cards="report.overview_cards" />

      <section class="panel">
        <div class="section-header compact">
          <div>
            <h3>Key findings</h3>
            <p>Evidence is separated into raw features, derived proxy indicators, candidate labels, and cross-omics evidence.</p>
          </div>
        </div>
        <EntityEvidenceBadges :evidence="evidence" />
        <ul class="clean-list compact-list key-findings">
          <li v-for="finding in keyFindings" :key="finding">{{ finding }}</li>
        </ul>
      </section>

      <section v-if="model8CaseEvidence" class="panel">
        <div class="section-header compact">
          <div>
            <h3>Model-8 case evidence</h3>
            <p>This entity is included in the fixed eight-organism Case 3 evidence chain as a descriptive candidate or matched control.</p>
          </div>
          <span class="badge">{{ model8CaseEvidence.direction }}</span>
        </div>
        <div class="grid grid-4">
          <div class="card">
            <div class="label">Role</div>
            <div class="kpi small-kpi">{{ model8CaseEvidence.candidate_role }}</div>
          </div>
          <div class="card">
            <div class="label">Pair</div>
            <div class="kpi small-kpi">{{ model8CaseEvidence.pair_id }}</div>
          </div>
          <div class="card">
            <div class="label">Residual z</div>
            <div class="kpi small-kpi">{{ format(model8CaseEvidence.residual_z) }}</div>
          </div>
          <div class="card">
            <div class="label">Function evidence</div>
            <div class="kpi small-kpi">GO {{ model8CaseEvidence.go_count || 0 }} / KEGG {{ model8CaseEvidence.kegg_count || 0 }}</div>
          </div>
        </div>
        <p class="annotation">Badge label: Model-8 case evidence. This label is not causal, regulatory, or adaptive interpretation.</p>
      </section>

      <section class="panel">
        <div class="section-header compact">
          <div>
            <h3>Cross-omics chain</h3>
            <p>Canonical selection keeps all isoforms visible and records the fallback rule used by the report.</p>
          </div>
        </div>
        <OmicsChainPanel :chain="report.id_chain" />
      </section>

      <section class="panel">
        <div class="section-header compact">
          <div>
            <h3>ID mapping evidence</h3>
            <p>Resolved gene, transcript, protein, and external database identifiers are kept separate from stoichiometric features.</p>
          </div>
          <div class="row">
            <button class="btn subtle" type="button" @click="copyIdChain" :disabled="!idMapping.available">Copy ID chain</button>
            <a class="btn subtle" :href="report.download_links?.id_mapping || mappingDownloadUrl" target="_blank" rel="noreferrer">Download row</a>
          </div>
        </div>
        <template v-if="idMapping.available">
          <div class="grid grid-4">
            <div class="card">
              <div class="label">Resolved from</div>
              <div class="kpi small-kpi">{{ idMapping.resolved_from }}</div>
            </div>
            <div class="card">
              <div class="label">Internal mapping</div>
              <div class="kpi small-kpi">{{ idMapping.mapping_status }} / {{ idMapping.mapping_confidence }}</div>
            </div>
            <div class="card">
              <div class="label">External mapping</div>
              <div class="kpi small-kpi">{{ idMapping.external_mapping_status || 'none' }}</div>
            </div>
            <div class="card">
              <div class="label">External confidence</div>
              <div class="kpi small-kpi">{{ idMapping.external_mapping_confidence || '-' }}</div>
            </div>
          </div>
          <div v-if="idMapping.conflict_warning" class="annotation warning-note">
            <strong>Conflict row retained.</strong>
            This mapping should not be used as a high-confidence Case 2/3 candidate without manual review.
          </div>
          <div class="table-wrap compact-top">
            <table class="table compact-table">
              <thead><tr><th>Gene</th><th>Transcript</th><th>Protein</th><th>External IDs</th></tr></thead>
              <tbody>
                <tr>
                  <td>{{ idMapping.id_chain?.gene_id || '-' }}</td>
                  <td>{{ idMapping.id_chain?.transcript_id || '-' }}</td>
                  <td>{{ idMapping.id_chain?.protein_id || '-' }}</td>
                  <td>
                    <span v-for="item in mappingExternalBadges" :key="item" class="badge muted-badge">{{ item }}</span>
                    <span v-if="!mappingExternalBadges.length" class="muted">-</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="badge-row">
            <a v-for="link in idMapping.external_links || []" :key="`${link.database}-${link.id}`" class="badge link-badge" :href="link.url" target="_blank" rel="noreferrer">{{ link.database }}: {{ link.id }}</a>
          </div>
        </template>
        <p v-else class="muted">No ID mapping row was found in the runtime alias index for this entity.</p>
      </section>

      <section class="panel">
        <div class="section-header compact">
          <div>
            <h3>Mapping evidence ladder</h3>
            <p>Evidence grade is based on linked genome, transcript sequence, and proteome layers plus species-level mapping quality.</p>
          </div>
        </div>
        <div class="grid grid-4">
          <div class="card">
            <div class="label">Evidence grade</div>
            <div class="kpi">{{ report.mapping_evidence?.evidence_grade || '-' }}</div>
          </div>
          <div class="card">
            <div class="label">Complete chain</div>
            <div class="kpi">{{ report.mapping_evidence?.complete_chain ? 'yes' : 'no' }}</div>
          </div>
          <div class="card">
            <div class="label">All-three coverage</div>
            <div class="kpi">{{ formatPercent(report.mapping_evidence?.coverage?.all_three) }}</div>
          </div>
          <div class="card">
            <div class="label">Mapping conflicts</div>
            <div class="kpi">{{ report.mapping_evidence?.conflict_count ?? report.cross_omics?.mapping_conflict_count ?? 0 }}</div>
          </div>
        </div>
        <p class="annotation">{{ report.mapping_evidence?.chain_status || report.cross_omics?.note }}</p>
        <div class="badge-row">
          <span v-for="layer in report.mapping_evidence?.available_layers || []" :key="layer" class="badge">{{ omicsLabel(layer) }}</span>
          <span v-for="layer in report.mapping_evidence?.missing_layers || []" :key="`missing-${layer}`" class="badge muted-badge">missing {{ omicsLabel(layer) }}</span>
        </div>
      </section>

      <section class="panel">
        <div class="section-header compact">
          <div>
            <h3>Core feature context</h3>
            <p>Each numeric field is compared against the current species background using percentile and robust z-score.</p>
          </div>
        </div>
        <div class="omics-feature-grid">
          <div v-for="omicsKey in omicsOrder" :key="omicsKey" class="omics-feature-column">
            <h4>{{ omicsLabel(omicsKey) }}</h4>
            <template v-if="report.omics_sections?.[omicsKey]?.available">
              <FeatureContextStrip
                v-for="feature in report.omics_sections[omicsKey].features"
                :key="`${omicsKey}-${feature.feature}`"
                :feature="feature"
              />
            </template>
            <p v-else class="muted">No linked {{ omicsLabel(omicsKey).toLowerCase() }} entity for this ID.</p>
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="section-header compact">
          <div>
            <h3>Candidate evidence table</h3>
            <p>Rows are aggregated from existing G/T/P/X candidate artifacts and chart-linked candidate payloads.</p>
          </div>
          <button class="btn subtle" @click="downloadEvidenceCsv" :disabled="!evidence.length">Download evidence CSV</button>
        </div>
        <EntityEvidenceTable :evidence="evidence" />
      </section>

      <section class="panel">
        <div class="section-header compact">
          <div>
            <h3>Linked charts and nearest neighbors</h3>
            <p>Chart contexts explain where this entity can be located or why it appears as a candidate.</p>
          </div>
        </div>
        <div class="two-column-grid">
          <div>
            <h4>Chart contexts</h4>
            <ul class="clean-list compact-list">
              <li v-for="ctx in report.chart_contexts || []" :key="`${ctx.module_id}-${ctx.chart_id}`">
                <strong>{{ ctx.module_id }}</strong> · {{ ctx.method }}<br />
                <span class="muted">{{ ctx.why_flagged }}</span>
              </li>
            </ul>
          </div>
          <div>
            <h4>Nearest neighbors</h4>
            <div class="table-wrap" v-if="report.nearest_neighbors?.length">
              <table class="table compact-table">
                <thead><tr><th>Omics</th><th>Entity</th><th>Gene</th><th>Distance</th></tr></thead>
                <tbody>
                  <tr v-for="row in report.nearest_neighbors" :key="`${row.omics}-${row.entity_id}`">
                    <td>{{ row.omics }}</td>
                    <td>{{ row.entity_id }}</td>
                    <td>{{ row.gene_id || row.gene_name || '-' }}</td>
                    <td>{{ format(row.distance) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p v-else class="muted">Nearest-neighbor context is unavailable for this entity.</p>
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="section-header compact">
          <div>
            <h3>Raw fields, quality notes, and downloads</h3>
            <p>Raw payloads are optional so the normal report remains fast; use the raw endpoint for complete field inspection.</p>
          </div>
          <div class="row">
            <button class="btn subtle" @click="downloadReportJson">Download report JSON</button>
            <button class="btn subtle" @click="toggleRaw">{{ rawLoaded ? 'Hide raw' : 'Load raw fields' }}</button>
          </div>
        </div>
        <div class="badge-row">
          <span v-for="flag in report.data_quality?.flags || []" :key="flag" class="badge muted-badge">{{ flag }}</span>
        </div>
        <ul class="clean-list compact-list">
          <li v-for="note in report.data_quality?.notes || []" :key="note">{{ note }}</li>
        </ul>
        <pre v-if="rawLoaded" class="json-block">{{ JSON.stringify(rawPayload, null, 2) }}</pre>
      </section>

      <section class="panel">
        <div class="section-header compact">
          <div>
            <h3>External annotation evidence layer</h3>
            <p>External GO/KEGG/Pfam/UniProt/AlphaFold/expression evidence is kept separate from core stoichiometric results.</p>
          </div>
        </div>
        <div v-if="report.external_annotations?.available" class="table-wrap">
          <table class="table compact-table">
            <thead><tr><th>Source</th><th>Matched IDs</th><th>Annotation</th></tr></thead>
            <tbody>
              <tr v-for="(row, idx) in report.external_annotations.annotations" :key="idx">
                <td>{{ row.source }}</td>
                <td>{{ (row.matched_ids || []).join(', ') }}</td>
                <td><pre class="inline-json">{{ JSON.stringify(row.annotation, null, 2) }}</pre></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="annotation">
          <strong>No local external annotation file matched this entity.</strong>
          <p>{{ report.external_annotations?.note }}</p>
          <ul class="clean-list compact-list">
            <li v-for="item in report.external_annotations?.required_sources || []" :key="item">{{ item }}</li>
          </ul>
        </div>
      </section>

      <section class="panel">
        <div class="section-header compact">
          <div>
            <h3>Standard GO/KEGG functional evidence</h3>
            <p>Official standard annotation records matched through the project ID chain.</p>
          </div>
          <a
            v-if="report.download_links?.function"
            class="btn subtle"
            :href="report.download_links.function"
            target="_blank"
            rel="noopener"
          >Open API</a>
        </div>
        <div v-if="report.functional_evidence?.available" class="grid grid-2">
          <div class="card">
            <div class="label">GO terms</div>
            <strong>{{ report.functional_evidence.go?.row_count || 0 }}</strong>
            <div class="badge-row">
              <span v-for="term in (report.functional_evidence.go?.terms || []).slice(0, 8)" :key="term.go_id" class="badge">
                {{ term.go_id }} · {{ term.go_namespace }}
              </span>
            </div>
          </div>
          <div class="card">
            <div class="label">KEGG links</div>
            <strong>{{ report.functional_evidence.kegg?.link_row_count || 0 }}</strong>
            <div class="badge-row">
              <span v-for="term in (report.functional_evidence.kegg?.annotations || []).slice(0, 8)" :key="term.annotation_type + term.annotation_id" class="badge">
                {{ term.annotation_type }} · {{ term.annotation_id }}
              </span>
            </div>
          </div>
        </div>
        <div v-if="report.functional_evidence?.available" class="table-wrap">
          <table class="table compact-table">
            <thead><tr><th>Type</th><th>ID</th><th>Name</th><th>Entities</th></tr></thead>
            <tbody>
              <tr v-for="term in functionalEvidenceRows" :key="`${term.kind}-${term.id}`">
                <td>{{ term.kind }}</td>
                <td>{{ term.id }}</td>
                <td>{{ term.name || '-' }}</td>
                <td>{{ term.count }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="annotation">No official GO/KEGG annotation matched this entity. Unsupported species and unmatched entities are not predicted.</p>
      </section>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import EntityReportHeader from '../components/EntityReportHeader.vue'
import EntityEvidenceBadges from '../components/EntityEvidenceBadges.vue'
import EntityEvidenceTable from '../components/EntityEvidenceTable.vue'
import FeatureContextStrip from '../components/FeatureContextStrip.vue'
import OmicsChainPanel from '../components/OmicsChainPanel.vue'
import { getEntityRaw, getEntityReport, getModel8Case3Reports } from '../api/stoichdb'

const props = defineProps({
  speciesId: String,
  entityKey: String,
})

const loading = ref(false)
const error = ref('')
const report = ref(null)
const rawLoaded = ref(false)
const rawPayload = ref(null)
const model8Case3Reports = ref(null)
const omicsOrder = ['genome', 'transcriptome', 'proteome']

const evidence = computed(() => report.value?.evidence_summary?.evidence || [])
const idMapping = computed(() => report.value?.id_mapping_evidence || {})
const model8CaseEvidence = computed(() => {
  const needle = String(props.entityKey || '').toLowerCase()
  if (!needle) return null
  return (model8Case3Reports.value?.report_index || []).find((row) =>
    [row.gene_id, row.transcript_id, row.protein_id].some((value) => String(value || '').toLowerCase() === needle)
  ) || null
})
const mappingDownloadUrl = computed(() => `/api/stoichdb/species/${encodeURIComponent(props.speciesId || '')}/entities/${encodeURIComponent(props.entityKey || '')}/mapping/`)
const mappingExternalBadges = computed(() => {
  const ids = idMapping.value?.external_ids || {}
  const labels = []
  if ((ids.uniprot || []).length) labels.push(`UniProt ${ids.uniprot.join(', ')}`)
  if ((ids.ncbi_gene || []).length) labels.push(`NCBI Gene ${ids.ncbi_gene.join(', ')}`)
  if ((ids.ncbi_protein || []).length) labels.push(`NCBI Protein ${ids.ncbi_protein.join(', ')}`)
  if ((ids.refseq_protein || []).length) labels.push(`RefSeq ${ids.refseq_protein.join(', ')}`)
  if ((ids.insdc_protein || []).length) labels.push(`INSDC protein ${ids.insdc_protein.join(', ')}`)
  if ((ids.insdc_region || []).length) labels.push(`INSDC region ${ids.insdc_region.join(', ')}`)
  return labels
})
const functionalEvidenceRows = computed(() => {
  const goRows = (report.value?.functional_evidence?.go?.terms || []).slice(0, 12).map((term) => ({
    kind: `GO:${term.go_namespace || 'term'}`,
    id: term.go_id,
    name: term.go_name,
    count: term.entity_count,
  }))
  const keggRows = (report.value?.functional_evidence?.kegg?.annotations || []).slice(0, 12).map((term) => ({
    kind: `KEGG:${term.annotation_type || 'link'}`,
    id: term.annotation_id,
    name: term.annotation_name,
    count: term.entity_count,
  }))
  return [...goRows, ...keggRows]
})
const keyFindings = computed(() => {
  if (!report.value) return []
  const cards = (report.value.overview_cards || []).map((card) => `${card.label}: ${card.value}. ${card.note}`)
  const topEvidence = evidence.value.slice(0, 3).map((item) => `${item.module_id}: ${item.explanation}`)
  return [...cards, ...topEvidence].slice(0, 7)
})

async function loadReport() {
  loading.value = true
  error.value = ''
  rawLoaded.value = false
  rawPayload.value = null
  try {
    report.value = await getEntityReport(props.speciesId, props.entityKey, {
      include_raw: 0,
      include_charts: 1,
      include_neighbors: 1,
    })
  } catch (err) {
    error.value = err?.message || 'Failed to load entity report.'
    report.value = null
  } finally {
    loading.value = false
  }
}

async function loadModel8CaseBadge() {
  try {
    model8Case3Reports.value = await getModel8Case3Reports()
  } catch (_err) {
    model8Case3Reports.value = null
  }
}

async function toggleRaw() {
  if (rawLoaded.value) {
    rawLoaded.value = false
    return
  }
  rawPayload.value = await getEntityRaw(props.speciesId, props.entityKey)
  rawLoaded.value = true
}

function omicsLabel(value) {
  return ({ genome: 'Genome', transcriptome: 'Transcript sequence', proteome: 'Proteome' })[value] || value
}

function format(value) {
  const num = Number(value)
  if (!Number.isFinite(num)) return value ?? '-'
  return num.toFixed(3).replace(/\.000$/, '')
}

function formatPercent(value) {
  const num = Number(value)
  if (!Number.isFinite(num)) return '-'
  return `${(num * 100).toFixed(2)}%`
}

function saveText(filename, content, type = 'text/plain;charset=utf-8') {
  const blob = new Blob([content], { type })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

function csvEscape(value) {
  const text = String(value ?? '')
  return /[",\n\r]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text
}

function downloadEvidenceCsv() {
  const columns = ['module_id', 'module_name', 'omics_scope', 'candidate_type', 'score', 'score_field', 'rank', 'severity_level', 'evidence_level', 'source_path', 'explanation']
  const lines = [columns.join(',')]
  evidence.value.forEach((row) => {
    lines.push(columns.map((key) => csvEscape(row[key])).join(','))
  })
  saveText(`${props.speciesId}_${props.entityKey}_entity_evidence.csv`, lines.join('\n'), 'text/csv;charset=utf-8')
}

async function copyIdChain() {
  const chain = idMapping.value?.id_chain || {}
  const text = `gene_id=${chain.gene_id || ''}\ntranscript_id=${chain.transcript_id || ''}\nprotein_id=${chain.protein_id || ''}`
  await navigator.clipboard?.writeText(text)
}

function downloadReportJson() {
  saveText(`${props.speciesId}_${props.entityKey}_entity_report.json`, JSON.stringify(report.value, null, 2), 'application/json;charset=utf-8')
}

onMounted(() => {
  loadReport()
  loadModel8CaseBadge()
})
watch(() => [props.speciesId, props.entityKey], loadReport)
</script>

<style scoped>
.key-findings {
  margin-top: 14px;
}

.omics-feature-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.omics-feature-column {
  display: grid;
  gap: 10px;
  align-content: start;
}

.two-column-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.json-block {
  max-height: 420px;
  overflow: auto;
  border: 1px solid rgba(42, 89, 140, 0.14);
  border-radius: 8px;
  padding: 12px;
  background: #f8fbff;
}

.inline-json {
  margin: 0;
  white-space: pre-wrap;
  max-width: 520px;
}

.badge-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}

.small-kpi {
  font-size: 0.95rem;
  overflow-wrap: anywhere;
}

.warning-note {
  border: 1px solid #e7b86a;
  border-radius: 8px;
  background: #fffaf0;
  padding: 10px 12px;
  color: #6f4b00;
}

.link-badge {
  text-decoration: none;
}

@media (max-width: 1100px) {
  .omics-feature-grid,
  .two-column-grid {
    grid-template-columns: 1fr;
  }
}
</style>
