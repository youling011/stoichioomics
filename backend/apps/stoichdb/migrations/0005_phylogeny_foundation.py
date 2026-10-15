# Generated manually for the P0/P1 phylogeny foundation layer.

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('stoichdb', '0004_function_annotations'),
    ]

    operations = [
        migrations.CreateModel(
            name='PhylogenyRelease',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('release_id', models.CharField(max_length=128, unique=True)),
                ('label', models.CharField(max_length=255)),
                ('scope', models.CharField(default='protists', max_length=64)),
                ('tree_kind', models.CharField(default='taxonomy_reference_topology', max_length=128)),
                ('source', models.CharField(blank=True, default='', max_length=255)),
                ('source_version', models.CharField(blank=True, default='', max_length=255)),
                ('method', models.TextField(blank=True, default='')),
                ('rooted', models.BooleanField(default=True)),
                ('branch_length_unit', models.CharField(blank=True, default='none', max_length=64)),
                ('tip_count', models.PositiveIntegerField(default=0)),
                ('analysis_eligible', models.BooleanField(default=False)),
                ('topology_eligible', models.BooleanField(default=True)),
                ('tree_path', models.CharField(blank=True, default='', max_length=1024)),
                ('tree_sha256', models.CharField(blank=True, default='', max_length=64)),
                ('tip_map_path', models.CharField(blank=True, default='', max_length=1024)),
                ('tip_map_sha256', models.CharField(blank=True, default='', max_length=64)),
                ('metadata_json', models.JSONField(blank=True, default=dict)),
                ('is_active', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['-created_at', '-id'],
                'indexes': [
                    models.Index(fields=['release_id'], name='stoichdb_ph_release_69d6ca_idx'),
                    models.Index(fields=['scope', 'is_active'], name='stoichdb_ph_scope_7c0d1d_idx'),
                    models.Index(fields=['tree_kind'], name='stoichdb_ph_tree_ki_e37b18_idx'),
                ],
            },
        ),
        migrations.CreateModel(
            name='PhylogenyQCMetric',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('metric', models.CharField(max_length=128)),
                ('value', models.CharField(blank=True, default='', max_length=128)),
                ('status', models.CharField(default='pass', max_length=32)),
                ('detail', models.TextField(blank=True, default='')),
                ('release', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='qc_metrics', to='stoichdb.phylogenyrelease')),
            ],
            options={
                'indexes': [
                    models.Index(fields=['metric'], name='stoichdb_ph_metric_53fd38_idx'),
                    models.Index(fields=['status'], name='stoichdb_ph_status_73e11b_idx'),
                ],
                'unique_together': {('release', 'metric')},
            },
        ),
        migrations.CreateModel(
            name='PhylogenyTipMap',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('species_id_text', models.CharField(max_length=128)),
                ('tip_label', models.CharField(max_length=255)),
                ('display_name', models.CharField(blank=True, default='', max_length=255)),
                ('tax_id', models.CharField(blank=True, default='', max_length=64)),
                ('full_lineage', models.TextField(blank=True, default='')),
                ('rank_json', models.JSONField(blank=True, default=dict)),
                ('mapping_status', models.CharField(default='mapped', max_length=64)),
                ('topology_eligible', models.BooleanField(default=True)),
                ('pgls_eligible', models.BooleanField(default=False)),
                ('pgls_blocker', models.CharField(blank=True, default='', max_length=255)),
                ('release', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tip_maps', to='stoichdb.phylogenyrelease')),
                ('species', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='phylogeny_tip_maps', to='stoichdb.species')),
            ],
            options={
                'indexes': [
                    models.Index(fields=['species_id_text'], name='stoichdb_ph_species_4b808e_idx'),
                    models.Index(fields=['tip_label'], name='stoichdb_ph_tip_lab_9fd326_idx'),
                    models.Index(fields=['tax_id'], name='stoichdb_ph_tax_id_0f5fbb_idx'),
                    models.Index(fields=['mapping_status'], name='stoichdb_ph_mapping_396bb7_idx'),
                ],
                'unique_together': {('release', 'species_id_text')},
            },
        ),
    ]
