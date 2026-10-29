from __future__ import annotations

import csv
import gzip
import hashlib
import itertools
import json
import math
import random
from statistics import mean, pstdev
from typing import Any
from pathlib import Path

from django.db.models import Q

from . import services
from . import function_annotations
from .models import DataRelease, EntityRecord, ProteinIndex, Species


FINGERPRINT_FIELDS = [
    ('genome_gc', 'Genome GC'),
    ('promoter_gc', 'Promoter GC'),
    ('genome_n_per_base', 'Genome N/base'),
    ('transcript_gc', 'Transcript GC'),
    ('transcript_entropy', 'Transcript entropy'),
    ('transcript_coupling', 'Transcript coupling'),
    ('proteome_n_per_aa', 'Proteome N/aa'),
    ('proteome_s_per_aa', 'Proteome S/aa'),
    ('proteome_pi', 'Proteome pI'),
    ('proteome_gravy', 'Proteome GRAVY'),
]

CASE3_FEATURES = [
    ('length_aa', 'Length aa', 'aa'),
    ('N_atoms_per_aa', 'N atoms per aa', 'atoms/aa'),
    ('S_atoms_per_aa', 'S atoms per aa', 'atoms/aa'),
    ('pI', 'Isoelectric point', 'pI'),
    ('gravy', 'GRAVY', 'index'),
    ('resource_budget_score', 'Resource budget score', 'score'),
]

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CASE1_TAXONOMY_DIR = PROJECT_ROOT / 'data' / 'metadata' / 'taxonomy'
CASE1_TAXONOMY_METADATA_PATH = CASE1_TAXONOMY_DIR / 'local_all_protist_taxonomy_metadata.csv'
CASE1_ENSEMBL_TAXONOMY_PATH = CASE1_TAXONOMY_DIR / 'ensembl_protists_species_taxonomy.csv'
CASE1_ADVANCED_ARTIFACT_DIR = PROJECT_ROOT / 'workspace' / 'generated_analysis_artifacts' / 'case1_advanced'
MODEL8_CASE1_DIR = PROJECT_ROOT / 'data' / 'case_studies' / 'model8' / 'case1_atlas'
MODEL8_CASE2_DIR = PROJECT_ROOT / 'data' / 'case_studies' / 'model8' / 'case2_coupling'
MODEL8_CASE3_DIR = PROJECT_ROOT / 'data' / 'case_studies' / 'model8' / 'case3_evidence'
MODEL8_CASE4_DIR = PROJECT_ROOT / 'data' / 'case_studies' / 'model8' / 'case4_upload_gold'
MODEL8_CASE5_DIR = PROJECT_ROOT / 'data' / 'case_studies' / 'model8' / 'case5_hvg_stoich'
MODEL8_PLATFORM_RELEASE_DIR = PROJECT_ROOT / 'data' / 'case_studies' / 'model8' / 'platform_release'

TAXONOMY_RANKS = ['domain_or_realm', 'kingdom', 'phylum', 'class', 'order', 'family', 'genus', 'species']
GROUP_RANKS = ['phylum', 'class', 'order']
FORMAL_MIN_N = 5
ROBUST_MIN_N = 10


def _release_summary() -> dict[str, Any]:
    if services.db_mode():
        release = DataRelease.objects.filter(is_active=True).first() or DataRelease.objects.first()
        if release:
            return {
                'release_id': release.release_id,
                'label': release.label,
                'species_count': release.species_count,
                'dataset_count': release.dataset_count,
                'entity_row_count': release.entity_row_count,
                'artifact_count': release.artifact_count,
                'database_engine': release.database_engine,
            }
    idx = services.load_index()
    return {
        'release_id': idx.get('project', {}).get('release_id', 'file_registry'),
        'label': idx.get('project', {}).get('name', 'File registry'),
        'species_count': len(idx.get('species', [])),
        'dataset_count': '',
        'entity_row_count': '',
        'artifact_count': '',
        'database_engine': 'file_registry',
    }


def _to_float(value: Any) -> float | None:
    if value in (None, ''):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _rounded(value: Any, digits: int = 4) -> float | None:
    number = _to_float(value)
    if number is None:
        return None
    return round(number, digits)


def _zscore_matrix(rows: list[dict[str, Any]]) -> tuple[list[list[float | None]], list[dict[str, Any]]]:
    stats = []
    for field, label in FINGERPRINT_FIELDS:
        values = [_to_float(row.get('fingerprint', {}).get(field)) for row in rows]
        clean = [v for v in values if v is not None]
        if clean:
            center = mean(clean)
            spread = pstdev(clean) or 1.0
            stats.append({
                'field': field,
                'label': label,
                'mean': round(center, 5),
                'std': round(spread, 5),
                'min': round(min(clean), 5),
                'max': round(max(clean), 5),
                'range': round(max(clean) - min(clean), 5),
                'coverage': len(clean),
            })
        else:
            center = 0.0
            spread = 1.0
            stats.append({
                'field': field,
                'label': label,
                'mean': None,
                'std': None,
                'min': None,
                'max': None,
                'range': None,
                'coverage': 0,
            })
        for row, value in zip(rows, values):
            row.setdefault('_zscore', {})[field] = None if value is None else round((value - center) / spread, 3)

    matrix = [[row.get('_zscore', {}).get(field) for field, _label in FINGERPRINT_FIELDS] for row in rows]
    return matrix, sorted(stats, key=lambda item: item.get('range') or 0, reverse=True)


def _species_rows() -> list[dict[str, Any]]:
    species_qs = Species.objects.filter(has_genome=True, has_transcriptome=True, has_proteome=True).only(
        'species_id',
        'display_name',
        'has_genome',
        'has_transcriptome',
        'has_proteome',
        'fingerprint',
        'cross_omics_payload',
        'domain',
        'kingdom',
        'phylum',
        'clade',
        'habitat',
    )
    rows = []
    for species in species_qs:
        fingerprint = species.fingerprint or {}
        if not any(_to_float(fingerprint.get(field)) is not None for field, _label in FINGERPRINT_FIELDS):
            continue
        cross_payload = species.cross_omics_payload or {}
        rows.append({
            'species_id': species.species_id,
            'display_name': species.display_name,
            'fingerprint': fingerprint,
            'cross_points_count': len(cross_payload.get('cross_points') or []),
            'top_transformations_count': len(cross_payload.get('top_transformations') or []),
            'taxonomy': {
                'domain': species.domain,
                'kingdom': species.kingdom,
                'phylum': species.phylum,
                'clade': species.clade,
                'habitat': species.habitat,
            },
        })
    return rows


def _case1_species_atlas(all_rows: list[dict[str, Any]]) -> dict[str, Any]:
    matrix_rows = sorted(all_rows, key=lambda row: row['display_name'])[:80]
    matrix, feature_stats = _zscore_matrix(matrix_rows)
    exemplar_rows = []
    for row in matrix_rows[:12]:
        exemplar_rows.append({
            'species_id': row['species_id'],
            'display_name': row['display_name'],
            'cross_points_count': row['cross_points_count'],
            'fingerprint': {
                field: _rounded(row.get('fingerprint', {}).get(field))
                for field, _label in FINGERPRINT_FIELDS
            },
        })

    return {
        'id': 'case1',
        'title': 'Case 1. Internal cross-species stoichiometric fingerprint atlas',
        'status': 'implemented_internal_descriptive',
        'research_question': 'Can existing platform data describe species-level stoichiometric allocation patterns without external phenotype or phylogeny annotations?',
        'evidence_level': 'internal_data_descriptive',
        'finding': f'{len(all_rows)} complete genome/transcript sequence/proteome species support a descriptive fingerprint atlas; taxonomy-aware context is available through the Case 1 Advanced endpoint, while habitat and phylogeny-aware interpretation remain unavailable.',
        'heatmap': {
            'x_labels': [label for _field, label in FINGERPRINT_FIELDS],
            'y_labels': [row['display_name'] for row in matrix_rows],
            'values': matrix,
            'displayed_species_count': len(matrix_rows),
            'total_complete_species_count': len(all_rows),
        },
        'feature_variability': feature_stats,
        'example_species': exemplar_rows,
        'method': 'Complete-omics species were selected from the active registry, ten stored fingerprint fields were standardized with z-scores, and the first 80 species are rendered for a compact atlas preview.',
        'limitations': [
            'This basic panel does not join taxonomy metadata; use the Advanced tab for taxonomy-aware descriptive comparison.',
            'No habitat, ecological phenotype, or phylogenetic tree is joined in this basic implementation.',
            'The atlas is descriptive and should not be interpreted as evolutionary or ecological causality.',
        ],
    }


def _case2_cross_omics_coupling(all_rows: list[dict[str, Any]]) -> dict[str, Any]:
    ranked = sorted(
        all_rows,
        key=lambda row: (row['cross_points_count'], row['top_transformations_count'], row['display_name']),
        reverse=True,
    )
    selected_id = ranked[0]['species_id'] if ranked else ''
    selected = Species.objects.filter(species_id=selected_id).only('species_id', 'display_name', 'cross_omics_payload').first()
    payload = services.get_cross_omics(selected_id) if selected_id else {}
    function_summary = function_annotations.species_functional_summary(selected.species_id) if selected else {}
    candidate_species = []
    for row in ranked[:12]:
        candidate_species.append({
            'species_id': row['species_id'],
            'display_name': row['display_name'],
            'cross_points_count': row['cross_points_count'],
            'top_transformations_count': row['top_transformations_count'],
        })

    return {
        'id': 'case2',
        'title': 'Case 2. Single-species genome-RNA-protein coupling using stored cross-omics results',
        'status': 'implemented_standardized_descriptive',
        'research_question': 'Within one well-covered species, can stored cross-omics results explain gene-to-transcript-to-protein stoichiometric shifts?',
        'evidence_level': 'internal_data_descriptive',
        'selected_species': {
            'species_id': selected.species_id if selected else '',
            'display_name': selected.display_name if selected else '',
            'selection_rule': 'Highest available stored cross_points count among complete-omics species.',
        },
        'candidate_species': candidate_species,
        'correlation_matrix': payload.get('correlation_matrix') or {},
        'cross_points': (payload.get('cross_points') or [])[:80],
        'top_transformations': (payload.get('top_transformations') or [])[:16],
        'functional_annotation_extension': {
            'summary': function_summary,
            'route': '/api/stoichdb/case-studies/case2/function-chain/',
            'interpretation': 'Use the functional chain endpoint to connect selected cross-omics entities to UniProt, GO, and KEGG evidence when official annotations exist.',
        },
        'finding': f'{selected.display_name if selected else "No species"} was selected because it has {len(payload.get("cross_points") or [])} stored cross-omics points and {len(payload.get("top_transformations") or [])} transformation rows in the active dataset.',
        'method': 'The case uses services.get_cross_omics so DNA-RNA and RNA-protein shifts are exposed as dimensionless robust-z deltas; legacy raw/proxy fields remain available only for traceability.',
        'limitations': [
            'This implementation does not add experimental expression/protein abundance measurements.',
            'The case explains stored sequence-derived stoichiometric coupling only, not measured biological regulation.',
        ],
    }


def _value_from_entity(entity: EntityRecord | None, field: str) -> float | None:
    if entity is None:
        return None
    value = _to_float((entity.numeric_summary or {}).get(field))
    if value is not None:
        return value
    return _to_float((entity.payload_json or {}).get(field))


def _percentile(values: list[float], value: float | None) -> float | None:
    if value is None or not values:
        return None
    count = sum(1 for item in values if item <= value)
    return round(count / len(values) * 100, 2)


def _protein_candidate() -> tuple[ProteinIndex | None, EntityRecord | None]:
    base_filter = (
        ProteinIndex.objects.select_related('species')
        .filter(species__has_proteome=True)
        .exclude(description='')
        .exclude(description__icontains='hypothetical')
        .exclude(description__icontains='uncharacterized')
        .exclude(description__icontains='unknown')
    )
    preferred = base_filter.filter(species__species_id='acanthamoeba_castellanii').order_by('protein_id').first()
    protein = preferred or base_filter.order_by('species__display_name', 'protein_id').first()
    if not protein:
        return None, None
    id_terms = [protein.protein_id, protein.gene_id, protein.ensembl_gene_id, protein.gene_symbol]
    id_terms = [term for term in id_terms if term]
    query = Q()
    for term in id_terms:
        query |= Q(entity_id=term) | Q(canonical_gene_id=term) | Q(secondary_id=term) | Q(gene_name=term)
    entity = EntityRecord.objects.filter(species=protein.species, omics_type='proteome').filter(query).first()
    if entity is None:
        entity = EntityRecord.objects.filter(
            species=protein.species,
            omics_type='proteome',
            description=protein.description,
        ).first()
    return protein, entity


def _case3_candidate_entity_report() -> dict[str, Any]:
    protein, entity = _protein_candidate()
    if not protein:
        return {
            'id': 'case3',
            'title': 'Case 3. Candidate protein stoichiometric report',
            'status': 'unavailable',
            'research_question': 'Can one annotated protein be interpreted with current internal stoichiometric features?',
            'evidence_level': 'no_candidate',
            'finding': 'No annotated protein candidate was found in the current active dataset.',
            'feature_profile': [],
            'candidate_pool': [],
            'limitations': ['Protein annotation rows are required for this candidate-protein case.'],
        }

    proteome_qs = EntityRecord.objects.filter(species=protein.species, omics_type='proteome').only('numeric_summary', 'payload_json')
    feature_profile = []
    for field, label, unit in CASE3_FEATURES:
        value = _value_from_entity(entity, field)
        values = []
        for row in proteome_qs:
            row_value = _value_from_entity(row, field)
            if row_value is not None:
                values.append(row_value)
        feature_profile.append({
            'field': field,
            'label': label,
            'unit': unit,
            'value': _rounded(value),
            'species_percentile': _percentile(values, value),
            'coverage': len(values),
        })

    pool = []
    for item in ProteinIndex.objects.filter(species=protein.species).exclude(description='').order_by('protein_id')[:10]:
        pool.append({
            'protein_id': item.protein_id,
            'gene_id': item.gene_id,
            'gene_symbol': item.gene_symbol,
            'description': item.description,
            'length_aa': item.length_aa,
        })
    function_key = protein.gene_id or protein.protein_id
    functional_evidence = function_annotations.entity_function_payload(protein.species.species_id, function_key)

    return {
        'id': 'case3',
        'title': 'Case 3. Candidate protein stoichiometric report',
        'status': 'implemented_internal_descriptive',
        'research_question': 'Can one internally annotated protein be converted into a readable stoichiometric interpretation report?',
        'evidence_level': 'internal_annotation_plus_stoichiometric_features',
        'selected_entity': {
            'species_id': protein.species.species_id,
            'species_name': protein.species.display_name,
            'protein_id': protein.protein_id,
            'gene_id': protein.gene_id,
            'gene_symbol': protein.gene_symbol,
            'description': protein.description,
            'entity_id': entity.entity_id if entity else '',
        },
        'feature_profile': feature_profile,
        'functional_evidence': functional_evidence,
        'candidate_pool': pool,
        'finding': f'{protein.protein_id} has an internal annotation and can be summarized against the {protein.species.display_name} proteome feature distribution; GO/KEGG evidence is attached when official records match the entity IDs.',
        'method': 'One non-hypothetical annotated protein was selected from ProteinIndex, linked to its proteome EntityRecord where possible, each feature percentile was calculated against same-species proteome rows, and official GO/KEGG evidence was joined through the functional annotation layer.',
        'limitations': [
            'GO/KEGG evidence is available only when the species and entity are covered by official standard annotation records.',
            'Percentiles are sequence-feature percentiles within the same species proteome, not functional validation.',
        ],
    }


def _case4_upload_gold_workflow() -> dict[str, Any]:
    try:
        summary = model8_case4_summary_payload()
    except services.NotFoundError:
        summary = {}
    return {
        'id': 'case4',
        'title': 'Case 4. Eight-model-organism upload gold standard and user workflow',
        'research_question': (
            'Can uploaded FASTA/GFF3/sample-sheet workflows reproduce fixed sequence stoichiometric features, '
            'surface expected errors, and keep user data isolated from the public registry?'
        ),
        'finding': summary.get(
            'finding',
            'Model-8 upload gold-standard artifacts are not generated yet; run scripts/build_model8_case4_upload_gold.py.',
        ),
        'method': summary.get(
            'method',
            'Fixed upload gold records, synthetic boundary sequences, workflow examples, and tolerance checks are read from frozen Case 4 artifacts.',
        ),
        'gold_standard': {
            'species_count': summary.get('species_count'),
            'protein_gold_records': summary.get('protein_gold_records'),
            'nucleotide_gold_records': summary.get('nucleotide_gold_records'),
            'synthetic_nucleotide_records': summary.get('synthetic_nucleotide_records'),
            'synthetic_protein_records': summary.get('synthetic_protein_records'),
            'workflow_count': summary.get('workflow_count'),
            'agreement': summary.get('agreement'),
        },
        'limitations': summary.get('limitations', []),
    }


def _case5_hvg_stoich_workflow() -> dict[str, Any]:
    try:
        summary = model8_case5_summary_payload()
    except services.NotFoundError:
        summary = {}
    acceptance = summary.get('acceptance', {})
    return {
        'id': 'case5',
        'title': 'Case 5. Eight-model-organism HVG-Stoich flagship system',
        'research_question': summary.get(
            'research_question',
            'Do expression-derived highly variable genes show reproducible incremental association with sequence stoichiometric features across model organisms?',
        ),
        'finding': summary.get(
            'finding',
            'Model-8 HVG-Stoich artifacts are not generated yet; run scripts/build_model8_case5_hvg_stoich.py.',
        ),
        'method': summary.get(
            'method',
            'Expression matrices are profiled with HVG methods, linked to versioned transcript/protein stoichiometric features, and tested with cross-validated baseline and stoichiometric models.',
        ),
        'hvg_stoich': {
            'phase1_complete_count': acceptance.get('phase1_complete_count'),
            'phase2_complete_count': acceptance.get('phase2_complete_count'),
            'meets_plan_minimum': acceptance.get('meets_plan_minimum'),
            'mapping_threshold_phase2': acceptance.get('mapping_threshold_phase2'),
            'species_status': summary.get('species_status', []),
        },
        'limitations': summary.get('limitations', []),
    }


def _normal_text(value: Any, fallback: str = 'Missing') -> str:
    text = str(value or '').strip()
    if not text or text.lower() in {'nan', 'none', 'null'}:
        return fallback
    return text


def _file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _read_csv_rows(path: Path) -> tuple[list[dict[str, str]], dict[str, Any], list[str]]:
    limitations: list[str] = []
    info = {
        'metadata_file': str(path),
        'exists': path.exists(),
        'row_count': 0,
        'column_count': 0,
        'columns': [],
        'sha256': '',
        'last_modified': '',
    }
    if not path.exists():
        limitations.append(f'Taxonomy metadata file is missing: {path}.')
        return [], info, limitations
    try:
        with path.open('r', encoding='utf-8-sig', newline='') as fh:
            reader = csv.DictReader(fh)
            rows = [dict(row) for row in reader]
            columns = list(reader.fieldnames or [])
    except Exception as exc:
        limitations.append(f'Taxonomy metadata CSV could not be read: {exc}.')
        return [], info, limitations
    info.update({
        'row_count': len(rows),
        'column_count': len(columns),
        'columns': columns,
        'sha256': _file_checksum(path),
        'last_modified': path.stat().st_mtime,
    })
    return rows, info, limitations


def load_case1_taxonomy_metadata() -> dict[str, Any]:
    required = {
        'species_id', 'match_status', 'tax_id_current', 'domain_or_realm', 'phylum',
        'class', 'order', 'family', 'genus', 'species', 'full_lineage',
    }
    rows, info, limitations = _read_csv_rows(CASE1_TAXONOMY_METADATA_PATH)
    reference_rows, reference_info, reference_limitations = _read_csv_rows(CASE1_ENSEMBL_TAXONOMY_PATH)
    limitations.extend(reference_limitations)
    columns = set(info.get('columns') or [])
    missing = sorted(required - columns)
    if missing:
        limitations.append(f'Taxonomy metadata is missing required columns: {", ".join(missing)}.')
    normalized = []
    for row in rows:
        species_id = _normal_text(row.get('species_id'), '')
        if not species_id:
            continue
        clean = dict(row)
        clean['species_id'] = species_id
        for key in TAXONOMY_RANKS + ['match_status', 'tax_id_status']:
            clean[key] = _normal_text(clean.get(key))
        clean['tax_id_current'] = _normal_text(clean.get('tax_id_current'), '')
        clean['full_lineage'] = _normal_text(clean.get('full_lineage'), '')
        normalized.append(clean)
    return {
        'rows': normalized,
        'by_species_id': {row['species_id']: row for row in normalized},
        'metadata_info': info,
        'reference_info': reference_info,
        'limitations': limitations,
    }


def _taxonomy_quality_grade(taxonomy: dict[str, Any]) -> str:
    phylum = _normal_text(taxonomy.get('phylum'))
    klass = _normal_text(taxonomy.get('class'))
    order = _normal_text(taxonomy.get('order'))
    family = _normal_text(taxonomy.get('family'))
    genus = _normal_text(taxonomy.get('genus'))
    species = _normal_text(taxonomy.get('species'))
    tax_id = _normal_text(taxonomy.get('tax_id_current'), '')
    lineage = _normal_text(taxonomy.get('full_lineage'), '')
    if all(value != 'Missing' for value in [phylum, klass, order, family, genus, species]):
        return 'A'
    if all(value != 'Missing' for value in [phylum, order, family, genus, species]):
        return 'B'
    if phylum == 'Missing' and tax_id and lineage:
        return 'C'
    if not tax_id or not lineage:
        return 'D'
    return 'C'


def build_case1_taxonomy_support_matrix(
    case1_rows: list[dict[str, Any]],
    taxonomy_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    by_species = taxonomy_payload.get('by_species_id') or {}
    case1_ids = {row['species_id'] for row in case1_rows}
    case1_by_species = {row['species_id']: row for row in case1_rows}
    support_rows = []
    for species_id in sorted(case1_ids):
        case_row = case1_by_species[species_id]
        taxonomy = by_species.get(species_id, {})
        matched = bool(taxonomy)
        support_rows.append({
            'species_id': species_id,
            'display_name': case_row.get('display_name', ''),
            'ensembl_name': taxonomy.get('ensembl_name', ''),
            'match_status': taxonomy.get('match_status') or ('unmatched_case1_species' if not matched else 'matched_ensembl_name'),
            'tax_id_current': taxonomy.get('tax_id_current', ''),
            'tax_id_status': taxonomy.get('tax_id_status', ''),
            'domain_or_realm': _normal_text(taxonomy.get('domain_or_realm')),
            'kingdom': _normal_text(taxonomy.get('kingdom')),
            'phylum': _normal_text(taxonomy.get('phylum')),
            'class': _normal_text(taxonomy.get('class')),
            'order': _normal_text(taxonomy.get('order')),
            'family': _normal_text(taxonomy.get('family')),
            'genus': _normal_text(taxonomy.get('genus')),
            'species': _normal_text(taxonomy.get('species')),
            'full_lineage': taxonomy.get('full_lineage', ''),
            'has_genome': True,
            'has_transcriptome': True,
            'has_proteome': True,
            'included_in_case1': True,
            'taxonomy_quality_grade': _taxonomy_quality_grade(taxonomy),
        })
    for taxonomy in taxonomy_payload.get('rows') or []:
        species_id = taxonomy.get('species_id')
        if species_id in case1_ids:
            continue
        support_rows.append({
            'species_id': species_id,
            'display_name': taxonomy.get('ensembl_display_name') or species_id,
            'ensembl_name': taxonomy.get('ensembl_name', ''),
            'match_status': taxonomy.get('match_status', 'taxonomy_only'),
            'tax_id_current': taxonomy.get('tax_id_current', ''),
            'tax_id_status': taxonomy.get('tax_id_status', ''),
            'domain_or_realm': _normal_text(taxonomy.get('domain_or_realm')),
            'kingdom': _normal_text(taxonomy.get('kingdom')),
            'phylum': _normal_text(taxonomy.get('phylum')),
            'class': _normal_text(taxonomy.get('class')),
            'order': _normal_text(taxonomy.get('order')),
            'family': _normal_text(taxonomy.get('family')),
            'genus': _normal_text(taxonomy.get('genus')),
            'species': _normal_text(taxonomy.get('species')),
            'full_lineage': taxonomy.get('full_lineage', ''),
            'has_genome': taxonomy.get('has_genome', ''),
            'has_transcriptome': taxonomy.get('has_transcriptome', ''),
            'has_proteome': taxonomy.get('has_proteome', ''),
            'included_in_case1': False,
            'taxonomy_quality_grade': _taxonomy_quality_grade(taxonomy),
        })
    return support_rows


def _count_by(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for row in rows:
        value = _normal_text(row.get(key))
        counts[value] = counts.get(value, 0) + 1
    return [
        {'value': value, 'count': count}
        for value, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def summarize_taxonomy_coverage(support_rows: list[dict[str, Any]]) -> dict[str, Any]:
    case_rows = [row for row in support_rows if row.get('included_in_case1')]
    total = len(case_rows)
    rank_coverage = []
    for rank in TAXONOMY_RANKS:
        present = sum(1 for row in case_rows if _normal_text(row.get(rank)) != 'Missing')
        allowed_for_grouping = rank in GROUP_RANKS and present >= max(FORMAL_MIN_N, total * 0.5)
        rank_coverage.append({
            'rank': rank,
            'present_count': present,
            'missing_count': total - present,
            'coverage': round(present / total, 4) if total else 0.0,
            'analysis_status': 'grouping_enabled' if allowed_for_grouping else 'unavailable_or_context_only',
        })
    return {
        'species_total': total,
        'taxonomy_rows_total': len(support_rows),
        'matched_species_count': sum(1 for row in case_rows if row.get('match_status') != 'unmatched_case1_species'),
        'quality_grade_distribution': _count_by(case_rows, 'taxonomy_quality_grade'),
        'match_status_distribution': _count_by(case_rows, 'match_status'),
        'tax_id_status_distribution': _count_by(case_rows, 'tax_id_status'),
        'rank_coverage': rank_coverage,
        'major_taxa': {
            rank: _count_by(case_rows, rank)[:16]
            for rank in ['phylum', 'class', 'order', 'family']
        },
        'unavailable_ranks': [
            item['rank'] for item in rank_coverage
            if item['present_count'] == 0 or item['analysis_status'] != 'grouping_enabled'
        ],
    }


def _feature_values(row: dict[str, Any]) -> dict[str, float | None]:
    fingerprint = row.get('fingerprint') or {}
    return {field: _to_float(fingerprint.get(field)) for field, _label in FINGERPRINT_FIELDS}


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    lower = math.floor(pos)
    upper = math.ceil(pos)
    if lower == upper:
        return ordered[int(pos)]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (pos - lower)


def _rank_values(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i + 1
        while j < len(indexed) and indexed[j][1] == indexed[i][1]:
            j += 1
        avg_rank = (i + 1 + j) / 2
        for k in range(i, j):
            ranks[indexed[k][0]] = avg_rank
        i = j
    return ranks


def _regularized_gamma_q(a: float, x: float) -> float:
    if x <= 0:
        return 1.0
    if x < a + 1.0:
        ap = a
        delta = 1.0 / a
        total = delta
        for _ in range(200):
            ap += 1.0
            delta *= x / ap
            total += delta
            if abs(delta) < abs(total) * 3e-7:
                break
        p = total * math.exp(-x + a * math.log(x) - math.lgamma(a))
        return max(0.0, min(1.0, 1.0 - p))
    b = x + 1.0 - a
    c = 1.0 / 1e-30
    d = 1.0 / b
    h = d
    for i in range(1, 200):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < 1e-30:
            d = 1e-30
        c = b + an / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 3e-7:
            break
    return max(0.0, min(1.0, math.exp(-x + a * math.log(x) - math.lgamma(a)) * h))


def _chi_square_sf(x: float, df: int) -> float:
    if df <= 0 or x < 0:
        return 1.0
    return _regularized_gamma_q(df / 2.0, x / 2.0)


def _kruskal_wallis(groups: list[list[float]]) -> dict[str, Any]:
    clean_groups = [[float(value) for value in group if value is not None] for group in groups if group]
    if len(clean_groups) < 2:
        return {'h_statistic': None, 'pvalue': None, 'df': 0, 'n_total': sum(len(group) for group in clean_groups)}
    values = [value for group in clean_groups for value in group]
    ranks = _rank_values(values)
    n_total = len(values)
    offset = 0
    rank_sums = []
    for group in clean_groups:
        group_ranks = ranks[offset:offset + len(group)]
        rank_sums.append(sum(group_ranks))
        offset += len(group)
    h = (12.0 / (n_total * (n_total + 1.0))) * sum(
        (rank_sum * rank_sum) / len(group)
        for rank_sum, group in zip(rank_sums, clean_groups)
    ) - 3.0 * (n_total + 1.0)
    tie_counts: dict[float, int] = {}
    for value in values:
        tie_counts[value] = tie_counts.get(value, 0) + 1
    tie_correction = 1.0 - sum(count ** 3 - count for count in tie_counts.values()) / (n_total ** 3 - n_total) if n_total > 1 else 1.0
    if tie_correction > 0:
        h = h / tie_correction
    df = len(clean_groups) - 1
    return {
        'h_statistic': round(h, 6),
        'pvalue': round(_chi_square_sf(h, df), 8),
        'df': df,
        'n_total': n_total,
    }


def _bh_fdr(pvalues: list[float | None]) -> list[float | None]:
    indexed = [(idx, p) for idx, p in enumerate(pvalues) if p is not None and math.isfinite(float(p))]
    m = len(indexed)
    qvalues: list[float | None] = [None] * len(pvalues)
    if not indexed:
        return qvalues
    sorted_items = sorted(indexed, key=lambda item: item[1])
    prev = 1.0
    for rank, (idx, pvalue) in reversed(list(enumerate(sorted_items, start=1))):
        q = min(prev, float(pvalue) * m / rank)
        qvalues[idx] = round(max(0.0, min(1.0, q)), 8)
        prev = q
    return qvalues


def _zscore_rows(case_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, dict[str, float]]]:
    stats: dict[str, dict[str, float]] = {}
    for field, _label in FINGERPRINT_FIELDS:
        clean = [
            value for value in (_to_float(row.get('fingerprint', {}).get(field)) for row in case_rows)
            if value is not None
        ]
        center = mean(clean) if clean else 0.0
        spread = pstdev(clean) if len(clean) > 1 else 1.0
        if not spread:
            spread = 1.0
        stats[field] = {'mean': center, 'std': spread}
    z_rows = []
    for row in case_rows:
        z = {}
        for field, _label in FINGERPRINT_FIELDS:
            value = _to_float(row.get('fingerprint', {}).get(field))
            z[field] = None if value is None else (value - stats[field]['mean']) / stats[field]['std']
        z_rows.append({**row, '_z': z})
    return z_rows, stats


def _taxonomy_joined_rows(case1_rows: list[dict[str, Any]], support_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    support_by_species = {row['species_id']: row for row in support_rows if row.get('included_in_case1')}
    z_rows, _stats = _zscore_rows(case1_rows)
    joined = []
    for row in z_rows:
        support = support_by_species.get(row['species_id'], {})
        joined.append({**row, 'taxonomy_meta': support})
    return joined


def compute_rank_group_statistics(joined_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    summary_rows: list[dict[str, Any]] = []
    tests: list[dict[str, Any]] = []
    for rank in GROUP_RANKS:
        rank_tests_start = len(tests)
        for field, label in FINGERPRINT_FIELDS:
            global_values = [
                _to_float(row.get('fingerprint', {}).get(field))
                for row in joined_rows
                if _to_float(row.get('fingerprint', {}).get(field)) is not None
            ]
            global_mean = mean(global_values) if global_values else None
            global_median = _median(global_values) if global_values else None
            global_std = pstdev(global_values) if len(global_values) > 1 else 1.0
            groups: dict[str, list[float]] = {}
            for row in joined_rows:
                taxon = _normal_text((row.get('taxonomy_meta') or {}).get(rank))
                value = _to_float(row.get('fingerprint', {}).get(field))
                if value is None or taxon == 'Missing':
                    continue
                groups.setdefault(taxon, []).append(value)
            eligible_groups = [values for values in groups.values() if len(values) >= FORMAL_MIN_N]
            test = _kruskal_wallis(eligible_groups)
            test_row = {
                'rank_level': rank,
                'feature': field,
                'feature_label': label,
                'eligible_group_count': len(eligible_groups),
                'n_species': test['n_total'],
                'kruskal_h': test['h_statistic'],
                'kruskal_pvalue': test['pvalue'],
                'fdr_qvalue': None,
                'effect_size_eta_squared': None,
                'statistical_status': 'formal_test' if len(eligible_groups) >= 2 else 'insufficient_groups',
            }
            if test['h_statistic'] is not None and test['n_total'] > len(eligible_groups):
                denom = max(1, test['n_total'] - len(eligible_groups))
                test_row['effect_size_eta_squared'] = round(max(0.0, (test['h_statistic'] - len(eligible_groups) + 1) / denom), 6)
            tests.append(test_row)
            for taxon, values in groups.items():
                if not values:
                    continue
                q1 = _quantile(values, 0.25)
                q3 = _quantile(values, 0.75)
                med = _median(values)
                status = 'formal_test' if len(values) >= FORMAL_MIN_N and len(eligible_groups) >= 2 else 'display_only_small_n'
                if len(values) >= ROBUST_MIN_N and len(eligible_groups) >= 2:
                    status = 'robust_group'
                summary_rows.append({
                    'rank_level': rank,
                    'taxon_name': taxon,
                    'feature': field,
                    'feature_label': label,
                    'n_species': len(values),
                    'mean': _rounded(mean(values)),
                    'median': _rounded(med),
                    'std': _rounded(pstdev(values) if len(values) > 1 else 0),
                    'iqr': _rounded((q3 - q1) if q1 is not None and q3 is not None else None),
                    'min': _rounded(min(values)),
                    'max': _rounded(max(values)),
                    'global_mean': _rounded(global_mean),
                    'global_median': _rounded(global_median),
                    'delta_from_global': _rounded((med - global_median) if med is not None and global_median is not None else None),
                    'effect_size': _rounded(((med - global_median) / global_std) if med is not None and global_median is not None and global_std else None),
                    'kruskal_pvalue': test_row['kruskal_pvalue'],
                    'fdr_qvalue': None,
                    'statistical_status': status,
                })
        qvalues = _bh_fdr([row.get('kruskal_pvalue') for row in tests[rank_tests_start:]])
        for row, qvalue in zip(tests[rank_tests_start:], qvalues):
            row['fdr_qvalue'] = qvalue
            for summary in summary_rows:
                if summary['rank_level'] == row['rank_level'] and summary['feature'] == row['feature']:
                    summary['fdr_qvalue'] = qvalue
    summary_rows.sort(key=lambda item: (item['rank_level'], item['taxon_name'], item['feature']))
    tests.sort(key=lambda item: (item['rank_level'], item['fdr_qvalue'] if item['fdr_qvalue'] is not None else 9, item['feature']))
    return summary_rows, tests


def build_taxonomy_annotated_heatmap(joined_rows: list[dict[str, Any]], rank: str = 'phylum') -> dict[str, Any]:
    rows = sorted(
        joined_rows,
        key=lambda row: (
            _normal_text((row.get('taxonomy_meta') or {}).get(rank)),
            _normal_text((row.get('taxonomy_meta') or {}).get('class')),
            row.get('display_name', ''),
        ),
    )
    matrix = []
    annotations = []
    for row in rows[:160]:
        taxonomy = row.get('taxonomy_meta') or {}
        matrix.append([
            None if row.get('_z', {}).get(field) is None else round(row['_z'][field], 3)
            for field, _label in FINGERPRINT_FIELDS
        ])
        annotations.append({
            'species_id': row['species_id'],
            'display_name': row['display_name'],
            'phylum': _normal_text(taxonomy.get('phylum')),
            'class': _normal_text(taxonomy.get('class')),
            'order': _normal_text(taxonomy.get('order')),
            'taxonomy_quality_grade': taxonomy.get('taxonomy_quality_grade', 'D'),
            'match_status': taxonomy.get('match_status', 'Missing'),
        })
    return {
        'x_labels': [label for _field, label in FINGERPRINT_FIELDS],
        'y_labels': [row['display_name'] for row in rows[:160]],
        'values': matrix,
        'row_annotations': annotations,
        'sort_rank': rank,
        'displayed_species_count': len(matrix),
        'total_species_count': len(joined_rows),
    }


def _matrix_from_zrows(joined_rows: list[dict[str, Any]]) -> tuple[list[list[float]], list[dict[str, Any]]]:
    matrix = []
    valid_rows = []
    for row in joined_rows:
        values = [row.get('_z', {}).get(field) for field, _label in FINGERPRINT_FIELDS]
        if all(value is not None for value in values):
            matrix.append([float(value) for value in values])
            valid_rows.append(row)
    return matrix, valid_rows


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _matvec(matrix: list[list[float]], vector: list[float]) -> list[float]:
    return [_dot(row, vector) for row in matrix]


def _norm(vector: list[float]) -> float:
    return math.sqrt(sum(value * value for value in vector))


def _power_component(cov: list[list[float]], seed: int) -> tuple[list[float], float]:
    vector = [1.0 / math.sqrt(len(cov)) for _ in cov]
    vector[seed % len(vector)] += 0.01
    for _ in range(120):
        next_vector = _matvec(cov, vector)
        length = _norm(next_vector) or 1.0
        next_vector = [value / length for value in next_vector]
        if _norm([a - b for a, b in zip(vector, next_vector)]) < 1e-9:
            vector = next_vector
            break
        vector = next_vector
    eigenvalue = _dot(vector, _matvec(cov, vector))
    return vector, eigenvalue


def compute_case1_taxonomy_pca(joined_rows: list[dict[str, Any]]) -> dict[str, Any]:
    matrix, valid_rows = _matrix_from_zrows(joined_rows)
    if len(matrix) < 3:
        return {'available': False, 'limitations': ['PCA requires at least three complete fingerprint rows.']}
    n_features = len(FINGERPRINT_FIELDS)
    cov = [[0.0 for _ in range(n_features)] for _ in range(n_features)]
    for values in matrix:
        for i in range(n_features):
            for j in range(n_features):
                cov[i][j] += values[i] * values[j]
    denom = max(1, len(matrix) - 1)
    cov = [[value / denom for value in row] for row in cov]
    v1, e1 = _power_component(cov, 0)
    cov2 = [
        [cov[i][j] - e1 * v1[i] * v1[j] for j in range(n_features)]
        for i in range(n_features)
    ]
    v2, e2 = _power_component(cov2, 1)
    total_variance = sum(cov[i][i] for i in range(n_features)) or 1.0
    points = []
    for row, values in zip(valid_rows, matrix):
        taxonomy = row.get('taxonomy_meta') or {}
        points.append({
            'species_id': row['species_id'],
            'display_name': row['display_name'],
            'pc1': round(_dot(values, v1), 5),
            'pc2': round(_dot(values, v2), 5),
            'phylum': _normal_text(taxonomy.get('phylum')),
            'class': _normal_text(taxonomy.get('class')),
            'order': _normal_text(taxonomy.get('order')),
            'taxonomy_quality_grade': taxonomy.get('taxonomy_quality_grade', 'D'),
        })
    loadings = [
        {
            'feature': field,
            'label': label,
            'pc1': round(v1[idx], 5),
            'pc2': round(v2[idx], 5),
        }
        for idx, (field, label) in enumerate(FINGERPRINT_FIELDS)
    ]
    return {
        'available': True,
        'points': points,
        'explained_variance_ratio': [round(e1 / total_variance, 5), round(e2 / total_variance, 5)],
        'loadings': loadings,
        'method': 'PCA from standardized fingerprint matrix using covariance eigendecomposition.',
    }


def _interpret_feature(field: str, delta: float) -> str:
    direction = 'high' if delta >= 0 else 'low'
    labels = {
        'genome_gc': f'{direction} genome GC',
        'promoter_gc': f'{direction} promoter GC',
        'genome_n_per_base': f'{direction} genome nitrogen budget',
        'transcript_gc': f'{direction} transcript GC',
        'transcript_entropy': f'{direction} transcript entropy',
        'transcript_coupling': f'{direction} transcript coupling',
        'proteome_n_per_aa': f'{direction} protein nitrogen budget',
        'proteome_s_per_aa': f'{direction} sulfur-rich proteome tendency',
        'proteome_pi': 'basic proteome shift' if delta >= 0 else 'acidic proteome shift',
        'proteome_gravy': 'hydrophobicity shift upward' if delta >= 0 else 'hydrophobicity shift downward',
    }
    return labels.get(field, f'{direction} {field}')


def compute_clade_signatures(joined_rows: list[dict[str, Any]], group_summary: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries = {
        (row['rank_level'], row['taxon_name'], row['feature']): row
        for row in group_summary
    }
    signatures = []
    for rank in GROUP_RANKS:
        taxa = sorted({
            _normal_text((row.get('taxonomy_meta') or {}).get(rank))
            for row in joined_rows
            if _normal_text((row.get('taxonomy_meta') or {}).get(rank)) != 'Missing'
        })
        for taxon in taxa:
            group = [row for row in joined_rows if _normal_text((row.get('taxonomy_meta') or {}).get(rank)) == taxon]
            if len(group) < FORMAL_MIN_N:
                continue
            for field, label in FINGERPRINT_FIELDS:
                z_values = [row.get('_z', {}).get(field) for row in group if row.get('_z', {}).get(field) is not None]
                if not z_values:
                    continue
                delta = mean(z_values)
                summary = summaries.get((rank, taxon, field), {})
                signatures.append({
                    'rank_level': rank,
                    'taxon_name': taxon,
                    'n_species': len(group),
                    'feature': field,
                    'feature_label': label,
                    'group_mean': _rounded(summary.get('mean')),
                    'global_mean': _rounded(summary.get('global_mean')),
                    'delta': round(delta, 5),
                    'effect_size': _rounded(summary.get('effect_size')),
                    'pvalue': summary.get('kruskal_pvalue'),
                    'qvalue': summary.get('fdr_qvalue'),
                    'direction': 'high' if delta >= 0 else 'low',
                    'interpretation_label': _interpret_feature(field, delta),
                    'feature_missing_rate': round(1.0 - len(z_values) / len(group), 4),
                    'caution_flag': 'small_n' if len(group) < ROBUST_MIN_N else '',
                    'signature_score': round(delta, 5),
                })
    signatures.sort(key=lambda row: (row['rank_level'], row['taxon_name'], -abs(row['signature_score'])))
    return signatures


def _common_prefix_depth(a: str, b: str) -> tuple[int, int]:
    left = [part.strip() for part in str(a or '').split(';') if part.strip()]
    right = [part.strip() for part in str(b or '').split(';') if part.strip()]
    shared = 0
    for x, y in zip(left, right):
        if x != y:
            break
        shared += 1
    return shared, max(len(left), len(right), 1)


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    mx = mean(xs)
    my = mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if not dx or not dy:
        return None
    return num / (dx * dy)


def _spearman(xs: list[float], ys: list[float]) -> float | None:
    return _pearson(_rank_values(xs), _rank_values(ys))


def _box(values: list[float]) -> dict[str, Any]:
    return {
        'n': len(values),
        'min': _rounded(min(values) if values else None),
        'q1': _rounded(_quantile(values, 0.25)),
        'median': _rounded(_median(values)),
        'q3': _rounded(_quantile(values, 0.75)),
        'max': _rounded(max(values) if values else None),
    }


def compute_taxonomy_proxy_distance_alignment(joined_rows: list[dict[str, Any]]) -> dict[str, Any]:
    matrix, valid_rows = _matrix_from_zrows(joined_rows)
    pairs = []
    stoich_distances = []
    tax_distances = []
    same_phylum = []
    different_phylum = []
    row_values = list(zip(valid_rows, matrix))
    for (row_a, vec_a), (row_b, vec_b) in itertools.combinations(row_values, 2):
        tax_a = row_a.get('taxonomy_meta') or {}
        tax_b = row_b.get('taxonomy_meta') or {}
        stoich = math.sqrt(sum((a - b) ** 2 for a, b in zip(vec_a, vec_b)))
        shared, depth = _common_prefix_depth(tax_a.get('full_lineage'), tax_b.get('full_lineage'))
        taxdist = 1.0 - shared / depth
        if not math.isfinite(taxdist):
            continue
        stoich_distances.append(stoich)
        tax_distances.append(taxdist)
        same = _normal_text(tax_a.get('phylum')) != 'Missing' and _normal_text(tax_a.get('phylum')) == _normal_text(tax_b.get('phylum'))
        (same_phylum if same else different_phylum).append(stoich)
        if len(pairs) < 1600:
            pairs.append({
                'species_a': row_a['display_name'],
                'species_b': row_b['display_name'],
                'stoichiometric_distance': round(stoich, 5),
                'taxonomy_proxy_distance': round(taxdist, 5),
                'same_phylum': same,
            })
    corr = _spearman(stoich_distances, tax_distances)
    pvalue = None
    if corr is not None and len(stoich_distances) >= 10:
        rng = random.Random(20260629)
        observed = abs(corr)
        count = 0
        permutations = 120
        shuffled = tax_distances[:]
        for _ in range(permutations):
            rng.shuffle(shuffled)
            perm_corr = _spearman(stoich_distances, shuffled)
            if perm_corr is not None and abs(perm_corr) >= observed:
                count += 1
        pvalue = round((count + 1) / (permutations + 1), 6)
    return {
        'method': 'Taxonomy-proxy distance is 1 - shared lineage prefix depth / max lineage depth; this is not a phylogenetic signal test.',
        'pair_count': len(stoich_distances),
        'sampled_pairs': pairs,
        'spearman_correlation': _rounded(corr),
        'permutation_pvalue': pvalue,
        'same_phylum_box': _box(same_phylum),
        'different_phylum_box': _box(different_phylum),
        'limitations': [
            'This uses NCBI lineage text as a taxonomy proxy and does not use a phylogenetic tree or branch lengths.',
            'The result should be interpreted as descriptive alignment, not phylogenetic signal.',
        ],
    }


def select_representative_and_outlier_species(joined_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    matrix, valid_rows = _matrix_from_zrows(joined_rows)
    by_species = {row['species_id']: values for row, values in zip(valid_rows, matrix)}
    representatives = []
    outliers = []
    for rank in GROUP_RANKS:
        taxa = sorted({
            _normal_text((row.get('taxonomy_meta') or {}).get(rank))
            for row in valid_rows
            if _normal_text((row.get('taxonomy_meta') or {}).get(rank)) != 'Missing'
        })
        for taxon in taxa:
            group = [row for row in valid_rows if _normal_text((row.get('taxonomy_meta') or {}).get(rank)) == taxon and row['species_id'] in by_species]
            if len(group) < FORMAL_MIN_N:
                continue
            centroid = [
                mean([by_species[row['species_id']][idx] for row in group])
                for idx in range(len(FINGERPRINT_FIELDS))
            ]
            scored = []
            for row in group:
                values = by_species[row['species_id']]
                distance = math.sqrt(sum((value - center) ** 2 for value, center in zip(values, centroid)))
                deviations = sorted(
                    [
                        {
                            'feature': field,
                            'label': label,
                            'z_delta_from_centroid': round(values[idx] - centroid[idx], 4),
                        }
                        for idx, (field, label) in enumerate(FINGERPRINT_FIELDS)
                    ],
                    key=lambda item: abs(item['z_delta_from_centroid']),
                    reverse=True,
                )[:3]
                scored.append((distance, row, deviations))
            scored.sort(key=lambda item: item[0])
            rep_distance, rep_row, rep_features = scored[0]
            out_distance, out_row, out_features = scored[-1]
            for bucket, distance, row, features in (
                (representatives, rep_distance, rep_row, rep_features),
                (outliers, out_distance, out_row, out_features),
            ):
                taxonomy = row.get('taxonomy_meta') or {}
                bucket.append({
                    'rank_level': rank,
                    'taxon_name': taxon,
                    'n_species': len(group),
                    'species_id': row['species_id'],
                    'display_name': row['display_name'],
                    'distance_to_centroid': round(distance, 5),
                    'outlier_score': round(distance, 5),
                    'top_deviating_features': features,
                    'taxonomy_quality_grade': taxonomy.get('taxonomy_quality_grade', 'D'),
                    'interpretation_caution': 'Centroid distance is descriptive and depends on the selected fingerprint feature set.',
                })
    representatives.sort(key=lambda item: (item['rank_level'], -item['n_species'], item['taxon_name']))
    outliers.sort(key=lambda item: (item['rank_level'], -item['outlier_score']))
    return representatives, outliers


def _write_csv_artifact(filename: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    CASE1_ADVANCED_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    path = CASE1_ADVANCED_ARTIFACT_DIR / filename
    columns = sorted({key for row in rows for key in row.keys()})
    preferred = [
        'rank_level', 'taxon_name', 'species_id', 'display_name', 'feature',
        'feature_label', 'n_species', 'match_status', 'tax_id_current',
        'taxonomy_quality_grade', 'statistical_status',
    ]
    columns = [column for column in preferred if column in columns] + [column for column in columns if column not in preferred]
    with path.open('w', encoding='utf-8-sig', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    return {
        'name': filename,
        'path': str(path.relative_to(PROJECT_ROOT)),
        'row_count': len(rows),
        'sha256': _file_checksum(path),
    }


def _compact_group_summary(rows: list[dict[str, Any]], limit: int = 180) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            row.get('rank_level', ''),
            -(row.get('n_species') or 0),
            abs(row.get('effect_size') or 0) * -1,
        ),
    )[:limit]


def build_case1_taxonomy_advanced() -> dict[str, Any]:
    if not services.db_mode():
        raise services.NotFoundError('Case 1 taxonomy advanced analysis requires the PostgreSQL-backed platform registry.')
    taxonomy_payload = load_case1_taxonomy_metadata()
    limitations = list(taxonomy_payload.get('limitations') or [])
    case1_rows = _species_rows()
    support_rows = build_case1_taxonomy_support_matrix(case1_rows, taxonomy_payload)
    joined_rows = _taxonomy_joined_rows(case1_rows, support_rows)
    coverage = summarize_taxonomy_coverage(support_rows)

    if limitations:
        return {
            'id': 'case1_taxonomy_advanced',
            'status': 'available_with_limitations',
            'metadata': {
                'taxonomy_metadata': taxonomy_payload.get('metadata_info'),
                'ensembl_taxonomy_reference': taxonomy_payload.get('reference_info'),
            },
            'taxonomy_coverage': coverage,
            'taxonomy_support_matrix': [row for row in support_rows if row.get('included_in_case1')][:40],
            'rank_group_summary': [],
            'feature_group_tests': [],
            'taxonomy_annotated_heatmap': build_taxonomy_annotated_heatmap(joined_rows),
            'dimension_reduction': {'pca': {'available': False, 'limitations': limitations}},
            'clade_signatures': [],
            'distance_taxonomy_alignment': {},
            'representative_species_by_taxon': [],
            'outlier_species_by_taxon': [],
            'artifacts': [],
            'limitations': limitations,
        }

    group_summary, feature_tests = compute_rank_group_statistics(joined_rows)
    heatmap = build_taxonomy_annotated_heatmap(joined_rows)
    pca = compute_case1_taxonomy_pca(joined_rows)
    signatures = compute_clade_signatures(joined_rows, group_summary)
    distance_alignment = compute_taxonomy_proxy_distance_alignment(joined_rows)
    representatives, outliers = select_representative_and_outlier_species(joined_rows)

    artifacts = [
        _write_csv_artifact('case1_taxonomy_support_matrix.csv', support_rows),
        _write_csv_artifact('case1_rank_group_summary.csv', group_summary),
        _write_csv_artifact('case1_feature_group_tests.csv', feature_tests),
        _write_csv_artifact('case1_clade_signatures.csv', signatures),
        _write_csv_artifact('case1_representative_outlier_species.csv', representatives + outliers),
    ]

    return {
        'id': 'case1_taxonomy_advanced',
        'title': 'Case 1 Advanced. Taxonomy-aware cross-species stoichiometric fingerprint atlas',
        'status': 'implemented_advanced_taxonomy_aware',
        'research_question': 'Do stoichiometric fingerprint features show taxonomy-associated distribution patterns across complete-omics protist species?',
        'evidence_level': 'taxonomy_aware_internal_descriptive_comparative',
        'finding': (
            f'{coverage["matched_species_count"]} complete-omics Case 1 species were aligned to taxonomy metadata. '
            'Phylum, class, and order are used for descriptive group comparison; kingdom is unavailable and hidden from grouped analysis.'
        ),
        'metadata': {
            'taxonomy_metadata': taxonomy_payload.get('metadata_info'),
            'ensembl_taxonomy_reference': taxonomy_payload.get('reference_info'),
        },
        'taxonomy_coverage': coverage,
        'taxonomy_support_matrix': [row for row in support_rows if row.get('included_in_case1')][:80],
        'rank_group_summary': _compact_group_summary(group_summary),
        'feature_group_tests': feature_tests,
        'taxonomy_annotated_heatmap': heatmap,
        'dimension_reduction': {'pca': pca, 'umap': {'available': False, 'reason': 'UMAP is optional and no extra dependency is required for this implementation.'}},
        'clade_signatures': signatures[:180],
        'distance_taxonomy_alignment': distance_alignment,
        'representative_species_by_taxon': representatives[:90],
        'outlier_species_by_taxon': outliers[:90],
        'artifacts': artifacts,
        'method': (
            'Complete-omics Case 1 species were joined to local taxonomy metadata by species_id. '
            'Fingerprint features were z-scored, summarized by phylum/class/order, tested with Kruskal-Wallis and BH-FDR, '
            'projected with PCA, compared to taxonomy-proxy lineage distance, and ranked by taxon centroid distance.'
        ),
        'limitations': [
            'This is taxonomy-aware descriptive analysis, not ecological adaptation analysis.',
            'This is not phylogenetic signal analysis because no phylogenetic tree or branch lengths are used.',
            'Kingdom is unavailable in the current NCBI-derived metadata and is not used for grouping.',
            'Taxa with n < 5 are displayed only and are excluded from formal significance interpretation.',
        ],
    }


def _read_model8_case1_json(filename: str) -> dict[str, Any]:
    path = MODEL8_CASE1_DIR / filename
    if not path.exists():
        raise services.NotFoundError(
            'Model-8 Case 1 atlas artifacts are missing. Run scripts/build_model8_case1_atlas.py first.'
        )
    return json.loads(path.read_text(encoding='utf-8'))


def _read_model8_case2_json(filename: str) -> dict[str, Any]:
    path = MODEL8_CASE2_DIR / filename
    if not path.exists():
        raise services.NotFoundError(
            'Model-8 Case 2 coupling artifacts are missing. Run scripts/build_model8_case2_coupling.py first.'
        )
    return json.loads(path.read_text(encoding='utf-8'))


def _read_model8_case3_json(filename: str) -> dict[str, Any]:
    path = MODEL8_CASE3_DIR / filename
    if not path.exists():
        raise services.NotFoundError(
            'Model-8 Case 3 evidence-chain artifacts are missing. Run scripts/build_model8_case3_evidence.py first.'
        )
    return json.loads(path.read_text(encoding='utf-8'))


def _read_model8_case4_json(filename: str) -> dict[str, Any]:
    path = MODEL8_CASE4_DIR / filename
    if not path.exists():
        raise services.NotFoundError(
            'Model-8 Case 4 upload gold-standard artifacts are missing. Run scripts/build_model8_case4_upload_gold.py first.'
        )
    return json.loads(path.read_text(encoding='utf-8'))


def _read_model8_case5_json(filename: str) -> dict[str, Any]:
    path = MODEL8_CASE5_DIR / filename
    if not path.exists():
        raise services.NotFoundError(
            'Model-8 Case 5 HVG-Stoich artifacts are missing. Run scripts/build_model8_case5_hvg_stoich.py first.'
        )
    return json.loads(path.read_text(encoding='utf-8'))


def _read_model8_platform_json(filename: str) -> dict[str, Any] | list[Any]:
    path = MODEL8_PLATFORM_RELEASE_DIR / filename
    if not path.exists():
        raise services.NotFoundError(
            'Model-8 platform release artifacts are missing. Run scripts/build_model8_platform_release.py first.'
        )
    return json.loads(path.read_text(encoding='utf-8'))


def _read_model8_platform_csv(filename: str, limit: int = 400) -> list[dict[str, str]]:
    path = MODEL8_PLATFORM_RELEASE_DIR / filename
    if not path.exists():
        raise services.NotFoundError(
            'Model-8 platform release artifacts are missing. Run scripts/build_model8_platform_release.py first.'
        )
    rows = []
    with path.open('r', encoding='utf-8-sig', newline='') as handle:
        for idx, row in enumerate(csv.DictReader(handle)):
            if idx >= limit:
                break
            rows.append(dict(row))
    return rows


def _norm_model8_case_code(case_code: str) -> str:
    code = str(case_code or '').strip().upper()
    allowed = {'ECOLI', 'BSUB', 'ORYSA', 'DROME', 'YEAST', 'ARATH', 'DANRE', 'MOUSE'}
    if code not in allowed:
        raise services.NotFoundError(f'Model-8 species code is unavailable: {case_code}')
    return code


def _read_case_csv(path: Path, case_code: str = '', limit: int = 120) -> list[dict[str, str]]:
    if not path.exists():
        raise services.NotFoundError(f'Model-8 case artifact is missing: {path.name}')
    code = str(case_code or '').upper()
    rows: list[dict[str, str]] = []
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt', encoding='utf-8-sig', newline='') as handle:
        for row in csv.DictReader(handle):
            if code and str(row.get('case_code', '')).upper() != code:
                continue
            rows.append(dict(row))
            if len(rows) >= limit:
                break
    return rows


def _table_payload(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        'columns': list(rows[0].keys()) if rows else [],
        'rows': rows,
        'total': len(rows),
    }


def model8_case2_summary_payload() -> dict[str, Any]:
    return _read_model8_case2_json('summary.json')


def model8_case2_coupling_payload() -> dict[str, Any]:
    return _read_model8_case2_json('coupling.json')


def model8_case2_null_models_payload() -> dict[str, Any]:
    return _read_model8_case2_json('null_models.json')


def model8_case2_sensitivity_payload() -> dict[str, Any]:
    return _read_model8_case2_json('sensitivity.json')


def model8_case3_summary_payload() -> dict[str, Any]:
    return _read_model8_case3_json('summary.json')


def model8_case3_candidates_payload() -> dict[str, Any]:
    return _read_model8_case3_json('candidates.json')


def model8_case3_reports_payload() -> dict[str, Any]:
    return _read_model8_case3_json('reports.json')


def model8_case3_sensitivity_payload() -> dict[str, Any]:
    return _read_model8_case3_json('sensitivity.json')


def model8_case4_summary_payload() -> dict[str, Any]:
    return _read_model8_case4_json('summary.json')


def model8_case4_gold_payload() -> dict[str, Any]:
    return _read_model8_case4_json('gold_standard.json')


def model8_case4_workflows_payload() -> dict[str, Any]:
    return _read_model8_case4_json('workflows.json')


def model8_case4_validation_payload() -> dict[str, Any]:
    return _read_model8_case4_json('validation.json')


def model8_case4_species_payload(case_code: str) -> dict[str, Any]:
    code = _norm_model8_case_code(case_code)
    summary = model8_case4_summary_payload()
    gold = model8_case4_gold_payload()
    validation = model8_case4_validation_payload()
    workflows = model8_case4_workflows_payload()
    subset = next((row for row in gold.get('subset_manifest', []) if str(row.get('case_code', '')).upper() == code), {})
    selection_rows = [row for row in gold.get('selection_manifest', []) if str(row.get('case_code', '')).upper() == code]
    protein_rows = _read_case_csv(MODEL8_CASE4_DIR / 'expected_protein_features.csv', code, limit=500)
    nucleotide_rows = _read_case_csv(MODEL8_CASE4_DIR / 'expected_cds_transcript_features.csv', code, limit=500)
    agreement_rows = _read_case_csv(MODEL8_CASE4_DIR / 'platform_gold_agreement.csv', code, limit=1000)
    synthetic_rows = gold.get('synthetic_boundary', {}).get('error_cases', [])
    return {
        'case_id': summary.get('case_id'),
        'case_code': code,
        'species_status': {
            'case_code': code,
            'scientific_name': subset.get('scientific_name') or (selection_rows[0].get('scientific_name') if selection_rows else code),
            'protein_records': subset.get('protein_records'),
            'nucleotide_records': subset.get('nucleotide_records'),
            'gff3_rows': subset.get('gff3_rows'),
            'cds_status': subset.get('cds_status'),
            'gff3_subset_status': subset.get('gff3_subset_status'),
            'protein_sha256': subset.get('protein_sha256'),
            'nucleotide_sha256': subset.get('nucleotide_sha256'),
            'gff3_sha256': subset.get('gff3_sha256'),
        },
        'kpis': {
            'protein_feature_rows_previewed': len(protein_rows),
            'nucleotide_feature_rows_previewed': len(nucleotide_rows),
            'agreement_rows_previewed': len(agreement_rows),
            'global_total_checks': validation.get('agreement', {}).get('total_checks'),
            'global_pass_rate': validation.get('agreement', {}).get('pass_rate'),
        },
        'tables': {
            'selected_gold_records': _table_payload(selection_rows),
            'expected_protein_features': _table_payload(protein_rows),
            'expected_cds_transcript_features': _table_payload(nucleotide_rows),
            'platform_gold_agreement': _table_payload(agreement_rows),
            'tolerance_report': _table_payload(gold.get('tolerance_report', [])),
            'workflow_examples': _table_payload(workflows.get('workflow_examples', [])),
            'privacy_security_checks': _table_payload(workflows.get('privacy_security_checks', [])),
            'synthetic_error_cases': _table_payload(synthetic_rows),
        },
        'downloads': {
            'protein_gold_fasta': f"/api/stoichdb/case-studies/model8/download/case4_upload_gold/{subset.get('protein_gold_path', '')}",
            'nucleotide_gold_fasta': f"/api/stoichdb/case-studies/model8/download/case4_upload_gold/{subset.get('nucleotide_gold_path', '')}",
            'gff3_subset': f"/api/stoichdb/case-studies/model8/download/case4_upload_gold/{subset.get('gff3_subset_path', '')}",
            'expected_protein_features': '/api/stoichdb/case-studies/model8/download/case4_upload_gold/expected_protein_features.csv',
            'expected_cds_transcript_features': '/api/stoichdb/case-studies/model8/download/case4_upload_gold/expected_cds_transcript_features.csv',
            'platform_gold_agreement': '/api/stoichdb/case-studies/model8/download/case4_upload_gold/platform_gold_agreement.csv',
        },
    }


def model8_case5_summary_payload() -> dict[str, Any]:
    return _read_model8_case5_json('summary.json')


def model8_case5_phase1_payload() -> dict[str, Any]:
    return _read_model8_case5_json('phase1.json')


def model8_case5_phase2_payload() -> dict[str, Any]:
    return _read_model8_case5_json('phase2.json')


def model8_case5_downstream_payload() -> dict[str, Any]:
    return _read_model8_case5_json('downstream.json')


def model8_case5_species_payload(case_code: str) -> dict[str, Any]:
    code = _norm_model8_case_code(case_code)
    summary = model8_case5_summary_payload()
    species_status = next((row for row in summary.get('species_status', []) if str(row.get('case_code', '')).upper() == code), {})
    hvg_rows = _read_case_csv(MODEL8_CASE5_DIR / 'hvg_consensus.csv', code, limit=120)
    model_rows = _read_case_csv(MODEL8_CASE5_DIR / 'model_comparison.csv', code, limit=40)
    feature_rows = _read_case_csv(MODEL8_CASE5_DIR / 'feature_summary.csv', code, limit=80)
    prediction_rows = _read_case_csv(MODEL8_CASE5_DIR / 'cv_predictions.csv', code, limit=120)
    candidate_rows = _read_case_csv(MODEL8_CASE5_DIR / 'candidate_genes.csv', code, limit=80)
    control_rows = _read_case_csv(MODEL8_CASE5_DIR / 'matched_controls.csv', code, limit=80)
    enrichment_rows = _read_case_csv(MODEL8_CASE5_DIR / 'enrichment_results.csv', code, limit=80)
    joined_path = MODEL8_CASE5_DIR / f'{code}_joined_hvg_stoich.csv.gz'
    joined_rows = _read_case_csv(joined_path, code, limit=120) if joined_path.exists() else []
    comparison_dir = MODEL8_CASE5_DIR / 'hvg_nonhvg' / code
    comparison_summary_path = comparison_dir / 'hvg_nonhvg_summary.json'
    comparison_summary = json.loads(comparison_summary_path.read_text(encoding='utf-8')) if comparison_summary_path.exists() else {
        'status': 'legacy_not_generated',
        'comparison_status': 'legacy_not_generated',
        'reason': 'This frozen Case 5 species artifact has not been backfilled with hvg_nonhvg_v1.',
        'counts': {},
        'resolved_blocks': [],
    }
    comparison_mapping_summary_path = comparison_dir / 'hvg_multiomics_mapping_summary.json'
    comparison_mapping_summary = json.loads(comparison_mapping_summary_path.read_text(encoding='utf-8')) if comparison_mapping_summary_path.exists() else {}
    comparison_assembly_manifest_path = comparison_dir / 'hvg_multiomics_assembly_manifest.json'
    comparison_assembly_manifest = json.loads(comparison_assembly_manifest_path.read_text(encoding='utf-8')) if comparison_assembly_manifest_path.exists() else {}
    comparison_coverage_rows = _read_case_csv(comparison_dir / 'hvg_nonhvg_block_coverage.csv', limit=20) if (comparison_dir / 'hvg_nonhvg_block_coverage.csv').exists() else []
    comparison_rows = _read_case_csv(comparison_dir / 'hvg_nonhvg_feature_comparison.csv', limit=240) if (comparison_dir / 'hvg_nonhvg_feature_comparison.csv').exists() else []
    comparison_audit_rows = _read_case_csv(comparison_dir / 'hvg_nonhvg_feature_audit.csv', limit=240) if (comparison_dir / 'hvg_nonhvg_feature_audit.csv').exists() else []
    adjusted_rows = _read_case_csv(comparison_dir / 'hvg_nonhvg_adjusted_comparison.csv', limit=240) if (comparison_dir / 'hvg_nonhvg_adjusted_comparison.csv').exists() else []
    quantile_rows = _read_case_csv(comparison_dir / 'hvg_nonhvg_distribution_quantiles.csv', limit=480) if (comparison_dir / 'hvg_nonhvg_distribution_quantiles.csv').exists() else []
    family_rows = _read_case_csv(comparison_dir / 'hvg_nonhvg_family_summary.csv', limit=120) if (comparison_dir / 'hvg_nonhvg_family_summary.csv').exists() else []
    comparison_plots_path = comparison_dir / 'hvg_nonhvg_plots_payload.json'
    comparison_plots = json.loads(comparison_plots_path.read_text(encoding='utf-8')) if comparison_plots_path.exists() else {}
    # Keep the species overview bounded. Feature-level display points remain in
    # the downloadable plots artifact; the UI detail view uses compact quantiles.
    comparison_plots.pop('feature_distributions', None)
    comparison_downloads = {}
    for kind, filename in {
        'feature_audit': 'hvg_nonhvg_feature_audit.csv',
        'feature_comparison': 'hvg_nonhvg_feature_comparison.csv',
        'adjusted_comparison': 'hvg_nonhvg_adjusted_comparison.csv',
        'distribution_quantiles': 'hvg_nonhvg_distribution_quantiles.csv',
        'family_summary': 'hvg_nonhvg_family_summary.csv',
        'plots_payload': 'hvg_nonhvg_plots_payload.json',
        'summary': 'hvg_nonhvg_summary.json',
        'run_manifest': 'hvg_nonhvg_run_manifest.json',
        'multiomics_core_features': 'hvg_multiomics_core_features.csv',
        'feature_provenance': 'hvg_multiomics_feature_provenance.csv',
        'mapping_table': 'hvg_multiomics_mapping_table.csv',
        'mapping_summary': 'hvg_multiomics_mapping_summary.json',
        'assembly_manifest': 'hvg_multiomics_assembly_manifest.json',
        'block_coverage': 'hvg_nonhvg_block_coverage.csv',
    }.items():
        if (comparison_dir / filename).exists():
            comparison_downloads[kind] = f'/api/stoichdb/case-studies/model8/download/case5_hvg_stoich/hvg_nonhvg/{code}/{filename}'
    return {
        'case_id': summary.get('case_id'),
        'case_code': code,
        'species_status': species_status,
        'kpis': {
            'genes_profiled': species_status.get('genes_profiled'),
            'cells_or_samples': species_status.get('cells_or_samples'),
            'mapped_genes': species_status.get('mapped_genes'),
            'mapping_rate': species_status.get('mapping_rate'),
            'hvg_rows_previewed': len(hvg_rows),
            'candidate_rows_previewed': len(candidate_rows),
            'joined_rows_previewed': len(joined_rows),
        },
        'tables': {
            'top_hvg_consensus': _table_payload(hvg_rows),
            'model_comparison': _table_payload(model_rows),
            'feature_summary': _table_payload(feature_rows),
            'cv_predictions': _table_payload(prediction_rows),
            'candidate_genes': _table_payload(candidate_rows),
            'matched_controls': _table_payload(control_rows),
            'enrichment_results': _table_payload(enrichment_rows),
            'joined_hvg_stoich': _table_payload(joined_rows),
        },
        'group_comparison': {
            **comparison_summary,
            'features': comparison_rows,
            'audit': comparison_audit_rows,
            'adjusted': adjusted_rows,
            'quantiles': quantile_rows,
            'family_summary': family_rows or comparison_summary.get('family_summary', []),
            'plots': comparison_plots,
            'mapping_summary': comparison_mapping_summary,
            'hvg_multiomics_mapping_summary': comparison_mapping_summary,
            'assembly_manifest': comparison_assembly_manifest,
            'block_coverage': comparison_coverage_rows or comparison_summary.get('block_coverage', []),
            'downloads': comparison_downloads,
        },
        'downloads': {
            'joined_hvg_stoich': f'/api/stoichdb/case-studies/model8/download/case5_hvg_stoich/{code}_joined_hvg_stoich.csv.gz',
            'hvg_consensus': '/api/stoichdb/case-studies/model8/download/case5_hvg_stoich/hvg_consensus.csv',
            'candidate_genes': '/api/stoichdb/case-studies/model8/download/case5_hvg_stoich/candidate_genes.csv',
            'model_comparison': '/api/stoichdb/case-studies/model8/download/case5_hvg_stoich/model_comparison.csv',
            'enrichment_results': '/api/stoichdb/case-studies/model8/download/case5_hvg_stoich/enrichment_results.csv',
        },
    }


def model8_platform_release_payload() -> dict[str, Any]:
    manifest = _read_model8_platform_json('model8_platform_release_manifest.json')
    artifact_rows = _read_model8_platform_csv('case_artifact_registry.csv', limit=500)
    figure_rows = _read_model8_platform_csv('figure_mapping.csv', limit=500)
    claims = _read_model8_platform_json('claims.json')
    return {
        'manifest': manifest,
        'artifact_registry_preview': artifact_rows,
        'figure_mapping_preview': figure_rows,
        'claims': claims,
        'download_urls': {
            'bundle': '/api/stoichdb/case-studies/model8/download-bundle/',
            'artifact_registry': '/api/stoichdb/case-studies/model8/download/platform_release/case_artifact_registry.csv',
            'figure_mapping': '/api/stoichdb/case-studies/model8/download/platform_release/figure_mapping.csv',
            'claims': '/api/stoichdb/case-studies/model8/download/platform_release/claims.json',
            'manifest': '/api/stoichdb/case-studies/model8/download/platform_release/model8_platform_release_manifest.json',
        },
    }


def resolve_model8_platform_file(relative_path: str = '') -> Path:
    if relative_path == '__bundle__':
        candidate = MODEL8_PLATFORM_RELEASE_DIR / 'model8_case1_5_platform_bundle.zip'
    else:
        safe_path = Path(relative_path)
        if safe_path.is_absolute() or '..' in safe_path.parts:
            raise services.NotFoundError('Invalid Model-8 platform artifact path.')
        candidate = PROJECT_ROOT / 'data' / 'case_studies' / 'model8' / safe_path
    try:
        resolved = candidate.resolve(strict=True)
        allowed = (PROJECT_ROOT / 'data' / 'case_studies' / 'model8').resolve(strict=True)
        resolved.relative_to(allowed)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise services.NotFoundError(f'Model-8 platform artifact is unavailable: {relative_path}') from exc
    if not resolved.is_file():
        raise services.NotFoundError(f'Model-8 platform artifact is not a file: {relative_path}')
    return resolved


def model8_case1_summary_payload() -> dict[str, Any]:
    return _read_model8_case1_json('summary.json')


def model8_case1_matrix_payload() -> dict[str, Any]:
    return _read_model8_case1_json('matrix.json')


def model8_case1_pairwise_payload() -> dict[str, Any]:
    return _read_model8_case1_json('pairwise.json')


def model8_case1_sensitivity_payload() -> dict[str, Any]:
    return _read_model8_case1_json('sensitivity.json')


def _scope_payload() -> dict[str, Any]:
    try:
        platform_release = model8_platform_release_payload().get('manifest', {})
    except services.NotFoundError:
        platform_release = {}
    return {
        'implemented_cases': ['case1', 'case2', 'case3', 'case4', 'case5'],
        'deferred_cases': [],
        'implementation_mode': 'case1_advanced_taxonomy_aware_plus_internal_cases_plus_case4_upload_gold_plus_case5_hvg_stoich',
        'model8_platform_release': {
            'release_id': platform_release.get('release_id', ''),
            'artifact_count': platform_release.get('artifact_count', 0),
            'figure_mapping_count': platform_release.get('figure_mapping_count', 0),
            'bundle': platform_release.get('bundle', {}),
            'download_url': '/api/stoichdb/case-studies/model8/download-bundle/',
            'manifest_url': '/api/stoichdb/case-studies/model8/platform-release/',
        },
        'external_data_policy': 'Case 1 advanced uses local NCBI/Ensembl taxonomy metadata CSV files; case2/case3 remain internal-data descriptive cases; case4 uses frozen Model-8 reference sequences and upload workflow examples; case5 uses frozen local expression bundles linked to versioned Model-8 stoichiometric features.',
        'excluded_full_stage6_requirements': [
            'External literature-grade biological validation.',
            'Ecology-aware grouped comparison with habitat or environment metadata.',
            'Phylogenetic signal testing with a tree and branch lengths.',
            'Independent benchmark datasets beyond the current platform release.',
        ],
    }


@__import__('backend.apps.common.public_snapshots',fromlist=['snapshot']).snapshot('cases')
def case_study_gallery_payload() -> dict[str, Any]:
    if not services.db_mode():
        raise services.NotFoundError('Stage 6 case studies require the PostgreSQL-backed platform registry.')
    species_rows = _species_rows()
    return {
        'title': 'Stage 6 internal-data descriptive case-study gallery',
        'release': _release_summary(),
        'scope': _scope_payload(),
        'support_matrix': {
            'current_data_supports': [
                'Complete-omics species-level fingerprint atlas.',
                'Taxonomy-aware descriptive comparison by phylum, class, and order for Case 1 advanced.',
                'Stored cross-omics coupling explanation for species with cross_omics_payload.',
                'Candidate protein report when ProteinIndex annotations and proteome EntityRecord features are present.',
                'Fixed sequence-upload gold standard with synthetic boundary cases, Model-8 real FASTA inputs, workflow manifests, and tolerance checks.',
                'Eight-model-organism HVG-Stoich flagship workflow with expression HVG consensus, feature mapping boundaries, CV models, permutation nulls, matched controls, and candidate gene outputs.',
            ],
            'current_data_missing': [
                'Habitat, phylogeny, branch length, and ecology metadata for robust mechanism-level biological interpretation.',
                'Complete cross-reference tables for rice LOC/EVM IDs and additional expression ID harmonization for zebrafish and mouse below the declared mapping threshold.',
                'Measured protein abundance data for regulatory validation beyond transcript-derived HVG profiles.',
            ],
        },
        'cases': [
            _case1_species_atlas(species_rows),
            _case2_cross_omics_coupling(species_rows),
            _case3_candidate_entity_report(),
            _case4_upload_gold_workflow(),
            _case5_hvg_stoich_workflow(),
        ],
    }
