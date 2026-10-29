import {visibleChartQueue} from './visibleChartQueue'
import {ref,reactive,watch,onBeforeUnmount} from 'vue'
import {sequenceGet,sequenceEnsure} from '../api/sequenceVisuals'
const cache=new Map()
export function useSequenceVisuals(props){
  const manifest=ref(null),states=reactive({}),error=ref('');let seq=0,controller,timer
  async function reload(){
    const current=++seq;clearTimeout(timer);controller?.abort();controller=new AbortController();const signal=controller.signal;error.value='';manifest.value=null;Object.keys(states).forEach(k=>delete states[k]);const context=[props.speciesId,props.omics,props.scope,props.section]
    try{
      const m=await sequenceGet(context[0],context[1],'',{scope:context[2]},{signal});if(seq!==current)return;manifest.value=m
      if(m.readiness!=='ready'){
        if(m.readiness==='unavailable'||m.enabled===false)return
        const job=await sequenceEnsure(context[0],context[1],context[2],{signal});if(seq!==current)return;manifest.value={...m,...job}
        if(job.readiness==='ready'){reload();return}
        let retries=0
        async function poll(){try{const r=await sequenceGet(context[0],context[1],`requests/${job.request_id}/`,{},{signal});if(current!==seq)return;manifest.value={...manifest.value,...r};if(r.readiness==='ready'){reload();return}if(r.readiness==='interrupted'&&retries++<1)await sequenceEnsure(context[0],context[1],context[2],{signal});if(['queued','running','interrupted'].includes(r.readiness))timer=setTimeout(poll,1500)}catch(e){if(current===seq&&!signal.aborted)error.value=e.message}}
        if(job.request_id)timer=setTimeout(poll,1500);return
      }
      const ids=m.charts.filter(c=>(c.section===context[3]||(context[3]==='deep'&&c.chart_id.includes('S')))&&!['species_fingerprint_pca','species_distance','species_dispersion'].includes(c.kind)).map(c=>c.chart_id);ids.forEach(id=>states[id]={loading:true});
      async function load(id){const key=[...context,m.release_id,m.source_hash,m.method_version,m.artifact_version,id].join('::');try{const r=cache.get(key)||await sequenceGet(context[0],context[1],`charts/${id}/`,{scope:context[2],artifact_version:m.artifact_version,source_hash:m.source_hash},{signal});if(current!==seq)return;if(!r.result?.data?.cohort){cache.set(key,r);while(cache.size>80)cache.delete(cache.keys().next().value)}states[id]={loading:false,result:r.result,error:''}}catch(e){if(current===seq&&!signal.aborted)states[id]={loading:false,error:e?.response?.data?.error?.message||e.message}}}
      await visibleChartQueue(ids,load,signal,`[data-testid="sequence-v1"][data-species-id="${CSS.escape(context[0])}"][data-omics="${context[1]}"]`)
    }catch(e){if(current===seq&&!signal.aborted)error.value=e?.response?.data?.error?.message||e.message}
  }
  watch(()=>[props.speciesId,props.omics,props.scope,props.section],reload,{immediate:true});onBeforeUnmount(()=>{seq++;clearTimeout(timer);controller?.abort()});return {manifest,states,error,reload}
}
