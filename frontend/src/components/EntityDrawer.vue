<template>
  <aside class="entity-drawer" v-if="entity">
    <div class="drawer-head">
      <div>
        <div class="eyebrow">Entity context</div>
        <h3>{{ entity.entity_id || entity.gene_id || entity.protein_id || entity.transcript_id }}</h3>
      </div>
      <button class="btn subtle" @click="$emit('close')">Close</button>
    </div>
    <p class="muted">{{ entity.gene_name || entity.description || 'Chart-linked entity point' }}</p>
    <router-link
      v-if="reportRoute"
      class="btn"
      :to="reportRoute"
    >
      Open full report
    </router-link>
  </aside>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  entity: { type: Object, default: null },
  speciesId: { type: String, default: '' },
})
defineEmits(['close'])

const reportRoute = computed(() => {
  if (!props.entity) return ''
  const speciesId = props.entity.species_id || props.speciesId
  const entityKey = props.entity.gene_id || props.entity.entity_id || props.entity.protein_id || props.entity.transcript_id
  if (!speciesId || !entityKey) return ''
  return `/species/${encodeURIComponent(speciesId)}/entity/${encodeURIComponent(entityKey)}`
})
</script>

<style scoped>
.entity-drawer {
  position: fixed;
  right: 18px;
  bottom: 18px;
  width: min(420px, calc(100vw - 36px));
  z-index: 20;
  border: 1px solid rgba(42, 89, 140, 0.18);
  border-radius: 10px;
  background: #fff;
  box-shadow: 0 18px 48px rgba(10, 31, 56, 0.18);
  padding: 16px;
}

.drawer-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: start;
}

.drawer-head h3 {
  margin: 4px 0;
  word-break: break-all;
}
</style>
