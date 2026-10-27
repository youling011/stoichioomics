"""Prepare only owned runtime directories; never migrate, restore or download data."""
from pathlib import Path
import os
import shutil
import sys

ROOT=Path('/opt/local')
for relative in ['workspace/jobs','workspace/sequence_analysis','uploads','runtime/sequence_analysis',
                 'runtime/compare_core','runtime/proteome_visuals_v3','runtime/sequence_visuals_v1',
                 'runtime/integration_visuals_v1','home','cache','matplotlib','numba','tmp']:
    (ROOT/'state'/relative).mkdir(parents=True,exist_ok=True)
registry=ROOT/'state/workspace/case_registry.json'
public=Path('/srv/stoichioomics/项目平台数据/stoich_platform_postgres_open_search_v6_2_perf_fix/proj/workspace/case_registry.json')
if not registry.exists() and public.is_file():
    shutil.copyfile(public,registry)
if len(sys.argv)<2:
    raise SystemExit('An explicit service or management command is required')
if sys.argv[1]=='uwsgi':
    required=Path('/opt/local/project/data/stoichdb_demo')
    if not required.is_dir():
        raise SystemExit('External scientific data is missing. See data-releases/README.md; no placeholder data is generated.')
    for key in ('DJANGO_SECRET_KEY','POSTGRES_PASSWORD'):
        value=os.environ.get(key,'')
        if not value or '__REQUIRED_' in value or value.startswith('CHANGE_ME'):
            raise SystemExit(key+' must be configured privately')
os.execvp(sys.argv[1],sys.argv[1:])
