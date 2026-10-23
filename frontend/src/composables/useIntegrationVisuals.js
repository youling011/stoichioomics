import {ref,reactive,watch,onBeforeUnmount} from 'vue'
import {integrationGet,integrationPost} from '../api/integrationVisuals'
export function useIntegrationVisuals(speciesId,active){
 const manifest=ref(null),charts=reactive({}),cohort=ref(null),cohortTask=ref(null),cohortKey=ref(''),status=ref('missing'),error=ref(''),busy=ref(false)
 let generation=0,controller=new AbortController(),timer=null,disposed=false,loading=0;const queue=[],cache=new Map(),wanted=new Set(),cohortIds=new Set(['OV01','CX14','CX15','CX16','XS01']);let cohortRequest=null,customRequest=null
 const sid=()=>speciesId.value;const params=()=>({artifact_version:manifest.value?.artifact_version,cohort_key:cohortKey.value||undefined})
 const valid=(g,id)=>!disposed&&g===generation&&sid()===id&&active.value
 function cancel(){generation++;controller.abort();controller=new AbortController();clearTimeout(timer);timer=null;queue.splice(0);loading=0;busy.value=false}
 function later(fn){clearTimeout(timer);if(active.value&&!disposed)timer=setTimeout(fn,1500)}
 async function refresh(){if(!active.value||!sid())return;const g=generation,id=sid();busy.value=true;error.value=''
  try{const m=await integrationGet(id,'',{},controller.signal);if(!valid(g,id))return;const prior=manifest.value
   if(prior?.artifact_version&&prior.artifact_version!==m.artifact_version){for(const k of Object.keys(charts))delete charts[k];queue.splice(0)}
   if(prior?.default_cohort_key&&cohortKey.value===prior.default_cohort_key&&cohortKey.value!==m.default_cohort_key){cohortKey.value=m.default_cohort_key;cohort.value=null;for(const k of cohortIds)delete charts[k]}
   for(const k of Object.keys(charts))if(charts[k]?.status==='failed')delete charts[k]
   manifest.value=m;status.value=m.status
   if(m.status==='ready'){
    if(customRequest){want([...wanted].filter(k=>!cohortIds.has(k)));later(()=>pollCustom(customRequest));return}
    if(!cohortKey.value)cohortKey.value=m.default_cohort_key
    const ensured=await integrationPost(id,'ensure/',{policy:'core_plus_optional_full'},controller.signal);if(!valid(g,id))return
    if(cohortKey.value===m.default_cohort_key&&ensured.default_cohort_key){cohortKey.value=ensured.default_cohort_key;manifest.value={...m,default_cohort_key:ensured.default_cohort_key}}
    cohortRequest=ensured.cohort_request
    if(cohortRequest&&cohortRequest.status!=='ready')later(()=>poll(cohortRequest.request_id,true));else await loadCohort()
    want([...wanted]);return
   }
   const r=await integrationPost(id,'ensure/',{policy:'core_plus_optional_full'},controller.signal);if(!valid(g,id))return
   status.value=r.status;if(r.status==='ready')later(refresh);else if(r.request_id)later(()=>poll(r.request_id,false))
  }catch(e){if(!valid(g,id))return;error.value=e?.response?.data?.error?.message||e.message;status.value='failed'}finally{if(valid(g,id))busy.value=false}
 }
 async function poll(requestId,isCohort){if(!active.value)return;const g=generation,id=sid();try{const r=await integrationGet(id,`requests/${requestId}/`,{},controller.signal);if(!valid(g,id))return
  if(r.status==='ready'){if(isCohort){if(r.cohort_key){cohortKey.value=r.cohort_key;manifest.value={...manifest.value,default_cohort_key:r.cohort_key}}await loadCohort();await loadPending()}else await refresh()}
  else if(['failed','interrupted'].includes(r.status)){error.value=r.reason||r.status;status.value=r.status}
  else later(()=>poll(requestId,isCohort))
 }catch(e){if(valid(g,id)){error.value=e.message;status.value='failed'}}}
 async function loadCohort(){const g=generation,id=sid(),key=cohortKey.value;try{const r=await integrationGet(id,'cohort/',params(),controller.signal);if(valid(g,id)&&key===cohortKey.value)cohort.value=r}catch(e){if(valid(g,id)&&e?.response?.status===409&&cohort.value?.species_ids){await selectCohort([...cohort.value.species_ids])}else if(valid(g,id)&&e?.response?.status!==404)error.value=e.message}}
 function want(ids){for(const cid of ids){wanted.add(cid);if(!charts[cid]&&!queue.includes(cid))queue.push(cid)}pump()}
 function retryChart(id){delete charts[id];for(const k of cache.keys())if(k.endsWith('|'+id))cache.delete(k);want([id])}
 async function loadPending(){for(const cid of Object.keys(charts))if(charts[cid]?.status==='queued'){delete charts[cid];queue.push(cid)}pump()}
 function pump(){if(manifest.value?.status!=='ready'||!active.value)return
  while(loading<3&&queue.length){const cid=queue.shift(),g=generation,id=sid(),isCohort=cohortIds.has(cid),key=isCohort?cohortKey.value:'',version=manifest.value.artifact_version,ck=[id,version,key,cid].join('|');const hit=cache.get(ck)
   if(hit){charts[cid]=hit;continue}loading++
   integrationGet(id,`charts/${cid}/`,params(),controller.signal).then(r=>{if(valid(g,id)&&(!isCohort||key===cohortKey.value)&&version===manifest.value?.artifact_version){charts[cid]=r;if(r.status!=='queued'){cache.set(ck,r);if(cache.size>80)cache.delete(cache.keys().next().value)}}}).catch(e=>{if(valid(g,id)){if([409,410].includes(e?.response?.status)){cancel();refresh()}else charts[cid]={id:cid,status:'failed',reason:e?.response?.data?.error?.message||e.message}}}).finally(()=>{if(g===generation){loading--;pump()}})
  }
 }
 async function selectCohort(ids){const id=sid();cancel();const g=generation;error.value='';cohort.value=null
  for(const cid of ['OV01','CX14','CX15','CX16','XS01'])delete charts[cid]
  try{const r=await integrationPost(id,'cohort/',{species_ids:ids},controller.signal);if(!valid(g,id))return
   if(r.cohort_key&&!r.task_kind){customRequest=null;cohortTask.value=null;cohortKey.value=r.cohort_key;cohort.value=r;want([...wanted,...cohortIds])}
   else{cohortKey.value='';customRequest=r;cohortTask.value=r;want([...wanted].filter(k=>!cohortIds.has(k)));later(()=>pollCustom(r))}
  }catch(e){if(valid(g,id))error.value=e.message}
 }
 async function pollCustom(task){const g=generation,id=sid();try{const result=await integrationGet(id,`requests/${task.request_id}/`,{},controller.signal);if(!valid(g,id))return;cohortTask.value=result;if(result.status==='ready'){customRequest=null;cohortTask.value=null;cohortKey.value=result.cohort_key;await loadCohort();want([...wanted,...cohortIds])}else if(['failed','interrupted'].includes(result.status)){error.value=result.reason||result.status;customRequest=null}else later(()=>pollCustom(task))}catch(e){if(valid(g,id)){error.value=e.message;customRequest=null}}}
 watch(speciesId,()=>{cancel();customRequest=null;cohortTask.value=null;wanted.clear();manifest.value=null;cohort.value=null;cohortKey.value='';for(const k of Object.keys(charts))delete charts[k];cache.clear();if(active.value)refresh()},{immediate:true})
 watch(active,v=>{cancel();if(v)refresh()})
 onBeforeUnmount(()=>{disposed=true;cancel()})
 async function get(path,p={}){try{return await integrationGet(sid(),path,{...params(),...p},controller.signal)}catch(e){if(active.value&&[409,410].includes(e?.response?.status)){cancel();refresh()}throw e}}
 return {manifest,charts,cohort,cohortTask,cohortKey,status,error,busy,refresh,want,retryChart,selectCohort,params,get}
}
