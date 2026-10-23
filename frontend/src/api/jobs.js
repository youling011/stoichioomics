import client from './client'
import {tokenKey,authConfig} from './jobAuth'
export const listJobs = () => client.get('/jobs/').then(r => r.data.data)
export const createJob = (payload) => client.post('/jobs/', payload).then(r => {
  const data = r.data.data
  if (data?.job_id && data?.access_token) localStorage.setItem(tokenKey(data.job_id), data.access_token)
  return data
})
export const getJob = (jobId) => client.get(`/jobs/${jobId}/`).then(r => r.data.data)
export const uploadJobFiles = (jobId, files) => {
  const form = new FormData()
  files.forEach(f => form.append('files', f))
  return client.post(`/jobs/${jobId}/upload/`, form, authConfig(jobId)).then(r => r.data.data)
}
export const configureJob = (jobId, payload) => client.post(`/jobs/${jobId}/configure/`, payload, authConfig(jobId)).then(r => r.data.data)
export const autoconfigureJob = (jobId, payload={}) => client.post(`/jobs/${jobId}/autoconfigure/`, payload, authConfig(jobId)).then(r => r.data.data)
export const confirmJobConfig = (jobId, payload={}) => client.post(`/jobs/${jobId}/confirm-config/`, payload, authConfig(jobId)).then(r => r.data.data)
export const preflightJob = (jobId) => client.post(`/jobs/${jobId}/preflight/`).then(r => r.data.data)
export const runJob = (jobId) => client.post(`/jobs/${jobId}/run/`, {}, authConfig(jobId)).then(r => r.data.data)
export const cancelJob = (jobId) => client.post(`/jobs/${jobId}/cancel/`, {}, authConfig(jobId)).then(r => r.data.data)
export const getJobLogs = (jobId, params = {}) => client.get(`/jobs/${jobId}/logs/`, { params }).then(r => r.data.data)
export const getJobReproducibility = (jobId) => client.get(`/jobs/${jobId}/reproducibility/`).then(r => r.data.data)
