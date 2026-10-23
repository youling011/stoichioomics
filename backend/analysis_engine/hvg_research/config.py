"""Strict, versioned research configuration. Legacy pipelines are opt-in unchanged."""
from copy import deepcopy
SCHEMA='hvg_research_v1'
DEFAULTS={
 'enabled':False,'schema_version':SCHEMA,'objective':'stoich_functional_characterization',
 'context_policy':'global_and_declared_subsets','contexts':[],
 'core':{'omics':['genome','transcriptome','proteome'],'coverage_policy':'audit_all_legal_core','semantic_overlay':'shared/schemas/hvg_core_semantics_v1.json','min_group_n':20,'main_max_missing_rate':.20,'exploratory_max_missing_rate':.50,'conditional_policy':'reviewed_per_feature'},
 'preprocessing':{'canonical_units':True,'continuous_scaler':'robust','composition_joint_transform':'ilr','composition_single_transform':'clr'},
 'feature_tests':{'alpha':.05,'minimum_abs_cliffs_delta':.147,'ci_repeats':500,'adjustment':'expression_detection_length','matching_enabled':True},
 'gene_sets':{'reference':'nonhvg_feature_applicable','low_quantile':.20,'high_quantile':.80,'compute_both_directions':True,'min_annotated_query':20},
 'enrichment':{'sources':['GO_BP','GO_MF','GO_CC','KEGG_pathway','KEGG_module'],'min_term_size':10,'max_term_size':500,'annotation_release_id':None,'fdr_scope':'all_declared_contexts_features_directions_terms'},
 'pathway':{'rank_relationship_enabled':True,'gsea_enabled':True,'gsea_permutations':1000,'within_pathway_enabled':True,'interaction_enabled':True},
 'validation':{'seed':42,'by_sensitivity':True,'biological_replication':'when_available','donor_key':None,'cell_resamples':10,'cell_fraction':.8,'top_n_factors':[.5,1.5]},
 'execution':{'worker_count':1,'stage_resume':True,'atomic_outputs':True,'resume_run_id':None,'retain_days':30}}
def deep_merge(base,updates,strict=False,path=''):
 out=deepcopy(base)
 if not isinstance(updates,dict):raise ValueError(f'{path}: expected object')
 for k,v in updates.items():
  if strict and k not in base:raise ValueError(f'Unknown research option {path}{k}')
  out[k]=deep_merge(out[k],v,strict,path+k+'.') if isinstance(out.get(k),dict) else deepcopy(v)
 return out
def validate_config(value=None):
 c=deep_merge(DEFAULTS,value or {},True)
 for path in ['enabled','gene_sets.compute_both_directions','execution.stage_resume','execution.atomic_outputs','feature_tests.matching_enabled','pathway.gsea_enabled','pathway.interaction_enabled','pathway.within_pathway_enabled','pathway.rank_relationship_enabled']:
  v=c
  for p in path.split('.'):v=v[p]
  if type(v) is not bool:raise ValueError(path+' must be boolean')
 if c['objective']!='stoich_functional_characterization' or c['context_policy']!='global_and_declared_subsets':raise ValueError('Unsupported research objective/context policy')
 if not c['execution']['atomic_outputs']:raise ValueError('Atomic research outputs are required')
 if c['execution']['resume_run_id'] and not c['execution']['stage_resume']:raise ValueError('Stage resume is disabled; create a new run')
 if not c['preprocessing']['canonical_units'] or c['preprocessing']['composition_joint_transform']!='ilr' or c['preprocessing']['composition_single_transform']!='clr':raise ValueError('Unsupported preprocessing contract')
 if c['schema_version']!=SCHEMA:raise ValueError('Unsupported research schema')
 for section,key,lo,hi in [('core','min_group_n',2,100000),('feature_tests','ci_repeats',2,100000),('pathway','gsea_permutations',10,1000000),('validation','cell_resamples',1,10000),('execution','worker_count',1,1),('execution','retain_days',1,3650)]:
  v=c[section][key]
  if type(v) is not int or not lo<=v<=hi:raise ValueError(section+'.'+key+' outside allowed range')
 if not 0<c['gene_sets']['low_quantile']<c['gene_sets']['high_quantile']<1:raise ValueError('Invalid quantile interval')
 if not 0<c['feature_tests']['alpha']<1:raise ValueError('Invalid alpha')
 if not 0<=c['core']['main_max_missing_rate']<=c['core']['exploratory_max_missing_rate']<=1:raise ValueError('Invalid missingness thresholds')
 if c['enrichment']['min_term_size']<1 or c['enrichment']['max_term_size']<c['enrichment']['min_term_size']:raise ValueError('Invalid term sizes')
 if c['preprocessing']['continuous_scaler'] not in ['robust','standard']:raise ValueError('Unknown scaler')
 if not c['core']['omics']:raise ValueError('Select at least one omics block')
 overlay=str(c['core']['semantic_overlay']).replace('\\','/')
 if not overlay.startswith('shared/schemas/') or '..' in overlay.split('/') or ':' in overlay:raise ValueError('Semantic overlay must be a project shared schema')
 if not c['gene_sets']['compute_both_directions']:raise ValueError('Both directions are required for the declared FDR family')
 if c['gene_sets']['reference']!='nonhvg_feature_applicable' or c['feature_tests']['adjustment']!='expression_detection_length':raise ValueError('Unsupported feature/set inference policy')
 if set(c['core']['omics'])-{'genome','transcriptome','proteome'}:raise ValueError('Unsupported omics')
 if set(c['enrichment']['sources'])-set(DEFAULTS['enrichment']['sources']):raise ValueError('Unsupported annotation source')
 if not isinstance(c['contexts'],list):raise ValueError('contexts must be list')
 ids={'global'}
 for ctx in c['contexts']:
  if set(ctx)-{'context_id','field','values'} or not all(k in ctx for k in ['context_id','field','values']):raise ValueError('Context requires context_id, field, values')
  if ctx['context_id'] in ids or not isinstance(ctx['values'],list) or not ctx['values']:raise ValueError('Invalid/duplicate context')
  ids.add(ctx['context_id'])
 return c
