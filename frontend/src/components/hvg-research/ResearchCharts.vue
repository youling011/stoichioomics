<template>
  <div class="grid grid-2 hvg-topic-plots">
    <div v-for="kind in kinds" :key="kind" class="card hvg-topic-plot" :class="{'is-wide':isWide(kind)}" :data-visual="kind">
      <div class="section-header compact"><div><h3>{{visualTitles[kind] || kind}}</h3><p class="muted" v-if="payloads[kind]">{{metadata(payloads[kind])}}</p></div></div>
      <div v-if="canExpand(kind)" class="hvg-plot-toolbar"><span class="muted">{{expanded[kind] ? 'All plotted rows expanded' : 'Scroll the chart to explore all plotted rows'}}</span><button class="btn secondary" :aria-pressed="!!expanded[kind]" @click="expanded[kind]=!expanded[kind]">{{expanded[kind] ? 'Compact view' : 'Expand all rows'}}</button></div>
      <p v-if="busy[kind]" role="status">Loading chart data…</p>
      <p v-else-if="errors[kind]" role="alert">{{errors[kind]}} <button class="btn secondary" @click="reload">Retry charts</button></p>
      <EChart v-else-if="options[kind]" :option="options[kind]" :data-rows="payloads[kind]?.rows || []" :auto-loading="false" :height="height(kind)" :export-name="kind" :caption="caption(kind)" @chart-click="inspect(kind,$event)" />
      <div v-else class="empty-state"><div><h4>No estimable chart data</h4><p class="muted">{{payloads[kind]?.reason || 'No saved result is available yet.'}}</p><p v-if="payloads[kind]?.status_counts">{{formatValue(payloads[kind].status_counts)}}</p></div></div>
      <button v-if="payloads[kind]?.source_table" class="btn secondary" @click="$emit('table',payloads[kind].source_table)">View supporting table</button>
    </div>
  </div>
</template>
<script setup>
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import EChart from '../EChart.vue'
import {originalCaption} from './originalCharts'
import {researchOption,visualTitles,formatValue,viewportRows} from './researchCharts'
const props=defineProps({state:{type:Object,required:true},kinds:{type:Array,default:()=>[]}}),emit=defineEmits(['table','inspect'])
const expanded=ref({})
const payloads=ref({}),errors=ref({}),busy=ref({}),options=computed(()=>Object.fromEntries(Object.entries(payloads.value).map(([k,p])=>[k,researchOption(p,props.state.compact,!!expanded.value[k])])))
let generation=0,controller
async function reload(){
  const id=++generation;controller?.abort();controller=new AbortController();payloads.value={};props.state.sharedVisuals={};expanded.value={};errors.value={};busy.value=Object.fromEntries(props.kinds.map(k=>[k,true]))
  let cursor=0;const kinds=[...props.kinds],signal=controller.signal
  async function worker(){while(cursor<kinds.length){const kind=kinds[cursor++];try{const p=await props.state.get('visuals/'+kind,{},true,signal);if(id===generation){payloads.value={...payloads.value,[kind]:p};props.state.sharedVisuals={...props.state.sharedVisuals,[kind]:p}}}catch(e){if(id===generation&&e.code!=='ERR_CANCELED')errors.value={...errors.value,[kind]:e.response?.data?.error?.message||e.message}}finally{if(id===generation)busy.value={...busy.value,[kind]:false}}}}
  await Promise.all(Array.from({length:Math.min(3,kinds.length)},worker))
}
const signature=computed(()=>JSON.stringify([props.kinds,props.state.run,props.state.context,props.state.feature,props.state.term,props.state.source,props.state.direction,props.state.qmax,props.state.scope,props.state.version]))
watch(signature,reload,{immediate:true})
onBeforeUnmount(()=>{generation++;controller?.abort()})
function isWide(kind){const p=payloads.value[kind];return ['forest','bubble','heatmap','context_heatmap','original_family_heatmap','original_enrichment','original_status'].includes(p?.chart_type)||(['bar'].includes(p?.chart_type)&&(p.rows?.length||0)>12)}
function canExpand(kind){const p=payloads.value[kind];return ['forest','bubble','bar'].includes(p?.chart_type)&&(p.rows?.length||0)>viewportRows}
function height(kind){const p=payloads.value[kind];if(p?.chart_type==='original_family_heatmap')return Math.max(460,Math.min(1000,new Set((p.rows||[]).map(r=>r.family)).size*28+150));if(p?.chart_type==='original_status')return Math.max(420,Math.min(1100,(p.rows?.length||0)*26+100));if(p?.chart_type==='original_enrichment')return Math.max(420,Math.min(1100,(p.rows?.length||0)*28+120));if(['forest','bubble','bar'].includes(p?.chart_type)){const n=expanded.value[kind]?p.rows?.length:Math.min(viewportRows,p.rows?.length||0);return Math.min(1800,Math.max(360,n*29+118))}return ['heatmap','context_heatmap'].includes(p?.chart_type)?(props.state.compact?580:620):420}
function metadata(p){return `${Number(p.total||0).toLocaleString('en-US')} matching · ${p.displayed??p.rows?.length??0} plotted${p.estimable!==undefined?' · '+p.estimable+' estimable':''}${p.source?' · '+p.source:''}${p.scope?' · '+p.scope.replace(/_/g,' '):''}`}
function caption(kind){
 const p=payloads.value[kind];if(kind.startsWith('original_'))return originalCaption(kind,p);const type=p?.chart_type,tested=!!p?.rows?.some(r=>r.q_global!==undefined)
 const color=type==='heatmap'||type==='context_heatmap'?'Blue: positive effect; brown: negative effect. Hover for global BH q and full identifiers.':type==='volcano'?'Blue: strong raw evidence (global BH q, declared effect-size and confidence-interval criteria); grey: other estimates. Dashed line: q = 0.05.':tested?'Blue: global BH q < 0.05; grey: other estimates.':kind==='hvg_scatter'||kind==='hvg_histogram'?'Blue: HVG; grey: non-HVG.':kind==='candidate_priority'?'Teal: annotated; gold: unannotated.':'Summary of saved records in the selected context.'
 return [p?.feature_key,color,type==='forest'?(p.value==='beta'?'Points and confidence intervals on the log odds ratio scale; covariate-adjusted models are shown separately.':"Points and saved confidence intervals; positive Cliff’s delta indicates higher values in HVGs."):'',type==='bubble'?'Bubble size represents overlapping genes (k).':'',p?.displayed<p?.estimable&&kind!=='feature_volcano'?'A selected preview is shown; full results remain in the table and downloads.':'',kind==='distribution'?'Box: 25th–75th percentiles; whiskers: 5th–95th percentiles. Both groups use one scale.':'',kind==='gsea'?'Select a bar or GSEA curve in the table to inspect the saved-rank running ES.':'',kind==='feature_volcano'?'Zero q values use a plotting floor of 1e−300; original data are unchanged.':'',kind==='core_missingness'?'Median recorded feature-missing fraction per omics; inapplicable fields are not replaced with zero.':'',kind==='baseline_stability'?'Descriptive technical resample frequency at per-run BH q < 0.05; not a new global significance test.':''].filter(Boolean).join(' ')
}
function inspect(kind,event){if(event?.seriesType==='line'&&!event?.data?.raw)return;const raw=event?.data?.raw||payloads.value[kind]?.rows?.[event?.dataIndex];if(raw)emit('inspect',{kind,row:raw})}
</script>
<style scoped>
.hvg-topic-plots{align-items:stretch;gap:20px}.hvg-topic-plot{min-width:0;display:flex;flex-direction:column}.hvg-topic-plot.is-wide{grid-column:1/-1}.hvg-topic-plot .section-header{margin-bottom:8px}.hvg-topic-plot h3{font-size:1.1rem;margin:0 0 5px;line-height:1.4}.hvg-topic-plot p{overflow-wrap:anywhere}.hvg-topic-plot .section-header p{font-size:.84rem;margin:0;color:var(--text-soft)}.hvg-topic-plot>.btn{align-self:flex-start;margin-top:14px}.hvg-topic-plot .empty-state{min-height:220px}.hvg-plot-toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;border-bottom:1px solid var(--line-soft);padding:4px 0 10px;font-size:.84rem}.hvg-plot-toolbar .btn{font-size:.82rem;padding:6px 12px;white-space:nowrap}.hvg-topic-plot :deep(.chart-export-row){margin:10px 0 4px;gap:6px}.hvg-topic-plot :deep(.chart-caption){border-top:1px solid var(--line-soft);padding-top:10px;margin-top:4px;line-height:1.6;color:var(--text-soft)}.hvg-topic-plot :deep(.chart-caption p){margin:0;font-size:.85rem}.hvg-topic-plot :deep(.echart-shell){min-width:0}.hvg-topic-plot :deep(.chart-host){width:100%;min-width:0}
@media(max-width:1100px){.hvg-topic-plots{grid-template-columns:1fr}}@media(max-width:760px){.hvg-topic-plots{gap:16px}.hvg-topic-plot h3{font-size:1.05rem}.hvg-plot-toolbar{align-items:flex-start;flex-wrap:wrap}.hvg-topic-plot :deep(.chart-export-btn),.hvg-plot-toolbar .btn{min-height:44px}.hvg-topic-plot :deep(.chart-caption p){font-size:14px}}
</style>
