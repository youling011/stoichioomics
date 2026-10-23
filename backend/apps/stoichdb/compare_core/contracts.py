from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

from django.conf import settings

VERSION = 'compare_core_v1'
ANALYSIS_VERSION = 'compare_core_analysis_v1_1'
OMICS = ('genome', 'transcriptome', 'proteome')
ACTIVE = ('queued', 'profiling', 'analyzing', 'exporting', 'cancel_requested')
TERMINAL = ('completed', 'partial', 'failed', 'cancelled', 'interrupted')
TABLES = ('dataset_qc', 'weighted_densities', 'coverage', 'profiles', 'categories', 'rankings', 'differences', 'distances',
          'contributions', 'pca_loadings', 'clusters', 'group_comparison', 'cross_omics',
          'candidates', 'excluded_fields', 'composition_profiles', 'pca_coordinates')


class CompareError(ValueError):
    def __init__(self, message: str, code: str = 'invalid_request', status: int = 400):
        super().__init__(message)
        self.code, self.status = code, status


class Cancelled(Exception):
    pass


def clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if hasattr(value, 'tolist'):
        return clean(value.tolist())
    if hasattr(value, 'item'):
        return clean(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Path):
        return str(value)
    return value


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(clean(value), sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def root() -> Path:
    return Path(getattr(settings, 'COMPARE_CORE_ROOT', Path(settings.BASE_DIR) / 'runtime' / 'compare_core'))


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f'.{os.getpid()}.tmp')
    tmp.write_text(json.dumps(clean(value), ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    os.replace(tmp, path)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def unique_ids(values: Any) -> list[str]:
    if not isinstance(values, list) or any(not isinstance(x, str) or not x.strip() for x in values):
        raise CompareError('Species IDs must be a list of nonempty strings.')
    return list(dict.fromkeys(x.strip() for x in values))
