#!/usr/bin/env python3
"""Build byte-offset indexes for final-whitelist ID mapping CSV files.

The final-whitelist mapping files are intentionally kept as CSV download/import
sources. This index lets the runtime service seek directly to one species block
instead of scanning a whole division file.
"""

from __future__ import annotations

import json
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROOT = PROJECT_ROOT / "data" / "id_mapping" / "final_whitelist"
GROUPS = ["bacteria", "fungi", "metazoa", "plants"]


def external_csv(group: str) -> Path:
    return ROOT / group / f"{group}_external_id_mapping_final_whitelist.csv"


def parse_species(line: bytes) -> str:
    # CSV starts with: division,species_id,...
    first = line.find(b",")
    if first < 0:
        return ""
    second = line.find(b",", first + 1)
    if second < 0:
        return ""
    return line[first + 1 : second].decode("utf-8", errors="replace")


def build_offsets_for_group(group: str) -> dict:
    path = external_csv(group)
    started = time.time()
    species: dict[str, dict] = {}
    with path.open("rb") as fh:
        header = fh.readline().decode("utf-8-sig", errors="replace").rstrip("\r\n")
        current_id = ""
        current_start = fh.tell()
        current_rows = 0
        line_start = fh.tell()
        while True:
            line = fh.readline()
            if not line:
                if current_id:
                    species[current_id]["end_byte"] = line_start
                    species[current_id]["row_count"] = current_rows
                break
            sid = parse_species(line)
            if not sid:
                line_start = fh.tell()
                continue
            if not current_id:
                current_id = sid
                current_start = line_start
                current_rows = 0
                species[current_id] = {"division": group, "path": str(path), "start_byte": current_start}
            elif sid != current_id:
                species[current_id]["end_byte"] = line_start
                species[current_id]["row_count"] = current_rows
                current_id = sid
                current_start = line_start
                current_rows = 0
                species[current_id] = {"division": group, "path": str(path), "start_byte": current_start}
            current_rows += 1
            line_start = fh.tell()
    return {
        "division": group,
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "header": header.split(","),
        "species_count": len(species),
        "row_count": sum(item["row_count"] for item in species.values()),
        "elapsed_seconds": round(time.time() - started, 3),
        "species": species,
    }


def main() -> int:
    ROOT.mkdir(parents=True, exist_ok=True)
    started = time.time()
    groups = {}
    species_index = {}
    for group in GROUPS:
        print(f"Indexing {group}...", flush=True)
        item = build_offsets_for_group(group)
        groups[group] = {key: value for key, value in item.items() if key != "species"}
        for sid, offset in item["species"].items():
            species_index[sid] = offset
        print(f"  {group}: {item['species_count']} species, {item['row_count']} rows", flush=True)
    payload = {
        "schema_version": "final_whitelist_offset_index.v1",
        "created_at_unix": int(time.time()),
        "runtime_seconds": round(time.time() - started, 3),
        "groups": groups,
        "species": species_index,
    }
    out = ROOT / "final_whitelist_external_offsets.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
