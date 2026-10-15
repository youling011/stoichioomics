<template>
  <section class="panel">
    <div class="section-header compact">
      <div>
        <h3>Batch entity workbench</h3>
        <p>Paste one gene, transcript, or protein ID per line to produce a ranked candidate table.</p>
      </div>
      <div class="row">
        <button class="btn subtle" @click="downloadCsv" :disabled="!result.rows?.length">Download CSV</button>
        <button class="btn" @click="runBatch" :disabled="loading || !idsText.trim()">Run batch</button>
      </div>
    </div>
    <textarea v-model="idsText" class="input batch-input" placeholder="gene_id&#10;protein_id&#10;transcript_id"></textarea>
    <p v-if="loading" class="muted">Running batch entity report...</p>
    <p v-if="error" class="error-text">{{ error }}</p>
    <div class="table-wrap" v-if="result.rows?.length">
      <table class="table compact-table">
        <thead>
          <tr>
            <th>Rank</th>
            <th>Input</th>
            <th>Matched</th>
            <th>Species</th>
            <th>Omics</th>
            <th>Modules</th>
            <th>Severity</th>
            <th>Priority</th>
            <th>Report</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in result.rows" :key="`${row.input_id}-${row.matched_id}`">
            <td>{{ row.priority_rank }}</td>
            <td>{{ row.input_id }}</td>
            <td>{{ row.matched_id }}</td>
            <td>{{ row.species_id }}</td>
            <td>{{ row.omics_available }}</td>
            <td>{{ row.hit_module_count }}</td>
            <td>{{ row.max_severity }}</td>
            <td>{{ format(row.priority_score) }}</td>
            <td><router-link class="ghost-link" :to="row.report_url">Open</router-link></td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-if="result.unmatched?.length" class="annotation">
      Unmatched: {{ result.unmatched.map((row) => row.input_id).join(', ') }}
    </p>
  </section>
</template>

<script setup>
import { ref } from 'vue'
import { batchEntityReport } from '../api/stoichdb'

const props = defineProps({
  speciesId: { type: String, default: '' },
})

const idsText = ref('')
const loading = ref(false)
const error = ref('')
const result = ref({ rows: [], unmatched: [] })

async function runBatch() {
  loading.value = true
  error.value = ''
  try {
    const ids = idsText.value.split(/\r?\n|,/).map((item) => item.trim()).filter(Boolean)
    result.value = await batchEntityReport({ species_id: props.speciesId || '', ids })
  } catch (err) {
    error.value = err?.message || 'Batch entity report failed.'
  } finally {
    loading.value = false
  }
}

function format(value) {
  const num = Number(value)
  if (!Number.isFinite(num)) return value ?? '-'
  return num.toFixed(3)
}

function csvEscape(value) {
  const text = String(value ?? '')
  return /[",\n\r]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text
}

function downloadCsv() {
  const columns = ['priority_rank', 'input_id', 'matched_id', 'species_id', 'gene_id', 'gene_name', 'omics_available', 'hit_module_count', 'max_severity', 'tail_feature_count', 'link_confidence', 'priority_score', 'report_url']
  const lines = [columns.join(',')]
  ;(result.value.rows || []).forEach((row) => {
    lines.push(columns.map((key) => csvEscape(row[key])).join(','))
  })
  const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `entity_batch_report_${props.speciesId || 'global'}.csv`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}
</script>

<style scoped>
.batch-input {
  min-height: 130px;
  resize: vertical;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
}
</style>
