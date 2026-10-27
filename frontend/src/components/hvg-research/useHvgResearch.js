import { reactive, onBeforeUnmount, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { researchGet } from '../../api/hvgResearch'
import {getWorkflowCapabilities,workflowVisualsEnabled} from '../../api/workflowVisuals'

export function useHvgResearch(identifier) {
  const route=useRoute(), router=useRouter()
  const state=reactive({available:false, initialized:false, loading:false, error:'', accessDenied:false, summary:{}, visualCapabilities:null, runs:[], phenomena:[],sharedVisuals:{},modelClass:'',
    run:String(route.query.research_run||''),context:String(route.query.research_context||'global'),
    feature:String(route.query.research_feature||''),term:String(route.query.research_term||''),source:'',direction:'',scope:'all_annotated',qmax:'',gene:String(route.query.research_gene||''),set:'',version:0,compact:window.matchMedia('(max-width:760px)').matches})
  let generation=0,timer,disposed=false
  state.params=(extra={},filtered=true)=>({analysis_run_id:state.run||undefined,context_id:state.context||undefined,
    ...(filtered?{feature_key:state.feature||undefined,term_key:state.term||undefined,source:state.source||undefined,direction:state.direction||undefined,q_max:state.qmax,scope:state.scope||undefined}:{}),...extra})
  state.get=(endpoint,extra={},filtered=true,signal)=>researchGet(identifier(),endpoint,state.params(extra,filtered),{signal})
  state.persist=(tab)=>router.replace({query:{...route.query,research_run:state.run||undefined,research_context:state.context||undefined,
    research_feature:state.feature||undefined,research_term:state.term||undefined,research_gene:state.gene||undefined,
    ...(tab?{research_tab:tab,research_panel:undefined}:{})}}).catch(()=>{})
  state.clear=()=>{state.feature='';state.term='';state.source='';state.direction='';state.qmax='';state.set='';state.modelClass='';state.sharedVisuals={};state.scope='all_annotated';state.version++;state.persist()}
  state.refresh=async()=>{
    const id=++generation;clearTimeout(timer);state.loading=true;state.error='';state.accessDenied=false
    try{
      const [s,r]=await Promise.all([state.get('summary',{},false),researchGet(identifier(),'runs')])
      if(disposed||id!==generation)return
      state.summary=s;state.runs=r.rows||[];state.available=true;state.run=s.analysis_run_id
      if(workflowVisualsEnabled){try{const caps=await getWorkflowCapabilities('hvg',identifier());if(!disposed&&id===generation)state.visualCapabilities=caps}catch{if(!disposed&&id===generation)state.visualCapabilities=null}}
      if(disposed||id!==generation)return
      if(!(s.contexts||[]).some(c=>c.context_id===state.context))state.context=s.contexts?.[0]?.context_id||'global'
      const p=await state.get('phenomena',{},false)
      if(disposed||id!==generation)return
      state.phenomena=(p.rows||[]).filter(x=>!x.context_id||x.context_id===state.context)
      state.persist();state.version++
      if(s.status==='running')timer=setTimeout(state.refresh,5000)
    }catch(e){if(disposed||id!==generation)return;state.accessDenied=e.response?.status===403;if(e.response?.status===404)state.available=false;else state.error=e.response?.data?.error?.message||e.message}
    finally{if(!disposed&&id===generation){state.loading=false;state.initialized=true}}
  }
  watch(()=>state.run,(next,previous)=>{if(state.initialized&&next&&next!==state.summary.analysis_run_id){state.clear();state.gene='';state.refresh()}})
  watch(()=>state.context,()=>{state.clear();state.gene='';state.persist();if(state.initialized)state.refresh()})
  const media=window.matchMedia('(max-width:760px)'),resize=e=>{state.compact=e.matches};media.addEventListener('change',resize)
  onBeforeUnmount(()=>{disposed=true;generation++;clearTimeout(timer);media.removeEventListener('change',resize)})
  return state
}
