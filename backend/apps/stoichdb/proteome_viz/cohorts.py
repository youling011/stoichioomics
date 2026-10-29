from backend.apps.common.artifact_locations import locate
"""Shared cohort membership and fingerprint identities for all three species views."""
from backend.apps.stoichdb.feature_sources import io as feature_io
import hashlib,json
from pathlib import Path
import numpy as np
from threading import RLock
from threadpoolctl import threadpool_limits
from backend.apps.stoichdb.models import Species,OmicsDataset
from . import METHOD_VERSION,artifacts as store
from .contracts import FINGERPRINT
from .ordination import cohort
_fit_lock=RLock()

def fingerprint(sid,scope,release):
    pointer=store.published(sid,scope,release)
    if pointer:
        manifest=store.read_json(store.path_for(pointer)/'manifest.json');row=pointer['fingerprint']
    else:manifest=None;row=None
    location=locate('proteome',store.root(),'fingerprints/'+store.component(release)+'/'+store.component(sid)+'_'+scope+'.json',required=False)
    p=location.target if location else store.root()/'fingerprints'/store.component(release)/(store.component(sid)+'_'+scope+'.json')
    if row is None and feature_io.source_available(p):row=store.read_json(p)
    if row is None:return None
    identity=manifest or row
    if identity.get('implementation_hash')!=store.implementation_hash():return None
    ds=OmicsDataset.objects.filter(species__species_id=sid,omics_type='proteome').only('dataset_id','core_csv_path','full_csv_path').first()
    if ds is None or row.get('dataset_id')!=ds.dataset_id:return None
    expected=identity.get('source',{}).get('file_signatures',identity.get('file_signatures',{}))
    for kind in ['core','full']:
        raw=getattr(ds,kind+'_csv_path');path=Path(raw) if raw else None
        actual={'bytes':feature_io.source_metadata(path).size,'mtime_ns':feature_io.source_metadata(path).mtime_ns} if path and feature_io.source_available(path) else None
        if actual!=expected.get(kind):return None
    return row

def default_ids(sid,scope,release):
    from backend.apps.stoichdb.services import HOME_REPRESENTATIVE_SPECIES
    ids=[sid]
    for config in HOME_REPRESENTATIVE_SPECIES:
        for candidate in config['preferred_ids']:
            row=fingerprint(candidate,scope,release)
            if candidate not in ids and row and all(row['means'].get(f) is not None for f in FINGERPRINT):ids.append(candidate);break
        if len(ids)>=8:break
    return ids

def payload(sid,scope,release,ids=None):
    ids=ids or default_ids(sid,scope,release)
    if not 1<=len(ids)<=64:raise ValueError('cohort_requires_1_to_64_species')
    species={s.species_id:s for s in Species.objects.filter(species_id__in=ids)}
    if len(species)!=len(ids):raise ValueError('unknown_species_in_cohort')
    rows=[];missing=[]
    for key in ids:
        row=fingerprint(key,scope,release)
        if row is None:missing.append(key)
        else:rows.append({**row,'label':species[key].display_name,'domain':species[key].domain})
    if missing:return {'readiness':'not_prepared','reason_code':'cohort_fingerprints_not_prepared','missing_species':missing,'species_ids':ids}
    with _fit_lock,threadpool_limits(limits=1):data=cohort(rows)
    data.get('pca',{}).pop('mask',None)
    digest=hashlib.sha256(json.dumps(store.clean([METHOD_VERSION,store.implementation_hash(),scope,rows]),sort_keys=True).encode()).hexdigest();data['cohort_hash']=digest
    if data['status']!='unavailable':
        d=data['distance']
        if not np.allclose(d,d.T,atol=1e-12) or not np.allclose(np.diag(d),0,atol=1e-12):raise ValueError('invalid_cohort_distance_matrix')
    return store.clean({'readiness':'ready','primary_scope':scope,'release_id':release,'method_version':METHOD_VERSION,'cohort_hash':digest,'species_ids':ids,'current_species':sid,'data':data})
