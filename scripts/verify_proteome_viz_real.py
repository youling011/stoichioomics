"""Read-only numerical acceptance against complete source files and the Word PCA oracle."""
import argparse,os,sys,json
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.linalg import orthogonal_procrustes
from scipy.stats import rankdata,spearmanr
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','backend.config.settings')
import django;django.setup()
from backend.apps.stoichdb.proteome_viz import artifacts as store
from backend.apps.stoichdb.proteome_viz.source import release_id,read_frame
from backend.apps.stoichdb.proteome_viz.contracts import CORE_FIELDS
from backend.apps.stoichdb.proteome_viz.cohorts import payload
from backend.apps.stoichdb.models import OmicsDataset

def scale(x):
    med=np.nanmedian(x,axis=0);mad=np.nanmedian(abs(x-med),axis=0);sd=np.nanstd(x,axis=0)
    return (x-med)/np.where(mad>1e-12,mad,np.where(sd>1e-12,sd,1.))

def main():
    p=argparse.ArgumentParser();p.add_argument('--species-file',required=True);p.add_argument('--golden-dir',required=True);p.add_argument('--output',required=True);a=p.parse_args();results=[]
    for sid in Path(a.species_file).read_text(encoding='utf-8-sig').split():
        target=store.lookup_version(sid,'core',release_id());m=store.read_json(target/'manifest.json');matrix=store.read_matrix(str(target));arrays=store.read_arrays(str(target));meta=store.read_metadata(str(target));fig=store.read_bundle(str(target));profiles=store.read_json(target/'profiles.json.gz');ds=OmicsDataset.objects.get(species__species_id=sid,omics_type='proteome');raw=read_frame(ds.core_csv_path);checks={}
        assert raw.protein_id.astype(str).tolist()==meta['protein_id'];assert len(raw)==m['n_source'];checks['source_ids_and_complete_rows']=len(raw)
        for f in CORE_FIELDS:
            v=pd.to_numeric(raw[f],errors='coerce').to_numpy(float);good=np.isfinite(v);r=profiles[f]
            assert r['n_valid']==int(good.sum()) and r['n_missing']==int((~good).sum()) and r['n_zero']==int((v[good]==0).sum()),f
            if good.any():assert np.allclose(r['quantiles'],np.quantile(v[good],[0,.05,.25,.5,.75,.95,1]),rtol=1e-8,atol=1e-10),f
        checks['all_core_stats']=52
        corr=fig['D13']['data'];columns=[matrix['matrix'][:,matrix['fields'].index(f)] for f in corr['fields']]
        for i,x in enumerate(columns):
            for j,y in enumerate(columns):
                good=np.isfinite(x)&np.isfinite(y);assert corr['pair_n'][i][j]==int(good.sum())
                if good.sum()>=3 and np.ptp(x[good])>0 and np.ptp(y[good])>0:assert np.isclose(corr['matrix'][i][j],spearmanr(x[good],y[good]).statistic,rtol=1e-8,atol=1e-10)
        checks['spearman_pairs']=49
        names=fig['D15']['data']['modules'];expected={}
        for name,e in fig['D14']['data']['evidence'].items():
            x=np.column_stack([matrix['matrix'][:,matrix['fields'].index(f)] for f in e['fields']]);z=scale(x);score=(z if name=='S-rich' else abs(z)).mean(1);score[~np.isfinite(x).all(1)]=np.nan;expected[name]=score
        for name,f in [('Hydropathy','gravy'),('SS upper/L','disulfide_density')]:expected[name]=matrix['matrix'][:,matrix['fields'].index(f)]
        union=[];ids=np.array(meta['protein_id'])
        for j,name in enumerate(names):
            v=expected[name];assert np.allclose(v,arrays['candidate_scores'][:,j],equal_nan=True,rtol=1e-8,atol=1e-10);good=np.flatnonzero(np.isfinite(v));ranks=np.full(len(v),np.nan);ranks[good]=100*rankdata(v[good],method='average')/len(good);assert np.allclose(ranks,arrays['candidate_percentiles'][:,j],equal_nan=True,rtol=1e-8,atol=1e-10)
            ordered=good[np.lexsort((ids[good],-v[good]))];assert [r['protein_id'] for r in fig['D14']['data']['top'][name]]==ids[ordered[:8]].tolist()
            for i in ordered[:3]:
                if i not in union:union.append(i)
        assert [r['protein_id'] for r in fig['D15']['data']['rows']]==ids[union].tolist();checks['candidate_modules']=6;checks['candidate_union']=len(union)
        c=payload(sid,'core',release_id());assert c['readiness']=='ready' and c['data']['status']!='unavailable';d=np.array(c['data']['distance']);assert np.allclose(d,d.T) and np.allclose(np.diag(d),0);checks['cohort_hash']=c['cohort_hash'];checks['cohort_species']=len(c['species_ids'])
        if sid=='saccharomyces_cerevisiae':
            for cid,file in [('D01','01_p2_scores.csv'),('D03','03_p4_clr_scores.csv')]:
                golden=pd.read_csv(Path(a.golden_dir)/file).set_index('protein_id');idx=arrays[cid+'_row_index'];keys=ids[idx];reference=golden.reindex(keys)[['PC1','PC2']].to_numpy(float);current=arrays[cid+'_coordinates'];assert np.isfinite(reference).all();assert set(keys)==set(golden.index)
                signs=np.where(np.sum(current*reference,axis=0)<0,-1.,1.);error=np.linalg.norm(current*signs-reference)/np.linalg.norm(reference);assert error<=1e-8
                parity=json.loads((Path(a.golden_dir).parent/'word_golden_parity.json').read_text(encoding='utf-8'));expected=parity[cid]['variance'];actual=fig[cid]['data']['ordination']['variance'];assert np.allclose(actual,expected,rtol=1e-8,atol=1e-10)
                checks[cid+'_word_coordinate_error_sign_only']=float(error);checks[cid+'_variance']=actual;checks[cid+'_golden_input_ids_equal']=True
        results.append({'species_id':sid,'status':'passed','checks':checks});print(sid,flush=True)
        for fn in [store.read_bundle,store.read_matrix,store.read_metadata,store.read_arrays]:fn.cache_clear()
    store.write_json(Path(a.output),{'status':'passed','species':len(results),'results':results})
if __name__=='__main__':main()
