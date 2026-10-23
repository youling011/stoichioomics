<template>
  <section class="panel" data-testid="proteome-candidates">
    <div class="section-header"><div><h3>Complete candidate evidence table</h3><p class="muted">Scores are ranked within each module. Incomplete evidence has a separate table.</p></div></div>
    <div class="proteome-controls"><label>Module<select v-model="module" class="input"><option v-for="m in modules" :key="m">{{ m }}</option></select></label><label>Evidence<select v-model="evidence" class="input"><option value="complete">Complete components</option><option value="partial">Partial evidence</option></select></label><span>{{ result?.total?.toLocaleString()||0 }} records in this ranking</span></div>
    <p v-if="error">{{ error }}</p><p v-if="loading" class="muted">Loading ranked records…</p>
    <div class="table-wrap"><table><thead><tr><th>Rank</th><th>Protein ID</th><th>Gene ID</th><th>Native score</th><th>Valid components</th><th>Source</th></tr></thead><tbody><tr v-for="row in result?.rows||[]" :key="row.protein_id"><td>{{ row.rank }}</td><td><button class="proteome-entity-link" @click="open(row)">{{ row.protein_id }}</button></td><td>{{ row.gene_id||'—' }}</td><td>{{ number(row.score,6) }}</td><td>{{ row.component_n }}</td><td>{{ row.source_db }}</td></tr><tr v-if="!loading&&!result?.rows?.length"><td colspan="6">No {{ evidence }} candidate evidence for this module.</td></tr></tbody></table></div>
    <div class="proteome-controls"><button class="btn subtle" :disabled="page===1||loading" @click="page--">Previous records</button><span>Page {{ page }} / {{ Math.max(1,Math.ceil((result?.total||0)/25)) }}</span><button class="btn subtle" :disabled="page*25>=(result?.total||0)||loading" @click="page++">Next records</button></div>
  </section>
</template>
<script setup>
import {ref,watch,onBeforeUnmount} from 'vue'
import {getProteomeCandidates} from '../../api/proteomeVisuals'
import {number} from '../../utils/proteomeFormat'
const props=defineProps({speciesId:String,scope:String,manifest:Object});const modules=['Resource','S-rich','AA anomaly','Hydropathy','SS upper/L','Redox'];const module=ref('Resource'),evidence=ref('complete'),page=ref(1),result=ref(null),loading=ref(false),error=ref('');let controller,seq=0
watch([module,evidence],()=>{page.value=1})
watch(()=>[props.speciesId,props.scope,props.manifest.artifact_version,module.value,evidence.value,page.value],async()=>{
  const current=++seq;controller?.abort();controller=new AbortController();result.value=null;loading.value=true;error.value=''
  try{const r=await getProteomeCandidates(props.speciesId,{scope:props.scope,artifact_version:props.manifest.artifact_version,module:module.value,evidence:evidence.value,page:page.value,page_size:25},{signal:controller.signal});if(current===seq)result.value=r}catch(e){if(current===seq&&!controller.signal.aborted)error.value=e?.response?.data?.error?.message||e.message}finally{if(current===seq)loading.value=false}
},{immediate:true})
onBeforeUnmount(()=>{seq++;controller?.abort()})
function open(row){window.dispatchEvent(new CustomEvent('stoich-entity-chart-click',{detail:{...row,species_id:props.speciesId,entity_id:row.protein_id,report_entity_key:row.protein_id}}))}
</script>
