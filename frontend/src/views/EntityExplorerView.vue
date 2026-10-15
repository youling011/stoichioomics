<template>
  <div class="page-stack">
    <section class="panel">
      <div class="section-header">
        <div>
          <div class="eyebrow">Entity Explorer</div>
          <h2>Gene, transcript, and protein search</h2>
          <p>
            Search a single ID globally or within one species, then open a structured entity report with background percentiles,
            candidate evidence, cross-omics links, and raw field traceability.
          </p>
        </div>
      </div>
      <EntitySearchBar
        :query="query"
        :species-id="speciesId"
        :omics="omics"
        :id-type="idType"
        :confidence="mappingConfidence"
        :status="mappingStatus"
        :mapping-level="mappingLevel"
        :external-status="externalStatus"
        :conflict-only="conflictOnly"
        :loading="loading"
        @search="runSearch"
      />
      <p v-if="speciesId" class="annotation">Search is limited to species: {{ speciesId }}.</p>
      <p class="annotation">ID Resolution Layer is queried first. EntityRecord fallback uses exact ID matching inside the selected species.</p>
      <p v-if="loading" class="muted">Searching entity index...</p>
      <p v-if="error" class="error-text">{{ error }}</p>
    </section>

    <section class="panel" v-if="searched">
      <div class="section-header compact">
        <div>
          <h3>Entity matches</h3>
          <p>{{ result.total || 0 }} matching rows from {{ result.source || 'the current platform index' }}.</p>
        </div>
      </div>
      <EntityMatchTable :matches="result.matches || []" />
    </section>

    <section class="panel" v-if="searched">
      <div class="section-header compact">
        <div>
          <h3>GO/KEGG annotation matches</h3>
          <p>{{ annotationResults.length }} standard annotation records matched the query.</p>
        </div>
      </div>
      <div v-if="annotationResults.length" class="table-wrap">
        <table class="table compact-table">
          <thead><tr><th>Kind</th><th>Species</th><th>Entity</th><th>Annotation</th><th>Name</th><th></th></tr></thead>
          <tbody>
            <tr v-for="row in annotationResults" :key="`${row.kind}-${row.species_id}-${row.entity_key}-${row.annotation_id}`">
              <td>{{ row.kind }}</td>
              <td>{{ row.species_id }}</td>
              <td>{{ row.entity_key }}</td>
              <td>{{ row.annotation_id }}</td>
              <td>{{ row.annotation_name || row.namespace || row.annotation_type || '-' }}</td>
              <td><router-link :to="`/species/${row.species_id}/entity/${row.entity_key}`">Open report</router-link></td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="annotation">No GO/KEGG annotation record matched this query.</p>
    </section>

    <BatchEntityWorkbench :species-id="speciesId" />
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import EntitySearchBar from '../components/EntitySearchBar.vue'
import EntityMatchTable from '../components/EntityMatchTable.vue'
import BatchEntityWorkbench from '../components/BatchEntityWorkbench.vue'
import { searchAnnotations, searchEntities, searchIdMappings } from '../api/stoichdb'

const route = useRoute()
const router = useRouter()

const query = ref(String(route.query.q || route.query.query || ''))
const omics = ref(String(route.query.omics || ''))
const speciesId = ref(String(route.query.species_id || ''))
const idType = ref(String(route.query.id_type || ''))
const mappingConfidence = ref(String(route.query.mapping_confidence || ''))
const mappingStatus = ref(String(route.query.mapping_status || ''))
const mappingLevel = ref(String(route.query.mapping_level || ''))
const externalStatus = ref(String(route.query.external_status || ''))
const conflictOnly = ref(String(route.query.conflict_only || '') === '1')
const loading = ref(false)
const error = ref('')
const searched = ref(false)
const result = ref({ matches: [], total: 0 })
const annotationResults = ref([])

function looksLikeAnnotationQuery(value) {
  const text = String(value || '').trim().toUpperCase()
  if (!text) return false
  if (text.startsWith('GO:')) return true
  if (text.startsWith('KO:') || text.startsWith('PATH:') || text.startsWith('MAP')) return true
  return text.startsWith('K') && text.length >= 6 && /\d/.test(text.slice(1))
}

async function runSearch(payload = {}) {
  query.value = payload.q ?? query.value
  speciesId.value = payload.species_id ?? speciesId.value
  omics.value = payload.omics ?? omics.value
  idType.value = payload.id_type ?? idType.value
  mappingConfidence.value = payload.mapping_confidence ?? mappingConfidence.value
  mappingStatus.value = payload.mapping_status ?? mappingStatus.value
  mappingLevel.value = payload.mapping_level ?? mappingLevel.value
  externalStatus.value = payload.external_status ?? externalStatus.value
  conflictOnly.value = !!payload.conflict_only
  if (!query.value) return
  loading.value = true
  error.value = ''
  searched.value = true
  router.replace({
    query: {
      q: query.value,
      ...(omics.value ? { omics: omics.value } : {}),
      ...(speciesId.value ? { species_id: speciesId.value } : {}),
      ...(idType.value ? { id_type: idType.value } : {}),
      ...(mappingConfidence.value ? { mapping_confidence: mappingConfidence.value } : {}),
      ...(mappingStatus.value ? { mapping_status: mappingStatus.value } : {}),
      ...(mappingLevel.value ? { mapping_level: mappingLevel.value } : {}),
      ...(externalStatus.value ? { external_status: externalStatus.value } : {}),
      ...(conflictOnly.value ? { conflict_only: '1' } : {}),
    },
  }).catch(() => {})
  try {
    const shouldSearchAnnotations = !!speciesId.value || looksLikeAnnotationQuery(query.value)
    const [mappingResult, annotationResult] = await Promise.all([
      searchIdMappings({
        query: query.value,
        species_id: speciesId.value,
        id_type: idType.value,
        mapping_confidence: mappingConfidence.value,
        mapping_status: mappingStatus.value,
        mapping_level: mappingLevel.value,
        external_status: externalStatus.value,
        conflict_only: conflictOnly.value ? 1 : '',
        limit: 50,
      }),
      shouldSearchAnnotations ? searchAnnotations({
        query: query.value,
        species_id: speciesId.value,
        limit: 50,
      }) : Promise.resolve({ results: [] }),
    ])
    annotationResults.value = annotationResult.results || []
    if (mappingResult.matches?.length) {
      result.value = { ...mappingResult, source: 'ID mapping alias index' }
    } else {
      const fallback = await searchEntities({
        q: query.value,
        omics: omics.value,
        species_id: speciesId.value,
        limit: 50,
        include_synonyms: 1,
      })
      result.value = { ...fallback, source: 'EntityRecord fallback search' }
    }
  } catch (err) {
    error.value = err?.message || 'Entity search failed.'
    result.value = { matches: [], total: 0 }
    annotationResults.value = []
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  if (query.value) runSearch()
})
</script>
