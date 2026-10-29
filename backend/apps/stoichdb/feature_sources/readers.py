"""Streaming, explicitly configured logical Core views over Full CSV files."""
from __future__ import annotations

import csv
import io
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence

from .projection import CoreRecipe, ProjectionError


class _IteratorRawIO(io.RawIOBase):
    """Adapt byte chunks to a bounded readable stream and close the producer."""

    def __init__(self, chunks: Iterator[bytes]):
        super().__init__()
        self._chunks = iter(chunks)
        self._pending = b''
        self.completed = False
        self.full_digest = None
        self._position = 0
        self.byte_digest = hashlib.sha256()

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int:
        self._checkClosed()
        if self.completed:
            return 0
        view = memoryview(buffer).cast('B')
        written = 0
        while written < len(view):
            if not self._pending:
                try:
                    chunk = next(self._chunks)
                    if not isinstance(chunk, bytes):
                        raise TypeError('CSV byte iterator returned a non-bytes chunk')
                    self.byte_digest.update(chunk)
                    self._pending = memoryview(chunk)
                except StopIteration as exc:
                    self.full_digest = exc.value if isinstance(exc.value,str) and len(exc.value)==64 else None
                    self.completed = True
                    break
                if not self._pending:
                    continue
            take = min(len(view) - written, len(self._pending))
            view[written:written + take] = self._pending[:take]
            self._pending = self._pending[take:]
            written += take
        self._position += written
        return written

    def tell(self):
        self._checkClosed()
        return self._position

    def close(self) -> None:
        if not self.closed:
            close = getattr(self._chunks, 'close', None)
            if close:
                close()
            self._pending = b''
        super().close()


@dataclass(frozen=True)
class CoreCSVSource:
    full_path: Path
    recipe: CoreRecipe
    expected_sha256: str = ""
    row_limit: int | None = None

    def header(self) -> tuple[str, ...]:
        with Path(self.full_path).open('r', encoding='utf-8-sig', newline='') as handle:
            full_header = next(csv.reader(handle), [])
        self.recipe.validate_full_header(full_header)
        return self.recipe.columns

    def iter_records(self, fields: Sequence[str] | None = None) -> Iterator[dict[str, object]]:
        selected = self.recipe.columns if fields is None else tuple(fields)
        self.recipe.required_columns(selected)
        raw = _HashingFull(Path(self.full_path).open('rb'))
        with io.TextIOWrapper(io.BufferedReader(raw), encoding='utf-8-sig', newline='') as handle:
            reader = csv.DictReader(handle)
            self.recipe.validate_full_header(reader.fieldnames or [], selected)
            emitted = 0
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise ProjectionError('malformed Full CSV row')
                if self.row_limit is None or emitted < self.row_limit:
                    yield self.recipe.project(row, selected)
                    emitted += 1
            if self.row_limit is not None and emitted != self.row_limit:
                raise ProjectionError("Full cannot supply the verified Core row range")
            if self.expected_sha256 and raw.digest.hexdigest() != self.expected_sha256:
                raise ProjectionError("Full checksum changed during consumption")

    def iter_csv_bytes(self, *, line_terminator: str = '\n', bom: bool = False,
                       quoting: int = csv.QUOTE_MINIMAL) -> Iterator[bytes]:
        """Serialize on demand; a caller must verify bytes against its legacy contract."""
        if line_terminator not in {'\n', '\r\n'}:
            raise ProjectionError('unsupported line terminator')
        if quoting not in {csv.QUOTE_MINIMAL, csv.QUOTE_ALL}:
            raise ProjectionError('unsupported CSV quoting')
        try:
            from .arrow import iter_core_bytes
        except ImportError:
            iter_core_bytes = None
        if iter_core_bytes is not None:
            return (yield from iter_core_bytes(self.full_path, self.recipe, line_terminator=line_terminator, bom=bom, quoting=quoting, expected_sha256=self.expected_sha256, row_limit=self.row_limit))
        columns = self.header()
        if bom:
            yield b'\xef\xbb\xbf'
        buf = io.StringIO(newline='')
        writer = csv.writer(buf, lineterminator=line_terminator, quoting=quoting)
        writer.writerow(columns)
        yield buf.getvalue().encode('utf-8')
        for row in self.iter_records():
            buf.seek(0)
            buf.truncate(0)
            writer.writerow([row[column] for column in columns])
            yield buf.getvalue().encode('utf-8')

    def open_binary(self, *, line_terminator: str = '\n', bom: bool = False,
                    quoting: int = csv.QUOTE_MINIMAL) -> io.BufferedReader:
        """Open a non-seekable Core CSV stream without materializing a Core file."""
        chunks = self.iter_csv_bytes(line_terminator=line_terminator, bom=bom, quoting=quoting)
        return io.BufferedReader(_IteratorRawIO(chunks))


class _HashingFull(io.RawIOBase):
    def __init__(self,handle):super().__init__();self.handle=handle;self.digest=hashlib.sha256()
    def readable(self):return True
    def readinto(self,buffer):
        n=self.handle.readinto(buffer)
        if n:self.digest.update(memoryview(buffer)[:n])
        return n
    def close(self):
        if not self.closed:self.handle.close()
        super().close()
