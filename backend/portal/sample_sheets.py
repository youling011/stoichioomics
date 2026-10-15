from __future__ import annotations
import pandas as pd


def sample_sheet_template(input_mode: str) -> pd.DataFrame:
    if input_mode == 'h5ad_multi':
        return pd.DataFrame([
            {'file_name': 'sample_0h.h5ad', 'sample_id': 'sample_0h', 'condition': 'control', 'timepoint': '0h', 'batch': 'batch1', 'donor': 'NA', 'format': 'h5ad'},
            {'file_name': 'sample_24h.h5ad', 'sample_id': 'sample_24h', 'condition': 'control', 'timepoint': '24h', 'batch': 'batch1', 'donor': 'NA', 'format': 'h5ad'},
        ])
    if input_mode == 'tenx_multi':
        return pd.DataFrame([
            {'sample_id': 'sample_a', 'bundle_dir': 'sample_a', 'matrix_file': 'matrix.mtx.gz', 'features_file': 'features.tsv.gz', 'barcodes_file': 'barcodes.tsv.gz', 'condition': 'control', 'timepoint': '0h', 'batch': 'batch1', 'donor': 'NA'},
            {'sample_id': 'sample_b', 'bundle_dir': 'sample_b', 'matrix_file': 'matrix.mtx.gz', 'features_file': 'features.tsv.gz', 'barcodes_file': 'barcodes.tsv.gz', 'condition': 'treatment', 'timepoint': '24h', 'batch': 'batch1', 'donor': 'NA'},
        ])
    return pd.DataFrame()
