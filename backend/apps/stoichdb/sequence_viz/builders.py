import numpy as np
from .contracts import FIGURES,CORE,unit,scientific_mask,FINGERPRINT
from .statistics import profile,summary,robust,ecdf,histogram,kde,hexbin,conditional,correlation,pareto,smooth_contours
from .ordination import fit,cluster
from . import METHOD_VERSION
def pair(v,x,y,n,m,tx='identity',ty='identity',gridsize=40,k=10):
    def transform(a,t):
        if t=='identity':return a.copy()
        if t=='log10':return np.log10(np.where(a>0,a,np.nan))
        if t=='log1p':return np.log1p(np.where(a>=0,a,np.nan))
        raise ValueError('invalid_transform')
    rawx=v.get(x,np.full(n,np.nan));rawy=v.get(y,np.full(n,np.nan));a=transform(rawx,tx);b=transform(rawy,ty);mask=scientific_mask(v,[x,y],m,n);a[~mask]=np.nan;b[~mask]=np.nan
    h=hexbin(a,b,gridsize);membership=h.pop('membership');h.pop('mask');groups=conditional(a,b,k)
    for g in groups:g.pop('_members',None)
    return {'kind':'pair','x':x,'y':y,'transform_x':tx,'transform_y':ty,'hex':h,'conditional':groups,'correlation':correlation(a,b),'response':profile(rawy[np.isfinite(a)&np.isfinite(b)],y,unit(y,m)),'x_unit':unit(x,m),'y_unit':unit(y,m),'n_pair':h['n'],'excluded_n':n-h['n']},membership
def build(ds):
    from .genome import derive as genome
    from .transcriptome import derive as transcriptome
    # Analysis may invalidate a direct composition count without rewriting its
    # original zero/invalid value in the full source atlas or raw-row downloads.
    raw_values={k:ds['values'][k] for k in ds['fields']}
    (genome if ds['omics']=='genome' else transcriptome)(ds)
    physical={r['key'] for r in ds['catalog']}
    for key in ds['values']:
        if key not in physical:ds['catalog'].append({'key':key,'role':'numeric','origin':'derived','declared_feature_family':'derived','source_file_scope':'derived','unit':unit(key,ds['omics']),'primary':False})
    m=ds['omics'];v=ds['values'];n=ds['n'];get=lambda k:v.get(k,np.full(n,np.nan));arrays={};figures={};profiles={k:{**profile(raw_values[k],k,unit(k,m)),'n_invalid':ds['source']['invalid_counts'].get(k,0)} for k in ds['fields']}
    for k,p in profiles.items():p['n_raw_missing']=p['n_missing']-p['n_invalid']
    def prof(k,mask=None,violin=False):
        if mask is None:mask=scientific_mask(v,[k],m,n)
        return profile(get(k)[mask],k,unit(k,m),violin)
    def interval(ks,mask=None,violin=False):return [prof(k,mask,violin) for k in ks]
    def mat(ks,mask=None):return np.column_stack([get(k) for k in ks]) if ks else np.empty((n,0))
    def pair_for(cid,x,y,tx='identity',ty='identity'):
        d,a=pair(v,x,y,n,m,tx,ty);arrays[cid+'_membership']=a;return d
    pca_cache={};correlation_cache={}
    for cid,c in FIGURES.items():
        if c['omics']!=m:continue
        kind=c['proposed_kind'];ks=c['fields_or_vectors'];status='available';reason=None;fitn=n;d={'kind':kind};mask=scientific_mask(v,ks,m,n)
        if kind=='independent_intervals':d.update(profiles=interval(ks),independent_axes=True)
        elif kind in ['complete_field_atlas','native_quantile_table','core_quantile_signature']:
            d.update(fields=ds['fields'],total=len(profiles),profiles_ref='fields',rows=[{'field':k,'quantiles':p['quantiles'],'z':[(q-p['quantiles'][3])/p['scale'] for q in p['quantiles']] if p['quantiles'] else [None]*7,'n':p['n_valid'],'constant':p.get('fallback')=='constant'} for k,p in profiles.items()] if kind=='core_quantile_signature' else [])
        elif kind in ['region_violins','paired_delta_histograms','aa20_intervals']:
            d.update(profiles=interval(ks,mask if kind=='aa20_intervals' else None,kind=='region_violins'))
        elif kind in ['hex_conditional_marginal','custom_pair']:
            tx='log10' if cid in ['GB07','TD19'] else 'log1p' if cid=='GB10' else 'identity';d=pair_for(cid,*ks[:2],tx)
        elif kind=='distribution_ecdf':d.update(profile=prof(ks[0],mask),n_fit=int((mask&np.isfinite(get(ks[0]))).sum()))
        elif kind in ['biotype_and_evidence_bars','biotype_gene_coverage','biotype_orf_evidence_matrix','biotype_length_violins']:
            key='biotype' if m=='genome' else 'transcript_biotype';cats=np.asarray(ds['metadata'].get(key,['unknown']*n));names,counts=np.unique(cats,return_counts=True);order=np.argsort(-counts,kind='stable');names=names[order];counts=counts[order];rows=[]
            for name,count in zip(names,counts):
                sel=cats==name;r={'name':str(name),'count':int(count)}
                if kind=='biotype_gene_coverage':r['distinct_genes']=len(set(np.asarray(ds['metadata'].get('gene_id',['']*n))[sel])-set(['']))
                if kind=='biotype_orf_evidence_matrix':
                    valid=ds['coding'];stop=get('orf_has_stop');r['evidence']=[int((sel&valid&(stop==1)).sum()),int((sel&valid&(stop==0)).sum()),int((sel&~valid).sum()),int((sel&valid&~np.isin(stop,[0,1])).sum())]
                if kind=='biotype_length_violins':r['profile']=profile(np.log10(np.where(get('length_nt_acgu')[sel]>0,get('length_nt_acgu')[sel],np.nan)),'log10 length (nt)','log10 nt',True)
                rows.append(r)
            d.update(categories=rows,coding_n=int(ds['coding'].sum()),other_n=int((~ds['coding']).sum()))
        elif kind=='skew_joint_and_regions':d=pair_for(cid,'locus_at_skew','locus_gc_skew');d.update(profiles=interval(['locus_gc_skew','exon_gc_skew','promoter_gc_skew'],violin=True))
        elif kind in ['chromosome_cumulative_tracks','chromosome_score_tracks']:
            seq=np.asarray(ds['metadata'].get('seqid',['']*n));start=get('start_1');end=get('end_1');tracks=[];order_all=[];cumulative=np.full(n,np.nan);membership=np.full(n,-1,np.int32);offset=0
            for name in np.unique(seq):
                ix=np.flatnonzero((seq==name)&np.isfinite(start)&np.isfinite(end)&(end>=start));ix=ix[np.lexsort((np.asarray(ds['ids'])[ix],end[ix],start[ix]))];order_all.extend(ix)
                if not len(ix):continue
                rows=[]
                if kind=='chromosome_cumulative_tracks':
                    delta=get('locus_count_G')[ix]-get('locus_count_C')[ix];good=np.isfinite(delta);cumulative[ix[good]]=np.cumsum(delta[good]);bounds=np.linspace(0,len(ix),min(300,len(ix))+1,dtype=int)
                    for a,b in zip(bounds[:-1],bounds[1:]):
                        chunk=ix[a:b];ok=chunk[np.isfinite(cumulative[chunk])]
                        if len(ok):rows.append({'x':float(start[ok[-1]]),'value':float(cumulative[ok[-1]]),'min':float(cumulative[ok].min()),'max':float(cumulative[ok].max()),'count':len(chunk),'bin_id':offset});membership[chunk]=offset;offset+=1
                    excluded=int((~good).sum())
                else:
                    edges=np.linspace(start[ix].min(),max(end[ix].max(),start[ix].min()+1),49);groups=np.clip(np.searchsorted(edges,start[ix],side='right')-1,0,47);excluded=0
                    for j in range(48):
                        chunk=ix[groups==j];z=get('island_score')[chunk];p=summary(z);q=p['quantiles'];rows.append({'x':float((edges[j]+edges[j+1])/2),'value':q[3] if q else None,'min':q[2] if q else None,'max':q[4] if q else None,'count':len(chunk),'bin_id':offset});membership[chunk]=offset;offset+=1
                tracks.append({'seqid':str(name),'n':len(ix),'min':float(start[ix].min()),'max':float(end[ix].max()),'excluded_increment_n':excluded,'status':'partial' if excluded else 'available','bins':rows})
            arrays[cid+'_order']=np.array(order_all,dtype=np.int64);arrays[cid+'_membership']=membership
            if kind=='chromosome_cumulative_tracks':arrays['locus_gc_cumulative_count']=cumulative
            d.update(tracks=tracks,unplaced_n=n-len(order_all),n_coordinates=len(order_all));status='partial' if any(t['excluded_increment_n'] for t in tracks) or len(order_all)<n else 'available'
        elif kind in ['dinucleotide_grammar','rna_dinucleotide_grammar','codon_grammar_64']:
            panels=[];chunks=[ks[:16],ks[16:32]] if cid=='GD03' else [ks[:16]] if cid=='TD03' else [ks]
            for fields in chunks:
                if not fields:continue
                a=mat(fields);use=mask if kind=='codon_grammar_64' else np.ones(n,bool);cells=[]
                for j,k in enumerate(fields):z=a[use,j];finite=z[np.isfinite(z)];cells.append({'field':k,'value':float(finite.mean()) if len(finite) else None,'n':len(finite)})
                panels.append({'name':fields[0].split('_')[0] if cid=='GD03' else 'frequency','cells':cells,'columns':16 if kind=='codon_grammar_64' else 4})
            if cid=='TD03':
                cells=[]
                from .contracts import RNA,words
                for w in words(RNA,2):
                    num=get('dinuc_'+w+'_freq');den=get('frac_'+w[0])*get('frac_'+w[1]);good=np.isfinite(num)&np.isfinite(den)&(num>0)&(den>0);z=np.log2(num[good]/den[good]);cells.append({'field':w,'value':float(z.mean()) if len(z) else None,'n':len(z)})
                panels.append({'name':'mean per-record log2(observed / independent background)','cells':cells,'columns':4,'diverging':True})
            d['panels']=panels
        elif kind=='distance_distribution_and_length':d=pair_for(cid,'locus_length_bp','dinuc_distance','log10');d['distance_profile']=prof('dinuc_distance')
        elif kind in ['clr_pca_density_directions','robust_pca_density_directions']:
            fields=c['fit_inputs'] or ks;a=mat(fields);info,scores,valid,x=fit(a,ds['coding'] if cid in ['GD11','TD10','TD12'] else None,kind.startswith('clr'));pca_cache[cid]=(info,scores,valid,x);d.update(info,fields=fields);status=info['status'];reason=info.get('reason_code');fitn=info['n_fit']
            arrays[cid+'_rows']=np.flatnonzero(valid)
            if scores is not None:
                arrays[cid+'_scores']=scores;arrays[cid+'_components']=np.array(info['components']);sx=scores[:,0];sy=scores[:,1] if scores.shape[1]>1 else np.zeros(len(scores));h=hexbin(sx,sy);local=h.pop('membership');h.pop('mask');mem=np.full(n,-1,np.int32);mem[valid]=local;arrays[cid+'_membership']=mem;d['hex']=h
                if cid in ['GD05','TD04']:d['contours']=smooth_contours(sx,sy)
        elif kind=='kmeans_context':
            ref='GD11' if cid=='GD12' else 'GD19';info,scores,valid,x=pca_cache[ref];labels,details=cluster(x,get(ks[0])[valid]);status=details['status'];reason=details.get('reason_code');d.update(details,fields=ks,fit_reference=ref,groups=[]);arrays[cid+'_rows']=np.flatnonzero(valid)
            if labels is not None:
                arrays[cid+'_assignments']=labels;mem=np.full(n,-1,np.int32);mem[valid]=labels;arrays[cid+'_membership']=mem;z=robust(mat(ks)[valid])[0]
                for i in range(3):d['groups'].append({'name':f'Cluster {i+1}','group_id':i,'n':int((labels==i).sum()),'profiles':interval(ks,valid&(mem==i)),'median_z':np.nanmedian(z[labels==i],axis=0).tolist()})
        elif kind in ['quantile_strata_context','gc3_entropy_stratified_violin','gc_length_stratified_ecdf']:
            by=ks[0];context=ks if kind=='quantile_strata_context' else [ks[0]]
            if cid=='TB04':by='length_nt_acgu';context=['gc_content']
            if cid=='TD11':by='derived_gc3_fraction';context=['derived_codon_entropy_bits']
            groups=conditional(get(by),get(by),3 if cid=='GD08' else 4);z=robust(mat(context))[0];mem=np.full(n,-1,np.int32);rows=[]
            for g in groups:
                ix=g.pop('_members');mem[ix]=g['group_id'];rows.append({**g,'name':f'Q{g["group_id"]+1}','profiles':[prof(k,np.isin(np.arange(n),ix),kind=='gc3_entropy_stratified_violin') for k in context],'median_z':np.nanmedian(z[ix],axis=0).tolist()})
            arrays[cid+'_membership']=mem;d.update(groups=rows,fields=context,stratify_field=by,profile=prof('gc_content') if cid=='TB04' else None)
        elif kind in ['pairwise_spearman_matrix','threshold_network','rna_protein_cross_matrix']:
            left=ks[:3] if kind=='rna_protein_cross_matrix' else ks;right=ks[3:] if kind=='rna_protein_cross_matrix' else ks;cells=[]
            for i,x in enumerate(left):
                for j,y in enumerate(right):
                    use=scientific_mask(v,[x,y],m,n);r=correlation(get(x)[use],get(y)[use]);cells.append({'x':j,'y':i,'x_field':y,'y_field':x,**r})
            d.update(x_fields=right,y_fields=left,cells=cells,threshold=.65,threshold_range=[0,.95,.05]);d['edges']=[r for r in cells if r['x']>r['y'] and r['rho'] is not None and abs(r['rho'])>=.65] if kind=='threshold_network' else []
        elif kind=='descriptive_pareto':
            x,y=map(get,ks);front=pareto(x,y);arrays[cid+'_front']=front;d=pair_for(cid,*ks);d.update(front=[{'row':int(i),'id':ds['ids'][i],'x':float(x[i]),'y':float(y[i])} for i in np.flatnonzero(front)],front_n=int(front.sum()),objectives=['min '+ks[0],'max '+ks[1]])
        elif kind=='codon_position_gc':d=pair_for(cid,'GC12_percent','gc3_percent');d['profiles']=interval(ks[:3],ds['coding'],True)
        elif kind=='rna_composition_budget':
            fields=[f'frac_{w}' for w in 'ACGU'];a=mat([f'n_{w}' for w in 'ACGU']);good=np.isfinite(a).all(1)&(a>=0).all(1);total=a[good].sum(0);d.update(profiles=interval(fields,violin=True),record_mean=[summary(get(k))['mean'] for k in fields],pooled=(total/total.sum()).tolist() if total.sum()>0 else [None]*4,budget_n=int(good.sum()),labels=list('ACGU'))
        elif kind=='element_density_budget':
            fields=[f'atoms_per_nt_{e}' for e in 'CHONP'];a=mat([f'{e}_atoms' for e in 'CHONP']);good=np.isfinite(a).all(1)&(a>=0).all(1);total=a[good].sum(0);d.update(profiles=interval(fields),pooled=(total/total.sum()).tolist() if total.sum()>0 else [None]*5,budget_n=int(good.sum()),labels=list('CHONP'))
        elif kind=='orf_length_stop_ecdf':d.update(profile=prof('orf_len_aa',get('orf_len_aa')>0),groups=[{'name':str(flag),'profile':prof('orf_len_aa',(get('orf_has_stop')==flag)&(get('orf_len_aa')>0))} for flag in [0,1]],stop_missing_n=int((~np.isin(get('orf_has_stop'),[0,1])).sum()));d['profile']['histogram']=histogram(get('orf_len_aa'),True)
        elif kind=='orf_span_joint_ecdf':d=pair_for(cid,'length_nt_acgu','orf_len_nt','log10','log10');d.update(ratio_profile=prof('coding_coverage_raw'),ratio_above_one_n=int((get('coding_coverage_raw')>1).sum()))
        elif kind in ['native_candidate_evidence','candidate_union_evidence']:
            fields=ks;score=get(ks[0]);ids=np.asarray(ds['ids']);order=np.lexsort((ids,-np.nan_to_num(score,nan=-np.inf)));arrays[cid+'_order']=order;rows=[]
            if kind=='candidate_union_evidence':
                union=set()
                for k in ks:
                    a=get(k+'_percentile');o=np.lexsort((ids,-np.nan_to_num(a,nan=-np.inf)));union.update(int(i) for i in o[:3] if np.isfinite(a[i]))
                order=np.array(sorted(union,key=lambda i:ds['ids'][i]),int)
            for i in order[:12] if kind=='native_candidate_evidence' else order:rows.append({'row':int(i),'id':ds['ids'][i],'values':[float(get(k)[i]) for k in ks],'percentiles':[float(get(k+'_percentile')[i]) for k in ks] if kind=='candidate_union_evidence' else [],'coverage':int(get('score_module_coverage')[i])})
            d.update(fields=ks,rows=rows,total=n,preview_only=True)
            if cid=='GS01' and (get('composition_coverage')<13).any():status='partial';reason='composition_components_incomplete; see per-record coverage'
        elif kind in ['species_fingerprint_pca','species_dinuc_pca','species_distance','species_dispersion']:d.update(cohort_ref=True,fields=ks)
        else:raise ValueError('unimplemented_chart_kind:'+kind)
        # Panel-wise capability: preserve usable panels when optional Full inputs are missing.
        if 'profiles' in d:
            good=sum(p['n_valid']>0 for p in d['profiles']);status='unavailable' if not good else 'partial' if good<len(d['profiles']) else status
        if 'hex' in d and not d['hex']['n']:status='partial' if any(p['n_valid'] for p in d.get('profiles',[])) else 'unavailable';reason='no_eligible_pairs'
        if 'panels' in d:
            good=[any(x['value'] is not None for x in p['cells']) for p in d['panels']];status='available' if all(good) else 'partial' if any(good) else 'unavailable'
        # A conflicting appended source must be visible rather than silently deemed equivalent.
        relevant=set(c.get('source_dependency_expansion',{}))&set(ds['source']['same_name_conflicts'])
        if relevant and status=='available':status='partial';reason='core_full_conflicts_preserved_core'
        figures[cid]={'chart_id':cid,'title':c['old_title'],'design_kind':kind,'species_id':ds['species_id'],'omics':m,'dataset_id':ds['dataset_id'],'release_id':ds['release_id'],'primary_scope':ds['scope'],'source_hash':ds['source_hash'],'method_version':METHOD_VERSION,'status':status,'reason_code':reason,'coverage':{'n_source':n,'n_fit':fitn,'n_pair':d.get('n_pair'),'sampling_policy':'none'},'method':{'name':kind,'inputs':ks,'fit_inputs':c['fit_inputs'],'parameters':{'quantile_method':'linear','conditional_groups':10,'pseudo_count':.5 if kind.startswith('clr') else None}},'data':d}
    fp={};counts={}
    fields=FINGERPRINT[m]+([f'locus_dinuc_{a+b}_freq' for a in 'ACGT' for b in 'ACGT'] if m=='genome' else [])
    dinuc_fields=[k for k in fields if k.startswith('locus_dinuc_')];dinuc_mask=np.ones(n,bool)
    if dinuc_fields:
        df=mat(dinuc_fields);dinuc_mask=np.isfinite(df).all(1)&(df>=0).all(1)&(abs(df.sum(1)-1)<=1e-6)&(get('locus_dinuc_total_valid')>0)
    for k in fields:
        use=dinuc_mask if k in dinuc_fields else scientific_mask(v,[k],m,n);a=get(k);good=use&np.isfinite(a);fp[k]=float(a[good].mean()) if good.any() else None;counts[k]=int(good.sum())
    metadata_coverage=[{'field':k,'n_source':n,'n_valid':sum(bool(x) for x in a),'n_unique':len(set(a)), 'role':'metadata'} for k,a in ds['metadata'].items()]
    for k,a in raw_values.items():ds['values'][k]=a
    return {'figures':figures,'arrays':arrays,'profiles':profiles,'fingerprint':{'means':fp,'counts':counts},'metadata_coverage':metadata_coverage}
