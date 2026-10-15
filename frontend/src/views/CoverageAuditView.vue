<template>
  <div class="stack-lg coverage-audit-page">
    <ModuleState
      v-if="loading"
      state="loading"
      title="Loading six-group coverage audit"
      message="Reconciling the species registry with every downstream platform module."
      :retry="load"
    />
    <ModuleState
      v-else-if="loadError"
      state="error"
      title="Coverage audit unavailable"
      :message="loadError"
      :retry="load"
    />

    <template v-else-if="payload">
      <ActiveReleaseBanner :release="payload.release" :show-release-link="true" />

      <section class="panel coverage-audit-intro">
        <div>
          <div class="eyebrow">Platform-wide data contract audit</div>
          <h2>Six groups × every module</h2>
          <p class="muted">This page separates a dataset that is registered, a downstream artifact that is generated, and a module that is genuinely applicable. A visible loading state is temporary; the states below describe the persistent data contract after loading finishes.</p>
        </div>
        <span class="coverage-status-pill" :class="stateClass(payload.status)">{{ stateLabel(payload.status) }}</span>
      </section>

      <section class="grid grid-4">
        <article class="feature-card">
          <div class="eyebrow">Registry</div>
          <h3>{{ integer(payload.summary.species_count) }} species</h3>
          <p class="muted">Species rows currently visible in PostgreSQL.</p>
        </article>
        <article class="feature-card">
          <div class="eyebrow">Core omics</div>
          <h3>{{ integer(payload.summary.all_omics_species) }}</h3>
          <p class="muted">Species with non-zero registered core rows in all three omics layers.</p>
        </article>
        <article class="feature-card">
          <div class="eyebrow">Deep artifacts</div>
          <h3>{{ integer(payload.summary.analysis_artifact_species) }}</h3>
          <p class="muted">Species with at least one registered downstream analysis artifact.</p>
        </article>
        <article class="feature-card">
          <div class="eyebrow">Entity index</div>
          <h3>{{ integer(payload.summary.entity_index_species) }}</h3>
          <p class="muted">Species with PostgreSQL EntityRecord rows; zero means indexed search can be empty.</p>
        </article>
      </section>

      <section class="panel">
        <div class="section-header compact">
          <div>
            <div class="eyebrow">Registry reconciliation</div>
            <h3>Database registry vs six-group taxonomy manifest</h3>
            <p class="muted">The manifest is a reference snapshot and is reported separately from the active DataRelease record.</p>
          </div>
          <span class="coverage-status-pill" :class="stateClass(payload.taxonomy_reference.state)">{{ stateLabel(payload.taxonomy_reference.state) }}</span>
        </div>
        <div class="coverage-reconciliation-grid">
          <div class="mini-card"><div class="label">Reference rows</div><div class="metric-inline">{{ integer(payload.taxonomy_reference.expected_species_count) }}</div></div>
          <div class="mini-card"><div class="label">Database rows</div><div class="metric-inline">{{ integer(payload.taxonomy_reference.database_species_count) }}</div></div>
          <div class="mini-card"><div class="label">Delta</div><div class="metric-inline">{{ signedInteger(payload.taxonomy_reference.delta) }}</div></div>
          <div class="mini-card"><div class="label">Manifest generated</div><div class="metric-inline">{{ payload.taxonomy_reference.generated_at || 'Not registered' }}</div></div>
        </div>
        <div class="table-wrap compact-top">
          <table class="table compact-table">
            <thead><tr><th>Group</th><th>Manifest</th><th>Database</th><th>Delta</th></tr></thead>
            <tbody>
              <tr v-for="group in payload.groups" :key="group.key">
                <td><strong>{{ group.label }}</strong><span v-if="group.database_domain === 'Unknown'" class="table-note">DB domain: Unknown</span></td>
                <td>{{ integer(payload.taxonomy_reference.expected_groups?.[group.key]) }}</td>
                <td>{{ integer(group.species_count) }}</td>
                <td><span class="coverage-number" :class="{ negative: payload.taxonomy_reference.group_deltas?.[group.key] < 0, positive: payload.taxonomy_reference.group_deltas?.[group.key] > 0 }">{{ signedInteger(payload.taxonomy_reference.group_deltas?.[group.key]) }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="panel">
        <div class="section-header compact">
          <div>
            <div class="eyebrow">Module contracts</div>
            <h3>G1-G8, T1-T8, P1-P8 and X0-X8</h3>
            <p class="muted">The platform code exposes every requested module contract. The source-coverage column is the population ceiling; exact field-level status is evaluated per species and shown in the Species Explorer.</p>
          </div>
        </div>
        <div class="table-wrap">
          <table class="table compact-table coverage-contract-table">
            <thead><tr><th>ID</th><th>Area</th><th>Module</th><th>Coverage basis</th><th>Source coverage</th><th>Required fields / interpretation</th></tr></thead>
            <tbody>
              <tr v-for="contract in payload.module_contracts || []" :key="`${contract.area}-${contract.id}`">
                <td><strong>{{ contract.id }}</strong></td>
                <td>{{ contract.area }}</td>
                <td>{{ contract.label }}</td>
                <td><span class="table-note">{{ contract.coverage_basis }}</span><span class="state-badge" :class="stateClass(contract.source_state)">{{ stateLabel(contract.source_state) }}</span></td>
                <td>{{ integer(contract.source_available) }}/{{ integer(contract.source_denominator) }} ({{ contractRate(contract) }})</td>
                <td>{{ contractFields(contract) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="panel">
        <div class="section-header compact">
          <div>
            <div class="eyebrow">Module matrix</div>
            <h3>What is populated after the request completes?</h3>
            <p class="muted">Coverage is calculated against all registry species unless the row explicitly says otherwise.</p>
          </div>
          <div class="coverage-legend"><span class="legend-ready">Ready</span><span class="legend-limited">Limited</span><span class="legend-missing">Missing</span></div>
        </div>
        <div class="table-wrap">
          <table class="table compact-table coverage-module-table">
            <thead><tr><th>Module</th><th>Coverage</th><th>State</th><th>Why a panel may be blank</th></tr></thead>
            <tbody>
              <tr v-for="module in payload.modules" :key="module.key">
                <td><strong>{{ module.label }}</strong><span class="table-note">{{ module.key }}</span></td>
                <td><strong>{{ formatStat(module) }}</strong><div class="coverage-meter"><i :style="{ width: `${Math.min(100, Number(module.coverage_percent || 0))}%` }"></i></div></td>
                <td><span class="state-badge" :class="stateClass(module.state)">{{ stateLabel(module.state) }}</span></td>
                <td>{{ module.reason }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="panel">
        <div class="section-header compact">
          <div>
            <div class="eyebrow">Six-group comparison</div>
            <h3>Basic, full, deep, annotation, and phylogeny coverage by group</h3>
          </div>
        </div>
        <div class="table-wrap">
          <table class="table compact-table coverage-group-table">
            <thead><tr><th>Group</th><th>Species</th><th>Genome core</th><th>Transcript core</th><th>Proteome core</th><th>Full scope<br><small>G / T / P</small></th><th>Deep artifacts</th><th>Annotations<br><small>status / GO / KEGG</small></th><th>Phylogeny</th></tr></thead>
            <tbody>
              <tr v-for="group in payload.groups" :key="group.key">
                <td><strong>{{ group.label }}</strong></td>
                <td>{{ integer(group.species_count) }}</td>
                <td>{{ formatStat(group.basic_omics.genome) }}</td>
                <td>{{ formatStat(group.basic_omics.transcriptome) }}</td>
                <td>{{ formatStat(group.basic_omics.proteome) }}</td>
                <td>{{ shortTriplet(group.full_scope) }}</td>
                <td>{{ formatStat(group.analysis_artifacts) }}</td>
                <td>{{ annotationTriplet(group) }}</td>
                <td>{{ formatStat(group.phylogeny) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="grid grid-2">
        <article class="panel">
          <div class="section-header compact"><div><div class="eyebrow">Persistent gaps</div><h3>Why content can be empty</h3></div></div>
          <div class="coverage-limitations">
            <article v-for="item in payload.known_limitations" :key="item.code" class="coverage-limitation" :class="stateClass(item.severity)">
              <div class="coverage-limitation-head"><strong>{{ item.title }}</strong><span class="state-badge" :class="stateClass(item.severity)">{{ item.severity }}</span></div>
              <p>{{ item.detail }}</p>
            </article>
          </div>
        </article>
        <article class="panel">
          <div class="section-header compact"><div><div class="eyebrow">Interpretation</div><h3>Loading vs missing data</h3></div></div>
          <div class="coverage-explanation">
            <div><span class="explanation-mark loading-mark">↻</span><p><strong>Loading</strong><br>Shown while the request is still pending. The global progress bar and module skeletons make this temporary state explicit.</p></div>
            <div><span class="explanation-mark limited-mark">△</span><p><strong>Limited</strong><br>A source exists, but a full scope, artifact, annotation, or eligibility signal is incomplete.</p></div>
            <div><span class="explanation-mark missing-mark">—</span><p><strong>Missing</strong><br>The request completed, but no usable payload is registered for that module/species combination.</p></div>
          </div>
        </article>
      </section>
    </template>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import ActiveReleaseBanner from '../components/ActiveReleaseBanner.vue'
import ModuleState from '../components/ModuleState.vue'
import { getCoverageAudit } from '../api/stoichdb'

const loading = ref(true)
const loadError = ref('')
const payload = ref(null)

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    payload.value = await getCoverageAudit()
  } catch (error) {
    loadError.value = error?.response?.data?.error || error?.message || 'Coverage audit request failed.'
  } finally {
    loading.value = false
  }
}

function integer(value) {
  const number = Number(value)
  return Number.isFinite(number) ? number.toLocaleString() : '—'
}

function signedInteger(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '—'
  return `${number > 0 ? '+' : ''}${number.toLocaleString()}`
}

function formatStat(stat = {}) {
  return `${integer(stat.available)}/${integer(stat.denominator)} (${Number(stat.coverage_percent || 0).toFixed(2)}%)`
}

function shortTriplet(scope = {}) {
  return ['genome', 'transcriptome', 'proteome'].map((key) => `${Number(scope[key]?.coverage_percent || 0).toFixed(1)}%`).join(' / ')
}

function annotationTriplet(group) {
  return [group.functional_annotation_status, group.functional_annotation_go, group.functional_annotation_kegg]
    .map((item) => `${integer(item?.available)}/${integer(item?.denominator)}`)
    .join(' / ')
}

function contractFields(contract) {
  if (contract.required_fields?.length) return contract.required_fields.join(', ')
  return contract.reason || 'Field-dependent status is evaluated per species.'
}

function contractRate(contract) {
  const available = Number(contract.source_available || 0)
  const denominator = Number(contract.source_denominator || 0)
  return `${(denominator ? available / denominator * 100 : 0).toFixed(2)}%`
}

function stateClass(state) {
  return `state-${String(state || 'unknown').replaceAll('_', '-')}`
}

function stateLabel(state) {
  const labels = {
    ready: 'Ready',
    ready_with_gaps: 'Ready with gaps',
    limited: 'Limited',
    mismatch: 'Mismatch',
    missing: 'Missing',
    error: 'Error',
  }
  return labels[state] || state || 'Unknown'
}

onMounted(load)
</script>

<style scoped>
.coverage-audit-intro { display: flex; align-items: flex-start; justify-content: space-between; gap: 22px; }
.coverage-audit-intro h2 { margin: 4px 0 8px; color: #143551; }
.coverage-status-pill,
.state-badge { display: inline-flex; align-items: center; width: max-content; border-radius: 999px; padding: 5px 9px; font-size: 0.72rem; font-weight: 800; letter-spacing: 0.02em; }
.state-ready, .legend-ready { color: #236c52; background: #e5f6ed; }
.state-limited, .state-mismatch, .legend-limited { color: #8a641b; background: #fff3cf; }
.state-missing, .state-error, .legend-missing { color: #9d4d43; background: #ffebe7; }
.state-ready-with-gaps { color: #8a641b; background: #fff3cf; }
.coverage-reconciliation-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.coverage-legend { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; font-size: 0.75rem; }
.coverage-legend span { border-radius: 999px; padding: 5px 9px; font-weight: 700; }
.table-note { display: block; margin-top: 3px; color: #7a94a8; font-size: 0.72rem; }
.coverage-number.negative { color: #a34f45; }
.coverage-number.positive { color: #9b6c18; }
.coverage-meter { width: 92px; height: 5px; margin-top: 6px; overflow: hidden; border-radius: 999px; background: #e4edf4; }
.coverage-meter i { display: block; height: 100%; border-radius: inherit; background: linear-gradient(90deg, #70b5db, #2f77c8); }
.coverage-module-table td:last-child { min-width: 320px; color: #5c7690; line-height: 1.45; }
.coverage-contract-table { min-width: 1180px; }
.coverage-contract-table td:last-child { min-width: 360px; color: #607d95; line-height: 1.45; }
.coverage-group-table { min-width: 1120px; }
.coverage-group-table small { color: #7a94a8; font-weight: 500; }
.coverage-limitations { display: flex; flex-direction: column; gap: 10px; }
.coverage-limitation { padding: 12px 14px; border-left: 3px solid #d5e3ec; border-radius: 10px; background: #f8fbfd; }
.coverage-limitation.state-warning { border-left-color: #c49331; background: #fffaf0; }
.coverage-limitation-head { display: flex; justify-content: space-between; gap: 12px; align-items: center; color: #254d6d; }
.coverage-limitation p { margin: 7px 0 0; color: #607d95; font-size: 0.84rem; line-height: 1.5; }
.coverage-explanation { display: flex; flex-direction: column; gap: 14px; }
.coverage-explanation > div { display: flex; align-items: flex-start; gap: 10px; }
.coverage-explanation p { margin: 0; color: #607d95; font-size: 0.86rem; line-height: 1.5; }
.explanation-mark { display: grid; flex: 0 0 auto; place-items: center; width: 27px; height: 27px; border-radius: 50%; font-weight: 800; }
.loading-mark { color: #276eaa; background: #e6f2fb; }
.limited-mark { color: #8a641b; background: #fff3cf; }
.missing-mark { color: #9d4d43; background: #ffebe7; }
@media (max-width: 900px) {
  .coverage-audit-intro { flex-direction: column; }
  .coverage-reconciliation-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
