"""Species/release-scoped adapters; no annotation writes and no per-feature ORM."""
from backend.apps.stoichdb.feature_sources import io as feature_io
from pathlib import Path
from contextlib import contextmanager
import json,shutil
import numpy as np,pandas as pd
from django.db import connection,transaction
from django.conf import settings
from backend.analysis_engine.hvg_research.artifacts import atomic_json,atomic_frame,digest,member_hash,content_hash
@contextmanager
def readonly_source():
 with transaction.atomic():
  with connection.cursor() as c:
   c.execute('SET TRANSACTION READ ONLY');c.execute('SET LOCAL statement_timeout=60000')
  yield
def freeze_sources(species_id,release_id=None):
 from backend.apps.stoichdb.models import FunctionalAnnotationRelease,OmicsDataset,SchemaRegistry,GOAnnotation,KEGGAnnotationLink
 with readonly_source():
  q=FunctionalAnnotationRelease.objects.filter(release_id=release_id) if release_id else FunctionalAnnotationRelease.objects.filter(is_active=True)
  releases=list(q.values_list('release_id',flat=True))
  if len(releases)>1:raise ValueError('Ambiguous active annotation releases; specify annotation_release_id')
  data=list(OmicsDataset.objects.filter(species__species_id=species_id).values('dataset_id','omics_type','schema_version','core_csv_path','row_count_core'))
  schemas=list(SchemaRegistry.objects.filter(product_type='core',status='active').values('schema_id','omics_type','columns_json'))
  # Source file hashes protect resume even if mutable storage metadata is unchanged.
  for row in data:
   p=Path(row.get('core_csv_path') or '')
   row['actual_sha256']=feature_io.source_sha256(p) if feature_io.source_available(p) else None
  selected=releases[0] if releases else None
  annotation_digest=content_hash({'go':list(GOAnnotation.objects.filter(species_id_text=species_id,release__release_id=selected).order_by('id').values('gene_id','transcript_id','protein_id','go_id','go_namespace','go_is_obsolete')) if selected else [],'kegg':list(KEGGAnnotationLink.objects.filter(species_id_text=species_id,release__release_id=selected).order_by('id').values('gene_id','transcript_id','protein_id','annotation_id','annotation_type')) if selected else []})
 return {'species_id':species_id,'annotation_release_id':selected,'annotation_content_hash':annotation_digest,'datasets':data,'schemas':schemas}
def annotation_snapshot(root,species_id,release_id,policy):
 from backend.apps.stoichdb.models import GOAnnotation,KEGGAnnotationLink,GeneIndex
 from backend.apps.hvg.feature_mapping import SpeciesMappingIndex
 root=Path(root);L=pd.read_parquet(root/'labels/hvg_labels.parquet');genes=L.gene_id.astype(str).tolist()
 with readonly_source():
  go=list(GOAnnotation.objects.filter(species_id_text=species_id,release__release_id=release_id,go_is_obsolete=False).values('gene_id','transcript_id','protein_id','source_protein_id','go_id','go_name','go_namespace','mapping_confidence','annotation_status','source')) if release_id else []
  kg=list(KEGGAnnotationLink.objects.filter(species_id_text=species_id,release__release_id=release_id,annotation_type__in=['pathway','module']).values('gene_id','transcript_id','protein_id','annotation_id','annotation_name','annotation_type','source','annotation_status')) if release_id else []
  index=SpeciesMappingIndex(species_id=species_id,candidate_ids=genes)
  results=index.resolve_many(genes,'genome');canonical={}
  for g,r in results.items():
   if r.mapping_status=='mapped':canonical.setdefault(r.canonical_gene_id,set()).add(g)
  # Existing mapper has species-scoped unique alias/transcript/protein resolution.
  ids=sorted({str(r.get(k) or '') for r in go+kg for k in ['gene_id','transcript_id','protein_id','source_protein_id']} - {''})
  aindex=SpeciesMappingIndex(species_id=species_id,candidate_ids=ids)
  resolved={o:aindex.resolve_many(ids,o) for o in ['genome','transcriptome','proteome']}
  names=list(GeneIndex.objects.filter(species__species_id=species_id,gene_id__in=list(canonical)).values('gene_id','gene_name','biotype'))
 rows=[];audit=[];ns={'biological_process':'GO_BP','molecular_function':'GO_MF','cellular_component':'GO_CC'}
 for row in go+kg:
  hits=set()
  for key,o in [('gene_id','genome'),('transcript_id','transcriptome'),('protein_id','proteome'),('source_protein_id','proteome')]:
   identifier=str(row.get(key) or '');r=resolved[o].get(identifier)
   if r and r.mapping_status=='mapped':hits.update(canonical.get(r.canonical_gene_id,set()))
  gene=next(iter(hits)) if len(hits)==1 else None
  isgo='go_id' in row;source=ns.get(row.get('go_namespace')) if isgo else 'KEGG_'+row['annotation_type'];term=row['go_id'] if isgo else row['annotation_id'];tk=str(source)+'::'+str(term)
  audit.append({'source_gene_id':row['gene_id'],'gene_id':gene,'term_key':tk,'status':'mapped' if gene else 'not_in_U_or_ambiguous','release_id':release_id})
  if gene and source in policy['sources']:rows.append({'gene_id':gene,'term_key':tk,'term_id':term,'term_name':row['go_name'] if isgo else row['annotation_name'],'source':source})
 members=pd.DataFrame(rows,columns=['gene_id','term_key','term_id','term_name','source']).drop_duplicates(['gene_id','term_key'])
 terms=members.drop_duplicates('term_key')[['term_key','term_id','term_name','source']].copy();terms['background_size']=terms.term_key.map(members.groupby('term_key').size())
 for name,df in [('gene_term_membership',members),('terms',terms),('annotation_mapping_audit',pd.DataFrame(audit)),('source_go',pd.DataFrame(go)),('source_kegg',pd.DataFrame(kg))]:atomic_frame(root/'annotations'/f'{name}.parquet',df)
 namerows=[{**r,'canonical_gene_id':r['gene_id'],'gene_id':g} for r in names for g in canonical.get(r['gene_id'],[])]
 atomic_frame(root/'annotations/gene_names.parquet',pd.DataFrame(namerows,columns=['gene_id','gene_name','biotype','canonical_gene_id']))
 manifest={'species_id':species_id,'release_id':release_id,'matched_unique_genes':members.gene_id.nunique(),'term_count':len(terms),'membership_hash':content_hash(members.sort_values(['gene_id','term_key']).to_dict('records')),'evidence_code':'unavailable_in_schema','GO_propagation':'direct_imported_associations_only; no DAG','mapping':'existing species-scoped SpeciesMappingIndex; ambiguous discarded','source_status':'available' if len(members) else 'source_missing'}
 atomic_json(root/'annotations/annotation_manifest.json',manifest);return manifest
def core_snapshot(root,species_id,config):
 from backend.apps.hvg.feature_context import build_hvg_multiomics_feature_context
 root=Path(root);registry=Path(settings.BASE_DIR)/'shared/schemas/stoich_ml_feature_registry_v1.json';snapshot=root/'core/registry_snapshot.json';snapshot.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(registry,snapshot)
 with readonly_source():
  result=build_hvg_multiomics_feature_context(baseline_csv=root/'labels/baseline.csv',output_dir=root/'core',species_id=species_id,requested_omics=config['core']['omics'],config={'registry_snapshot_path':str(snapshot),'comparison_min_block_mapped_genes':config['core']['min_group_n']*2,'comparison_min_block_match_rate':0.0,'comparison_source_chunk_size':50000,'comparison_require_unique_mapping':True})
 L=pd.read_parquet(root/'labels/hvg_labels.parquet');path=result.get('comparison_input_csv');x=feature_io.read_csv(path,low_memory=False) if path and feature_io.source_available(Path(path)) else L.copy()
 if x.gene_id.tolist()!=L.gene_id.tolist():raise ValueError('Core context changed frozen U order')
 atomic_frame(root/'core/context.parquet',x);atomic_json(root/'core/context_result.json',result)
 atomic_json(root/'core/isoform_policy.json',{'policy':'existing source canonical representative else stable source representative; ambiguity retained by existing mapper','cross_omics_isoform_equivalence':'not_proven','derived_cross_isoform_ratios_enabled':False,'mapping_audit':'hvg_multiomics_mapping_table.csv'})
 return result
