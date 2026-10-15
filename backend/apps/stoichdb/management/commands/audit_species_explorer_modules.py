from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from backend.apps.stoichdb import services


KEY_CHARTS: dict[str, dict[str, list[str]]] = {
    'genome': {
        'G1': ['composition_profile'],
        'G2': ['promoter_exon_scatter'],
        'G3': ['gc_skew_histogram', 'cumulative_gc_skew'],
        'G4': ['heatmap', 'distance_histogram'],
        'G5': ['codon_heatmap', 'codon_entropy_histogram'],
        'G6': ['coordinate_profile', 'score_histogram'],
        'G7': ['biotype_counts', 'length_vs_gc_scatter'],
        'G8': ['species_pca', 'distance_matrix'],
    },
    'transcriptome': {
        'T1': ['gc_histogram', 'base_composition'],
        'T2': ['element_profile', 'resource_projection'],
        'T3': ['dinuc_heatmap', 'stability_histogram'],
        'T4': ['biotype_counts', 'length_by_biotype'],
        'T5': ['orf_length_histogram', 'orf_vs_transcript_scatter'],
        'T6': ['codon_heatmap', 'codon_entropy_histogram'],
        'T7': ['aa_composition', 'protein_projection'],
        'T8': ['species_pca', 'distance_matrix'],
    },
    'proteome': {
        'P1': ['length_histogram', 'quality_counts'],
        'P2': ['element_profile', 'n_histogram'],
        'P3': ['ns_tradeoff_scatter'],
        'P4': ['aa_composition', 'aa_projection'],
        'P5': ['pi_histogram', 'gravy_histogram'],
        'P6': ['secondary_structure_profile', 'flex_access_scatter'],
        'P7': ['zc_histogram', 'redox_gravy_scatter'],
        'P8': ['species_pca', 'distance_matrix'],
    },
}


def payload_count(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        for key in ('points', 'values', 'centers', 'counts', 'rows'):
            if isinstance(value.get(key), list):
                return len(value[key])
        return sum(payload_count(item) for item in value.values())
    return 1 if value not in (None, '') else 0


class Command(BaseCommand):
    help = 'Read-only regression audit for Species Explorer omics module chart payloads.'

    def add_arguments(self, parser):
        parser.add_argument('--species-id', action='append', default=[])
        parser.add_argument('--omics', choices=['genome', 'transcriptome', 'proteome'], action='append', default=[])
        parser.add_argument('--scope', choices=['core', 'full'], default='core')
        parser.add_argument('--compute', choices=['stored', 'complete_core', 'full'], default='stored')
        parser.add_argument('--fail-on-empty', action='store_true')
        parser.add_argument('--publication-grade', action='store_true')
        parser.add_argument('--fail-on-partial-aggregate', action='store_true')

    def handle(self, *args, **options):
        species_ids = [str(item).strip() for item in options['species_id'] if str(item).strip()]
        if not species_ids:
            species_ids = sorted(services._home_representative_species_id_set())[:8]
        omics_list = options['omics'] or ['genome', 'transcriptome', 'proteome']
        failures: list[str] = []
        for species_id in species_ids:
            self.stdout.write(f'SPECIES {species_id}')
            for omics in omics_list:
                try:
                    payload = services.get_omics_bundle(
                        species_id,
                        omics,
                        scope=options['scope'],
                        compute=options['compute'],
                    )
                except Exception as exc:  # pragma: no cover - command diagnostic path
                    message = f'{species_id}/{omics}: request failed: {type(exc).__name__}: {exc}'
                    failures.append(message)
                    self.stdout.write(f'  {message}')
                    continue
                summary = payload.get('summary') or {}
                suite = summary.get(f'{omics}_module_suite') or {}
                modules = {item.get('id'): item for item in suite.get('modules') or [] if isinstance(item, dict)}
                self.stdout.write(
                    f'  {omics}: rows={summary.get("row_count")} modules={len(modules)} '
                    f'scope={suite.get("scope") or options["scope"]}'
                )
                for module_id, fields in KEY_CHARTS[omics].items():
                    module = modules.get(module_id) or {}
                    counts = {field: payload_count(module.get(field)) for field in fields}
                    self.stdout.write(f'    {module_id} {module.get("status", "missing")} {counts}')
                    if options.get('publication_grade'):
                        meta = module.get('ordination_meta') or module.get('promoter_exon_scatter_meta') or module.get('length_vs_gc_scatter_meta') or {}
                        source_n = (
                            meta.get('fit_n')
                            or meta.get('n_source_rows')
                            or (summary.get('method_metadata') or {}).get('complete_core_v2', {}).get('row_count_source')
                            or summary.get('row_count')
                        )
                        display_n = meta.get('display_n') or meta.get('n_points') or max(counts.values() or [0])
                        missing_fields = module.get('missing_fields') or []
                        self.stdout.write(
                            f'      publication source_n={source_n} display_n={display_n} '
                            f'missing_fields={len(missing_fields)} sampling={meta.get("sampling_policy", "aggregate_or_not_reported")}'
                        )
                        if options.get('fail_on_partial_aggregate') and options['compute'] == 'complete_core':
                            row_count = int(summary.get('row_count') or 0)
                            source_int = int(source_n or 0)
                            if source_int and row_count and source_int < row_count and display_n == source_int:
                                failures.append(f'{species_id}/{omics}/{module_id}: source_n {source_int} < row_count {row_count}')
                    for field, count in counts.items():
                        if count <= 0:
                            failures.append(f'{species_id}/{omics}/{module_id}.{field} is empty')
        if failures and options['fail_on_empty']:
            raise CommandError('\n'.join(failures))
        self.stdout.write(self.style.SUCCESS(f'Audit complete: {len(failures)} empty required chart payloads.'))
