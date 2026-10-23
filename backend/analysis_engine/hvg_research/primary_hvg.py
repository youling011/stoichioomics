"""Official labels and identical frozen QC, independent of any stoichiometry."""
import numpy as np,pandas as pd
import anndata as ad, scanpy as sc
from backend.analysis_engine.common import ExpressionDataset,bundle_to_expression_dataset
from backend.analysis_engine.phase1.utils import filter_low_quality_genes
FLAVORS={'seurat_v3','seurat_v3_paper','seurat','cell_ranger'}
def official_hvg(dataset,config):
 method=config.get('hvg_method','seurat_v3')
 if type(config.get('n_top_genes',2000)) is not int or config.get('n_top_genes',2000)<1:raise ValueError('n_top_genes must be a positive integer')
 if not 0<float(config.get('loess_span',.3))<=1:raise ValueError('loess_span must be in (0,1]')
 if int(config.get('min_cells',3))<1 or int(config.get('min_counts',1))<0:raise ValueError('Invalid gene QC threshold')
 if method not in FLAVORS:raise ValueError('Unsupported official HVG flavor: '+str(method))
 ids=pd.Index(dataset.gene_ids)
 if ids.has_duplicates or ids.isna().any():raise ValueError('Duplicate or missing gene_id; resolve before research')
 X=dataset.matrix.copy().tocsr();X.eliminate_zeros()
 if not np.isfinite(X.data).all() or (X.data<0).any():raise ValueError('Invalid matrix values')
 semantics=config.get('matrix_semantics') or dataset.uns.get('matrix_semantics')
 semantics={'raw_counts':'counts','log1p_normalized':'log_normalized'}.get(semantics,semantics)
 if method.startswith('seurat_v3'):
  if semantics!='counts' or not np.allclose(X.data,np.rint(X.data),atol=1e-6,rtol=0):raise ValueError('Seurat v3 requires verified nonnegative integer counts')
 elif semantics not in ['log_normalized','lognorm','log_normalized_expression']:
  raise ValueError('seurat/cell_ranger require explicitly verified log-normalized matrix')
 keepcells=np.asarray((X>0).sum(1)).ravel()>=int(config.get('min_cell_genes',0))
 if not keepcells.any():raise ValueError('No cells pass QC')
 ds=ExpressionDataset(X[keepcells],list(dataset.gene_ids),list(dataset.gene_names),list(np.array(dataset.cell_ids)[keepcells]),dataset.obs.loc[keepcells].reset_index(drop=True),dict(dataset.uns))
 filtered,qc=filter_low_quality_genes(ds,config.get('min_cells',3),config.get('min_counts',1))
 if filtered.n_cells<3 or filtered.n_genes<2:raise ValueError('Insufficient matrix after QC')
 obs=filtered.obs.copy();obs.index=pd.Index(filtered.cell_ids)
 a=ad.AnnData(filtered.matrix,obs=obs,var=pd.DataFrame(index=pd.Index(filtered.gene_ids,name='gene_id')))
 batch=config.get('batch_key')
 if batch:
  if batch not in obs or obs[batch].isna().any():raise ValueError('Invalid or missing batch_key')
  if obs[batch].value_counts().min()<3:raise ValueError('Each batch requires at least 3 cells')
 kw={'flavor':method,'n_top_genes':min(int(config.get('n_top_genes',2000)),a.n_vars),'batch_key':batch,'inplace':False}
 if method.startswith('seurat_v3'):kw['span']=float(config.get('loess_span',.3))
 else:kw['n_bins']=int(config.get('n_bins',20))
 hv=sc.pp.highly_variable_genes(a,**kw)
 M=filtered.matrix;mean=np.asarray(M.mean(0)).ravel();var=np.maximum(np.asarray(M.multiply(M).mean(0)).ravel()-mean**2,0)*filtered.n_cells/max(filtered.n_cells-1,1)
 detected=np.asarray((M>0).sum(0)).ravel()/filtered.n_cells
 scorecol='variances_norm' if 'variances_norm' in hv else 'dispersions_norm'
 out=hv.reset_index().rename(columns={'gene_id':'gene_id','highly_variable':'is_hvg'})
 if 'gene_id' not in out:out=out.rename(columns={out.columns[0]:'gene_id'})
 # Scanpy dispersion flavors retain categorical Interval mean bins. Preserve
 # their labels as strings so every supported flavor is Parquet/JSON portable.
 for column in out:
  if isinstance(out[column].dtype,pd.CategoricalDtype):out[column]=out[column].astype(str)
 out['gene_name']=filtered.gene_names;out['hvg_score']=hv[scorecol].to_numpy();out['mean_expr']=mean;out['variance']=var
 out['raw_dispersion']=np.divide(var,mean,out=np.zeros_like(var),where=mean>0);out['normalized_dispersion']=out['hvg_score'];out['pct_cells_detected']=detected;out['dropout_rate']=1-detected
 out['hvg_rank']=out.hvg_score.rank(method='first',ascending=False).astype('Int64');out['hvg_rank_semantics']='display score rank; official highly_variable_rank preserved separately'
 out['hvg_backend']='scanpy';out['hvg_method']=method;out['hvg_score_semantics']=scorecol;out['description_matrix_semantics']=semantics
 eligibility=pd.DataFrame({'gene_id':dataset.gene_ids});eligibility['eligible']=eligibility.gene_id.isin(out.gene_id);eligibility['is_hvg']=eligibility.gene_id.map(out.set_index('gene_id').is_hvg).astype('boolean');eligibility['reason']=np.where(eligibility.eligible,'passed','expression_QC_failed')
 meta={'backend':'scanpy','version':sc.__version__,'parameters':kw,'matrix_semantics':semantics,'qc':qc,'cells_before':dataset.n_cells,'cells_after':filtered.n_cells,'labels':'official highly_variable; no feature/model filtering','batch_key':batch}
 return out,eligibility,a,meta
