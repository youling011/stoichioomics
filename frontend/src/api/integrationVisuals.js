import client from './client'
const root=id=>`/stoichdb/species/${encodeURIComponent(id)}/integration/visualizations/`
export async function integrationGet(id,path='',params={},signal){const r=await client.get(root(id)+path,{params,signal});if(r.data.ok!==true)throw new Error(r.data.error?.message||'Integration request failed');return r.data.data}
export async function integrationPost(id,path,data={},signal){const r=await client.post(root(id)+path,data,{signal});if(r.data.ok!==true)throw new Error(r.data.error?.message||'Integration request failed');return r.data.data}
export function integrationExport(id,params){return '/api'+root(id)+'export/?'+new URLSearchParams(Object.entries(params).filter(([,v])=>v!==undefined&&v!==null)).toString()}
