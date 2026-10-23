<template>
 <div class="stack-lg">
  <p v-if="error" class="annotation" role="alert">{{ error }}</p>
  <template v-if="mode==='differences'">
   <label v-if="pairRows.length">Difference unit / family<select v-model="unit" class="input"><option v-for="u in units" :key="u">{{ u }}</option></select></label>
   <div v-if="shownPairs.length" class="chart-panel"><h4>A and B values · {{ unit }}</h4><EChart :option="pairOption" :height="360" :auto-loading="false" /><p class="annotation">Up to 20 fields in this unit/family, ordered by absolute A−B difference. Complete table below retains all fields.</p></div>
   <div v-if="groupRows.some(r=>r.cliffs_delta!=null)" class="chart-panel"><h4>Group effects · Cliff A−B and 95% bootstrap intervals</h4><EChart :option="groupOption" :height="380" :auto-loading="false" /><p class="annotation">Up to 20 estimable effects by absolute effect size. See the full table for n, p, q and m_tested.</p></div>
  </template>
  <template v-if="mode==='composition'"><h4>Complete mean compositions</h4><label>Composition group<select v-model="group" class="input"><option v-for="g in groups" :key="g">{{ g }}</option></select></label><EChart v-if="compositionRows.length" :option="compositionOption" :height="460" :auto-loading="false" /><p class="annotation">Equal-weight mean of complete, valid, closed entity compositions. Each species/group reports its own applicable and valid counts in the complete table. Individual-column medians are not used to construct these vectors.</p><CompareCoreTable :run-id="result.run_id" kind="composition_profiles" label="Composition values, closure and valid denominators" /></template>
  <template v-if="mode==='cross'"><div class="grid grid-2"><div v-for="(layer,o) in result.cross_omics_layers" :key="o" class="chart-panel"><h4>{{ o }} · {{ layer.n_blocks || 0 }} blocks</h4><EChart v-if="layer.pairs.length" :option="layerOption(layer,o)" :height="460" :auto-loading="false" /><p v-else class="annotation">Layer distance unavailable: no complete eligible blocks.</p></div></div></template>
 </div>
</template>
<script setup>
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import EChart from './EChart.vue'
import CompareCoreTable from './CompareCoreTable.vue'
import { compareTable } from '../api/compareCore'
import { dumbbellOption, forestOption, matrixHeatmapOption } from '../utils/charts'
const props=defineProps({result:Object,mode:String})
const pairRows=ref([]),groupRows=ref([]),compositionRows=ref([]),unit=ref(''),group=ref(''),error=ref('');let sequence=0
async function all(kind){let rows=[],page=1;while(true){const d=await compareTable(props.result.run_id,{kind,page,page_size:200});rows.push(...d.items);if(!d.has_next)return rows;page++}}
watch(()=>[props.result.run_id,props.mode],async()=>{const seq=++sequence;try{if(props.mode==='differences'){const [a,b]=await Promise.all([all('differences'),all('group_comparison')]);if(seq!==sequence)return;pairRows.value=a;groupRows.value=b;unit.value=units.value[0]||''}if(props.mode==='composition'){const data=await all('composition_profiles');if(seq!==sequence)return;compositionRows.value=data;group.value=groups.value[0]||''}}catch(e){if(seq===sequence)error.value=e.response?.data?.error?.message||e.message}},{immediate:true})
onBeforeUnmount(()=>sequence++)
const units=computed(()=>[...new Set(pairRows.value.map(r=>`${r.unit} / ${r.family}`))].sort())
const shownPairs=computed(()=>pairRows.value.filter(r=>`${r.unit} / ${r.family}`===unit.value && r.value_a!=null && r.value_b!=null).sort((a,b)=>b.abs_delta-a.abs_delta || a.field_key.localeCompare(b.field_key)).slice(0,20))
function mark(option,rows,kind){option.__dataRows=rows;option.__exportName=`compare_${kind}`;option.__semantic={...option.__semantic,minPoints:1,run_id:props.result.run_id,scope:'core',displayedCount:rows.length,totalCount:kind==='differences'?pairRows.value.length:kind==='group_effects'?groupRows.value.length:rows.length,samplingPolicy:'display_subset_only_full_tables_available'};return option}
const pairOption=computed(()=>mark(dumbbellOption(shownPairs.value,'field_key','value_b','value_a',{startLabel:'B',endLabel:'A',xName:unit.value,method:'Values in one canonical unit and feature family; A minus B'}),shownPairs.value,'differences'))
const groupOption=computed(()=>{const rows=groupRows.value.filter(r=>r.cliffs_delta!=null).sort((a,b)=>Math.abs(b.cliffs_delta)-Math.abs(a.cliffs_delta)||a.field_key.localeCompare(b.field_key)).slice(0,20);return mark(forestOption(rows,'field_key','cliffs_delta','ci_low','ci_high',{xName:'Cliff A−B',method:'2,000 deterministic species bootstraps; 95% percentile interval'}),rows,'group_effects')})
const groups=computed(()=>[...new Set(compositionRows.value.map(r=>r.group))].sort())
const compositionOption=computed(()=>{const rows=compositionRows.value.filter(r=>r.group===group.value),ids=[...new Set(rows.map(r=>r.species_id))],keys=[...new Set(rows.map(r=>r.field_key))],values=rows.map(r=>[keys.indexOf(r.field_key),ids.indexOf(r.species_id),r.mean_composition]);const o=matrixHeatmapOption(keys,ids,values,{title:group.value,min:0,max:1});if(keys.length>18)o.dataZoom=[{type:'slider',start:0,end:1800/keys.length,xAxisIndex:0}];return mark(o,rows,'composition')})
function layerOption(layer,omics){const ids=props.result.analysis_species,index=new Map(ids.map((s,i)=>[s,i])),values=ids.map((s,i)=>[i,i,0]);for(const p of layer.pairs){const i=index.get(p.source),j=index.get(p.target);values.push([i,j,p.distance],[j,i,p.distance])}const max=Math.max(...layer.pairs.map(p=>p.distance),1e-9);return mark(matrixHeatmapOption(ids,ids,values,{title:omics,min:0,max,distance:true}),values.map(([i,j,d])=>({source:ids[i],target:ids[j],distance:d,omics})),'cross_omics')}
</script>
