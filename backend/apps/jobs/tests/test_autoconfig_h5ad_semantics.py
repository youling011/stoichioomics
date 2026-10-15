from tempfile import TemporaryDirectory
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
from django.test import SimpleTestCase

from backend.apps.jobs.autoconfig import _detect_h5ad_matrix_semantics


class H5ADMatrixSemanticsTests(SimpleTestCase):
    def test_explicit_uns_raw_counts_are_detected(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "expression.h5ad"
            data = ad.AnnData(
                X=np.array([[0, 1], [2, 0]], dtype=np.int32),
                obs=pd.DataFrame(index=["cell-1", "cell-2"]),
                var=pd.DataFrame(index=["AT1G01010", "AT1G01020"]),
            )
            data.uns["matrix_semantics"] = "raw_counts"
            data.write_h5ad(path, compression="gzip")

            result = _detect_h5ad_matrix_semantics(path)

        self.assertEqual(result["matrix_semantics"], "raw_counts")
        self.assertEqual(result["confidence"], "high")
        self.assertIn("h5ad_uns_matrix_semantics", result["evidence"])
