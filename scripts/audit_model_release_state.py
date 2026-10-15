from django.db import connection


QUERIES = {
    'datasets_total': """
        select count(*)
        from stoichdb_omicsdataset d
        join stoichdb_species s on d.species_id = s.id
        where s.source_database = 'model_organism_release:model_organisms_20260731_v1'
    """,
    'summary_core_missing': """
        select count(*)
        from stoichdb_omicsdataset d
        join stoichdb_species s on d.species_id = s.id
        where s.source_database = 'model_organism_release:model_organisms_20260731_v1'
          and not (d.summary_payload ? 'scopes' and d.summary_payload->'scopes' ? 'core')
    """,
    'summary_full_missing': """
        select count(*)
        from stoichdb_omicsdataset d
        join stoichdb_species s on d.species_id = s.id
        where s.source_database = 'model_organism_release:model_organisms_20260731_v1'
          and not (d.summary_payload ? 'scopes' and d.summary_payload->'scopes' ? 'full')
    """,
    'analysis_core_missing': """
        select count(*)
        from stoichdb_omicsdataset d
        join stoichdb_species s on d.species_id = s.id
        where s.source_database = 'model_organism_release:model_organisms_20260731_v1'
          and not (d.analysis_payload ? 'scopes' and d.analysis_payload->'scopes' ? 'core')
    """,
    'analysis_full_missing': """
        select count(*)
        from stoichdb_omicsdataset d
        join stoichdb_species s on d.species_id = s.id
        where s.source_database = 'model_organism_release:model_organisms_20260731_v1'
          and not (d.analysis_payload ? 'scopes' and d.analysis_payload->'scopes' ? 'full')
    """,
    'precomputed_summary_missing': """
        select count(*)
        from stoichdb_omicsdataset d
        join stoichdb_species s on d.species_id = s.id
        where s.source_database = 'model_organism_release:model_organisms_20260731_v1'
          and coalesce((d.summary_payload->'scopes'->'core'->>'precomputed_from_real_rows'), '') <> 'true'
    """,
    'cross_missing': """
        select count(*)
        from stoichdb_species
        where source_database = 'model_organism_release:model_organisms_20260731_v1'
          and (cross_omics_payload is null or cross_omics_payload = '{}'::jsonb)
    """,
    'fingerprint_missing': """
        select count(*)
        from stoichdb_species
        where source_database = 'model_organism_release:model_organisms_20260731_v1'
          and (fingerprint is null or fingerprint = '{}'::jsonb)
    """,
    'cross_real_flag_missing': """
        select count(*)
        from stoichdb_species
        where source_database = 'model_organism_release:model_organisms_20260731_v1'
          and coalesce((cross_omics_payload->>'precomputed_from_real_rows'), '') <> 'true'
    """,
}


out = {}
with connection.cursor() as cursor:
    for key, query in QUERIES.items():
        cursor.execute(query)
        out[key] = cursor.fetchone()[0]

print(out)
