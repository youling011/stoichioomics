from __future__ import annotations
from pathlib import Path
from typing import Any, Optional, Tuple
import h5py
import pandas as pd
from scipy import sparse

from ..schemas import InternalDataset
from ..normalize import normalize_obs_columns, normalize_var_columns


def _decode_scalar(x: Any) -> Any:
    if isinstance(x, (bytes, bytearray)):
        return x.decode('utf-8')
    return x


def _decode_array(arr):
    if hasattr(arr, 'dtype') and arr.dtype.kind in {'S', 'O', 'U'}:
        out = []
        for x in arr:
            out.append(_decode_scalar(x))
        return out
    return arr.tolist() if hasattr(arr, 'tolist') else list(arr)


def _read_axis_group(g: h5py.Group):
    idx_key = '_index' if '_index' in g else None
    idx = _decode_array(g[idx_key][()]) if idx_key else None
    data = {}
    for k in g.keys():
        if k == '_index':
            continue
        obj = g[k]
        if isinstance(obj, h5py.Dataset):
            data[k] = _decode_array(obj[()])
        elif isinstance(obj, h5py.Group):
            keys = set(obj.keys())
            if {'categories', 'codes'}.issubset(keys):
                cats = _decode_array(obj['categories'][()])
                codes = obj['codes'][()]
                vals = []
                for c in codes:
                    c = int(c)
                    vals.append(None if c < 0 else cats[c])
                data[k] = vals
    return pd.DataFrame(data, index=idx)


def _get_shape_from_group(xobj: h5py.Group, encoding: str, expected_shape: Optional[Tuple[int, int]] = None) -> Tuple[int, int]:
    if 'shape' in xobj:
        shape = tuple(int(v) for v in xobj['shape'][()])
        if len(shape) == 2:
            return shape

    if 'shape' in xobj.attrs:
        raw = xobj.attrs['shape']
        shape = tuple(int(v) for v in raw)
        if len(shape) == 2:
            return shape

    if expected_shape is not None:
        return tuple(int(v) for v in expected_shape)

    data = xobj['data'][()]
    indices = xobj['indices'][()]
    indptr = xobj['indptr'][()]

    if encoding == 'csc_matrix':
        n_cols = len(indptr) - 1
        n_rows = int(indices.max()) + 1 if len(indices) else 0
        return (n_rows, n_cols)

    n_rows = len(indptr) - 1
    n_cols = int(indices.max()) + 1 if len(indices) else 0
    return (n_rows, n_cols)


def _read_x(xobj, expected_shape: Optional[Tuple[int, int]] = None):
    if isinstance(xobj, h5py.Dataset):
        arr = xobj[()]
        return sparse.csr_matrix(arr)

    encoding_raw = xobj.attrs.get('encoding-type', '')
    encoding = _decode_scalar(encoding_raw) or ''
    keys = set(xobj.keys())

    if encoding in {'csr_matrix', 'csc_matrix'} or {'data', 'indices', 'indptr'}.issubset(keys):
        data = xobj['data'][()]
        indices = xobj['indices'][()]
        indptr = xobj['indptr'][()]
        shape = _get_shape_from_group(xobj, encoding, expected_shape=expected_shape)

        if encoding == 'csc_matrix':
            return sparse.csc_matrix((data, indices, indptr), shape=shape).tocsr()

        return sparse.csr_matrix((data, indices, indptr), shape=shape)

    raise ValueError(f'Unsupported X storage in h5ad; keys={sorted(keys)}, encoding={encoding!r}')


def read_h5ad(path: str | Path, value_semantics: str = 'unknown') -> InternalDataset:
    path = Path(path)
    with h5py.File(path, 'r') as f:
        obs = _read_axis_group(f['obs']) if 'obs' in f else None
        var = _read_axis_group(f['var']) if 'var' in f else None

        expected_shape = None
        if obs is not None and var is not None:
            expected_shape = (obs.shape[0], var.shape[0])

        X = _read_x(f['X'], expected_shape=expected_shape)

        if obs is None:
            obs = pd.DataFrame(index=[str(i) for i in range(X.shape[0])])
        if var is None:
            var = pd.DataFrame(index=[str(i) for i in range(X.shape[1])])

    obs = normalize_obs_columns(obs)
    var = normalize_var_columns(var)

    if obs.shape[0] != X.shape[0] or var.shape[0] != X.shape[1]:
        raise ValueError(f'h5ad dimensions do not match obs/var: X={X.shape}, obs={obs.shape}, var={var.shape}')

    uns = {
        'source_format': 'h5ad',
        'matrix_semantics': value_semantics,
        'n_cells': int(X.shape[0]),
        'n_genes': int(X.shape[1]),
    }

    return InternalDataset(
        X=X.tocsr(),
        obs=obs,
        var=var,
        uns=uns,
        source_format='h5ad',
        matrix_semantics=value_semantics,
    )
