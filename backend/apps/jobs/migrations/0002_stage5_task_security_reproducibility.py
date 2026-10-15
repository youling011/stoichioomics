from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('jobs_app', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='analysisjob',
            name='status',
            field=models.CharField(choices=[
                ('CREATED', 'Created'),
                ('UPLOADING', 'Uploading'),
                ('READY', 'Ready'),
                ('RUNNING', 'Running'),
                ('SUCCEEDED', 'Succeeded'),
                ('FAILED', 'Failed'),
                ('CANCEL_REQUESTED', 'Cancel requested'),
                ('CANCELLED', 'Cancelled'),
            ], default='CREATED', max_length=32),
        ),
        migrations.AddField(
            model_name='analysisjob',
            name='access_token_hash',
            field=models.CharField(blank=True, default='', max_length=128),
        ),
        migrations.AddField(
            model_name='analysisjob',
            name='run_attempts',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='analysisjob',
            name='log_path',
            field=models.CharField(blank=True, default='', max_length=1024),
        ),
        migrations.AddField(
            model_name='analysisjob',
            name='reproducibility_path',
            field=models.CharField(blank=True, default='', max_length=1024),
        ),
    ]
