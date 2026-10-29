from __future__ import annotations
from backend.apps.stoichdb.feature_sources import io as feature_io

import csv
import gc
import json
import math
from backend.apps.common.host_paths import Path
from typing import Any

import numpy as np
import pandas as pd
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from scripts.build_stoichdb_from_real import (
    build_analysis,
    build_cross_omics,
    build_summary,
    derive_fingerprint,
    normalize_rows,
    percentile_summary,
)

from backend.apps.stoichdb.models import (
    AnalysisArtifact,
    DataRelease,
    OmicsDataset,
    Species,
)


RELEASE_ID_DEFAULT = 'model_organisms_20260731_v1'
GROUP_LABELS = {
    'bacteria': 'Bacteria',
    'fungi': 'Fungi',
    'metazoa': 'Metazoa',
    'plants': 'Plants',
    'protists': 'Protists',
    'vertebrates': 'Vertebrates',
}
OMICS_ORDER = ('genome', 'transcriptome', 'proteome')


def _workspace_root() -> Path:
    return Path(settings.BASE_DIR).resolve().parent.parent


def _default_model_list() -> Path:
    root = _workspace_root()
    for directory in root.iterdir():
        if not directory.is_dir():
            continue
        for candidate in feature_io.logical_glob(directory, '*.csv'):
            try:
                with feature_io.open_source(candidate, 'r', encoding='utf-8-sig', newline='') as handle:
                    fields = set(next(csv.reader(handle), []))
            except (OSError, UnicodeError):
                continue
            if {'species_id', 'expected_model_group'}.issubset(fields):
                return candidate
    raise FileNotFoundError('Could not locate the model-organism whitelist CSV.')


def _json_safe(value: Any) -> Any:
    """Convert pandas/numpy values to values accepted by JSONField."""
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if pd.isna(value) if not isinstance(value, (str, bytes, bool, int)) else False:
        return None
    return value


def _selected_model_row(row: dict[str, Any]) -> bool:
    hard_fail = str(row.get('hard_fail') or '').strip().lower()
    return hard_fail not in {'1', 'true', 'yes', 'y'} and not str(row.get('exclude_reason') or '').strip()


def _read_model_rows(path: Path) -> dict[str, dict[str, Any]]:
    if not feature_io.source_exists(path):
        raise CommandError(f'Model organism list does not exist: {path}')
    with feature_io.open_source(path, 'r', encoding='utf-8-sig', newline='') as handle:
        rows = [dict(row) for row in csv.DictReader(handle)]
    output: dict[str, dict[str, Any]] = {}
    for row in rows:
        species_id = str(row.get('species_id') or '').strip()
        if species_id and _selected_model_row(row):
            output[species_id] = row
    if not output:
        raise CommandError(f'No selected model organisms found in {path}')
    return output


def _cross_frame(frame: pd.DataFrame, omics: str) -> pd.DataFrame:
    candidates = {
        'genome': [
            'gene_id', 'entity_id', 'gene_name', 'strategy_cluster',
            'exon_gc_percent', 'promoter_gc_percent', 'exon_atoms_N_per_base',
            'gc_delta_promoter_minus_exon', 'promoter_exon_gc_delta',
        ],
        'transcriptome': [
            'gene_id', 'entity_id', 'strategy_cluster', 'gc_content',
            'gc_percent_display', 'atoms_per_nt_N',
        ],
        'proteome': [
            'ensembl_gene_id', 'gene_id', 'entity_id', 'strategy_cluster',
            'N_atoms_per_aa', 'pI', 'gravy',
        ],
    }[omics]
    columns = [column for column in candidates if column in frame.columns]
    return frame[columns].copy()


_MODULE_PROJECTION_EXACT = {
    'genome': {
        'species_id', 'gene_id', 'entity_id', 'gene_name', 'gene_symbol', 'source_gene_id',
        'strategy_cluster', 'seqid', 'seq_region', 'start', 'end', 'start_1', 'end_1', 'strand',
        'biotype', 'gene_biotype', 'exon_gc_percent', 'promoter_gc_percent',
        'exon_atoms_N_per_base', 'promoter_atoms_N_per_base', 'exon_atoms_P_per_base',
        'promoter_atoms_P_per_base', 'locus_gc_percent', 'locus_atoms_N_per_base',
        'locus_atoms_P_per_base', 'locus_shannon_entropy_acgt', 'exon_shannon_entropy_acgt',
        'promoter_shannon_entropy_acgt', 'locus_gc_skew', 'locus_at_skew', 'exon_gc_skew',
        'promoter_gc_skew', 'gc1_percent', 'gc2_percent', 'gc3_percent', 'codon_entropy_bits',
        'codon_total_valid', 'aa_total_20', 'coding_valid', 'stoich_island_score',
        'transcript_count', 'upstream_intergenic_bp', 'downstream_intergenic_bp',
        'upstream_overlap_bp', 'downstream_overlap_bp', 'locus_dinuc_total_valid',
        'promoter_dinuc_total_valid', 'locus_ratio_C_N', 'locus_ratio_N_P',
    },
    'transcriptome': {
        'species_id', 'transcript_id', 'entity_id', 'gene_id', 'gene_symbol', 'gene_biotype',
        'transcript_biotype', 'strategy_cluster', 'assembly', 'seq_region', 'start', 'end', 'strand',
        'length_nt_total', 'length_nt_acgu', 'n_N', 'frac_A', 'frac_C', 'frac_G', 'frac_U',
        'gc_content', 'at_skew', 'gc_skew', 'purine_frac', 'nt_entropy', 'C_atoms', 'N_atoms',
        'P_atoms', 'C_N_ratio', 'C_P_ratio', 'N_P_ratio', 'atoms_per_nt_C', 'atoms_per_nt_N',
        'atoms_per_nt_P', 'mw_rna_nmp_per_nt_Da', 'dinuc_valid_pairs', 'max_run_any',
        'avg_spacing_A', 'avg_spacing_U', 'orf_len_nt', 'orf_len_aa', 'orf_has_stop',
        'protein_mw_Da', 'protein_isoelectric_point', 'protein_gravy', 'protein_instability_index',
        'aa_len', 'codon_valid_codons', 'rna_orf_coupling_score', 'protein_gravy_proxy',
    },
    'proteome': {
        'species_id', 'protein_id', 'entity_id', 'gene_id', 'gene_symbol', 'ensembl_gene_id',
        'ensembl_transcript_id', 'strategy_cluster', 'length_aa', 'length_canonical_aa',
        'noncanonical_aa', 'X_count', 'B_count', 'Z_count', 'J_count', 'U_count', 'O_count',
        'stop_asterisk_count', 'known_residues_for_atoms', 'unknown_residues_for_atoms',
        'mw_da', 'pI', 'net_charge_pH7', 'gravy', 'instability_index', 'aliphatic_index',
        'aromaticity', 'aa_entropy_bits', 'aa_hydrophobic_frac', 'aa_polar_frac', 'aa_pos_frac',
        'aa_neg_frac', 'aa_aromatic_frac', 'cys_count', 'met_count', 'sulfur_aa_frac',
        'C_atoms', 'N_atoms', 'S_atoms', 'Se_atoms', 'C_atoms_per_aa', 'N_atoms_per_aa',
        'S_atoms_per_aa', 'avg_oxidation_state_C', 'C_N_ratio', 'N_S_ratio', 'O_C_ratio',
        'H_C_ratio', 'C_mass_frac', 'N_mass_frac', 'O_mass_frac', 'S_mass_frac', 'Se_mass_frac',
        'ss_helix_frac', 'ss_turn_frac', 'ss_sheet_frac', 'possible_disulfides',
        'disulfide_density', 'flex_mean', 'surface_access_em_mean', 'extinction_reduced',
        'extinction_cystines', 'a280_1mgml_reduced',
    },
}

_MODULE_PROJECTION_PREFIXES = {
    'genome': ('locus_dinuc_', 'promoter_dinuc_', 'codon_', 'aa_'),
    'transcriptome': ('dinuc_', 'codon_', 'aa_', 'n_', 'protein_', 'orf_', 'max_run_', 'avg_spacing_'),
    'proteome': ('AA_', 'aa_', 'ss_', 'flex_', 'surface_access_', 'extinction_', 'a280_'),
}


def _module_projection_columns(path: Path, omics: str) -> list[str]:
    """Return only columns consumed by the public module contracts.

    Full source tables contain hundreds of auxiliary audit columns.  Reading
    their headers plus the module projection keeps the computation grounded in
    the same full release while avoiding a per-species wide-frame memory spike.
    """
    columns = list(feature_io.read_csv(path, nrows=0).columns)
    exact = _MODULE_PROJECTION_EXACT.get(omics, set())
    prefixes = _MODULE_PROJECTION_PREFIXES.get(omics, ())
    selected = [
        column for column in columns
        if column in exact or any(column.startswith(prefix) for prefix in prefixes)
    ]
    if not selected:
        return columns
    return selected


def _outlier_gene_sets(analyses: dict[str, dict[str, Any]]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for omics, payload in analyses.items():
        values: set[str] = set()
        outliers = payload.get('outliers') if isinstance(payload, dict) else {}
        if isinstance(outliers, dict):
            for side in ('high', 'low', 'multivariate'):
                for row in outliers.get(side) or []:
                    if not isinstance(row, dict):
                        continue
                    for key in ('gene_id', 'canonical_gene_id', 'entity_id', 'ensembl_gene_id'):
                        value = str(row.get(key) or '').strip()
                        if value:
                            values.add(value)
                            break
        result[omics] = values
    return result


def _scoped_payload(payload: dict[str, Any], scope: str, *, source_scope: str) -> dict[str, Any]:
    result = dict(payload)
    result['scope'] = scope
    result['available_scopes'] = ['core', 'full']
    result['precomputed_from_real_rows'] = True
    result['source_scope'] = source_scope
    return _json_safe(result)


def _method_metadata(omics: str, row_count: int, scope: str) -> dict[str, Any]:
    return {
        'method': 'precomputed from imported real six-group model-organism feature rows',
        'normalization': 'raw feature units with module-specific robust summaries',
        'missing_policy': 'only fields present in the source table are used; unsupported fields remain explicitly unavailable',
        'omics': omics,
        'scope': scope,
        'n_entities': int(row_count),
        'evidence_level': 'sequence-derived descriptive / hypothesis-generating',
        'phylogeny': 'excluded by project scope',
    }


def _histogram(values: list[float], bins: int = 42) -> dict[str, Any]:
    clean = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    if not clean:
        return {'centers': [], 'counts': [], 'n': 0}
    if min(clean) == max(clean):
        return {'centers': [round(clean[0], 6)], 'counts': [len(clean)], 'n': len(clean)}
    counts, edges = np.histogram(clean, bins=max(10, min(120, int(bins))))
    centers = ((edges[:-1] + edges[1:]) / 2).round(6).tolist()
    return {'centers': centers, 'counts': counts.astype(int).tolist(), 'n': len(clean)}


def _distribution(values: list[float]) -> dict[str, float]:
    clean = sorted(float(value) for value in values if value is not None and math.isfinite(float(value)))
    if not clean:
        return {'min': 0.0, 'p25': 0.0, 'p50': 0.0, 'p75': 0.0, 'max': 0.0, 'mean': 0.0}
    return {
        'min': round(clean[0], 6),
        'p25': round(float(np.quantile(clean, 0.25)), 6),
        'p50': round(float(np.quantile(clean, 0.50)), 6),
        'p75': round(float(np.quantile(clean, 0.75)), 6),
        'max': round(clean[-1], 6),
        'mean': round(float(np.mean(clean)), 6),
    }


def _build_enhanced_visuals(cross_payload: dict[str, Any], analyses: dict[str, dict[str, Any]]) -> dict[str, Any]:
    transformations = [row for row in (cross_payload.get('top_transformations') or []) if isinstance(row, dict)]
    dna = [float(row.get('dna_to_rna_n_shift_std', row.get('dna_to_rna_n_shift'))) for row in transformations if row.get('dna_to_rna_n_shift_std', row.get('dna_to_rna_n_shift')) is not None]
    protein = [float(row.get('rna_to_protein_n_shift_std', row.get('rna_to_protein_n_shift'))) for row in transformations if row.get('rna_to_protein_n_shift_std', row.get('rna_to_protein_n_shift')) is not None]
    islands = [row for row in (analyses.get('genome', {}).get('stoich_islands') or []) if isinstance(row, dict)]
    return {
        'coordinate_profiles': {
            'genome_stoich_island': {
                'centers': [row.get('start') for row in islands if row.get('start') is not None],
                'counts': [row.get('mean_island_score') or 0.0 for row in islands if row.get('start') is not None],
                'n': len(islands),
            },
            'genome_gc_delta': {'centers': [], 'counts': [], 'n': 0},
        },
        'shift_histograms': {'dna_to_rna_n_std': _histogram(dna), 'rna_to_protein_n_std': _histogram(protein)},
        'shift_stats': {'dna_to_rna_n_std': _distribution(dna), 'rna_to_protein_n_std': _distribution(protein)},
        'cluster_transition_links': list(cross_payload.get('cluster_transition_links') or []),
        'resource_budget_breakdown': list(analyses.get('proteome', {}).get('resource_budget') or []),
        'global_feature_rank': [],
        'paired_gene_count': int((cross_payload.get('join_summary') or {}).get('matched_all_three') or 0),
        'data_source': 'precomputed_real_feature_payloads',
        'entity_index_fallback': True,
    }


class Command(BaseCommand):
    help = 'Rebuild real summary, analysis, fingerprint, and cross-omics payloads for the six-group model-organism scope.'

    def add_arguments(self, parser):
        parser.add_argument('--model-list', default='', help='Model organism whitelist CSV.')
        parser.add_argument('--release-id', default=RELEASE_ID_DEFAULT)
        parser.add_argument('--species-id', action='append', default=[], help='Process only the supplied species ID; repeatable.')
        parser.add_argument('--offset', type=int, default=0, help='Start at this zero-based position in the sorted selected scope.')
        parser.add_argument('--limit', type=int, default=0, help='Process at most N selected species.')
        parser.add_argument('--dry-run', action='store_true', help='Read scope metadata and validate datasets without writing payloads.')
        parser.add_argument('--skip-artifacts', action='store_true', help='Do not materialize the standard per-species artifact files/rows.')
        parser.add_argument('--artifact-root', default='', help='Optional artifact output directory.')
        parser.add_argument(
            '--read-scope', choices=['module', 'core', 'full'], default='module',
            help='Read full-table module projection by default; use core for a lean run or full for an audit run.',
        )
        parser.add_argument('--resume', action='store_true', help='Skip species already written with this release ID.')

    def handle(self, *args, **options):
        model_list = Path(options['model_list']).resolve() if options.get('model_list') else _default_model_list()
        model_rows = _read_model_rows(model_list)
        requested = {str(value).strip() for value in options.get('species_id') or [] if str(value).strip()}
        if requested:
            model_rows = {sid: row for sid, row in model_rows.items() if sid in requested}
        ordered_model_rows = sorted(model_rows.items())
        offset = max(0, int(options.get('offset') or 0))
        if offset:
            ordered_model_rows = ordered_model_rows[offset:]
        model_rows = dict(ordered_model_rows)
        if options.get('limit'):
            model_rows = dict(list(sorted(model_rows.items()))[:max(1, int(options['limit']))])

        species_map = {
            row.species_id: row
            for row in Species.objects.filter(species_id__in=list(model_rows)).only(
                'id', 'species_id', 'display_name', 'short_name', 'domain', 'kingdom',
                'taxonomy_id', 'assembly_version', 'source_database', 'searchable_text',
            )
        }
        missing_species = sorted(set(model_rows) - set(species_map))
        self.stdout.write(
            f'Model organism payload scope: selected={len(model_rows)}, database_species={len(species_map)}, '
            f'missing_species={len(missing_species)}'
        )
        if options.get('dry_run'):
            self._dry_run(model_rows, species_map)
            return

        artifact_root = Path(options['artifact_root']).resolve() if options.get('artifact_root') else (
            # Keep the Windows path below MAX_PATH for long Salmonella and
            # other strain-level species IDs.  The release report remains in
            # the descriptive hardening directory; only materialized files
            # use this compact, stable root.
            Path(settings.BASE_DIR) / 'data' / 'mo_artifacts' / str(options['release_id'])
        )
        artifact_root.mkdir(parents=True, exist_ok=True)
        report_root = Path(settings.BASE_DIR) / 'data' / 'model_organism_release_hardening' / str(options['release_id'])
        report_root.mkdir(parents=True, exist_ok=True)

        report_rows: list[dict[str, Any]] = []
        processed = 0
        for species_id, model_row in sorted(model_rows.items()):
            species = species_map.get(species_id)
            if species is None:
                report_rows.append({
                    'species_id': species_id,
                    'display_name': model_row.get('display_name') or species_id,
                    'model_group': model_row.get('expected_model_group') or '',
                    'status': 'missing_species_registry',
                    'error': 'species_id is present in the model whitelist but absent from the current database',
                })
                continue
            if options.get('resume') and species.source_database == f'model_organism_release:{options["release_id"]}' and species.fingerprint:
                report_rows.append({
                    'species_id': species_id,
                    'display_name': species.display_name,
                    'model_group': model_row.get('expected_model_group') or '',
                    'status': 'already_updated',
                    'error': '',
                })
                continue
            try:
                result = self._process_species(
                    species,
                    model_row,
                    release_id=str(options['release_id']),
                    artifact_root=artifact_root,
                    materialize_artifacts=not bool(options.get('skip_artifacts')),
                    read_scope=str(options.get('read_scope') or 'module'),
                )
                result.update({'status': 'updated', 'error': ''})
                report_rows.append(result)
                processed += 1
                if processed == 1 or processed % 10 == 0:
                    self.stdout.write(
                        f'Updated {processed}/{len(species_map)}: {species_id} '
                        f'rows={result.get("total_rows", 0)} matched_all_three={result.get("matched_all_three", 0)}'
                    )
            except Exception as exc:  # keep the batch resumable and report the exact failed species
                report_rows.append({
                    'species_id': species_id,
                    'display_name': species.display_name,
                    'model_group': model_row.get('expected_model_group') or '',
                    'status': 'error',
                    'error': f'{type(exc).__name__}: {exc}',
                })
                self.stderr.write(self.style.ERROR(f'Failed {species_id}: {type(exc).__name__}: {exc}'))
            finally:
                # ``species_map`` intentionally keeps the registry objects so
                # the batch does not issue one registry query per organism.
                # The payload fields just written can be very large, however;
                # retaining them on those long-lived objects makes RSS grow
                # monotonically across hundreds of species.  The database row
                # is already committed, so release the in-memory copies before
                # moving to the next organism.  This is also safe for resume
                # skips and failed organisms.
                if species is not None:
                    species.fingerprint = None
                    species.cross_omics_payload = None
                gc.collect()

        generated_at = timezone.now().isoformat()
        report = {
            'release_id': options['release_id'],
            'generated_at': generated_at,
            'model_list': str(model_list),
            'scope': 'six_group_model_organisms_without_phylogeny',
            'selected_model_species': len(model_rows),
            'database_species_in_scope': len(species_map),
            'processed_species': sum(1 for row in report_rows if row.get('status') == 'updated'),
            'missing_species': sum(1 for row in report_rows if row.get('status') == 'missing_species_registry'),
            'failed_species': sum(1 for row in report_rows if row.get('status') == 'error'),
            'rows': _json_safe(report_rows),
        }
        (report_root / 'payload_rebuild_report.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8'
        )
        fieldnames = sorted({key for row in report_rows for key in row.keys()})
        with (report_root / 'payload_rebuild_report.csv').open('w', encoding='utf-8-sig', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(_json_safe(report_rows))

        if not options.get('dry_run'):
            self._register_release(options['release_id'], report, report_root)
        self.stdout.write(self.style.SUCCESS(json.dumps({key: report[key] for key in report if key != 'rows'}, ensure_ascii=False, indent=2)))

    def _dry_run(self, model_rows: dict[str, dict[str, Any]], species_map: dict[str, Species]) -> None:
        missing_omics = 0
        valid = 0
        for species_id, species in sorted(species_map.items()):
            datasets = {ds.omics_type: ds for ds in OmicsDataset.objects.filter(species=species)}
            absent = []
            for omics in OMICS_ORDER:
                ds = datasets.get(omics)
                path = Path(str((ds.full_csv_path if ds and ds.full_csv_path else ds.core_csv_path if ds else '') or '')) if ds else None
                if not ds or not path or not feature_io.source_exists(path):
                    absent.append(omics)
            if absent:
                missing_omics += 1
            else:
                valid += 1
            if len(model_rows) <= 10 or absent:
                self.stdout.write(f'{species_id}: ' + ('ready' if not absent else f'missing={",".join(absent)}'))
        self.stdout.write(json.dumps({'ready_species': valid, 'species_with_missing_omics': missing_omics, 'missing_registry_species': len(set(model_rows) - set(species_map))}, ensure_ascii=False))

    def _process_species(
        self,
        species: Species,
        model_row: dict[str, Any],
        *,
        release_id: str,
        artifact_root: Path,
        materialize_artifacts: bool,
        read_scope: str,
    ) -> dict[str, Any]:
        datasets = {ds.omics_type: ds for ds in OmicsDataset.objects.filter(species=species)}
        frames: dict[str, pd.DataFrame] = {}
        source_paths: dict[str, str] = {}
        source_scopes: dict[str, str] = {}
        for omics in OMICS_ORDER:
            dataset = datasets.get(omics)
            if dataset is None:
                raise CommandError(f'missing dataset {omics}')
            full_path = Path(str(dataset.full_csv_path or ''))
            core_path = Path(str(dataset.core_csv_path or ''))
            source_path = full_path if read_scope != 'core' and feature_io.source_exists(full_path) else core_path
            if not feature_io.source_exists(source_path):
                raise CommandError(f'missing source CSV for {omics}: {source_path}')
            read_kwargs: dict[str, Any] = {'low_memory': False}
            if read_scope == 'module' and source_path == full_path:
                read_kwargs['usecols'] = _module_projection_columns(source_path, omics)
            frame = normalize_rows(feature_io.read_csv(source_path, **read_kwargs), omics)
            if frame.empty:
                raise CommandError(f'empty source CSV for {omics}: {source_path}')
            meta_id = {'genome': 'gene_id', 'transcriptome': 'transcript_id', 'proteome': 'protein_id'}[omics]
            if 'entity_id' not in frame.columns:
                frame['entity_id'] = frame.get(meta_id, pd.Series([''] * len(frame), index=frame.index))
            frames[omics] = frame
            source_paths[omics] = str(source_path)
            source_scopes[omics] = 'full' if source_path == full_path and feature_io.source_exists(full_path) else 'core'

        meta_payload = dict(model_row)
        meta_payload['display_name'] = species.display_name or model_row.get('display_name') or species.species_id
        summaries: dict[str, dict[str, Any]] = {}
        analyses: dict[str, dict[str, Any]] = {}
        for omics, frame in frames.items():
            summary = build_summary(frame, omics, meta_payload)
            source_method = 'module_projection_from_full_source' if read_scope == 'module' and source_scopes[omics] == 'full' else f'{source_scopes[omics]}_source_as_registered_scope'
            summary['method_metadata'] = _method_metadata(omics, len(frame), source_method)
            analysis = build_analysis(frame, omics)
            analysis['method_metadata'] = {
                **(analysis.get('method_metadata') if isinstance(analysis.get('method_metadata'), dict) else {}),
                **_method_metadata(omics, len(frame), source_method),
            }
            summaries[omics] = _scoped_payload(summary, 'core', source_scope=source_scopes[omics])
            analyses[omics] = _scoped_payload(analysis, 'core', source_scope=source_scopes[omics])

        # Keep a compact, all-relevant-field statistical layer in the
        # dataset payload.  It lets the API assemble module cards without
        # rescanning the remote CSV for every chart request.
        for omics, frame in frames.items():
            module_cards = {
                str(column): percentile_summary(frame[column])
                for column in frame.columns
                if pd.api.types.is_numeric_dtype(frame[column])
            }
            summaries[omics]['source_fields'] = list(frame.columns)
            summaries[omics]['row_count'] = int(len(frame))
            summaries[omics]['module_feature_cards'] = module_cards
            summaries[omics]['module_category_counts'] = {
                str(column): [
                    {'name': str(key), 'value': int(value)}
                    for key, value in frame[column].fillna('').astype(str).replace('', 'unknown').value_counts().head(24).items()
                ]
                for column in frame.columns
                if not pd.api.types.is_numeric_dtype(frame[column]) and column in {
                    'biotype', 'gene_biotype', 'transcript_biotype', 'strand', 'seqid', 'seq_region'
                }
            }
            summaries[omics]['analysis_results'] = {
                key: analyses[omics].get(key)
                for key in (
                    'outliers', 'tradeoff_front', 'stoich_islands', 'motif_themes',
                    'composition_themes', 'resource_budget', 'sequence_intrinsic_resource_profile',
                )
                if key in analyses[omics]
            }

        cross_frames = {omics: _cross_frame(frame, omics) for omics, frame in frames.items()}
        fingerprint = derive_fingerprint(meta_payload, summaries, frames)
        cross_payload = build_cross_omics(
            species.species_id,
            cross_frames,
            fingerprint,
            outlier_gene_sets=_outlier_gene_sets(analyses),
        )
        cross_payload.update({
            'release_id': release_id,
            'precomputed_from_real_rows': True,
            'source_csv_paths': source_paths,
            'method_metadata': {
                **(cross_payload.get('method_metadata') if isinstance(cross_payload.get('method_metadata'), dict) else {}),
                'source': 'real feature tables registered in OmicsDataset',
                'phylogeny': 'excluded by project scope',
            },
        })
        cross_payload['enhanced_visuals'] = _build_enhanced_visuals(cross_payload, analyses)
        cross_payload = _json_safe(cross_payload)
        for payload in summaries.values():
            payload['fingerprint'] = _json_safe(fingerprint)

        scoped_summaries = {
            omics: {
                'core': _scoped_payload(payload, 'core', source_scope=source_scopes[omics]),
                'full': _scoped_payload(payload, 'full', source_scope=source_scopes[omics]),
            }
            for omics, payload in summaries.items()
        }
        scoped_analyses = {
            omics: {
                'core': _scoped_payload(payload, 'core', source_scope=source_scopes[omics]),
                'full': _scoped_payload(payload, 'full', source_scope=source_scopes[omics]),
            }
            for omics, payload in analyses.items()
        }

        group = str(model_row.get('expected_model_group') or model_row.get('source_division') or '').strip().lower()
        group_label = GROUP_LABELS.get(group, group.title())
        display_name = species.display_name or model_row.get('display_name') or species.species_id
        searchable = ' '.join(filter(None, [species.searchable_text, species.species_id, display_name, group_label, model_row.get('model_group_latin')]))
        artifact_count = 0
        with transaction.atomic():
            species.domain = group_label
            species.kingdom = species.kingdom or group_label
            species.taxonomy_id = str(model_row.get('taxon_id') or species.taxonomy_id or '')
            species.assembly_version = str(model_row.get('assembly_accession') or species.assembly_version or '')
            species.source_database = f'model_organism_release:{release_id}'
            species.has_genome = True
            species.has_transcriptome = True
            species.has_proteome = True
            species.is_featured = True
            species.fingerprint = _json_safe(fingerprint)
            species.cross_omics_payload = cross_payload
            species.searchable_text = searchable
            species.save(update_fields=[
                'domain', 'kingdom', 'taxonomy_id', 'assembly_version', 'source_database',
                'has_genome', 'has_transcriptome', 'has_proteome', 'is_featured',
                'fingerprint', 'cross_omics_payload', 'searchable_text', 'updated_at',
            ])

            for omics, dataset in datasets.items():
                frame = frames[omics]
                dataset.summary_payload = {'release_id': release_id, 'scopes': scoped_summaries[omics]}
                dataset.analysis_payload = {'release_id': release_id, 'scopes': scoped_analyses[omics]}
                dataset.row_count_full = int(len(frame))
                dataset.row_count_core = int(dataset.row_count_core or len(frame))
                dataset.status = 'ready'
                browse = dict(dataset.browse_meta or {})
                browse.update({
                    'available_scopes': ['core', 'full'],
                    'precomputed_from_real_rows': True,
                    'payload_release_id': release_id,
                    'source_scope': source_scopes[omics],
                    'source_csv_path': source_paths[omics],
                    'schema_fields': list(frame.columns),
                    'schema_field_count': len(frame.columns),
                    'row_count_validated': int(len(frame)),
                    'phylogeny_in_scope': False,
                })
                dataset.browse_meta = _json_safe(browse)
                dataset.schema_version = 'real_feature_model_scope_v1'
                dataset.searchable_text = ' '.join([species.species_id, omics, group_label, *list(frame.columns)[:80]])
                dataset.save(update_fields=[
                    'summary_payload', 'analysis_payload', 'row_count_core', 'row_count_full',
                    'status', 'browse_meta', 'schema_version', 'searchable_text', 'updated_at',
                ])
                if materialize_artifacts:
                    artifact_count += self._upsert_omics_artifacts(
                        species, dataset, omics, scoped_summaries[omics], scoped_analyses[omics],
                        artifact_root, release_id,
                    )
            if materialize_artifacts:
                artifact_count += self._upsert_cross_artifacts(species, cross_payload, artifact_root, release_id)

        total_rows = sum(len(frame) for frame in frames.values())
        return {
            'species_id': species.species_id,
            'display_name': display_name,
            'model_group': group,
            'total_rows': total_rows,
            'genome_rows': len(frames['genome']),
            'transcriptome_rows': len(frames['transcriptome']),
            'proteome_rows': len(frames['proteome']),
            'matched_genome_transcriptome': (cross_payload.get('join_summary') or {}).get('matched_genome_transcriptome', 0),
            'matched_transcriptome_proteome': (cross_payload.get('join_summary') or {}).get('matched_transcriptome_proteome', 0),
            'matched_all_three': (cross_payload.get('join_summary') or {}).get('matched_all_three', 0),
            'annotation_ready_payload': True,
            'artifact_count': artifact_count,
        }

    def _write_artifact(self, path: Path, artifact_id: str, artifact_type: str, species_id: str, omics: str, payload: dict[str, Any], metadata: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        envelope = {
            'artifact_id': artifact_id,
            'artifact_type': artifact_type,
            'species_id': species_id,
            'omics_type': omics,
            'release_id': metadata.get('release_id', ''),
            'method_metadata': metadata,
            'payload': _json_safe(payload),
        }
        path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding='utf-8')

    def _upsert_omics_artifacts(self, species: Species, dataset: OmicsDataset, omics: str, summaries: dict[str, dict[str, Any]], analyses: dict[str, dict[str, Any]], artifact_root: Path, release_id: str) -> int:
        summary = summaries.get('core') or summaries.get('full') or {}
        analysis = analyses.get('core') or analyses.get('full') or {}
        entries = [
            ('profile', {'species_id': species.species_id, 'omics': omics, 'row_count': dataset.row_count_full, 'feature_cards': summary.get('feature_cards') or []}),
            ('core_features', {'species_id': species.species_id, 'omics': omics, 'scope': 'core', 'available_scopes': ['core', 'full'], 'field_meta': summary.get('field_meta') or [], 'row_count': dataset.row_count_core}),
            ('summary', summary),
            ('analysis', analysis),
        ]
        for artifact_type, payload in entries:
            artifact_id = f'{species.species_id}__{omics}__model__{artifact_type}'
            metadata = {
                'method': f'model-organism real-row {artifact_type} payload',
                'normalization': 'raw/module-specific',
                'missing_policy': 'source fields only; unavailable modules are declared in payload',
                'n_entities': dataset.row_count_full,
                'n_features': len(summary.get('feature_cards') or {}),
                'is_exploratory': artifact_type in {'analysis', 'summary'},
                'release_id': release_id,
            }
            path = artifact_root / species.species_id / omics / f'{artifact_type}.json'
            self._write_artifact(path, artifact_id, artifact_type, species.species_id, omics, payload, metadata)
            AnalysisArtifact.objects.update_or_create(
                artifact_id=artifact_id,
                defaults={
                    'species': species,
                    'dataset': dataset,
                    'omics_type': omics,
                    'artifact_type': artifact_type,
                    'path': str(path),
                    'payload_json': {'method_metadata': metadata, **_json_safe(payload)},
                    'version': 'model_scope_v1',
                },
            )
        return len(entries)

    def _upsert_cross_artifacts(self, species: Species, cross_payload: dict[str, Any], artifact_root: Path, release_id: str) -> int:
        artifact_id = f'{species.species_id}__model__cross_omics'
        metadata = {
            'method': 'model-organism real-row cross-omics payload',
            'normalization': 'raw shifts and correlation payload',
            'missing_policy': 'matched genes and fields available in all three source tables',
            'n_entities': (cross_payload.get('join_summary') or {}).get('matched_all_three', 0),
            'n_features': len(cross_payload.get('correlation_matrix') or {}),
            'is_exploratory': True,
            'release_id': release_id,
        }
        path = artifact_root / species.species_id / 'cross_omics' / 'cross_omics.json'
        self._write_artifact(path, artifact_id, 'cross_omics', species.species_id, 'all', cross_payload, metadata)
        AnalysisArtifact.objects.update_or_create(
            artifact_id=artifact_id,
            defaults={
                'species': species,
                'dataset': None,
                'omics_type': 'all',
                'artifact_type': 'cross_omics',
                'path': str(path),
                'payload_json': {'method_metadata': metadata, **_json_safe(cross_payload)},
                'version': 'model_scope_v1',
            },
        )
        return 1

    def _register_release(self, release_id: str, report: dict[str, Any], report_root: Path) -> None:
        scoped_species = Species.objects.filter(source_database=f'model_organism_release:{release_id}')
        scoped_species_ids = list(scoped_species.values_list('id', flat=True))
        scoped_datasets = OmicsDataset.objects.filter(species_id__in=scoped_species_ids)
        scoped_artifacts = AnalysisArtifact.objects.filter(species_id__in=scoped_species_ids)
        with transaction.atomic():
            DataRelease.objects.filter(is_active=True).update(is_active=False)
            DataRelease.objects.update_or_create(
                release_id=release_id,
                defaults={
                    'label': 'Six-group model organisms v1',
                    'description': 'Real genome, transcriptome, proteome, ID mapping, and functional-annotation compatible release for the six-group model-organism scope. Phylogeny is intentionally excluded.',
                    'source_root': 'G:/stoichioomics',
                    'pipeline_root': str(report_root),
                    'platform_registry_path': str(report_root),
                    'database_engine': 'postgresql',
                    'species_count': scoped_species.count(),
                    'dataset_count': scoped_datasets.count(),
                    'entity_row_count': sum(int(value or 0) for value in scoped_datasets.values_list('row_count_full', flat=True)),
                    'artifact_count': scoped_artifacts.count(),
                    'feature_file_count': scoped_datasets.count() * 2,
                    'metadata_json': {
                        'scope': 'six_group_model_organisms',
                        'model_list': str(_default_model_list()),
                        'phylogeny': 'excluded',
                        'payload_report': str(report_root / 'payload_rebuild_report.json'),
                    },
                    'manifest_json': report,
                    'is_active': True,
                },
            )
