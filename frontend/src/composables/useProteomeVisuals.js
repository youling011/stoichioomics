import {visibleChartQueue} from './visibleChartQueue'
import {ref,reactive,watch,onBeforeUnmount} from 'vue'
import {getProteomeManifest,getProteomeChart,ensureProteomeVisuals,getProteomeRequest} from '../api/proteomeVisuals'

const cache=new Map()
function save(key,value){cache.delete(key);cache.set(key,value);while(cache.size>48)cache.delete(cache.keys().next().value)}
export function useProteomeVisuals(props){
  const manifest=ref(null),states=reactive({}),error=ref(''),loading=ref(false);let controller,sequence=0,timer
  async function reload(){
    const seq=++sequence;clearTimeout(timer);controller?.abort();controller=new AbortController();const signal=controller.signal;loading.value=true;error.value='';manifest.value=null
    Object.keys(states).forEach(k=>delete states[k])
    try{
      const m=await getProteomeManifest(props.speciesId,{scope:props.scope},{signal});if(seq!==sequence)return;manifest.value=m
      if(m.readiness!=='ready'){
        if(m.reason_code==='full_not_registered')return
        const job=await ensureProteomeVisuals(props.speciesId,{scope:props.scope},{signal});if(seq!==sequence)return
        manifest.value={...m,readiness:job.readiness,reason_code:job.reason_code,request_id:job.request_id}
        if(job.readiness==='ready'){reload();return}
        if(job.request_id&&['queued','running','interrupted'].includes(job.readiness)){
          let resumed=false
          const poll=async()=>{try{const state=await getProteomeRequest(props.speciesId,job.request_id,{signal});if(seq!==sequence)return;if(state.readiness==='ready'){reload();return}manifest.value={...manifest.value,readiness:state.readiness,calculation_error:state.error||state.result?.error};if(state.readiness==='interrupted'){if(resumed){manifest.value={...manifest.value,readiness:'failed',calculation_error:'The worker was interrupted again. Retry when resources are available.'};return}resumed=true;await ensureProteomeVisuals(props.speciesId,{scope:props.scope},{signal})}if(['queued','running','interrupted'].includes(state.readiness))timer=setTimeout(poll,1500)}catch(e){if(seq===sequence&&!signal.aborted)error.value=e.message}}
          timer=setTimeout(poll,1500)
        }
        return
      }
      const ids=props.section==='basic'?[...Array.from({length:12},(_,i)=>`B${String(i+1).padStart(2,'0')}`),'B15','D14']:Array.from({length:16},(_,i)=>`D${String(i+1).padStart(2,'0')}`).filter(id=>!['D11','D12','D16'].includes(id))
      ids.forEach(id=>{states[id]={loading:true,error:'',result:null}})
      const load=async(id)=>{
          const canonical=id==='B10'?'D02':id,key=[props.speciesId,props.scope,m.release_id,m.method_version,m.source_hash,m.artifact_version,canonical].join('::')
          try{const r=cache.get(key)||await getProteomeChart(props.speciesId,canonical,{scope:props.scope,artifact_version:m.artifact_version,source_hash:m.source_hash},{signal});if(seq!==sequence)return;save(key,r);states[id]={loading:false,error:'',result:r.result,readiness:r.readiness}}
          catch(e){if(seq===sequence&&!signal.aborted)states[id]={loading:false,error:e?.response?.data?.error?.message||e.message,result:null}}
      }
      await visibleChartQueue(ids,load,signal,`[data-testid="proteome-v3"][data-species-id="${CSS.escape(props.speciesId)}"]`)
    }catch(e){if(seq===sequence&&!signal.aborted)error.value=e?.response?.data?.error?.message||e.message}
    finally{if(seq===sequence)loading.value=false}
  }
  watch(()=>[props.speciesId,props.scope,props.section],reload,{immediate:true})
  onBeforeUnmount(()=>{sequence++;clearTimeout(timer);controller?.abort()})
  return {manifest,states,error,loading,reload}
}
