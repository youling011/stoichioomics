<template>
  <form class="entity-search-bar" @submit.prevent="submit">
    <input v-model.trim="localQuery" class="input query-input" placeholder="Enter gene, transcript, protein, UniProt, NCBI, RefSeq, or INSDC ID" />
    <input v-model.trim="localSpeciesId" class="input compact-input species-input" placeholder="Species ID" />
    <select v-model="localIdType" class="input compact-input">
      <option value="">All ID types</option>
      <option value="gene_id">Gene</option>
      <option value="transcript_id">Transcript</option>
      <option value="protein_id">Protein</option>
      <option value="uniprot">UniProt</option>
      <option value="ncbi_gene">NCBI Gene</option>
      <option value="ncbi_protein">NCBI protein</option>
      <option value="refseq_protein">RefSeq protein</option>
      <option value="insdc_protein">INSDC protein</option>
      <option value="insdc_region">INSDC region</option>
      <option value="gene_symbol">Gene symbol</option>
    </select>
    <select v-model="localConfidence" class="input compact-input">
      <option value="">All confidence</option>
      <option value="high">High</option>
      <option value="medium">Medium</option>
      <option value="low">Low</option>
    </select>
    <select v-model="localStatus" class="input compact-input">
      <option value="">All status</option>
      <option value="ok">OK</option>
      <option value="conflict">Conflict</option>
    </select>
    <select v-model="localLevel" class="input compact-input">
      <option value="">All levels</option>
      <option value="gene_transcript_protein">G-T-P</option>
      <option value="gene_transcript">G-T</option>
    </select>
    <select v-model="localExternalStatus" class="input compact-input">
      <option value="">All external</option>
      <option value="mapped_uniprot">UniProt</option>
      <option value="mapped_ncbi_gene_or_protein">NCBI protein/gene</option>
      <option value="species_and_region_only">Region only</option>
      <option value="species_standard_only">Species only</option>
    </select>
    <label class="check-row">
      <input v-model="localConflictOnly" type="checkbox" />
      Conflict only
    </label>
    <button class="btn" type="submit" :disabled="!localQuery || loading">Search IDs</button>
  </form>
</template>

<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  query: { type: String, default: '' },
  speciesId: { type: String, default: '' },
  omics: { type: String, default: '' },
  idType: { type: String, default: '' },
  confidence: { type: String, default: '' },
  status: { type: String, default: '' },
  mappingLevel: { type: String, default: '' },
  externalStatus: { type: String, default: '' },
  conflictOnly: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
})
const emit = defineEmits(['search'])

const localQuery = ref(props.query)
const localSpeciesId = ref(props.speciesId)
const localOmics = ref(props.omics)
const localIdType = ref(props.idType)
const localConfidence = ref(props.confidence)
const localStatus = ref(props.status)
const localLevel = ref(props.mappingLevel)
const localExternalStatus = ref(props.externalStatus)
const localConflictOnly = ref(props.conflictOnly)

watch(() => props.query, (value) => { localQuery.value = value || '' })
watch(() => props.speciesId, (value) => { localSpeciesId.value = value || '' })
watch(() => props.omics, (value) => { localOmics.value = value || '' })
watch(() => props.idType, (value) => { localIdType.value = value || '' })
watch(() => props.confidence, (value) => { localConfidence.value = value || '' })
watch(() => props.status, (value) => { localStatus.value = value || '' })
watch(() => props.mappingLevel, (value) => { localLevel.value = value || '' })
watch(() => props.externalStatus, (value) => { localExternalStatus.value = value || '' })
watch(() => props.conflictOnly, (value) => { localConflictOnly.value = !!value })

function submit() {
  emit('search', {
    q: localQuery.value,
    species_id: localSpeciesId.value,
    omics: localOmics.value,
    id_type: localIdType.value,
    mapping_confidence: localConfidence.value,
    mapping_status: localStatus.value,
    mapping_level: localLevel.value,
    external_status: localExternalStatus.value,
    conflict_only: localConflictOnly.value,
  })
}
</script>

<style scoped>
.entity-search-bar {
  display: grid;
  grid-template-columns: minmax(280px, 1.4fr) minmax(150px, 0.65fr) repeat(5, minmax(130px, 0.55fr)) auto auto;
  gap: 10px;
  align-items: center;
}

.query-input {
  min-width: 260px;
}

.compact-input {
  min-width: 120px;
}

.species-input {
  min-width: 150px;
}

.check-row {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #40576d;
  font-size: 0.86rem;
  white-space: nowrap;
}

@media (max-width: 760px) {
  .entity-search-bar {
    grid-template-columns: 1fr;
  }
}
</style>
