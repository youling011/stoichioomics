from __future__ import annotations

"""Species-scoped, batched mapping used by the HVG comparison context.

This is an adapter around the platform's existing mapping tables/runtime.  It
does not expose a second ID-mapping product and it never resolves one gene at
a time through the public ``resolve_id`` API.
"""

from dataclasses import dataclass
from typing import Any, Iterable
import re

from django.db.models import Q

from backend.apps.stoichdb.models import EntityRecord, GeneIndex, ProteinIndex, Species, TranscriptIndex


OMICS = ("genome", "transcriptome", "proteome")
VERSION_SUFFIX = re.compile(r"\.\d+$")


@dataclass(frozen=True)
class GeneMappingResult:
    expression_gene_id: str
    canonical_gene_id: str
    mapping_method: str
    mapping_status: str
    candidate_count: int
    confidence: str
    reason: str
    source_entity_id: str = ""


@dataclass(frozen=True)
class _Candidate:
    canonical_gene_id: str
    source_entity_id: str = ""


def _clean(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in {"nan", "none", "null", "<na>"} else text


def _key(value: Any) -> str:
    return _clean(value).casefold()


def _coding_biotype(value: Any) -> bool | None:
    text = _key(value).replace("-", "_").replace(" ", "_")
    if not text:
        return None
    if any(token in text for token in ("noncoding", "non_coding", "pseudogene", "lncrna", "linc_rna")):
        return False
    if any(token in text for token in ("protein_coding", "protein_coding_gene", "coding", "mrna", "cds")):
        return True
    return None


def _chunks(values: Iterable[str], size: int = 5000) -> Iterable[list[str]]:
    batch: list[str] = []
    for value in values:
        text = _clean(value)
        if text and text.casefold() not in {item.casefold() for item in batch}:
            batch.append(text)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


class SpeciesMappingIndex:
    """A small in-memory index populated by a few species-scoped queries."""

    _METHOD_ORDER = (
        "exact_gene_id",
        "gene_alias_unique",
        "transcript_chain_unique",
        "protein_chain_unique",
        "entity_record_unique",
        "existing_mapping_runtime_unique",
        "version_stripped_unique",
    )

    def __init__(
        self,
        species_id: str,
        candidate_ids: Iterable[str] | None = None,
        *,
        load_database: bool = True,
    ) -> None:
        self.species_id = _clean(species_id)
        candidate_values = list(candidate_ids or [])
        self._expression_keys = {_key(value) for value in candidate_values if _clean(value)}
        self._maps: dict[str, dict[str, dict[str, set[_Candidate]]]] = {
            omics: {method: {} for method in self._METHOD_ORDER if method != "version_stripped_unique"}
            for omics in OMICS
        }
        self._source_exact: dict[str, dict[str, set[_Candidate]]] = {omics: {} for omics in OMICS}
        self._species_pk: int | None = None
        if load_database:
            self._load_database(candidate_values)
            self._load_existing_runtime(candidate_values)

    def _add(self, omics: str, alias: Any, canonical: Any, method: str, source_entity_id: Any = "") -> None:
        omics = _clean(omics).lower()
        alias_key = _key(alias)
        canonical_id = _clean(canonical)
        if omics not in self._maps or not alias_key or not canonical_id:
            return
        bucket = self._maps[omics].setdefault(method, {})
        bucket.setdefault(alias_key, set()).add(_Candidate(canonical_id, _clean(source_entity_id)))

    def has_expression_id(self, value: Any) -> bool:
        return _key(value) in self._expression_keys

    def add_source_identity(self, omics: str, row: dict[str, Any], canonical_gene_id: str) -> None:
        """Register verified source identities for the current species only."""
        canonical = _clean(canonical_gene_id)
        if not canonical:
            return
        omics = _clean(omics).lower()
        if omics == "proteome":
            for field in ("ensembl_gene_id", "canonical_gene_id"):
                source_value = _clean(row.get(field))
                if source_value:
                    self._source_exact.setdefault(omics, {}).setdefault(_key(source_value), set()).add(
                        _Candidate(source_value, row.get("protein_id") or source_value)
                    )
        for field in ("gene_id", "canonical_gene_id", "ensembl_gene_id"):
            value = _clean(row.get(field))
            if value:
                method = "exact_gene_id" if field != "gene_id" or _key(value) == _key(canonical) else "gene_alias_unique"
                self._add(omics, value, canonical, method, row.get("entity_id") or value)
        transcript = _clean(row.get("transcript_id"))
        if transcript:
            self._add(omics, transcript, canonical, "transcript_chain_unique", row.get("entity_id") or transcript)
        protein = _clean(row.get("protein_id"))
        if protein:
            self._add(omics, protein, canonical, "protein_chain_unique", row.get("entity_id") or protein)
        entity = _clean(row.get("entity_id"))
        if entity:
            self._add(omics, entity, canonical, "entity_record_unique", entity)
        for field in ("gene_name", "gene_symbol", "locus_tag"):
            value = _clean(row.get(field))
            if value:
                self._add(omics, value, canonical, "gene_alias_unique", row.get("entity_id") or value)

    def _load_database(self, candidate_ids: Iterable[str]) -> None:
        if not self.species_id:
            return
        values = [_clean(value) for value in candidate_ids if _clean(value)]
        if not values:
            return
        try:
            species = Species.objects.only("id").get(species_id=self.species_id)
            self._species_pk = int(species.pk)
        except Exception:
            return

        for batch in _chunks(values):
            gene_rows = GeneIndex.objects.filter(
                species_id=self._species_pk,
            ).filter(
                Q(gene_id__in=batch) | Q(gene_name__in=batch) | Q(locus_tag__in=batch)
            ).values("gene_id", "gene_name", "locus_tag")
            for row in gene_rows:
                canonical = _clean(row.get("gene_id"))
                self._add("genome", row.get("gene_id"), canonical, "exact_gene_id", canonical)
                for field in ("gene_name", "locus_tag"):
                    self._add("genome", row.get(field), canonical, "gene_alias_unique", canonical)
                    # The canonical gene ID can be used by the other two Core blocks.
                    self._add("transcriptome", row.get(field), canonical, "gene_alias_unique", canonical)
                    self._add("proteome", row.get(field), canonical, "gene_alias_unique", canonical)
                for omics in OMICS:
                    self._add(omics, row.get("gene_id"), canonical, "exact_gene_id", canonical)

            transcript_rows = TranscriptIndex.objects.filter(
                species_id=self._species_pk,
            ).filter(
                Q(transcript_id__in=batch) | Q(gene_id__in=batch) | Q(gene_symbol__in=batch)
            ).values("transcript_id", "gene_id", "gene_symbol")
            for row in transcript_rows:
                canonical = _clean(row.get("gene_id"))
                if not canonical:
                    continue
                self._add("transcriptome", row.get("transcript_id"), canonical, "transcript_chain_unique", row.get("transcript_id"))
                self._add("transcriptome", row.get("gene_id"), canonical, "exact_gene_id", row.get("transcript_id"))
                self._add("transcriptome", row.get("gene_symbol"), canonical, "gene_alias_unique", row.get("transcript_id"))

            protein_rows = ProteinIndex.objects.filter(
                species_id=self._species_pk,
            ).filter(
                Q(protein_id__in=batch)
                | Q(ensembl_gene_id__in=batch)
                | Q(gene_id__in=batch)
                | Q(gene_symbol__in=batch)
            ).values("protein_id", "ensembl_gene_id", "gene_id", "gene_symbol")
            for row in protein_rows:
                canonical = _clean(row.get("gene_id") or row.get("ensembl_gene_id"))
                if not canonical:
                    continue
                self._add("proteome", row.get("protein_id"), canonical, "protein_chain_unique", row.get("protein_id"))
                self._add("proteome", row.get("ensembl_gene_id"), canonical, "exact_gene_id", row.get("protein_id"))
                self._add("proteome", row.get("gene_id"), canonical, "exact_gene_id", row.get("protein_id"))
                self._add("proteome", row.get("gene_symbol"), canonical, "gene_alias_unique", row.get("protein_id"))

            for omics in OMICS:
                entity_rows = EntityRecord.objects.filter(
                    species_id=self._species_pk,
                    omics_type=omics,
                ).filter(
                    Q(entity_id__in=batch)
                    | Q(canonical_gene_id__in=batch)
                    | Q(secondary_id__in=batch)
                    | Q(gene_name__in=batch)
                ).values("entity_id", "canonical_gene_id", "secondary_id", "gene_name")
                for row in entity_rows:
                    canonical = _clean(row.get("canonical_gene_id"))
                    if not canonical:
                        continue
                    for field in ("entity_id", "secondary_id"):
                        self._add(omics, row.get(field), canonical, "entity_record_unique", row.get("entity_id"))
                    self._add(omics, row.get("gene_name"), canonical, "gene_alias_unique", row.get("entity_id"))

    def _load_existing_runtime(self, candidate_ids: Iterable[str]) -> None:
        """Reuse the existing species-scoped runtime index in one query batch."""
        values = [_clean(value) for value in candidate_ids if _clean(value)]
        if not values or not self.species_id:
            return
        try:
            from backend.apps.stoichdb import id_mapping as runtime

            with runtime._conn() as conn:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(id_alias_index)").fetchall()}
                if "normalized_alias" not in columns:
                    return
                for batch in _chunks(values):
                    placeholders = ",".join("?" for _ in batch)
                    rows = conn.execute(
                        f"SELECT * FROM id_alias_index WHERE species_id=? AND normalized_alias IN ({placeholders})",
                        [self.species_id, *[_key(item) for item in batch]],
                    ).fetchall()
                    for row in rows:
                        data = dict(row)
                        canonical = _clean(data.get("gene_id"))
                        target_type = _clean(data.get("target_type")).lower()
                        target_id = _clean(data.get("target_id"))
                        if not canonical and target_type == "gene":
                            canonical = target_id
                        if not canonical:
                            continue
                        alias = data.get("alias_value") or data.get("normalized_alias")
                        alias_type = _clean(data.get("alias_type")).lower()
                        targets = OMICS
                        if alias_type in {"transcript_id", "refseq_transcript", "transcript"} or target_type == "transcript":
                            targets = ("transcriptome",)
                        elif alias_type in {"protein_id", "refseq_protein", "uniprot", "ncbi_protein", "protein"} or target_type == "protein":
                            targets = ("proteome",)
                        for omics in targets:
                            self._add(omics, alias, canonical, "existing_mapping_runtime_unique", data.get("target_id"))

            # The final whitelist uses a species byte-range.  One sequential
            # scan is cheaper and safer than calling resolve_id for each gene.
            final_iter = getattr(runtime, "_final_iter_species_rows", None)
            final_aliases = getattr(runtime, "_final_row_aliases", None)
            if final_iter and final_aliases:
                wanted = {_key(value) for value in values}
                for row in final_iter(self.species_id) or []:
                    canonical = _clean(row.get("gene_id"))
                    if not canonical:
                        continue
                    for alias, alias_type, _target_type in final_aliases(row):
                        if _key(alias) not in wanted:
                            continue
                        targets = ("genome", "transcriptome", "proteome")
                        if "transcript" in alias_type:
                            targets = ("transcriptome",)
                        elif "protein" in alias_type or alias_type in {"uniprot", "ncbi_protein"}:
                            targets = ("proteome",)
                        for omics in targets:
                            self._add(omics, alias, canonical, "existing_mapping_runtime_unique", row.get("gene_id"))
        except Exception:
            # Runtime indexes are optional for local/demo environments.  The
            # ORM indexes and verified source identities remain authoritative.
            return

    def _candidates(self, omics: str, value: str, method: str) -> set[_Candidate]:
        return set(self._maps.get(omics, {}).get(method, {}).get(_key(value), set()))

    def _resolve_at_key(self, omics: str, value: str, method: str) -> set[_Candidate]:
        if method == "version_stripped_unique":
            stripped = VERSION_SUFFIX.sub("", _clean(value))
            if stripped == _clean(value):
                return set()
            candidates: set[_Candidate] = set()
            for prior in self._METHOD_ORDER[:-1]:
                candidates.update(self._candidates(omics, stripped, prior))
            return candidates
        return self._candidates(omics, value, method)

    def resolve(self, expression_gene_id: Any, omics: str) -> GeneMappingResult:
        expression = _clean(expression_gene_id)
        omics = _clean(omics).lower()
        if not expression:
            return GeneMappingResult(expression, "", "unmapped", "unmapped", 0, "none", "empty_expression_gene_id")
        source_candidates = self._source_exact.get(omics, {}).get(_key(expression), set())
        source_canonical_ids = sorted({item.canonical_gene_id for item in source_candidates if item.canonical_gene_id})
        if source_canonical_ids:
            if len(source_canonical_ids) > 1:
                return GeneMappingResult(
                    expression, "", "ambiguous", "ambiguous", len(source_canonical_ids), "none",
                    "multiple_source_verified_candidates",
                )
            candidate = next(item for item in source_candidates if item.canonical_gene_id == source_canonical_ids[0])
            return GeneMappingResult(
                expression, source_canonical_ids[0], "exact_gene_id", "mapped", len(source_candidates),
                "high", "", candidate.source_entity_id,
            )
        for method in self._METHOD_ORDER:
            candidates = self._resolve_at_key(omics, expression, method)
            canonical_ids = sorted({item.canonical_gene_id for item in candidates if item.canonical_gene_id})
            if not canonical_ids:
                continue
            if len(canonical_ids) > 1:
                return GeneMappingResult(
                    expression, "", "ambiguous", "ambiguous", len(canonical_ids), "none",
                    "multiple_species_scoped_candidates",
                )
            candidate = next(item for item in candidates if item.canonical_gene_id == canonical_ids[0])
            confidence = "high" if method == "exact_gene_id" else "medium" if method in {
                "gene_alias_unique", "transcript_chain_unique", "protein_chain_unique", "entity_record_unique",
                "existing_mapping_runtime_unique",
            } else "low"
            reason = "version_suffix_removed" if method == "version_stripped_unique" else ""
            return GeneMappingResult(expression, canonical_ids[0], method, "mapped", len(candidates), confidence, reason, candidate.source_entity_id)
        return GeneMappingResult(expression, "", "unmapped", "unmapped", 0, "none", "no_species_scoped_candidate")

    def resolve_many(self, expression_gene_ids: Iterable[str], omics: str) -> dict[str, GeneMappingResult]:
        return {str(value): self.resolve(value, omics) for value in expression_gene_ids}

    def coding_by_expression(self, results: dict[str, GeneMappingResult]) -> dict[str, bool | None]:
        """Read GeneIndex biotypes for mapped genes in one species-scoped query."""
        if self._species_pk is None:
            return {}
        canonical_ids = sorted({
            result.canonical_gene_id
            for result in results.values()
            if result.mapping_status == "mapped" and result.canonical_gene_id
        })
        if not canonical_ids:
            return {}
        try:
            rows = GeneIndex.objects.filter(
                species_id=self._species_pk,
                gene_id__in=canonical_ids,
            ).values("gene_id", "biotype")
            by_canonical = {
                _clean(row.get("gene_id")): _coding_biotype(row.get("biotype"))
                for row in rows
            }
            return {
                expression_id: by_canonical.get(result.canonical_gene_id)
                for expression_id, result in results.items()
                if result.canonical_gene_id in by_canonical
            }
        except Exception:
            return {}


def source_identity_fields(omics: str, row: dict[str, Any]) -> list[str]:
    omics = _clean(omics).lower()
    if omics == "genome":
        return ["gene_id", "canonical_gene_id", "entity_id"]
    if omics == "transcriptome":
        return ["gene_id", "canonical_gene_id", "transcript_id", "entity_id"]
    # Protein Core files may use a gene symbol in ``gene_id`` while the
    # expression universe uses the stable gene/protein namespace.  Prefer the
    # explicit Ensembl gene identity when present; fall back to the source
    # gene symbol and protein chain only when it is absent.
    return ["ensembl_gene_id", "canonical_gene_id", "gene_id", "protein_id", "entity_id"]


def resolve_source_identity(index: SpeciesMappingIndex, omics: str, row: dict[str, Any]) -> GeneMappingResult:
    """Resolve source rows according to the fixed source-identity priority."""
    expression = ""
    fields = source_identity_fields(omics, row)
    if _clean(omics).lower() == "proteome":
        stable_values = [_clean(row.get(field)) for field in ("ensembl_gene_id", "canonical_gene_id")]
        if not any(index.has_expression_id(value) for value in stable_values if value):
            fields = ["gene_id", "ensembl_gene_id", "canonical_gene_id", "protein_id", "entity_id"]
    for field in fields:
        value = _clean(row.get(field))
        if not value:
            continue
        expression = value
        if field in {"gene_id", "canonical_gene_id", "ensembl_gene_id"}:
            index.add_source_identity(omics, row, value)
        result = index.resolve(value, omics)
        if result.mapping_status == "mapped":
            return result
    return GeneMappingResult(expression, "", "unmapped", "unmapped", 0, "none", "source_identity_unresolved")
