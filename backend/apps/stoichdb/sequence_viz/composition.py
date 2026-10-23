import numpy as np
def counts(values,fields,frequency_fields,denom,n,allow_partial_total=False):
    total=values.get(denom,np.full(n,np.nan));freq=np.column_stack([values.get(k,np.full(n,np.nan)) for k in frequency_fields]);raw=freq*total[:,None];rounded=np.rint(raw)
    valid=np.isfinite(raw).all(1)&(raw>=0).all(1)&(abs(raw-rounded)<=1e-6).all(1)&(total>0)
    valid&=(rounded.sum(1)<=total+1e-6) if allow_partial_total else abs(rounded.sum(1)-total)<=1e-6
    direct=np.column_stack([values.get(k,np.full(n,np.nan)) for k in fields]);have=np.isfinite(direct).all(1)&(direct>=0).all(1)&(abs(direct-np.rint(direct))<=1e-6).all(1)&(total>0)
    have&=(direct.sum(1)<=total+1e-6) if allow_partial_total else abs(direct.sum(1)-total)<=1e-6
    conflict=have&valid&(abs(direct-rounded)>1e-6).any(1)
    result=np.full_like(raw,np.nan);result[valid]=rounded[valid];result[have]=direct[have];result[conflict]=np.nan
    return result,{'direct_n':int(have.sum()),'reconstructed_n':int((valid&~have).sum()),'conflict_n':int(conflict.sum()),'n_valid':int(np.isfinite(result).all(1).sum()),'denominator':denom,'integer_tolerance':1e-6,'allow_standard_aa_total_below_length':allow_partial_total}
def clr(a):
    a=np.asarray(a,float);z=np.log(a+.5);return z-z.mean(1,keepdims=True)
