from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = []

    operations = [
        migrations.CreateModel(
            name='AnalysisJob',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('job_id', models.CharField(max_length=64, unique=True)),
                ('name', models.CharField(blank=True, default='', max_length=255)),
                ('module_name', models.CharField(default='hvg', max_length=64)),
                ('status', models.CharField(choices=[('CREATED', 'Created'), ('UPLOADING', 'Uploading'), ('READY', 'Ready'), ('RUNNING', 'Running'), ('SUCCEEDED', 'Succeeded'), ('FAILED', 'Failed')], default='CREATED', max_length=32)),
                ('pipeline_type', models.CharField(blank=True, default='full', max_length=32)),
                ('input_mode', models.CharField(blank=True, default='', max_length=64)),
                ('base_dir', models.CharField(blank=True, default='', max_length=1024)),
                ('workspace_path', models.CharField(blank=True, default='', max_length=1024)),
                ('config_path', models.CharField(blank=True, default='', max_length=1024)),
                ('recommended_mode', models.CharField(blank=True, default='', max_length=128)),
                ('metadata_json', models.JSONField(blank=True, default=dict)),
                ('error_message', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name='JobFile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('file_name', models.CharField(max_length=512)),
                ('relative_path', models.CharField(max_length=1024)),
                ('category', models.CharField(blank=True, default='raw', max_length=64)),
                ('uploaded_at', models.DateTimeField(auto_now_add=True)),
                ('job', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='files', to='jobs_app.analysisjob')),
            ],
            options={'unique_together': {('job', 'relative_path')}},
        ),
    ]
