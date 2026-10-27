<template>
 <div v-if="legacy && !packet" class="workflow-legacy"><p class="muted workflow-note">{{ error || 'Legacy saved preview; full-population presentation is disabled.' }}</p><slot /></div>
 <div v-else class="workflow-chart" :data-chart-id="resolved?.chart_id || chartId" :data-design-revision="resolved?.design_revision" :data-workflow-slot="slotId || params.panel_id_core && 'seq.core.'+params.panel_id_core || resource+'.'+(params.panel_profile||chartId)">
  <div v-if="busy" class="workflow-state" role="status">Loading complete saved evidence…</div>
  <div v-else-if="error" class="workflow-state" role="alert">{{error}} <button type="button" class="btn secondary" @click="reload">Retry chart</button></div>
  <template v-else-if="resolved">
   <div class="workflow-toolbar"><span class="workflow-count">Full saved evidence</span><label>Export <select v-model="exportScope" aria-label="Export population"><option value="plot">Chart statistics</option><option value="source">Complete filtered sources</option></select></label><button class="chart-export-btn" type="button" :disabled="exportBusy" @click="download('csv')">CSV</button><button class="chart-export-btn" type="button" :disabled="exportBusy" @click="download('tsv')">TSV</button></div>
   <div v-if="isAdjusted" class="workflow-view-switch" role="group" aria-label="Adjusted association view"><button class="btn secondary" :aria-pressed="view==='evidence'" @click="view='evidence'">Adjustment evidence</button><button class="btn secondary" :aria-pressed="view==='ci'" @click="view='ci'">Saved confidence intervals</button></div>
   <p v-if="resolved.reason" class="workflow-note" :data-reason-code="resolved.reason_code">{{resolved.reason}}</p>
   <p v-if="resolved.design_revision!==3" class="workflow-note" data-legacy-design>Legacy display contract; saved results remain available.</p>
   <WorkflowFigure v-if="primary.length" :packet="resolved" :height="height" :detail-field="detailField" @inspect="inspect" />
   <div v-else-if="!diagnostics.length" class="workflow-state"><strong>{{resolved.status.replaceAll('_',' ')}}</strong><p>{{resolved.reason || 'No saved estimable values. Inspect the supporting source table.'}}</p></div>
   <WorkflowStatusSummary :panels="diagnostics" />
   <p v-if="primary.some(p=>p.symbol_field==='annotated')" class="workflow-note">Circle: annotated gene; cross: unannotated gene. Color identifies the saved context. Candidate priority and technical frequency are separate from gene-level significance.</p>
   <details v-if="detailPanels.length" class="workflow-field-detail"><summary>Explore a complete field distribution</summary><label>Field<select v-model="detailField" aria-label="Detailed field distribution"><option :value="null">Choose a saved field</option><option v-for="p in detailPanels" :key="p.panel_id" :value="p.panel_id">{{p.title}}</option></select></label></details>
   <details class="workflow-provenance"><summary>Methods and complete population</summary><p>{{metadata(resolved)}}</p><p>{{resolved.method?.name}}. {{resolved.method?.transform}}. {{resolved.method?.unit}}.</p><ul><li v-for="p in resolved.data.panels.filter(p=>p.role!=='diagnostic')" :key="p.panel_id">{{p.title}}: {{p.counts?.scope_rows?.toLocaleString('en-US')}} in scope, {{p.counts?.finite_rows?.toLocaleString('en-US')}} finite, {{p.counts?.non_estimable_rows?.toLocaleString('en-US')}} non-estimable. {{p.ci_transform ? 'Saved CI: '+p.ci_transform : ''}}</li></ul><pre>{{JSON.stringify(resolved.provenance?.source_tables,null,2)}}</pre></details>
   <div v-if="details" class="workflow-records" role="region" aria-label="Exact plot members"><div class="workflow-toolbar"><strong>{{details.total.toLocaleString('en-US')}} exact members</strong><button type="button" class="btn secondary" @click="details=null">Close members</button><button type="button" class="chart-export-btn" @click="downloadMembers">Export all members</button></div><div class="workflow-record-table"><table class="table compact-table"><thead><tr><th v-for="c in detailColumns" :key="c">{{c}}</th><th>Inspect</th></tr></thead><tbody><tr v-for="(row,i) in details.rows" :key="i"><td v-for="c in detailColumns" :key="c">{{row[c]}}</td><td><button type="button" class="btn secondary" @click="emit('inspect',{chart_id:resolved.chart_id,panel_id:detailSelection.panel_id,row})">Inspect</button></td></tr></tbody></table></div><button class="btn secondary" :disabled="details.page===1" @click="loadMembers(details.page-1)">Previous</button><span> Page {{details.page}} </span><button class="btn secondary" :disabled="details.page*details.page_size>=details.total" @click="loadMembers(details.page+1)">Next</button></div>
   <p v-if="actionError" role="alert" class="workflow-action-error">{{actionError}}</p>
  </template>
 </div>
</template>
<script setup>
import {computed,ref,watch,onBeforeUnmount,getCurrentInstance} from 'vue'
import WorkflowFigure from './WorkflowFigure.vue'
import WorkflowStatusSummary from './WorkflowStatusSummary.vue'
import {metadata} from '../../utils/workflowVisuals/shared'
import {useWorkflowVisuals} from '../../composables/useWorkflowVisuals'
import {exportWorkflowVisual,getWorkflowRecords} from '../../api/workflowVisuals'
const props=defineProps({resource:String,identifier:String,chartId:String,params:{type:Object,default:()=>({})},packet:Object,slotId:String,height:{type:Number,default:360}})
const emit=defineEmits(['inspect','retry'])
const instance=getCurrentInstance()
const view=ref('evidence'),detailField=ref(null)
const isAdjusted=computed(()=>props.params?.panel_profile==='adjusted_forest'||props.packet?.chart_id==='H08')
const state=useWorkflowVisuals(()=>({resource:props.packet&&view.value!=='ci'?null:props.resource,identifier:props.identifier,chart:view.value==='ci'?'H28':props.chartId,params:view.value==='ci'?{...props.params,panel_profile:'adjusted_forest'}:props.params}))
const resolved=computed(()=>view.value==='ci'?state.packet.value:props.packet||state.packet.value),busy=computed(()=>(view.value==='ci'||!props.packet)&&state.busy.value),error=computed(()=>(view.value==='ci'||!props.packet)&&state.error.value),legacy=computed(()=>!props.packet&&state.legacy.value)
const primary=computed(()=>(resolved.value?.data?.panels||[]).filter(p=>!['diagnostic','detail'].includes(p.role)))
const diagnostics=computed(()=>(resolved.value?.data?.panels||[]).filter(p=>p.role==='diagnostic'))
const detailPanels=computed(()=>(resolved.value?.data?.panels||[]).filter(p=>p.role==='detail'))
const exportScope=ref('plot'),exportBusy=ref(false),actionError=ref(''),details=ref(null),detailSelection=ref({})
const detailColumns=computed(()=>Object.keys(details.value?.rows?.[0]||{}))
let controller
watch(()=>resolved.value?.plot_signature,()=>{controller?.abort();details.value=null;detailSelection.value={};detailField.value=null;actionError.value=''})
function reload(){state.reload();emit('retry')}
function analysisParams(){return {...props.params,...resolved.value?.scope?.filters}}
async function download(format,extra={}){exportBusy.value=true;actionError.value='';try{await exportWorkflowVisual(props.resource,props.identifier,resolved.value.chart_id,{...analysisParams(),export_scope:exportScope.value,format,plot_signature:resolved.value.plot_signature,...extra})}catch(e){actionError.value=e.response?.status===409?'Saved evidence changed. Refresh this chart before exporting.':e.response?.data?.error?.message||e.message}finally{exportBusy.value=false}}
async function inspect(panel,event){
 const data=event?.data;if(!data)return
 if(data.record_id!==undefined&&data.raw&&instance.vnode.props?.onInspect){emit('inspect',{chart_id:resolved.value.chart_id,panel_id:panel.panel_id,row:data.raw});return}
 if(data.bin_id||data.record_id!==undefined){detailSelection.value={panel_id:panel.panel_id,...(data.bin_id?{bin_id:data.bin_id}:{record_id:data.record_id})};await loadMembers(1);if(data.record_id!==undefined&&details.value?.rows?.length===1&&instance.vnode.props?.onInspect){emit('inspect',{chart_id:resolved.value.chart_id,panel_id:panel.panel_id,row:details.value.rows[0]});details.value=null}}
 else if(data.raw)emit('inspect',{chart_id:resolved.value.chart_id,panel_id:panel.panel_id,row:data.raw})
}
async function loadMembers(page){controller?.abort();controller=new AbortController();actionError.value='';try{details.value=await getWorkflowRecords(props.resource,props.identifier,resolved.value.chart_id,{...analysisParams(),...detailSelection.value,plot_signature:resolved.value.plot_signature,page,page_size:25},controller.signal)}catch(e){if(e.code!=='ERR_CANCELED')actionError.value=e.response?.status===409?'This plot is stale. Retry the chart.':e.response?.data?.error?.message||e.message}}
function downloadMembers(){return download('csv',{...detailSelection.value,export_scope:'source'})}
onBeforeUnmount(()=>controller?.abort())
</script>
<style scoped>
.workflow-chart{display:flex;flex-direction:column;min-width:0;position:relative;overflow:visible;color:var(--text-main,#173B64)}
.workflow-toolbar{display:flex;align-items:center;gap:6px;flex-wrap:wrap;flex-shrink:0;min-height:30px;font-size:.72rem;line-height:1.4}
.workflow-count{flex:1;min-width:110px;overflow-wrap:anywhere;color:#173B64}.workflow-toolbar label{display:flex;align-items:center;gap:4px}.workflow-toolbar select{font:inherit;border:1px solid var(--line-soft,#d6e2ef);border-radius:6px;background:#fff;color:#173B64;max-width:155px}
.chart-export-btn{border:1px solid rgba(42,89,140,.16);background:rgba(255,255,255,.9);color:#1f5d9a;border-radius:999px;padding:5px 10px;font-size:.75rem;cursor:pointer}.chart-export-btn:focus-visible{outline:2px solid #2468C7;outline-offset:2px}.chart-export-btn:disabled{opacity:.55;cursor:wait}
.workflow-panels{min-width:0}.workflow-panel{min-width:0;border-bottom:1px solid var(--line-soft,#e3ebf2);padding:2px 0 7px}.workflow-panel:last-of-type{border-bottom:0}.workflow-note{font-size:.72rem;line-height:1.5;margin:4px 0;color:#536E88;overflow-wrap:anywhere}.workflow-state{padding:18px 4px;font-size:.88rem;overflow:auto}.workflow-provenance{font-size:.74rem;color:#173B64;padding:8px}.workflow-provenance pre{white-space:pre-wrap;font-size:.7rem}.workflow-records{position:absolute;inset:0;background:#fff;z-index:1;padding:8px;display:flex;flex-direction:column;overflow:auto;border:1px solid var(--line-soft,#d6e2ef);border-radius:8px}.workflow-record-table{overflow:auto;flex:1;min-height:60px}.workflow-record-table td{max-width:240px;overflow-wrap:anywhere}.workflow-action-error{color:#9b2c20;font-size:.8rem;overflow-wrap:anywhere;margin:4px}.workflow-legacy{min-width:0}.workflow-chart :deep(.chart-host){min-height:0}.workflow-chart :deep(.chart-export-row){margin:3px 0 4px}
@media(max-width:760px){.workflow-toolbar{font-size:.76rem}.chart-export-btn{min-height:36px}.workflow-chart :deep(.chart-export-btn){min-height:36px}.workflow-toolbar select{max-width:120px}}
.workflow-view-switch{display:flex;gap:6px;margin:5px 0}.workflow-view-switch button{font-size:.75rem;padding:5px 8px}.workflow-view-switch [aria-pressed="true"]{background:#edf5fc;border-color:#2468C7}.workflow-field-detail{font-size:.76rem;margin:5px 0}.workflow-field-detail label{display:flex;gap:6px;align-items:center;padding:6px 0}.workflow-field-detail select{max-width:100%;font:inherit;color:inherit}
</style>
