from backend.apps.common.artifact_locations import locate
from backend.apps.stoichdb.feature_sources import io as feature_io
from threading import RLock
import hashlib,json
import numpy as np
from scipy.spatial.distance import pdist,squareform
from scipy.cluster.hierarchy import linkage,leaves_list
from threadpoolctl import threadpool_limits
from . import artifacts as store
from .contracts import FINGERPRINT,FAMILIES
from .statistics import robust
from .source import release_id
from backend.apps.stoichdb.complete_core.datasource import CompleteCoreDataSource
from pathlib import Path
from . import METHOD_VERSION
DEFAULT=['arabidopsis_thaliana','bacillus_subtilis_gca_004328845','danio_rerio','drosophila_melanogaster','escherichia_coli_str_k_12_substr_mg1655_gca_000005845','mus_musculus_casteij','oryza_sativa','saccharomyces_cerevisiae']
_lock=RLock()
def compute(sid,m,scope,selected=None,dinuc=False):
    from django.conf import settings
    from .ordination import fit
    species=list(dict.fromkeys(selected if selected is not None else DEFAULT+([sid] if sid not in DEFAULT else [])))
    if len(species)>min(32,getattr(settings,'SEQUENCE_VIZ_COHORT_LIMIT',32)):raise ValueError('cohort_limit_32')
    fields=[f'locus_dinuc_{a+b}_freq' for a in 'ACGT' for b in 'ACGT'] if dinuc else FINGERPRINT[m];included=[];excluded=[];rows=[];versions=[];counts=[]
    for s in species:
        try:
            ds=CompleteCoreDataSource(s,m);target=store.lookup(s,m,scope,release_id());manifest=store.read_json(target/'manifest.json')
            if store.stale(manifest,ds):raise FileNotFoundError('stale_fingerprint')
            means=manifest['fingerprint']['means'];a=np.array([np.nan if means.get(k) is None else means[k] for k in fields],float)
            if not np.isfinite(a).all():excluded.append({'species_id':s,'reason_code':'missing_fingerprint_fields','fields':[k for k,x in zip(fields,a) if not np.isfinite(x)]});continue
            included.append(s);rows.append(a);versions.append(manifest['source_hash']+':'+manifest['implementation_hash']);counts.append(manifest['fingerprint']['counts'])
        except FileNotFoundError as e:excluded.append({'species_id':s,'reason_code':str(e),'needs_preparation':True})
    raw=np.array(rows,float).reshape(-1,len(fields));data=raw.copy();family=FAMILIES[m];unweighted=[];weighted=[];distance=[];order=list(range(len(rows)));link=[];pca={'status':'unavailable','reason_code':'insufficient_n'};coordinates=[]
    with _lock,threadpool_limits(limits=1):
        if len(rows):
            if dinuc:data=data/data.sum(1,keepdims=True);data=np.log(data+1e-6);data-=data.mean(1,keepdims=True);z=data.copy();weighted=data
            else:
                if m=='transcriptome':data[:,fields.index('orf_len_aa')]=np.log10(np.where(data[:,fields.index('orf_len_aa')]>0,data[:,fields.index('orf_len_aa')],np.nan))
                z=robust(data)[0];weighted=z/np.sqrt(family)
            unweighted=z.tolist()
            if len(rows)>=2:
                dist=pdist(weighted)/np.sqrt(5 if m=='genome' else 4);distance=squareform(dist).tolist();lm=linkage(dist,method='average',optimal_ordering=True);link=lm.tolist();order=leaves_list(lm).tolist()
            if len(rows)>=3:
                # Weighted input is already scaled; PCA must not robust-scale it a second time.
                from sklearn.decomposition import PCA
                centered=weighted-weighted.mean(0);rank=int(np.linalg.matrix_rank(centered))
                if rank:
                    model=PCA(min(2,rank),svd_solver='full');scores=model.fit_transform(weighted);coordinates=scores.tolist();pca={'status':'available' if rank>1 else 'partial','rank':rank,'components':model.components_.tolist(),'variance':model.explained_variance_ratio_.tolist()}
    cohort_implementation_hash=hashlib.sha256(Path(__file__).read_bytes()).hexdigest();identity=[m,scope,species,included,fields,versions,family,dinuc,METHOD_VERSION,store.implementation_hash(),cohort_implementation_hash];cohort_id=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    return {'cohort_id':cohort_id,'method_version':METHOD_VERSION,'implementation_hash':store.implementation_hash(),'cohort_implementation_hash':cohort_implementation_hash,'species':included,'selected_species':species,'excluded_species':excluded,'fields':fields,'raw_means':raw.tolist(),'counts':counts,'transformed_input':data.tolist(),'unweighted_z':unweighted,'weighted_input':np.asarray(weighted).tolist(),'family_dimensions':family if not dinuc else [16]*16,'distance':distance,'distance_divisor':np.sqrt(5 if m=='genome' else 4),'linkage':link,'order':order,'pca':pca,'coordinates':coordinates,'primary_scope':scope,'source_versions':versions,'current_species':sid,'raw_sd':np.std(raw,axis=0).tolist() if len(raw) else [],'raw_range':np.ptp(raw,axis=0).tolist() if len(raw) else [],'z_sd':np.std(unweighted,axis=0).tolist() if len(rows) else []}
