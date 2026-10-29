"""Select a Python interpreter even when embedded in the uWSGI executable."""
import os,sys
from pathlib import Path
from django.conf import settings

def python_executable():
 configured=getattr(settings,'DEPLOYMENT_PYTHON',None) or os.environ.get('DEPLOYMENT_PYTHON')
 if configured:candidates=[Path(configured)]
 else:
  executable=Path(sys.executable)
  candidates=([executable] if executable.name.lower().startswith('python') else [])+[executable.with_name('python.exe' if os.name=='nt' else 'python'),Path(sys.prefix)/('Scripts/python.exe' if os.name=='nt' else 'bin/python')]
 for p in candidates:
  if p.is_file() and p.name.lower().startswith('python') and (os.name=='nt' or os.access(p,os.X_OK)):return str(p)
 raise RuntimeError('No executable Python interpreter is configured for background work')
