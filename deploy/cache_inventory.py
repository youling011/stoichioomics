"""Exact offline cache/export classification; never invokes a producer."""
import hashlib,json,zipfile
from pathlib import Path
from backend.apps.common.artifact_locations import read_roots
from backend.apps.stoichdb.feature_hub.sources import DatasetSourceResolver
from backend.apps.stoichdb.feature_hub.cache_identity import source_content_identity,legacy_fingerprints

def inventory(roots):
 rows=[];descriptors={}
 for namespace,write_root in roots.items():
  for ordinal,root in enumerate(read_roots(namespace,write_root)):
   if namespace=='feature_exports':
    for status_path in sorted(root.glob('*/status.json')):
     value=json.loads(status_path.read_text('utf8'));folder=status_path.parent;state=value.get('status');valid=False;reason='Historical orphan is not scheduled' if state in ['queued','running'] else 'Saved state: '+str(state)
     if state=='completed':
      try:
       checks=(folder/'checksums.sha256').read_text('utf8').splitlines()
       for line in checks:
        expected,name=line.split(None,1);name=name.strip();p=(folder/name).resolve()
        if not p.is_relative_to(folder.resolve()) or p.name!=name:raise ValueError('Export checksum path escape')
        with p.open('rb') as f:actual=hashlib.file_digest(f,'sha256').hexdigest()
        if actual!=expected:raise ValueError('Export member checksum mismatch')
       archive=folder/(folder.name+'.zip')
       with zipfile.ZipFile(archive) as z:
        if z.testzip():raise ValueError('Corrupt export ZIP')
       with archive.open('rb') as f:archive_sha=hashlib.file_digest(f,'sha256').hexdigest()
       valid=True;reason='Complete checksums and ZIP CRC verified'
      except (OSError,ValueError,zipfile.BadZipFile) as exc:reason=str(exc);archive_sha=None
     rows.append({'namespace':namespace,'source_root':str(root),'object_id':folder.name,'source_version':folder.name,'relative_manifest':str(status_path.relative_to(root)),'expected_source_sha256':hashlib.sha256(status_path.read_bytes()).hexdigest(),'target_root':str(write_root),'availability':'available' if valid else 'expired' if state in ['queued','running'] and ordinal else 'missing','decision':'expose_historical' if valid else 'exclude_expired' if state in ['queued','running'] and ordinal else 'preserve_unavailable','reason':reason,'zip_sha256':archive_sha if valid else None,'has_saved_expiry':bool(value.get('expires_at'))})
    continue
   for p in sorted(root.glob('*.json')):
    valid=False;identity=None
    try:
     value=json.loads(p.read_text('utf8'));sid=value['species_id'];mode=value['omics'];scope=value.get('scope',value.get('table_level','core'));key=(sid,mode,scope)
     if key not in descriptors:descriptors[key]=DatasetSourceResolver().resolve(*key)
     source=descriptors[key];identity=source_content_identity(source);legacy=legacy_fingerprints(source)
     if value.get('source_sha') and value['source_sha'] not in [source.fingerprint,*legacy]:raise ValueError('Source fingerprint changed')
     if int(value.get('n_rows',value.get('entity_count',-1)))!=source.row_count:raise ValueError('Complete row population differs')
     if namespace=='feature_profiles' and not any(p.name==v+'.'+value['field']+'.json' for v in [source.fingerprint,*legacy]):raise ValueError('Field/cache identity differs')
     if namespace=='feature_qc':
      fields=list(value['missingness']);fields_key=hashlib.sha256('\n'.join(fields).encode()).hexdigest()[:16]
      if value['selected_features']!=len(fields) or not any(p.name==v+'.'+mode+'.'+fields_key+'.json' for v in [source.fingerprint,*legacy]):raise ValueError('QC full selected field set differs')
     if namespace=='feature_home' and (value['dataset_id']!=source.dataset_id or value['schema_version']!=source.schema_version):raise ValueError('Schema/dataset differs')
     valid=True;reason='Canonical source content/binding, original metadata, complete population and exact cache parameters validated'
    except (OSError,ValueError,KeyError,LookupError) as exc:reason=str(exc)
    rows.append({'namespace':namespace,'source_root':str(root),'object_id':p.name,'source_version':p.stem,'relative_manifest':p.name,'expected_source_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'target_root':str(write_root),'availability':'reusable' if valid else 'stale','decision':'reuse_with_exact_receipt' if valid else 'preserve_unavailable','reason':reason,'canonical_source_content_sha256':identity})
 return rows
