<template>
  <div ref="viewport" class="home-atlas-plot" :data-chart-id="card?.chart_id">
    <div class="home-atlas-canvas" :style="{ minWidth: minWidth + 'px' }">
      <EChart :option="option" :height="chartHeight" :auto-loading="false" :show-exports="showExports"
        :export-name="'home_atlas_' + card?.chart_id" @chart-click="emit('chart-click', $event)" />
    </div>
  </div>
</template>
<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import EChart from './EChart.vue'
import * as charts from '../utils/homeAtlasCharts'
const props = defineProps({ card: Object, meta: Object, mode: String, selectedPattern: String, showExports: { type: Boolean, default: false }, minWidth: { type: Number, default: 0 } })
const emit = defineEmits(['chart-click'])
const viewport = ref(null), dimensions = ref({ width: 450, height: 320 })
let observer
const chartHeight = computed(() => Math.max(160, dimensions.value.height - (props.showExports ? 38 : 0)))
const factories = { H1: charts.buildH1SpeciesOption, H2: charts.buildH2RecordFlowOption, H3: charts.buildH3FieldFamiliesOption,
  D1: charts.buildD1CoverageOption, D2: charts.buildD2GenomeDistributionOption, D3: charts.buildD3MembershipOption,
  D4: charts.buildD4MissingnessOption, D5: charts.buildD5CoreDiagnosticsOption }
const option = computed(() => factories[props.card?.chart_id]?.({ ...props.card, applied_filters: props.meta?.applied_filters, ignored_for_context: props.meta?.ignored_for_context }, { mode: props.mode, selectedPattern: props.selectedPattern, ...dimensions.value }) || {})
onMounted(() => {
  observer = new ResizeObserver(([entry]) => { const r = entry.contentRect; if (r.width > 0 && r.height > 0 && (Math.abs(r.width - dimensions.value.width) > .2 || Math.abs(r.height - dimensions.value.height) > .2)) dimensions.value = { width: r.width, height: r.height } })
  observer.observe(viewport.value)
})
onBeforeUnmount(() => observer?.disconnect())
</script>
<style scoped>
.home-atlas-plot { width:100%;height:100%;min-height:0;min-width:0;overflow-x:auto;overflow-y:hidden; }
.home-atlas-canvas { width:100%;height:100%; }
:deep(.chart-host) { min-height:0; }
:deep(.echart-shell) { height:100%;min-height:0; }
:deep(.chart-export-row) { position:static;justify-content:flex-end;margin-bottom:8px;display:flex;gap:6px; }
</style>
