from pathlib import Path
def validate_job_research_config(job,cfg):
 if not (cfg.get('hvg_research') or {}).get('enabled'):return
 root=Path(job.workspace_path).resolve();p=cfg['input_adapter'];raw=(root/'raw').resolve();workspace=p.get('workspace') or {}
 if Path(p['input_dir']).resolve()!=raw:raise ValueError('Research input_dir must belong to this job raw directory')
 if workspace.get('job_id')!=job.job_id or (Path(workspace.get('root_dir',''))/job.job_id).resolve()!=root:raise ValueError('Research workspace belongs to another job')
 for section in ['expression','metadata','stoich']:
  values=p.get(section) or {}
  if values.get('external_command'):raise ValueError('Web research jobs cannot execute arbitrary external commands')
  for key,value in values.items():
   if isinstance(value,str) and 'file' in key and value:
    path=Path(value)
    if path.is_absolute() or '..' in path.parts or not (raw/path).resolve().is_relative_to(raw):raise ValueError('Input file must belong to this job')
