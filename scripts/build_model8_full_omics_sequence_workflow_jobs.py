from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

EXTRACTOR_ROOT = Path(r"G:\stoichioomics\项目平台数据\组学化学计量特征提取代码")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.config.settings")
os.environ["STOICH_FEATURE_EXTRACTOR_ROOT"] = str(EXTRACTOR_ROOT)

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402

from backend.apps.common.reproducibility import sha256_file, utc_now_iso, write_reproducibility_manifest  # noqa: E402
from backend.apps.sequence_analysis.feature_panels import build_core_feature_panels  # noqa: E402
from backend.apps.sequence_analysis.real_engine import (  # noqa: E402
    EXTRACTOR_FILES,
    PREFERRED_FEATURES,
    _build_basic_visualization_payload,
    _build_feature_catalog,
    _build_feature_summary,
    _build_method_metadata,
    _build_sample_comparison_payload,
    _build_summary_analysis,
    _build_top_low_entities,
    _differential_entities,
    _differential_features,
    _normalize_feature_table,
    _plots_payload,
    _safe_json,
    _write_json,
    feature_extractor_contract,
    ml_discrimination_from_rows,
    numeric_feature_columns,
)
from backend.apps.sequence_analysis.services import OUTPUT_FILES  # noqa: E402


DOWNLOAD_ROOT = Path(r"G:\stoichioomics\全组学下载数据")
FEATURE_ROOT = Path(r"G:\stoichioomics\全组学特征数据")
EXAMPLE_ROOT = PROJECT_ROOT / "data" / "examples" / "sequence_analysis_results"

SPECIES = {
    "ECOLI": {
        "case_code": "ECOLI",
        "species_id": "ECOLI_MG1655",
        "scientific_name": "Escherichia coli str. K-12 substr. MG1655",
        "download_dir": DOWNLOAD_ROOT / "bacteria" / "escherichia_coli_str_k_12_substr_mg1655_gca_000005845",
        "feature": {
            "genome": FEATURE_ROOT / "细菌" / "基因组" / "escherichia_coli_str_k_12_substr_mg1655_gca_000005845.genome_features.csv",
            "transcriptome": FEATURE_ROOT / "细菌" / "转录组" / "escherichia_coli_str_k_12_substr_mg1655_gca_000005845.transcriptome.full.v5.csv",
            "proteome": FEATURE_ROOT / "细菌" / "蛋白质组" / "escherichia_coli_str_k_12_substr_mg1655_gca_000005845" / "escherichia_coli_str_k_12_substr_mg1655_gca_000005845.proteome_features.full.csv",
        },
        "sequence": {
            "genome": "Escherichia_coli_str_k_12_substr_mg1655_gca_000005845.ASM584v2.dna.toplevel.fa.gz",
            "transcriptome": "Escherichia_coli_str_k_12_substr_mg1655_gca_000005845.ASM584v2.cdna.all.fa.gz",
            "proteome": "Escherichia_coli_str_k_12_substr_mg1655_gca_000005845.ASM584v2.pep.all.fa.gz",
            "gff3": "Escherichia_coli_str_k_12_substr_mg1655_gca_000005845.ASM584v2.62.gff3.gz",
        },
    },
    "YEAST": {
        "case_code": "YEAST",
        "species_id": "YEAST_R64",
        "scientific_name": "Saccharomyces cerevisiae R64-1-1",
        "download_dir": DOWNLOAD_ROOT / "fungi" / "saccharomyces_cerevisiae",
        "feature": {
            "genome": FEATURE_ROOT / "真菌" / "基因组" / "saccharomyces_cerevisiae.genome_features.csv",
            "transcriptome": FEATURE_ROOT / "真菌" / "转录组" / "saccharomyces_cerevisiae.transcriptome.full.v5.csv",
            "proteome": FEATURE_ROOT / "真菌" / "蛋白质组" / "saccharomyces_cerevisiae" / "saccharomyces_cerevisiae.proteome_features.full.csv",
        },
        "sequence": {
            "genome": "Saccharomyces_cerevisiae.R64-1-1.dna.toplevel.fa.gz",
            "transcriptome": "Saccharomyces_cerevisiae.R64-1-1.cdna.all.fa.gz",
            "proteome": "Saccharomyces_cerevisiae.R64-1-1.pep.all.fa.gz",
            "gff3": "Saccharomyces_cerevisiae.R64-1-1.62.gff3.gz",
        },
    },
}

JOB_SPECS = [
    {
        "job_id": "seq_model8_full_ECOLI_genome_single_sequence",
        "name": "Model-8 ECOLI full genome single-sequence",
        "analysis_type": "single_sequence",
        "omics": "genome",
        "species": ["ECOLI"],
        "sample_count": 1,
        "group_field": "group",
        "reference_group": "",
    },
    {
        "job_id": "seq_model8_full_YEAST_genome_single_sequence",
        "name": "Model-8 YEAST full genome single-sequence",
        "analysis_type": "single_sequence",
        "omics": "genome",
        "species": ["YEAST"],
        "sample_count": 1,
        "group_field": "group",
        "reference_group": "",
    },
    {
        "job_id": "seq_model8_full_ECOLI_transcriptome_multi_sample",
        "name": "Model-8 ECOLI full transcriptome multi-sample",
        "analysis_type": "multi_sample",
        "omics": "transcriptome",
        "species": ["ECOLI"],
        "sample_count": 4,
        "group_field": "condition",
        "reference_group": "fraction_1",
    },
    {
        "job_id": "seq_model8_full_YEAST_transcriptome_multi_sample",
        "name": "Model-8 YEAST full transcriptome multi-sample",
        "analysis_type": "multi_sample",
        "omics": "transcriptome",
        "species": ["YEAST"],
        "sample_count": 4,
        "group_field": "condition",
        "reference_group": "fraction_1",
    },
    {
        "job_id": "seq_model8_full_ECOLI_YEAST_proteome_multi_species",
        "name": "Model-8 ECOLI + YEAST full proteome multi-species",
        "analysis_type": "multi_species",
        "omics": "proteome",
        "species": ["ECOLI", "YEAST"],
        "sample_count": 2,
        "group_field": "species_id",
        "reference_group": "ECOLI_MG1655",
    },
    {
        "job_id": "seq_model8_full_ECOLI_YEAST_genome_multi_species",
        "name": "Model-8 ECOLI + YEAST full genome multi-species",
        "analysis_type": "multi_species",
        "omics": "genome",
        "species": ["ECOLI", "YEAST"],
        "sample_count": 2,
        "group_field": "species_id",
        "reference_group": "ECOLI_MG1655",
    },
]

OLD_DERIVED_JOB_IDS = [
    "seq_model8_case4_ECOLI_proteome_multi_sample",
    "seq_model8_case4_YEAST_proteome_multi_sample",
]

ANALYSIS_FEATURE_LIMIT = 72
ANALYSIS_METADATA_COLUMNS = [
    "entity_id",
    "gene_id",
    "gene_name",
    "gene_symbol",
    "transcript_id",
    "protein_id",
    "sample_id",
    "group",
    "condition",
    "species_id",
    "case_code",
    "scientific_name",
    "strategy_cluster",
    "strategy_score",
    "gene_key",
    "file_name",
    "gff_file",
    "omics_type",
    "source_species_id",
    "source_feature_table",
]


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def _append_log(job_root: Path, event: str, payload: dict[str, Any]) -> None:
    path = job_root / "logs" / "job_events.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"ts": utc_now_iso(), "event": event, "payload": payload}, ensure_ascii=False) + "\n")


def _stable_bucket(value: Any, buckets: int, salt: str) -> int:
    raw = f"{salt}|{value}".encode("utf-8", errors="ignore")
    return int(hashlib.sha256(raw).hexdigest()[:12], 16) % buckets


def _entity_key(row: pd.Series) -> str:
    for col in ("entity_id", "gene_id", "transcript_id", "protein_id", "source_gene_id"):
        if col in row and pd.notna(row[col]) and str(row[col]).strip():
            return str(row[col])
    return str(row.name)


def _source_sequence_paths(code: str, omics: str) -> list[Path]:
    info = SPECIES[code]
    paths = [info["download_dir"] / info["sequence"][omics]]
    if omics == "genome":
        paths.append(info["download_dir"] / info["sequence"]["gff3"])
    return paths


def _manifest_for_path(path: Path, role: str) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    return {
        "role": role,
        "path": str(path),
        "name": path.name,
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _load_species_feature_table(code: str, omics: str) -> pd.DataFrame:
    info = SPECIES[code]
    path = info["feature"][omics]
    if not path.exists():
        raise FileNotFoundError(path)
    df = pd.read_csv(path, low_memory=False)
    df["source_species_id"] = df.get("species_id", "")
    df["species_id"] = info["species_id"]
    df["case_code"] = info["case_code"]
    df["scientific_name"] = info["scientific_name"]
    df["source_feature_table"] = str(path)
    return df


def _assign_samples(df: pd.DataFrame, *, code: str, spec: dict[str, Any]) -> pd.DataFrame:
    data = df.copy()
    analysis_type = spec["analysis_type"]
    sample_count = int(spec["sample_count"])
    if analysis_type == "single_sequence":
        data["sample_id"] = f"{code.lower()}_{spec['omics']}_full"
        data["condition"] = "single"
        data["group"] = "single"
        return data

    if analysis_type == "multi_sample":
        keys = data.apply(_entity_key, axis=1)
        buckets = keys.map(lambda value: _stable_bucket(value, sample_count, spec["job_id"]))
        labels = buckets.map(lambda idx: f"fraction_{idx + 1}")
        data["sample_id"] = labels.map(lambda label: f"{code.lower()}_{spec['omics']}_{label}")
        data["condition"] = labels
        data["group"] = labels
        return data

    keys = data.apply(_entity_key, axis=1)
    buckets = keys.map(lambda value: _stable_bucket(value, sample_count, spec["job_id"]))
    data["sample_id"] = buckets.map(lambda idx: f"{code.lower()}_{spec['omics']}_sample_{idx + 1}")
    data["condition"] = buckets.map(lambda idx: f"sample_{idx + 1}")
    data["group"] = data["species_id"]
    return data


def _build_feature_df(spec: dict[str, Any]) -> pd.DataFrame:
    frames = []
    for code in spec["species"]:
        raw = _load_species_feature_table(code, spec["omics"])
        frames.append(_assign_samples(raw, code=code, spec=spec))
    return _normalize_feature_table(pd.concat(frames, ignore_index=True), spec["omics"])


def _analysis_frame(full_df: pd.DataFrame, omics: str) -> pd.DataFrame:
    numeric = numeric_feature_columns(full_df)
    preferred = [col for col in PREFERRED_FEATURES.get(omics, []) if col in numeric]
    remaining = [col for col in numeric if col not in preferred]
    if remaining:
        variances = full_df[remaining].apply(pd.to_numeric, errors="coerce").var(skipna=True).sort_values(ascending=False)
        remaining = [col for col in variances.index if pd.notna(variances[col]) and variances[col] > 0]
    selected = list(dict.fromkeys([*preferred, *remaining[: max(0, ANALYSIS_FEATURE_LIMIT - len(preferred))]]))
    metadata = [col for col in ANALYSIS_METADATA_COLUMNS if col in full_df.columns]
    columns = list(dict.fromkeys([*metadata, *selected]))
    return full_df[columns].copy()


def _write_outputs(feature_df: pd.DataFrame, output_dir: Path, spec: dict[str, Any]) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    omics = spec["omics"]
    feature_set = "full"
    analysis_type = spec["analysis_type"]
    reference_group = spec["reference_group"]
    group_field = spec["group_field"]
    analysis_df = _analysis_frame(feature_df, omics)

    diff_features, diff_meta, rf_model_features = _differential_features(analysis_df, analysis_type, reference_group, omics)
    diff_entities = _differential_entities(analysis_df, analysis_type, reference_group, diff_features, rf_model_features, omics)
    summary_payload, analysis_payload, platform_bundle = _build_summary_analysis(analysis_df, omics, feature_set)
    feature_catalog = _build_feature_catalog(analysis_df, omics)
    feature_summary_table, feature_summary_payload = _build_feature_summary(feature_df, feature_catalog)
    basic_visualization = _build_basic_visualization_payload(analysis_df, feature_catalog, feature_summary_table, omics)
    core_feature_panels = build_core_feature_panels(analysis_df, omics)
    top_low_table, top_low_payload = _build_top_low_entities(analysis_df, feature_catalog, n=10)
    sample_comparison = _build_sample_comparison_payload(analysis_df, diff_features, diff_entities, reference_group, omics)
    ml_discrimination = ml_discrimination_from_rows(analysis_df, label_field="group")
    method_metadata = _build_method_metadata(
        analysis_type=analysis_type,
        omics=omics,
        feature_set=feature_set,
        resolved_group_field=group_field,
        reference_group=reference_group,
        feature_catalog=feature_catalog,
        basic_visualization=basic_visualization,
        sample_comparison=sample_comparison,
        ml_discrimination=ml_discrimination,
    )
    method_metadata["feature_extraction"]["method"] = "precomputed_full_omics_feature_tables_matched_to_project_extractors"
    method_metadata["feature_extraction"]["raw_input_policy"] = "full source sequence files remain in G:\\stoichioomics\\全组学下载数据; workflow outputs are persisted as curated examples"
    plots = _plots_payload(analysis_df, diff_features, diff_entities, platform_bundle, omics)

    feature_df.to_csv(output_dir / OUTPUT_FILES["features"], index=False)
    feature_df.to_csv(output_dir / OUTPUT_FILES["platform_rows"], index=False)
    diff_features.to_csv(output_dir / OUTPUT_FILES["differential_features"], index=False)
    diff_entities.to_csv(output_dir / OUTPUT_FILES["differential_entities"], index=False)
    feature_summary_table.to_csv(output_dir / OUTPUT_FILES["feature_summary_csv"], index=False)
    top_low_table.to_csv(output_dir / OUTPUT_FILES["top_low_entities_csv"], index=False)
    pd.DataFrame(sample_comparison.get("differential_features", [])).to_csv(output_dir / OUTPUT_FILES["sample_comparison_features_csv"], index=False)
    pd.DataFrame(sample_comparison.get("differential_entities", [])).to_csv(output_dir / OUTPUT_FILES["sample_comparison_entities_csv"], index=False)
    pd.DataFrame(ml_discrimination.get("feature_importance", [])).to_csv(output_dir / OUTPUT_FILES["ml_feature_importance"], index=False)
    pd.DataFrame(ml_discrimination.get("predictions", [])).to_csv(output_dir / OUTPUT_FILES["ml_predictions"], index=False)

    summary = {
        "analysis_type": analysis_type,
        "omics_type": omics,
        "feature_set": feature_set,
        "group_field": group_field,
        "reference_group": reference_group or None,
        "input_file_count": sum(len(_source_sequence_paths(code, omics)) for code in spec["species"]),
        "annotation_file_count": sum(1 for code in spec["species"] for path in _source_sequence_paths(code, omics) if path.name.endswith(".gff3.gz")),
        "record_count": int(len(feature_df)),
        "sample_count": int(feature_df["sample_id"].nunique()),
        "group_count": int(feature_df["group"].nunique()),
        "species_count": int(feature_df["species_id"].nunique()),
        "feature_count": int(len(numeric_feature_columns(analysis_df))),
        "full_feature_count": int(len(numeric_feature_columns(feature_df))),
        "analysis_feature_count": int(len(numeric_feature_columns(analysis_df))),
        "differential_feature_count": int(len(diff_features)),
        "differential_entity_count": int(len(diff_entities)),
        "significant_feature_count": int((pd.to_numeric(diff_features.get("fdr"), errors="coerce").fillna(1.0) <= 0.05).sum()) if not diff_features.empty and "fdr" in diff_features else 0,
        "extractor_root": str(EXTRACTOR_ROOT),
        "differential_method": diff_meta,
        "platform_summary": summary_payload,
        "feature_catalog": {
            "feature_count": feature_catalog.get("feature_count", 0),
            "families": feature_catalog.get("families", []),
        },
        "artifact_contract": {
            "evidence_level": "descriptive/exploratory",
            "source": "full_omics_precomputed_feature_tables",
            "analysis_matrix": f"full row set with {ANALYSIS_FEATURE_LIMIT} prioritized numeric features for expensive visual/statistical modules",
            "new_optimization_artifacts": [
                "feature_catalog",
                "feature_summary",
                "basic_visualization",
                "top_low_entities",
                "sample_comparison",
                "ml_discrimination",
            ],
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
        "outputs": OUTPUT_FILES,
    }
    _write_json(output_dir / OUTPUT_FILES["feature_catalog"], feature_catalog)
    _write_json(output_dir / OUTPUT_FILES["feature_summary"], feature_summary_payload)
    _write_json(output_dir / OUTPUT_FILES["basic_visualization"], basic_visualization)
    _write_json(output_dir / OUTPUT_FILES["core_feature_panels"], core_feature_panels)
    _write_json(output_dir / OUTPUT_FILES["top_low_entities"], top_low_payload)
    _write_json(output_dir / OUTPUT_FILES["sample_comparison"], sample_comparison)
    _write_json(output_dir / OUTPUT_FILES["sample_comparison_features"], {"rows": sample_comparison.get("differential_features", []), "method_metadata": sample_comparison.get("method_metadata", {})})
    _write_json(output_dir / OUTPUT_FILES["sample_comparison_entities"], {"rows": sample_comparison.get("differential_entities", []), "method_metadata": sample_comparison.get("method_metadata", {})})
    _write_json(output_dir / OUTPUT_FILES["ml_discrimination"], ml_discrimination)
    _write_json(output_dir / OUTPUT_FILES["ml_feature_importance_json"], {"rows": ml_discrimination.get("feature_importance", []), "method_metadata": ml_discrimination.get("method_metadata", {})})
    _write_json(output_dir / OUTPUT_FILES["ml_predictions_json"], {"rows": ml_discrimination.get("predictions", []), "method_metadata": ml_discrimination.get("method_metadata", {})})
    _write_json(output_dir / OUTPUT_FILES["method_metadata"], method_metadata)
    _write_json(output_dir / OUTPUT_FILES["summary"], summary)
    _write_json(output_dir / OUTPUT_FILES["analysis"], analysis_payload)
    _write_json(output_dir / OUTPUT_FILES["platform_bundle"], platform_bundle)
    _write_json(output_dir / OUTPUT_FILES["plots"], plots)
    _write_json(output_dir / OUTPUT_FILES["run_log"], {
        "started_at": summary["created_at"],
        "finished_at": utc_now_iso(),
        "raw_inputs_deleted_after_run": False,
        "source_mode": "full_omics_precomputed_feature_table",
        "extractors": EXTRACTOR_FILES,
        "full_database_feature_extractor_contract": feature_extractor_contract(),
        "artifacts": OUTPUT_FILES,
        "samples": feature_df[["sample_id", "group", "species_id", "condition"]].drop_duplicates().to_dict(orient="records"),
    })
    return _safe_json(summary)


def _source_inputs_for_job(spec: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for code in spec["species"]:
        feature_path = SPECIES[code]["feature"][spec["omics"]]
        rows.append(_manifest_for_path(feature_path, "full_feature_table"))
        for path in _source_sequence_paths(code, spec["omics"]):
            role = "gff3_annotation" if path.name.endswith(".gff3.gz") else f"{spec['omics']}_sequence"
            rows.append(_manifest_for_path(path, role))
    for omics, filename in EXTRACTOR_FILES.items():
        rows.append(_manifest_for_path(EXTRACTOR_ROOT / filename, f"{omics}_extractor_script"))
    return rows


def _write_job_json(job_root: Path, spec: dict[str, Any], summary: dict[str, Any]) -> None:
    code = "_".join(spec["species"])
    species_codes = spec["species"]
    job = {
        "job_id": spec["job_id"],
        "name": spec["name"],
        "status": "SUCCEEDED",
        "analysis_type": spec["analysis_type"],
        "omics_type": spec["omics"],
        "group_field": spec["group_field"],
        "reference_group": spec["reference_group"],
        "feature_set": "full",
        "genetic_code": 11 if "ECOLI" in species_codes else 1,
        "created_at": summary["created_at"],
        "updated_at": utc_now_iso(),
        "expires_at": None,
        "source": "persistent_model8_full_omics_sequence_upload",
        "is_example": True,
        "case_family": "model8_case4_upload_gold",
        "species_case_code": code,
        "species_case_codes": species_codes,
        "standard_sequence_upload_case": True,
        "full_omics_sequence_upload_case": True,
        "summary": summary,
        "outputs": OUTPUT_FILES,
        "inputs": {
            "files": [row["name"] for row in _source_inputs_for_job(spec) if row["role"].endswith("_sequence")],
            "annotation_files": [row["name"] for row in _source_inputs_for_job(spec) if row["role"] == "gff3_annotation"],
            "sample_sheet": None,
            "manifest": {
                "files": _source_inputs_for_job(spec),
                "split_strategy": {
                    "method": "stable_sha256_bucket_without_sampling",
                    "sample_count": spec["sample_count"],
                    "salt": spec["job_id"],
                    "note": "Rows are partitioned into workflow samples deterministically; all full feature-table rows are retained.",
                },
            },
        },
        "privacy": {
            "raw_uploads_persisted": True,
            "raw_uploads_location": str(DOWNLOAD_ROOT),
            "derived_results_persisted_until": "public full-omics example release",
            "cleanup_policy": "persistent_curated_full_omics_example",
            "workspace_isolation": "per-sequence-job example directory",
        },
        "reproducibility": {
            "manifest_path": str(job_root / "logs" / "reproducibility_manifest.json"),
            "run_log_path": str(job_root / "logs" / "job_events.log"),
        },
    }
    _write_json(job_root / "job.json", job)


def build_job(spec: dict[str, Any]) -> dict[str, Any]:
    job_root = EXAMPLE_ROOT / spec["job_id"]
    output_dir = job_root / "outputs"
    job_root.mkdir(parents=True, exist_ok=True)
    log_path = job_root / "logs" / "job_events.log"
    if log_path.exists():
        log_path.unlink()
    params = {
        "analysis_type": spec["analysis_type"],
        "omics_type": spec["omics"],
        "feature_set": "full",
        "group_field": spec["group_field"],
        "reference_group": spec["reference_group"],
        "species": spec["species"],
        "source_mode": "full_omics_precomputed_feature_table",
    }
    _append_log(job_root, "job_created", {"parameters": params})
    feature_df = _build_feature_df(spec)
    _append_log(job_root, "feature_table_loaded", {
        "rows": int(len(feature_df)),
        "samples": int(feature_df["sample_id"].nunique()),
        "groups": int(feature_df["group"].nunique()),
        "species": int(feature_df["species_id"].nunique()),
    })
    summary = _write_outputs(feature_df, output_dir, spec)
    _write_job_json(job_root, spec, summary)
    write_reproducibility_manifest(
        job_root / "logs" / "reproducibility_manifest.json",
        job_id=spec["job_id"],
        pipeline_type="sequence_analysis",
        parameters=params,
        inputs=_source_inputs_for_job(spec),
        base_dir=settings.BASE_DIR,
        extra={
            "stage": "succeeded",
            "case_family": "model8_case4_upload_gold",
            "full_omics_sequence_upload_case": True,
            "standard_sequence_upload_case": True,
            "outputs": OUTPUT_FILES,
            "feature_extractor_contract": feature_extractor_contract(),
        },
    )
    _append_log(job_root, "job_succeeded", {"summary": summary})
    return {
        "job_id": spec["job_id"],
        "record_count": summary["record_count"],
        "sample_count": summary["sample_count"],
        "group_count": summary["group_count"],
        "feature_count": summary["feature_count"],
    }


def hide_old_derived_jobs() -> None:
    for job_id in OLD_DERIVED_JOB_IDS:
        path = EXAMPLE_ROOT / job_id / "job.json"
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["hidden_from_sequence_index"] = True
        payload["hidden_reason"] = "Superseded by full-omics ECOLI/YEAST workflow jobs built from G:\\stoichioomics source data."
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build full-omics ECOLI/YEAST sequence workflow jobs.")
    parser.add_argument("--jobs", nargs="*", default=[spec["job_id"] for spec in JOB_SPECS])
    args = parser.parse_args()
    wanted = set(args.jobs)
    selected = [spec for spec in JOB_SPECS if spec["job_id"] in wanted]
    if not selected:
        raise SystemExit("No matching jobs selected.")
    hide_old_derived_jobs()
    built = [build_job(spec) for spec in selected]
    print(json.dumps({"built": built}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
