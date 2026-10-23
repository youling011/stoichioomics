export const tokenKey = jobId => `stoich_job_token_${jobId}`
export const authConfig = jobId => { const token = localStorage.getItem(tokenKey(jobId)); return token ? { headers: { 'X-Job-Token': token } } : {} }
