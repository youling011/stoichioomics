from __future__ import annotations
from backend.apps.stoichdb.feature_sources import io as feature_io

import csv
import gzip
import hashlib
import io
from pathlib import Path

from ..feature_hub.sources import DatasetSourceResolver
from .contracts import CompareError, digest


def signature(path: Path) -> dict:
    stat = feature_io.source_metadata(path)
    return {'path': str(path.resolve()), 'size': stat.size, 'mtime_ns': stat.mtime_ns,
            'file_id': stat.ino}


def resolve(species_id: str, omics: str):
    from ..models import OmicsDataset
    try:
        source = DatasetSourceResolver().resolve(species_id, omics, 'core')
    except Exception as exc:
        raise CompareError(f'No readable Core source for {species_id}/{omics}: {exc}', 'source_unavailable', 404) from exc
    # Scope is fixed: no full fallback and no legacy fingerprint substitution.
    primary = {'genome': 'gene_id', 'transcriptome': 'transcript_id', 'proteome': 'protein_id'}[omics]
    opener = gzip.open if source.path.suffix.lower() == '.gz' else feature_io.open_source
    with opener(source.path, 'rt', encoding='utf-8-sig', newline='') as handle:
        header = next(csv.reader(handle), [])
    if primary not in header:
        raise CompareError(f'Core source lacks primary ID {primary}.', 'invalid_core_header', 409)
    if len(header) != len(set(header)):
        raise CompareError('Duplicate column names in Core source.', 'duplicate_columns', 409)
    ds = OmicsDataset.objects.get(dataset_id=source.dataset_id)
    return source, ds, header, signature(source.path)


class HashReader(io.RawIOBase):
    def __init__(self, handle):
        self.handle = handle
        self.hasher = hashlib.sha256()

    def readable(self):
        return True

    def readinto(self, buffer):
        size = self.handle.readinto(buffer)
        if size:
            self.hasher.update(memoryview(buffer)[:size])
        return size

    def close(self):
        if not self.closed:
            self.handle.close()
        super().close()


def hashed_text(path):
    reader = HashReader(feature_io.open_source(Path(path), 'rb'))
    buffer = io.BufferedReader(reader)
    data = gzip.GzipFile(fileobj=buffer) if str(path).lower().endswith('.gz') else buffer
    return io.TextIOWrapper(data, encoding='utf-8-sig', newline=''), reader
