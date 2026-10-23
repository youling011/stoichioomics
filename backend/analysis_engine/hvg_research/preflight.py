from django.conf import settings
from pathlib import Path
import json
from backend.apps.hvg.research_repository import readonly_source
from backend.apps.jobs.stoich_registry_resolver import _resolve_species_id
from .config import validate_config
def research_preflight(cfg):
 from backend.apps.stoichdb.models import OmicsDataset,FunctionalAnnotationRelease,GOAnnotation,KEGGAnnotationLink
 c=validate_config(cfg.get('hvg_research'));p=cfg.get('phase1_analysis',{});species=_resolve_species_id((cfg.get('phase2_stoich') or {}).get('species_id',''));method=p.get('hvg_method','seurat_v3');sem=p.get('matrix_semantics') or (cfg.get('input_adapter') or {}).get('expression',{}).get('value_semantics')
 sem={'raw_counts':'counts','log1p_normalized':'log_normalized'}.get(sem,sem);checks=[]
 expected='counts' if method.startswith('seurat_v3') else 'log_normalized'
 checks.append({'name':'research_matrix_semantics','status':'ready' if sem==expected else 'blocked','method':method,'observed_semantics':sem,'required_semantics':expected,'input_layer':p.get('input_layer','X'),'message':'Select a verified matrix/layer; raw does not automatically mean counts'})
 checks.append({'name':'research_primary_backend','status':'ready' if p.get('primary_backend','scanpy')=='scanpy' and method in ['seurat_v3','seurat_v3_paper','seurat','cell_ranger'] and not p.get('allow_primary_fallback',False) else 'blocked','batch_key':p.get('batch_key'),'n_top_genes':p.get('n_top_genes',2000)})
 with readonly_source():
  data=list(OmicsDataset.objects.filter(species__species_id=species).values('omics_type','schema_version','row_count_core'))
  release=c['enrichment']['annotation_release_id'] or FunctionalAnnotationRelease.objects.filter(is_active=True).values_list('release_id',flat=True).first()
  counts={'GO':GOAnnotation.objects.filter(species_id_text=species,release__release_id=release).count() if release else 0,'KEGG':KEGGAnnotationLink.objects.filter(species_id_text=species,release__release_id=release).count() if release else 0}
 checks.append({'name':'research_sources','status':'ready' if len({r['omics_type'] for r in data})==3 and sum(counts.values()) else 'degraded','species_id':species,'core_sources':data,'annotation_release_id':release,'annotation_source_rows':counts,'message':'Source counts are not the final expression-universe mapping coverage'})
 checks.append(workload_estimate(cfg,c,species,release))
 return checks

def workload_estimate(cfg,c,species,release):
 from backend.apps.stoichdb.models import GOAnnotation,KEGGAnnotationLink
 registry=json.loads((Path(settings.BASE_DIR)/'shared/schemas/stoich_ml_feature_registry_v1.json').read_text(encoding='utf-8'))
 fields=[r for r in registry['fields'] if r.get('scope')=='core']
 requested=sum(r['omics'] in c['core']['omics'] for r in fields)
 sources=c['enrichment']['sources'];terms=0
 namespaces={'GO_BP':'biological_process','GO_MF':'molecular_function','GO_CC':'cellular_component'}
 with readonly_source():
  for source in sources:
   if source in namespaces:terms+=GOAnnotation.objects.filter(species_id_text=species,release__release_id=release,go_is_obsolete=False,go_namespace=namespaces[source]).values('go_id').distinct().count() if release else 0
   else:terms+=KEGGAnnotationLink.objects.filter(species_id_text=species,release__release_id=release,annotation_type=source.removeprefix('KEGG_')).values('annotation_id').distinct().count() if release else 0
 cells=genes=None;adapter=cfg.get('input_adapter',{});expr=adapter.get('expression',{})
 if expr.get('format')=='h5ad':
  path=Path(adapter.get('input_dir',''))/str(expr.get('file') or '')
  if path.is_file():
   import anndata as ad
   a=ad.read_h5ad(path,backed='r')
   try:cells,genes=a.shape
   finally:a.file.close()
 contexts=1+len(c['contexts']);directions=2;grid=requested*terms*contexts
 return {'name':'research_workload_budget','status':'ready','input_cells':cells,'input_genes_before_QC':genes,'audited_core_fields':len(fields),'requested_core_upper_bound':requested,'source_terms_before_mapping_and_size_filter':terms,'contexts_including_global':contexts,'directions':directions,'feature_term_grid_upper_bound':grid,'direction_ORA_grid_upper_bound':grid*directions,'gsea_ES_evaluations_upper_bound':grid*2*c['pathway']['gsea_permutations'] if c['pathway']['gsea_enabled'] else 0,'bootstrap_repeats':c['feature_tests']['ci_repeats'],'gsea_permutations':c['pathway']['gsea_permutations'],'worker_count':c['execution']['worker_count'],'estimate_kind':'upper bounds before gene mapping, feature QC, term sizes and eligibility; not expected result rows or predicted wall time','message':'Complete Core and function analyses may take time. Workload estimates do not truncate features or terms, or silently reduce repetitions. Stage status, cancellation and resumption remain available during execution.' }
