<template>
  <div class="proteome-viz-workspace" data-testid="proteome-v3" :data-species-id="speciesId" :data-scope="scope" :data-section="section">
    <ModuleState v-if="error" state="error" title="Proteome results unavailable" :message="error" :retry="reload" />
    <ModuleState v-else-if="!manifest" state="loading" title="Loading complete Proteome results" message="Retrieving the current population, feature catalog and chart versions." />
    <section v-else-if="manifest.readiness!=='ready'" class="panel" data-testid="proteome-preparation" :data-status="manifest.readiness"><h3>{{ ['queued','running','interrupted'].includes(manifest.readiness)?'Calculating complete-population visualizations':manifest.readiness==='failed'?'Visualization calculation failed':'Visualizations are not yet available for this release' }}</h3><p v-if="manifest.reason_code==='full_not_registered'">This species has no registered Full file. Its Core results remain available.</p><p v-else-if="['queued','running','interrupted'].includes(manifest.readiness)">{{ manifest.readiness==='running'?'Computing all valid records':'Waiting for the calculation worker' }}. Results will appear automatically when ready; the complete feature table remains available.</p><p v-else>{{ manifest.calculation_error||manifest.reason_code||'The complete feature table remains available while visualization results are prepared.' }}</p><button class="btn subtle" @click="reload">Check availability / retry</button></section>
    <template v-else>
      <section class="panel proteome-viz-summary"><div class="section-header"><div><h3>Proteome · {{ section==='basic'?'Basic visualization':'Deep analysis' }}</h3><p class="muted">{{ manifest.n_source.toLocaleString() }} complete {{ scope }} records · {{ manifest.fields.length }} numeric fields · sequence-derived descriptions</p></div><div class="metric-band"><span class="badge">{{ scope }}</span><span class="badge">Whole population</span><span class="badge">{{ manifest.method_version }}</span></div></div><p class="muted">Each plot uses the fields required by its scientific question. Zero, missing and constant values retain their own meaning.</p></section>
      <div class="proteome-viz-grid">
        <template v-for="id in plotIds" :key="id">
          <div :class="['proteome-viz-item',span(id)]">
            <div v-if="id==='B15'" class="proteome-controls proteome-pair-controls"><label>X descriptor<select v-model="pairX" class="input" data-testid="pair-x"><option v-for="f in manifest.fields" :key="f.key" :value="f.key">{{ f.key }}</option></select></label><label>Y descriptor<select v-model="pairY" class="input" data-testid="pair-y"><option v-for="f in manifest.fields" :key="f.key" :value="f.key">{{ f.key }}</option></select></label><button class="btn" :disabled="pairLoading" @click="loadPair">Update relationship</button></div>
            <ProteomeFigure :figure="id==='B15'&&pairResult?pairResult:states[id]?.result" :chart-id="id" :species-id="speciesId" :scope="scope" :loading="id==='B15'?pairLoading||states[id]?.loading:states[id]?.loading" :error="id==='B15'?pairError||states[id]?.error:states[id]?.error" @bin="openBin" @structure-window="openStructure" />
            <ProteomeStructureAtlas v-if="id==='D07'&&states.D07?.result" :species-id="speciesId" :scope="scope" :manifest="manifest" :overview="states.D07.result" :requested-start="structureStart" />
          </div>
        </template>
      </div>
      <ProteomeFieldAtlas v-if="section==='basic'" :species-id="speciesId" :scope="scope" :manifest="manifest" />
      <section v-if="members" class="panel" data-testid="proteome-bin-members"><div class="section-header"><div><h3>All records in the selected hexagon</h3><p class="muted">{{ members.total?.toLocaleString()||0 }} members · {{ selectedBin?.bin_id }} · {{ selectedBin?.figure?.artifact_version }}</p></div><button class="btn subtle" @click="closeMembers">Close records</button></div><p v-if="memberLoading">Loading records…</p><p v-if="memberError">{{ memberError }}</p><div class="table-wrap"><table><thead><tr><th>Protein ID</th><th>Gene ID</th><th>Gene symbol</th><th>Description</th></tr></thead><tbody><tr v-for="row in members.rows||[]" :key="row.protein_id"><td><button class="proteome-entity-link" @click="openProtein(row)">{{ row.protein_id }}</button></td><td>{{ row.gene_id }}</td><td>{{ row.gene_symbol }}</td><td>{{ row.description }}</td></tr></tbody></table></div><div class="proteome-controls"><button class="btn subtle" :disabled="memberPage===1||memberLoading" @click="memberPage--;loadMembers()">Previous records</button><span>Page {{ memberPage }} / {{ Math.max(1,Math.ceil((members.total||0)/50)) }}</span><button class="btn subtle" :disabled="memberPage*50>=members.total||memberLoading" @click="memberPage++;loadMembers()">Next records</button></div></section>
      <ProteomeCohortSelector v-if="section==='analysis'" :species-id="speciesId" :scope="scope" />
      <ProteomeCandidateTable :species-id="speciesId" :scope="scope" :manifest="manifest" />
    </template>
  </div>
</template>
<script setup>
import {computed,ref,watch,onBeforeUnmount} from 'vue'
import ModuleState from '../ModuleState.vue'
import ProteomeFigure from './ProteomeFigure.vue'
import ProteomeFieldAtlas from './ProteomeFieldAtlas.vue'
import ProteomeStructureAtlas from './ProteomeStructureAtlas.vue'
import ProteomeCohortSelector from './ProteomeCohortSelector.vue'
import ProteomeCandidateTable from './ProteomeCandidateTable.vue'
import {useProteomeVisuals} from '../../composables/useProteomeVisuals'
import {getProteomePair,getProteomeMembers} from '../../api/proteomeVisuals'
const props=defineProps({speciesId:String,scope:{type:String,default:'core'},section:{type:String,default:'basic'}});const emit=defineEmits(['manifest'])
const {manifest,states,error,loading,reload}=useProteomeVisuals(props)
const plotIds=computed(()=>props.section==='basic'?[...Array.from({length:12},(_,i)=>`B${String(i+1).padStart(2,'0')}`),'B15']:['D01','D02','D03','D04','D05','D06','D07','D08','D09','D10','D13','D14','D15'])
const span=id=>['B03','B04','B06','B08','B11','B12','D04','D08'].includes(id)?'proteome-viz-half':'proteome-viz-wide'
const pairX=ref('pI'),pairY=ref('N_atoms_per_aa'),pairResult=ref(null),pairLoading=ref(false),pairError=ref(''),members=ref(null),selectedBin=ref(null),memberPage=ref(1),memberLoading=ref(false),memberError=ref(''),structureStart=ref(null);let pairController,memberController,pairSeq=0,memberSeq=0
watch(manifest,m=>{if(m)emit('manifest',m)})
watch(()=>[props.speciesId,props.scope,props.section],()=>{pairSeq++;memberSeq++;pairController?.abort();memberController?.abort();pairLoading.value=false;pairError.value='';memberLoading.value=false;memberError.value='';pairResult.value=null;members.value=null;selectedBin.value=null;structureStart.value=null;pairX.value='pI';pairY.value='N_atoms_per_aa'})
async function loadPair(){if(!manifest.value)return;const current=++pairSeq;pairController?.abort();pairController=new AbortController();pairLoading.value=true;pairError.value='';try{const r=await getProteomePair(props.speciesId,{scope:props.scope,artifact_version:manifest.value.artifact_version,source_hash:manifest.value.source_hash,x:pairX.value,y:pairY.value},{signal:pairController.signal});if(current===pairSeq)pairResult.value=r.result}catch(e){if(current===pairSeq&&!pairController.signal.aborted)pairError.value=e?.response?.data?.error?.message||e.message}finally{if(current===pairSeq)pairLoading.value=false}}
function openBin(raw){selectedBin.value=raw;memberPage.value=1;members.value={total:0,rows:[]};loadMembers()}
async function loadMembers(){const b=selectedBin.value;if(!b)return;const current=++memberSeq;memberController?.abort();memberController=new AbortController();memberLoading.value=true;memberError.value='';try{const r=await getProteomeMembers(props.speciesId,{scope:props.scope,chart_id:b.chart_id,bin_id:b.bin_id,variant_id:b.variant_id||'',artifact_version:b.figure.artifact_version,source_hash:b.figure.source_hash,page:memberPage.value,page_size:50},{signal:memberController.signal});if(current===memberSeq)members.value=r}catch(e){if(current===memberSeq&&!memberController.signal.aborted)memberError.value=e?.response?.data?.error?.message||e.message}finally{if(current===memberSeq)memberLoading.value=false}}
function closeMembers(){memberSeq++;memberController?.abort();members.value=null;selectedBin.value=null}
function openStructure(rank){structureStart.value=rank}
function openProtein(row){window.dispatchEvent(new CustomEvent('stoich-entity-chart-click',{detail:{...row,species_id:props.speciesId,entity_id:row.protein_id,report_entity_key:row.protein_id}}))}
onBeforeUnmount(()=>{pairSeq++;memberSeq++;pairController?.abort();memberController?.abort()})
</script>
<style>
.proteome-viz-workspace{display:flex;flex-direction:column;gap:22px;min-width:0;color:#18334a}
.proteome-viz-workspace h3,.proteome-viz-workspace h4{text-wrap:balance}
.proteome-viz-grid{display:grid;grid-template-columns:repeat(12,minmax(0,1fr));gap:22px}
.proteome-viz-item{min-width:0;display:flex;flex-direction:column;gap:18px}.proteome-viz-wide{grid-column:1/-1}.proteome-viz-half{grid-column:span 6}.proteome-viz-half>.proteome-figure{flex:1}
.proteome-figure{min-width:0;box-sizing:border-box}.proteome-figure .section-header{align-items:flex-start;gap:15px}.proteome-figure h3{font-size:18px;line-height:1.35;margin:0 0 8px}
.proteome-plot-scroll{overflow-x:auto;max-width:100%;background:#fff}.proteome-plot-scroll>div{min-width:0}
.proteome-viz-workspace .chart-export-row{position:relative;inset:auto;justify-content:flex-end;min-height:28px;margin-bottom:6px}
.proteome-scientific-caption{font-size:12px;line-height:1.65;color:#526575;margin:12px 0;max-width:90ch}
.proteome-downloads{display:flex;gap:8px 18px;flex-wrap:wrap;font-size:12px;padding:10px 0;border-top:1px solid #dce4ea}
.proteome-method{font-size:12px;line-height:1.6;color:#526575;margin-top:8px}.proteome-method summary{cursor:pointer;color:#285d85}.proteome-method p{overflow-wrap:anywhere;max-width:95ch}.proteome-version{font-family:ui-monospace,monospace;font-size:10px}
.proteome-controls{display:flex;gap:12px;align-items:end;flex-wrap:wrap;margin:14px 0;color:#526575;font-size:12px}.proteome-controls label{display:flex;flex-direction:column;gap:6px;min-width:150px;max-width:100%}.proteome-controls .input{max-width:100%;min-width:0}.proteome-controls input[type=number]{width:160px}.proteome-pair-controls{padding:0 18px}.proteome-controls button{white-space:normal}
.proteome-field-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px}.proteome-field-grid>section{min-width:0;border-top:1px solid #dce4ea;padding-top:12px}.proteome-field-grid h4{font-size:14px;margin:0 0 8px}.proteome-viz-workspace .table-wrap{max-width:100%;overflow:auto}.proteome-viz-workspace table{font-size:12px}
.proteome-entity-link{padding:0;border:0;background:none;color:#1f5d9a;cursor:pointer;text-align:left;font:inherit;overflow-wrap:anywhere;text-decoration:underline;text-underline-offset:3px}.proteome-entity-link:focus-visible{outline:2px solid #2867a1;outline-offset:4px}
.proteome-cohort-list{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0 24px}.proteome-cohort-list button{font-size:11px;max-width:100%;overflow-wrap:anywhere}.proteome-species-matches{list-style:none;padding:0;max-height:280px;overflow:auto}.proteome-species-matches li{margin:5px 0}.proteome-species-matches button{text-align:left;max-width:100%;overflow-wrap:anywhere}.proteome-species-matches span{display:block;font-size:10px}.proteome-structure-control{padding:12px 0}.proteome-cohort-section{display:flex;flex-direction:column;gap:18px;min-width:0}
@media(max-width:1100px){.proteome-viz-half{grid-column:1/-1}}
@media(max-width:700px){.proteome-field-grid{grid-template-columns:1fr}.proteome-viz-workspace .panel{padding:16px}.proteome-viz-grid{gap:16px}.proteome-viz-workspace h3{font-size:16px}.proteome-controls label{flex:1 1 160px}.proteome-viz-workspace .section-header{flex-wrap:wrap}.proteome-downloads{gap:10px}.proteome-controls .btn{padding:9px 12px}}
@media(prefers-reduced-motion:reduce){.proteome-viz-workspace *{animation:none!important;transition-duration:0ms!important}}
</style>
