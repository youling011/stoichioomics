from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable
import json
import math

import numpy as np
import pandas as pd

try:
    from scipy.stats import hypergeom, mannwhitneyu
except Exception:  # pragma: no cover - scipy is part of the HVG environment.
    hypergeom = None
    mannwhitneyu = None


ID_COLUMNS = [
    "gene_id",
    "gene_name",
    "transcript_id",
    "protein_id",
    "source_protein_id",
    "uniprot_accession",
    "kegg_gene_id",
]

QUERY_CLASSES = [
    "all_hvg",
    "stoich_excess_hvg",
    "stoich_explained_hvg",
    "stoich_constrained_stable",
    "canonical_hvg",
    "top_candidate",
]


def _norm(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return ""
    text = text.split("|")[0].strip()
    if "." in text and not text.upper().startswith(("GO:", "KO:", "PATH:")):
        text = text.split(".", 1)[0]
    return text.lower()


def _safe_num(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except Exception:
        return default
    return out if math.isfinite(out) else default


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _empty_outputs(out: Path, reason_code: str, reason_message: str, classified: pd.DataFrame, species_id: str = "") -> Dict[str, str]:
    out.mkdir(parents=True, exist_ok=True)
    row = {
        "status": "skipped",
        "reason_code": reason_code,
        "reason_message": reason_message,
        "species_id": species_id,
        "input_gene_count": int(classified.shape[0]) if classified is not None else 0,
    }
    ora_path = out / "enrichment_ora.csv"
    rank_path = out / "gsea_prerank_results.csv"
    top_path = out / "functional_enrichment_top_terms.csv"
    dotplot_path = out / "functional_enrichment_dotplot.json"
    summary_path = out / "functional_enrichment_summary.json"
    pd.DataFrame([row]).to_csv(ora_path, index=False)
    pd.DataFrame([{**row, "method": "prerank_gsea_gseapy"}]).to_csv(rank_path, index=False)
    pd.DataFrame([row]).to_csv(top_path, index=False)
    _write_json(dotplot_path, {"status": "skipped", "reason_code": reason_code, "rows": []})
    _write_json(summary_path, {"status": "skipped", "reason_code": reason_code, "reason_message": reason_message, "species_id": species_id})
    return {
        "enrichment_ora": str(ora_path.resolve()),
        "gsea_prerank_results": str(rank_path.resolve()),
        "functional_enrichment_top_terms": str(top_path.resolve()),
        "functional_enrichment_dotplot": str(dotplot_path.resolve()),
        "functional_enrichment_summary": str(summary_path.resolve()),
    }


def _load_annotation_universe(species_id: str) -> tuple[dict[str, set[str]], dict[str, dict[str, str]], dict[str, set[str]], dict[str, Any]]:
    from backend.apps.stoichdb import function_annotations

    term_to_genes: dict[str, set[str]] = defaultdict(set)
    term_meta: dict[str, dict[str, str]] = {}
    identifier_to_gene: dict[str, set[str]] = defaultdict(set)

    for row in function_annotations._go_rows_for_species(species_id):
        gene = _norm(row.get("gene_id") or row.get("protein_id") or row.get("uniprot_accession"))
        term = str(row.get("go_id") or "").strip()
        if not gene or not term:
            continue
        key = f"GO|{term}"
        term_to_genes[key].add(gene)
        term_meta.setdefault(key, {
            "source": "GO",
            "term_id": term,
            "term_name": str(row.get("go_name") or ""),
            "namespace_or_type": str(row.get("go_namespace") or "unknown"),
        })
        for identifier in function_annotations._entity_identifiers(row):
            identifier_to_gene[identifier].add(gene)

    for row in function_annotations._kegg_link_rows_for_species(species_id):
        gene = _norm(row.get("gene_id") or row.get("protein_id") or row.get("uniprot_accession"))
        term = str(row.get("annotation_id") or "").strip()
        if not gene or not term:
            continue
        source = f"KEGG_{str(row.get('annotation_type') or 'annotation').upper()}"
        key = f"{source}|{term}"
        term_to_genes[key].add(gene)
        term_meta.setdefault(key, {
            "source": source,
            "term_id": term,
            "term_name": str(row.get("annotation_name") or ""),
            "namespace_or_type": str(row.get("annotation_type") or "kegg"),
        })
        for identifier in function_annotations._entity_identifiers(row):
            identifier_to_gene[identifier].add(gene)

    # Compact KEGG rows are used when the long-form KEGG link table is absent.
    if not any(meta["source"].startswith("KEGG") for meta in term_meta.values()):
        for row in function_annotations._kegg_gene_rows_for_species(species_id):
            gene = _norm(row.get("gene_id") or row.get("protein_id") or row.get("uniprot_accession"))
            if not gene:
                continue
            for field, label in [("ko_ids", "KEGG_KO"), ("pathway_ids", "KEGG_PATHWAY"), ("module_ids", "KEGG_MODULE")]:
                ids = [item.strip() for item in str(row.get(field) or "").replace("|", ";").split(";") if item.strip()]
                for term in ids:
                    key = f"{label}|{term}"
                    term_to_genes[key].add(gene)
                    term_meta.setdefault(key, {
                        "source": label,
                        "term_id": term,
                        "term_name": "",
                        "namespace_or_type": label.replace("KEGG_", "").lower(),
                    })
            for identifier in function_annotations._entity_identifiers(row):
                identifier_to_gene[identifier].add(gene)

    try:
        status = function_annotations.species_functional_summary(species_id)
    except Exception:
        status = {"available": bool(term_to_genes)}
    return dict(term_to_genes), term_meta, dict(identifier_to_gene), status


def _row_identifiers(row: pd.Series) -> set[str]:
    values: set[str] = set()
    for col in ID_COLUMNS:
        if col in row.index:
            normalized = _norm(row.get(col))
            if normalized:
                values.add(normalized)
    return values


def _matched_gene_by_row(classified: pd.DataFrame, identifier_to_gene: dict[str, set[str]], universe: set[str]) -> pd.Series:
    matched = []
    for _, row in classified.iterrows():
        genes: set[str] = set()
        for identifier in _row_identifiers(row):
            genes.update(identifier_to_gene.get(identifier) or set())
            if identifier in universe:
                genes.add(identifier)
        matched.append(sorted(genes)[0] if genes else "")
    return pd.Series(matched, index=classified.index)


def _candidate_score(classified: pd.DataFrame) -> pd.Series:
    score = pd.to_numeric(classified.get("stoich_excess_var"), errors="coerce")
    if score.notna().any():
        score = score.fillna(0.0)
    else:
        score = pd.to_numeric(classified.get("hvg_score"), errors="coerce").fillna(0.0)
    rank = pd.to_numeric(classified.get("hvg_rank"), errors="coerce")
    if rank.notna().any():
        rank_component = 1.0 - ((rank - 1.0) / max(float(rank.max()), 1.0))
        score = score + rank_component.fillna(0.0)
    return score.fillna(0.0)


def _query_masks(classified: pd.DataFrame, top_n: int) -> dict[str, pd.Series]:
    index = classified.index
    is_hvg = classified.get("is_hvg", pd.Series(False, index=index)).fillna(False).astype(bool)
    stoich_class = classified.get("stoich_class", pd.Series("", index=index)).astype(str)
    masks = {
        "all_hvg": is_hvg,
        "stoich_excess_hvg": stoich_class.eq("stoich_excess_hvg"),
        "stoich_explained_hvg": stoich_class.eq("stoich_explained_hvg"),
        "stoich_constrained_stable": stoich_class.eq("stoich_constrained_stable"),
        "canonical_hvg": stoich_class.eq("canonical_hvg"),
    }
    score = _candidate_score(classified)
    top_indices = score.sort_values(ascending=False).head(min(max(top_n, 1), len(score))).index
    masks["top_candidate"] = pd.Series(index.isin(top_indices), index=index)
    return masks


def _bh_adjust(rows: list[dict[str, Any]], p_col: str = "p_value", fdr_col: str = "fdr_bh") -> None:
    valid = [row for row in rows if row.get(p_col) is not None and math.isfinite(_safe_num(row.get(p_col), default=float("nan")))]
    ordered = sorted(valid, key=lambda item: _safe_num(item[p_col], 1.0))
    n = len(ordered)
    best = 1.0
    for rank_from_end, item in enumerate(reversed(ordered), start=1):
        rank = n - rank_from_end + 1
        adjusted = min(best, _safe_num(item[p_col], 1.0) * n / rank)
        item[fdr_col] = adjusted
        best = adjusted


def _hypergeom_p(k: int, population: int, term_size: int, draws: int) -> float:
    if k <= 0 or population <= 0 or term_size <= 0 or draws <= 0:
        return 1.0
    if hypergeom is not None:
        return float(hypergeom.sf(k - 1, population, term_size, draws))
    denom = math.comb(population, draws)
    total = 0
    for i in range(k, min(term_size, draws) + 1):
        total += math.comb(term_size, i) * math.comb(population - term_size, draws - i)
    return min(1.0, total / denom) if denom else 1.0


def _ora_rows(
    classified: pd.DataFrame,
    term_to_genes: dict[str, set[str]],
    term_meta: dict[str, dict[str, str]],
    matched_gene: pd.Series,
    species_id: str,
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    background = {gene for gene in matched_gene.astype(str) if gene}
    masks = _query_masks(classified, top_n=int(config.get("functional_enrichment_top_n", 300)))
    min_overlap = max(1, int(config.get("functional_enrichment_min_overlap", 2)))
    min_term_size = max(1, int(config.get("functional_enrichment_min_term_size", 3)))
    max_term_size = max(min_term_size, int(config.get("functional_enrichment_max_term_size", 500)))
    rows: list[dict[str, Any]] = []
    population = len(background)
    if population == 0:
        return rows
    for query_label in QUERY_CLASSES:
        mask = masks.get(query_label)
        if mask is None:
            continue
        query = {gene for gene in matched_gene.loc[mask].astype(str) if gene}
        draws = len(query)
        if draws == 0:
            continue
        for term_key, raw_genes in term_to_genes.items():
            genes = set(raw_genes) & background
            term_size = len(genes)
            if term_size < min_term_size or term_size > max_term_size:
                continue
            overlap = sorted(query & genes)
            k = len(overlap)
            if k < min_overlap:
                continue
            p_value = _hypergeom_p(k, population, term_size, draws)
            meta = term_meta.get(term_key, {})
            rows.append({
                "query_label": query_label,
                "source": meta.get("source") or "unknown",
                "term_id": meta.get("term_id") or term_key,
                "term_name": meta.get("term_name") or "",
                "namespace_or_type": meta.get("namespace_or_type") or "",
                "candidate_hits": k,
                "background_hits": term_size,
                "candidate_n": draws,
                "background_n": population,
                "p_value": p_value,
                "fdr_bh": None,
                "fold_enrichment": (k / draws) / (term_size / population) if draws and term_size and population else 0.0,
                "overlap_genes": ";".join(overlap[:200]),
                "species_id": species_id,
                "status": "generated",
                "method": "one_sided_hypergeometric_ora",
            })
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[f"{row['query_label']}|{row['source']}"].append(row)
    for group_rows in grouped.values():
        _bh_adjust(group_rows)
    return sorted(rows, key=lambda row: (_safe_num(row.get("fdr_bh"), 1.0), _safe_num(row.get("p_value"), 1.0), -int(row.get("candidate_hits") or 0)))


def _rank_rows(
    classified: pd.DataFrame,
    term_to_genes: dict[str, set[str]],
    term_meta: dict[str, dict[str, str]],
    matched_gene: pd.Series,
    species_id: str,
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    background = {gene for gene in matched_gene.astype(str) if gene}
    if len(background) < 5:
        return []
    score = _candidate_score(classified)
    gene_scores = (
        pd.DataFrame({"matched_gene": matched_gene, "rank_score": score})
        .loc[lambda df: df["matched_gene"].astype(str).ne("")]
        .groupby("matched_gene", as_index=False)["rank_score"].max()
    )
    score_map = dict(zip(gene_scores["matched_gene"].astype(str), pd.to_numeric(gene_scores["rank_score"], errors="coerce").fillna(0.0)))
    all_scores = np.array([score_map[g] for g in background if g in score_map], dtype=float)
    if all_scores.size < 5:
        return []
    min_term_size = max(3, int(config.get("functional_rank_min_term_size", config.get("functional_enrichment_min_term_size", 3))))
    max_term_size = max(min_term_size, int(config.get("functional_enrichment_max_term_size", 500)))
    filtered_gene_sets = {
        term_key: sorted((set(raw_genes) & background) & set(score_map))
        for term_key, raw_genes in term_to_genes.items()
    }
    filtered_gene_sets = {
        term_key: genes
        for term_key, genes in filtered_gene_sets.items()
        if min_term_size <= len(genes) <= max_term_size
    }
    try:
        import gseapy as gp

        rnk = gene_scores.rename(columns={"matched_gene": "gene", "rank_score": "score"}).sort_values("score", ascending=False)
        permutation_num = int(config.get("functional_gsea_permutations", 100))
        if not filtered_gene_sets or rnk.shape[0] < min_term_size:
            return []
        res = gp.prerank(
            rnk=rnk[["gene", "score"]],
            gene_sets=filtered_gene_sets,
            outdir=None,
            min_size=min_term_size,
            max_size=max_term_size,
            permutation_num=max(10, permutation_num),
            seed=int(config.get("random_state", 42)),
            threads=int(config.get("functional_gsea_threads", 1)),
            verbose=False,
        )
        gsea_df = getattr(res, "res2d", pd.DataFrame())
        rows: list[dict[str, Any]] = []
        if gsea_df is not None and not gsea_df.empty:
            for _, row in gsea_df.iterrows():
                term_key = str(row.get("Term") or "")
                meta = term_meta.get(term_key, {})
                genes = filtered_gene_sets.get(term_key, [])
                rows.append({
                    "source": meta.get("source") or "unknown",
                    "term_id": meta.get("term_id") or term_key,
                    "term_name": meta.get("term_name") or "",
                    "namespace_or_type": meta.get("namespace_or_type") or "",
                    "term_gene_count": len(genes),
                    "ranked_gene_count": int(rnk.shape[0]),
                    "es": _safe_num(row.get("ES"), 0.0),
                    "nes": _safe_num(row.get("NES"), 0.0),
                    "p_value": _safe_num(row.get("NOM p-val"), 1.0),
                    "fdr_bh": _safe_num(row.get("FDR q-val"), 1.0),
                    "fwer_p_value": _safe_num(row.get("FWER p-val"), 1.0),
                    "tag_fraction": row.get("Tag %"),
                    "gene_fraction": row.get("Gene %"),
                    "lead_genes": row.get("Lead_genes"),
                    "species_id": species_id,
                    "status": "generated",
                    "method": "prerank_gsea_gseapy",
                    "permutation_num": max(10, permutation_num),
                })
        if rows:
            return sorted(rows, key=lambda item: (_safe_num(item.get("fdr_bh"), 1.0), -abs(_safe_num(item.get("nes"), 0.0))))
    except Exception:
        pass

    rows: list[dict[str, Any]] = []
    for term_key, genes_list in filtered_gene_sets.items():
        genes = set(genes_list)
        term_size = len(genes)
        in_scores = np.array([score_map[g] for g in genes if g in score_map], dtype=float)
        out_scores = np.array([score_map[g] for g in background - genes if g in score_map], dtype=float)
        if in_scores.size < min_term_size or out_scores.size < 3:
            continue
        if mannwhitneyu is not None:
            test = mannwhitneyu(in_scores, out_scores, alternative="greater")
            p_value = float(test.pvalue)
        else:
            p_value = 1.0
        meta = term_meta.get(term_key, {})
        rows.append({
            "source": meta.get("source") or "unknown",
            "term_id": meta.get("term_id") or term_key,
            "term_name": meta.get("term_name") or "",
            "namespace_or_type": meta.get("namespace_or_type") or "",
            "term_gene_count": term_size,
            "ranked_gene_count": int(all_scores.size),
            "mean_rank_score_in_term": float(np.mean(in_scores)),
            "mean_rank_score_background": float(np.mean(out_scores)),
            "median_rank_score_in_term": float(np.median(in_scores)),
            "median_rank_score_background": float(np.median(out_scores)),
            "rank_effect": float(np.median(in_scores) - np.median(out_scores)),
            "p_value": p_value,
            "fdr_bh": None,
            "species_id": species_id,
            "status": "generated",
            "method": "mann_whitney_rank_enrichment",
        })
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["source"])].append(row)
    for group_rows in grouped.values():
        _bh_adjust(group_rows)
    return sorted(rows, key=lambda row: (_safe_num(row.get("fdr_bh"), 1.0), _safe_num(row.get("p_value"), 1.0), -_safe_num(row.get("rank_effect"), 0.0)))


def _dotplot_payload(rows: list[dict[str, Any]], top_n: int = 30) -> dict[str, Any]:
    selected = rows[:top_n]
    payload_rows = []
    for row in selected:
        fdr = _safe_num(row.get("fdr_bh"), 1.0)
        payload_rows.append({
            "query_label": row.get("query_label"),
            "source": row.get("source"),
            "term_id": row.get("term_id"),
            "term_name": row.get("term_name") or row.get("term_id"),
            "namespace_or_type": row.get("namespace_or_type"),
            "candidate_hits": row.get("candidate_hits"),
            "background_hits": row.get("background_hits"),
            "fold_enrichment": row.get("fold_enrichment"),
            "fdr_bh": row.get("fdr_bh"),
            "minus_log10_fdr": -math.log10(max(fdr, 1e-300)),
        })
    return {"status": "generated" if payload_rows else "skipped", "rows": payload_rows}


def run_enrichment_outputs(classified: pd.DataFrame, output_dir: str | Path, config: dict[str, Any] | None = None) -> Dict[str, str]:
    config = config or {}
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    if config.get("enable_functional_enrichment") is False:
        return _empty_outputs(out, "functional_enrichment_disabled", "GO/KEGG functional enrichment is disabled in phase2_stoich config.", classified, str(config.get("species_id") or ""))
    species_id = str(config.get("species_id") or "").strip()
    if not species_id or species_id == "unknown":
        return _empty_outputs(out, "missing_species_id", "GO/KEGG enrichment requires a species_id in phase2_stoich config.", classified, species_id)

    term_to_genes, term_meta, identifier_to_gene, annotation_status = _load_annotation_universe(species_id)
    if not term_to_genes:
        return _empty_outputs(out, "no_standard_annotation", "No standard GO/KEGG annotation universe is available for this species.", classified, species_id)

    universe = set().union(*term_to_genes.values())
    matched_gene = _matched_gene_by_row(classified, identifier_to_gene, universe)
    matched_count = int(matched_gene.astype(str).ne("").sum())
    if matched_count == 0:
        return _empty_outputs(out, "no_gene_id_annotation_overlap", "No expression/HVG gene identifiers matched the standard GO/KEGG annotation universe.", classified, species_id)

    ora_rows = _ora_rows(classified, term_to_genes, term_meta, matched_gene, species_id, config)
    rank_rows = _rank_rows(classified, term_to_genes, term_meta, matched_gene, species_id, config)
    if not ora_rows:
        ora_rows = [{
            "status": "skipped",
            "reason_code": "no_enriched_terms_after_filters",
            "reason_message": "No GO/KEGG terms passed overlap and term-size filters for the matched HVG candidate sets.",
            "species_id": species_id,
            "input_gene_count": int(classified.shape[0]),
            "matched_annotated_gene_count": matched_count,
        }]
    if not rank_rows:
        rank_rows = [{
            "status": "skipped",
            "reason_code": "no_gsea_terms_after_filters",
            "reason_message": "No GO/KEGG terms passed filters for candidate-score prerank GSEA.",
            "species_id": species_id,
            "ranked_gene_count": matched_count,
            "method": "prerank_gsea_gseapy",
        }]

    ora_df = pd.DataFrame(ora_rows)
    rank_df = pd.DataFrame(rank_rows)
    generated_ora = ora_df.loc[ora_df.get("status", pd.Series(dtype=str)).astype(str).eq("generated")].copy()
    top_df = generated_ora.head(int(config.get("functional_enrichment_report_terms", 200))) if not generated_ora.empty else ora_df.copy()

    ora_path = out / "enrichment_ora.csv"
    rank_path = out / "gsea_prerank_results.csv"
    top_path = out / "functional_enrichment_top_terms.csv"
    dotplot_path = out / "functional_enrichment_dotplot.json"
    summary_path = out / "functional_enrichment_summary.json"
    ora_df.to_csv(ora_path, index=False)
    rank_df.to_csv(rank_path, index=False)
    top_df.to_csv(top_path, index=False)
    _write_json(dotplot_path, _dotplot_payload(top_df.to_dict(orient="records"), top_n=int(config.get("functional_enrichment_plot_terms", 30))))

    significant = generated_ora.loc[pd.to_numeric(generated_ora.get("fdr_bh"), errors="coerce").le(float(config.get("functional_enrichment_fdr", 0.05)))] if not generated_ora.empty else pd.DataFrame()
    summary = {
        "status": "generated",
        "species_id": species_id,
        "input_gene_count": int(classified.shape[0]),
        "matched_annotated_gene_count": matched_count,
        "matched_annotation_fraction": float(matched_count / max(int(classified.shape[0]), 1)),
        "term_count": int(len(term_to_genes)),
        "go_term_count": int(sum(1 for meta in term_meta.values() if meta.get("source") == "GO")),
        "kegg_term_count": int(sum(1 for meta in term_meta.values() if str(meta.get("source")).startswith("KEGG"))),
        "ora_result_count": int(generated_ora.shape[0]),
        "significant_ora_count": int(significant.shape[0]),
        "rank_result_count": int(rank_df.loc[rank_df.get("status", pd.Series(dtype=str)).astype(str).eq("generated")].shape[0]) if "status" in rank_df else 0,
        "fdr_threshold": float(config.get("functional_enrichment_fdr", 0.05)),
        "annotation_status": annotation_status,
        "method_metadata": {
            "annotation_source": "project PostgreSQL stoichdb GOAnnotation and KEGGAnnotationLink/KEGGGeneAnnotation standard records",
            "query_sets": QUERY_CLASSES,
            "ora_test": "one-sided hypergeometric over-representation against matched same-species annotated background",
            "rank_test": "local prerank GSEA with gseapy over candidate-score ranks; falls back to one-sided Mann-Whitney U only if the GSEA engine is unavailable",
            "multiple_testing": "Benjamini-Hochberg FDR within query_label/source for ORA and within source for rank enrichment",
            "prediction_policy": "No GO or KEGG function is predicted for unannotated genes or unsupported species.",
        },
    }
    _write_json(summary_path, summary)
    return {
        "enrichment_ora": str(ora_path.resolve()),
        "gsea_prerank_results": str(rank_path.resolve()),
        "functional_enrichment_top_terms": str(top_path.resolve()),
        "functional_enrichment_dotplot": str(dotplot_path.resolve()),
        "functional_enrichment_summary": str(summary_path.resolve()),
    }
