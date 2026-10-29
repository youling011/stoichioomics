"""Keep small fixed chart packets independently within the shared byte budget.

The immutable source bundle signature is checked on every access. This avoids
retaining a whole oversized bundle merely to display one small chart, without
changing any scientific data or making extra disk copies.
"""
from .artifact_locations import budget_cache
from .request_timing import stage

@budget_cache('figures.json.gz')
def _chart(target,namespace,key):
 if namespace=='proteome':
  from backend.apps.stoichdb.proteome_viz import artifacts,api
  return api.presentation(artifacts.read_bundle(target)[key])
 if namespace=='sequence':
  from backend.apps.stoichdb.sequence_viz import artifacts
  return artifacts.bundle(target)[key]
 raise ValueError('unsupported_fixed_chart_namespace')

def get(namespace,target,key):
 with stage('chart_total'):return _chart(str(target),namespace,key)
