from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, Tuple, List
import json, subprocess
import pandas as pd
import numpy as np
from scipy import sparse

from .schemas import InternalDataset
from .detect import detect_input_bundle
from .readers import (
    read_h5ad, read_tenx, read_matrix_csv, read_metadata, read_stoich_table,
    read_sample_sheet, validate_sample_sheet,
)

RECOMMENDED_META_FIELDS = ['sample_id','batch','condition','timepoint','cluster','cell_type','donor','perturbation','pseudotime']


def _run_external_stoich(base: Path, stoich_cfg: Dict[str, Any]) -> Path:
    output_file = stoich_cfg.get('output_file', 'generated_stoich_features.csv')
    cmd = stoich_cfg.get('external_command')
    if not cmd:
        raise ValueError('stoich.external_command is missing')
    fmt_vars = {k: str((base / v).resolve()) for k, v in stoich_cfg.items() if isinstance(v, str) and k not in {'external_command'}}
    fmt_vars['output_csv'] = str((base / output_file).resolve())
    rendered = cmd.format(**fmt_vars)
    subprocess.run(rendered, shell=True, check=True, cwd=str(base))
    out = base / output_file
    if not out.exists():
        raise FileNotFoundError(f'External stoich command did not create {out}')
    return out


def _join_cell_metadata(ds: InternalDataset, meta: pd.DataFrame) -> InternalDataset:
    add = meta.drop(columns=['cell_id'], errors='ignore')
    overlap = [column for column in add.columns if column in ds.obs.columns]
    if overlap:
        ds.obs = ds.obs.drop(columns=overlap)
    ds.obs = ds.obs.join(add, how='left')
    return ds


def _deduplicate_index_rows(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.index.is_unique:
        return frame
    return frame.loc[~frame.index.duplicated(keep='first')].copy()


def _apply_metadata_field_mapping(meta: pd.DataFrame, mapping: Dict[str, Any] | None) -> pd.DataFrame:
    if not mapping:
        return meta
    standard_fields = mapping.get('standard_fields') if isinstance(mapping, dict) else mapping
    if not isinstance(standard_fields, dict):
        return meta
    rename = {}
    for standard, source in standard_fields.items():
        if source and source in meta.columns and standard not in meta.columns:
            rename[source] = standard
    return meta.rename(columns=rename).copy() if rename else meta


def _annotate_obs(ds: InternalDataset, row: pd.Series, prefix_cell_ids: bool) -> InternalDataset:
    for col in ['sample_id','batch','condition','timepoint','cluster','cell_type','donor','perturbation','pseudotime']:
        if col in row.index and pd.notna(row[col]):
            ds.obs[col] = row[col]
    sample_id = str(row.get('sample_id', '') or '')
    if prefix_cell_ids and sample_id:
        ds.obs = ds.obs.copy()
        ds.obs['cell_id'] = sample_id + ':' + ds.obs['cell_id'].astype(str)
        ds.obs.index = ds.obs['cell_id'].astype(str)
    return ds


def _subset_genes(ds: InternalDataset, gene_ids: List[str]) -> InternalDataset:
    idx = pd.Index(ds.var.index.astype(str))
    pos = idx.get_indexer(gene_ids)
    keep = pos >= 0
    pos = pos[keep]
    final_genes = [gene_ids[i] for i, ok in enumerate(keep) if ok]
    X = ds.X[:, pos].tocsr()
    var = ds.var.loc[final_genes].copy()
    return InternalDataset(X=X, obs=ds.obs.copy(), var=var, uns=ds.uns.copy(), source_format=ds.source_format, matrix_semantics=ds.matrix_semantics)


def _remap_to_union(ds: InternalDataset, union_genes: List[str]) -> InternalDataset:
    current = pd.Index(ds.var.index.astype(str))
    col_map = {g: i for i, g in enumerate(current)}
    new_pos = np.array([col_map.get(g, -1) for g in union_genes], dtype=int)
    mask = new_pos >= 0
    take_old = new_pos[mask]
    tmp = ds.X[:, take_old]
    coo = tmp.tocoo()
    target_cols = np.where(mask)[0][coo.col]
    new = sparse.coo_matrix((coo.data, (coo.row, target_cols)), shape=(ds.X.shape[0], len(union_genes))).tocsr()
    var = ds.var.reindex(union_genes).copy()
    if 'gene_id' not in var.columns:
        var.insert(0, 'gene_id', pd.Index(union_genes, dtype=str))
    return InternalDataset(X=new, obs=ds.obs.copy(), var=var, uns=ds.uns.copy(), source_format=ds.source_format, matrix_semantics=ds.matrix_semantics)


def _concat_datasets(datasets: List[InternalDataset], merge_strategy: str='inner_genes') -> InternalDataset:
    if not datasets:
        raise ValueError('No datasets to concatenate')
    if len(datasets) == 1:
        return datasets[0]
    gene_sets = [set(ds.var.index.astype(str)) for ds in datasets]
    if merge_strategy == 'inner_genes':
        genes = sorted(set.intersection(*gene_sets))
        aligned = [_subset_genes(ds, genes) for ds in datasets]
    elif merge_strategy == 'union_genes':
        genes = sorted(set.union(*gene_sets))
        aligned = [_remap_to_union(ds, genes) for ds in datasets]
    else:
        raise ValueError(f'Unsupported merge_strategy: {merge_strategy}')
    X = sparse.vstack([ds.X for ds in aligned], format='csr')
    obs = pd.concat([ds.obs for ds in aligned], axis=0)
    var = aligned[0].var.copy()
    if 'gene_id' not in var.columns:
        var.insert(0, 'gene_id', var.index.astype(str))
    uns = {
        'source_format': 'multi_concat',
        'matrix_semantics': datasets[0].matrix_semantics,
        'merge_strategy': merge_strategy,
        'n_inputs': len(datasets),
    }
    return InternalDataset(X=X, obs=obs, var=var, uns=uns, source_format='multi_concat', matrix_semantics=datasets[0].matrix_semantics)


def _build_from_h5ad_multi(base: Path, exp_cfg: Dict[str, Any], semantics: str) -> Tuple[InternalDataset, Dict[str, Any]]:
    ss = read_sample_sheet(base / exp_cfg['sample_sheet'])
    validate_sample_sheet(ss, 'h5ad_multi')
    prefix = bool(exp_cfg.get('prefix_cell_ids', True))
    merge_strategy = exp_cfg.get('merge_strategy', 'inner_genes')
    datasets = []
    samples = []
    for _, row in ss.iterrows():
        file_name = str(row['file_name'])
        ds = read_h5ad(base / file_name, value_semantics=semantics)
        ds = _annotate_obs(ds, row, prefix)
        datasets.append(ds)
        samples.append({'file_name': file_name, 'sample_id': str(row.get('sample_id','')), 'n_cells': int(ds.n_cells), 'n_genes': int(ds.n_genes)})
    merged = _concat_datasets(datasets, merge_strategy=merge_strategy)
    merged.uns.update({'source_format': 'h5ad_multi', 'samples': samples, 'merge_strategy': merge_strategy})
    return merged, {'sample_sheet_rows': int(ss.shape[0]), 'samples': samples}


def _build_from_tenx_multi(base: Path, exp_cfg: Dict[str, Any], semantics: str) -> Tuple[InternalDataset, Dict[str, Any]]:
    ss = read_sample_sheet(base / exp_cfg['sample_sheet'])
    validate_sample_sheet(ss, 'tenx_multi')
    prefix = bool(exp_cfg.get('prefix_cell_ids', True))
    merge_strategy = exp_cfg.get('merge_strategy', 'inner_genes')
    datasets = []
    samples = []
    for _, row in ss.iterrows():
        bundle_dir = str(row.get('bundle_dir', '') or '.').strip()
        bbase = (base / bundle_dir).resolve() if bundle_dir else base
        ds = read_tenx(
            bbase,
            matrix_file=str(row.get('matrix_file', exp_cfg.get('matrix_file', 'matrix.mtx'))),
            features_file=str(row.get('features_file', exp_cfg.get('features_file', 'features.tsv'))),
            barcodes_file=str(row.get('barcodes_file', exp_cfg.get('barcodes_file', 'barcodes.tsv'))),
            value_semantics=semantics,
        )
        ds = _annotate_obs(ds, row, prefix)
        datasets.append(ds)
        samples.append({'sample_id': str(row.get('sample_id','')), 'bundle_dir': str(row.get('bundle_dir','.')), 'n_cells': int(ds.n_cells), 'n_genes': int(ds.n_genes)})
    merged = _concat_datasets(datasets, merge_strategy=merge_strategy)
    merged.uns.update({'source_format': 'tenx_multi', 'samples': samples, 'merge_strategy': merge_strategy})
    return merged, {'sample_sheet_rows': int(ss.shape[0]), 'samples': samples}


def build_internal_dataset(config: Dict[str, Any]) -> Tuple[InternalDataset, Dict[str, Any], Dict[str, Any]]:
    base = Path(config['input_dir'])
    manifest = detect_input_bundle(base, config)
    exp_cfg = config.get('expression', {})
    fmt = manifest['expression']['detected_format']
    semantics = exp_cfg.get('value_semantics', 'unknown')
    multi_info = None

    if fmt == 'h5ad':
        ds = read_h5ad(base / exp_cfg.get('file', manifest['expression']['files'][0]), value_semantics=semantics)
    elif fmt == 'tenx':
        ds = read_tenx(base,
            matrix_file=exp_cfg.get('matrix_file','matrix.mtx'),
            features_file=exp_cfg.get('features_file','features.tsv'),
            barcodes_file=exp_cfg.get('barcodes_file','barcodes.tsv'),
            value_semantics=semantics)
    elif fmt in {'csv', 'tsv'}:
        ds = read_matrix_csv(base / exp_cfg.get('file', manifest['expression']['files'][0]),
            orientation=exp_cfg.get('orientation', 'auto'), value_semantics=semantics,
            gene_id_col=exp_cfg.get('gene_id_col', 'gene_id'))
    elif fmt == 'h5ad_multi':
        ds, multi_info = _build_from_h5ad_multi(base, exp_cfg, semantics)
    elif fmt == 'tenx_multi':
        ds, multi_info = _build_from_tenx_multi(base, exp_cfg, semantics)
    else:
        raise ValueError(f'Unsupported input format: {fmt}')

    meta_cfg = config.get('metadata', {}) or {}
    if meta_cfg.get('file'):
        meta = read_metadata(base / meta_cfg['file'])
        meta = _apply_metadata_field_mapping(meta, meta_cfg.get('field_mapping'))
        ds = _join_cell_metadata(ds, meta)

    stoich_cfg = config.get('stoich', {}) or {}
    stoich_df = None
    if stoich_cfg.get('file'):
        stoich_df = read_stoich_table(base / stoich_cfg['file'])
    elif stoich_cfg.get('external_command'):
        out = _run_external_stoich(base, stoich_cfg)
        stoich_df = read_stoich_table(out)
        manifest['stoich'] = {'present': True, 'file': str(out.relative_to(base))}
    elif stoich_cfg.get('require', False):
        raise FileNotFoundError('stoich.require=true but no stoich file or external command provided')

    validation = {
        'n_cells': int(ds.X.shape[0]),
        'n_genes_expression': int(ds.X.shape[1]),
        'source_format': ds.source_format,
        'matrix_semantics': ds.matrix_semantics,
        'recommended_metadata_fields_present': [c for c in RECOMMENDED_META_FIELDS if c in ds.obs.columns],
        'recommended_metadata_fields_missing': [c for c in RECOMMENDED_META_FIELDS if c not in ds.obs.columns],
        'duplicate_cell_ids': int(ds.obs.index.duplicated().sum()),
        'duplicate_gene_ids': int(ds.var.index.duplicated().sum()),
        'has_negative_values': bool(ds.X.min() < 0),
        'zero_only_cells': int(((ds.X.getnnz(axis=1)) == 0).sum()),
        'zero_only_genes': int(((ds.X.getnnz(axis=0)) == 0).sum()),
    }
    if multi_info is not None:
        validation['multi_input'] = multi_info

    if stoich_df is not None:
        overlap = ds.var.index.intersection(stoich_df.index)
        validation['stoich_present'] = True
        validation['n_genes_stoich'] = int(stoich_df.shape[0])
        validation['n_genes_overlap'] = int(len(overlap))
        validation['gene_overlap_fraction_vs_expression'] = float(len(overlap) / max(1, ds.var.shape[0]))
        validation['gene_overlap_fraction_vs_stoich'] = float(len(overlap) / max(1, stoich_df.shape[0]))
        validation['overlap_examples'] = [str(x) for x in list(overlap[:10])]
        stoich_join = stoich_df.drop(columns=['gene_id'], errors='ignore').copy()
        stoich_join = _deduplicate_index_rows(stoich_join)
        drop_overlap = [c for c in stoich_join.columns if c in ds.var.columns and c not in {'gene_id'}]
        if drop_overlap:
            stoich_join = stoich_join.drop(columns=drop_overlap, errors='ignore')
        ds.var = ds.var.join(stoich_join, how='left')
    else:
        validation['stoich_present'] = False

    ds.uns.update({
        'case_id': config.get('case_id'),
        'input_dir': str(base.resolve()),
        'source_format': ds.source_format,
        'matrix_semantics': ds.matrix_semantics,
        'input_manifest': manifest,
    })
    if multi_info is not None:
        ds.uns['multi_input'] = multi_info
    return ds, manifest, validation


def export_standardized_dataset(dataset: InternalDataset, output_dir: str | Path, manifest: Dict[str, Any], validation: Dict[str, Any], config: Dict[str, Any]) -> None:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    sparse.save_npz(out / 'standardized_matrix.npz', dataset.X.tocsr())
    dataset.obs.to_csv(out / 'standardized_obs.csv', index=False)
    dataset.var.to_csv(out / 'standardized_var.csv', index=False)
    with open(out / 'standardized_uns.json', 'w', encoding='utf-8') as f:
        json.dump(dataset.uns, f, ensure_ascii=False, indent=2)
    with open(out / 'input_manifest.json', 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    with open(out / 'input_validation_report.json', 'w', encoding='utf-8') as f:
        json.dump(validation, f, ensure_ascii=False, indent=2)
    h5ad_report = {'written': False, 'path': str((out / 'standardized.h5ad').resolve()), 'error': None}
    try:
        import anndata as ad
        obs = dataset.obs.copy()
        var = dataset.var.copy()
        if 'cell_id' in obs.columns:
            obs.index = obs['cell_id'].astype(str)
        if 'gene_id' in var.columns:
            var.index = var['gene_id'].astype(str)
        adata = ad.AnnData(X=dataset.X.tocsr(), obs=obs, var=var, uns=dataset.uns.copy())
        adata.layers['counts_or_count_like'] = dataset.X.tocsr()
        adata.uns['hvg_layer_contract'] = {
            'primary_X': 'counts_or_count_like',
            'required_layer': 'counts_or_count_like',
            'matrix_semantics': dataset.matrix_semantics,
            'gene_axis': 'var',
            'cell_axis': 'obs',
        }
        adata.write_h5ad(out / 'standardized.h5ad')
        h5ad_report['written'] = True
    except Exception as exc:
        h5ad_report['error'] = str(exc)
    with open(out / 'standardized_h5ad_report.json', 'w', encoding='utf-8') as f:
        json.dump(h5ad_report, f, ensure_ascii=False, indent=2)
    run_log = {
        'case_id': config.get('case_id'),
        'input_dir': config.get('input_dir'),
        'output_dir': str(out.resolve()),
        'expression_format': manifest['expression']['detected_format'],
        'n_cells': int(dataset.X.shape[0]),
        'n_genes': int(dataset.X.shape[1]),
        'workspace': config.get('workspace', {}),
        'standardized_h5ad': h5ad_report,
    }
    with open(out / 'run_log.json', 'w', encoding='utf-8') as f:
        json.dump(run_log, f, ensure_ascii=False, indent=2)
