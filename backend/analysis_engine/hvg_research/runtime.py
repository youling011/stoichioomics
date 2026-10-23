import os,sys,json,hashlib,time,warnings
from pathlib import Path
import numpy as np,pandas as pd
from scipy import stats,sparse
from .statistics import *
from .statistics import rank_test as _rank_test
from .artifacts import atomic_json,atomic_frame,digest,member_hash,content_hash
ROOT=Path(os.environ['HVG_RESEARCH_CONTEXT_ROOT'])
CFG=json.loads((ROOT/'research_config.json').read_text(encoding='utf-8'))
DESIGN=json.loads((ROOT/'design.json').read_text(encoding='utf-8'))
SEED=CFG['validation']['seed'];MIN_N=CFG['core']['min_group_n'];ALPHA=CFG['feature_tests']['alpha'];MIN_DELTA=CFG['feature_tests']['minimum_abs_cliffs_delta'];CI_REPEATS=CFG['feature_tests']['ci_repeats']
LOW_Q=CFG['gene_sets']['low_quantile'];HIGH_Q=CFG['gene_sets']['high_quantile'];MIN_QUERY=CFG['gene_sets']['min_annotated_query'];TERM_MIN=CFG['enrichment']['min_term_size'];TERM_MAX=CFG['enrichment']['max_term_size']
N_PERM=CFG['pathway']['gsea_permutations']
def check_cancel():
 if (ROOT/'cancel_requested.json').exists() or (ROOT.parents[1]/'cancel_requested.json').exists():raise InterruptedError('research cancelled')
def log(*args):
 check_cancel();print(time.strftime('%H:%M:%S'),*args,flush=True)
def sha(path):return digest(path)
def set_hash(ids):return member_hash(ids)
def write_json(relative,obj):check_cancel();atomic_json(ROOT/relative,obj)
def read_json(relative):return json.loads((ROOT/relative).read_text(encoding='utf-8'))
def save(relative,frame,csv=True):
 check_cancel()
 if not isinstance(frame,pd.DataFrame):frame=pd.DataFrame(frame)
 atomic_frame((ROOT/relative).with_suffix('.parquet'),frame)
 if csv:
  p=(ROOT/relative).with_suffix('.csv.gz');tmp=p.with_name('.'+p.name+'.tmp');frame.to_csv(tmp,index=False,encoding='utf-8-sig',compression='gzip');os.replace(tmp,p)
 return frame
def load(relative):return pd.read_parquet((ROOT/relative).with_suffix('.parquet'))
def rank_test(x,y,boot=False,seed=None):
 check_cancel();return _rank_test(x,y,boot=boot,seed=SEED if seed is None else seed,min_group_n=MIN_N,repeats=CI_REPEATS)
def zscore(x):
 x=np.asarray(x,float)
 if not np.isfinite(x).any():return np.full_like(x,np.nan)
 center=np.nanmedian(x) if CFG['preprocessing']['continuous_scaler']=='robust' else np.nanmean(x)
 scale=np.subtract(*np.nanpercentile(x,[75,25])) if CFG['preprocessing']['continuous_scaler']=='robust' else np.nanstd(x)
 if not np.isfinite(scale) or scale<=1e-12*max(np.nanmax(abs(x)),1e-12):scale=np.nanstd(x)
 return (x-center)/scale if scale>0 else np.full_like(x,np.nan)
