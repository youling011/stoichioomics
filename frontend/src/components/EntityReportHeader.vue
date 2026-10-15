<template>
  <section class="panel entity-report-header">
    <div>
      <div class="eyebrow">{{ identity.species_name || identity.species_id }}</div>
      <h2>{{ identity.gene_id || identity.entity_key || identity.entity_id }}</h2>
      <p>{{ identity.description || identity.gene_name || 'Stoichiometric entity report' }}</p>
      <div class="row">
        <span class="badge">link {{ identity.link_confidence || 'unknown' }}</span>
        <span class="badge muted-badge">entity {{ identity.entity_id }}</span>
        <span class="badge muted-badge" v-if="identity.gene_name">{{ identity.gene_name }}</span>
      </div>
    </div>
    <div class="summary-cards compact-summary">
      <div v-for="card in cards" :key="card.label" class="summary-card">
        <span>{{ card.label }}</span>
        <strong>{{ card.value }}</strong>
        <small>{{ card.note }}</small>
      </div>
    </div>
  </section>
</template>

<script setup>
defineProps({
  identity: { type: Object, default: () => ({}) },
  cards: { type: Array, default: () => [] },
})
</script>

<style scoped>
.entity-report-header {
  display: grid;
  grid-template-columns: minmax(260px, 0.95fr) 1.3fr;
  gap: 18px;
  align-items: start;
}

.entity-report-header h2 {
  margin: 6px 0;
}

.compact-summary {
  margin: 0;
}

@media (max-width: 900px) {
  .entity-report-header {
    grid-template-columns: 1fr;
  }
}
</style>
