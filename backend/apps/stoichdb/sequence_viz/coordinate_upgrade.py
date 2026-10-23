"""Upgrade coordinates only when all other scientific code/source is identical."""
import copy,hashlib
from pathlib import Path
from . import artifacts as store
from .coordinates import apply
def compatible(m):
    if m['omics']!='genome':return False
    base=store.implementation_hash();old_full=hashlib.sha256((base+hashlib.sha256(Path(__file__).with_name('full_scope.py').read_bytes()).hexdigest()).encode()).hexdigest()
    return m['implementation_hash']==(old_full if m['primary_scope']=='full' else base)
def upgrade(target):
    target=Path(target);m=store.read_json(target/'manifest.json');meta=copy.deepcopy(store.metadata(str(target)));v=store.matrix(str(target));ds={'species_id':m['species_id'],'omics':m['omics'],'scope':m['primary_scope'],'dataset_id':m['dataset_id'],'release_id':m['release_id'],'source_hash':m['source_hash'],'available_scopes':m['available_scopes'],'key':m['identity_field'],'ids':meta[m['identity_field']],'n':m['n_source'],'metadata':meta,'values':v,'fields':[r['key'] for r in m['fields']],'catalog':copy.deepcopy(m['catalog']),'source':copy.deepcopy(m['source'])};built={'figures':copy.deepcopy(store.bundle(str(target))),'arrays':{k:a.copy() for k,a in store.arrays(str(target)).items()},'profiles':store.profiles(str(target)),'fingerprint':copy.deepcopy(m['fingerprint']),'metadata_coverage':copy.deepcopy(m['metadata_coverage'])};apply(ds,built);ds['source']['coordinate_upgrade']={'previous_artifact':m['artifact_version'],'other_fitted_arrays_and_original_profiles_unchanged':True};return ds,built
