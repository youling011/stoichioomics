import client from './client'
const base = '/stoichdb/compare/core'
const unwrap = response => response.data.data
export const compareCatalog = () => client.get(`${base}/catalog/`).then(unwrap)
export const compareSpecies = params => client.get(`${base}/species/`, { params }).then(unwrap)
export const createCompare = payload => client.post(`${base}/runs/`, payload).then(unwrap)
export const compareStatus = id => client.get(`${base}/runs/${id}/`).then(unwrap)
export const compareResult = id => client.get(`${base}/runs/${id}/result/`).then(unwrap)
export const compareTable = (id, params) => client.get(`${base}/runs/${id}/table/`, { params }).then(unwrap)
export const compareDistribution = (id, params) => client.get(`${base}/runs/${id}/distribution/`, { params }).then(unwrap)
export const cancelCompare = id => client.post(`${base}/runs/${id}/cancel/`).then(unwrap)
export const resumeCompare = id => client.post(`${base}/runs/${id}/resume/`).then(unwrap)
export const compareDownload = (id, kind = 'bundle') => `/api${base}/runs/${id}/download/?kind=${encodeURIComponent(kind)}`
