from django.db import migrations


def create_postgres_indexes(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    schema_editor.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm;')
    schema_editor.execute(
        'CREATE INDEX IF NOT EXISTS stoichdb_species_searchable_text_trgm '
        'ON stoichdb_species USING gin (searchable_text gin_trgm_ops);'
    )
    schema_editor.execute(
        'CREATE INDEX IF NOT EXISTS stoichdb_omicsdataset_searchable_text_trgm '
        'ON stoichdb_omicsdataset USING gin (searchable_text gin_trgm_ops);'
    )
    schema_editor.execute(
        'CREATE INDEX IF NOT EXISTS stoichdb_entityrecord_searchable_text_trgm '
        'ON stoichdb_entityrecord USING gin (searchable_text gin_trgm_ops);'
    )


def drop_postgres_indexes(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    schema_editor.execute('DROP INDEX IF EXISTS stoichdb_entityrecord_searchable_text_trgm;')
    schema_editor.execute('DROP INDEX IF EXISTS stoichdb_omicsdataset_searchable_text_trgm;')
    schema_editor.execute('DROP INDEX IF EXISTS stoichdb_species_searchable_text_trgm;')


class Migration(migrations.Migration):

    dependencies = [
        ('stoichdb', '0002_datarelease'),
    ]

    operations = [
        migrations.RunPython(create_postgres_indexes, drop_postgres_indexes),
    ]
