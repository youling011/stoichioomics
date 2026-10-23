"""All charts derive from shared complete populations, never preview slices."""
import collections
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from backend.apps.stoichdb.proteome_viz.density import hexbin
from .contracts import MODES,KEY,FIGURES,COHORT_IDS,unit,EXTRA
from .statistics import distribution,conditional,numbers
from .mapping import link,aggregate
from .analysis import island,chain_math
from .coordinates import build as coordinate_build
from .correlations import cross_correlations
def records(f):return f.reset_index().to_dict('records')
def build(ds):
    frames=ds['frames'];fields=ds['fields'];profiles={};metadata={};tables={};members={};charts={};matrices={};source=ds['source']
    for m,f in ds['raw'].items():
        profiles[m]=[];metadata[m]=[]
        for i,k in enumerate(fields[m]):
            r=distribution(frames[m][k],40);r.update(field=k,field_id=f'{m[0].upper()}{i+1:03}',source_unit=unit(m,k),family=k.split('_')[0]);profiles[m].append(r)
        for k in ds['metadata'][m]:
            s=f[k].astype(str);valid=s.str.strip().ne('');vc=s[valid].value_counts(sort=True)
            metadata[m].append({'field':k,'n_source':len(f),'n_nonempty':int(valid.sum()),'n_missing':int((~valid).sum()),'categories':[{'value':v,'count':int(n)} for v,n in vc.items()]})
    def put(cid,data,population,n,valid=None,status='available',reason=None):
        contract=FIGURES[cid];valid=n if valid is None else valid
        charts[cid]={'id':cid,'title':contract['title'],'renderer_kind':contract['renderer_kind'],'status':status if valid else 'unavailable','reason':reason if valid else reason or 'no_valid_population','population':population,'n_source':n,'n_valid':valid,'n_missing':n-valid,'unit':'dimensionless' if cid in ['OV04','OV05','CX03','CX04','CX05'] else 'see source fields','parameters':contract['parameters'],'method':contract['method'],'caveats':contract['interpretation'],'data':data,'member_lookup':'members/'}
    # Preserve valid raw atlases even if one Core source is invalid.
    if len(frames)!=3:
        for cid in FIGURES:
            if cid not in COHORT_IDS:put(cid,{},'source-dependent analysis',0,status='invalid_source',reason='one_or_more_core_sources_invalid');charts[cid]['status']='invalid_source'
        return dict(charts=charts,profiles=profiles,metadata=metadata,tables=tables,members=members,matrices=matrices,source=source,frames=frames,ds=ds)
    linked,mapping=link(frames);j=aggregate(linked,fields);g,island_audit=island(frames['genome'],'');linked['genome']=g;g['_gene']=g.gene_id
    c,exact,math=chain_math(j,g,linked['transcriptome'],linked['proteome'])
    exact.index.name='transcript_id';c.index.name='gene_id';j.index.name='gene_id'
    names=g.set_index('gene_id').gene_name if 'gene_name' in g else pd.Series(dtype=str)
    for f in [j,c]:f['gene_name']=names.reindex(f.index).fillna('')
    tables['gene_matrix']=j.reset_index();tables['chain_rows']=records(c);tables['exact_pairs']=records(exact)
    mapping_rows=[]
    for m,f in linked.items():
        for row in f.to_dict('records'):
            evidence=row.get('_mapping_evidence','genome_anchor' if m=='genome' else 'gene_id' if row.get('_gene') else 'unmapped')
            mapping_rows.append({'omics':m,'entity_id':row[KEY[m]],'entity_type':KEY[m].replace('_id',''),'gene_id':row.get('_gene',''),'source_gene_id':row.get('gene_id',''),'evidence':evidence,'status':'mapped' if row.get('_gene') else evidence,'transcript_id':row.get('transcript_id',''),'ensembl_gene_id':row.get('ensembl_gene_id',''),'ensembl_transcript_id':row.get('ensembl_transcript_id','')})
    tables['x0_mapping']=mapping_rows;tables['x0_conflicts']=mapping['protein_conflicts']
    # Complete native membership for every anchored gene is shared by all tables.
    gene_members={m:linked[m].loc[linked[m]._gene.ne('')].groupby('_gene')[KEY[m]].agg(list).to_dict() for m in MODES}
    for row in tables['chain_rows']:
        row.update({m+'_ids':gene_members[m].get(row['gene_id'],[]) for m in MODES});row['direction']=str(int(row['shift_GT']>=0))+str(int(row['shift_TP']>=0))
    tables['x1_shifts']=sorted(tables['chain_rows'],key=lambda r:(-r['resource_magnitude'],r['gene_id']))
    tables['candidates']=sorted([r for r in tables['chain_rows'] if np.isfinite(r.get('candidate_score',np.nan))],key=lambda r:(-r['candidate_score'],r['gene_id']))
    tables['x4_pairs']=sorted(tables['exact_pairs'],key=lambda r:(-abs(r['pi_delta']) if np.isfinite(r['pi_delta']) else float('inf'),r['transcript_id']))
    coords,cm=coordinate_build(g);members.update(cm)
    partial=source['supplement']['status']!='available' or bool(source['supplement'].get('missing_full_columns'))
    put('OV02',coords,'native Genome records, located finite island score',len(g),int(g.island_score.notna().sum()),'partial' if partial else 'available');put('OV03',{**coords,'distribution':distribution(g.delta_gc)},'native Genome records; histogram includes unlocated finite values',len(g),int(g.delta_gc.notna().sum()))
    put('CX01',mapping,'raw Core records and uniquely anchored genes',sum(len(f) for f in frames.values()))
    put('CX02',mapping,'union of Genome-anchored genes; GTP disjoint memberships',len(j))
    for cid,key in [('OV04','shift_GT'),('OV05','shift_TP'),('CX03','shift_GT'),('CX04','shift_TP')]:put(cid,{'distribution':distribution(c[key]),'robust_references':math['robust_references'],'field':key},'same three-layer N-complete gene means C',len(c))
    def density(cid,x,y,ids,population,xlabel,ylabel,condition=False,extra=None):
        h=hexbin(x,y,48);membership=h.pop('membership');h.pop('mask');h['lattice_version']='axial_hex_v1_gridsize48'
        ids=np.asarray(ids,str)
        for b in h['bins']:
            selection=f'{cid}:bin:{b["bin_id"]}';members[selection]=ids[membership==b['index']].tolist();b['selection_id']=selection
        data={'hex':h,'x_label':xlabel,'y_label':ylabel,**(extra or {})}
        good=np.isfinite(x)&np.isfinite(y);data['rho']=float(spearmanr(np.asarray(x)[good],np.asarray(y)[good]).statistic) if good.sum()>=3 and np.ptp(np.asarray(x)[good])>0 and np.ptp(np.asarray(y)[good])>0 else None
        if condition:
            groups,b=conditional(x,y);data['conditional']=groups
            for group in groups:
                selection=f'{cid}:group:{group["index"]}';members[selection]=ids[b==group['index']].tolist();group['selection_id']=selection
        put(cid,data,population,len(ids),h['n']);return data
    density('CX05',c.shift_GT.to_numpy(),c.shift_TP.to_numpy(),c.index,'same three-layer N-complete gene means C','DNA → RNA robust-z difference','RNA → Protein robust-z difference')
    put('CX06',{'quadrants':math['quadrants']},'same C, quadrant >=0 is nonnegative',len(c))
    for pattern in ['00','01','10','11']:members['CX06:'+pattern]=c.index[((c.shift_GT>=0).astype(int).astype(str)+(c.shift_TP>=0).astype(int).astype(str)).eq(pattern)].tolist()
    gx=j['genome__exon_gc_percent'].to_numpy();tx=100*j['transcriptome__gc_content'].to_numpy();mask=np.isfinite(gx)&np.isfinite(tx)
    density('CX07',gx,tx,j.index,'G–T pairwise-valid anchored gene means','Genome exon GC (%)','RNA GC (%)',extra={'distribution':distribution((tx-gx)[mask]),'identity_line':True})
    gcrows=pd.DataFrame({'gene_id':j.index,'gene_name':j.gene_name,'genome_exon_gc_percent':gx,'rna_gc_percent':tx,'gc_delta_pp':tx-gx})[mask];tables['x2_gc']=gcrows.iloc[np.argsort(-abs(gcrows.gc_delta_pp.to_numpy()),kind='stable')].to_dict('records')
    x3=[]
    for cid,key,label in [('CX08','N_atoms_per_aa','Protein N atoms/aa'),('CX09','pI','Protein pI'),('CX10','gravy','Protein GRAVY')]:
        y=j['proteome__'+key].to_numpy();d=density(cid,tx,y,j.index,'own RNA–Protein pairwise-valid anchored gene means','RNA GC (%)',label,True,{'distribution':distribution(y[np.isfinite(tx)&np.isfinite(y)])})
        groups,binids=conditional(tx,y)
        for i in np.flatnonzero(binids>=0):x3.append({'chart_id':cid,'gene_id':j.index[i],'rna_gc_percent':tx[i],'value':y[i],'conditional_bin':int(binids[i])})
    tables['x3_members']=x3
    density('CX11',exact.pi_mean.to_numpy(),exact.pi_delta.to_numpy(),exact.index,'exact transcript-paired, gene-consistent sequence-derived pI','Mean RNA ORF and Protein pI','Protein pI − RNA ORF pI',extra={'distribution':distribution(exact.pi_delta.abs()),'n_pair':len(exact),'n_valid_pi':int(exact.pi_delta.notna().sum()),'n_invalid_pi':int(exact.pi_delta.isna().sum()),'protein_records':int(exact.protein_records.sum()),'zero_delta_n':int(exact.pi_delta.eq(0).sum())})
    put('CX12',{'counts':math['outlier_disjoint_counts'],'thresholds':math['outlier_thresholds'],'eligible_n':math['outlier_eligible'],'excluded_n':len(c)-math['outlier_eligible'],'supplement':source['supplement']},'C with all three outlier metrics finite, GTP disjoint sets; 000 separate',len(c),math['outlier_eligible'],'partial' if partial else 'available')
    for pattern in math['outlier_disjoint_counts']:members['CX12:'+pattern]=c.index[c.outlier_pattern.eq(pattern)].tolist()
    edges=cross_correlations(j,fields);edges['status']=np.where(edges.rho.notna(),'available','undefined');edges['reason']=np.where(edges.pair_n<3,'pair_n_lt_3',np.where(edges.rho.isna(),'constant_pairwise_input',''));edges['method']='pairwise-complete Spearman; rerank within each pair'
    edges=edges.assign(_order=pd.to_numeric(edges.rho,errors='coerce').abs()).sort_values(['_order','feature_a','feature_b'],ascending=[False,True,True],kind='stable').drop(columns='_order');tables['x6_edges']=edges.to_dict('records')
    for cid,a,b in [('CGT','genome','transcriptome'),('CGP','genome','proteome'),('CTP','transcriptome','proteome')]:
        rows=edges[edges.feature_a.str.startswith(a+'__')&edges.feature_b.str.startswith(b+'__')].to_dict('records');matrices[cid]=rows
        put(cid,{'rows':[a+'__'+k for k in fields[a]],'columns':[b+'__'+k for k in fields[b]],'cells':rows},'all anchored gene means, each pair has its own finite population',len(rows),sum(r['status']=='available' for r in rows))
    # Representative fields come from the approved contract, including diagonal
    # and within-layer values computed by the same pairwise-complete algorithm.
    reps=FIGURES['CX13']['fields'];reps=[k for k in reps if k in j]
    if not reps:raise ValueError('representative_contract_fields_missing')
    cells=[]
    for a in reps:
        for b in reps:
            good=j[[a,b]].notna().all(axis=1) if a!=b else j[a].notna();av=j.loc[good,a];bv=j.loc[good,b];n=int(good.sum());rho=float(spearmanr(av,bv).statistic) if n>=3 and av.nunique()>1 and bv.nunique()>1 else None
            cells.append({'feature_a':a,'feature_b':b,'rho':rho,'pair_n':n,'reason':None if rho is not None else 'constant_or_insufficient'})
    put('CX13',{'rows':reps,'columns':reps,'cells':cells},'pairwise-complete anchored gene means; includes same-layer and diagonals',len(cells),sum(r['rho'] is not None for r in cells))
    put('XS04',{'distribution':distribution(edges.rho),'undefined_n':int(edges.rho.isna().sum()),'total_pairs':len(edges)},'all cross-layer field pairs, finite effects only in distribution',len(edges),int(edges.rho.notna().sum()))
    put('CX17',{'transitions':math['transitions']},'C, source-row conditional fractions of empirical resource tertiles',len(c))
    for ab in ['GT','TP']:
        cuts={m:c['z'+m].quantile([1/3,2/3]).to_numpy() for m in ab}
        strata={m:np.searchsorted(cuts[m],c['z'+m],side='right') for m in ab}
        for i in range(3):
            for k in range(3):members[f'CX17:{ab}:{i}:{k}']=c.index[(strata[ab[0]]==i)&(strata[ab[1]]==k)].tolist()
    candidate_rows=tables['candidates'];selected=[r for r in candidate_rows if r['candidate']]
    put('XS02',{'scores':[[i+1,r['candidate_score'],r['gene_id']] for i,r in enumerate(candidate_rows)],'distribution':distribution([r['candidate_score'] for r in candidate_rows]),'threshold':math['candidate_threshold'],'eligible_n':len(candidate_rows),'selected_n':len(selected)},'all genes with all three candidate evidence finite',len(c),len(candidate_rows))
    put('XS03',{'rows':selected,'threshold':math['candidate_threshold'],'eligible_n':len(candidate_rows)},'all Q95-and-ties candidates, sorted score descending then gene_id',len(candidate_rows),len(selected))
    math['island']=island_audit;source['quality']={'noncoding_records':int(numbers(g.coding_valid).ne(1).sum()),'component_n_counts':g[['composition_score','dinuc_score','codon_score']].notna().sum(axis=1).value_counts().to_dict()}
    return dict(charts=charts,profiles=profiles,metadata=metadata,tables=tables,members=members,matrices=matrices,source=source,mapping=mapping,math=math,frames=frames,ds=ds)
