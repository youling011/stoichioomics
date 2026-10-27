// Shared rendering profiles make equivalence inspectable rather than title-based.
export function modelPreviewPackets(payload){
 const p=payload?.plots?.[0]||{},m=payload?.model?.[0]||{},t=payload?.tables||{},out={}
 const finite=(r,...keys)=>keys.every(k=>typeof r[k]==='number'&&Number.isFinite(r[k]))
 const packet=(kind,rows,chart_type,meta={})=>{if(rows.length)out[kind]={kind,rows,chart_type,origin:'original_workflow',context_id:'global',analysis_run_id:payload.analysis_run_id,...meta}}
 packet('original_classes',(p.class_bar||[]).filter(r=>finite(r,'count')).map(r=>({...r,label:r.stoich_class,value:r.count})),'bar',{value:'value',unit:'Genes',interaction:'class_to_gene_filter'})
 packet('original_expected_observed',(p.expected_observed_scatter||[]).filter(r=>finite(r,'stoich_expected_var','observed_hvg_signal')),'original_scatter',{x:'stoich_expected_var',y:'observed_hvg_signal',x_label:'Expected HVG signal',y_label:'Observed HVG signal',identity_line:true})
 const residual=(p.residual_scatter||[]).filter(r=>finite(r,'stoich_excess_var')).map(r=>r.stoich_excess_var)
 if(residual.length){const low=Math.min(...residual),high=Math.max(...residual);const min=high===low?low-.5:low,max=high===low?high+.5:high,width=(max-min)/24,bins=Array(24).fill(0);residual.forEach(v=>bins[Math.min(23,Math.max(0,Math.floor((v-min)/width)))]++);packet('original_residuals',bins.map((v,i)=>({label:min+(i+.5)*width,value:v,bin_left:min+i*width,bin_right:min+(i+1)*width})),'original_histogram',{x_label:'Prediction residual'})}
 packet('original_model_associations',(p.feature_association_top||[]).filter(r=>finite(r,'cliffs_delta')).map(r=>({...r,label:r.feature||r.feature_key,value:r.cliffs_delta})),'bar',{value:'value',unit:"Model-branch Cliff's delta"})
 for(const [key,kind,metrics] of [['model_comparison','original_model_comparison',['cv_r2','r2','roc_auc','mae','rmse','mean_score']],['bootstrap_feature_stability','original_bootstrap',['selection_frequency','mean_abs_importance','sign_stability','frequency','stability']]]){
  const rows=t[key]||m[key]||[],metric=metrics.find(k=>rows.some(r=>finite(r,k)))
  if(metric)packet(kind,rows.filter(r=>finite(r,metric)).map(r=>({...r,label:r.model_id||r.model||r.feature||r.feature_key||r.model_name,value:r[metric]})),'bar',{value:'value',unit:metric})
 }
 return out
}
const canonical=v=>Array.isArray(v)?v.map(canonical):v&&typeof v==='object'?Object.fromEntries(Object.keys(v).sort().map(k=>[k,canonical(v[k])])):v
export function equivalentPackets(a,b){
 if(b?.schema_version==='workflow_viz_v2')return coveredByCompleteEvidence(a,b)
 if(!a?.rows?.length||!b?.rows?.length||!a.analysis_run_id||a.analysis_run_id!==b.analysis_run_id)return false
 const profile=p=>({analysis_run_id:p.analysis_run_id,kind:p.kind,chart_type:p.chart_type,x:p.x,y:p.y,value:p.value,unit:p.unit,identity_line:!!p.identity_line,interaction:p.interaction,x_label:p.x_label,y_label:p.y_label,context_id:p.context_id||'global',rows:p.rows})
 // Entire ordered rows (including tooltip/source statistics), coordinates, units,
 // identity line and navigation profile must match. No rounded-value comparison.
 return JSON.stringify(canonical(profile(a)))===JSON.stringify(canonical(profile(b)))
}
// A preview can be folded only when every saved field/value is represented by
// the same run/global scientific view. Unknown geometry remains independently
// available. No title matching or rounded-value comparisons are accepted.
export function coveredByCompleteEvidence(a,b){
 if(!a?.rows?.length||b?.design_revision!==3||!a.analysis_run_id||a.analysis_run_id!==b.analysis_run_id||(a.context_id||'global')!==(b.context_id||'global'))return false
 const panels=b.data?.panels||[],kind=a.kind,allowed={original_model_associations:'effect_lollipop',original_bootstrap:'scatter',original_model_comparison:'model_curve',original_classes:'categories'}
 const panel=panels.find(p=>p.type===allowed[kind]);if(!panel)return false
 if(kind==='original_classes')return a.rows.every(r=>panel.rows.some(s=>s.category===r.stoich_class&&s.count===r.count))&&a.rows.reduce((n,r)=>n+r.count,0)===panel.rows.reduce((n,r)=>n+r.count,0)
 // Scatter packets do not contain complete raw rows: their exact-member
 // endpoint remains available, but cannot establish a synchronous proof here.
 const rows=panel.rows;if(!rows?.length)return false
 const drop=new Set(['label','value'])
 return a.rows.every(r=>rows.some(s=>Object.keys(r).filter(k=>!drop.has(k)).every(k=>Object.hasOwn(s,k)&&JSON.stringify(canonical(s[k]))===JSON.stringify(canonical(r[k])))))
}
