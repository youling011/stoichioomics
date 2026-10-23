import client from './client'
import {authConfig} from './jobAuth'
const base=id=>`/hvg/${encodeURIComponent(id)}/research/`
export const researchGet=(id,endpoint,params={},options={})=>client.get(base(id)+endpoint+'/',{...authConfig(id),params,signal:options.signal}).then(r=>r.data.data)
export const researchControl=(id,action,payload={})=>client.post(base(id)+action+'/',payload,authConfig(id)).then(r=>r.data.data)
const save=(blob,name)=>{const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
export const researchDownload=async(id,artifact,params={})=>{const r=await client.get(base(id)+'download/'+artifact.artifact_id+'/',{...authConfig(id),params,responseType:'blob'});save(r.data,String(artifact.name||'research_file').replace('结果总览.html','results_overview.html'))}
export const researchSafeExport=async(id,table,params={})=>{const r=await client.get(base(id)+'safe-export/'+encodeURIComponent(table)+'/',{...authConfig(id),params,responseType:'blob'});save(r.data,table+'_spreadsheet_safe.csv')}
