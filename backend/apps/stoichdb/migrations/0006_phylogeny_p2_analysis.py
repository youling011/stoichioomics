# Generated manually for P2 phylogeny analysis services.

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('stoichdb', '0005_phylogeny_foundation'),
    ]

    operations = [
        migrations.CreateModel(
            name='ComparativeAnalysisRun',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('analysis_id', models.CharField(max_length=160, unique=True)),
                ('analysis_type', models.CharField(default='pgls', max_length=64)),
                ('formula', models.CharField(blank=True, default='', max_length=255)),
                ('n_species', models.PositiveIntegerField(default=0)),
                ('status', models.CharField(default='pending', max_length=64)),
                ('blocker', models.CharField(blank=True, default='', max_length=255)),
                ('result_json', models.JSONField(blank=True, default=dict)),
                ('method_metadata', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('release', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='comparative_runs', to='stoichdb.phylogenyrelease')),
            ],
            options={
                'indexes': [
                    models.Index(fields=['analysis_id'], name='stoichdb_co_analysi_ddaf02_idx'),
                    models.Index(fields=['analysis_type'], name='stoichdb_co_analysi_647134_idx'),
                    models.Index(fields=['status'], name='stoichdb_co_status_ea6fd5_idx'),
                ],
            },
        ),
        migrations.CreateModel(
            name='PhylogeneticSignalResult',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('analysis_id', models.CharField(max_length=160, unique=True)),
                ('feature', models.CharField(max_length=128)),
                ('n_species', models.PositiveIntegerField(default=0)),
                ('lambda_value', models.FloatField(blank=True, null=True)),
                ('p_value', models.FloatField(blank=True, null=True)),
                ('q_value', models.FloatField(blank=True, null=True)),
                ('status', models.CharField(default='pending', max_length=64)),
                ('blocker', models.CharField(blank=True, default='', max_length=255)),
                ('result_json', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('release', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='signal_results', to='stoichdb.phylogenyrelease')),
            ],
            options={
                'indexes': [
                    models.Index(fields=['feature'], name='stoichdb_ph_feature_986e0a_idx'),
                    models.Index(fields=['status'], name='stoichdb_ph_status_0922f0_idx'),
                    models.Index(fields=['analysis_id'], name='stoichdb_ph_analysi_6e0cde_idx'),
                ],
            },
        ),
    ]
