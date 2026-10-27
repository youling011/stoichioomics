<template>
  <div class="home-atlas-card-content" :data-chart-id="id">
    <div v-if="id === 'D1' || id === 'D2'" class="atlas-card-header">
      <div><h3>{{ titles[id] }} <span class="atlas-info" :title="scopeNote">i</span></h3><p class="muted">{{ subtitles[id] }}</p></div>
      <div v-if="id === 'D1'" class="atlas-toggle" role="tablist" aria-label="Coverage display mode">
        <button :class="{ active: coverageMode === 'pct' }" type="button" @click="coverageMode = 'pct'">% Coverage</button>
        <button :class="{ active: coverageMode === 'count' }" type="button" @click="coverageMode = 'count'">Record Count</button>
      </div>
      <div v-else class="atlas-toggle" role="tablist" aria-label="Genome distribution display mode">
        <button :class="{ active: genomeMode === 'box' }" type="button" @click="genomeMode = 'box'">Box Plot</button>
        <button :class="{ active: genomeMode === 'violin' }" type="button" @click="genomeMode = 'violin'">Violin Plot</button>
      </div>
    </div>
    <h3 v-else>{{ titles[id] }}</h3>
    <div class="atlas-current-plot">
      <ModuleState v-if="!card || card.status === 'error'" state="error" message="Chart data unavailable." :retry="retry" />
      <ModuleState v-else-if="card.status === 'empty' || !card.n_source" state="missing" :message="emptyMessage" />
      <div v-else-if="id === 'D1'" class="matrix-viewport">
        <div class="record-matrix" role="grid" :aria-label="titles[id]">
          <strong class="matrix-header">Platform group</strong><strong v-for="m in omics" :key="m" class="matrix-header">{{ label(m) }}</strong>
          <template v-for="row in card.data.rows" :key="row.group">
            <div class="matrix-group"><i :style="{ background: groupColors[row.group] }"></i><span>{{ row.group }}<small>n = {{ formatRaw(row.species_count) }}</small></span></div>
            <button v-for="m in omics" :key="row.group + m" class="matrix-cell" :style="cellStyle(row.layers[m])"
              :aria-label="row.group + ' ' + m + ': ' + cellText(row.layers[m])" :title="row.group + ' · ' + m + '\n' + cellText(row.layers[m])"
              @click="emit('coverage-cell-click', { domain: row.group, omics: m, allThree: false })">{{ cellText(row.layers[m]) }}</button>
          </template>
        </div>
        <div class="matrix-legend"><span>{{ coverageMode === 'count' ? 'Registered Core records · logarithmic color' : 'Ready Core species / all species in group' }}</span><i></i></div>
      </div>
      <HomeAtlasPlot v-else :card="card" :meta="meta" :mode="genomeMode" :selected-pattern="selectedPattern" :show-exports="id === 'D2'"
        :min-width="id === 'D5' ? Math.max(560, card.data.cohort.n_context_matched * 23 + 70) : id === 'D2' ? 500 : 0" @chart-click="openSpecies" />
    </div>
    <p class="atlas-current-note" :title="scopeNote">{{ note }}</p>
  </div>
</template>
<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import ModuleState from './ModuleState.vue'
import HomeAtlasPlot from './HomeAtlasPlot.vue'
import { contrastText, formatRaw, groupColors, omics, omicsNames } from '../utils/homeAtlasCharts'
const props = defineProps({ card: Object, id: String, meta: Object, retry: Function, coverageMode: {type:String,default:'count'}, genomeMode: {type:String,default:'violin'} })
const emit = defineEmits(['coverage-cell-click','update:coverageMode','update:genomeMode'])
const router = useRouter(), selectedPattern = ref('')
const coverageMode = computed({get:()=>props.coverageMode,set:value=>emit('update:coverageMode',value)})
const genomeMode = computed({get:()=>props.genomeMode,set:value=>emit('update:genomeMode',value)})
const titles = { D1:'Core Records Across Groups and Omics', D2:'Genome Size Distribution by Group',
  D3:'Core and Full Layer Availability', D4:'Completeness Evidence and Missingness', D5:'Whole-Core Diagnostics: Named Cohort' }
const subtitles = { D1:'Exact Core record counts; switch to ready-species coverage.', D2:'All registry-reported sizes; density, points, median and IQR.' }
const scopeNote = computed(() => 'Atlas omics-presence conditions control the list only. Applied: ' + JSON.stringify(props.meta?.applied_filters || {}) + '; ignored for context: ' + JSON.stringify(props.meta?.ignored_for_context || {}))
const emptyMessage = computed(() => props.id === 'D5' ? 'The named 24-species cohort has no members in this context.' : 'No registered data matches this context.')
const note = computed(() => {
  const c = props.card
  if (!c) return ''
  if (props.id === 'D5') return c.data.cohort.n_context_matched + '/' + c.data.cohort.total_named_species + ' named species · entire original numeric Core · ' + c.n_valid + '/' + c.n_source + ' tables ready'
  if (props.id === 'D2') return 'All ' + formatRaw(c.n_valid) + ' positive Mb values; ' + c.n_excluded + ' excluded. Registry values; no assembly-quality claim.'
  if (props.id === 'D3') return selectedPattern.value ? 'Full pattern ' + selectedPattern.value + ' highlighted locally; no registry filter applied.' : 'All eight Full-path patterns; path registration does not establish file quality.'
  if (props.id === 'D4') return 'Cached evidence, not a new whole-registry cell scan. Omics-presence conditions control the list only.'
  return formatRaw(c.n_source) + ' context species · omics-presence conditions control the list only.'
})
const label = m => omicsNames[omics.indexOf(m)]
const cellText = c => coverageMode.value === 'count' ? formatRaw(c.record_count_core) : c.coverage_pct === null ? 'N/A' : formatRaw(c.coverage_pct) + '%'
function cellStyle(c) {
  const max = Math.max(1, ...(props.card?.data.rows || []).flatMap(r => omics.map(m => r.layers[m].record_count_core)))
  const min = Math.min(max, ...(props.card?.data.rows || []).flatMap(r => omics.map(m => r.layers[m].record_count_core)).filter(n => n > 0))
  const n = coverageMode.value === 'count' ? c.record_count_core : c.coverage_pct
  const t = n === null || n === 0 ? 0 : coverageMode.value === 'count' ? max === min ? .5 : (Math.log10(n) - Math.log10(min)) / (Math.log10(max) - Math.log10(min)) : n / 100
  const a = [240,247,252], b = [22,57,88], rgb = a.map((x,i) => Math.round(x + (b[i] - x) * t))
  return { background:'rgb(' + rgb.join(',') + ')', color: contrastText(rgb) }
}
function openSpecies(p) {
  const row = p?.data?.raw
  if (props.id === 'D3' && row?.pattern) { selectedPattern.value = selectedPattern.value === row.pattern ? '' : row.pattern; return }
  if (row?.species_id) router.push('/species/' + encodeURIComponent(row.species_id))
}
</script>
<style scoped>
.home-atlas-card-content { position:absolute;inset:0;display:flex;flex-direction:column;min-width:0;min-height:0; }
.atlas-card-header { flex-shrink:0; }
.atlas-current-plot { flex:1;min-height:160px;min-width:0;overflow:hidden; }
.atlas-current-note { flex-shrink:0;margin:8px 0 0;color:#536E88;font-size:11px;line-height:1.45; }
.matrix-viewport { height:100%;overflow:auto; }
.record-matrix { display:grid;grid-template-columns:minmax(130px,1.2fr) repeat(3,minmax(96px,1fr));min-width:460px;align-content:stretch;grid-auto-rows:minmax(42px,1fr);height:calc(100% - 48px);gap:2px;border-bottom:1px solid #DCE7F1; }
.matrix-header { display:grid;place-items:center;color:#173B64;font-size:11px; }
.matrix-group { display:flex;gap:7px;align-items:center;font-size:12px;color:#173B64; }
.matrix-group small { display:block;color:#536E88;font-size:10px; }
.matrix-group i { width:7px;height:7px;border-radius:50%;flex-shrink:0; }
.matrix-cell { border:0;border-radius:3px;font:600 12px Inter,Arial;cursor:pointer;min-height:36px; }
.matrix-cell:focus-visible { outline:3px solid #2468C7;outline-offset:-3px; }
.matrix-legend { display:flex;align-items:center;gap:12px;font-size:10px;color:#536E88;margin-top:10px; }
.matrix-legend i { width:95px;height:7px;background:linear-gradient(to right,#F0F7FC,#5691BE,#163958);border-radius:4px; }
</style>
