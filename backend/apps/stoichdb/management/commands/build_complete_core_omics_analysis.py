from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from backend.apps.stoichdb.models import Species
from backend.apps.stoichdb.services import build_complete_core_omics_payload


class Command(BaseCommand):
    help = 'Build on-demand complete-core omics analysis JSON artifacts without writing database rows.'

    def add_arguments(self, parser):
        parser.add_argument('--species-id', action='append', default=[], help='Species ID. Repeat for multiple species.')
        parser.add_argument('--query', default='', help='Case-insensitive species display/species_id query used when species-id is omitted.')
        parser.add_argument('--omics', choices=['genome', 'transcriptome', 'proteome'], action='append', default=[])
        parser.add_argument('--output-root', required=True)
        parser.add_argument('--scatter-limit', type=int, default=5000)

    def handle(self, *args, **options):
        species_ids = [str(item).strip() for item in options['species_id'] if str(item).strip()]
        if not species_ids:
            query = str(options.get('query') or '').strip()
            qs = Species.objects.all().order_by('display_name', 'species_id')
            if query:
                qs = qs.filter(Q(display_name__icontains=query) | Q(species_id__icontains=query))
            species_ids = list(qs.values_list('species_id', flat=True)[:8])
        if not species_ids:
            raise CommandError('No species selected.')

        omics_list = options['omics'] or ['genome', 'transcriptome', 'proteome']
        output_root = Path(options['output_root'])
        output_root.mkdir(parents=True, exist_ok=True)
        manifest = {
            'pipeline': 'complete_core_omics_analysis',
            'writes_database': False,
            'primary_scope': 'core',
            'full_supplement_policy': 'full CSV is used only to supplement missing module fields when available',
            'items': [],
        }
        for species_id in species_ids:
            for omics in omics_list:
                try:
                    payload = build_complete_core_omics_payload(
                        species_id,
                        omics,
                        scatter_limit=options['scatter_limit'],
                    )
                except Exception as exc:  # pragma: no cover - diagnostic command
                    self.stderr.write(f'{species_id}/{omics}: {type(exc).__name__}: {exc}')
                    continue
                target = output_root / species_id / omics / 'complete_core'
                target.mkdir(parents=True, exist_ok=True)
                for key in ['summary', 'analysis', 'source']:
                    (target / f'{key}.json').write_text(
                        json.dumps(payload.get(key) or {}, ensure_ascii=False, indent=2),
                        encoding='utf-8',
                    )
                summary = payload.get('summary') or {}
                manifest['items'].append({
                    'species_id': species_id,
                    'omics': omics,
                    'scope': 'core',
                    'compute_mode': 'complete_core',
                    'row_count': summary.get('row_count'),
                    'output_dir': str(target),
                })
                self.stdout.write(f'{species_id}/{omics}/complete_core: rows={summary.get("row_count")}')
        (output_root / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        self.stdout.write(self.style.SUCCESS(f'Complete-core analysis artifacts written to {output_root}'))
