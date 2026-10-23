from pathlib import Path
from .primary_hvg import official_hvg
from .artifacts import atomic_json
from backend.validation.loader import load_standardized_bundle
from backend.analysis_engine.common import bundle_to_expression_dataset
def run_primary_pipeline(config):
 d=Path(config['output_dir']);d.mkdir(parents=True,exist_ok=True)
 bundle=load_standardized_bundle(config['standardized_input_dir'],config.get('raw_stoich_file'));L,E,A,M=official_hvg(bundle_to_expression_dataset(bundle),config)
 L.to_csv(d/'hvg_baseline.csv',index=False);E.to_parquet(d/'gene_eligibility.parquet',index=False)
 summary={'analysis_mode':'global_hvg','method_metadata':M,'n_rows_primary':len(L),'n_hvgs_primary':int(L.is_hvg.sum()),'primary_output':str(d/'hvg_baseline.csv'),'primary_backend':'scanpy'}
 atomic_json(d/'phase1_mode_summary.json',summary);atomic_json(d/'hvg_method_manifest.json',M)
 return {'analysis_mode':'global_hvg','output_dir':str(d),'baseline_csv':str(d/'hvg_baseline.csv'),'summary':summary}
