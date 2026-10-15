from __future__ import annotations

import hashlib
import mimetypes
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from django.utils.text import get_valid_filename


DEFAULT_ALLOWED_EXTENSIONS = {
    ".csv", ".tsv", ".txt", ".json", ".yaml", ".yml",
    ".h5ad", ".mtx", ".gz", ".zip",
    ".fa", ".fasta", ".faa", ".fna", ".fas",
    ".gff", ".gff3", ".gtf",
}

SEQUENCE_FASTA_EXTENSIONS = {".fa", ".fasta", ".faa", ".fna", ".fas", ".txt"}
SEQUENCE_ANNOTATION_EXTENSIONS = {".gff", ".gff3", ".gtf", ".txt"}
SEQUENCE_SAMPLE_SHEET_EXTENSIONS = {".csv", ".tsv", ".txt"}


@dataclass(frozen=True)
class StoredUpload:
    original_name: str
    safe_name: str
    relative_path: str
    absolute_path: str
    size_bytes: int
    sha256: str
    content_type: str
    extension: str


def max_upload_bytes() -> int:
    return int(getattr(settings, "USER_UPLOAD_MAX_BYTES", 100 * 1024 * 1024))


def allowed_extensions() -> set[str]:
    configured = getattr(settings, "USER_UPLOAD_ALLOWED_EXTENSIONS", None)
    if not configured:
        return set(DEFAULT_ALLOWED_EXTENSIONS)
    return {str(item).lower() for item in configured}


def sanitize_upload_name(name: str | None) -> str:
    base = Path(name or "").name
    safe = get_valid_filename(base)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", safe).strip("._")
    return safe or f"upload_{uuid.uuid4().hex}"


def validate_upload_name(name: str, *, allowed: Iterable[str] | None = None) -> str:
    safe = sanitize_upload_name(name)
    suffix = Path(safe).suffix.lower()
    allowed_set = {item.lower() for item in (allowed or allowed_extensions())}
    if suffix not in allowed_set:
        raise ValueError(f"Unsupported file extension '{suffix or '<none>'}'. Allowed extensions: {', '.join(sorted(allowed_set))}.")
    return safe


def ensure_child_path(root: Path, candidate: Path) -> Path:
    root_resolved = root.resolve()
    candidate_resolved = candidate.resolve()
    if root_resolved != candidate_resolved and root_resolved not in candidate_resolved.parents:
        raise ValueError("Resolved upload path escapes the job workspace.")
    return candidate_resolved


def _unique_target(target_dir: Path, safe_name: str) -> Path:
    target = target_dir / safe_name
    counter = 1
    while target.exists():
        stem = target.stem
        suffix = target.suffix
        target = target_dir / f"{stem}_{counter}{suffix}"
        counter += 1
    return target


def store_uploaded_file(
    upload: UploadedFile,
    target_dir: Path,
    workspace_root: Path,
    *,
    allowed: Iterable[str] | None = None,
) -> StoredUpload:
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_name = validate_upload_name(getattr(upload, "name", ""), allowed=allowed)
    target = _unique_target(target_dir, safe_name)
    target = ensure_child_path(workspace_root, target)
    limit = max_upload_bytes()
    digest = hashlib.sha256()
    size = 0
    with target.open("wb") as handle:
        for chunk in upload.chunks():
            size += len(chunk)
            if size > limit:
                handle.close()
                target.unlink(missing_ok=True)
                raise ValueError(f"Uploaded file '{safe_name}' exceeds the configured {limit} byte limit.")
            digest.update(chunk)
            handle.write(chunk)
    content_type = getattr(upload, "content_type", "") or mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
    return StoredUpload(
        original_name=getattr(upload, "name", safe_name),
        safe_name=target.name,
        relative_path=str(target.relative_to(workspace_root)),
        absolute_path=str(target),
        size_bytes=size,
        sha256=digest.hexdigest(),
        content_type=content_type,
        extension=Path(target.name).suffix.lower(),
    )
