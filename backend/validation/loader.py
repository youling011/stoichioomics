from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, Optional
import pandas as pd
from scipy import sparse

from .schemas import StandardizedBundle
from .utils import read_json


def load_standardized_bundle(input_dir: str | Path, raw_stoich_file: Optional[str | Path] = None) -> StandardizedBundle:
    base = Path(input_dir)
    required = [
        'standardized_matrix.npz',
        'standardized_obs.csv',
        'standardized_var.csv',
        'standardized_uns.json',
        'input_manifest.json',
        'input_validation_report.json',
        'run_log.json',
    ]
    missing = [f for f in required if not (base / f).exists()]
    if missing:
        raise FileNotFoundError(f'Missing required standardized bundle files in {base}: {missing}')

    X = sparse.load_npz(base / 'standardized_matrix.npz').tocsr()
    obs = pd.read_csv(base / 'standardized_obs.csv')
    var = pd.read_csv(base / 'standardized_var.csv')
    if 'cell_id' in obs.columns:
        obs.index = obs['cell_id'].astype(str)
    if 'gene_id' in var.columns:
        var.index = var['gene_id'].astype(str)
    uns = read_json(base / 'standardized_uns.json')
    manifest = read_json(base / 'input_manifest.json')
    phase1_validation = read_json(base / 'input_validation_report.json')
    run_log = read_json(base / 'run_log.json')

    raw_stoich = None
    if raw_stoich_file:
        raw_p = Path(raw_stoich_file)
        if not raw_p.is_absolute():
            raw_p = (base / raw_p).resolve()
        sep = '\t' if raw_p.suffix.lower() in {'.tsv', '.txt'} else ','
        raw_stoich = pd.read_csv(raw_p, sep=sep)
        if 'gene_id' not in raw_stoich.columns:
            raw_stoich.rename(columns={raw_stoich.columns[0]: 'gene_id'}, inplace=True)
        raw_stoich['gene_id'] = raw_stoich['gene_id'].astype(str)
        raw_stoich.index = raw_stoich['gene_id']

    return StandardizedBundle(
        X=X, obs=obs, var=var, uns=uns,
        input_manifest=manifest, phase1_validation=phase1_validation,
        run_log=run_log, input_dir=base, raw_stoich=raw_stoich
    )
