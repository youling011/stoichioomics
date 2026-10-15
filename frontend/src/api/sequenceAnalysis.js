import client from './client'

export const createSequenceAnalysisJob = (payload) => client.post('/sequence-analysis/jobs/', payload).then(r => r.data.data)
export const listSequenceAnalysisJobs = () => client.get('/sequence-analysis/jobs/').then(r => r.data.data)
export const getSequenceAnalysisJob = (jobId) => client.get(`/sequence-analysis/jobs/${jobId}/`).then(r => r.data.data)
export const getSequenceAnalysisLogs = (jobId, params = {}) => client.get(`/sequence-analysis/jobs/${jobId}/logs/`, { params }).then(r => r.data.data)
export const getSequenceAnalysisReproducibility = (jobId) => client.get(`/sequence-analysis/jobs/${jobId}/reproducibility/`).then(r => r.data.data)
export const prevalidateSequenceAnalysisJob = (payload) => client.post('/sequence-analysis/prevalidate/', payload).then(r => r.data.data)
export const sequenceSampleSheetTemplateUrl = (analysisType = 'multi_sample', omicsType = 'transcriptome') => `/api/sequence-analysis/sample-sheet-template/?analysis_type=${encodeURIComponent(analysisType)}&omics_type=${encodeURIComponent(omicsType)}`
export const getSequenceJobManifest = (jobId) => client.get(`/sequence-analysis/jobs/${jobId}/job-manifest/`).then(r => r.data.data)
export const getSequenceInputQc = (jobId) => client.get(`/sequence-analysis/jobs/${jobId}/input-qc/`).then(r => r.data.data)
export const getSequenceAnalysisDesign = (jobId) => client.get(`/sequence-analysis/jobs/${jobId}/analysis-design/`).then(r => r.data.data)
export const getSequenceResultInterpretation = (jobId) => client.get(`/sequence-analysis/jobs/${jobId}/result-interpretation/`).then(r => r.data.data)
export const getSequenceDownloadManifest = (jobId) => client.get(`/sequence-analysis/jobs/${jobId}/download-manifest/`).then(r => r.data.data)
export const getSequenceFeatures = (jobId, params = {}) => client.get(`/sequence-analysis/jobs/${jobId}/features/`, { params }).then(r => r.data.data)
export const getDifferentialFeatures = (jobId, params = {}) => client.get(`/sequence-analysis/jobs/${jobId}/differential-features/`, { params }).then(r => r.data.data)
export const getDifferentialEntities = (jobId, params = {}) => client.get(`/sequence-analysis/jobs/${jobId}/differential-entities/`, { params }).then(r => r.data.data)
export const getSequencePlots = (jobId) => client.get(`/sequence-analysis/jobs/${jobId}/plots/`).then(r => r.data.data)
export const getSequencePlatformBundle = (jobId) => client.get(`/sequence-analysis/jobs/${jobId}/platform/`).then(r => r.data.data)
export const getSequenceAnalysisPayload = (jobId) => client.get(`/sequence-analysis/jobs/${jobId}/analysis/`).then(r => r.data.data)
export const getSequenceFeatureCatalog = (jobId) => client.get(`/sequence-analysis/jobs/${jobId}/feature-catalog/`).then(r => r.data.data)
export const getSequenceFeatureSummary = (jobId, params = {}) => client.get(`/sequence-analysis/jobs/${jobId}/feature-summary/`, { params }).then(r => r.data.data)
export const getSequenceBasicVisualization = (jobId) => client.get(`/sequence-analysis/jobs/${jobId}/basic-visualization/`).then(r => r.data.data)
export const getSequenceCoreFeaturePanels = (jobId, params = {}) => client.get(`/sequence-analysis/jobs/${jobId}/core-feature-panels/`, { params }).then(r => r.data.data)
export const getSequenceTopLow = (jobId, params = {}) => client.get(`/sequence-analysis/jobs/${jobId}/top-low/`, { params }).then(r => r.data.data)
export const getSequenceSampleComparison = (jobId) => client.get(`/sequence-analysis/jobs/${jobId}/comparison/sample/`).then(r => r.data.data)
export const getSequenceMlDiscrimination = (jobId, payload = null) => payload
  ? client.post(`/sequence-analysis/jobs/${jobId}/ml-discrimination/`, payload).then(r => r.data.data)
  : client.get(`/sequence-analysis/jobs/${jobId}/ml-discrimination/`).then(r => r.data.data)
export const getSequenceFieldSummary = (jobId, params = {}) => client.get(`/sequence-analysis/jobs/${jobId}/field-summary/`, { params }).then(r => r.data.data)
export const getSequenceScatter = (jobId, params = {}) => client.get(`/sequence-analysis/jobs/${jobId}/scatter/`, { params }).then(r => r.data.data)
export const getSequenceFeatureComparison = (jobId, params = {}) => client.get(`/sequence-analysis/jobs/${jobId}/comparison/feature/`, { params }).then(r => r.data.data)
export const getSequenceEntityComparison = (jobId, params = {}) => client.get(`/sequence-analysis/jobs/${jobId}/comparison/entities/`, { params }).then(r => r.data.data)
export const sequenceDownloadUrl = (jobId, kind) => `/api/sequence-analysis/jobs/${encodeURIComponent(jobId)}/download/${encodeURIComponent(kind)}/`
export const sequenceTableExportUrl = (jobId, kind, params = {}) => {
  const query = new URLSearchParams()
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && String(value) !== '') query.set(key, String(value))
  })
  const suffix = query.toString() ? `?${query.toString()}` : ''
  return `/api/sequence-analysis/jobs/${encodeURIComponent(jobId)}/table-export/${encodeURIComponent(kind)}/${suffix}`
}
