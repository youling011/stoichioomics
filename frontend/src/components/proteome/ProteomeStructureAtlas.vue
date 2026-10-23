<template>
  <div class="proteome-structure-control" data-testid="proteome-structure-window">
    <div class="proteome-controls"><label>First sorted rank<input v-model.number="start" type="number" class="input" min="1" :max="manifest.n_source" /></label><label>Window size<select v-model.number="count" class="input"><option :value="100">100 records</option><option :value="250">250 records</option><option :value="1000">1,000 records</option></select></label><button class="btn" :disabled="loading" @click="load">Open precise window</button><button class="btn subtle" :disabled="start<=1||loading" @click="shift(-1)">Previous window</button><button class="btn subtle" :disabled="start+count>manifest.n_source||loading" @click="shift(1)">Next window</button><button v-if="detail" class="btn subtle" @click="detail=null">Return to overview</button></div>
    <p class="muted">Every sorted rank is accessible, including records beyond 5,000. {{ manifest.n_source.toLocaleString() }} records in total.</p>
    <button v-if="detail" class="btn subtle" @click="download">Download this exact window (JSON)</button>
    <ProteomeFigure v-if="detail||loading||error" :figure="figure" chart-id="D07" :species-id="speciesId" :scope="scope" :loading="loading" :error="error" title="Precise structure proxy window" />
  </div>
</template>
<script setup>
import {ref,computed,watch,onBeforeUnmount} from 'vue'
import {getProteomeStructure} from '../../api/proteomeVisuals'
import ProteomeFigure from './ProteomeFigure.vue'
const props=defineProps({speciesId:String,scope:String,manifest:Object,overview:Object,requestedStart:Number});const start=ref(1),count=ref(100),detail=ref(null),error=ref(''),loading=ref(false);let controller,seq=0
const figure=computed(()=>detail.value?{...props.overview,data:{...detail.value,kind:'structure_atlas'}}:null)
watch(()=>[props.speciesId,props.scope,props.manifest.artifact_version],()=>{seq++;controller?.abort();detail.value=null;loading.value=false;error.value='';start.value=1})
watch(()=>props.requestedStart,value=>{if(value!==undefined&&value!==null){start.value=value+1;load()}})
async function load(){const current=++seq;controller?.abort();controller=new AbortController();loading.value=true;error.value='';start.value=Math.max(1,Math.min(props.manifest.n_source,Number(start.value)||1));try{const r=await getProteomeStructure(props.speciesId,{scope:props.scope,artifact_version:props.manifest.artifact_version,resolution:'window',rank_start:start.value-1,rank_count:count.value},{signal:controller.signal});if(current===seq)detail.value=r}catch(e){if(current===seq&&!controller.signal.aborted)error.value=e.message}finally{if(current===seq)loading.value=false}}
function shift(direction){start.value=Math.max(1,Math.min(props.manifest.n_source,start.value+direction*count.value));load()}
function download(){const a=document.createElement('a'),blob=new Blob([JSON.stringify(detail.value)],{type:'application/json'});a.href=URL.createObjectURL(blob);a.download=`${props.speciesId}_${props.scope}_structure_r${detail.value.rank_start+1}-${detail.value.rank_start+detail.value.rows.length}_${props.manifest.artifact_version}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),0)}
onBeforeUnmount(()=>{seq++;controller?.abort()})
</script>
