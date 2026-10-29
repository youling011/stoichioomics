"""Read-only registry snapshot for isolated CLI/consumer processes only.

Never use this context in HTTP handlers. It caches metadata, not scientific
values, and verifies the same live registry state on exit. Source-file stat/SHA
checks and the existing mathematics continue unchanged.
"""
from backend.apps.stoichdb.feature_sources import io as feature_io
from contextlib import contextmanager
import hashlib,json
from django.db.models import F
from backend.apps.stoichdb.models import Species,OmicsDataset
from . import source,cohorts
FIELDS=('dataset_id','omics_type','core_csv_path','full_csv_path','row_count_core','species_id')
_active=False

def load_snapshot(ids):
    ids=sorted(set(ids))
    if set(Species.objects.filter(species_id__in=ids).values_list('species_id',flat=True))!=set(ids):raise LookupError('unknown_species_in_cohort_snapshot')
    rows={sid:{} for sid in ids};identity=[]
    datasets=OmicsDataset.objects.filter(species__species_id__in=ids).only(*FIELDS).annotate(_integration_species_key=F('species__species_id'))
    for d in datasets:
        sid=d._integration_species_key;rows[sid][d.omics_type]=d;identity.append((sid,d.omics_type,d.dataset_id,d.core_csv_path,d.full_csv_path,d.row_count_core))
    signature=hashlib.sha256(json.dumps(sorted(identity),ensure_ascii=False).encode()).hexdigest()
    return rows,signature

@contextmanager
def registry_snapshot(ids):
    global _active
    if _active:
        yield {'nested':True};return
    rows,before=load_snapshot(ids);original_source=source.registry;original_engine=cohorts.registry
    def read(sid):return rows[sid] if sid in rows else original_source(sid)
    _active=True;source.registry=read;cohorts.registry=read;failed=False
    try:yield {'registry_sha256':before,'species':len(rows),'datasets':sum(len(v) for v in rows.values())}
    except BaseException:failed=True;raise
    finally:
        source.registry=original_source;cohorts.registry=original_engine;_active=False
        if not failed and load_snapshot(ids)[1]!=before:raise ValueError('registry_changed_during_cohort_snapshot')
