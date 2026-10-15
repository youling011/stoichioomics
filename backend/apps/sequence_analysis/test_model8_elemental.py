from __future__ import annotations

from django.test import SimpleTestCase

from backend.apps.sequence_analysis.engine import (
    AA_RESIDUE_FORMULAS as RUNTIME_AA_RESIDUE_FORMULAS,
    protein_features as runtime_protein_features,
)
from scripts.build_model8_case1_atlas import FEATURE_SPECS
from scripts.build_model8_case2_coupling import FEATURE_PAIRS
from scripts.build_model8_case4_upload_gold import protein_features as gold_protein_features
from scripts.model8_a0_a3_implement import protein_stats
from scripts.model8_elemental_contract import (
    AA_RESIDUE_FORMULAS as MODEL8_AA_RESIDUE_FORMULAS,
    ELEMENTAL_CONTRACT_ID,
    LEGACY_AMBIGUOUS_FIELDS,
    protein_elemental_features,
)


class Model8ElementalSemanticsTests(SimpleTestCase):
    def test_all_twenty_residue_formulas_match_runtime_engine(self):
        self.assertEqual(set(MODEL8_AA_RESIDUE_FORMULAS), set(RUNTIME_AA_RESIDUE_FORMULAS))
        for residue in MODEL8_AA_RESIDUE_FORMULAS:
            for atom in ("C", "N", "S"):
                self.assertEqual(
                    MODEL8_AA_RESIDUE_FORMULAS[residue].get(atom, 0),
                    RUNTIME_AA_RESIDUE_FORMULAS[residue].get(atom, 0),
                    f"{residue} {atom} formula mismatch",
                )

    def test_hand_calculated_residue_formula(self):
        result = protein_elemental_features("ACMN")
        self.assertEqual(result["length"], 4)
        self.assertEqual(result["c_atoms"], 15)
        self.assertEqual(result["n_atoms"], 5)
        self.assertEqual(result["s_atoms"], 2)
        self.assertEqual(result["cys_count"], 1)
        self.assertEqual(result["ser_count"], 0)
        self.assertEqual(result["asn_count"], 1)
        self.assertEqual(result["met_count"], 1)
        self.assertAlmostEqual(result["c_atoms_per_aa"], 3.75)
        self.assertAlmostEqual(result["n_atoms_per_aa"], 1.25)
        self.assertAlmostEqual(result["s_atoms_per_aa"], 0.5)

    def test_serine_is_not_sulfur_and_methionine_is_sulfur(self):
        serine = protein_elemental_features("SS")
        methionine = protein_elemental_features("MM")
        self.assertEqual(serine["ser_count"], 2)
        self.assertEqual(serine["s_atoms"], 0)
        self.assertEqual(methionine["met_count"], 2)
        self.assertEqual(methionine["s_atoms"], 2)

    def test_model8_matches_runtime_engine_atom_totals(self):
        model8 = protein_elemental_features("ACMNW")
        runtime = runtime_protein_features("ACMNW")
        for atom in ("c", "n", "s"):
            self.assertEqual(model8[f"{atom}_atoms"], runtime[f"{atom}_atoms"])
            self.assertAlmostEqual(model8[f"{atom}_atoms_per_aa"], runtime[f"{atom}_per_aa"])

    def test_a0_and_gold_builders_emit_explicit_contract(self):
        a0 = protein_stats("ACMN")
        gold = gold_protein_features("ACMN")
        self.assertEqual(a0["elemental_contract_id"], ELEMENTAL_CONTRACT_ID)
        self.assertEqual(gold["elemental_contract_id"], ELEMENTAL_CONTRACT_ID)
        self.assertTrue(LEGACY_AMBIGUOUS_FIELDS.isdisjoint(a0))
        self.assertTrue(LEGACY_AMBIGUOUS_FIELDS.isdisjoint(gold))
        for field in ("c_atoms_per_aa", "n_atoms_per_aa", "s_atoms_per_aa"):
            self.assertAlmostEqual(float(a0[field]), float(gold[field]), places=6)

    def test_case_feature_contracts_are_explicit(self):
        case1_fields = {spec["column"] for spec in FEATURE_SPECS if spec["omics"] == "protein"}
        case2_fields = {pair["y"] for pair in FEATURE_PAIRS}
        self.assertIn("c_atoms_per_aa", case1_fields)
        self.assertIn("n_atoms_per_aa", case1_fields)
        self.assertIn("s_atoms_per_aa", case1_fields)
        self.assertIn("protein_c_atoms_per_aa", case2_fields)
        self.assertIn("protein_n_atoms_per_aa", case2_fields)
        self.assertIn("protein_s_atoms_per_aa", case2_fields)
        self.assertTrue(LEGACY_AMBIGUOUS_FIELDS.isdisjoint(case1_fields))
        self.assertTrue(LEGACY_AMBIGUOUS_FIELDS.isdisjoint(case2_fields))
