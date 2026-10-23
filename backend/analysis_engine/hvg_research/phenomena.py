"""Structured observations grounded in actual full-family statistics and members."""
import pandas as pd
from .artifacts import content_hash,clean
from .catalog import TABLES
def functional_phenomena(run,alpha=.05):
 def table(key):
  p=run/(TABLES[key]+'.parquet');return pd.read_parquet(p) if p.exists() else pd.DataFrame()
 A=table('annotations');S=table('set_members');L=table('labels');E=table('features');results=[]
 for kind in ['baseline','subset','within_hvg','within_pathways']:
  data=table(kind)
  if 'q_global' not in data:continue
  for r in data[data.q_global.lt(alpha)].sort_values('q_global').head(20).to_dict('records'):
   cid=r.get('context_id','global');ann=A[(A.context_id==cid)&(A.term_key==r['term_key'])];genes=set(ann.gene_id)
   feature=r.get('feature_key');setid=r.get('set_id');support='functional_association';limits=['Annotation coverage limits interpretation','No independent external validation','Association does not establish a mechanism']
   if kind=='baseline':
    h=set(L.loc[(L.context_id==cid)&L.is_hvg,'gene_id']);genes&=h;observation='Baseline HVGs are enriched for this function in the declared annotated universe'
   elif kind in ['subset','within_hvg']:
    genes&=set(S.loc[(S.context_id==cid)&S.set_id.eq(setid),'gene_id']);observation='This directional feature subset is enriched for this function within HVGs' if kind=='within_hvg' else 'This directional HVG subset is enriched for this function against the shared universe'
    e=E[(E.context_id==cid)&E.feature_key.eq(feature)];strong=bool(len(e) and e.iloc[0].strong_raw and (('high' if e.iloc[0].effect>0 else 'low')==r.get('direction')))
    support='strong_feature_and_function' if strong else 'supplementary_functional_stratification';limits.append('Does not establish HVG-specific interaction; compare F8 separately')
   else:
    genes&=set(L.loc[(L.context_id==cid)&L.is_hvg,'gene_id']);observation='A raw HVG/non-HVG feature difference remains within this functional category';limits.append('Raw within-category effect; inspect adjusted and interaction results separately')
   results.append({'phenomenon_id':content_hash([cid,kind,feature,setid,r['term_key']]),'context_id':cid,'feature_key':feature,'term_key':r['term_key'],'term_name':r.get('term_name'),'source':r.get('source'),'set_id':setid,'background_id':r.get('background_id'),'family_id':r.get('family_id',kind),'observation':observation,'effect':r.get('effect',r.get('fold_enrichment')),'effect_type':'cliffs_delta' if kind=='within_pathways' else 'fold_enrichment','q_global':r['q_global'],'counts':{x:r.get(x) for x in ['N','K','n','k','n1','n0']},'genes':sorted(genes),'support_level':support,'statistical_level':'feature or set/term; not gene significance','validation_status':'no independent external replication','alternatives':['length/expression/detection confounding','cell composition','overlapping annotations'],'limitations':limits,'source_table':TABLES[kind]})
 return clean(results)
