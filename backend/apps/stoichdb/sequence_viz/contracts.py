from pathlib import Path
import json,itertools
CONTRACTS=json.loads(Path(__file__).with_name('figure_contracts.json').read_text(encoding='utf8'))
CATALOG=json.loads(Path(__file__).with_name('core_field_catalog.json').read_text(encoding='utf8'))
DNA=list('ACGT');RNA=list('ACGU');AA=list('ACDEFGHIKLMNPQRSTVWY')
META={m:[r['field'] for r in CATALOG if r['omics']==m and r['role']=='metadata'] for m in ['genome','transcriptome']}
CORE={m:[r['field'] for r in CATALOG if r['omics']==m and r['role']=='numeric'] for m in META}
FIGURES={r['chart_id']:r for r in CONTRACTS}
ALIASES={'gene_length_bp':'gene_span_bp','delta_gc':'delta_gc_pp','delta_entropy':'delta_entropy_bits','coding_coverage':'coding_coverage_raw','codon_entropy':'derived_codon_entropy_bits','gc3':'derived_gc3_fraction','pattern_score':'pattern_proxy_score'}
FINGERPRINT={'genome':['locus_gc_percent','exon_gc_percent','promoter_gc_percent','exon_atoms_N_per_base','exon_shannon_entropy_acgt','delta_gc_pp','gc3_percent','codon_entropy_bits'],'transcriptome':['gc_content','nt_entropy','purine_frac','atoms_per_nt_N','C_N_ratio','coding_coverage_raw','orf_len_aa','protein_gravy','protein_instability_index']}
FAMILIES={'genome':[3,3,3,1,1,1,2,2],'transcriptome':[3,3,3,2,2,2,2,2,2]}
def words(alphabet,n):return [''.join(p) for p in itertools.product(alphabet,repeat=n)]
def unit(k,m):
    explicit={'gene_span_bp':'bp','delta_gc_pp':'percentage points','delta_n':'atoms/base','delta_p':'atoms/base','delta_entropy_bits':'bits','coding_coverage_raw':'ORF nt / ACGU nt','derived_gc3_fraction':'fraction','derived_codon_entropy_bits':'bits'}
    if k in explicit:return explicit[k]
    found=next((r['unit'] for r in CATALOG if r['omics']==m and r['field']==k),None)
    if found:return found
    return 'fraction' if k.endswith(('_freq','_frac')) or k.startswith('frac_') else 'count' if k.endswith('_count') or k.startswith('n_') else 'source unit; see source catalog'
def scientific_mask(values,fields,m,n):
    import numpy as np
    if m=='genome':target=any(k in ['gc3_percent','gc1_percent','gc2_percent','codon_entropy_bits','aa_entropy_bits'] or k.startswith(('codon_','aa_','cds_')) for k in fields);return values.get('coding_valid',np.zeros(n))==1 if target else np.ones(n,bool)
    target=any(k.startswith(('orf_','protein_','aa_','codon_','derived_gc3','derived_codon')) for k in fields)
    return (values.get('aa_len',np.zeros(n))>0)&(values.get('codon_valid_codons',np.zeros(n))>0) if target else np.ones(n,bool)
