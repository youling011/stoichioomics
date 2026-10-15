<template>
  <div class="grid grid-3">
    <article class="mini-card">
      <div class="label">Rows</div>
      <div class="metric-inline">{{ report.n_rows || 0 }}</div>
    </article>
    <article class="mini-card">
      <div class="label">Selected</div>
      <div class="metric-inline">{{ report.selected_features || 0 }}</div>
    </article>
    <article class="mini-card">
      <div class="label">Usable</div>
      <div class="metric-inline">{{ report.usable_features || 0 }}</div>
    </article>
    <article class="panel">
      <h4>Constants</h4>
      <p class="muted">{{ list(report.constant) }}</p>
    </article>
    <article class="panel">
      <h4>Duplicate groups</h4>
      <p class="muted">{{ (report.exact_duplicate_groups || []).length }} groups</p>
    </article>
    <article class="panel">
      <h4>Composition groups</h4>
      <p class="muted">{{ Object.keys(report.composition_groups || {}).join(', ') || 'None' }}</p>
    </article>
  </div>
  <div class="panel compact-top" v-if="(report.recommendations || []).length">
    <h4>Recommendations</h4>
    <ul class="clean-list">
      <li v-for="item in report.recommendations" :key="item">{{ item }}</li>
    </ul>
  </div>
</template>

<script setup>
defineProps({ report: { type: Object, default: () => ({}) } })

function list(items) {
  return (items || []).slice(0, 8).join(', ') || 'None'
}
</script>

