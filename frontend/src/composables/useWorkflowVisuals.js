import {ref,shallowRef,watch,onBeforeUnmount} from 'vue'
import {getWorkflowVisual,workflowVisualsEnabled} from '../api/workflowVisuals'
let active=0;const queue=[]
async function bounded(work,signal){
 if(active>=3)await new Promise(resolve=>queue.push(resolve))
 if(signal.aborted){queue.shift()?.();throw Object.assign(new Error('Cancelled'),{code:'ERR_CANCELED'})}
 active++
 try{return await work()}finally{active--;queue.shift()?.()}
}
export function useWorkflowVisuals(selection){
 const packet=shallowRef(null),busy=ref(false),error=ref(''),legacy=ref(!workflowVisualsEnabled)
 let generation=0,controller
 async function reload(){
  const selected=selection(),version=++generation;controller?.abort();controller=new AbortController();error.value='';packet.value=null
  if(!workflowVisualsEnabled||!selected.resource||!selected.identifier||!selected.chart){legacy.value=true;busy.value=false;return}
  legacy.value=false;busy.value=true
  try{const result=await bounded(()=>getWorkflowVisual(selected.resource,selected.identifier,selected.chart,selected.params||{},controller.signal),controller.signal);if(version===generation){if(result?.schema_version!=='workflow_viz_v2'){legacy.value=true;error.value='Legacy saved preview: backend presentation version differs.'}else packet.value=result}}
  catch(e){if(version===generation&&e.code!=='ERR_CANCELED'){if(e.response?.status===404){legacy.value=true;error.value='Legacy saved preview: full-population presentation is unavailable for this saved task.'}else error.value=e.response?.data?.error?.message||e.message}}
  finally{if(version===generation)busy.value=false}
 }
 watch(()=>JSON.stringify(selection()),reload,{immediate:true})
 onBeforeUnmount(()=>{generation++;controller?.abort()})
 return {packet,busy,error,legacy,reload}
}
