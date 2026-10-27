"""Resolve an explicitly published external data manifest; never touch PostgreSQL."""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json
import os
import re
import shutil
import tarfile
import urllib.parse
import urllib.request

CHUNK=4*1024*1024
KINDS={'postgres-custom','tar'}


def relative(value):
    if not isinstance(value,str) or not value or '\\' in value or ':' in value:
        raise ValueError('Expected a portable relative path')
    p=PurePosixPath(value)
    if p.is_absolute() or any(x in {'..','.'} for x in value.split('/')) or '' in value.split('/'):
        raise ValueError('Unsafe relative path')
    return p


def load(path,require_published=True):
    manifest=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if manifest.get('schema_version')!=1 or manifest.get('status') not in {'not_published','published'}:
        raise ValueError('Unsupported data manifest')
    if require_published and manifest['status']!='published':
        raise ValueError('Data has not been published. No download URL or checksum is currently available.')
    if not isinstance(manifest.get('artifacts'),list):raise ValueError('artifacts must be a list')
    ids=set();names=set();kinds=set();components=set()
    required={row['id'] for row in manifest.get('required_components',[])}
    for row in manifest['artifacts']:
        key=row.get('id','')
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]*',key) or key in ids:raise ValueError('Invalid/duplicate artifact id')
        ids.add(key)
        if not isinstance(row.get('component'),str) or row['component'] not in required:
            raise ValueError('Each artifact must name a declared release component')
        components.add(row['component'])
        filename=str(relative(row.get('filename')))
        if filename in names:raise ValueError('Duplicate artifact filename')
        names.add(filename)
        url=urllib.parse.urlsplit(row.get('url',''))
        if url.scheme!='https' or not url.netloc or url.username or url.password:raise ValueError('Artifact URL must be HTTPS without embedded credentials')
        if not re.fullmatch(r'[0-9a-f]{64}',row.get('sha256','')):raise ValueError('A real SHA256 is required')
        if isinstance(row.get('bytes'),bool) or not isinstance(row.get('bytes'),int) or row['bytes']<=0:raise ValueError('A measured positive byte count is required')
        if row.get('kind') not in KINDS:raise ValueError('Unsupported artifact kind')
        if row['kind']=='tar' and (not isinstance(row.get('unpacked_bytes'),int) or row['unpacked_bytes']<=0):
            raise ValueError('Tar artifacts require a measured unpacked_bytes capacity bound')
        kinds.add(row['kind'])
    if manifest['status']=='published' and (not ids or 'postgres-custom' not in kinds or 'tar' not in kinds):
        raise ValueError('A complete published release requires database and file artifacts')
    if manifest['status']=='published' and (not required or components!=required):
        raise ValueError('Published release does not cover every required component')
    return manifest


def checksum(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(CHUNK),b''):h.update(block)
    return h.hexdigest()


def local_path(root,name):
    root=Path(root).resolve();target=root/str(relative(name))
    if not target.resolve().is_relative_to(root) or target.is_symlink():raise ValueError('Destination escaped its root')
    return target


def verified(path,row):
    return path.is_file() and not path.is_symlink() and path.stat().st_size==row['bytes'] and checksum(path)==row['sha256']


def fetch(row,root):
    target=local_path(root,row['filename'])
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():
        if verified(target,row):return
        raise ValueError('Existing destination differs; refusing overwrite: '+row['id'])
    partial=target.with_name(target.name+'.part')
    if partial.is_symlink():raise ValueError('Partial destination is a symlink')
    offset=partial.stat().st_size if partial.exists() else 0
    if offset>row['bytes']:raise ValueError('Partial file exceeds declared size')
    if offset==row['bytes']:
        if not verified(partial,row):raise ValueError('Completed partial checksum mismatch')
        partial.replace(target);return
    request=urllib.request.Request(row['url'],headers={'Range':f'bytes={offset}-'} if offset else {})
    with urllib.request.urlopen(request,timeout=60) as response:
        if urllib.parse.urlsplit(response.geturl()).scheme!='https':raise ValueError('HTTPS downgrade refused')
        if response.status==206:
            header=response.headers.get('Content-Range','')
            if not header.startswith(f'bytes {offset}-') or not header.endswith('/'+str(row['bytes'])):
                raise ValueError('Unexpected resume response')
            mode='ab'
        elif response.status==200:
            offset=0;mode='wb'
        else:raise ValueError('Unexpected download status')
        with partial.open(mode) as output:
            for block in iter(lambda:response.read(CHUNK),b''):
                offset+=len(block)
                if offset>row['bytes']:raise ValueError('Download exceeds declared size')
                output.write(block)
    if not verified(partial,row):raise ValueError('Downloaded file size or SHA256 mismatch: '+row['id'])
    if target.exists():raise ValueError('Destination appeared during download')
    partial.replace(target)


def extract(row,downloads,destination):
    if row['kind']!='tar':return
    archive=local_path(downloads,row['filename'])
    if not verified(archive,row):raise ValueError('Archive must pass checksum verification before extraction')
    destination=Path(destination).resolve();destination.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(destination).free<row['unpacked_bytes']:raise ValueError('Insufficient free extraction space')
    with tarfile.open(archive,'r:*') as source:
        members=source.getmembers();seen=set();total=0
        if len(members)>2_000_000:raise ValueError('Archive member limit exceeded')
        for member in members:
            # Normalization does not change scientific file contents.
            name=member.name.removeprefix('./').rstrip('/')
            if name in {'','.'} and member.isdir():continue
            relative(name)
            if not (member.isdir() or member.isfile()):raise ValueError('Archive links and special files are not supported')
            target=local_path(destination,name)
            folded=name.casefold() if os.name=='nt' else name
            if folded in seen:raise ValueError('Archive member collision')
            seen.add(folded)
            if member.isfile():
                if target.exists():raise ValueError('Refusing to overwrite extracted data: '+name)
                total+=member.size
        if total!=row['unpacked_bytes']:raise ValueError('Unpacked size differs from published capacity metadata')
        for member in members:
            name=member.name.removeprefix('./').rstrip('/')
            if name in {'','.'} and member.isdir():continue
            target=local_path(destination,name)
            if member.isdir():target.mkdir(parents=True,exist_ok=True);continue
            target.parent.mkdir(parents=True,exist_ok=True)
            with source.extractfile(member) as content,target.open('xb') as output:shutil.copyfileobj(content,output,CHUNK)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['status','fetch','verify','extract'])
    parser.add_argument('--manifest',default='data-releases/release.example.json')
    parser.add_argument('--download-dir',default='var/downloads')
    parser.add_argument('--data-root',help='External root corresponding to the original G:/stoichioomics layout')
    args=parser.parse_args()
    try:
        manifest=load(args.manifest,require_published=args.action!='status')
        if args.action=='status':
            print(json.dumps({'release_id':manifest.get('release_id'),'status':manifest['status'],'artifacts':len(manifest['artifacts'])}));return
        if args.action=='extract' and not args.data_root:raise ValueError('--data-root is required for extraction')
        for row in manifest['artifacts']:
            if args.action=='fetch':fetch(row,args.download_dir)
            elif args.action=='verify':
                if not verified(local_path(args.download_dir,row['filename']),row):raise ValueError('Missing/mismatched artifact: '+row['id'])
            else:extract(row,args.download_dir,args.data_root)
            print(args.action+': '+row['id'])
    except (ValueError,OSError,KeyError,tarfile.TarError) as exc:parser.exit(2,str(exc)+'\n')


if __name__=='__main__':main()
