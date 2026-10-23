import client from './client'
const root=(id,omics)=>`/stoichdb/species/${encodeURIComponent(id)}/${omics}/visualizations/`
export const sequenceGet=(id,omics,path='',params={},config={})=>client.get(root(id,omics)+path,{...config,params}).then(r=>r.data.data)
export const sequenceEnsure=(id,omics,scope,config={})=>client.post(root(id,omics)+'ensure/',{scope},config).then(r=>r.data.data)
export const sequenceExport=(id,omics,params={})=>`/api${root(id,omics)}export/?${new URLSearchParams(params)}`
