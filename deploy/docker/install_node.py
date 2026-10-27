"""Install the explicitly selected official Node archive with its published checksum."""
from pathlib import Path
import argparse
import hashlib
import re
import shutil
import tarfile
import urllib.request

parser=argparse.ArgumentParser()
parser.add_argument('--version',required=True)
parser.add_argument('--arch',required=True,choices=['amd64','arm64'])
args=parser.parse_args()
if not re.fullmatch(r'22\.\d+\.\d+',args.version):parser.error('Expected an explicit Node 22 release')
arch={'amd64':'x64','arm64':'arm64'}[args.arch]
name=f'node-v{args.version}-linux-{arch}.tar.xz'
base=f'https://nodejs.org/dist/v{args.version}/'
with urllib.request.urlopen(base+'SHASUMS256.txt',timeout=60) as response:
    hashes=dict(line.split()[::-1] for line in response.read().decode().splitlines())
if name not in hashes:raise SystemExit('Requested official Node archive is not listed')
archive=Path('/tmp')/name
with urllib.request.urlopen(base+name,timeout=60) as response,archive.open('wb') as output:
    shutil.copyfileobj(response,output)
if hashlib.sha256(archive.read_bytes()).hexdigest()!=hashes[name]:raise SystemExit('Node archive SHA256 mismatch')
with tarfile.open(archive) as content:content.extractall('/opt',filter='data')
Path('/opt',f'node-v{args.version}-linux-{arch}').rename('/opt/node')
archive.unlink()
