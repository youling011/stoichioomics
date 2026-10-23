from pathlib import Path
import os,sys,json,argparse
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','backend.config.settings')
import numpy as np,pandas as pd,scipy.stats as stats
from backend.analysis_engine.hvg_research.artifacts import safe_path,digest,atomic_json,member_hash
from backend.analysis_engine.hvg_research.catalog import TABLES,FAMILIES
def validate(run):
 run=Path(run);m=json.loads((run/'run_manifest.json').read_text(encoding='utf-8'));checks=[]
 def check(name,condition,detail=''):
  checks.append({'name':name,'passed':bool(condition),'detail':detail})
 def read(rel):return pd.read_parquet(run/(rel+'.parquet'))
 check('published_terminal',m['status']=='completed');check('required_stages_finished',all(s['execution_status']=='completed' for s in m['stages'].values()))
 for info in m['contexts']:
  ctx=run/info['directory'];L=pd.read_parquet(ctx/'labels/hvg_labels.parquet');H=set(L.loc[L.is_hvg,'gene_id']);N=set(L.loc[~L.is_hvg,'gene_id']);U=set(L.gene_id)
  check(info['context_id']+':U_H_N',L.gene_id.is_unique and not H&N and H|N==U and len(H)==info['H'])
  reg=json.loads((ctx/'core/registry_snapshot.json').read_text(encoding='utf-8'));expected={r['omics']+'::'+r['field'] for r in reg['fields'] if r.get('scope')=='core'};audit=pd.read_parquet(ctx/'core/core_feature_audit.parquet')
  check(info['context_id']+':all_legal_Core',audit.feature_key.is_unique and set(audit.feature_key)==expected)
  check(info['context_id']+':audit_reasons',audit.final_status.notna().all() and audit.loc[~audit.final_status.eq('tested'),'reason'].fillna('').ne('').all())
  import anndata as ad,scanpy as sc
  a=ad.read_h5ad(ctx/'labels/filtered_counts.h5ad');meta=json.loads((ctx/'labels/hvg_method_manifest.json').read_text(encoding='utf-8'));oracle=sc.pp.highly_variable_genes(a,**meta['parameters']);check(info['context_id']+':independent_official_oracle',np.array_equal(oracle.highly_variable,L.is_hvg))
  sets=pd.read_parquet(ctx/'gene_sets/gene_set_members.parquet');check(info['context_id']+':all_sets_subset_H',set(sets.gene_id)<=H)
  C=pd.read_parquet(ctx/'candidates/candidate_genes.parquet');check(info['context_id']+':candidates_unique_H',C.gene_id.is_unique and set(C.gene_id)<=H)
  if (ctx/'features/feature_values.parquet').exists():
   P=pd.read_parquet(ctx/'features/feature_values.parquet');E=pd.read_parquet(ctx/'features/feature_tests.parquet');mask=L.is_hvg.to_numpy(bool)
   for row in E[E.p_value.notna()].head(8).itertuples():
    if row.feature_key not in P or row.effect_type!='cliffs_delta':continue
    v=P[row.feature_key].to_numpy(float);ok=np.isfinite(v);x=v[ok&mask];y=v[ok&~mask];r=stats.mannwhitneyu(x,y,alternative='two-sided',method='asymptotic');d=2*r.statistic/(len(x)*len(y))-1
    check(info['context_id']+':F1_recompute:'+row.feature_key,np.isclose(d,row.effect,atol=1e-12) and np.isclose(r.pvalue,row.p_value,atol=1e-14,rtol=1e-8))
  A=pd.read_parquet(ctx/'annotations/gene_term_membership.parquet');B=pd.read_parquet(ctx/'labels/universe_members.parquet');S=pd.read_parquet(ctx/'gene_sets/gene_set_members.parquet');bg={b:set(f.gene_id) for b,f in B.groupby('background_id')};ss={s:set(f.gene_id) for s,f in S.groupby('set_id')};term={t:set(f.gene_id) for t,f in A.groupby('term_key')}
  for key in ['baseline','subset','within_hvg']:
   tab=pd.read_parquet(ctx/(TABLES[key]+'.parquet'))
   for row in tab[tab.p_value.notna()].head(12).itertuples():
    universe=bg.get(row.background_id,set(A.loc[A.source.eq(row.source),'gene_id']));query=(H if key=='baseline' else ss[row.set_id])&universe;t=term[row.term_key]&universe;vals=(len(universe),len(t),len(query),len(query&t));p=stats.hypergeom.sf(vals[3]-1,*vals[:3]);check(info['context_id']+':ORA_members:'+key+':'+row.term_key,vals==(row.N,row.K,row.n,row.k) and np.isclose(p,row.p_value,rtol=1e-8,atol=1e-14))
 for key,family in FAMILIES.items():
  p=run/(TABLES[key]+'.parquet')
  if not p.exists():continue
  f=pd.read_parquet(p)
  if 'p_value' not in f:continue
  groups=['model'] if key=='adjusted' and 'model' in f else ['family_id'] if key=='supplementary_ora' and 'family_id' in f else []
  for group,part in f.groupby(groups,dropna=False) if groups else [('all',f)]:
   v=part.p_value.to_numpy(float);ok=np.isfinite(v)
   if not ok.any():continue
   expected=stats.false_discovery_control(v[ok],method='bh');check('global_BH:'+key+':'+str(group),np.allclose(expected,part.loc[ok,'q_global'],rtol=1e-10,atol=1e-14));check('p_q_range:'+key,part.loc[ok,'p_value'].between(0,1).all() and part.loc[ok,'q_global'].between(0,1).all())
 gsea=run/'pathway_links/gsea_results.parquet'
 if gsea.exists():
  G=pd.read_parquet(gsea)
  if len(G):check('GSEA_finite_p_from_real_null_tail',np.allclose(G.p_value,(G.raw_tail_count+1)/(G.same_sign_null_count+1)) and G.permutation_num.ge(10).all())
 for a in m.get('artifacts',[]):
  p=safe_path(run,a['path']);check('artifact_SHA256:'+a['artifact_id'],p.is_file() and digest(p)==a['sha256'])
 return {'analysis_run_id':m['analysis_run_id'],'research_status':m['research_status'],'status':'passed' if all(c['passed'] for c in checks) else 'failed','passed':sum(c['passed'] for c in checks),'total':len(checks),'checks':checks}
def main():
 p=argparse.ArgumentParser();p.add_argument('--run-dir',required=True);p.add_argument('--report',required=True);args=p.parse_args();r=validate(args.run_dir);atomic_json(Path(args.report),r);print(json.dumps({k:v for k,v in r.items() if k!='checks'}));raise SystemExit(0 if r['status']=='passed' else 1)
if __name__=='__main__':main()
