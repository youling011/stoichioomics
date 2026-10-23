export default async function setup(){
  const base=process.env.PROTEOME_FRONTEND_URL||'http://127.0.0.1:5177'
  if(!['127.0.0.1','localhost'].includes(new URL(base).hostname))throw new Error('Proteome verification requires an explicitly local read-only instance')
  let last=''
  for(let i=0;i<150;i++){
    try{const response=await fetch(`${base}/api/stoichdb/species/saccharomyces_cerevisiae/proteome/visualizations/`,{signal:AbortSignal.timeout(2000)});if(response.ok){const body=await response.json();if(body.data?.readiness==='ready')return}last=`HTTP ${response.status}`}catch(e){last=e.message}
    await new Promise(r=>setTimeout(r,2000))
  }
  throw new Error(`Verification servers did not become ready: ${last}`)
}
