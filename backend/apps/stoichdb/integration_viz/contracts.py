from pathlib import Path
import json
from . import METHOD_VERSION,SCHEMA_VERSION
MODES=['genome','transcriptome','proteome']
KEY=dict(zip(MODES,['gene_id','transcript_id','protein_id']))
CATALOG=json.loads(Path(__file__).with_name('core_field_catalog.json').read_text('utf8'))
META={m:[r['field'] for r in CATALOG if r['omics']==m and r['role']=='metadata_core'] for m in MODES}
CORE={m:[r['field'] for r in CATALOG if r['omics']==m and r['role']=='numeric_core'] for m in MODES}
FIGURES={r['api_id']:r for r in json.loads(Path(__file__).with_name('figure_contracts.json').read_text('utf8')) if r['online_form']=='independent_chart'}
COHORT_IDS={'OV01','CX14','CX15','CX16','XS01'}
FP={'genome':['exon_gc_percent','promoter_gc_percent','exon_atoms_N_per_base','codon_entropy_bits'],'transcriptome':['gc_content','nt_entropy','atoms_per_nt_N','orf_len_aa'],'proteome':['N_atoms_per_aa','S_atoms_per_aa','pI','gravy']}
DEFAULT_SPECIES=['arabidopsis_thaliana','bacillus_subtilis_gca_004328845','danio_rerio','drosophila_melanogaster','escherichia_coli_str_k_12_substr_mg1655_gca_000005845','mus_musculus_casteij','oryza_sativa','saccharomyces_cerevisiae']
EXTRA=['locus_atoms_N_per_base','locus_atoms_P_per_base','locus_shannon_entropy_acgt']
def unit(m,k):
    if m=='proteome':
        from backend.apps.stoichdb.proteome_viz.contracts import unit as u
        return u(k)
    from backend.apps.stoichdb.sequence_viz.contracts import unit as u
    return u(k,m)
