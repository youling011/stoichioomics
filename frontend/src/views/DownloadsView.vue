<template>
  <div class="stack-lg">
    <section class="panel">
      <div class="section-header">
        <div>
          <div class="eyebrow">Downloads</div>
          <h3>Source files and artifacts</h3>
          <p class="muted">Filter by species or omics to open raw feature tables, derived files, and analysis artifacts registered in the active release.</p>
        </div>
      </div>
      <div class="toolbar-grid wide">
        <select v-model="speciesId" class="input">
          <option value="">All species</option>
          <option v-for="row in speciesRows" :key="row.species_id" :value="row.species_id">{{ row.display_name }}</option>
        </select>
        <select v-model="omics" class="input">
          <option value="">All omics</option>
          <option value="genome">Genome</option>
          <option value="transcriptome">Transcript sequence</option>
          <option value="proteome">Proteome</option>
        </select>
        <button class="btn" :disabled="loading" @click="load">Apply</button>
        <button class="btn subtle" :disabled="materializing" @click="materializeArtifacts">
          {{ materializing ? 'Materializing...' : 'Materialize analysis artifacts' }}
        </button>
      </div>
      <p v-if="loading" class="annotation">Loading download registry...</p>
      <p v-else-if="loadError" class="annotation">{{ loadError }}</p>
      <p v-if="materializeResult" class="annotation">
        Generated {{ materializeResult.artifact_count }} reusable analysis artifact files at {{ materializeResult.export_root }}.
      </p>
    </section>

    <ActiveReleaseBanner
      v-if="payload?.release"
      :release="payload.release"
      :omics-coverage="downloadOmicsCoverage"
    />

    <section v-if="payload?.phylogeny_downloads?.length" class="panel">
      <div class="section-header compact">
        <div>
          <h3>Phylogeny release files</h3>
          <p class="muted">Versioned tree, tip mapping, trait matrix, validation and analysis-grade artifacts used by P3 phylogeny-aware modules.</p>
        </div>
      </div>
      <div class="table-wrap">
        <table class="table compact-table">
          <thead><tr><th>File</th><th>Kind</th><th>Description</th><th>Size</th><th>Status</th><th>Path</th></tr></thead>
          <tbody>
            <tr v-for="row in payload.phylogeny_downloads" :key="row.kind">
              <td>{{ row.label }}</td>
              <td>{{ row.kind }}</td>
              <td>{{ row.description }}</td>
              <td>{{ formatBytes(row.size_bytes) }}</td>
              <td><span :class="['badge', row.exists ? 'status-ready' : 'status-muted']">{{ row.exists ? 'available' : 'missing' }}</span></td>
              <td>{{ row.path }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section v-if="payload?.id_mapping_downloads?.length" class="panel">
      <div class="section-header compact">
        <div>
          <h3>ID mapping downloads</h3>
          <p class="muted">Download full all-species ID mapping tables, manifest, and QC summary used by the resolution layer.</p>
        </div>
      </div>
      <div class="table-wrap">
        <table class="table compact-table">
          <thead><tr><th>File</th><th>Description</th><th>Size</th><th></th></tr></thead>
          <tbody>
            <tr v-for="row in payload.id_mapping_downloads" :key="row.kind">
              <td>{{ row.label }}</td>
              <td>{{ row.description }}</td>
              <td>{{ formatBytes(row.size_bytes) }}</td>
              <td><a :href="row.url || idMappingDownloadUrl(row.kind)">Download</a></td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section v-if="payload?.annotation_downloads?.length" class="panel">
      <div class="section-header compact">
        <div>
          <h3>GO/KEGG annotation downloads</h3>
          <p class="muted">Download the official standard annotation bundle used by status, entity evidence, and enrichment APIs.</p>
        </div>
      </div>
      <div class="table-wrap">
        <table class="table compact-table">
          <thead><tr><th>File</th><th>Description</th><th>Size</th><th></th></tr></thead>
          <tbody>
            <tr v-for="row in payload.annotation_downloads" :key="row.kind">
              <td>{{ row.label }}</td>
              <td>{{ row.description }}</td>
              <td>{{ formatBytes(row.size_bytes) }}</td>
              <td><a :href="row.url || annotationDownloadUrl(row.kind)">Download</a></td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section v-if="payload" class="panel">
      <div class="section-header compact"><h3>Registered datasets</h3></div>
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>Species</th>
              <th>Omics</th>
              <th>Dataset ID</th>
              <th>QC</th>
              <th>Schema</th>
              <th>Release</th>
              <th>Rows</th>
              <th>Files</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in payload.datasets || []" :key="row.dataset_id">
              <td>{{ row.species_name }}</td>
              <td>{{ row.omics }}</td>
              <td>{{ row.dataset_id }}</td>
              <td><span class="badge">{{ row.qc_grade || '-' }}</span></td>
              <td>{{ row.schema_version || '-' }}</td>
              <td>{{ row.release_id || '-' }}</td>
              <td>{{ row.row_count_full || row.row_count_core }}</td>
              <td>{{ row.feature_files?.length || 0 }}</td>
              <td><router-link :to="row.source_page_route">Open source page</router-link></td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section v-if="payload" class="grid grid-2">
      <article class="panel">
        <div class="section-header compact"><h3>Feature files</h3></div>
        <div class="table-wrap">
          <table class="table compact-table">
            <thead>
              <tr>
                <th>Dataset</th>
                <th>Type</th>
                <th>Schema</th>
                <th>Release</th>
                <th>Checksum</th>
                <th>Generated</th>
                <th>Filename</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in flattenedFiles" :key="row.file_id">
                <td>{{ row.dataset_id }}</td>
                <td>{{ row.file_type }}</td>
                <td>{{ row.schema_version || '-' }}</td>
                <td>{{ row.release_id || '-' }}</td>
                <td>{{ shortChecksum(row.checksum, row.checksum_status) }}</td>
                <td>{{ row.generated_at || '-' }}</td>
                <td>{{ row.filename }}</td>
                <td><a :href="featureFileDownloadUrl(row.file_id)">Download</a></td>
              </tr>
            </tbody>
          </table>
        </div>
      </article>
      <article class="panel">
        <div class="section-header compact"><h3>Artifacts</h3></div>
        <div class="table-wrap">
          <table class="table compact-table">
            <thead>
              <tr>
                <th>Species</th>
                <th>Type</th>
                <th>Method</th>
                <th>Normalization</th>
                <th>Missing policy</th>
                <th>Schema</th>
                <th>Release</th>
                <th>Checksum</th>
                <th>Generated</th>
                <th>n</th>
                <th>Exploratory</th>
                <th>Filename</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in payload.artifacts || []" :key="row.artifact_id">
                <td>{{ row.species_name }}</td>
                <td>{{ row.artifact_type }}</td>
                <td>{{ row.analysis_metadata?.method || '-' }}</td>
                <td>{{ row.analysis_metadata?.normalization || '-' }}</td>
                <td>{{ row.analysis_metadata?.missing_policy || '-' }}</td>
                <td>{{ row.schema_version || '-' }}</td>
                <td>{{ row.release_id || row.analysis_metadata?.release_id || '-' }}</td>
                <td>{{ shortChecksum(row.checksum, row.checksum_status) }}</td>
                <td>{{ row.generated_at || row.created_at || '-' }}</td>
                <td>{{ row.analysis_metadata?.n_entities || '-' }}</td>
                <td>{{ row.analysis_metadata?.is_exploratory ? 'yes' : 'no' }}</td>
                <td>{{ row.filename }}</td>
                <td><a :href="artifactDownloadUrl(row.artifact_id)">Download</a></td>
              </tr>
            </tbody>
          </table>
        </div>
      </article>
    </section>

    <section v-if="!loading && !loadError && !payload" class="panel">
      <p class="muted">No download payload is available.</p>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import ActiveReleaseBanner from '../components/ActiveReleaseBanner.vue'
import { annotationDownloadUrl, artifactDownloadUrl, featureFileDownloadUrl, getDownloads, idMappingDownloadUrl, listSpecies, materializeAnalysisArtifacts } from '../api/stoichdb'

const speciesRows = ref([])
const speciesId = ref('')
const omics = ref('')
const payload = ref(null)
const loading = ref(true)
const loadError = ref('')
const materializing = ref(false)
const materializeResult = ref(null)

const flattenedFiles = computed(() =>
  (payload.value?.datasets || []).flatMap((row) =>
    (row.feature_files || []).map((file) => ({
      ...file,
      dataset_id: row.dataset_id,
    })),
  ),
)

const downloadOmicsCoverage = computed(() => {
  const counts = {}
  ;(payload.value?.datasets || []).forEach((row) => {
    counts[row.omics] = (counts[row.omics] || 0) + 1
  })
  return Object.entries(counts).map(([omicsKey, count]) => ({ omics: omicsKey, count }))
})

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    payload.value = await getDownloads({
      species: speciesId.value,
      omics: omics.value,
      dataset_limit: 300,
      artifact_limit: 300,
    })
  } catch (error) {
    payload.value = null
    loadError.value =
      error?.response?.data?.error?.message ||
      error?.response?.data?.message ||
      error?.message ||
      'Failed to load download registry.'
  } finally {
    loading.value = false
  }
}

async function materializeArtifacts() {
  materializing.value = true
  materializeResult.value = null
  try {
    materializeResult.value = await materializeAnalysisArtifacts()
    await load()
  } catch (error) {
    loadError.value =
      error?.response?.data?.error?.message ||
      error?.response?.data?.message ||
      error?.message ||
      'Failed to materialize analysis artifacts.'
  } finally {
    materializing.value = false
  }
}

function shortChecksum(value, status) {
  if (value) return `${String(value).slice(0, 12)}...`
  return status || '-'
}

function formatBytes(value) {
  const n = Number(value)
  if (!Number.isFinite(n) || n <= 0) return '-'
  if (n > 1024 * 1024 * 1024) return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`
  if (n > 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`
  return `${(n / 1024).toFixed(1)} KB`
}

onMounted(async () => {
  loading.value = true
  loadError.value = ''
  try {
    const [speciesPayload, downloadsPayload] = await Promise.all([
      listSpecies({ page: 1, page_size: 500 }),
      getDownloads({
        species: speciesId.value,
        omics: omics.value,
        dataset_limit: 300,
        artifact_limit: 300,
      }),
    ])
    speciesRows.value = Array.isArray(speciesPayload) ? speciesPayload : (speciesPayload?.items || [])
    payload.value = downloadsPayload
  } catch (error) {
    speciesRows.value = []
    payload.value = null
    loadError.value =
      error?.response?.data?.error?.message ||
      error?.response?.data?.message ||
      error?.message ||
      'Failed to initialize download registry.'
  } finally {
    loading.value = false
  }
})
</script>
