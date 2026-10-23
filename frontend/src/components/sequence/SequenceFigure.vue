<template>
 <section ref="frame" class="panel sequence-viz-figure" data-testid="sequence-figure" :data-chart-id="chartId" :data-status="loading?'loading':error?'failed':figure?.status||'unavailable'">
  <div class="section-header"><div><h3>{{ chartId }} · {{ sequenceTitles[chartId]||title||figure?.title }}</h3><p v-if="figure" class="muted">{{ figure.primary_scope }} · {{ figure.coverage?.n_source?.toLocaleString() }} {{ figure.data?.cohort?'species':omics==='genome'?'gene records':'transcript records' }} · whole population<span v-if="figure.coverage?.n_fit!==undefined &amp;&amp; figure.coverage.n_fit!==figure.coverage.n_source"> · {{ figure.coverage.n_fit }} fitted</span><span v-if="figure.coverage?.n_pair!==undefined &amp;&amp; figure.coverage.n_pair!==null"> · {{ figure.coverage.n_pair }} jointly valid</span></p></div><span v-if="figure" class="badge">{{ figure.status }}</span></div>
  <ModuleState v-if="loading" state="loading" title="Loading complete-population result" />
  <ModuleState v-else-if="error" state="error" title="Result unavailable" :message="error" />
  <ModuleState v-else-if="!figure||figure.status==='unavailable'" state="missing" title="Analysis unavailable for these inputs" :message="figure?.reason_code||figure?.source_capability_note||'Required fields or sufficient eligible records are unavailable. The complete feature atlas remains accessible.'" />
  <template v-else>
   <p v-if="figure.source_capability_note" class="sequence-viz-caption">{{ figure.source_capability_note }}</p><p v-if="figure.reason_code" class="muted">{{ figure.reason_code }}</p>
   <div class="sequence-viz-scroll"><div :style="{minWidth:minimumWidth+'px'}"><EChart :option="option" :height="height" :auto-loading="false" :show-data-exports="false" :export-name="exportName" @chart-click="click" /></div></div>
   <p class="sequence-viz-caption">{{ caption }}</p>
   <p v-if="figure.data?.correlation" class="sequence-viz-caption">Paired n={{ figure.data.correlation.n }} · Spearman ρ={{ fmt(figure.data.correlation.rho) }}{{ figure.data.correlation.reason?' · '+figure.data.correlation.reason:'' }}</p>
   <div class="sequence-viz-downloads"><a v-if="!figure.data?.cohort" :href="download('complete_rows')">Complete records CSV</a><a v-else :href="download('cohort')">Complete cohort inputs and matrices JSON</a><a v-if="!figure.data?.cohort" :href="download('raw_source_view')">Original primary source CSV</a><a :href="download('chart')">Figure aggregate JSON</a><a :href="download('method')">Source &amp; method JSON</a><a v-if="figure.design_kind?.includes('pca')&&!figure.data.cohort" :href="download('coordinates')">All PCA coordinates</a><a v-if="figure.design_kind==='kmeans_context'" :href="download('assignments')">All assignments</a><a v-if="figure.data.profile" :href="download('exact_ecdf',{field:figure.data.profile.field})">Exact ECDF CSV</a></div>
   <details class="sequence-viz-method"><summary>Inputs, method and provenance</summary><p>{{ figure.method?.name }} · {{ figure.method?.inputs?.join(', ') }}</p><p>All eligible records; no row sampling. Quantiles describe record distributions, not confidence intervals. Sequence descriptors are not expression measurements.</p><p>{{ figure.method_version }} · {{ figure.artifact_version }} · {{ figure.source_hash }}</p><pre>{{ JSON.stringify(figure.method?.parameters,null,2) }}</pre></details>
  </template>
 </section>
</template>
<script setup>
import {computed,ref,onMounted,onBeforeUnmount} from 'vue'
import EChart from '../EChart.vue'
import ModuleState from '../ModuleState.vue'
import {sequenceCaption} from '../../utils/sequenceCaptions'
import {sequenceTitles} from '../../utils/sequenceTitles'
import {sequenceOption,sequenceHeight} from '../../utils/sequenceCharts'
import {sequenceExport} from '../../api/sequenceVisuals'
import {number as fmt} from '../../utils/sequenceFormat'
const props=defineProps({figure:Object,chartId:String,speciesId:String,omics:String,scope:String,loading:Boolean,error:String,title:String,threshold:Number});const emit=defineEmits(['bin']);const frame=ref(),width=ref(1000);let observer
onMounted(()=>{observer=new ResizeObserver(e=>width.value=e[0].contentRect.width);observer.observe(frame.value)});onBeforeUnmount(()=>observer?.disconnect())
const enriched=computed(()=>({...props.figure,__narrow:width.value<700,__width:width.value,__threshold:props.threshold}));const option=computed(()=>{const o=sequenceOption(enriched.value);if(!props.figure)return o;const f=props.figure;o.visualMap=(Array.isArray(o.visualMap)?o.visualMap:o.visualMap?[o.visualMap]:[]).map(v=>({...v,bottom:42}));o.graphic=[...(o.graphic||[]),{type:'text',left:14,bottom:3,silent:true,style:{text:`${props.speciesId} · ${props.omics} · ${props.scope} · n_source=${f.coverage?.n_source}${f.design_kind?.includes('pca')&&!f.data?.cohort?' · n_fit='+f.coverage.n_fit:f.data?.profile?' · n_valid='+f.data.profile.n_valid:''}${f.coverage?.n_pair!==undefined&&f.coverage.n_pair!==null?' · n_pair='+f.coverage.n_pair:''}\n${props.chartId} · ${f.method_version||''} · artifact ${f.artifact_version||''} · ${f.data?.cohort?'cohort '+f.data.cohort.cohort_id.slice(0,12):'source '+(f.source_hash?.slice(0,12)||'')}`,fontSize:10,lineHeight:13,fill:'#526575'}}];return o});const height=computed(()=>sequenceHeight(enriched.value));const minimumWidth=computed(()=>props.figure?.data?.kind==='species_distance'?1000:['codon_grammar_64','pairwise_spearman_matrix','rna_protein_cross_matrix','native_candidate_evidence','candidate_union_evidence','core_quantile_signature'].includes(props.figure?.data?.kind)?720:0)
const exportName=computed(()=>[props.speciesId,props.omics,props.scope,props.chartId,props.figure?.variant_id?.slice(0,10),props.figure?.data?.cohort?.cohort_id?.slice(0,12),props.figure?.artifact_version].filter(Boolean).join('_'))
const caption=computed(()=>sequenceCaption(props.figure))
function download(kind,extra={}){return sequenceExport(props.speciesId,props.omics,{scope:props.scope,kind,chart_id:props.chartId,artifact_version:props.figure?.artifact_version||'',source_hash:props.figure?.source_hash||'',...(props.figure?.variant_id?{variant_id:props.figure.variant_id}:{}),...(props.threshold!==undefined?{threshold:props.threshold}:{}),...(props.figure?.data?.cohort?{species:props.figure.data.cohort.selected_species.join(',')}:{}),...extra})}
function click(e){const raw=e?.data?.raw;if(raw?.bin_id!==undefined)emit('bin',{...raw,figure:props.figure})}
</script>
