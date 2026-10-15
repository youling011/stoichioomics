import unittest

import pandas as pd
from scipy import sparse

from backend.input_adapter.merge import _deduplicate_index_rows, _join_cell_metadata
from backend.input_adapter.schemas import InternalDataset


class JoinCellMetadataTests(unittest.TestCase):
    def test_external_metadata_replaces_overlapping_h5ad_obs_fields(self):
        dataset = InternalDataset(
            X=sparse.csr_matrix([[1, 0], [0, 1]]),
            obs=pd.DataFrame(
                {"cell_id": ["cell_a", "cell_b"], "sample_id": ["embedded", "embedded"]},
                index=["cell_a", "cell_b"],
            ),
            var=pd.DataFrame({"gene_id": ["gene_a", "gene_b"]}, index=["gene_a", "gene_b"]),
        )
        metadata = pd.DataFrame(
            {"cell_id": ["cell_a", "cell_b"], "sample_id": ["external", "external"], "condition": ["wt", "wt"]},
            index=["cell_a", "cell_b"],
        )

        result = _join_cell_metadata(dataset, metadata)

        self.assertEqual(list(result.obs.columns), ["cell_id", "sample_id", "condition"])
        self.assertEqual(result.obs["sample_id"].tolist(), ["external", "external"])
        self.assertEqual(result.obs["condition"].tolist(), ["wt", "wt"])

    def test_stoich_index_rows_keep_stable_first_gene_representative(self):
        frame = pd.DataFrame(
            {"gene_id": ["gene_a", "gene_a", "gene_b"], "length_nt": [10, 20, 30]},
            index=["gene_a", "gene_a", "gene_b"],
        )

        result = _deduplicate_index_rows(frame)

        self.assertEqual(result.index.tolist(), ["gene_a", "gene_b"])
        self.assertEqual(result.loc["gene_a", "length_nt"], 10)
