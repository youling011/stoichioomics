from __future__ import annotations

import tempfile
import json
import re
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import numpy as np
import pandas as pd

from backend.analysis_engine.phase2.comparison_selector import resolve_comparison_features
from backend.analysis_engine.phase2.comparison_qc import run_comparison_qc
from backend.analysis_engine.phase2.comparison_stats import (
    _apply_fdr,
    _binary_test,
    _categorical_test,
    cliffs_delta_fast,
)
from backend.analysis_engine.phase2.comparison_adjustment import compute_adjusted_comparison
from backend.analysis_engine.phase2.group_comparison import (
    ARTIFACTS,
    run_hvg_nonhvg_comparison,
    write_unavailable_comparison,
)
from backend.analysis_engine.phase2.runner_core import run_phase2_stoich_pipeline
from backend.apps.hvg.services import (
    get_downloadable_file,
    get_group_comparison_feature_detail,
    get_group_comparison_features,
    get_group_comparison_summary,
)
from backend.apps.hvg.views import hvg_group_comparison_features
from rest_framework.test import APIRequestFactory


def registry_payload():
    def row(omics, field, role="eligible", semantic="continuous", family="other", **extra):
        return {
            "omics": omics, "scope": "core", "field": field, "label": field,
            "ml_role": role, "semantic_type": semantic, "family": family,
            "schema_id": f"{omics}_core", "schema_version": "1", "applicability": "all",
            "zero_semantics": "true_zero", "composition_group": "", "redundancy_group": "",
            "description": f"Test definition for {field}", **extra,
        }
    return {
        "registry_version": "test_registry_v1",
        "fields": [
            row("transcriptome", "length_nt_total", family="length_count"),
            row("transcriptome", "gc_content", family="gc_composition"),
            row("transcriptome", "nt_entropy", family="sequence_complexity"),
            row("transcriptome", "transcript_id", role="exclude", semantic="identifier", family="metadata"),
            row("transcriptome", "transcript_biotype", role="conditional", semantic="categorical_code", family="metadata"),
            row("proteome", "length_aa", family="length_count"),
            row("proteome", "C_atoms_per_aa", family="element_density"),
            row("proteome", "aa_entropy_bits", family="sequence_complexity"),
            row("proteome", "protein_id", role="exclude", semantic="identifier", family="metadata"),
            row("genome", "gc_content", family="gc_composition"),
        ],
    }


def comparison_frame():
    rng = np.random.default_rng(4)
    n = 100
    hvg = np.zeros(n, dtype=bool)
    hvg[:40] = True
    shift = hvg.astype(float)
    return pd.DataFrame({
        "gene_id": [f"gene_{idx}" for idx in range(n)],
        "is_hvg": hvg,
        "mean_expr": rng.lognormal(1.0, 0.4, n),
        "pct_cells_detected": rng.uniform(0.2, 1.0, n),
        "length_nt": rng.normal(1000 + 80 * shift, 120, n),
        "gc_content": rng.normal(0.45 + 0.05 * shift, 0.03, n),
        "transcript_entropy": rng.normal(1.8 + 0.04 * shift, 0.05, n),
        "protein_length": rng.normal(300 + 25 * shift, 45, n),
        "c_atoms_per_aa": rng.normal(4.8 + 0.15 * shift, 0.18, n),
        "aa_entropy": rng.normal(3.7 + 0.08 * shift, 0.12, n),
    })


class GroupComparisonTests(TestCase):
    def test_selector_resolves_transcript_and_protein_but_not_genome(self):
        selected, audit, blocks, version = resolve_comparison_features(
            comparison_frame(),
            {"comparison_omics": ["transcriptome", "proteome"]},
            registry_payload(),
        )
        self.assertEqual(blocks, ["transcriptome", "proteome"])
        self.assertEqual(version, "test_registry_v1")
        self.assertFalse(audit["omics_layer"].eq("genome").any())
        self.assertIn("transcriptome::gc_content", {row["feature_key"] for row in selected})
        self.assertIn("proteome::C_atoms_per_aa", {row["feature_key"] for row in selected})
        excluded = audit.loc[audit["feature_name"].isin(["transcript_id", "protein_id"]), "status"]
        self.assertTrue(excluded.eq("excluded").all())
        self.assertTrue({
            "comparison_schema_version", "description", "source_block", "provenance_resolution"
        }.issubset(audit.columns))

    def test_selector_supports_single_blocks_and_missing_block(self):
        transcript, _, transcript_blocks, _ = resolve_comparison_features(
            comparison_frame(), {"comparison_omics": ["transcriptome"], "comparison_auto_detect_blocks": False}, registry_payload()
        )
        protein, _, protein_blocks, _ = resolve_comparison_features(
            comparison_frame(), {"comparison_omics": ["proteome"], "comparison_auto_detect_blocks": False}, registry_payload()
        )
        _, _, missing_blocks, _ = resolve_comparison_features(
            comparison_frame()[["gene_id", "is_hvg"]],
            {"comparison_omics": ["transcriptome", "proteome"]},
            registry_payload(),
        )
        self.assertEqual(transcript_blocks, ["transcriptome"])
        self.assertEqual(protein_blocks, ["proteome"])
        self.assertTrue(all(row["omics_layer"] == "transcriptome" for row in transcript))
        self.assertTrue(all(row["omics_layer"] == "proteome" for row in protein))
        self.assertEqual(missing_blocks, [])

    def test_selector_requires_namespace_for_cross_omics_name_collision(self):
        payload = registry_payload()
        payload["fields"].append({
            **payload["fields"][1], "omics": "proteome", "schema_id": "proteome_core"
        })
        frame = comparison_frame()[["gene_id", "is_hvg", "gc_content"]].copy()
        _, audit, blocks, _ = resolve_comparison_features(
            frame, {"comparison_omics": ["transcriptome", "proteome"]}, payload
        )
        self.assertEqual(blocks, [])
        self.assertTrue(audit.empty)
        selected, _, blocks, _ = resolve_comparison_features(
            frame,
            {
                "comparison_omics": ["transcriptome", "proteome"],
                "comparison_feature_provenance": {"transcriptome::gc_content": "gc_content"},
            },
            payload,
        )
        self.assertEqual(blocks, ["transcriptome"])
        self.assertEqual(selected[0]["provenance_resolution"], "explicit_provenance")

    def test_cliffs_delta_handles_ties_without_cartesian_arrays(self):
        x = np.array([1.0, 2.0, 2.0, 4.0])
        y = np.array([1.0, 2.0, 3.0])
        expected = sum(a > b for a in x for b in y) - sum(a < b for a in x for b in y)
        expected /= x.size * y.size
        self.assertAlmostEqual(cliffs_delta_fast(x, y), expected)

    def test_binary_and_categorical_statistics_preserve_effect_definitions(self):
        binary = _binary_test(np.array([1, 1, 1, 0, 0]), np.array([1, 0, 0, 0, 0]))
        self.assertEqual(binary["effect_type"], "odds_ratio")
        self.assertGreater(binary["odds_ratio"], 1)
        self.assertAlmostEqual(binary["proportion_diff"], 0.4)
        categorical = _categorical_test(
            pd.Series(["a"] * 9 + ["b"]),
            pd.Series(["a"] * 5 + ["b"] * 5),
            min_cell_count=5,
        )
        self.assertEqual(categorical["hypothesis_status"], "descriptive_only")
        self.assertTrue(np.isnan(categorical["p_value"]))
        self.assertEqual(json.loads(categorical["category_counts_hvg"])["b"], 1)

    def test_bh_scopes_are_global_omics_and_family_across_omics(self):
        frame = pd.DataFrame({
            "p_value": [0.01, 0.04, 0.02, np.nan],
            "omics_layer": ["transcriptome", "transcriptome", "proteome", "proteome"],
            "family": ["shared", "other", "shared", "other"],
        })
        adjusted = _apply_fdr(frame)
        self.assertAlmostEqual(adjusted.loc[0, "global_fdr"], 0.03)
        self.assertAlmostEqual(adjusted.loc[0, "omics_fdr"], 0.02)
        self.assertAlmostEqual(adjusted.loc[0, "family_fdr"], 0.02)

    def test_qc_reports_range_duplicate_correlation_and_applicability(self):
        n = 60
        frame = pd.DataFrame({
            "gene_id": [f"g{i}" for i in range(n)],
            "is_hvg": [True] * 30 + [False] * 30,
            "bounded": np.linspace(-0.1, 1.1, n),
            "duplicate": np.linspace(-0.1, 1.1, n),
            "near_copy": np.linspace(-0.1, 1.1, n) + np.linspace(0, 1e-8, n),
            "constant": 1.0,
            "not_applicable": np.linspace(0, 1, n),
        })
        fields = []
        for name, applicability in [
            ("bounded", "all"), ("duplicate", "all"), ("near_copy", "all"),
            ("constant", "all"), ("not_applicable", "organism_specific"),
        ]:
            fields.append({
                "omics": "transcriptome", "scope": "core", "field": name,
                "label": name, "ml_role": "eligible", "semantic_type": "continuous",
                "family": "test", "schema_id": "t", "schema_version": "1",
                "applicability": applicability, "zero_semantics": "true_zero",
                "composition_group": "", "redundancy_group": "",
                "bounded_min": 0 if name == "bounded" else None,
                "bounded_max": 1 if name == "bounded" else None,
            })
        selected, audit, _, _ = resolve_comparison_features(
            frame, {"comparison_omics": ["transcriptome"]}, {"registry_version": "q", "fields": fields}
        )
        _, audit, _ = run_comparison_qc(
            frame, selected, audit, min_group_n=10, high_correlation_threshold=0.99
        )
        rows = audit.set_index("feature_name")
        self.assertGreater(int(rows.loc["bounded", "out_of_range_n"]), 0)
        self.assertEqual(rows.loc["constant", "reason"], "constant")
        self.assertEqual(rows.loc["not_applicable", "reason"], "not_applicable")
        self.assertTrue(
            rows["reason"].fillna("").str.startswith("duplicate_of:").any()
            or rows["warnings"].fillna("").str.contains("high_correlation:").any()
        )

    def test_adjustment_is_gene_level_and_excludes_target_from_covariates(self):
        frame = comparison_frame()
        selected, audit, _, _ = resolve_comparison_features(
            frame, {"comparison_omics": ["transcriptome", "proteome"]}, registry_payload()
        )
        tested, _, prepared = run_comparison_qc(frame, selected, audit, min_group_n=20)
        adjusted = compute_adjusted_comparison(frame, tested, prepared, min_group_n=20)
        self.assertFalse(adjusted.empty)
        for row in adjusted.to_dict(orient="records"):
            self.assertEqual(row["n_total"], row["n_used"])
            self.assertNotIn(row["source_column"], json.loads(row["covariates_used"]))
            if row["feature_name"] in {"length_nt_total", "length_aa"}:
                self.assertNotIn("length", json.loads(row["covariates_used"]))

    def test_full_comparison_writes_versioned_artifacts(self):
        with tempfile.TemporaryDirectory() as temp:
            result = run_hvg_nonhvg_comparison(
                comparison_frame(),
                {
                    "comparison_omics": ["transcriptome", "proteome"],
                    "comparison_min_group_n": 20,
                    "comparison_bootstrap_ci_repeats": 30,
                    "comparison_bootstrap_max_group_n": 100,
                    "comparison_adjustment_enabled": True,
                    "random_state": 9,
                },
                output_dir=temp,
                registry_payload=registry_payload(),
            )
            self.assertIn(result["summary"]["comparison_status"], {"complete", "partial"})
            self.assertGreaterEqual(result["summary"]["counts"]["tested_fields"], 6)
            self.assertTrue(set(result["feature_comparison"]["effect_type"]) == {"cliffs_delta"})
            self.assertTrue(result["feature_comparison"]["global_fdr"].notna().all())
            self.assertTrue(result["adjusted_comparison"]["adjusted_status"].isin(["tested", "failed", "skipped"]).all())
            adjusted_numeric = result["adjusted_comparison"][[
                "adjusted_odds_ratio", "effect_ci_low", "effect_ci_high"
            ]].apply(pd.to_numeric, errors="coerce")
            self.assertFalse(np.isinf(adjusted_numeric.to_numpy()).any())
            for filename in ARTIFACTS.values():
                self.assertTrue((Path(temp) / filename).exists(), filename)
            manifest = json.loads((Path(temp) / ARTIFACTS["run_manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(set(manifest["artifact_checksums"]), set(ARTIFACTS))
            self.assertIsNone(manifest["artifact_checksums"]["run_manifest"])
            self.assertIn("runtime_seconds", manifest)
            self.assertIn("fdr_scopes", manifest["methods"])

    def test_unavailable_branch_still_writes_all_contract_artifacts(self):
        with tempfile.TemporaryDirectory() as temp:
            write_unavailable_comparison(temp, reason="mapping blocked", mapping_context={"ready_for_phase2_stoich": False})
            for filename in ARTIFACTS.values():
                self.assertTrue((Path(temp) / filename).exists(), filename)
            manifest = json.loads((Path(temp) / ARTIFACTS["run_manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["mapping"]["mapping_status"], "blocked")

    @patch("backend.analysis_engine.phase2.runner_core.build_visualization_artifacts", return_value={})
    @patch("backend.analysis_engine.phase2.runner_core._run_phase2_stoich_model_pipeline", side_effect=RuntimeError("model failed"))
    @patch("backend.analysis_engine.phase2.runner_core.run_hvg_nonhvg_comparison")
    def test_model_failure_does_not_erase_comparison_status(self, comparison_mock, _model_mock, _visual_mock):
        comparison_mock.return_value = {"summary": {"status": "complete", "comparison_status": "complete", "artifacts": ARTIFACTS}}
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            baseline = base / "baseline.csv"
            comparison_frame().to_csv(baseline, index=False)
            result = run_phase2_stoich_pipeline({
                "output_dir": str(base / "analysis_phase2"), "input_baseline_csv": str(baseline),
                "case_id": "branch-test", "enabled": True,
            })
            self.assertEqual(result["comparison_status"], "complete")
            self.assertEqual(result["model_status"], "failed")

    @patch("backend.analysis_engine.phase2.runner_core.build_visualization_artifacts", return_value={})
    @patch("backend.analysis_engine.phase2.runner_core._run_phase2_stoich_model_pipeline", return_value={"summary": {}})
    @patch("backend.analysis_engine.phase2.runner_core.run_hvg_nonhvg_comparison", side_effect=RuntimeError("comparison failed"))
    def test_comparison_failure_does_not_erase_model_status(self, _comparison_mock, _model_mock, _visual_mock):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            baseline = base / "baseline.csv"
            comparison_frame().to_csv(baseline, index=False)
            result = run_phase2_stoich_pipeline({
                "output_dir": str(base / "analysis_phase2"), "input_baseline_csv": str(baseline),
                "case_id": "branch-test", "enabled": True,
            })
            self.assertEqual(result["comparison_status"], "failed")
            self.assertEqual(result["model_status"], "complete")
            self.assertTrue((base / "analysis_phase2" / ARTIFACTS["feature_audit"]).exists())


class GroupComparisonServiceTests(TestCase):
    def outputs(self):
        audit = pd.DataFrame([{
            "feature_key": "transcriptome::x", "feature_name": "x", "display_name": "X",
            "omics_layer": "transcriptome", "family": "test", "status": "tested",
            "description": "x definition", "source_column": "x", "source_block": "transcriptome",
        }])
        comparison = pd.DataFrame([{
            "feature_key": "transcriptome::x", "effect_value": 0.2, "global_fdr": 0.04,
            "evidence_level": "statistical_association_moderate", "direction": "higher_in_hvg",
        }])
        adjusted = pd.DataFrame([{
            "feature_key": "transcriptome::x", "adjusted_status": "tested", "effect_ci_low": 1.01,
            "effect_ci_high": 1.2, "p_value": 0.03, "adjusted_global_fdr": 0.03,
        }])
        return {
            "hvg_nonhvg_summary": {"status": "complete", "counts": {"tested_fields": 1}},
            "hvg_nonhvg_feature_audit": audit,
            "hvg_nonhvg_feature_comparison": comparison,
            "hvg_nonhvg_adjusted_comparison": adjusted,
            "hvg_nonhvg_distribution_quantiles": pd.DataFrame([{"feature_key": "transcriptome::x", "group": "hvg"}]),
            "hvg_nonhvg_plots_payload": {"effect_forest": [], "feature_distributions": {"transcriptome::x": {"hvg": [1, 2]}}},
            "hvg_nonhvg_run_manifest": {"limits": {"api_page_size_max": 1}},
        }

    @patch("backend.apps.hvg.services.get_case_outputs")
    def test_summary_is_compact_and_detail_is_on_demand(self, outputs_mock):
        outputs_mock.return_value = self.outputs()
        summary = get_group_comparison_summary("case")
        self.assertNotIn("feature_distributions", summary["plots"])
        detail = get_group_comparison_feature_detail("case", "transcriptome::x")
        self.assertEqual(detail["distribution"]["hvg"], [1, 2])

    @patch("backend.apps.hvg.services.get_case_outputs")
    def test_feature_service_validates_sort_and_enforces_page_cap(self, outputs_mock):
        outputs_mock.return_value = self.outputs()
        payload = get_group_comparison_features("case", page_size=999)
        self.assertEqual(payload["page_size"], 1)
        with self.assertRaises(ValueError):
            get_group_comparison_features("case", sort_by="__illegal__")
        with self.assertRaises(ValueError):
            get_group_comparison_features("case", sort_order="sideways")
        with self.assertRaises(ValueError):
            get_group_comparison_features("case", filters={"omics": "genome"})
        with self.assertRaises(FileNotFoundError):
            get_group_comparison_feature_detail("case", "unknown")

    @patch("backend.apps.hvg.services.get_case_outputs")
    def test_legacy_summary_and_search_filter_are_stable(self, outputs_mock):
        outputs_mock.return_value = {}
        legacy = get_group_comparison_summary("legacy")
        self.assertEqual(legacy["comparison_status"], "legacy_not_generated")
        outputs_mock.return_value = self.outputs()
        self.assertEqual(
            get_group_comparison_features("case", filters={"search": "missing"})["total"], 0
        )
        self.assertEqual(
            get_group_comparison_features("case", filters={"evidence": "statistical_association_moderate"})["total"], 1
        )

    @patch("backend.apps.hvg.views.get_group_comparison_features", side_effect=ValueError("Unsupported sort_by"))
    def test_api_view_returns_400_for_illegal_sort(self, _service_mock):
        request = APIRequestFactory().get("/api/hvg/case/group-comparison/features/?sort_by=../../secret")
        response = hvg_group_comparison_features(request, "case")
        self.assertEqual(response.status_code, 400)

    @patch("backend.apps.hvg.services._resolve_case_base")
    def test_download_kind_cannot_form_a_path(self, resolve_mock):
        with tempfile.TemporaryDirectory() as temp:
            resolve_mock.return_value = Path(temp)
            with self.assertRaises(FileNotFoundError):
                get_downloadable_file("case", "../../secret")


class GroupComparisonFrontendContractTests(TestCase):
    def test_component_covers_status_traceability_linkage_and_download_contract(self):
        project_root = Path(__file__).resolve().parents[4]
        component = (project_root / "frontend" / "src" / "components" / "HvgGroupComparisonPanel.vue").read_text(encoding="utf-8")
        for token in [
            "complete", "partial", "unavailable", "failed", "legacy_not_generated",
            "composition_group", "provenance_resolution", "zero_semantics",
            "@chart-click=\"showFeatureByChart\"", "hvg_nonhvg_distribution_quantiles",
            "hvg_nonhvg_plots", "hvg_nonhvg_summary", "hvg_nonhvg_manifest",
        ]:
            self.assertIn(token, component)
        self.assertIn("overflow-wrap: anywhere", component)

    def test_case5_does_not_convert_model_importance_to_group_effect(self):
        project_root = Path(__file__).resolve().parents[4]
        texts = "\n".join([
            (project_root / "frontend" / "src" / "components" / "HvgGroupComparisonPanel.vue").read_text(encoding="utf-8"),
            (project_root / "frontend" / "src" / "views" / "HvgCaseView.vue").read_text(encoding="utf-8"),
        ])
        self.assertIsNone(re.search(r"permutation_importance.{0,200}cliffs_delta", texts, re.DOTALL))
