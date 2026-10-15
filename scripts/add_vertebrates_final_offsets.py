#!/usr/bin/env python3
"""Append vertebrates byte offsets to the final-whitelist external offset index."""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
F_OUT = PROJECT_ROOT / "workspace" / "generated_analysis_artifacts" / "id_mapping_final_whitelist" / "vertebrates" / "final_whitelist_external_offsets.with_vertebrates.json"
G_PROJECT = Path("G:/") / "stoichioomics" / "\u9879\u76ee\u5e73\u53f0\u6570\u636e" / "stoich_platform_postgres_open_search_v6_2_perf_fix" / "proj"
EXISTING = G_PROJECT / "data" / "id_mapping" / "final_whitelist" / "final_whitelist_external_offsets.json"
VERTEBRATES_EXTERNAL = G_PROJECT / "data" / "id_mapping" / "final_whitelist" / "vertebrates" / "vertebrates_external_id_mapping_final_whitelist.csv"


def build_vertebrates_offsets() -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    start = time.time()
    species_offsets: dict[str, dict[str, object]] = {}
    with VERTEBRATES_EXTERNAL.open("rb") as fh:
        header_raw = fh.readline()
        header = next(csv.reader([header_raw.decode("utf-8-sig", errors="replace").rstrip("\r\n")]))
        species_idx = header.index("species_id")
        current_species = ""
        current_start = fh.tell()
        row_count = 0
        group_row_count = 0
        while True:
            pos = fh.tell()
            raw = fh.readline()
            if not raw:
                if current_species:
                    species_offsets[current_species] = {
                        "division": "vertebrates",
                        "path": str(VERTEBRATES_EXTERNAL),
                        "start_byte": current_start,
                        "end_byte": pos,
                        "row_count": row_count,
                    }
                break
            try:
                row = next(csv.reader([raw.decode("utf-8", errors="replace")]))
            except Exception:
                continue
            species_id = row[species_idx] if species_idx < len(row) else ""
            if not current_species:
                current_species = species_id
                current_start = pos
                row_count = 0
            if species_id != current_species:
                species_offsets[current_species] = {
                    "division": "vertebrates",
                    "path": str(VERTEBRATES_EXTERNAL),
                    "start_byte": current_start,
                    "end_byte": pos,
                    "row_count": row_count,
                }
                current_species = species_id
                current_start = pos
                row_count = 0
            row_count += 1
            group_row_count += 1
            if group_row_count % 1_000_000 == 0:
                print(f"[offsets] rows={group_row_count:,} species={len(species_offsets):,}", flush=True)
    group_info = {
        "division": "vertebrates",
        "path": str(VERTEBRATES_EXTERNAL),
        "size_bytes": VERTEBRATES_EXTERNAL.stat().st_size,
        "header": header,
        "species_count": len(species_offsets),
        "row_count": group_row_count,
        "runtime_seconds": round(time.time() - start, 3),
    }
    return group_info, species_offsets


def main() -> int:
    start = time.time()
    index = json.loads(EXISTING.read_text(encoding="utf-8")) if EXISTING.exists() else {
        "schema_version": "final_whitelist_offset_index.v1",
        "groups": {},
        "species": {},
    }
    group_info, species_offsets = build_vertebrates_offsets()
    index.setdefault("groups", {})["vertebrates"] = group_info
    species = index.setdefault("species", {})
    for key in [key for key, value in species.items() if value.get("division") == "vertebrates"]:
        species.pop(key, None)
    species.update(species_offsets)
    index["updated_at_unix"] = int(time.time())
    index["runtime_seconds_with_vertebrates_append"] = round(time.time() - start, 3)
    F_OUT.parent.mkdir(parents=True, exist_ok=True)
    F_OUT.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(F_OUT), "vertebrates": group_info, "total_species": len(species)}, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
