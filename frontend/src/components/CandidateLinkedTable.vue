<template>
  <div class="table-wrap candidate-linked-table" v-if="rows.length">
    <table class="table compact-table">
      <thead>
        <tr>
          <th>Entity</th>
          <th>Gene / transcript / protein</th>
          <th v-for="field in valueFields" :key="field">{{ formatKey(field) }}</th>
          <th>Score</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows.slice(0, limit)" :key="row.entity_id || row.gene_id || row.transcript_id || row.protein_id">
          <td>
            <router-link v-if="reportRoute(row)" class="ghost-link" :to="reportRoute(row)">{{ row.entity_id || '-' }}</router-link>
            <span v-else>{{ row.entity_id || '-' }}</span>
          </td>
          <td>{{ row.gene_name || row.gene_id || row.transcript_id || row.protein_id || '-' }}</td>
          <td v-for="field in valueFields" :key="`${row.entity_id}-${field}`">{{ formatValue(row[field]) }}</td>
          <td>{{ formatValue(row.residual ?? row.quadrant_score ?? row.outlier_score) }}</td>
        </tr>
      </tbody>
    </table>
  </div>
  <p v-else class="annotation">No linked candidates are available for this scatter payload.</p>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  candidates: { type: Array, default: () => [] },
  limit: { type: Number, default: 8 },
  speciesId: { type: String, default: '' },
})

const rows = computed(() => props.candidates || [])
const valueFields = computed(() => {
  const first = rows.value[0] || {}
  return Object.keys(first)
    .filter((key) => !['entity_id', 'gene_id', 'gene_name', 'transcript_id', 'protein_id', 'residual', 'quadrant_score', 'outlier_score'].includes(key))
    .slice(0, 2)
})

function formatKey(key = '') {
  return String(key || '').replaceAll('_', ' ')
}

function formatValue(value) {
  const num = Number(value)
  if (!Number.isFinite(num)) return value ?? '-'
  if (Math.abs(num) >= 100) return num.toFixed(1)
  if (Math.abs(num) >= 10) return num.toFixed(2)
  return num.toFixed(4)
}

function reportRoute(row = {}) {
  const speciesId = row.species_id || props.speciesId
  const entityKey = row.gene_id || row.entity_id || row.protein_id || row.transcript_id
  if (!speciesId || !entityKey) return ''
  return `/species/${encodeURIComponent(speciesId)}/entity/${encodeURIComponent(entityKey)}`
}
</script>

<style scoped>
.candidate-linked-table {
  margin-top: 10px;
}
</style>
