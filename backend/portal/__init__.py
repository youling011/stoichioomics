"""Portal API, loaded on use so read-only HTTP never initializes all engines."""
from importlib import import_module
_MODULES={
 'create_job_from_uploads':'jobs','ensure_job_dirs':'jobs','list_workspace_jobs':'jobs',
 'build_full_pipeline_config':'config_builder','build_preanalysis_config':'config_builder',
 'run_full_pipeline_from_config':'pipeline_runner','run_preanalysis_from_config':'pipeline_runner',
 'scan_cases':'registry','load_case_outputs':'results',
}
__all__=list(_MODULES)
def __getattr__(name):
 if name not in _MODULES:raise AttributeError(name)
 value=getattr(import_module('.'+_MODULES[name],__name__),name);globals()[name]=value;return value
