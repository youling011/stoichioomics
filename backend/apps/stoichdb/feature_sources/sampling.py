"""Transparent evidence level for the user's sampled acceptance policy.

Metadata registration is not a claim of per-file cell or SHA equivalence.
No source Core data are read by business consumers, even for unsampled files.
"""
import csv,hashlib,io,json,re
from pathlib import Path
from .projection import CoreRecipe,ProjectionError

LEVEL='sampled_rule_metadata'
def is_sampled(row):return row.get('verification_level')==LEVEL

def approval(filename,expected_digest):
    data=Path(filename).read_bytes();actual=hashlib.sha256(data).hexdigest()
    if not expected_digest or actual!=expected_digest:raise ProjectionError('Exact random sampling receipt digest required')
    report=json.loads(data)
    if report.get('format')!='corefull-random-sampling-acceptance-v1' or report.get('scope')!='data_source_random_sample' or report.get('passed') is not True or report.get('failures') or report.get('dataset_count',0)<75 or report.get('species_count',0)<25:
        raise ProjectionError('Complete successful random sampling receipt required')
    return actual

def validate_metadata(row):
    if not is_sampled(row):raise ProjectionError('Unknown sampled source evidence level')
    if row.get('binding_ready') is not False or row.get('content_equivalence_verified') is not False:
        raise ProjectionError('Sampled metadata must not claim per-file content equivalence')
    if row.get('representation','csv')!='csv':raise ProjectionError('Parquet requires its independent exact proof')
    for key in ['sampling_receipt_sha256','sampling_plan_sha256']:
        if not re.fullmatch('[0-9a-f]{64}',row.get(key,'')):raise ProjectionError('Missing sampled acceptance provenance')
    if row.get('header_contract_verified') is not True:raise ProjectionError('Exact source header contract missing')
    if row.get('baseline_kind')!=LEVEL:raise ProjectionError('Sampled baseline identity must remain explicit')
    if row['rows']<0 or row['virtual_size']!=row['core_stat']['size']:raise ProjectionError('Invalid retained Core metadata')

def header_contract(path,*,exact_serialization=True):
    """Read only the exact header and terminal newline, never feature bodies."""
    path=Path(path)
    with path.open('rb') as stream:
        raw=stream.readline(262145)
        if len(raw)>262144 or not raw.endswith(b'\n'):raise ProjectionError('Unsupported source CSV header')
        stream.seek(0,2);size=stream.tell();stream.seek(max(0,size-2));tail=stream.read()
    text=raw.decode('utf-8-sig');columns=next(csv.reader(io.StringIO(text,newline='')))
    if not columns or len(set(columns))!=len(columns):raise ProjectionError('Empty or duplicate source header')
    fmt={'line_terminator':'\r\n' if raw.endswith(b'\r\n') else '\n','bom':raw.startswith(b'\xef\xbb\xbf'),'quoting':csv.QUOTE_ALL if text.startswith('"') else csv.QUOTE_MINIMAL}
    if exact_serialization and not tail.endswith(fmt['line_terminator'].encode()):raise ProjectionError('Source CSV terminal newline differs from frozen format')
    buffer=io.StringIO(newline='');csv.writer(buffer,lineterminator=fmt['line_terminator'],quoting=fmt['quoting']).writerow(columns)
    generated=(b'\xef\xbb\xbf' if fmt['bom'] else b'')+buffer.getvalue().encode()
    if exact_serialization and generated!=raw:raise ProjectionError('Source header serialization cannot be preserved exactly')
    return columns,fmt


def prepare_metadata(core,full,omics,dataset_id,core_rows,full_rows,sampling_digest,plan_digest,registered_full_path):
    from .arrow import stat_of
    from .resolver import alias_key
    if alias_key(core)==alias_key(full):raise ProjectionError('Core alias and Full asset must be distinct')
    before_core,before_full=stat_of(core),stat_of(full)
    columns,fmt=header_contract(core);wide,_=header_contract(full,exact_serialization=False)
    recipe={'omics_type':omics,'columns_json':columns,'fill_noncoding':'zero','version':'extractor-projection-v1','serialization_json':fmt}
    CoreRecipe(omics,tuple(columns)).validate_full_header(wide)
    key={'genome':'gene_id','transcriptome':'transcript_id','proteome':'protein_id'}[omics]
    if key not in columns or key not in wide:raise ProjectionError('Primary ID missing in source header')
    if core_rows<0 or full_rows<0:raise ProjectionError('Invalid registered row count')
    if before_core!=stat_of(core) or before_full!=stat_of(full):raise ProjectionError('Source changed during metadata capture')
    row={'dataset_id':dataset_id,'omics':omics,'core_path':str(core),'full_path':str(full),'registered_full_path':registered_full_path,
        'recipe':recipe,'recipe_id':hashlib.sha256(json.dumps(recipe,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),
        'core_stat':before_core,'full_stat':before_full,'rows':int(core_rows),'full_rows':int(full_rows or core_rows),
        'virtual_size':before_core['size'],'serialization':fmt,'core_sha256':'','full_sha256':'','virtual_csv_sha256':'','logical_cell_hash':'',
        'row_selection':{'kind':'prefix','count':int(core_rows),'full_rows':int(max(core_rows,full_rows))},
        'verification_level':LEVEL,'baseline_kind':LEVEL,'binding_ready':False,'content_equivalence_verified':False,
        'header_contract_verified':True,'core_header_sha256':hashlib.sha256(json.dumps(columns,ensure_ascii=False).encode()).hexdigest(),
        'full_header_sha256':hashlib.sha256(json.dumps(wide,ensure_ascii=False).encode()).hexdigest(),
        'sampling_receipt_sha256':sampling_digest,'sampling_plan_sha256':plan_digest,'counts_provenance':'original_dataset_registry',
        'scientific_rule_provenance':'frozen_original_extractor_projection','source_core_retained':True}
    validate_metadata(row);return row
