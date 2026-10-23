"""Synthetic fixtures ONLY: requires an explicit test database and opt-in."""
import csv
import os
from pathlib import Path


def main():
    if os.environ.get('STOICH_VALIDATION_ONLY') != '1':
        raise RuntimeError('Synthetic fixture creation requires STOICH_VALIDATION_ONLY=1')
    import django
    django.setup()
    from django.conf import settings
    if not settings.DATABASES['default']['NAME'].startswith('test_stoich_deploy_'):
        raise RuntimeError('Refusing to write a non-validation database')
    from backend.apps.stoichdb.models import Species, OmicsDataset, FeatureFile, SchemaRegistry
    if Species.objects.exists():
        raise RuntimeError('Fixture requires an empty isolated database')
    species = Species.objects.create(species_id='deployment_fixture', display_name='Synthetic deployment fixture',
        domain='Bacteria', has_genome=True, has_transcriptome=True, has_proteome=True)
    root = Path(settings.STOICHDB_DATA_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    tables = {
        'genome': [['species_id', 'gene_id', 'gene_len_nt', 'locus_gc_percent'], ['deployment_fixture', 'g1', 100, 40], ['deployment_fixture', 'g2', 200, 50]],
        'transcriptome': [['species_id', 'transcript_id', 'length_nt', 'gc_content'], ['deployment_fixture', 't1', 100, 40], ['deployment_fixture', 't2', 200, 50]],
    }
    for omics in ['genome', 'transcriptome', 'proteome']:
        path = root / (omics + '.core.csv')
        if omics == 'proteome':
            path.write_bytes((Path(settings.BASE_DIR) / 'backend/apps/stoichdb/tests/fixtures/proteome_viz_core12.csv').read_bytes())
            with path.open(encoding='utf-8-sig') as handle:
                rows = list(csv.reader(handle))
        else:
            rows = tables[omics]
            with path.open('w', newline='', encoding='utf-8') as handle:
                csv.writer(handle).writerows(rows)
        ds = OmicsDataset.objects.create(species=species, dataset_id='deployment_fixture__' + omics,
            omics_type=omics, core_csv_path=str(path), full_csv_path=str(path),
            row_count_core=len(rows) - 1, row_count_full=len(rows) - 1)
        FeatureFile.objects.create(file_id='deployment_fixture__' + omics, dataset=ds,
            file_type='core', path=str(path), size_bytes=path.stat().st_size)
        SchemaRegistry.objects.create(schema_id='deployment_fixture__' + omics, omics_type=omics,
            product_type='core', status='active', columns_json=[{'name': name, 'dtype': 'string' if name.endswith('_id') else 'float'} for name in rows[0]])
    print('Synthetic fixture: 1 species / 3 datasets; no business data imported')


if __name__ == '__main__':
    main()
