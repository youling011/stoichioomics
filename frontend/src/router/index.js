import { createRouter, createWebHistory } from 'vue-router'

const LandingView = () => import('../views/LandingView.vue')
const HomeView = () => import('../views/HomeView.vue')
const DatabaseView = () => import('../views/DatabaseView.vue')
const ReleaseView = () => import('../views/ReleaseView.vue')
const QualityView = () => import('../views/QualityView.vue')
const DownloadsView = () => import('../views/DownloadsView.vue')
const DocsView = () => import('../views/DocsView.vue')
const VisualizationHubView = () => import('../views/VisualizationHubView.vue')
const DatabaseResultsHubView = () => import('../views/DatabaseResultsHubView.vue')
const SpeciesView = () => import('../views/SpeciesView.vue')
const AnalysisHubView = () => import('../views/AnalysisHubView.vue')
const CompareView = () => import('../views/CompareView.vue')
const CaseStudiesView = () => import('../views/CaseStudiesView.vue')
const UserWorkflowsHubView = () => import('../views/UserWorkflowsHubView.vue')
const MoreHubView = () => import('../views/MoreHubView.vue')
const GuideView = () => import('../views/GuideView.vue')
const ContactView = () => import('../views/ContactView.vue')
const JobsView = () => import('../views/JobsView.vue')
const CreateJobView = () => import('../views/CreateJobView.vue')
const JobDetailView = () => import('../views/JobDetailView.vue')
const RegistryView = () => import('../views/RegistryView.vue')
const HvgCaseView = () => import('../views/HvgCaseView.vue')
const HvgCompareView = () => import('../views/HvgCompareView.vue')
const SequenceAnalysisCreateView = () => import('../views/SequenceAnalysisCreateView.vue')
const SequenceAnalysisResultView = () => import('../views/SequenceAnalysisResultView.vue')
const EntityExplorerView = () => import('../views/EntityExplorerView.vue')
const EntityReportView = () => import('../views/EntityReportView.vue')
const FeatureHubView = () => import('../views/FeatureHubView.vue')
const FeatureCatalogView = () => import('../views/FeatureCatalogView.vue')
const FeatureBrowseView = () => import('../views/FeatureBrowseView.vue')
const FeatureDatasetBuilderView = () => import('../views/FeatureDatasetBuilderView.vue')
const FeatureQcView = () => import('../views/FeatureQcView.vue')
const FeatureExportsView = () => import('../views/FeatureExportsView.vue')

const routes = [
  {
    path: '/',
    component: LandingView,
    meta: {
      title: 'Stoichioomics Gateway',
      subtitle: 'Main landing page for the stoichiometric database platform, global search, and module entry cards.',
      section: 'landing',
      noSidebar: true,
    },
  },
  {
    path: '/overview',
    component: HomeView,
    meta: {
      title: 'Stoichioomics Overview',
      subtitle: 'Overview for the multi-species genome, transcript sequence, and proteome stoichiometric feature database and its user-data extensions.',
      section: 'overview',
    },
  },
  {
    path: '/database',
    component: DatabaseView,
    meta: {
      title: 'Species Registry and Screening',
      subtitle: 'Search species, filter omics layers, inspect registry-level fingerprints, and open gene / transcript / protein explorers.',
      section: 'screening',
    },
  },
  {
    path: '/database-results',
    component: DatabaseResultsHubView,
    meta: {
      title: 'Results & Analysis Hub',
      subtitle: 'Unified internal hub for existing species data query, visualization, deep analysis, feature-table browsing, and entity reports.',
      section: 'databaseResults',
    },
  },
  {
    path: '/feature-hub',
    component: FeatureHubView,
    meta: {
      title: 'Feature Hub',
      subtitle: 'Browse Core and Full feature schemas, inspect real records, and build traceable Core matrices for machine learning.',
      section: 'features',
    },
  },
  {
    path: '/feature-hub/catalog',
    component: FeatureCatalogView,
    meta: {
      title: 'Feature Catalog',
      subtitle: 'Search all Genome, Transcriptome, and Proteome Core/Full fields with ML role and scientific semantics.',
      section: 'features',
    },
  },
  {
    path: '/feature-hub/browse',
    component: FeatureBrowseView,
    meta: {
      title: 'Feature Browser',
      subtitle: 'Preview real Core/Full records through server-side paging, field selection, and cached field profiles.',
      section: 'features',
    },
  },
  {
    path: '/feature-hub/builder',
    component: FeatureDatasetBuilderView,
    meta: {
      title: 'ML Dataset Builder',
      subtitle: 'Construct Core-only X matrices with metadata separation, QC, manifest, checksums, and preprocessing recipe.',
      section: 'features',
    },
  },
  {
    path: '/feature-hub/qc',
    component: FeatureQcView,
    meta: {
      title: 'Feature QC',
      subtitle: 'Run Core feature quality checks for missingness, constants, duplicates, composition constraints, and leakage policy.',
      section: 'features',
    },
  },
  {
    path: '/feature-hub/exports',
    component: FeatureExportsView,
    meta: {
      title: 'Feature Exports',
      subtitle: 'Inspect generated Feature Hub packages, manifest state, and download ZIP artifacts.',
      section: 'features',
    },
  },
  {
    path: '/entity-search',
    component: EntityExplorerView,
    meta: {
      title: 'Entity Explorer',
      subtitle: 'Search gene, transcript, and protein IDs, generate entity-level reports, and run batch candidate interpretation.',
      section: 'databaseResults',
    },
  },
  {
    path: '/release',
    component: ReleaseView,
    meta: {
      title: 'Release/QC and Provenance',
      subtitle: 'Inspect the active PostgreSQL release, import manifest, and provenance chain for the platform registry.',
      section: 'releaseQc',
    },
  },
  {
    path: '/quality',
    component: QualityView,
    meta: {
      title: 'Quality Control',
      subtitle: 'Review completeness, QC coverage, source-file health, and artifact readiness across the registry.',
      section: 'releaseQc',
    },
  },
  {
    path: '/downloads',
    component: DownloadsView,
    meta: {
      title: 'Downloads and Source Files',
      subtitle: 'Browse registered source feature tables, analysis artifacts, and direct download links.',
      section: 'releaseQc',
    },
  },
  {
    path: '/docs',
    component: DocsView,
    meta: {
      title: 'API and Data Dictionary',
      subtitle: 'Reference the backend endpoints, data contract, and schema-level dictionary for the platform.',
      section: 'docs',
    },
  },
  {
    path: '/visualization',
    component: VisualizationHubView,
    meta: {
      title: 'Foundational Visualization',
      subtitle: 'Feature-table driven visual summaries for genome, transcript sequence, proteome, and cross-omics patterns.',
      section: 'visualization',
    },
  },
  {
    path: '/analysis',
    component: AnalysisHubView,
    meta: {
      title: 'Deep Stoichiometric Analysis',
      subtitle: 'Artifact-centric modules for strategy typing, outliers, trade-offs, coupling networks, and omics-specific analyses.',
      section: 'analysis',
    },
  },
  {
    path: '/compare',
    component: CompareView,
    meta: {
      title: 'Multi-species Comparative View',
      subtitle: 'Compare species fingerprints, distances, omics coverage, and cross-species stoichiometric structure.',
      section: 'compare',
    },
  },
  {
    path: '/case-studies',
    component: CaseStudiesView,
    meta: {
      title: 'Stage 6 Case Studies',
      subtitle: 'Downgraded internal-data case studies for cross-species fingerprints, cross-omics coupling, and candidate protein reports.',
      section: 'databaseResults',
    },
  },
  {
    path: '/guide',
    component: GuideView,
    meta: {
      title: 'Platform Guide',
      subtitle: 'Usage flow, data contract, deployment assumptions, and notes for connecting real feature tables.',
      section: 'docs',
    },
  },
  {
    path: '/workflows',
    component: UserWorkflowsHubView,
    meta: {
      title: 'User Workflow Center',
      subtitle: 'Two user-owned workflow branches: uploaded sequence stoichiometry and Expression/HVG Stoich Extension analysis.',
      section: 'workflows',
    },
  },
  {
    path: '/more',
    component: MoreHubView,
    meta: {
      title: 'Other Platform Modules',
      subtitle: 'Release, quality control, documentation, guide, contact, and legacy workflow utilities grouped in one entry page.',
      section: 'docs',
    },
  },
  {
    path: '/contact',
    component: ContactView,
    meta: {
      title: 'Contact and Platform Scope',
      subtitle: 'Coordination notes, collaboration-facing summary, and current platform capabilities.',
      section: 'docs',
    },
  },
  {
    path: '/species/:speciesId',
    component: SpeciesView,
    props: true,
    meta: {
      title: 'Species Explorer',
      subtitle: 'Inspect species-specific basic visualization, deep analysis, feature tables, and cross-omics summaries.',
      section: 'databaseResults',
      noSidebar: true,
    },
  },
  {
    path: '/species/:speciesId/entity/:entityKey',
    component: EntityReportView,
    props: true,
    meta: {
      title: 'Entity Report',
      subtitle: 'One-stop stoichiometric report for a gene, transcript, or protein across omics evidence layers.',
      section: 'databaseResults',
    },
  },
  {
    path: '/sequence-analysis',
    component: SequenceAnalysisCreateView,
    meta: {
      title: 'Sequence Stoichiometric Analysis',
      subtitle: 'Upload FASTA sequences for single-sequence profiling, single-species multi-sample comparison, or multi-species stoichiometric comparison.',
      section: 'workflows',
    },
  },
  {
    path: '/sequence-analysis/:jobId',
    component: SequenceAnalysisResultView,
    props: true,
    meta: {
      title: 'Sequence Analysis Result',
      subtitle: 'Inspect uploaded-sequence stoichiometric features, differential features, differential genes or records, plots, and downloadable outputs.',
      section: 'workflows',
    },
  },
  {
    path: '/jobs',
    component: JobsView,
    meta: {
      title: 'User Workflow Jobs',
      subtitle: 'Manage queued, running and finished jobs, refresh job state, and open result pages.',
      section: 'workflows',
    },
  },
  {
    path: '/hvg-workflow',
    component: CreateJobView,
    meta: {
      title: 'Expression/HVG Workflow',
      subtitle: 'Create a research-contract-backed Expression/HVG Stoich Extension workspace with input QC, preflight, reproducibility, and registry promotion support.',
      section: 'workflows',
    },
  },
  {
    path: '/create',
    component: CreateJobView,
    meta: {
      title: 'Create a New Job',
      subtitle: 'Prepare a new analysis task for user data and connect it to the Expression/HVG Stoich Extension workflow branch.',
      section: 'workflows',
    },
  },
  {
    path: '/jobs/:jobId',
    component: JobDetailView,
    props: true,
    meta: {
      title: 'Job Detail',
      subtitle: 'Inspect logs, status, and output files for a selected analysis task.',
      section: 'workflows',
    },
  },
  {
    path: '/registry',
    component: RegistryView,
    meta: {
      title: 'Expression/HVG Registry',
      subtitle: 'Browse saved Expression/HVG Stoich Extension cases generated through the workflow branch.',
      section: 'workflows',
    },
  },
  {
    path: '/hvg-compare',
    component: HvgCompareView,
    meta: {
      title: 'Expression/HVG Comparative View',
      subtitle: 'Compare multiple Expression/HVG Stoich Extension cases in one interface.',
      section: 'workflows',
    },
  },
  {
    path: '/hvg/:identifier',
    component: HvgCaseView,
    props: true,
    meta: {
      title: 'Expression/HVG Case View',
      subtitle: 'Detailed view of an expression variability case linked to stoichiometric feature context.',
      section: 'workflows',
    },
  },
]

export default createRouter({ history: createWebHistory(), routes })
