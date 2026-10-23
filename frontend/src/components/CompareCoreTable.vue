<template>
  <section class="stack">
    <div class="table-tools">
      <input v-model="query" class="input" type="search" aria-label="Filter result table" placeholder="Search species, field or family" @keyup.enter="reload(true)" />
      <button class="btn subtle" :disabled="loading" @click="reload(true)">Filter</button>
      <a :href="compareDownload(runId, kind)" class="btn subtle">Complete CSV</a>
    </div>
    <p v-if="error" role="alert" class="annotation">{{ error }}</p>
    <div class="table-wrap" :aria-busy="loading">
      <table class="compact-table"><caption>{{ label }} · {{ total }} rows; null means unavailable</caption>
        <thead><tr><th v-for="key in columns" :key="key"><button class="sort-key" @click="sort(key)">{{ key.replaceAll('_', ' ') }} {{ sortBy === key ? (direction === 'asc' ? '↑' : '↓') : '' }}</button></th></tr></thead>
        <tbody><tr v-for="(row, index) in rows" :key="index"><td v-for="key in columns" :key="key">{{ format(row[key]) }}</td></tr></tbody>
      </table>
      <p v-if="!loading && !rows.length" class="annotation">No estimable rows for this table and filter. Check task, field coverage and exclusion reasons.</p>
    </div>
    <div class="table-tools"><button class="btn subtle" :disabled="loading || page <= 1" @click="page--; reload()">Previous</button><span>Page {{ page }} · {{ rows.length }} / {{ total }}</span><button class="btn subtle" :disabled="loading || !hasNext" @click="page++; reload()">Next</button></div>
  </section>
</template>
<script setup>
import { ref, watch, onBeforeUnmount } from 'vue'
import { compareTable, compareDownload } from '../api/compareCore'
const props = defineProps({ runId: String, kind: String, field: { type: String, default: '' }, label: { type: String, default: 'Complete statistical table' } })
const rows = ref([]), total = ref(0), page = ref(1), hasNext = ref(false), query = ref(''), sortBy = ref(''), direction = ref('asc'), loading = ref(false), error = ref(''), columns = ref([])
let sequence = 0
async function reload(reset = false) {
  if (!props.runId) return
  if (reset) page.value = 1
  const seq = ++sequence
  loading.value = true; error.value = ''
  try {
    const data = await compareTable(props.runId, { kind: props.kind, field: props.field, page: page.value, page_size: 25, query: query.value, sort_by: sortBy.value, direction: direction.value })
    if (seq !== sequence) return
    rows.value = data.items; total.value = data.total; hasNext.value = data.has_next
    columns.value = [...new Set(data.items.flatMap(Object.keys))]
  } catch (e) { if (seq === sequence) error.value = e.response?.data?.error?.message || e.message }
  finally { if (seq === sequence) loading.value = false }
}
function sort(key) { direction.value = sortBy.value === key && direction.value === 'asc' ? 'desc' : 'asc'; sortBy.value = key; reload(true) }
function format(value) { if (value == null) return '—'; if (typeof value === 'object') return JSON.stringify(value); if (typeof value === 'number') return Number.isInteger(value) ? value : Number(value.toPrecision(6)); return value }
watch(() => [props.runId, props.kind, props.field], () => { sortBy.value = ''; reload(true) }, { immediate: true })
onBeforeUnmount(() => sequence++)
</script>
<style scoped>
.table-tools{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.table-tools .input{max-width:360px}.table-wrap{max-width:100%;overflow:auto;max-height:620px}.compact-table{min-width:640px}.compact-table td{max-width:350px;overflow-wrap:anywhere;vertical-align:top}.sort-key{border:0;background:transparent;color:inherit;font:inherit;text-align:left;cursor:pointer;white-space:nowrap}caption{text-align:left;padding:12px 0;color:var(--muted,#5c7590)}
</style>
