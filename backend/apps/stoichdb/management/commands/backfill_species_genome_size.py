from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from backend.apps.stoichdb.models import OmicsDataset, Species


SEQ_COLUMNS = ("seqid", "seq_region", "chromosome", "contig", "scaffold")
END_COLUMNS = ("end_1", "end", "stop", "gene_end", "cds_end")


def _positive_float(value: Any) -> float | None:
    try:
        number = float(value)
    except Exception:
        return None
    if number > 0:
        return number
    return None


def _compute_genome_size_from_csv(path_text: str) -> dict[str, Any]:
    path = Path(str(path_text or ""))
    if not path.exists():
        return {"ok": False, "reason": "missing_file", "path": str(path)}

    max_end_by_seq: dict[str, float] = {}
    row_count = 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            return {"ok": False, "reason": "empty_file", "path": str(path)}

        normalized = {str(name).strip().lower(): idx for idx, name in enumerate(header)}
        seq_idx = next((normalized[name] for name in SEQ_COLUMNS if name in normalized), None)
        end_idx = next((normalized[name] for name in END_COLUMNS if name in normalized), None)
        if seq_idx is None or end_idx is None:
            return {
                "ok": False,
                "reason": "missing_seq_or_end_column",
                "path": str(path),
                "columns": header[:80],
            }

        for row in reader:
            row_count += 1
            if len(row) <= max(seq_idx, end_idx):
                continue
            seq = str(row[seq_idx] or "").strip()
            end_value = _positive_float(row[end_idx])
            if not seq or end_value is None:
                continue
            if end_value > max_end_by_seq.get(seq, 0.0):
                max_end_by_seq[seq] = end_value

    genome_size_mb = sum(max_end_by_seq.values()) / 1_000_000.0
    if genome_size_mb <= 0:
        return {
            "ok": False,
            "reason": "no_positive_coordinates",
            "path": str(path),
            "rows_scanned": row_count,
            "seq_count": len(max_end_by_seq),
        }
    return {
        "ok": True,
        "path": str(path),
        "genome_size_mb": round(genome_size_mb, 6),
        "rows_scanned": row_count,
        "seq_count": len(max_end_by_seq),
        "source_method": "sum_max_end_1_per_seqid_from_genome_feature_csv",
    }


class Command(BaseCommand):
    help = "Backfill Species.genome_size_mb from genome feature CSV coordinate spans."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write computed positive values to Species.genome_size_mb.")
        parser.add_argument("--force", action="store_true", help="Recompute and overwrite positive existing genome_size_mb values.")
        parser.add_argument("--limit", type=int, default=0, help="Limit number of genome datasets scanned.")
        parser.add_argument("--batch-size", type=int, default=500)
        parser.add_argument("--prefer-full", action="store_true", help="Use full_csv_path before core_csv_path when available.")
        parser.add_argument("--audit-out", default="", help="Optional JSON audit output path.")

    def handle(self, *args, **options):
        apply_changes = bool(options["apply"])
        force = bool(options["force"])
        limit = int(options["limit"] or 0)
        batch_size = max(1, int(options["batch_size"] or 500))
        prefer_full = bool(options["prefer_full"])
        audit_out = str(options.get("audit_out") or "").strip()

        qs = (
            OmicsDataset.objects
            .filter(omics_type="genome")
            .select_related("species")
            .only("id", "dataset_id", "omics_type", "core_csv_path", "full_csv_path", "row_count_core", "row_count_full", "species__id", "species__species_id", "species__domain", "species__genome_size_mb")
            .order_by("species__species_id")
        )
        if not force:
            qs = qs.filter(Q(species__genome_size_mb__isnull=True) | Q(species__genome_size_mb__lte=0))
        if limit > 0:
            qs = qs[:limit]

        total = qs.count() if not limit else len(list(qs))
        if limit > 0:
            qs = (
                OmicsDataset.objects
                .filter(omics_type="genome")
                .select_related("species")
                .only("id", "dataset_id", "omics_type", "core_csv_path", "full_csv_path", "row_count_core", "row_count_full", "species__id", "species__species_id", "species__domain", "species__genome_size_mb")
                .order_by("species__species_id")
            )
            if not force:
                qs = qs.filter(Q(species__genome_size_mb__isnull=True) | Q(species__genome_size_mb__lte=0))
            qs = qs[:limit]

        updates: list[Species] = []
        audit_rows: list[dict[str, Any]] = []
        reason_counts: Counter[str] = Counter()
        domain_counts: dict[str, Counter[str]] = defaultdict(Counter)
        scanned = 0
        computed = 0
        written = 0

        self.stdout.write(
            f"Backfill genome_size_mb from genome feature CSVs: candidates={total}, apply={apply_changes}, force={force}, prefer_full={prefer_full}"
        )

        for dataset in qs.iterator(chunk_size=64):
            scanned += 1
            species = dataset.species
            path = ""
            if prefer_full and dataset.full_csv_path:
                path = dataset.full_csv_path
            if not path:
                path = dataset.core_csv_path or dataset.full_csv_path
            result = _compute_genome_size_from_csv(path)
            domain = species.domain or "Unknown"
            if not result.get("ok"):
                reason = str(result.get("reason") or "unknown")
                reason_counts[reason] += 1
                domain_counts[domain][reason] += 1
                if len(audit_rows) < 2000:
                    audit_rows.append({
                        "species_id": species.species_id,
                        "domain": domain,
                        "dataset_id": dataset.dataset_id,
                        "status": "skipped",
                        **result,
                    })
            else:
                computed += 1
                value = float(result["genome_size_mb"])
                previous_value = species.genome_size_mb
                reason_counts["computed"] += 1
                domain_counts[domain]["computed"] += 1
                if apply_changes:
                    species.genome_size_mb = value
                    updates.append(species)
                    if len(updates) >= batch_size:
                        with transaction.atomic():
                            Species.objects.bulk_update(updates, ["genome_size_mb"], batch_size=batch_size)
                        written += len(updates)
                        updates.clear()
                if len(audit_rows) < 2000:
                    audit_rows.append({
                        "species_id": species.species_id,
                        "domain": domain,
                        "dataset_id": dataset.dataset_id,
                        "status": "computed",
                        "previous_genome_size_mb": previous_value,
                        **result,
                    })

            if scanned == 1 or scanned == total or scanned % 500 == 0:
                self.stdout.write(f"  scanned={scanned}/{total}, computed={computed}, written={written}")

        if apply_changes and updates:
            with transaction.atomic():
                Species.objects.bulk_update(updates, ["genome_size_mb"], batch_size=batch_size)
            written += len(updates)

        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "apply": apply_changes,
            "force": force,
            "prefer_full": prefer_full,
            "candidate_count": total,
            "scanned": scanned,
            "computed": computed,
            "written": written,
            "reason_counts": dict(reason_counts),
            "domain_counts": {domain: dict(counts) for domain, counts in sorted(domain_counts.items())},
            "sample_rows": audit_rows,
        }
        if audit_out:
            out_path = Path(audit_out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            self.stdout.write(f"Audit written: {out_path}")

        style = self.style.SUCCESS if (not apply_changes or written == computed) else self.style.WARNING
        self.stdout.write(style(
            f"Genome-size backfill finished: scanned={scanned}, computed={computed}, written={written}, reasons={dict(reason_counts)}"
        ))
