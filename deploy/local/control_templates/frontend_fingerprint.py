import hashlib
from pathlib import Path
def frontend_fingerprint(front):
    front=Path(front);files=[]
    for name in ['src','public']:
        files += [p for p in (front/name).rglob('*') if p.is_file()]
    files += [front/n for n in ['index.html','vite.config.js','package.json','package-lock.json'] if (front/n).is_file()]
    digest=hashlib.sha256()
    for path in sorted(files):
        digest.update(path.relative_to(front).as_posix().encode());digest.update(b'\0')
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()
