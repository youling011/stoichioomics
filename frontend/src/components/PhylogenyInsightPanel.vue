<template>
  <section class="panel phylogeny-panel">
    <div class="section-header">
      <div>
        <div class="eyebrow">Phylogeny-adjusted layer</div>
        <h3>{{ title }}</h3>
        <p class="muted">{{ subtitle }}</p>
      </div>
      <div class="phylogeny-actions">
        <span :class="['badge', pglsEligible ? 'status-ready' : 'status-blocked']">
          {{ pglsEligible ? 'PGLS ready' : 'PGLS blocked' }}
        </span>
        <router-link v-if="showDownloadsLink" class="btn subtle" to="/downloads">Download release files</router-link>
      </div>
    </div>

    <div v-if="loading" class="phylogeny-state">
      <p class="muted">Loading phylogeny runtime results...</p>
    </div>
    <div v-else-if="error" class="phylogeny-state">
      <p class="muted">{{ error }}</p>
      <button class="btn subtle" type="button" @click="loadAll">Retry phylogeny layer</button>
    </div>
    <template v-else>
      <div class="phylogeny-kpi-grid">
        <div class="case-kpi">
          <span>Release</span>
          <strong>{{ releaseId }}</strong>
        </div>
        <div class="case-kpi">
          <span>Analysis tips</span>
          <strong>{{ analysisTipCount }}</strong>
        </div>
        <div class="case-kpi">
          <span>Trait species</span>
          <strong>{{ traitSpeciesCount }}</strong>
        </div>
        <div class="case-kpi">
          <span>Branch lengths</span>
          <strong>{{ branchLengthsPresent ? 'Present' : 'Missing' }}</strong>
        </div>
      </div>

      <div v-if="selectedSpecies.length" class="phylogeny-selection-box">
        <div>
          <strong>Selected species tree coverage</strong>
          <p class="muted">
            {{ selectedCoverageText }}. Species outside the active subset30 tree remain available for descriptive comparison,
            but are excluded from PGLS.
          </p>
        </div>
        <div class="badge-row">
          <span v-for="row in selectedContextRows" :key="row.species_id" :class="['badge', row.pgls_eligible ? 'status-ready' : 'status-muted']">
            {{ row.display_name || row.species_id }}: {{ row.pgls_eligible ? 'tree' : 'no tree' }}
          </span>
        </div>
      </div>

      <div v-if="case1" class="caution-block phylogeny-boundary">
        <strong>Interpretation boundary</strong>
        <span>{{ case1.allowed_interpretation || 'Use only as phylogeny-aware statistical context for the active branch-length tree.' }}</span>
        <span>{{ case1.forbidden_interpretation || 'Do not treat branch lengths as absolute evolutionary time.' }}</span>
      </div>

      <div class="grid grid-2">
        <article class="phylogeny-result-card">
          <div class="section-header compact">
            <div>
              <div class="eyebrow">Pagel lambda</div>
              <h3>Phylogenetic signal</h3>
            </div>
          </div>
          <div class="table-wrap">
            <table class="table compact-table">
              <thead>
                <tr>
                  <th>Feature</th>
                  <th>λ</th>
                  <th>p</th>
                  <th>n</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in signalRows" :key="row.feature">
                  <td>{{ formatFeature(row.feature) }}</td>
                  <td>{{ formatNumber(row.lambda) }}</td>
                  <td>{{ formatNumber(row.p_value) }}</td>
                  <td>{{ row.n }}</td>
                  <td>{{ row.status }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </article>

        <article class="phylogeny-result-card">
          <div class="section-header compact">
            <div>
              <div class="eyebrow">OLS / PGLS</div>
              <h3>{{ formula }}</h3>
            </div>
          </div>
          <div v-if="pgls?.status === 'ok'" class="pgls-summary">
            <span class="badge">λ {{ formatNumber(pgls.lambda) }}</span>
            <span class="badge">OLS R² {{ formatNumber(pgls.ols?.r_squared) }}</span>
            <span class="badge">PGLS R² {{ formatNumber(pgls.pgls?.r_squared) }}</span>
          </div>
          <p v-else class="muted">{{ pgls?.blocker || pgls?.status || 'PGLS result is unavailable.' }}</p>
          <div v-if="pgls?.pgls?.terms?.length" class="table-wrap compact-top">
            <table class="table compact-table">
              <thead>
                <tr>
                  <th>Term</th>
                  <th>OLS β</th>
                  <th>PGLS β</th>
                  <th>PGLS p</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="term in pglsTerms" :key="term.term">
                  <td>{{ term.term }}</td>
                  <td>{{ formatNumber(term.ols_beta) }}</td>
                  <td>{{ formatNumber(term.pgls_beta) }}</td>
                  <td>{{ formatNumber(term.pgls_p_value) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </article>
      </div>

      <div class="phylogeny-method-row">
        <span class="method-badge">Tree: {{ treeSource }}</span>
        <span class="method-badge">Evidence: phylogeny_adjusted</span>
        <span class="method-badge">Subset mode: {{ subsetMode ? 'yes' : 'no' }}</span>
      </div>
    </template>
  </section>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import {
  getCase1Phylogeny,
  getPhylogenyRelease,
  getPhylogenyValidation,
  getSpeciesPhylogenyContext,
  runPhylogeneticSignal,
  runPhylogenyPgls,
} from '../api/stoichdb'

const props = defineProps({
  title: { type: String, default: 'Active analysis-grade tree and runtime statistics' },
  subtitle: {
    type: String,
    default: 'Uses the validated subset30 branch-length tree when available; otherwise the interface reports controlled blockers.',
  },
  releaseId: { type: String, default: 'protist_phylogeny_v1' },
  features: { type: Array, default: () => ['genome_gc', 'proteome_n_per_aa'] },
  formula: { type: String, default: 'proteome_n_per_aa ~ genome_gc' },
  selectedSpecies: { type: Array, default: () => [] },
  showDownloadsLink: { type: Boolean, default: true },
})

const loading = ref(false)
const error = ref('')
const release = ref(null)
const validation = ref(null)
const case1 = ref(null)
const signal = ref(null)
const pgls = ref(null)
const selectedContexts = ref([])

const releaseId = computed(() => release.value?.release_id || validation.value?.release_id || props.releaseId)
const activeTree = computed(() => release.value?.p2?.analysis_grade_tree || release.value?.analysis_grade_tree || {})
const analysisTipCount = computed(() => activeTree.value?.tip_count || validation.value?.tree_tip_count || case1.value?.matched_species_count || '-')
const traitSpeciesCount = computed(() => validation.value?.trait_tip_count || case1.value?.trait_species_count || '-')
const branchLengthsPresent = computed(() => Boolean(validation.value?.branch_lengths_present || activeTree.value?.branch_lengths_present || case1.value?.branch_lengths_present))
const pglsEligible = computed(() => Boolean(validation.value?.pgls_eligible || case1.value?.pgls_eligible || pgls.value?.status === 'ok'))
const subsetMode = computed(() => Boolean(validation.value?.subset_mode || activeTree.value?.subset_mode))
const treeSource = computed(() => activeTree.value?.source || validation.value?.source || 'active registered tree')
const signalRows = computed(() => signal.value?.features || [])
const selectedContextRows = computed(() => selectedContexts.value || [])
const selectedTreeCount = computed(() => selectedContextRows.value.filter((row) => row.pgls_eligible).length)
const selectedCoverageText = computed(() => `${selectedTreeCount.value}/${selectedSpecies.value.length} selected species are in the active branch-length tree`)

const pglsTerms = computed(() => {
  const olsTerms = pgls.value?.ols?.terms || []
  const pglsTerms = pgls.value?.pgls?.terms || []
  return pglsTerms.map((term) => {
    const ols = olsTerms.find((row) => row.term === term.term) || {}
    return {
      term: term.term,
      ols_beta: ols.beta,
      pgls_beta: term.beta,
      pgls_p_value: term.p_value,
    }
  })
})

const selectedSpecies = computed(() => props.selectedSpecies.filter(Boolean))

function formatFeature(value) {
  return String(value || '').replaceAll('_', ' ')
}

function formatNumber(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return value ?? '-'
  if (Math.abs(n) >= 100) return n.toFixed(2)
  if (Math.abs(n) >= 1) return n.toFixed(4).replace(/0+$/, '').replace(/\.$/, '')
  return n.toExponential(3)
}

function errorMessage(err) {
  return err?.response?.data?.error?.message || err?.response?.data?.message || err?.message || 'Failed to load phylogeny payload.'
}

async function loadSelectedContexts() {
  const ids = selectedSpecies.value.slice(0, 12)
  if (!ids.length) {
    selectedContexts.value = []
    return
  }
  const rows = await Promise.all(
    ids.map(async (speciesId) => {
      try {
        return await getSpeciesPhylogenyContext(speciesId)
      } catch {
        return { species_id: speciesId, pgls_eligible: false, display_name: speciesId }
      }
    }),
  )
  selectedContexts.value = rows
}

async function loadAll() {
  loading.value = true
  error.value = ''
  try {
    const [releasePayload, validationPayload, case1Payload, signalPayload, pglsPayload] = await Promise.all([
      getPhylogenyRelease(props.releaseId),
      getPhylogenyValidation(props.releaseId),
      getCase1Phylogeny({ release_id: props.releaseId }),
      runPhylogeneticSignal({ release_id: props.releaseId, features: props.features }),
      runPhylogenyPgls({ release_id: props.releaseId, formula: props.formula }),
    ])
    release.value = releasePayload
    validation.value = validationPayload
    case1.value = case1Payload
    signal.value = signalPayload
    pgls.value = pglsPayload
    await loadSelectedContexts()
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    loading.value = false
  }
}

watch(() => props.selectedSpecies.join(','), () => {
  if (!loading.value && !error.value) loadSelectedContexts()
})

onMounted(loadAll)
</script>

<style scoped>
.phylogeny-panel {
  border-color: rgba(31, 93, 154, 0.22);
}

.phylogeny-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 10px;
}

.phylogeny-state {
  padding: 14px 0;
}

.phylogeny-kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.phylogeny-selection-box,
.phylogeny-boundary {
  margin-bottom: 16px;
}

.phylogeny-boundary {
  display: grid;
  gap: 6px;
  padding: 14px;
  border: 1px solid rgba(176, 93, 33, 0.22);
  border-radius: 16px;
  background: rgba(255, 249, 241, 0.84);
}

.phylogeny-selection-box {
  display: grid;
  gap: 10px;
  padding: 14px;
  border: 1px solid var(--line-soft);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.64);
}

.phylogeny-result-card {
  padding: 16px;
  border: 1px solid var(--line-soft);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.72);
}

.pgls-summary,
.phylogeny-method-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.phylogeny-method-row {
  margin-top: 16px;
}

.status-ready {
  background: rgba(31, 118, 88, 0.12);
  color: #17684f;
  border-color: rgba(31, 118, 88, 0.22);
}

.status-blocked {
  background: rgba(176, 93, 33, 0.12);
  color: #8f4c1d;
  border-color: rgba(176, 93, 33, 0.24);
}

.status-muted {
  background: rgba(93, 118, 144, 0.12);
  color: var(--text-soft);
}
</style>
