"""Auditable storage adaptation. Physical Core deletion is deliberately disabled."""
import hashlib,json,os
from pathlib import Path as NativePath
from django.core.management.base import BaseCommand,CommandError
from django.db import connection,transaction
from backend.apps.common.host_paths import Path
from backend.apps.stoichdb.models import OmicsDataset,FeatureFile,CoreProjectionRecipe,FeatureSourceBinding
from backend.apps.stoichdb.feature_sources.arrow import verify,stat_of
from backend.apps.stoichdb.feature_sources.resolver import alias_key,clear_binding_cache

def full_candidate(dataset):
    if dataset.full_csv_path:
        p=Path(dataset.full_csv_path)
        if not p.is_file():raise ValueError('Registered Full is unavailable')
        return p
    core=Path(dataset.core_csv_path)
    names=[core.name.replace('.core.','.full.'),core.name.replace('_features.core.csv','_features.csv')]
    candidates=[core.with_name(n) for n in dict.fromkeys(names) if n!=core.name and core.with_name(n).is_file()]
    if len(candidates)!=1:raise ValueError('Full candidate is not unique')
    return candidates[0]

def file_digest(filename):
    h=hashlib.sha256()
    with NativePath(filename).open('rb') as stream:
        for block in iter(lambda:stream.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()

def emit(path,rows):
    target=NativePath(path);target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():raise CommandError('Refusing to overwrite an existing report')
    with target.open('x',encoding='utf-8') as handle:
        for row in rows:handle.write(json.dumps(row,ensure_ascii=False,default=str)+'\n')

class Command(BaseCommand):
    help='Inventory, verify, bind and check logical Core; this implementation NEVER deletes source files.'

    def add_arguments(self,parser):
        parser.add_argument('action',choices=['inventory','verify','bind','postcheck','restore-core','delete-sources','export-manifest','prepare-full','rollback-bindings'])
        parser.add_argument('--out',required=True)
        parser.add_argument('--verified-manifest',default='')
        parser.add_argument('--sampling-receipt',default='')
        parser.add_argument('--sampling-receipt-digest',default='')
        parser.add_argument('--plan-digest',default='')
        parser.add_argument('--apply',action='store_true')
        parser.add_argument('--journal',default='')
        parser.add_argument('--limit',type=int,default=0)
        parser.add_argument('--binding-id',default='')
        parser.add_argument('--isolated',action='store_true')
        parser.add_argument('--full-path',default='')
        parser.add_argument('--core-alias',default='')
        parser.add_argument('--omics',choices=['genome','transcriptome','proteome'])
        parser.add_argument('--recipe-catalog',default='')
        parser.add_argument('--recipe-id',default='')
        parser.add_argument('--dataset-id',default='')

    def handle(self,*args,**options):
        action=options['action']
        if options['limit']<0:raise CommandError('--limit must be nonnegative')
        if action=='delete-sources':raise CommandError('Source Core deletion is disabled by the current user instruction')
        target=NativePath(options['out'])
        if target.exists():raise CommandError('Refusing to overwrite an existing report before any database/source action')
        target.parent.mkdir(parents=True,exist_ok=True)
        if connection.vendor!='postgresql':raise CommandError('PostgreSQL is required')
        if action=='prepare-full':
            from backend.apps.stoichdb.feature_sources.new_sources import prepare
            catalog=json.loads(NativePath(options['recipe_catalog']).read_text(encoding='utf-8'))
            recipes=catalog.get('recipes',catalog)
            try:recipe=recipes[options['recipe_id']]
            except KeyError as exc:raise CommandError('Exact frozen --recipe-id is required') from exc
            if not options['dataset_id']:raise CommandError('Exact new --dataset-id required')
            manifest=prepare(options['full_path'],options['core_alias'],options['omics'],options['recipe_id'],recipe,options['dataset_id'])
            target.write_text(json.dumps(manifest,ensure_ascii=False,separators=(',',':')),encoding='utf-8');return
        if action=='rollback-bindings':return self.rollback(options)
        if action=='bind':return self.bind(options)
        if action=='export-manifest':return self.export(options)
        if action=='restore-core':return self.restore(options)
        if action=='postcheck':
            from backend.apps.stoichdb.feature_sources.resolver import logical_source,source_sha256
            def checks():
                rows=FeatureSourceBinding.objects.filter(status='full_backed').iterator(chunk_size=256)
                for index,binding in enumerate(rows):
                    if options['limit'] and index>=options['limit']:break
                    source=logical_source(binding.legacy_path,binding.release_context)
                    if binding.representation=='parquet':
                        h=hashlib.sha256()
                        with source.open_binary() as stream:
                            for block in iter(lambda:stream.read(4*1024*1024),b''):h.update(block)
                        actual=h.hexdigest()
                    else:actual=source_sha256(binding.legacy_path)
                    yield {'binding_id':binding.binding_id,'available':source is not None,'checksum_matches':(actual==binding.virtual_csv_sha256 if binding.virtual_csv_sha256 else None),
                           'verification_level':binding.receipt_json.get('verification_level','complete_file_equivalence'),
                           'physical_core_retained':Path(binding.legacy_path).is_file(),'full_path':binding.full_path}
            emit(options['out'],checks());return
        with transaction.atomic():
            with connection.cursor() as cursor:cursor.execute('SET TRANSACTION READ ONLY')
            queryset=OmicsDataset.objects.order_by('id').only('id','dataset_id','omics_type','core_csv_path','full_csv_path')
            if options['limit']:queryset=queryset[:options['limit']]
            datasets=list(queryset)
        def records():
            for dataset in datasets:
                try:
                    full=full_candidate(dataset)
                    row={'dataset_id':dataset.dataset_id,'dataset_pk':dataset.pk,'omics':dataset.omics_type,
                         'core_path':dataset.core_csv_path,'full_path':str(full),'registered_full_path':dataset.full_csv_path}
                    if action=='verify':
                        row.update(verify(dataset.core_csv_path,full,dataset.omics_type))
                        recipe={'omics_type':dataset.omics_type,'columns_json':row.pop('header'),'fill_noncoding':'zero',
                                'version':'extractor-projection-v1','serialization_json':row['serialization']}
                        row['recipe_id']=hashlib.sha256(json.dumps(recipe,ensure_ascii=False,sort_keys=True).encode()).hexdigest();row['recipe']=recipe
                        row.pop('full_header',None)
                    yield row
                except Exception as exc:yield {'dataset_id':dataset.dataset_id,'binding_ready':False,'error':type(exc).__name__+': '+str(exc)}
        emit(options['out'],records())

    def bind(self,options):
        filename=NativePath(options['verified_manifest'])
        if not filename.is_file():raise CommandError('Verified receipt manifest required')
        digest=file_digest(filename)
        if options['apply'] and digest!=options['plan_digest']:raise CommandError('Exact --plan-digest required for apply')
        receipts=[json.loads(line) for line in filename.read_text(encoding='utf-8').splitlines() if line.strip()]
        sidecar=filename.with_name('projection_recipes.json')
        recipes=json.loads(sidecar.read_text(encoding='utf-8')) if sidecar.is_file() else {}
        for row in receipts:
            if 'recipe' not in row:
                try:row['recipe']=recipes[row['recipe_id']]
                except KeyError as exc:raise CommandError('Missing exact frozen recipe sidecar') from exc
        from backend.apps.stoichdb.feature_sources.sampling import is_sampled,approval
        sampled_rows=[r for r in receipts if is_sampled(r)]
        sampling_digest=None
        if sampled_rows:
            if not options['sampling_receipt']:raise CommandError('Explicit random sampling receipt required for metadata-only bindings')
            sampling_digest=approval(options['sampling_receipt'],options['sampling_receipt_digest'])
            if any(r.get('sampling_receipt_sha256')!=sampling_digest for r in sampled_rows):raise CommandError('Sampling authorization does not match source manifest')
        if not receipts or any(not r.get('binding_ready') and not is_sampled(r) for r in receipts):raise CommandError('Every source requires a complete proof or explicitly authorized sampled metadata contract')
        covered={r['dataset_id'] for r in receipts if not r.get('source_library_only') and r.get('representation','csv')=='csv'}
        total=OmicsDataset.objects.count()
        isolated=str(connection.settings_dict['NAME']).startswith(('test_stoich_','codex_workflow_visuals_test_','stoich_corefull_test_'))
        registered=set(OmicsDataset.objects.values_list('dataset_id',flat=True))
        if covered!=registered and not (options['isolated'] and isolated and covered.issubset(registered)):raise CommandError('Manifest does not cover the exact registered dataset set')
        for row in receipts:
            if row.get('source_library_only') and (row.get('release_context')!='source_library' or row['dataset_id']!='source_library:'+alias_key(row['core_path'])):
                raise CommandError('Invalid source-library-only alias identity')
            source=Path(row['full_path']);stat=source.stat()
            expected=row['full_stat']
            if stat.st_size!=expected['size'] or stat.st_mtime_ns!=expected['mtime_ns']:raise CommandError('Full changed after validation: '+row['dataset_id'])
            if row['recipe']['omics_type']!=row['omics']:raise CommandError('Recipe/omics mismatch')
            from backend.apps.stoichdb.feature_sources.registration import validate_receipt
            validate_receipt(row,require_legacy_core=True)
            if not row.get('parquet_match') and row.get('representation')=='parquet':raise CommandError('Legacy Parquet not verified')
            if not is_sampled(row) and row.get('representation','csv')=='csv' and row['core_sha256']!=row['virtual_csv_sha256']:raise CommandError('Core byte identity not verified')
        plan={'action':'bind','manifest_sha256':digest,'receipts':len(receipts),'datasets':len(covered),'apply':options['apply'],'core_deleted':False,
            'exact_equivalence_receipts':len(receipts)-len(sampled_rows),'sampled_metadata_receipts':len(sampled_rows),'sampling_receipt_sha256':sampling_digest,
            'complete_corpus_equivalence_verified':not sampled_rows}
        if not options['apply']:emit(options['out'],[plan]);return
        if not options['journal']:raise CommandError('A new journal path is required')
        journal_path=NativePath(options['journal'])
        if journal_path.exists():raise CommandError('Journal already exists; reconcile it before resuming')
        journal_path.parent.mkdir(parents=True,exist_ok=True)
        with journal_path.open('x',encoding='utf-8',buffering=1) as journal:
            journal.write(json.dumps({'state':'planned',**plan})+'\n')
            # All-or-nothing database switch; filesystem source assets are never written.
            with transaction.atomic():
                datasets={d.dataset_id:d for d in OmicsDataset.objects.select_for_update().only('id','dataset_id','full_csv_path','row_count_full')}
                recipes={};batch=[];full_updates=[];file_additions=[]
                from backend.apps.stoichdb.feature_sources.provenance import frozen_provenance
                provenance=frozen_provenance()
                full_registered=set(FeatureFile.objects.filter(file_type='full').values_list('dataset_id',flat=True))
                # Keep only identifiers in memory; capture an old full image
                # only when its exact binding is actually replaced.
                existing_rows=list(FeatureSourceBinding.objects.values_list('binding_id','dataset_id','release_context','legacy_source_key'))
                existing={item[0] for item in existing_rows}
                natural_ids={(item[1],item[2],item[3]):item[0] for item in existing_rows}
                del existing_rows
                update_fields=[field.name for field in FeatureSourceBinding._meta.fields if field.name not in {'id','binding_id'}]
                def flush():
                    if batch:
                        FeatureSourceBinding.objects.bulk_create(batch,batch_size=256,update_conflicts=True,unique_fields=['binding_id'],update_fields=update_fields)
                        batch.clear()
                for row in receipts:
                    dataset=None if row.get('source_library_only') else datasets[row['dataset_id']];recipe_data=row['recipe'];rid=row['recipe_id']
                    if rid not in recipes:
                        expected={**recipe_data,'schema_hash':hashlib.sha256(json.dumps(recipe_data['columns_json']).encode()).hexdigest(),
                            'extractor_sha256':provenance['extractors'][row['omics']]['sha256']}
                        recipe,created=CoreProjectionRecipe.objects.get_or_create(recipe_id=rid,defaults=expected)
                        if any(getattr(recipe,key)!=value for key,value in expected.items()):raise CommandError('Immutable recipe conflict')
                        recipes[rid]=recipe
                    context=row.get('release_context','');legacy=row['core_path'];key=alias_key(legacy)
                    subject=dataset.dataset_id if dataset is not None else row['dataset_id']
                    canonical_id=hashlib.sha256((subject+'|'+context+'|'+key).encode()).hexdigest()
                    natural=(dataset.pk if dataset is not None else None,context,key)
                    binding_id=natural_ids.get(natural,canonical_id)
                    old=FeatureSourceBinding.objects.filter(binding_id=binding_id).values().first() if binding_id in existing else None
                    if old and (old['dataset_id'],old['release_context'],old['legacy_source_key'])!=natural:raise CommandError('Binding id collides with another logical source')
                    defaults=dict(dataset=dataset,recipe=recipes[rid],release_context=context,legacy_source_key=key,legacy_path=legacy,
                         logical_scope='core',representation=row.get('representation','csv'),full_path=row['full_path'],full_sha256=row['full_sha256'],
                         core_sha256=row['core_sha256'],virtual_csv_sha256=row['virtual_csv_sha256'],logical_cell_hash=row['logical_cell_hash'],
                         row_count=row['rows'],virtual_size=row['virtual_size'],legacy_stat_json=row['core_stat'],full_stat_json=row['full_stat'],
                         receipt_json={k:v for k,v in row.items() if k not in {'recipe','full_header','header'}},status='full_backed')
                    batch.append(FeatureSourceBinding(binding_id=binding_id,**defaults))
                    journal.write(json.dumps({'state':'binding_planned_in_transaction','binding_id':binding_id,'old':old,'new':{**{key:value for key,value in defaults.items() if key not in {'dataset','recipe'}},'dataset_id':dataset.pk if dataset is not None else None,'recipe_id':recipes[rid].pk},'dataset_id':subject},ensure_ascii=False,default=str)+'\n')
                    if len(batch)>=256:flush()
                    if dataset is not None and not context and row.get('representation','csv')=='csv':
                        registered=row.get('registered_full_path','')
                        if dataset.full_csv_path!=registered:raise CommandError('Dataset Full registration changed after inventory')
                        if not dataset.full_csv_path:
                            journal.write(json.dumps({'state':'dataset_full_planned','pk':dataset.pk,'old':'','new':row['full_path'],'old_row_count_full':dataset.row_count_full,'new_row_count_full':row.get('full_rows',row['rows'])},ensure_ascii=False)+'\n')
                            dataset.full_csv_path=row['full_path'];dataset.row_count_full=row.get('full_rows',row['rows']);full_updates.append(dataset)
                        if dataset.pk not in full_registered:
                            file_id=dataset.dataset_id+'__full'
                            file_additions.append(FeatureFile(file_id=file_id,dataset=dataset,file_type='full',path=dataset.full_csv_path,size_bytes=row['full_stat']['size']))
                            full_registered.add(dataset.pk)
                            journal.write(json.dumps({'state':'full_featurefile_planned','dataset_pk':dataset.pk,'file_id':file_id,'path':dataset.full_csv_path},ensure_ascii=False)+'\n')
                flush()
                if full_updates:OmicsDataset.objects.bulk_update(full_updates,['full_csv_path','row_count_full'],batch_size=256)
                if file_additions:FeatureFile.objects.bulk_create(file_additions,batch_size=256)
            journal.write(json.dumps({'state':'committed',**plan})+'\n')
        clear_binding_cache();emit(options['out'],[{**plan,'state':'committed'}])

    def export(self,options):
        recipes={};bindings={}
        for binding in FeatureSourceBinding.objects.filter(status='full_backed').select_related('recipe').iterator(chunk_size=256):
            r=binding.recipe;rid=r.recipe_id
            recipes[rid]={f:getattr(r,f) for f in ['omics_type','columns_json','fill_noncoding','version','serialization_json']}
            record={f.name:getattr(binding,f.name) for f in binding._meta.fields if f.name not in {'id','dataset','recipe','updated_at'}}
            record['recipe_id']=rid
            previous=bindings.get(binding.legacy_source_key)
            if previous and (previous['full_sha256'],previous['recipe_id'],previous['virtual_csv_sha256'])!=(record['full_sha256'],rid,record['virtual_csv_sha256']):raise CommandError('Ambiguous offline alias; release-specific manifest required')
            bindings[binding.legacy_source_key]=record
        target=NativePath(options['out'])
        if target.exists():raise CommandError('Refusing to replace an existing manifest without review')
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps({'format':'stoich-corefull-bindings-v1','recipes':recipes,'bindings':bindings},ensure_ascii=False,separators=(',',':')),encoding='utf-8')

    def restore(self,options):
        from backend.apps.stoichdb.feature_sources.resolver import logical_source
        try:binding=FeatureSourceBinding.objects.get(binding_id=options['binding_id'])
        except FeatureSourceBinding.DoesNotExist as exc:raise CommandError('Exact binding id required') from exc
        target=Path(binding.legacy_path)
        from backend.apps.stoichdb.feature_sources.registration import require_source_root
        require_source_root(target)
        if target.exists():raise CommandError('Existing Core is retained; never overwrite it')
        source=logical_source(binding.legacy_path,binding.release_context)
        if not binding.core_sha256:raise CommandError('Exact restore needs an original per-file byte baseline; sampled acceptance does not provide it')
        if binding.representation=='parquet' and not binding.receipt_json.get('parquet_recovery_match'):
            raise CommandError('Exact Parquet recovery proof is required')
        if not options['apply']:emit(options['out'],[{'action':'restore','binding_id':binding.binding_id,'target':str(target),'apply':False}]);return
        # Rollback only: exact registered source path, exclusive creation, checksum verified.
        h=hashlib.sha256();temporary=target.with_name(target.name+'.restore.tmp')
        try:
            if binding.representation=='parquet':
                from backend.apps.stoichdb.feature_sources.parquet import recover
                with temporary.open('xb') as output:recover(source,output)
                with temporary.open('rb') as stream:
                    for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
            else:
                with temporary.open('xb') as output,source.open_binary() as stream:
                    for block in iter(lambda:stream.read(1024*1024),b''):output.write(block);h.update(block)
            if h.hexdigest()!=binding.core_sha256:raise CommandError('Recovered Core checksum differs')
            if target.exists():raise CommandError('Core appeared during recovery')
            os.link(temporary,target);temporary.unlink()
        finally:
            if temporary.exists():temporary.unlink()
        emit(options['out'],[{'action':'restore','binding_id':binding.binding_id,'checksum':h.hexdigest(),'core_deleted':False}])

    def rollback(self,options):
        filename=NativePath(options['journal'])
        if not filename.is_file():raise CommandError('Exact committed binding journal required')
        digest=file_digest(filename)
        rows=[json.loads(line) for line in filename.read_text(encoding='utf-8').splitlines() if line.strip()]
        if not rows or rows[-1].get('state')!='committed':raise CommandError('Journal has no committed switch; reconcile before rollback')
        if options['apply'] and options['plan_digest']!=digest:raise CommandError('Exact journal --plan-digest required')
        snapshots=[row for row in rows if row.get('state')=='binding_planned_in_transaction']
        plan={'action':'rollback-bindings','journal_sha256':digest,'bindings':len(snapshots),'apply':options['apply'],'source_files_modified':False}
        if not options['apply']:emit(options['out'],[plan]);return
        with transaction.atomic():
            for row in reversed(rows):
                state=row.get('state')
                if state=='binding_planned_in_transaction':
                    current=FeatureSourceBinding.objects.select_for_update().filter(binding_id=row['binding_id']).values().first()
                    if not current or 'new' not in row or any(current.get(key)!=value for key,value in row['new'].items()):
                        raise CommandError('Binding changed after switch; rollback is blocked')
                    if row['old'] is None:FeatureSourceBinding.objects.filter(binding_id=row['binding_id']).delete()
                    else:
                        old={key:value for key,value in row['old'].items() if key not in {'id','binding_id'}}
                        FeatureSourceBinding.objects.filter(binding_id=row['binding_id']).update(**old)
                elif state=='full_featurefile_planned':
                    current=FeatureFile.objects.filter(file_id=row['file_id'],dataset_id=row['dataset_pk']).first()
                    if not current or current.path!=row.get('path'):raise CommandError('Full FeatureFile changed after switch')
                    current.delete()
                elif state=='dataset_full_planned':
                    dataset=OmicsDataset.objects.select_for_update().get(pk=row['pk'])
                    if dataset.full_csv_path!=row['new']:raise CommandError('Dataset Full changed after switch')
                    if dataset.row_count_full!=row.get('new_row_count_full',dataset.row_count_full):raise CommandError('Dataset Full count changed after switch')
                    dataset.full_csv_path=row['old'];dataset.row_count_full=row.get('old_row_count_full',dataset.row_count_full)
                    dataset.save(update_fields=['full_csv_path','row_count_full'])
        clear_binding_cache();emit(options['out'],[{**plan,'state':'rolled_back'}])
