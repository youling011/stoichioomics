import client from './client'
import {sharedManifest} from './sharedManifest'
const root=id=>`/stoichdb/species/${encodeURIComponent(id)}/proteome/visualizations/`
export const getProteomeManifest=(id,params={},config={})=>sharedManifest(root(id),params,config).then(r=>r.data.data)
export const ensureProteomeVisuals=(id,data={},config={})=>client.post(`${root(id)}ensure/`,data,config).then(r=>r.data.data)
export const getProteomeRequest=(id,key,config={})=>client.get(`${root(id)}requests/${key}/`,config).then(r=>r.data.data)
export const getProteomeChart=(id,chart,params={},config={})=>client.get(`${root(id)}charts/${chart}/`,{...config,params}).then(r=>r.data.data)
export const getProteomeFields=(id,params={},config={})=>client.get(`${root(id)}fields/`,{...config,params}).then(r=>r.data.data)
export const getProteomePair=(id,params={},config={})=>client.get(`${root(id)}pair/`,{...config,params}).then(r=>r.data.data)
export const getProteomeMembers=(id,params={},config={})=>client.get(`${root(id)}members/`,{...config,params}).then(r=>r.data.data)
export const getProteomeStructure=(id,params={},config={})=>client.get(`${root(id)}structure/`,{...config,params}).then(r=>r.data.data)
export const getProteomeCohort=(id,params={},config={})=>client.get(`${root(id)}cohort/`,{...config,params}).then(r=>r.data.data)
export const getProteomeCandidates=(id,params={},config={})=>client.get(`${root(id)}candidates/`,{...config,params}).then(r=>r.data.data)
export function proteomeExportUrl(id,params={}){const query={...params};if(query.format){query.file_format=query.format;delete query.format}return `/api${root(id)}export/?${new URLSearchParams(query)}`}
