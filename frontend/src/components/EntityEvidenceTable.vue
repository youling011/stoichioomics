<template>
  <div class="table-wrap" v-if="evidence.length">
    <table class="table compact-table">
      <thead>
        <tr>
          <th>Module</th>
          <th>Scope</th>
          <th>Candidate type</th>
          <th>Score</th>
          <th>Score field</th>
          <th>Severity</th>
          <th>Evidence level</th>
          <th>Explanation</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="item in evidence" :key="`${item.module_id}-${item.source_path}`">
          <td>{{ item.module_id }}</td>
          <td>{{ item.omics_scope }}</td>
          <td>{{ item.candidate_type }}</td>
          <td>{{ format(item.score) }}</td>
          <td>{{ item.score_field || '-' }}</td>
          <td><span class="badge" :class="classFor(item.severity_level)">{{ item.severity_level }}</span></td>
          <td>{{ item.evidence_level }}</td>
          <td>{{ item.explanation }}</td>
        </tr>
      </tbody>
    </table>
  </div>
  <p v-else class="muted">No candidate evidence table rows are linked to this entity.</p>
</template>

<script setup>
defineProps({
  evidence: { type: Array, default: () => [] },
})

function format(value) {
  const num = Number(value)
  if (!Number.isFinite(num)) return value ?? '-'
  return num.toFixed(3).replace(/\.000$/, '')
}

function classFor(severity = '') {
  const level = String(severity).toLowerCase()
  if (level === 'extreme' || level === 'high') return 'hot-badge'
  if (level === 'medium') return 'cool-badge'
  return 'muted-badge'
}
</script>
