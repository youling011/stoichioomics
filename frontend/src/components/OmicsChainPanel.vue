<template>
  <div class="omics-chain">
    <div class="chain-node" :class="{ active: Boolean(chain.genome_entity_id) }">
      <span>Genome</span>
      <strong>{{ chain.genome_entity_id || 'missing' }}</strong>
    </div>
    <div class="chain-link">DNA → RNA</div>
    <div class="chain-node" :class="{ active: transcriptCount }">
      <span>Transcript sequence</span>
      <strong>{{ transcriptCount }} transcript{{ transcriptCount === 1 ? '' : 's' }}</strong>
    </div>
    <div class="chain-link">RNA → Protein</div>
    <div class="chain-node" :class="{ active: proteinCount }">
      <span>Proteome</span>
      <strong>{{ proteinCount }} protein{{ proteinCount === 1 ? '' : 's' }}</strong>
    </div>
    <div class="chain-note">
      <span class="badge">{{ chain.link_confidence || 'unknown' }} confidence</span>
      <p class="annotation">{{ chain.isoform_rule }}</p>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  chain: { type: Object, default: () => ({}) },
})

const transcriptCount = computed(() => (props.chain.transcript_entities || []).length)
const proteinCount = computed(() => (props.chain.protein_entities || []).length)
</script>

<style scoped>
.omics-chain {
  display: grid;
  grid-template-columns: 1fr auto 1fr auto 1fr;
  gap: 10px;
  align-items: stretch;
}

.chain-node {
  border: 1px solid rgba(42, 89, 140, 0.14);
  border-radius: 8px;
  padding: 14px;
  background: #f8fbff;
}

.chain-node.active {
  border-color: rgba(47, 119, 200, 0.34);
  background: #eff6ff;
}

.chain-node span,
.chain-note {
  color: #607894;
  font-size: 13px;
}

.chain-node strong {
  display: block;
  margin-top: 6px;
  color: #123c69;
  word-break: break-all;
}

.chain-link {
  align-self: center;
  color: #4f6b86;
  font-size: 13px;
}

.chain-note {
  grid-column: 1 / -1;
}

@media (max-width: 900px) {
  .omics-chain {
    grid-template-columns: 1fr;
  }

  .chain-link {
    display: none;
  }
}
</style>
