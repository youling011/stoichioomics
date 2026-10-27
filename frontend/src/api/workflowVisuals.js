import client from './client'
import {authConfig} from './jobAuth'
export const workflowVisualsEnabled=import.meta.env?.VITE_WORKFLOW_VISUALS_V2!=='0'&&import.meta.env?.VITE_WORKFLOW_VISUALS_V2!=='false'
export const visualBase=(resource,id)=>resource==='sequence'?'/sequence-analysis/jobs/'+encodeURIComponent(id)+'/visuals/':'/hvg/'+encodeURIComponent(id)+'/visuals/'
const config=(resource,id)=>resource==='hvg'?authConfig(id):{}
export const getWorkflowCapabilities=(resource,id,signal)=>client.get(visualBase(resource,id),{...config(resource,id),signal}).then(r=>r.data.data)
export const getWorkflowVisual=(resource,id,chart,params={},signal)=>client.get(visualBase(resource,id)+chart+'/',{...config(resource,id),params,signal}).then(r=>r.data.data)
export const getWorkflowRecords=(resource,id,chart,params={},signal)=>client.get(visualBase(resource,id)+chart+'/records/',{...config(resource,id),params,signal}).then(r=>r.data.data)
export async function exportWorkflowVisual(resource,id,chart,params={},signal){
 const response=await client.get(visualBase(resource,id)+chart+'/export/',{...config(resource,id),params,signal,responseType:'blob'})
 const url=URL.createObjectURL(response.data),a=document.createElement('a');a.href=url;a.download=chart+'_'+(params.export_scope||'plot')+'.'+(params.format||'csv');a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)
}
