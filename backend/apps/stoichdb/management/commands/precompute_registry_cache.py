from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand
from django.db.models import Count, Max, Min, Sum

from backend.apps.stoichdb import services
from backend.apps.stoichdb.models import OmicsDataset, Species


def _histogram(values: list[float], bins: int = 24) -> dict[str, Any]:
    numeric = sorted(float(value) for value in values if value is not None)
    if not numeric:
        return {'centers': [], 'counts': [], 'n': 0}
    return services._histogram_payload(numeric, bins=bins)


class Command(BaseCommand):
    help = 'Materialize lightweight registry facets, omics summaries, distributions, and fingerprint scatter samples.'

    def add_arguments(self, parser):
        default_path = getattr(services, 'PRECOMPUTED_REGISTRY_PATH', None)
        if default_path is None:
            default_path = Path('runtime') / 'stoich_registry_cache.json'
        parser.add_argument('--out', default=str(default_path))

    def handle(self, *args, **options):
        output_path = Path(options['out'])
        output_path.parent.mkdir(parents=True, exist_ok=True)

        model_species_ids = set(Species.objects.filter(is_featured=True).values_list('species_id', flat=True))
        species_count = Species.objects.count()
        dataset_count = OmicsDataset.objects.count()

        source_databases = [
            row for row in Species.objects.values('source_database').annotate(count=Count('id')).order_by('source_database')
            if services._clean_meta_value(row.get('source_database'))
        ]
        domains = [
            row for row in Species.objects.values('domain').annotate(count=Count('id')).order_by('domain')
            if services._clean_meta_value(row.get('domain'))
        ]
        clades = [
            row for row in Species.objects.values('clade').annotate(count=Count('id')).order_by('clade')
            if services._clean_meta_value(row.get('clade'))
        ][:200]
        habitats = [
            row for row in Species.objects.values('habitat').annotate(count=Count('id')).order_by('habitat')
            if services._clean_meta_value(row.get('habitat'))
        ][:200]

        genome_range = Species.objects.aggregate(min_genome_size=Min('genome_size_mb'), max_genome_size=Max('genome_size_mb'))
        fingerprint_keys: set[str] = set()
        genome_size_values: list[float] = []
        scatter_points: list[dict[str, Any]] = []
        for row in Species.objects.only('species_id', 'display_name', 'genome_size_mb', 'fingerprint').iterator(chunk_size=512):
            fingerprint = row.fingerprint or {}
            fingerprint_keys.update(str(key) for key in fingerprint.keys())
            if row.genome_size_mb is not None:
                genome_size_values.append(float(row.genome_size_mb))
            if len(scatter_points) < 1200:
                scatter_points.append({
                    'species_id': row.species_id,
                    'display_name': row.display_name,
                    'genome_size_mb': row.genome_size_mb,
                    'genome_gc': services._safe_num(fingerprint.get('genome_gc')),
                    'transcript_coupling': services._safe_num(fingerprint.get('transcript_coupling')),
                    'proteome_pi': services._safe_num(fingerprint.get('proteome_pi')),
                    'is_model_organism': row.species_id in model_species_ids,
                })

        grouped_datasets = list(
            OmicsDataset.objects.values('omics_type')
            .annotate(count=Count('id'), core_rows=Sum('row_count_core'), full_rows=Sum('row_count_full'))
            .order_by('omics_type')
        )
        row_counts_by_omics: dict[str, list[float]] = defaultdict(list)
        indexed_feature_rows = 0
        for omics, core_rows, full_rows in OmicsDataset.objects.values_list('omics_type', 'row_count_core', 'row_count_full').iterator(chunk_size=1024):
            core = int(core_rows or 0)
            full = int(full_rows or 0)
            indexed_feature_rows += max(core, full)
            row_counts_by_omics[str(omics)].append(float(max(core, full)))

        card_accumulator: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        strategy_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        scatter_samples: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
        for dataset in OmicsDataset.objects.only('omics_type', 'summary_payload').iterator(chunk_size=128):
            omics = str(dataset.omics_type)
            summary = dataset.summary_payload or {}
            for field, card in (summary.get('feature_cards') or {}).items():
                mean_value = services._safe_num((card or {}).get('mean'))
                if mean_value is not None:
                    samples = card_accumulator[omics][str(field)]
                    if len(samples) < 5000:
                        samples.append(float(mean_value))
            for item in summary.get('strategy_breakdown') or []:
                cluster = str(item.get('cluster') or '').strip()
                count = int(services._safe_num(item.get('count')) or 0)
                if cluster:
                    strategy_counts[omics][cluster] += count
            for scatter_name, points in (summary.get('scatter') or {}).items():
                if not isinstance(points, list):
                    continue
                target = scatter_samples[omics][str(scatter_name)]
                if len(target) < 1200:
                    target.extend(item for item in points[:1200 - len(target)] if isinstance(item, dict))

        omics_summary = {}
        for row in grouped_datasets:
            omics = str(row['omics_type'])
            omics_summary[omics] = {
                'dataset_count': int(row['count'] or 0),
                'core_rows': int(row['core_rows'] or 0),
                'full_rows': int(row['full_rows'] or 0),
                'row_count_distribution': _histogram(row_counts_by_omics.get(omics, [])),
                'feature_card_mean_samples': {
                    field: {
                        'n_datasets': len(values),
                        'mean_of_dataset_means': round(sum(values) / len(values), 6) if values else None,
                        'distribution': _histogram(values, bins=18),
                    }
                    for field, values in sorted(card_accumulator.get(omics, {}).items())
                },
                'strategy_breakdown': [
                    {'cluster': cluster, 'count': count}
                    for cluster, count in sorted(strategy_counts.get(omics, {}).items(), key=lambda item: (-item[1], item[0]))
                ],
            }

        payload = {
            'artifact': 'stoich_registry_cache',
            'version': 'registry_cache_v1',
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'release_id': services.current_release().get('release_id', ''),
            'stats': {
                'species_count': species_count,
                'dataset_count': dataset_count,
                'model_species_count': len(model_species_ids),
                'indexed_feature_rows': indexed_feature_rows,
                'omics_breakdown': [
                    {'omics_type': str(row['omics_type']), 'count': int(row['count'] or 0)}
                    for row in grouped_datasets
                ],
            },
            'facets': {
                'source_databases': source_databases,
                'domains': domains,
                'clades': clades,
                'habitats': habitats,
                'omics_breakdown': [
                    {'omics': str(row['omics_type']), 'count': int(row['count'] or 0)}
                    for row in grouped_datasets
                ],
                'ranges': {
                    'genome_size_mb': {
                        'min': round(float(genome_range.get('min_genome_size') or 0), 4),
                        'max': round(float(genome_range.get('max_genome_size') or 0), 4),
                    }
                },
                'fingerprint_keys': sorted(fingerprint_keys),
                'model_species_count': len(model_species_ids),
            },
            'distributions': {
                'genome_size_mb': _histogram(genome_size_values),
            },
            'omics_summary': omics_summary,
            'scatter_samples': {
                'species_fingerprint': scatter_points,
                'dataset_feature_samples': {
                    omics: dict(scatter_by_omics)
                    for omics, scatter_by_omics in scatter_samples.items()
                },
            },
        }

        temp_path = output_path.with_suffix(output_path.suffix + '.tmp')
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
        temp_path.replace(output_path)
        self.stdout.write(self.style.SUCCESS(
            f'Precomputed registry cache: {output_path} ({species_count} species, {dataset_count} datasets, {len(model_species_ids)} model organisms)'
        ))
