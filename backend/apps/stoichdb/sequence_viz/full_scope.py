"""Explicit Full-schema adapter; never borrows a Core value or changes a raw column."""
import numpy as np
ADAPTER_VERSION='genome_full_eligibility_v1'
def apply(ds):
    if ds['omics']!='genome' or ds['scope']!='full' or 'coding_valid' in ds['values']:return ds
    required=['is_coding','codon_total_valid','aa_total_20'];n=ds['n'];v=ds['values']
    if not all(k in v for k in required):
        ds['source']['full_coding_eligibility']={'status':'unavailable','missing_fields':[k for k in required if k not in v],'adapter_version':ADAPTER_VERSION};return ds
    # Same predicate as the existing platform's _genome_feature_value fallback,
    # evaluated exclusively on every record in the complete Full file.
    valid=(v['is_coding']>0)&(v['codon_total_valid']>0)&(v['aa_total_20']>0);v['coding_valid']=valid.astype(float)
    ds['metadata']['coding_valid']=['1' if x else '0' for x in valid]
    ds['catalog'].append({'key':'coding_valid','role':'metadata','origin':'derived','declared_feature_family':'derived','source_file_scope':'derived from Full only','unit':'boolean eligibility','primary':False,'inputs':required,'rule':'is_coding>0 AND codon_total_valid>0 AND aa_total_20>0'})
    ds['source']['full_coding_eligibility']={'status':'available','adapter_version':ADAPTER_VERSION,'inputs':required,'input_scope':'full','rule':'is_coding>0 AND codon_total_valid>0 AND aa_total_20>0','n_source':n,'n_eligible':int(valid.sum()),'explicit_source_flag_overwritten':False}
    return ds
