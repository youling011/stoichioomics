"""Full-only source preparation with an explicitly selected frozen recipe.

This is for NEW datasets, not a substitute for legacy Core equivalence proofs.
No CSV/Parquet source is created; only the small binding manifest is emitted.
"""
import csv,hashlib,io,json,struct
from pathlib import Path
from .arrow import reader,project,encoded_rows,stat_of
from .projection import CoreRecipe
from .resolver import alias_key

def prepare(full_path,core_alias,omics,recipe_id,recipe,dataset_id):
    from .registration import require_source_root
    require_source_root(full_path);require_source_root(core_alias)
    if Path(core_alias).exists():raise ValueError('New Full-only source cannot replace a legacy Core; use verify instead')
    actual=hashlib.sha256(json.dumps(recipe,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    if actual!=recipe_id or recipe['omics_type']!=omics:raise ValueError('Explicit frozen recipe identity/omics mismatch')
    specification=CoreRecipe(omics,tuple(recipe['columns_json']),recipe['fill_noncoding'],recipe['version'])
    before=stat_of(full_path)
    with Path(full_path).open(encoding='utf-8-sig',newline='') as handle:header=next(csv.reader(handle),[])
    specification.validate_full_header(header)
    fmt=recipe['serialization_json'];virtual=hashlib.sha256();logical=hashlib.sha256();size=0;rows=0;ids=set()
    primary={'genome':'gene_id','transcriptome':'transcript_id','proteome':'protein_id'}[omics]
    if primary not in specification.columns:raise ValueError('Core primary ID not present')
    buf=io.StringIO(newline='');csv.writer(buf,lineterminator=fmt['line_terminator'],quoting=fmt['quoting']).writerow(specification.columns)
    encoded=(b'\xef\xbb\xbf' if fmt['bom'] else b'')+buf.getvalue().encode('utf-8')
    virtual.update(encoded);size+=len(encoded);logical.update(struct.pack('>Q',len(encoded)));logical.update(encoded)
    batches,raw,handle=reader(full_path,header)
    try:
        for batch in batches:
            projected=project(batch,specification)
            values=projected.column(primary).to_pylist();unique=set(values)
            if len(unique)!=len(values) or unique&ids or any(not value.strip() for value in values):raise ValueError('Duplicate or empty new-source Core ID')
            ids.update(unique);strings=encoded_rows(projected,fmt)
            block=(fmt['line_terminator'].join(strings)+fmt['line_terminator']).encode('utf-8')
            virtual.update(block);size+=len(block);rows+=batch.num_rows
            for value in strings:
                encoded=value.encode('utf-8');logical.update(struct.pack('>Q',len(encoded)));logical.update(encoded)
        full_sha=raw.hasher.hexdigest()
    finally:handle.close()
    if stat_of(full_path)!=before:raise ValueError('New Full source changed while preparing')
    receipt={'dataset_id':dataset_id,'omics':omics,'core_path':str(core_alias),'full_path':str(full_path),
        'recipe_id':recipe_id,'binding_ready':True,'baseline_kind':'new_full_only',
        'core_sha256':virtual.hexdigest(),'virtual_csv_sha256':virtual.hexdigest(),'full_sha256':full_sha,
        'logical_cell_hash':logical.hexdigest(),'rows':rows,'full_rows':rows,'row_selection':None,
        'virtual_size':size,'full_stat':before,'core_stat':{'size':size,'mtime_ns':before['mtime_ns'],
        'mtime':before['mtime'],'ino':0,'resolved_path':str(Path(core_alias).resolve())},'representation':'csv'}
    key=alias_key(core_alias);binding_id=hashlib.sha256((dataset_id+'||'+key).encode()).hexdigest()
    record={'binding_id':binding_id,'recipe_id':recipe_id,'release_context':'','legacy_source_key':key,
        'legacy_path':str(core_alias),'logical_scope':'core','representation':'csv','full_path':str(full_path),
        'full_sha256':full_sha,'core_sha256':virtual.hexdigest(),'virtual_csv_sha256':virtual.hexdigest(),
        'logical_cell_hash':logical.hexdigest(),'row_count':rows,'virtual_size':size,
        'legacy_stat_json':receipt['core_stat'],'full_stat_json':before,'receipt_json':receipt,'status':'full_backed'}
    return {'format':'stoich-corefull-bindings-v1','recipes':{recipe_id:recipe},'bindings':{key:record}}
