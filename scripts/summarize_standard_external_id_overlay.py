#!/usr/bin/env python3
"""Summarize generated standard external-ID overlay artifacts."""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = PROJECT_ROOT / "data" / "id_mapping" / "standard_external_id_overlay"
WORK_ROOT = PROJECT_ROOT / "workspace" / "generated_analysis_artifacts" / "standard_external_id_overlay"
GROUPS = ("protists", "bacteria", "fungi", "metazoa", "plants", "vertebrates")


def count_csv_rows(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return max(sum(1 for _ in fh) - 1, 0)


def summarize_group(group: str) -> dict:
    group_dir = DATA_ROOT / group
    csv_files = sorted(group_dir.glob("*.standard_id_overlay.csv"))
    empty_files = sorted(group_dir.glob("*.no_external.json"))
    index_path = group_dir / f"{group}_standard_id_overlay_index.csv"
    accession_map = group_dir / f"{group}_uniprot_online_accession_map.csv"
    local_summary_path = group_dir / f"{group}_standard_id_overlay_summary.json"
    overlay_rows = 0
    rows_with_uniprot = 0
    rows_with_ncbi_gene = 0
    rows_with_ncbi_protein = 0
    species_index_rows = 0
    species_with_overlay = 0
    species_without_overlay = 0
    if index_path.exists():
        with index_path.open("r", encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                species_index_rows += 1
                if int(float(row.get("overlay_rows") or 0)):
                    species_with_overlay += 1
                else:
                    species_without_overlay += 1
                overlay_rows += int(float(row.get("overlay_rows") or 0))
                rows_with_uniprot += int(float(row.get("rows_with_uniprot") or 0))
                rows_with_ncbi_gene += int(float(row.get("rows_with_ncbi_gene") or 0))
                rows_with_ncbi_protein += int(float(row.get("rows_with_ncbi_protein") or 0))
    return {
        "division": group,
        "species_index_rows": species_index_rows,
        "species_with_overlay": species_with_overlay,
        "species_without_overlay": species_without_overlay,
        "physical_overlay_files": len(csv_files),
        "physical_no_external_markers": len(empty_files),
        "overlay_rows": overlay_rows,
        "rows_with_uniprot": rows_with_uniprot,
        "rows_with_ncbi_gene": rows_with_ncbi_gene,
        "rows_with_ncbi_protein": rows_with_ncbi_protein,
        "online_accession_map_rows": count_csv_rows(accession_map),
        "bytes_overlay_csv": sum(path.stat().st_size for path in csv_files),
        "outputs": {
            "group_dir": str(group_dir),
            "index_csv": str(index_path),
            "online_accession_map": str(accession_map),
            "local_summary": str(local_summary_path),
        },
    }


def main() -> int:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    groups = [summarize_group(group) for group in GROUPS]
    manifest = {
        "schema_version": "standard_external_id_overlay.v1.combined",
        "generated_at_unix": int(time.time()),
        "groups": groups,
        "sources": {
            "local_annotation": "Ensembl/Ensembl Genomes downloaded GFF3 files",
            "online_api": "UniProt REST ID Mapping API",
        },
        "platform_runtime": {
            "overlay_root": "data/id_mapping/standard_external_id_overlay",
            "merge_keys": ["species_id", "gene_id", "transcript_id", "protein_id", "source_protein_id"],
            "external_targets": ["UniProtKB", "NCBI Gene", "NCBI Protein/RefSeq Protein", "NCBI Transcript/RefSeq Transcript"],
        },
    }
    manifest_path = DATA_ROOT / "standard_external_id_overlay_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    report_lines = [
        "# 标准外部 ID 覆盖层优化结果说明",
        "",
        "## 完成情况",
        "",
        "已完成六类群本地 GFF3 注释解析与 UniProt REST 在线补充，并生成可被平台运行时合并读取的 `standard_external_id_overlay` 覆盖层。",
        "",
        "| 类群 | 完成物种标记 | 覆盖层行数 | UniProt 行 | NCBI Gene 行 | NCBI Protein 行 | 在线 accession 映射行 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for item in groups:
        report_lines.append(
            f"| {item['division']} | {item['species_index_rows']:,} | {item['overlay_rows']:,} | "
            f"{item['rows_with_uniprot']:,} | {item['rows_with_ncbi_gene']:,} | "
            f"{item['rows_with_ncbi_protein']:,} | {item['online_accession_map_rows']:,} |"
        )
    report_lines.extend(
        [
            "",
            "## 未完全补齐的原因",
            "",
            "外部标准 ID 只能在 Ensembl/Ensembl Genomes GFF3 或 UniProtKB 官方交叉引用实际存在时获取；没有 Dbxref、UniProt accession 或 NCBI cross-reference 的内部 ID 不能可靠推断，已保留为空结果标记。",
            "",
            "## 平台接入",
            "",
            "后端 `id_mapping.py` 已增加覆盖层读取、合并和按物种外部 ID 反向解析逻辑；不需要重写原有超大宽表或重建 SQLite 即可在运行时补充展示。",
        ]
    )
    report_path = DATA_ROOT / "standard_external_id_overlay_result_report.md"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
