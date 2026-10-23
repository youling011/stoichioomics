"""Isolated, cancellable scientific workers; no persistent global per-job state."""
import os,sys,importlib
from pathlib import Path
ALLOWED={'feature_analysis','pathway_analysis','gsea','stability','candidates','supplementary'}
def main():
 stage,folder=sys.argv[1:3]
 if stage not in ALLOWED:raise ValueError('Invalid research stage')
 os.environ['HVG_RESEARCH_CONTEXT_ROOT']=str(Path(folder).resolve());os.environ['PYTHONDONTWRITEBYTECODE']='1'
 from .process_guard import watch_owner
 watch_owner()
 import pandas as pd,json,numpy as np
 root=Path(folder);reason=None
 if stage=='feature_analysis':
  x=pd.read_parquet(root/'core/context.parquet');L=pd.read_parquet(root/'labels/hvg_labels.parquet')
  if min(int(L.is_hvg.sum()),int((~L.is_hvg).sum()))<json.loads((root/'research_config.json').read_text(encoding='utf-8'))['core']['min_group_n']:reason='insufficient_group_n'
  columns=[c for c in x if '__' in c]
  if not any(pd.to_numeric(x[c],errors='coerce').notna().any() for c in columns):reason='source_missing'
 elif stage in ALLOWED:
  p=root/'features/feature_values.parquet'
  if p.is_file() and len(pd.read_parquet(p).columns)<=1:
   state=root/'reports/feature_analysis_unavailable.json'
   reason=json.loads(state.read_text(encoding='utf-8')).get('reason','source_missing') if state.exists() else 'source_missing'
 if reason:
  from .empty_results import empty_stage
  empty_stage(root,stage,reason)
 else:importlib.import_module('backend.analysis_engine.hvg_research.'+stage)
if __name__=='__main__':main()
