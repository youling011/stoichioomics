<template>
  <section class="proteome-cohort-section" data-testid="proteome-cohort">
    <div class="section-header"><div><h3>Species comparison</h3><p class="muted">Whole-{{ scope }} means · 11 shared descriptors · four equally weighted families · maximum 64 species</p></div><button v-if="response?.readiness==='ready'" class="btn subtle" @click="download">Download cohort evidence</button></div>
    <div class="proteome-controls"><label>Find any registered species<input v-model="search" class="input" placeholder="Species name or ID" @input="find" /></label><button class="btn subtle" @click="reset">Use representative cohort</button><button class="btn" :disabled="loading||!selected.length" @click="load(false)">Compare selected species</button><span>{{ selected.length }} / 64 selected</span></div>
    <ul v-if="matches.length" class="proteome-species-matches"><li v-for="s in matches" :key="s.species_id"><button class="btn subtle" :disabled="selected.includes(s.species_id)||selected.length>=64" @click="add(s)">{{ s.display_name }} <span class="muted">{{ s.species_id }}</span></button></li></ul>
    <div class="proteome-cohort-list"><button v-for="id in selected" :key="id" class="btn subtle" :title="id" @click="remove(id)">{{ names[id]||id }} <span aria-hidden="true">×</span><span class="sr-only">Remove from comparison</span></button></div>
    <p v-if="error" class="muted">{{ error }}</p><p v-if="response&&response.readiness!=='ready'" class="muted">Fingerprint results are not prepared for: {{ response.missing_species?.join(', ') }}.</p>
    <template v-if="response?.readiness==='ready'&&response.data?.status!=='unavailable'">
      <ProteomeFigure v-for="id in ['D11','D12','D16']" :key="id" :chart-id="id" :species-id="speciesId" :scope="scope" :figure="figure(id)" :option-override="option(id)" :loading="loading" @species="navigate" />
      <details class="panel"><summary>Observed feature dispersion in original units</summary><div class="table-wrap"><table><thead><tr><th>Descriptor</th><th>Minimum species mean</th><th>Maximum species mean</th><th>SD of species means</th><th>Species</th></tr></thead><tbody><tr v-for="r in response.data.raw_summary" :key="r.field"><td>{{ r.field }}</td><td>{{ number(r.min,6) }}</td><td>{{ number(r.max,6) }}</td><td>{{ number(r.sd,6) }}</td><td>{{ r.n_species }}</td></tr></tbody></table></div></details>
      <p class="muted">The three views share cohort {{ response.cohort_hash.slice(0,16) }}. Distances and clustering are descriptive, not a phylogenetic tree. Feature dispersion is not validated feature importance.</p>
    </template><p v-else-if="response?.data?.status==='unavailable'" class="muted">{{ response.data.reason }} {{ response.data.unavailable_species?.join(', ') }}</p>
  </section>
</template>
<script setup>
import {ref,watch,onBeforeUnmount} from 'vue'
import {useRouter} from 'vue-router'
import {getProteomeCohort,ensureProteomeVisuals,getProteomeRequest} from '../../api/proteomeVisuals'
import {cohortFigure} from '../../utils/proteomeCharts'
import {number} from '../../utils/proteomeFormat'
import ProteomeFigure from './ProteomeFigure.vue'
const props=defineProps({speciesId:String,scope:String});const router=useRouter(),selected=ref([]),names=ref({}),response=ref(null),search=ref(''),matches=ref([]),loading=ref(false),error=ref('');let controller,searchController,timer,pollTimer,seq=0,searchSeq=0;const preparation=new Map()
watch(()=>[props.speciesId,props.scope],()=>{selected.value=[];response.value=null;load(true)},{immediate:true})
async function load(defaults){
  const current=++seq;clearTimeout(pollTimer);controller?.abort();controller=new AbortController();const signal=controller.signal;loading.value=true;error.value=''
  try{
    const r=await getProteomeCohort(props.speciesId,{scope:props.scope,...(!defaults?{species_ids:selected.value.join(',')}:{})},{signal});if(current!==seq)return
    response.value=r;if(defaults)selected.value=r.species_ids||[];names.value={...names.value,...Object.fromEntries((r.data?.species||[]).map(s=>[s.species_id,s.label]))}
    if(r.readiness==='not_prepared'&&r.missing_species?.length){
      let pending=false
      for(const id of r.missing_species){
        const key=`${props.scope}:${id}`;let job=preparation.get(key)
        if(job?.request_id)job=await getProteomeRequest(id,job.request_id,{signal});else job=await ensureProteomeVisuals(id,{scope:props.scope},{signal})
        if(current!==seq)return;preparation.set(key,job)
        if(job.readiness==='failed'){error.value=`Calculation failed for ${id}: ${job.error||job.result?.error||'inspect task details'}`;return}
        if(['not_prepared','unavailable'].includes(job.readiness)){error.value=`${id}: ${job.reason_code}`;return}
        pending=true
      }
      if(pending)pollTimer=setTimeout(()=>load(false),1500)
    }
  }catch(e){if(current===seq&&!signal.aborted)error.value=e?.response?.data?.error?.message||e.message}finally{if(current===seq)loading.value=false}
}
function find(){clearTimeout(timer);const term=search.value.trim();if(!term){matches.value=[];return}timer=setTimeout(async()=>{const current=++searchSeq;searchController?.abort();searchController=new AbortController();try{const r=await getProteomeCohort(props.speciesId,{scope:props.scope,search:term},{signal:searchController.signal});if(current===searchSeq)matches.value=r.matches||[]}catch(e){if(!searchController.signal.aborted)error.value=e.message}},250)}
function add(s){if(selected.value.length<64&&!selected.value.includes(s.species_id)){selected.value.push(s.species_id);names.value[s.species_id]=s.display_name}matches.value=[];search.value=''}
function remove(id){selected.value=selected.value.filter(s=>s!==id)}
function reset(){selected.value=[];load(true)}
function figure(id){return {chart_id:id,title:{D11:'Species fingerprint PCA and contributions',D12:'Species distance and feature context',D16:'Observed feature dispersion across species'}[id],status:id==='D11'?response.value.data.pca?.status||'unavailable':response.value.data.status,reason_code:id==='D11'?response.value.data.pca?.reason:null,primary_scope:props.scope,species_id:props.speciesId,release_id:response.value.release_id,source_hash:response.value.cohort_hash,artifact_version:'cohort_'+response.value.cohort_hash.slice(0,16),coverage:{n_source:response.value.species_ids.length,n_valid:response.value.data.species.length},method_version:response.value.method_version,method:{name:'shared weighted whole-population fingerprint'},fields:response.value.data.fields.map(f=>({key:f,unit:'native'})),data:{kind:'cohort'}}}
function option(id){return cohortFigure(id,response.value)}
function navigate(id){router.push({path:`/species/${encodeURIComponent(id)}`,query:{panel:'proteome',tab:'analysis',scope:props.scope}})}
function download(){const blob=new Blob([JSON.stringify(response.value,null,2)],{type:'application/json'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=`proteome_${props.scope}_cohort_${response.value.cohort_hash}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),0)}
onBeforeUnmount(()=>{seq++;searchSeq++;controller?.abort();searchController?.abort();clearTimeout(timer);clearTimeout(pollTimer)})
</script>
