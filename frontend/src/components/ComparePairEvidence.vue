<template>
 <section class="stack">
  <div class="section-header"><h4>Saved pair evidence · {{ speciesIds.join(' / ') }}</h4><button class="btn subtle" @click="$emit('close')">Close pair</button></div>
  <p class="annotation">Raw canonical summaries from this saved run; direction A minus B. Full task thresholds, scope and reference remain frozen. Select the two-species task for a separate complete comparison package.</p>
  <p v-if="error" role="alert" class="annotation">{{ error }}</p>
  <div class="table-wrap"><table class="compact-table"><thead><tr><th>Core field</th><th>A</th><th>B</th><th>A−B</th><th>Unit</th><th>Valid rows A / B</th><th>Status A / B</th></tr></thead><tbody><tr v-for="r in visible" :key="r.field_key"><td>{{ r.field_key }}</td><td>{{ format(r.a) }}</td><td>{{ format(r.b) }}</td><td>{{ format(r.delta) }}</td><td>{{ r.unit }}</td><td>{{ r.n_a }} / {{ r.n_b }}</td><td>{{ r.status_a }} / {{ r.status_b }}</td></tr></tbody></table></div>
  <div class="compare-pair-tools"><button class="btn subtle" :disabled="page<=1" @click="page--">Previous</button><span>{{ rows.length }} numeric / composition / binary fields · page {{ page }}</span><button class="btn subtle" :disabled="page*25>=rows.length" @click="page++">Next</button></div>
 </section>
</template>
<script setup>
import { ref,watch,computed,onBeforeUnmount } from 'vue'
import { compareTable } from '../api/compareCore'
const props=defineProps({runId:String,speciesIds:Array});defineEmits(['close'])
const rows=ref([]),page=ref(1),error=ref('');let sequence=0
async function loadSpecies(sid){const rows=[];let page=1;while(true){const r=await compareTable(props.runId,{kind:'profiles',query:sid,page,page_size:200});rows.push(...r.items.filter(x=>x.species_id===sid));if(!r.has_next)return rows;page++}}
watch(()=>[props.runId,...props.speciesIds],async()=>{const seq=++sequence;rows.value=[];page.value=1;error.value='';try{const [a,b]=await Promise.all(props.speciesIds.map(loadSpecies));if(seq!==sequence)return;const right=new Map(b.map(r=>[r.field_key,r]));rows.value=a.filter(r=>['numeric','composition','binary_summary'].includes(r.compare_role)).map(r=>{const s=right.get(r.field_key);const x=r.value_canonical??null,y=s?.value_canonical??null;return {field_key:r.field_key,a:x,b:y,delta:x!=null&&y!=null?x-y:null,unit:r.unit_canonical,n_a:r.n_valid,n_b:s?.n_valid,status_a:r.status,status_b:s?.status||'source_unavailable'}})}catch(e){if(seq===sequence)error.value=e.response?.data?.error?.message||e.message}},{immediate:true})
onBeforeUnmount(()=>sequence++)
const visible=computed(()=>rows.value.slice((page.value-1)*25,page.value*25))
const format=value=>value==null?'—':Number(value.toPrecision(6))
</script>
<style scoped>.table-wrap{overflow:auto}.compact-table{min-width:800px}.compare-pair-tools{display:flex;align-items:center;flex-wrap:wrap;gap:12px}</style>
