from __future__ import annotations
import hashlib
import json
from django.core.management.base import BaseCommand, CommandError
from django.utils.timezone import now
from backend.apps.common.host_paths import Path
from backend.apps.stoichdb.models import OmicsDataset, Species
from backend.apps.stoichdb.home_atlas_viz import artifacts
from backend.apps.stoichdb.home_atlas_viz.aggregates import build_payload, clear_visuals_cache, registered_fields
from backend.apps.stoichdb.home_atlas_viz.contracts import OMICS, digest, group_name
from backend.apps.stoichdb.home_atlas_viz.core_diagnostics import ALGORITHM, scan_core
from backend.apps.stoichdb.home_atlas_viz.scope import snapshot


class Command(BaseCommand):
    help = "Precompute versioned whole-Core home/atlas diagnostics without altering source data or legacy artifacts."

    def add_arguments(self, parser):
        parser.add_argument("--global", dest="global_snapshot", action="store_true")
        parser.add_argument("--cohort-file")
        parser.add_argument("--species-id", action="append", default=[])
        parser.add_argument("--out-root")
        parser.add_argument("--verify", action="store_true")
        parser.add_argument("--strict", action="store_true")
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--chunksize", type=int, default=50000)
        parser.add_argument("--promote-from", help="Verify and atomically promote an already-scanned isolated artifact set.")

    def handle(self, *args, **opts):
        root = artifacts.artifact_root(opts["out_root"])
        state = artifacts.manifest(root)
        if opts["promote_from"]:
            from django.core.management import call_command
            import shutil
            source_root = artifacts.artifact_root(opts["promote_from"])
            if source_root.resolve() == root.resolve():
                raise CommandError("Promotion source and destination must differ.")
            call_command("precompute_home_atlas_visuals", out_root=str(source_root), verify=True, strict=True, stdout=self.stdout)
            incoming = artifacts.manifest(source_root)
            for entry in incoming["entries"].values():
                source = source_root / "diagnostics/objects" / entry["object_file"]
                target = root / "diagnostics/objects" / entry["object_file"]
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    temp = target.with_suffix(".tmp")
                    shutil.copyfile(source, temp)
                    temp.replace(target)
            if (source_root / "global_snapshot.json").is_file():
                artifacts.atomic_json(root / "global_snapshot.json", json.loads((source_root / "global_snapshot.json").read_text("utf8")))
            artifacts.atomic_json(root / "manifest.json", incoming)
            clear_visuals_cache()
            self.stdout.write(self.style.SUCCESS(f"Promoted {len(incoming['entries'])} verified immutable artifacts; no repeated raw scan."))
            return
        if opts["verify"]:
            if state["version"] == "not_built":
                raise CommandError("No complete manifest has been published.")
            fields, warnings = registered_fields(snapshot({})["schemas"])
            errors = []
            for key, entry in state["entries"].items():
                sid, omics = key.rsplit("__", 1)
                dataset = OmicsDataset.objects.filter(species__species_id=sid, omics_type=omics).values(
                    "core_csv_path", "schema_version", "row_count_core", "status").first()
                status, reason = artifacts.source_state(entry, dataset, digest([r for r in fields if r["omics"] == omics]))
                if status != "ready":
                    errors.append(f"{key}: {reason}")
                    continue
                obj = artifacts.diagnostic(entry, root)
                if (obj["constant_count"] + obj["variable_count"] + obj["empty_count"] != obj["n_numeric"]
                        or any(r["n_valid"] + r["n_missing"] != obj["n_rows"] for r in obj["profiles"])):
                    errors.append(f"{key}: field conservation failed")
            if errors:
                raise CommandError("; ".join(errors))
            self.stdout.write(self.style.SUCCESS(f"Verified {len(state['entries'])} immutable whole-Core table artifacts; no source rescan claimed."))
            return
        if opts["chunksize"] < 1:
            raise CommandError("chunksize must be positive")
        cohort = (json.loads(Path(opts["cohort_file"]).read_text(encoding="utf-8-sig"))
                  if opts["cohort_file"] else state["cohort"])
        members = cohort.get("species")
        if not isinstance(members, list) or not cohort.get("version"):
            raise CommandError("Cohort file requires version and species object array.")
        if len({r["sid"] for r in members}) != len(members) or len({r["species_id"] for r in members}) != len(members):
            raise CommandError("Cohort sid/species_id must each be unique.")
        registry = {r.species_id: r for r in Species.objects.filter(species_id__in=[r["species_id"] for r in members])}
        for member in members:
            row = registry.get(member["species_id"])
            if row is None or group_name(row.domain) != member["group"]:
                raise CommandError(f"Invalid cohort member or group: {member['species_id']}")
        targets = list(dict.fromkeys(([r["species_id"] for r in members] if opts["cohort_file"] or not opts["species_id"] else []) + opts["species_id"]))
        fields, warnings = registered_fields(snapshot({})["schemas"])
        if warnings:
            raise CommandError("; ".join(warnings))
        entries = dict(state["entries"])
        errors = []
        for sid in targets:
            for omics in OMICS:
                key = f"{sid}__{omics}"
                selected_fields = [r for r in fields if r["omics"] == omics]
                dataset = OmicsDataset.objects.filter(species__species_id=sid, omics_type=omics).values(
                    "core_csv_path", "schema_version", "row_count_core", "status").first()
                if not opts["force"] and artifacts.source_state(entries.get(key), dataset, digest(selected_fields))[0] == "ready":
                    self.stdout.write(f"UNCHANGED {key}")
                    continue
                try:
                    obj = scan_core(sid, omics, selected_fields, opts["chunksize"])
                    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
                    identity = hashlib.sha256(raw).hexdigest()
                    artifacts.atomic_json(root / "diagnostics/objects" / (identity + ".json"), obj)
                    entries[key] = {k: obj[k] for k in ("source_path", "source_sha256", "source_bytes", "source_mtime_ns",
                                                       "schema_digest", "schema_version", "n_rows")}
                    entries[key].update(object_file=identity + ".json", object_sha256=identity,
                                        registered_core_path=dataset["core_csv_path"])
                    self.stdout.write(f"SCANNED {key} rows={obj['n_rows']} numeric={obj['n_numeric']}")
                    self.stdout.flush()
                except Exception as exc:
                    errors.append(f"{key}: {exc}")
                    if opts["strict"]:
                        raise CommandError(errors[-1]) from exc
        if errors:
            raise CommandError("No new manifest published: " + "; ".join(errors))
        published = {"version": digest([ALGORITHM, cohort, entries]), "algorithm_version": ALGORITHM,
                     "generated_at": now().isoformat(), "cohort": cohort, "entries": entries}
        if opts["global_snapshot"]:
            artifacts.atomic_json(root / "global_snapshot.json", {
                "home": build_payload("home", root=root, use_cache=False, diagnostic_state=published),
                "atlas": build_payload("atlas", root=root, use_cache=False, diagnostic_state=published)})
        artifacts.atomic_json(root / "manifest.json", published)
        clear_visuals_cache()
        self.stdout.write(self.style.SUCCESS(f"Published {len(entries)} whole-Core artifacts at {root}"))
