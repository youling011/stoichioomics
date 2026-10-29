"""Read-only native metadata capture before any source Core retirement.

Run on each actual host against an already verified receipt manifest. Metadata
does not replace content verification. The coordinator must recheck its original
native change tokens before merging these host identities into the final plan.
"""
import argparse,json,os,sys
from pathlib import Path as NativePath
PROJECT=NativePath(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
from backend.apps.common.host_paths import Path
from backend.apps.stoichdb.feature_sources.asset_state import change_token
from backend.apps.stoichdb.feature_sources.resolver import alias_key

def stat_of(path):
    path=Path(path)
    if os.name=='posix':
        # O_PATH never reads the body. fstat + /proc's canonical handle path
        # avoid repeatedly traversing every Windows-mounted parent directory.
        descriptor=os.open(path,os.O_PATH|os.O_CLOEXEC)
        try:
            stat=os.fstat(descriptor);resolved=os.readlink('/proc/self/fd/'+str(descriptor))
            if resolved.endswith(' (deleted)'):raise ValueError('Source disappeared during identity capture')
            token={'host':'posix','change_ns':stat.st_ctime_ns}
        finally:os.close(descriptor)
    else:
        stat=path.stat();resolved=str(path.resolve());token=change_token(path)
    return {'size':stat.st_size,'mtime_ns':stat.st_mtime_ns,'mtime':stat.st_mtime,'ino':stat.st_ino,
        'resolved_path':resolved,'change_token':token}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--input',required=True);parser.add_argument('--out',required=True)
    parser.add_argument('--sampling-receipt',default='');parser.add_argument('--sampling-receipt-digest',default='')
    args=parser.parse_args();out=Path(args.out)
    sampling_digest=None
    if args.sampling_receipt:
        from backend.apps.stoichdb.feature_sources.sampling import approval
        sampling_digest=approval(args.sampling_receipt,args.sampling_receipt_digest)
    if out.exists():raise ValueError('A new host metadata report is required')
    out.parent.mkdir(parents=True,exist_ok=True);count=0;captured={}
    with Path(args.input).open(encoding='utf-8') as source,out.open('x',encoding='utf-8') as output:
        for line in source:
            if not line.strip():continue
            row=json.loads(line)
            if not row.get('binding_ready'):
                from backend.apps.stoichdb.feature_sources.sampling import validate_metadata
                validate_metadata(row)
                if not sampling_digest or row['sampling_receipt_sha256']!=sampling_digest:raise ValueError('Explicit matching sampled acceptance authorization required')
            core_key=alias_key(row['core_path']);full_key=alias_key(row['full_path'])
            if core_key not in captured:captured[core_key]=stat_of(row['core_path'])
            if full_key not in captured:captured[full_key]=stat_of(row['full_path'])
            core=captured[core_key];full=captured[full_key]
            for actual,key in [(core,'core_stat'),(full,'full_stat')]:
                expected=row[key]
                if (actual['size'],actual['mtime_ns'])!=(expected['size'],expected['mtime_ns']):raise ValueError('Source metadata differs across hosts: '+row['dataset_id'])
            output.write(json.dumps({'dataset_id':row['dataset_id'],'release_context':row.get('release_context',''),
                'legacy_source_key':alias_key(row['core_path']),'core_path':row['core_path'],'full_path':row['full_path'],
                'core_host_stat':core,'full_host_stat':full,'host':full['change_token']['host']},ensure_ascii=False,separators=(',',':'))+'\n')
            count+=1
            if count%5000==0:print(json.dumps({'captured':count,'metadata_only':True}),flush=True)
    print(json.dumps({'captured':count,'source_data_modified':False,'content_reverified':False}))

if __name__=='__main__':main()
