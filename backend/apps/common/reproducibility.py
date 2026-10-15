from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def git_commit(base_dir: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(base_dir),
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip()
    except Exception:
        return "unavailable"


def software_versions() -> dict[str, str]:
    versions = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
    }
    try:
        import django

        versions["django"] = django.get_version()
    except Exception:
        versions["django"] = "unavailable"
    try:
        import pandas

        versions["pandas"] = pandas.__version__
    except Exception:
        versions["pandas"] = "unavailable"
    return versions


def write_reproducibility_manifest(
    path: Path,
    *,
    job_id: str,
    pipeline_type: str,
    parameters: dict[str, Any] | None = None,
    inputs: list[dict[str, Any]] | None = None,
    config_path: Path | None = None,
    base_dir: Path | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = base_dir or Path.cwd()
    config_payload = None
    if config_path and config_path.exists():
        text = config_path.read_text(encoding="utf-8")
        config_payload = {
            "path": str(config_path),
            "sha256": sha256_text(text),
        }
    manifest = {
        "job_id": job_id,
        "pipeline_type": pipeline_type,
        "generated_at": utc_now_iso(),
        "git_commit": git_commit(base),
        "software_versions": software_versions(),
        "parameters": parameters or {},
        "inputs": inputs or [],
        "config": config_payload,
        "environment": {
            "DJANGO_DB_ENGINE": os.environ.get("DJANGO_DB_ENGINE", ""),
            "STOICHDB_STORAGE_MODE": os.environ.get("STOICHDB_STORAGE_MODE", ""),
        },
    }
    if extra:
        manifest.update(extra)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
