<template>
  <div class="card hvg-optional-model">
    <div class="section-header compact"><div><h3>Optional prediction model · global</h3><p class="muted">Expected vs observed values, residuals and diagnostics come from a separate prediction branch.</p></div></div>
    <p v-if="state.context!=='global'" class="muted">This model applies to the global context only. Select global to inspect its evidence.</p>
    <p v-else-if="!['complete','completed','ready'].includes(state.summary.model_status)" class="muted">Model status:{{state.summary.model_status || 'Not run'}}.{{state.summary.model_status==='skipped'?'Input or configuration requirements for the prediction branch were not met. Feature and function analyses remain available.':'Research statistics remain available without a model result.'}}</p>
    <button v-if="state.context==='global'" class="btn secondary" @click="load" :disabled="loading">{{loading?'Loading model…':'Inspect model and status'}}</button>
    <p v-if="error" role="alert">{{error}}</p>
    <template v-if="payload">
      <p v-if="merged.length" class="muted">Identical saved views are combined with the chart above: {{merged.map(k=>originalTitles[k]).join('; ')}}. Data, units and interactions were checked per chart.</p>
      <div class="grid grid-2" v-if="previewCharts.length">
        <div v-for="chart in previewCharts" :key="chart.kind" class="hvg-model-plot" :data-model-preview="chart.kind"><h4>Saved model preview · {{originalTitles[chart.kind]}}</h4><p class="muted">This saved preview differs from the complete original view in its rows or evidence fields and is retained separately.</p><EChart :option="chart.option" :data-rows="chart.rows" :auto-loading="false" :height="440" :export-name="'saved_preview_'+chart.kind" @chart-click="inspect(chart.kind,$event)" /></div>
      </div>
      <details><summary>Model parameters, status and saved evidence</summary><button class="btn secondary" @click="download">Download model evidence (JSON)</button><pre>{{JSON.stringify(payload,null,2)}}</pre></details>
    </template>
  </div>
</template>
<script setup>
import {computed,ref,watch,onBeforeUnmount} from 'vue'
import EChart from '../EChart.vue'
import {researchOption} from './researchCharts'
import {originalTitles} from './originalCharts'
import {modelPreviewPackets,equivalentPackets} from './modelPreviewPackets'
const props=defineProps({state:{type:Object,required:true},section:String}),payload=ref(null),error=ref(''),loading=ref(false)
const emit=defineEmits(['inspect'])
let generation=0,controller
watch(()=>[props.state.run,props.state.context],()=>{generation++;controller?.abort();payload.value=null;error.value='';loading.value=false})
onBeforeUnmount(()=>{generation++;controller?.abort()})
async function load(){const id=++generation;controller?.abort();controller=new AbortController();loading.value=true;error.value='';try{const p=await props.state.get('optional-model',{},false,controller.signal);if(id===generation)payload.value=p}catch(e){if(id===generation&&e.code!=='ERR_CANCELED')error.value=e.message}finally{if(id===generation)loading.value=false}}
const wanted=computed(()=>props.section==='phase2'?['original_classes','original_expected_observed','original_residuals','original_model_associations']:['original_model_comparison','original_bootstrap'])
const packets=computed(()=>modelPreviewPackets(payload.value))
const merged=computed(()=>wanted.value.filter(k=>equivalentPackets(packets.value[k],props.state.sharedVisuals?.[k])))
const previewCharts=computed(()=>wanted.value.filter(k=>packets.value[k]&&!merged.value.includes(k)).map(k=>({...packets.value[k],option:researchOption(packets.value[k],props.state.compact)})))
function inspect(kind,event){const p=packets.value[kind],row=event.data?.raw||p?.rows?.[event.dataIndex];if(row&&event.seriesType!=='line')emit('inspect',{kind,row})}
function download(){const url=URL.createObjectURL(new Blob([JSON.stringify(payload.value,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='optional_model_'+props.state.run+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
</script>
<style scoped>
.hvg-model-plot{min-width:0;border-top:1px solid var(--line-soft);padding-top:16px;margin-top:16px}.hvg-model-plot h4{margin:0 0 8px;font-size:1rem}.hvg-optional-model .grid{align-items:start;gap:20px}.hvg-optional-model pre{max-height:400px;overflow:auto;font-size:12px;white-space:pre-wrap;overflow-wrap:anywhere}.hvg-optional-model details{margin-top:16px}.hvg-optional-model summary{cursor:pointer;font-weight:600}
@media(max-width:1100px){.hvg-optional-model .grid{grid-template-columns:1fr}}
</style>
