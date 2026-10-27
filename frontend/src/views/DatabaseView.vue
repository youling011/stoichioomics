<template>
  <div class="stack-lg">
    <section class="panel">
      <div class="section-header">
        <div>
          <div class="eyebrow">Registry browser</div>
          <h3>Advanced species screening and database search</h3>
          <p class="muted">This registry is served from PostgreSQL-backed species, dataset, and entity indexes. Release-grade model organisms are shown first; the full registry remains available below and through all filters.</p>
        </div>
        <button v-if="loadError" class="btn subtle" @click="initialize">Retry load</button>
      </div>
      <div v-if="loading" class="annotation">Loading facets and species registry...</div>
      <div v-else-if="loadError" class="annotation">{{ loadError }}</div>
      <div class="toolbar-grid wide advanced-grid">
        <input class="input" v-model="query" placeholder="Search species, species_id, source context, or indexed text" @keyup.enter="load" />
        <select v-model="omics" class="input">
          <option value="">All omics</option>
          <option value="genome">Genome</option>
          <option value="transcriptome">Transcript sequence</option>
          <option value="proteome">Proteome</option>
        </select>
        <select v-model="domain" class="input">
          <option value="">All domains</option>
          <option v-for="row in facets.domains || []" :key="row.domain" :value="row.domain">{{ row.domain }} ({{ row.count }})</option>
        </select>
        <select v-model="clade" class="input">
          <option value="">All clades</option>
          <option v-for="row in facets.clades || []" :key="row.clade" :value="row.clade">{{ row.clade }} ({{ row.count }})</option>
        </select>
        <select v-model="habitat" class="input">
          <option value="">All habitats</option>
          <option v-for="row in facets.habitats || []" :key="row.habitat" :value="row.habitat">{{ row.habitat }} ({{ row.count }})</option>
        </select>
        <label class="checkbox-inline">
          <input type="checkbox" v-model="hasAllOmics" />
          <span>Only species with all 3 omics</span>
        </label>
        <input class="input" v-model="genomeSizeMin" type="number" step="0.01" placeholder="Genome size min (Mb)" />
        <input class="input" v-model="genomeSizeMax" type="number" step="0.01" placeholder="Genome size max (Mb)" />
        <select v-model="fingerprintKey" class="input">
          <option value="">Fingerprint feature</option>
          <option v-for="key in facets.fingerprint_keys || []" :key="key" :value="key">{{ formatKey(key) }}</option>
        </select>
        <input class="input" v-model="fingerprintMin" type="number" step="0.0001" placeholder="Feature min" />
        <input class="input" v-model="fingerprintMax" type="number" step="0.0001" placeholder="Feature max" />
        <select v-model="sortBy" class="input">
          <option value="display_name">Model release first, then name</option>
          <option value="genome_size_mb">Sort by genome size</option>
          <option value="genome_gc">Sort by genome GC</option>
          <option value="transcript_entropy">Sort by RNA entropy</option>
          <option value="proteome_pi">Sort by proteome pI</option>
        </select>
        <select v-model="sortOrder" class="input">
          <option value="asc">Ascending</option>
          <option value="desc">Descending</option>
        </select>
        <select v-model="viewMode" class="input">
          <option value="cards">Card view</option>
          <option value="table">Table view</option>
        </select>
        <label class="checkbox-inline">
          <input type="checkbox" v-model="useLogGenomeSize" />
          <span>Log genome-size axis</span>
        </label>
        <button class="btn subtle" @click="reset">Reset</button>
        <button class="btn" @click="load">Apply filters</button>
      </div>
    </section>

    <SpeciesAtlasOverview
      :payload="atlasPayload"
      :loading="atlasLoading"
      :error="atlasError"
      @retry="load({ resetPage: false, refreshAtlas: true })"
      @coverage-cell-click="applyCoverageDrilldown"
    />

    <section v-if="viewMode === 'cards'" class="grid grid-2">
      <router-link class="species-card" v-for="species in speciesRows" :key="species.species_id" :to="`/species/${species.species_id}`">
        <div class="section-header compact">
          <div>
            <h4>{{ species.display_name }}</h4>
            <p class="muted">{{ species.source_context || 'Local registry dataset' }}</p>
          </div>
          <span class="badge" :class="species.is_model_organism ? 'cool-badge' : ''">
            {{ species.is_model_organism ? 'Model release · Parquet' : 'Species explorer' }}
          </span>
        </div>
        <div class="grid grid-4 dense-grid">
          <div class="mini-card" v-for="(payload, key) in species.omics" :key="key">
            <div class="label">{{ key }}</div>
            <div class="metric-inline">{{ payload.row_count }}</div>
          </div>
        </div>
        <div class="metric-band">
          <span class="badge">Genome size {{ species.genome_size_mb }} Mb</span>
          <span class="badge">Genome GC {{ species.fingerprint.genome_gc }}</span>
          <span class="badge">RNA entropy {{ species.fingerprint.transcript_entropy }}</span>
          <span class="badge">Proteome pI {{ species.fingerprint.proteome_pi }}</span>
          <span v-if="species.is_model_organism && species.chart_completeness" class="badge cool-badge">
            Chart completeness {{ formatCompleteness(species.chart_completeness.overall_pct) }}
          </span>
        </div>
      </router-link>
    </section>

    <section v-else class="panel">
      <div class="section-header">
        <div>
          <div class="eyebrow">Tabular registry</div>
          <h3>Species summary table</h3>
        </div>
      </div>
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>Species</th>
              <th>Source context</th>
              <th>Genome size</th>
              <th>Genome GC</th>
              <th>RNA entropy</th>
              <th>Proteome pI</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="species in speciesRows" :key="species.species_id">
              <td>
                <div>{{ species.display_name }}</div>
                <span v-if="species.is_model_organism" class="badge cool-badge">Model release</span>
              </td>
              <td>{{ species.source_context || 'Local registry dataset' }}</td>
              <td>{{ species.genome_size_mb }}</td>
              <td>{{ species.fingerprint.genome_gc }}</td>
              <td>{{ species.fingerprint.transcript_entropy }}</td>
              <td>{{ species.fingerprint.proteome_pi }}</td>
              <td><router-link :to="`/species/${species.species_id}`">Open</router-link></td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section v-if="pageMeta.total" class="panel">
      <div class="section-header compact">
        <div>
          <div class="eyebrow">Server-side pagination</div>
          <p class="muted">Showing {{ pageMeta.page_start }}–{{ pageMeta.page_end }} of {{ pageMeta.total }} species. Release-grade model organisms are prioritized within the result set.</p>
        </div>
        <div class="row">
          <button class="btn subtle" :disabled="!pageMeta.has_previous || loading" @click="loadPreviousPage">Previous</button>
          <span class="badge">Page {{ pageMeta.page }} / {{ pageMeta.total_pages }}</span>
          <button class="btn subtle" :disabled="!pageMeta.has_next || loading" @click="loadNextPage">Next</button>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import SpeciesAtlasOverview from '../components/SpeciesAtlasOverview.vue'
import { getSpeciesAtlasVisuals, getSpeciesFacets, listSpecies } from '../api/stoichdb'

const speciesRows = ref([])
const facets = ref({ source_databases: [], domains: [], clades: [], habitats: [], omics_breakdown: [], ranges: {}, fingerprint_keys: [] })
const loading = ref(true)
const atlasLoading = ref(true)
const loadError = ref('')
const atlasError = ref('')
const atlasPayload = ref(null)
const query = ref('')
const omics = ref('')
const domain = ref('')
const clade = ref('')
const habitat = ref('')
const hasAllOmics = ref(true)
const genomeSizeMin = ref('')
const genomeSizeMax = ref('')
const fingerprintKey = ref('')
const fingerprintMin = ref('')
const fingerprintMax = ref('')
const sortBy = ref('display_name')
const sortOrder = ref('asc')
const viewMode = ref('cards')
const page = ref(1)
const pageSize = ref(24)
const pageMeta = ref({ page: 1, page_size: 24, total: 0, total_pages: 1, has_next: false, has_previous: false, page_start: 0, page_end: 0 })
const useLogGenomeSize = ref(false)
const registryAggregate = ref(null)

const buildFingerprintFilters = () => {
  if (!fingerprintKey.value) return ''
  return JSON.stringify([{ key: fingerprintKey.value, min: fingerprintMin.value === '' ? undefined : fingerprintMin.value, max: fingerprintMax.value === '' ? undefined : fingerprintMax.value }])
}

const buildSpeciesParams = () => ({
  query: query.value,
  omics: omics.value,
  domain: domain.value,
  clade: clade.value,
  habitat: habitat.value,
  has_all_omics: hasAllOmics.value ? 1 : '',
  genome_size_min: genomeSizeMin.value,
  genome_size_max: genomeSizeMax.value,
  fingerprint_filters: buildFingerprintFilters(),
  sort_by: sortBy.value,
  sort_order: sortOrder.value,
  page: page.value,
  page_size: pageSize.value,
})

const buildAtlasParams = () => ({
  query: query.value,
  domain: domain.value,
  clade: clade.value,
  habitat: habitat.value,
  genome_size_min: genomeSizeMin.value,
  genome_size_max: genomeSizeMax.value,
  fingerprint_filters: buildFingerprintFilters(),
})

const buildAtlasVisualsParams = () => ({ ...buildAtlasParams(), omics: omics.value, has_all_omics: hasAllOmics.value ? 1 : '' })
let listEpoch = 0, atlasEpoch = 0, listController, atlasController
const canceled = error => error?.code === 'ERR_CANCELED' || error?.name === 'AbortError'
const errorMessage = (error, fallback) => error?.response?.data?.error?.message || error?.response?.data?.message || error?.message || fallback
onBeforeUnmount(() => { ++listEpoch; ++atlasEpoch; listController?.abort(); atlasController?.abort() })

const applySpeciesPayload = (payload) => {
  if (Array.isArray(payload)) {
    speciesRows.value = payload
    registryAggregate.value = null
    pageMeta.value = {
      page: 1,
      page_size: payload.length,
      total: payload.length,
      total_pages: 1,
      has_next: false,
      has_previous: false,
      page_start: payload.length ? 1 : 0,
      page_end: payload.length,
    }
    return
  }
  const items = payload?.items || []
  speciesRows.value = items
  registryAggregate.value = payload?.aggregate || null
  const total = Number(payload?.total) || 0
  const currentPage = Number(payload?.page) || page.value
  const currentPageSize = Number(payload?.page_size) || pageSize.value
  page.value = currentPage
  pageMeta.value = {
    page: currentPage,
    page_size: currentPageSize,
    total,
    total_pages: Number(payload?.total_pages) || 1,
    has_next: Boolean(payload?.has_next),
    has_previous: Boolean(payload?.has_previous),
    page_start: total ? ((currentPage - 1) * currentPageSize) + 1 : 0,
    page_end: total ? Math.min(currentPage * currentPageSize, total) : 0,
  }
}

const loadAtlas = async (params = buildAtlasVisualsParams()) => {
  const epoch = ++atlasEpoch
  atlasController?.abort(); atlasController = new AbortController()
  atlasLoading.value = true; atlasError.value = ''
  try { const result = await getSpeciesAtlasVisuals(params, { signal: atlasController.signal }); if (epoch === atlasEpoch) atlasPayload.value = result }
  catch (error) { if (epoch === atlasEpoch && !canceled(error)) atlasError.value = errorMessage(error, 'Atlas summary request failed.') }
  finally { if (epoch === atlasEpoch) atlasLoading.value = false }
}

const load = async (options = {}) => {
  if (options?.resetPage !== false) page.value = 1
  const epoch = ++listEpoch, params = buildSpeciesParams(), atlasParams = buildAtlasVisualsParams()
  listController?.abort(); listController = new AbortController()
  loading.value = true; loadError.value = ''
  try {
    const [result] = await Promise.all([listSpecies(params, { signal: listController.signal }), options?.refreshAtlas === false ? Promise.resolve() : loadAtlas(atlasParams)])
    if (epoch === listEpoch) applySpeciesPayload(result)
  } catch (error) {
    if (epoch === listEpoch && !canceled(error)) {
      speciesRows.value = []
      pageMeta.value = { page: 1, page_size: pageSize.value, total: 0, total_pages: 1, has_next: false, has_previous: false, page_start: 0, page_end: 0 }
      loadError.value = errorMessage(error, 'Species list request failed.')
    }
  } finally { if (epoch === listEpoch) loading.value = false }
}

const reset = async () => {
  query.value = ''
  omics.value = ''
  domain.value = ''
  clade.value = ''
  habitat.value = ''
  hasAllOmics.value = true
  genomeSizeMin.value = ''
  genomeSizeMax.value = ''
  fingerprintKey.value = ''
  fingerprintMin.value = ''
  fingerprintMax.value = ''
  sortBy.value = 'display_name'
  sortOrder.value = 'asc'
  viewMode.value = 'cards'
  page.value = 1
  useLogGenomeSize.value = false
  await load()
}

const loadNextPage = async () => {
  if (!pageMeta.value.has_next) return
  page.value += 1
  await load({ resetPage: false, refreshAtlas: false })
}

const loadPreviousPage = async () => {
  if (!pageMeta.value.has_previous) return
  page.value = Math.max(1, page.value - 1)
  await load({ resetPage: false, refreshAtlas: false })
}

const applyCoverageDrilldown = async ({ domain: nextDomain = '', omics: nextOmics = '', allThree = false } = {}) => {
  domain.value = nextDomain
  omics.value = nextOmics
  hasAllOmics.value = Boolean(allThree)
  await load({ resetPage: true, refreshAtlas: true })
}

const formatKey = (key) => String(key || '').replaceAll('_', ' ')
const formatCompleteness = (value) => {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return '-'
  return `${numeric.toFixed(numeric >= 99.95 ? 0 : 1)}%`
}

async function initialize() {
  try { const [result] = await Promise.all([getSpeciesFacets(), load({ resetPage: false, refreshAtlas: true })]); facets.value = result }
  catch (error) { loadError.value = errorMessage(error, 'Registry facets request failed.') }
}

onMounted(initialize)
</script>
