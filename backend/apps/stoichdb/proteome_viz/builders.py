"""Scientific data builders, with no display sampling or browser-side statistics."""
import hashlib,json,warnings
import numpy as np
from scipy.stats import rankdata
from scipy.spatial.distance import pdist,squareform
from scipy.cluster.hierarchy import linkage,leaves_list
from .contracts import CORE_FIELDS,GROUPS,AA,META,STRUCTURE,TITLES,unit,FINGERPRINT,catalog
from . import METHOD_VERSION
from .statistics import summary,robust,histogram,ecdf,correlation,conditional,percentile
from .density import kde1,kde2,hexbin
from .ordination import pca

def build(ds):
    v=ds['values'];n=ds['n'];ids=np.array(ds['ids']);arrays={};figures={}
    profiles={}
    # Compute each column once, including Full extensions needed by both scopes.
    for f,a in v.items():
        profiles[f]={'field':f,'unit':unit(f),**summary(a),'histogram':histogram(a,log=f=='length_aa'),'ecdf':ecdf(a),'kde':kde1(a,f)}
        profiles[f]['n_semantic_invalid']=ds['source'].get('semantic_invalid_counts',{}).get(f,0)
        if f=='length_aa' and profiles[f]['n_semantic_invalid']:
            profiles[f]['histogram']['invalid_nonpositive']=sum(x[1]<=0 for x in ds['source']['semantic_invalid_values'][f])
    fields=list(dict.fromkeys(CORE_FIELDS+ds['original_fields']))

    def col(f):return v[f] if f in v else np.full(n,np.nan)
    def profile(f):
        if f in profiles:return profiles[f]
        return {'field':f,'unit':unit(f),**summary(col(f)),'histogram':histogram([]),'ecdf':ecdf([]),'kde':kde1([])}
    def fig(cid,kind,data,needed=(),valid=None,status=None,reason=None):
        needed=list(needed)
        if valid is None:valid=np.logical_and.reduce([np.isfinite(col(f)) for f in needed]) if needed else np.ones(n,bool)
        count=int(np.sum(valid));available=sum(np.isfinite(col(f)).any() for f in needed)
        if status is None:status='available' if count else 'partial' if available else 'unavailable'
        figures[cid]={'chart_id':cid,'title':TITLES[cid],'method_version':METHOD_VERSION,'primary_scope':ds['scope'],'species_id':ds['species_id'],'dataset_id':ds['dataset_id'],'release_id':ds['release_id'],'source_hash':ds['source_hash'],'status':status,'reason_code':reason or ('missing_required_fields' if status=='unavailable' else None),'fields':[{'key':f,'unit':unit(f),'role':'input'} for f in needed],'coverage':{'n_source':n,'n_valid':count,'n_excluded':n-count,'per_field':{f:{k:profile(f)[k] for k in ['n_valid','n_missing','n_zero']} for f in needed},'aggregation':kind,'sampling_policy':'none'},'method':{'name':kind,'parameters':{},'transforms':[]},'data':{'kind':kind,**data}}
        return figures[cid]
    def groups(x,y,k):
        result=conditional(col(x),col(y),k)
        for g in result:
            member=g.pop('_members');g['kde']=kde1(col(y)[member],y)
        return result
    def pair(cid,x,y,k=10):
        h=hexbin(col(x),col(y));arrays[cid+'_members']=h.pop('membership');valid=h.pop('mask')
        data={'x':x,'y':y,'hex':h,'conditional':groups(x,y,k),'correlation':correlation(col(x),col(y)),'x_profile':profile(x),'y_profile':profile(y)}
        return fig(cid,'hex_conditional',data,[x,y],valid)
    def ordination(cid,fs,clr=False):
        matrix=np.column_stack([col(f) for f in fs]);valid=np.isfinite(matrix).all(1)
        if clr:
            valid&=(matrix>=0).all(1)&(matrix.sum(1)>0)
            transformed=np.full_like(matrix,np.nan);logs=np.log(matrix[valid]+.5);transformed[valid]=logs-logs.mean(1,keepdims=True)
        else:transformed=matrix
        result=pca(transformed,scale=not clr);mask=result.pop('mask');fit_ids=ids[mask]
        if 'coordinates' not in result:
            if clr and profile('aa_entropy_bits')['n_valid']:
                return fig(cid,'distribution',{'profile':profile('aa_entropy_bits'),'fallback':'entropy_only','ordination':result},fs+['aa_entropy_bits'],np.isfinite(col('aa_entropy_bits')),status='partial',reason=result['reason'])
            if not clr and any(profile(f)['n_valid'] for f in fs):
                return fig(cid,'intervals',{'profiles':[profile(f) for f in fs],'fallback':'resource_intervals','ordination':result},fs,np.isfinite(matrix).any(1),status='partial',reason=result['reason'])
            return fig(cid,'ordination',{'ordination':result},fs,mask,status='unavailable',reason=result['reason'])
        co=result.pop('coordinates');arrays[cid+'_coordinates']=co;arrays[cid+'_row_index']=np.flatnonzero(mask)
        arrays[cid+'_components']=result['components'];arrays[cid+'_directions']=result['directions']
        h=hexbin(co[:,0],co[:,1] if co.shape[1]>1 else np.zeros(len(co)));h.pop('mask');membership=h.pop('membership');all_members=np.full(n,-1,dtype=np.int32);all_members[mask]=membership;arrays[cid+'_members']=all_members
        extreme=sorted(range(len(co)),key=lambda i:(-float(np.linalg.norm(co[i])),fit_ids[i]))[:3]
        data={'ordination':result,'hex':h,'input_fields':fs,'extremes':[{'protein_id':str(fit_ids[i]),'coordinate':co[i].tolist()} for i in extreme],'axis_y_reason':None if co.shape[1]>1 else 'Rank one: constant display baseline'}
        if clr:
            data['entropy']=profile('aa_entropy_bits');data['pseudocount']=.5
            choose=np.argsort(fit_ids,kind='stable')[:400];raw=matrix[mask][choose];reference=np.log(raw+.5);reference-=reference.mean(1,keepdims=True);base=pdist(reference)
            sensitivity=[]
            for pseudo in [.1,.5,1.]:
                z=np.log(raw+pseudo);z-=z.mean(1,keepdims=True);d=pdist(z)
                sensitivity.append({'pseudocount':pseudo,'diagnostic_n':len(choose),'distance_correlation':float(np.corrcoef(base,d)[0,1]) if len(base)>2 and np.ptp(base)>0 else None})
            data['sensitivity']=sensitivity
        return fig(cid,'ordination',data,fs,mask,status=result['status'],reason=result.get('reason'))

    fs=['N_atoms_per_aa','S_atoms_per_aa','C_N_ratio','pI','gravy','instability_index','avg_oxidation_state_C']
    fig('B01','intervals',{'profiles':[profile(f) for f in fs],'independent_axes':True},fs,valid=np.ones(n,bool))
    signature=[]
    for f in (fields if ds['scope']=='core' else CORE_FIELDS):
        p=profile(f);q=p['quantiles'];z,sc=robust(col(f));scale=sc['scale'][0];med=sc['median'][0]
        signature.append({'field':f,'unit':unit(f),'group':next((g for g,ff in GROUPS.items() if f in ff),'Core extensions'),'n':p['n_valid'],'quantiles':q,'z':((np.array(q)-med)/scale).tolist() if q else [None]*7,'constant':p['fallback']=='constant' if q else False})
    fig('B02','signature',{'rows':signature,'probabilities':[0,.05,.25,.5,.75,.95,1],'color_range':[-4,4]},CORE_FIELDS)
    fig('B03','distribution',{'profile':profile('length_aa'),'log':True},['length_aa'],np.isfinite(col('length_aa'))&(col('length_aa')>0))
    qc=['length_canonical_aa','unknown_residues_for_atoms','stop_asterisk_count'];length=col('length_aa');valid=np.isfinite(length)&(length>0)
    for f in qc:valid&=np.isfinite(col(f))
    canonical=col(qc[0])/np.where(length>0,length,np.nan);unknown=col(qc[1])/np.where(length>0,length,np.nan)
    high=valid&(canonical>=.98)&(unknown<=.01)&(col(qc[2])<=0);medium=valid&~high&(canonical>=.95)&(unknown<=.05);low=valid&~high&~medium
    metadata=[{'field':f,'nonempty':sum(bool(s.strip()) for s in ds['metadata'][f]),'n_unique_nonempty':len({s for s in ds['metadata'][f] if s.strip()}),'n':n} for f in META]
    fig('B04','quality',{'categories':[{'name':k,'count':int(m.sum())} for k,m in [('high',high),('medium',medium),('low',low),('unavailable',~valid)]],'annotation':metadata},qc+['length_aa'],valid,status='available' if valid.all() else 'partial')
    ef=[f'{e}_atoms_per_aa' for e in ['C','H','N','O','S']];ef+=['Se_atoms_per_aa'] if 'Se_atoms_per_aa' in v else []
    elements=['C','H','N','O','S','Se'];atoms=np.array([np.nansum(col(f'{e}_atoms')) for e in elements]);known=np.array([np.isfinite(col(f'{e}_atoms')).sum() for e in elements]);den=atoms.sum()
    fig('B05','elements',{'profiles':[profile(f) for f in ef],'budget':[{'element':e,'atoms':float(a) if count else None,'share':float(a/den) if count and den else None,'n_valid':int(count),'n_missing':n-int(count)} for e,a,count in zip(elements,atoms,known)],'budget_scope':'all atoms' if np.all(known==n) else 'known atoms only; incomplete counts reported'},ef,status='available' if np.all(known==n) else 'partial',reason=None if np.all(known==n) else 'incomplete_atom_budget')
    fig('B06','distribution',{'profile':profile('N_atoms_per_aa')},['N_atoms_per_aa'])
    fig('B07','stratified_ecdf',{'profile':profile('pI'),'groups':groups('length_aa','pI',4),'reference':7,'stratify':'length_aa'},['length_aa','pI'])
    fig('B08','violin',{'field':'gravy','groups':groups('length_aa','gravy',4),'stratify':'length_aa'},['length_aa','gravy'])
    fig('B09','intervals',{'profiles':[profile(f'AA_{a}_pct') for a in AA]},[f'AA_{a}_pct' for a in AA])
    fig('B11','density_rows',{'profiles':[profile(f) for f in STRUCTURE[:3]]},STRUCTURE[:3])
    fig('B12','distribution',{'profile':profile('avg_oxidation_state_C'),'reference':0},['avg_oxidation_state_C'])
    fig('B13','field_atlas',{'fields':catalog(fields),'profiles':[profile(f) for f in fields[:6]],'total_fields':len(fields)},CORE_FIELDS,valid=np.ones(n,bool))
    fig('B14','field_quantiles',{'profiles':[profile(f) for f in fields[:6]]},CORE_FIELDS,valid=np.ones(n,bool))
    pair('B15','pI','N_atoms_per_aa')
    ordination('D01',[f'{e}_atoms_per_aa' for e in ['C','H','N','O','S']])
    p=pair('D02','N_atoms_per_aa','S_atoms_per_aa');se=col('Se_atoms');positive=np.flatnonzero(np.isfinite(se)&(se>0));p['data']['selenium_positive_n']=len(positive);p['data']['selenium_candidates']=[{'protein_id':str(ids[i]),'atoms':float(se[i])} for i in sorted(positive,key=lambda i:(-se[i],ids[i]))[:16]]
    figures['B10']={'chart_id':'B10','chart_ref':'D02'}
    ordination('D03',[f'AA_{a}_count' for a in AA],clr=True)
    fs=['aa_hydrophobic_frac','aa_polar_frac','aa_pos_frac','aa_neg_frac','aa_aromatic_frac'];gg=[]
    for i,f in enumerate(fs):gg.append({'group_id':f,'label':f,'n':profile(f)['n_valid'],'summary':summary(col(f)*100),'kde':kde1(col(f)*100,'percentage_pct'),'quantiles':np.quantile(col(f)[np.isfinite(col(f))]*100,[.05,.1,.25,.5,.75,.9,.95]).tolist() if np.isfinite(col(f)).any() else None})
    fig('D04','violin',{'groups':gg,'field':'class fraction (%)'},fs)
    fs=['pI','net_charge_pH7','gravy','instability_index','aliphatic_index','aromaticity','mw_da'];rows=[]
    for f in fs:
        a=col(f);a=np.where(a>0,np.log10(np.where(a>0,a,np.nan)),np.nan) if f=='mw_da' else a;z,_=robust(a);rows.append({'field':f,'original':profile(f),'scaled':summary(z)})
    fig('D05','quantile_bands',{'rows':rows,'transforms':{'mw_da':'log10'}},fs,valid=np.ones(n,bool))
    p=pair('D06','gravy','instability_index');good=np.isfinite(col('gravy'))&np.isfinite(col('instability_index'));quads=[]
    for i,(lowx,lowy) in enumerate([(True,True),(False,True),(True,False),(False,False)]):
        use=good&((col('gravy')<0) if lowx else (col('gravy')>=0))&((col('instability_index')<40) if lowy else (col('instability_index')>=40));quads.append({'name':f'GRAVY {"<0" if lowx else "≥0"}; index {"<40" if lowy else "≥40"}','n':int(use.sum())})
    p['data']['quadrants']=quads;p['data']['reference_x']=0;p['data']['reference_y']=40
    matrix=np.column_stack([col(f) for f in STRUCTURE]);z,sc=robust(matrix);sort=np.lexsort((ids,np.where(np.isfinite(col('flex_mean')),col('flex_mean'),np.inf)));arrays['D07_order']=sort;arrays['D07_z']=z
    edges=np.linspace(0,n,min(n,400)+1,dtype=int);blocks=[]
    for a,b in zip(edges[:-1],edges[1:]):
        m=z[sort[a:b]];med=[]
        for j in range(len(STRUCTURE)):
            good=m[:,j][np.isfinite(m[:,j])];med.append(float(np.median(good)) if len(good) else None)
        blocks.append({'rank_start':int(a),'rank_end':int(b),'n':int(b-a),'n_valid':np.isfinite(m).sum(0).tolist(),'median_z':med})
    fig('D07','structure_atlas',{'fields':STRUCTURE,'blocks':blocks,'profiles':[profile(f) for f in STRUCTURE],'color_range':[-3,3],'row_count':n,'sort':'flex_mean, protein_id; missing last','scale':sc},STRUCTURE,valid=np.ones(n,bool),status='available' if np.isfinite(matrix).all() else 'partial')
    fig('D08','violin',{'field':'surface_access_em_mean','groups':groups('flex_mean','surface_access_em_mean',5),'stratify':'flex_mean','correlation':correlation(col('flex_mean'),col('surface_access_em_mean'))},['flex_mean','surface_access_em_mean'])
    fs=['O_C_ratio','H_C_ratio','O_N_ratio','a280_1mgml_reduced','extinction_reduced','aromaticity'];zr=col('avg_oxidation_state_C');rows=[]
    for f in fs:
        scaled,_=robust(col(f));gg=conditional(zr,scaled,4)
        for g in gg:g['native_summary']=summary(col(f)[g.pop('_members')])
        rows.append({'field':f,'groups':gg,'original':profile(f)})
    fig('D09','strata_matrix',{'rows':rows,'stratify':'avg_oxidation_state_C'},['avg_oxidation_state_C']+fs,valid=np.isfinite(zr),status='available' if all(np.isfinite(col(f)).any() for f in fs) else 'partial')
    p=pair('D10','avg_oxidation_state_C','gravy');contours=kde2(col('avg_oxidation_state_C'),col('gravy'));p['data']['kind']='probability_contours';p['data']['contours']=contours;p['data']['reference_y']=0
    if contours['status']!='available':p['status']='partial';p['reason_code']=contours['reason']
    fs=['N_atoms_per_aa','S_atoms_per_aa','pI','gravy','instability_index','aa_entropy_bits','avg_oxidation_state_C'];m=np.column_stack([col(f) for f in fs]);r=np.full((7,7),np.nan);counts=np.zeros((7,7),int)
    if np.isfinite(m).all() and n>=3:
        ranks=rankdata(m,axis=0,method='average')
        with np.errstate(invalid='ignore',divide='ignore'):r=np.corrcoef(ranks,rowvar=False)
        counts[:]=n
        constant=np.ptp(m,axis=0)==0;r[constant,:]=np.nan;r[:,constant]=np.nan
    else:
        for i in range(7):
            for j in range(i,7):
                cc=correlation(m[:,i],m[:,j]);r[i,j]=r[j,i]=np.nan if cc['rho'] is None else cc['rho'];counts[i,j]=counts[j,i]=cc['n']
    order=leaves_list(linkage(squareform(np.maximum(0,1-r),checks=False),method='average')).tolist() if np.isfinite(r).all() else list(range(7))
    fig('D13','correlation_matrix',{'fields':fs,'matrix':r,'pair_n':counts,'order':order,'range':[-1,1],'sort_reason':'average linkage 1-rho' if np.isfinite(r).all() else 'undefined pairs: fixed field order'},fs,valid=np.ones(n,bool))
    score_sets={
      'Resource':['N_atoms_per_aa','S_atoms_per_aa','C_atoms_per_aa','avg_residue_mass_da','C_N_ratio','N_S_ratio'],
      'S-rich':['S_atoms_per_aa','sulfur_aa_frac','disulfide_density'],
      'AA anomaly':[f'AA_{a}_pct' for a in AA]+['aa_entropy_bits'],
      'Redox':['avg_oxidation_state_C','O_C_ratio','H_C_ratio']}
    scores={};evidence={};partial={}
    for name,fs in score_sets.items():
        x=np.column_stack([col(f) for f in fs]);z,sc=robust(x);z=z if name=='S-rich' else abs(z);complete=np.isfinite(x).all(1);s=np.mean(z,axis=1);s[~complete]=np.nan;scores[name]=s
        count=np.isfinite(x).sum(1);ps=np.divide(np.nansum(z,axis=1),count,out=np.full(n,np.nan),where=count>0);partial[name]={'rows':np.flatnonzero(~complete),'scores':ps[~complete],'component_n':count[~complete]};evidence[name]={'fields':fs,'n_valid':int(complete.sum()),'n_partial':int(((count>0)&~complete).sum()),'scale':sc}
    scores['Hydropathy']=col('gravy');scores['SS upper/L']=col('disulfide_density');names=['Resource','S-rich','AA anomaly','Hydropathy','SS upper/L','Redox'];top={};union=[];ranks={}
    for name in names:
        a=scores[name];good=np.flatnonzero(np.isfinite(a));ordered=good[np.lexsort((ids[good],-a[good]))];top[name]=[{'protein_id':str(ids[i]),'gene_id':ds['metadata']['gene_id'][i],'score':float(a[i]),'row_index':int(i)} for i in ordered[:8]];ranks[name]=percentile(a)
        for i in ordered[:3]:
            if i not in union:union.append(i)
    arrays['candidate_scores']=np.column_stack([scores[name] for name in names]);arrays['candidate_percentiles']=np.column_stack([ranks[name] for name in names])
    for name,part in partial.items():
        arrays['partial_'+name.replace(' ','_')+'_rows']=part['rows'];arrays['partial_'+name.replace(' ','_')+'_scores']=part['scores'];arrays['partial_'+name.replace(' ','_')+'_component_n']=part['component_n']
    fig('D14','candidates',{'modules':names,'top':top,'evidence':evidence,'n_scored':{k:int(np.isfinite(a).sum()) for k,a in scores.items()},'scoring':'MAD→SD→1; complete components in primary ranking; partial evidence separate'},valid=np.ones(n,bool))
    fig('D15','candidate_matrix',{'modules':names,'rows':[{'protein_id':str(ids[i]),'gene_id':ds['metadata']['gene_id'][i],'values':[float(ranks[k][i]) if np.isfinite(ranks[k][i]) else None for k in names],'scores':[float(scores[k][i]) if np.isfinite(scores[k][i]) else None for k in names]} for i in union],'range':[0,100],'percentile':'100 × average rank / module valid n'},valid=np.ones(n,bool))
    fingerprint={'species_id':ds['species_id'],'dataset_id':ds['dataset_id'],'scope':ds['scope'],'source_hash':ds['source_hash'],'n':n,'means':{f:profile(f)['mean'] for f in FINGERPRINT},'counts':{f:profile(f)['n_valid'] for f in FINGERPRINT}}
    for cid in ['D11','D12','D16']:fig(cid,'cohort',{'requires_cohort':True},valid=np.ones(n,bool))
    return {'figures':figures,'profiles':profiles,'arrays':arrays,'fields':fields,'fingerprint':fingerprint,'metadata_coverage':metadata}
