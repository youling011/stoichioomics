export const PLATFORM_POSITIONING =
  'Multi-species genome, transcript sequence, and proteome sequence/molecular stoichiometric feature database and comparative analysis platform.'

export const MODULE_LAYERS = [
  {
    key: 'core',
    label: 'Core database',
    description: 'Curated species registry, genome/transcript sequence/proteome feature browsing, entity reports, visualization, analysis, and comparison.',
  },
  {
    key: 'extension',
    label: 'User data extensions',
    description: 'Uploaded sequence stoichiometry and Expression/HVG Stoich Extension workflows for user-owned runtime data.',
  },
  {
    key: 'support',
    label: 'Support and governance',
    description: 'Release, QC, downloads, API/data dictionary, guide, and contact pages that make the platform traceable and reproducible.',
  },
]

export const OMICS_TERMS = {
  genome: {
    label: 'Genome',
    description: 'Genome sequence stoichiometric features',
  },
  transcriptome: {
    label: 'Transcript sequence',
    description: 'Transcript sequence stoichiometric features, not RNA-seq expression abundance',
  },
  proteome: {
    label: 'Proteome',
    description: 'Protein sequence and molecular stoichiometric features',
  },
}

export const WORKFLOW_TERMS = {
  hvg: {
    label: 'Expression/HVG Stoich Extension',
    description: 'Expression matrix plus metadata workflow that links expression variability to stoichiometric feature context.',
  },
  mlDiagnostics: {
    label: 'Exploratory separability diagnostics',
    warning: 'Exploratory diagnostics can overfit when samples, labels, or cross-validation support are limited.',
  },
}

export function omicsLabel(key) {
  return OMICS_TERMS[key]?.label || key
}
