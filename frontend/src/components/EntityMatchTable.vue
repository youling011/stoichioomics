<template>
  <div class="table-wrap" v-if="matches.length">
    <table class="table compact-table">
      <thead>
        <tr>
          <th>Species</th>
          <th>Matched ID</th>
          <th>ID type</th>
          <th>Gene / transcript / protein</th>
          <th>Mapping</th>
          <th>External IDs</th>
          <th>Coverage</th>
          <th>Report</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in matches" :key="`${row.species_id}-${row.id_type || row.omics}-${row.entity_id || row.target_id || row.matched_id}`" :class="{ 'warning-row': row.conflict_warning || row.mapping_status === 'conflict' }">
          <td>{{ row.species_name || row.species_id }}</td>
          <td>{{ row.matched_id || row.entity_id }}</td>
          <td><span class="badge muted-badge">{{ row.id_type || row.omics || row.match_type }}</span></td>
          <td class="chain-cell">
            <span>{{ row.gene_id || row.gene_name || '-' }}</span>
            <span>{{ row.transcript_id || '-' }}</span>
            <span>{{ row.protein_id || row.secondary_id || '-' }}</span>
          </td>
          <td>
            <span :class="['badge', row.mapping_status === 'conflict' ? 'danger-badge' : '']">{{ row.mapping_status || row.match_type || 'matched' }}</span>
            <span class="badge muted-badge">{{ row.mapping_confidence || row.match_confidence || '-' }}</span>
          </td>
          <td>
            <span v-for="item in externalBadges(row)" :key="item" class="badge muted-badge">{{ item }}</span>
            <span v-if="!externalBadges(row).length" class="muted">-</span>
          </td>
          <td>
            <span class="badge muted-badge">G {{ yesNo(row.feature_coverage?.genome ?? row.gene_id) }}</span>
            <span class="badge muted-badge">T {{ yesNo(row.feature_coverage?.transcriptome ?? row.transcript_id) }}</span>
            <span class="badge muted-badge">P {{ yesNo(row.feature_coverage?.proteome ?? row.protein_id) }}</span>
          </td>
          <td>
            <router-link class="ghost-link" :to="reportRoute(row)">Open</router-link>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
  <p v-else class="muted">No entity matches are available for the current query.</p>
</template>

<script setup>
defineProps({
  matches: { type: Array, default: () => [] },
})

function reportRoute(row) {
  const entityKey = row.entity_key || row.gene_id || row.entity_id
  return `/species/${encodeURIComponent(row.species_id)}/entity/${encodeURIComponent(entityKey)}`
}

function yesNo(value) {
  return value ? 'yes' : 'no'
}

function externalBadges(row) {
  const ids = row.external_ids || {}
  const badges = []
  if ((ids.uniprot || []).length) badges.push(`UniProt ${ids.uniprot.length}`)
  if ((ids.ncbi_gene || []).length) badges.push(`NCBI Gene ${ids.ncbi_gene.length}`)
  if ((ids.ncbi_protein || []).length) badges.push(`NCBI Protein ${ids.ncbi_protein.length}`)
  if ((ids.refseq_protein || []).length) badges.push(`RefSeq ${ids.refseq_protein.length}`)
  if ((ids.insdc_protein || []).length || (ids.insdc_region || []).length) badges.push('INSDC')
  return badges
}
</script>

<style scoped>
.chain-cell {
  display: grid;
  gap: 2px;
  max-width: 320px;
  overflow-wrap: anywhere;
}

.danger-badge {
  background: #fff1f0;
  border-color: #e59b93;
  color: #9d2f26;
}

.warning-row {
  background: #fffaf0;
}
</style>
