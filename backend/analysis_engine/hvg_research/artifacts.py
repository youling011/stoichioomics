from pathlib import Path,PureWindowsPath
import os,json,hashlib,uuid,math,time
import numpy as np
import pandas as pd
def clean(v):
 if isinstance(v,dict):return {str(k):clean(x) for k,x in v.items()}
 if isinstance(v,(list,tuple,set,np.ndarray)):return [clean(x) for x in v]
 if isinstance(v,np.generic):return clean(v.item())
 if isinstance(v,float) and not math.isfinite(v):return None
 if v is pd.NA or v is pd.NaT:return None
 if isinstance(v,Path):return str(v)
 return v
def atomic_replace(source,target):
 for attempt in range(12):
  try:os.replace(source,target);return
  except PermissionError:
   if attempt==11:raise
   time.sleep(min(.025*2**attempt,.5))
def atomic_json(path,value):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_name('.'+path.name+'.'+uuid.uuid4().hex+'.tmp')
 try:tmp.write_text(json.dumps(clean(value),ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');atomic_replace(tmp,path)
 finally:
  if tmp.exists():tmp.unlink()
def atomic_frame(path,frame):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_name('.'+path.name+'.'+uuid.uuid4().hex+'.tmp')
 try:frame.to_parquet(tmp,index=False);atomic_replace(tmp,path)
 finally:
  if tmp.exists():tmp.unlink()
def digest(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for b in iter(lambda:f.read(2**20),b''):h.update(b)
 return h.hexdigest()
def content_hash(v):return hashlib.sha256(json.dumps(clean(v),ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def member_hash(ids):return content_hash(sorted(set(map(str,ids))))
def safe_path(root,relative):
 root=Path(root).resolve();windows=PureWindowsPath(str(relative));p=Path(str(relative).replace(chr(92),'/'))
 if windows.drive or p.is_absolute() or '..' in p.parts:raise ValueError('Invalid relative artifact path')
 resolved=(root/p).resolve()
 if not resolved.is_relative_to(root):raise ValueError('Artifact escapes run directory')
 return Path(chr(92)*2+chr(63)+chr(92)+str(resolved)) if os.name=='nt' and not str(resolved).startswith(chr(92)*2+chr(63)+chr(92)) else resolved
