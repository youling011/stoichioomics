import client from './client'
export const listCases = () => client.get('/registry/cases/').then(r => r.data.data)
export const promoteJob = (jobId, label, tags=[]) => client.post('/registry/promote/', { job_id: jobId, label, tags }).then(r => r.data.data)
export const compareCases = (caseIds) => client.post('/registry/compare/', { case_ids: caseIds }).then(r => r.data.data.rows)
