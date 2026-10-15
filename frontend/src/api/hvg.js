import client from './client'

export const getHvgSummary = (id) =>
  client.get(`/hvg/${encodeURIComponent(id)}/summary/`).then(r => r.data.data)

export const getHvgPlots = (id) =>
  client.get(`/hvg/${encodeURIComponent(id)}/plots/`).then(r => r.data.data)

export const getHvgPhase2Model = (id) =>
  client.get(`/hvg/${encodeURIComponent(id)}/phase2-model/`).then(r => r.data.data)

export const getHvgGenes = (id, params) =>
  client.get(`/hvg/${encodeURIComponent(id)}/genes/`, { params }).then(r => r.data.data)

export const getHvgGeneDetail = (id, geneId) =>
  client.get(`/hvg/${encodeURIComponent(id)}/genes/${encodeURIComponent(geneId)}/`).then(r => r.data.data)

export const getHvgGroupComparisonSummary = (id) =>
  client.get(`/hvg/${encodeURIComponent(id)}/group-comparison/summary/`).then(r => r.data.data)

export const getHvgGroupComparisonFeatures = (id, params) =>
  client.get(`/hvg/${encodeURIComponent(id)}/group-comparison/features/`, { params }).then(r => r.data.data)

export const getHvgGroupComparisonFeature = (id, featureKey) =>
  client.get(`/hvg/${encodeURIComponent(id)}/group-comparison/features/${encodeURIComponent(featureKey)}/`).then(r => r.data.data)

export const buildHvgDownloadUrl = (id, kind) =>
  `/api/hvg/${encodeURIComponent(id)}/download/${encodeURIComponent(kind)}/`
