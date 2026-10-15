<template>
  <div class="stack-lg">
    <section class="hero-panel workflow-registry-hero">
      <div class="hero-copy">
        <div class="eyebrow">Expression/HVG Stoich Extension</div>
        <h1>Expression/HVG case registry</h1>
        <p>
          Saved user jobs and curated Model-8 HVG-Stoich species cases are exposed as workflow cases with
          traceable tables, plots, text summaries, and downloadable artifacts.
        </p>
      </div>
      <div class="panel registry-summary-panel">
        <div class="label">Registry coverage</div>
        <div class="registry-kpis">
          <div><strong>{{ cases.length }}</strong><span>cases</span></div>
          <div><strong>{{ curatedCases.length }}</strong><span>curated species</span></div>
          <div><strong>{{ completeCount }}</strong><span>complete</span></div>
        </div>
        <button class="btn secondary" @click="load" :disabled="loading">{{ loading ? 'Refreshing...' : 'Refresh registry' }}</button>
      </div>
    </section>

    <section v-if="loadError" class="card error-text">{{ loadError }}</section>

    <section v-if="curatedCases.length" class="panel">
      <div class="section-header compact">
        <div>
          <h3>Model-8 species HVG workflow cases</h3>
          <p class="muted">Each species opens as an individual Expression/HVG job while preserving the shared Case 5 release artifacts.</p>
        </div>
        <span class="badge">Case 5</span>
      </div>
      <div class="case-card-grid">
        <router-link
          v-for="c in curatedCases"
          :key="c.case_id"
          class="case-job-card"
          :to="`/hvg/${c.case_id}`"
        >
          <div class="case-job-head">
            <div>
              <span class="badge">{{ c.species_case_code }}</span>
              <h4>{{ c.label }}</h4>
            </div>
            <span :class="['status-pill', statusClass(c.status)]" :title="c.status || 'SUCCEEDED'">{{ statusLabel(c.status) }}</span>
          </div>
          <div class="case-job-metrics">
            <div><span>Genes</span><strong>{{ formatNumber(c.summary?.genes_profiled) }}</strong></div>
            <div><span>Mapped</span><strong>{{ formatNumber(c.summary?.mapped_genes) }}</strong></div>
            <div><span>HVGs</span><strong>{{ formatNumber(c.summary?.hvg_consensus_count) }}</strong></div>
          </div>
          <div class="case-job-foot">
            <span>{{ percent(c.summary?.mapping_rate) }} mapped</span>
            <span :title="c.summary?.phase2_mode || '-'">{{ phaseModeLabel(c.summary?.phase2_mode) }}</span>
          </div>
        </router-link>
      </div>
    </section>

    <section class="panel">
      <div class="section-header compact">
        <div>
          <h3>All Expression/HVG workflow cases</h3>
          <p class="muted">Runtime and curated entries share the same detail route and download surface.</p>
        </div>
        <span class="badge">{{ filteredCases.length }} rows</span>
      </div>
      <div class="toolbar-grid registry-toolbar">
        <input class="input" v-model="query" placeholder="Search case, label, tag, accession, or source" />
        <select class="input" v-model="sourceFilter">
          <option value="">All sources</option>
          <option v-for="source in sourceOptions" :key="source" :value="source">{{ source }}</option>
        </select>
      </div>
      <div class="table-wrap">
        <table class="table registry-table">
          <thead>
            <tr>
              <th>Case ID</th>
              <th>Label</th>
              <th>Source</th>
              <th>Status</th>
              <th>Genes</th>
              <th>Mapping</th>
              <th>Tags</th>
              <th class="registry-action-col"></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="c in filteredCases" :key="c.case_id + c.base_dir">
              <td><code>{{ c.case_id }}</code></td>
              <td>{{ c.label }}</td>
              <td>{{ c.source }}</td>
              <td><span :class="['status-pill', statusClass(c.status)]" :title="c.status || '-'">{{ statusLabel(c.status) }}</span></td>
              <td>{{ formatNumber(c.summary?.genes_profiled) }}</td>
              <td>{{ percent(c.summary?.mapping_rate) }}</td>
              <td class="registry-tags">{{ (c.tags || []).join(', ') }}</td>
              <td class="registry-action-col"><router-link class="ghost-link open-result-link" :to="`/hvg/${c.case_id}`">Open result</router-link></td>
            </tr>
            <tr v-if="!filteredCases.length">
              <td colspan="8">No Expression/HVG cases match the current filters.</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { listCases } from '../api/registry'

const cases = ref([])
const loading = ref(false)
const loadError = ref('')
const query = ref('')
const sourceFilter = ref('')

const curatedCases = computed(() => cases.value.filter(c => c.case_family === 'model8_case5_hvg_stoich'))
const completeCount = computed(() => cases.value.filter(c => String(c.status || '').toUpperCase() === 'SUCCEEDED').length)
const sourceOptions = computed(() => [...new Set(cases.value.map(c => c.source).filter(Boolean))].sort())
const filteredCases = computed(() => {
  const q = query.value.trim().toLowerCase()
  return cases.value.filter((c) => {
    if (sourceFilter.value && c.source !== sourceFilter.value) return false
    if (!q) return true
    return [
      c.case_id,
      c.label,
      c.source,
      c.species_case_code,
      c.summary?.accession,
      ...(c.tags || []),
    ].some(value => String(value || '').toLowerCase().includes(q))
  })
})

function formatNumber(value) {
  const n = Number(value)
  return Number.isFinite(n) ? n.toLocaleString() : '-'
}

function percent(value) {
  const n = Number(value)
  return Number.isFinite(n) ? `${(n * 100).toFixed(1)}%` : '-'
}

function statusClass(value) {
  const status = String(value || '').toLowerCase()
  if (status.includes('succeed') || status.includes('complete')) return 'ready'
  if (status.includes('fail') || status.includes('blocked')) return 'blocked'
  return 'pending'
}

function statusLabel(value) {
  const status = String(value || '').toUpperCase()
  if (!status) return '-'
  if (status.includes('SUCCEED') || status.includes('COMPLETE')) return 'SUCCEEDED'
  if (status.includes('BLOCKED')) return 'BLOCKED'
  return status.replaceAll('_', ' ')
}

function phaseModeLabel(value) {
  const mode = String(value || '')
  if (!mode) return '-'
  if (mode.includes('enhanced')) return 'enhanced bridge'
  if (mode.includes('blocked')) return 'mapping boundary'
  return mode
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    cases.value = await listCases()
  } catch (error) {
    loadError.value = error?.response?.data?.error?.message || error?.response?.data?.error || error.message || 'Failed to load Expression/HVG case registry.'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.workflow-registry-hero {
  align-items: stretch;
}

.registry-summary-panel {
  min-width: min(360px, 100%);
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 16px;
  padding: 20px;
}

.registry-kpis {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.registry-kpis div {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.registry-kpis strong {
  color: var(--text-main);
  font-size: 1.35rem;
}

.registry-kpis span {
  color: var(--text-muted);
  font-size: 0.78rem;
}

.case-card-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.case-job-card {
  display: flex;
  min-height: 150px;
  flex-direction: column;
  justify-content: space-between;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--line-soft);
  border-radius: 8px;
  background: #fff;
  color: inherit;
  text-decoration: none;
  transition: border-color 0.16s ease, box-shadow 0.16s ease, transform 0.16s ease;
}

.case-job-card:hover {
  transform: translateY(-1px);
  border-color: rgba(31, 93, 154, 0.38);
  box-shadow: 0 8px 16px rgba(42, 83, 122, 0.08);
}

.case-job-head,
.case-job-foot {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.case-job-head h4 {
  margin: 7px 0 0;
  line-height: 1.16;
  font-size: 0.98rem;
}

.case-job-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
}

.case-job-metrics div {
  padding: 7px;
  border-radius: 8px;
  background: rgba(244, 248, 252, 0.9);
}

.case-job-metrics span,
.case-job-foot {
  color: var(--text-muted);
  font-size: 0.78rem;
}

.case-job-metrics strong {
  display: block;
  margin-top: 3px;
  color: var(--text-main);
}

.case-job-foot span:last-child {
  max-width: 52%;
  overflow: hidden;
  text-align: right;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.registry-toolbar {
  margin: 12px 0;
}

.table-wrap {
  overflow: auto;
}

.registry-table {
  min-width: 1180px;
  table-layout: fixed;
}

.registry-table th:nth-child(1),
.registry-table td:nth-child(1) {
  width: 170px;
}

.registry-table th:nth-child(2),
.registry-table td:nth-child(2) {
  width: 280px;
}

.registry-table th:nth-child(3),
.registry-table td:nth-child(3) {
  width: 185px;
}

.registry-table th:nth-child(4),
.registry-table td:nth-child(4) {
  width: 190px;
}

.registry-table th:nth-child(5),
.registry-table td:nth-child(5),
.registry-table th:nth-child(6),
.registry-table td:nth-child(6) {
  width: 90px;
}

.registry-tags {
  overflow-wrap: anywhere;
}

.registry-action-col {
  width: 126px;
  min-width: 126px;
  text-align: right;
}

.open-result-link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 104px;
  min-height: 34px;
  padding: 7px 12px;
  white-space: nowrap;
}

.status-pill {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 3px 8px;
  border-radius: 999px;
  border: 1px solid rgba(74, 113, 151, 0.18);
  background: rgba(240, 246, 252, 0.9);
  color: #31566f;
  font-size: 0.76rem;
  font-weight: 700;
}

.status-pill.ready {
  border-color: rgba(42, 157, 143, 0.28);
  background: rgba(232, 249, 246, 0.95);
  color: #17695e;
}

.status-pill.blocked {
  border-color: rgba(180, 35, 24, 0.22);
  background: rgba(255, 241, 240, 0.95);
  color: #9f1f17;
}

@media (max-width: 1280px) {
  .case-card-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 780px) {
  .registry-kpis,
  .case-job-metrics {
    grid-template-columns: 1fr;
  }

  .case-card-grid {
    grid-template-columns: 1fr;
  }
}
</style>
