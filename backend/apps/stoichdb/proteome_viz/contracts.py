from . import METHOD_VERSION

AA = list('ACDEFGHIKLMNPQRSTVWY')
META = ['species_id','protein_id','gene_id','gene_symbol','transcript_id','source_db','source_protein_id','ensembl_gene_id','ensembl_transcript_id','ensembl_protein_id','description']
GROUPS = {
 'Properties': ['length_aa','mw_da','pI','net_charge_pH7','gravy','aromaticity','instability_index','aliphatic_index','aa_entropy_bits','aa_hydrophobic_frac','aa_polar_frac','aa_pos_frac','aa_neg_frac','aa_aromatic_frac','cys_count','met_count','sulfur_aa_frac'],
 'Elements and ratios': ['C_atoms','H_atoms','N_atoms','O_atoms','S_atoms','Se_atoms','C_atoms_per_aa','N_atoms_per_aa','S_atoms_per_aa','avg_oxidation_state_C','C_N_ratio','N_S_ratio','O_C_ratio','H_C_ratio'],
 'Amino acid composition': [f'AA_{a}_pct' for a in AA]+['AA_other_pct'],
}
CORE_FIELDS = sum(GROUPS.values(), [])
FINGERPRINT = ['C_atoms_per_aa','N_atoms_per_aa','S_atoms_per_aa','pI','gravy','instability_index','aliphatic_index','aromaticity','mw_da','aa_entropy_bits','avg_oxidation_state_C']
STRUCTURE = ['ss_helix_frac','ss_turn_frac','ss_sheet_frac','flex_mean','flex_std','surface_access_em_mean','disulfide_density']
TITLES = {
 'B01':'Key descriptors: distributions in their own units', 'B02':'Complete feature quantile signature',
 'B03':'Protein length and cumulative distribution', 'B04':'Sequence quality and annotation coverage',
 'B05':'Element density and total atom budget', 'B06':'Nitrogen density distribution',
 'B07':'Isoelectric point across length strata', 'B08':'Hydropathy across length strata',
 'B09':'Twenty amino acid distributions', 'B10':'Nitrogen and sulfur relationship',
 'B11':'Secondary structure propensities', 'B12':'Carbon oxidation descriptor distribution',
 'B13':'Complete field distribution atlas', 'B14':'Field quantiles in original units',
 'B15':'Custom relationship: complete population',
 'D01':'Elemental resource space and directions', 'D02':'Nitrogen and sulfur: conditional distributions',
 'D03':'Amino acid CLR space and entropy', 'D04':'Biochemical class distributions',
 'D05':'Physicochemical quantile profile', 'D06':'Hydropathy and instability quadrants',
 'D07':'Complete protein structure proxy atlas', 'D08':'Accessibility across flexibility strata',
 'D09':'Optical and chemical descriptors across ZC strata', 'D10':'ZC and hydropathy probability contours',
 'D11':'Species fingerprint PCA and contributions', 'D12':'Species distance and feature context',
 'D13':'Within-proteome feature coupling', 'D14':'Module-native candidate evidence',
 'D15':'Candidate evidence profile', 'D16':'Observed feature dispersion across species',
}
ALIASES = {'B10':'D02'}
SECTIONS = {'basic':[f'B{i:02}' for i in range(1,16)], 'analysis':[f'D{i:02}' for i in range(1,17)]}

def unit(field):
    if field=='net_charge_pH7':return 'elementary charge'
    if field in ['aromaticity','canonical_fraction','unknown_atom_ratio','noncanonical_ratio']:return 'fraction'
    if field in ['instability_index','aliphatic_index']:return 'index'
    if field.endswith('_pct'): return '%'
    if field.endswith('_frac') or field.endswith('_ratio') or field in ['gravy','pI','avg_oxidation_state_C']: return 'dimensionless'
    if field.endswith('_per_aa'): return 'atoms / aa'
    if field.endswith('_atoms'): return 'atoms'
    if field=='mw_da': return 'Da'
    if field=='length_aa': return 'aa'
    if field.endswith('_count'): return 'residues'
    if field=='aa_entropy_bits': return 'bits'
    return 'native unit'

def catalog(fields):
    return [{'key':f,'unit':unit(f),'group':next((g for g, fs in GROUPS.items() if f in fs),'Full extensions')} for f in fields]
