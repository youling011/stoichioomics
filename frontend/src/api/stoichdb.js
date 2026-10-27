import client from './client'

export const getPlatformHome = () => client.get('/stoichdb/home/').then(r => r.data.data)
export const getPlatformMeta = () => client.get('/stoichdb/meta/').then(r => r.data.data)
export const getFeatureCatalog = () => client.get('/stoichdb/meta/features/').then(r => r.data.data)
export const getFeatureHubOverview = () => client.get('/stoichdb/feature-hub/overview/').then(r => r.data.data)
export const getFeatureHubCatalog = (params = {}, config = {}) => client.get('/stoichdb/feature-hub/catalog/', { ...config, params }).then(r => r.data.data)
export const getFeatureHubSpecies = (params = {}, config = {}) => client.get('/stoichdb/feature-hub/species/', { ...config, params }).then(r => r.data.data)
export const getFeatureHubDataset = (speciesId, omics, params = {}, config = {}) => client.get(`/stoichdb/feature-hub/datasets/${encodeURIComponent(speciesId)}/${encodeURIComponent(omics)}/`, { ...config, params }).then(r => r.data.data)
export const getFeatureHubPreview = (params = {}, config = {}) => client.get('/stoichdb/feature-hub/preview/', { ...config, params }).then(r => r.data.data)
export const getFeatureHubHomePreview = (params = {}, config = {}) => client.get('/stoichdb/feature-hub/home-preview/', { ...config, params }).then(r => r.data.data)
export const getFeatureHubFieldProfile = (params = {}, config = {}) => client.get('/stoichdb/feature-hub/field-profile/', { ...config, params }).then(r => r.data.data)
export const runFeatureHubQc = (payload = {}, config = {}) => client.post('/stoichdb/feature-hub/qc/', payload, config).then(r => r.data.data)
export const createFeatureHubExport = (payload = {}, config = {}) => client.post('/stoichdb/feature-hub/exports/', payload, config).then(r => r.data.data)
export const getFeatureHubExport = (exportId, config = {}) => client.get(`/stoichdb/feature-hub/exports/${encodeURIComponent(exportId)}/`, config).then(r => r.data.data)
export const featureHubExportDownloadUrl = (exportId) => `/api/stoichdb/feature-hub/exports/${encodeURIComponent(exportId)}/download/`
export const getRelease = () => client.get('/stoichdb/release/').then(r => r.data.data)
export const getAnalysisHub = () => client.get('/stoichdb/analysis/hub/').then(r => r.data.data)
export const getCaseStudies = () => client.get('/stoichdb/case-studies/').then(r => r.data.data)
export const getCase1TaxonomyAdvanced = () => client.get('/stoichdb/case-studies/case1/taxonomy/').then(r => r.data.data)
export const getModel8Case1Summary = () => client.get('/stoichdb/case-studies/model8/case1/summary/').then(r => r.data.data)
export const getModel8Case1Matrix = () => client.get('/stoichdb/case-studies/model8/case1/matrix/').then(r => r.data.data)
export const getModel8Case1Pairwise = () => client.get('/stoichdb/case-studies/model8/case1/pairwise/').then(r => r.data.data)
export const getModel8Case1Sensitivity = () => client.get('/stoichdb/case-studies/model8/case1/sensitivity/').then(r => r.data.data)
export const getModel8Case2Summary = () => client.get('/stoichdb/case-studies/model8/case2/summary/').then(r => r.data.data)
export const getModel8Case2Coupling = () => client.get('/stoichdb/case-studies/model8/case2/coupling/').then(r => r.data.data)
export const getModel8Case2NullModels = () => client.get('/stoichdb/case-studies/model8/case2/null-models/').then(r => r.data.data)
export const getModel8Case2Sensitivity = () => client.get('/stoichdb/case-studies/model8/case2/sensitivity/').then(r => r.data.data)
export const getModel8Case3Summary = () => client.get('/stoichdb/case-studies/model8/case3/summary/').then(r => r.data.data)
export const getModel8Case3Candidates = () => client.get('/stoichdb/case-studies/model8/case3/candidates/').then(r => r.data.data)
export const getModel8Case3Reports = () => client.get('/stoichdb/case-studies/model8/case3/reports/').then(r => r.data.data)
export const getModel8Case3Sensitivity = () => client.get('/stoichdb/case-studies/model8/case3/sensitivity/').then(r => r.data.data)
export const getModel8Case4Summary = () => client.get('/stoichdb/case-studies/model8/case4/summary/').then(r => r.data.data)
export const getModel8Case4Gold = () => client.get('/stoichdb/case-studies/model8/case4/gold/').then(r => r.data.data)
export const getModel8Case4Workflows = () => client.get('/stoichdb/case-studies/model8/case4/workflows/').then(r => r.data.data)
export const getModel8Case4Validation = () => client.get('/stoichdb/case-studies/model8/case4/validation/').then(r => r.data.data)
export const getModel8Case4Species = (caseCode) => client.get(`/stoichdb/case-studies/model8/case4/species/${encodeURIComponent(caseCode)}/`).then(r => r.data.data)
export const getModel8Case5Summary = () => client.get('/stoichdb/case-studies/model8/case5/summary/').then(r => r.data.data)
export const getModel8Case5Phase1 = () => client.get('/stoichdb/case-studies/model8/case5/phase1/').then(r => r.data.data)
export const getModel8Case5Phase2 = () => client.get('/stoichdb/case-studies/model8/case5/phase2/').then(r => r.data.data)
export const getModel8Case5Downstream = () => client.get('/stoichdb/case-studies/model8/case5/downstream/').then(r => r.data.data)
export const getModel8Case5Species = (caseCode) => client.get(`/stoichdb/case-studies/model8/case5/species/${encodeURIComponent(caseCode)}/`).then(r => r.data.data)
export const getModel8PlatformRelease = () => client.get('/stoichdb/case-studies/model8/platform-release/').then(r => r.data.data)
export const getCase2IdMapping = () => client.get('/stoichdb/case-studies/case2/id-mapping/').then(r => r.data.data)
export const getCase2FunctionChain = () => client.get('/stoichdb/case-studies/case2/function-chain/').then(r => r.data.data)
export const getCase3FunctionEvidence = () => client.get('/stoichdb/case-studies/case3/function-evidence/').then(r => r.data.data)
export const getAnnotationStatus = (params = {}, config = {}) => client.get('/stoichdb/annotations/status/', { ...config, params }).then(r => r.data.data)
export const searchAnnotations = (params = {}, config = {}) => client.get('/stoichdb/annotations/search/', { ...config, params }).then(r => r.data.data)
export const getSpeciesFunctionalSummary = (speciesId, config = {}) => client.get(`/stoichdb/species/${encodeURIComponent(speciesId)}/functional-summary/`, config).then(r => r.data.data)
export const getSpeciesGoAnnotations = (speciesId, params = {}, config = {}) => client.get(`/stoichdb/species/${encodeURIComponent(speciesId)}/annotations/go/`, { ...config, params }).then(r => r.data.data)
export const getSpeciesKeggAnnotations = (speciesId, params = {}, config = {}) => client.get(`/stoichdb/species/${encodeURIComponent(speciesId)}/annotations/kegg/`, { ...config, params }).then(r => r.data.data)
export const getEntityFunction = (speciesId, entityKey, config = {}) => client.get(`/stoichdb/species/${encodeURIComponent(speciesId)}/entities/${encodeURIComponent(entityKey)}/function/`, config).then(r => r.data.data)
export const runFunctionalEnrichment = (payload = {}, config = {}) => client.post('/stoichdb/analysis/enrichment/', payload, config).then(r => r.data.data)
export const getQuality = () => client.get('/stoichdb/quality/').then(r => r.data.data)
export const getSpeciesQuality = (speciesId) => client.get(`/stoichdb/quality/${encodeURIComponent(speciesId)}/`).then(r => r.data.data)
export const getGuide = () => client.get('/stoichdb/guide/').then(r => r.data.data)
export const getContact = () => client.get('/stoichdb/contact/').then(r => r.data.data)
export const listSpecies = (params = {}, config = {}) => client.get('/stoichdb/species/', { ...config, params }).then(r => r.data.data)
export const getSpeciesAtlasSummary = (params = {}, config = {}) => client.get('/stoichdb/species/atlas-summary/', { ...config, params }).then(r => r.data.data)
export const getSpecies = (speciesId, params = {}, config = {}) => client.get(`/stoichdb/species/${encodeURIComponent(speciesId)}/`, { ...config, params }).then(r => r.data.data)
export const getSpeciesEnhanced = (speciesId, params = {}, config = {}) => client.get(`/stoichdb/species/${encodeURIComponent(speciesId)}/enhanced/`, { ...config, params }).then(r => r.data.data)
export const getCrossOmics = (speciesId, params = {}, config = {}) => client.get(`/stoichdb/species/${encodeURIComponent(speciesId)}/cross-omics/`, { ...config, params }).then(r => r.data.data)
export const getOmicsBundle = (speciesId, omics, params = {}, config = {}) => client.get(`/stoichdb/species/${encodeURIComponent(speciesId)}/${encodeURIComponent(omics)}/panel/`, { ...config, params }).then(r => r.data.data)
export const getOmicsSummary = (speciesId, omics, params = {}, config = {}) => client.get(`/stoichdb/species/${encodeURIComponent(speciesId)}/${encodeURIComponent(omics)}/summary/`, { ...config, params }).then(r => r.data.data)
export const getOmicsAnalysis = (speciesId, omics, params = {}, config = {}) => client.get(`/stoichdb/species/${encodeURIComponent(speciesId)}/${encodeURIComponent(omics)}/analysis/`, { ...config, params }).then(r => r.data.data)
export const getOmicsRows = (speciesId, omics, params = {}, config = {}) => client.get(`/stoichdb/species/${encodeURIComponent(speciesId)}/${encodeURIComponent(omics)}/rows/`, { ...config, params }).then(r => r.data.data)
export const getOmicsRowDetail = (speciesId, omics, entityId, params = {}, config = {}) => client.get(`/stoichdb/species/${encodeURIComponent(speciesId)}/${encodeURIComponent(omics)}/rows/${encodeURIComponent(entityId)}/`, { ...config, params }).then(r => r.data.data)
export const getOmicsFieldSummary = (speciesId, omics, params = {}, config = {}) => client.get(`/stoichdb/species/${encodeURIComponent(speciesId)}/${encodeURIComponent(omics)}/field-summary/`, { ...config, params }).then(r => r.data.data)
export const getOmicsScatter = (speciesId, omics, params = {}, config = {}) => client.get(`/stoichdb/species/${encodeURIComponent(speciesId)}/${encodeURIComponent(omics)}/scatter/`, { ...config, params }).then(r => r.data.data)
export const searchEntities = (params = {}, config = {}) => client.get('/stoichdb/entities/search/', { ...config, params }).then(r => r.data.data)
export const resolveId = (params = {}, config = {}) => client.get('/stoichdb/id-mapping/resolve/', { ...config, params }).then(r => r.data.data)
export const searchIdMappings = (params = {}, config = {}) => client.get('/stoichdb/id-mapping/search/', { ...config, params }).then(r => r.data.data)
export const batchResolveIds = (payload = {}, config = {}) => client.post('/stoichdb/id-mapping/batch-resolve/', payload, config).then(r => r.data.data)
export const getIdMappingManifest = () => client.get('/stoichdb/id-mapping/manifest/').then(r => r.data.data)
export const getSpeciesIdMappingSummary = (speciesId, config = {}) => client.get(`/stoichdb/species/${encodeURIComponent(speciesId)}/id-mapping/summary/`, config).then(r => r.data.data)
export const getSpeciesIdMappingConflicts = (speciesId, params = {}, config = {}) => client.get(`/stoichdb/species/${encodeURIComponent(speciesId)}/id-mapping/conflicts/`, { ...config, params }).then(r => r.data.data)
export const getEntityMapping = (speciesId, entityKey, config = {}) => client.get(`/stoichdb/species/${encodeURIComponent(speciesId)}/entities/${encodeURIComponent(entityKey)}/mapping/`, config).then(r => r.data.data)
export const getEntityReport = (speciesId, entityKey, params = {}, config = {}) => client.get(`/stoichdb/species/${encodeURIComponent(speciesId)}/entities/${encodeURIComponent(entityKey)}/report/`, { ...config, params }).then(r => r.data.data)
export const getEntityEvidence = (speciesId, entityKey, params = {}, config = {}) => client.get(`/stoichdb/species/${encodeURIComponent(speciesId)}/entities/${encodeURIComponent(entityKey)}/evidence/`, { ...config, params }).then(r => r.data.data)
export const getEntityChartContext = (speciesId, entityKey, params = {}, config = {}) => client.get(`/stoichdb/species/${encodeURIComponent(speciesId)}/entities/${encodeURIComponent(entityKey)}/chart-context/`, { ...config, params }).then(r => r.data.data)
export const getEntityRaw = (speciesId, entityKey, params = {}, config = {}) => client.get(`/stoichdb/species/${encodeURIComponent(speciesId)}/entities/${encodeURIComponent(entityKey)}/raw/`, { ...config, params }).then(r => r.data.data)
export const batchEntityReport = (payload = {}, config = {}) => client.post('/stoichdb/entities/batch-report/', payload, config).then(r => r.data.data)
export const compareSpecies = (speciesIds, params = {}, config = {}) =>
  client.get('/stoichdb/compare/', {
    ...config,
    params: {
      species_ids: (speciesIds || []).join(','),
      omics: params.omics || '',
      normalization: params.normalization || 'robust_zscore',
      adjustment: params.adjustment || 'none',
      distance: params.distance || 'euclidean',
      group_by: params.group_by || '',
      detail: params.detail || 'light',
    },
  }).then(r => r.data.data)
export const getDownloads = (params = {}) => client.get('/stoichdb/downloads/', { params }).then(r => r.data.data)
export const getArtifactRegistry = (params = {}) => client.get('/stoichdb/downloads/artifacts/', { params }).then(r => r.data.data)
export const materializeAnalysisArtifacts = () => client.post('/stoichdb/downloads/artifacts/materialize/').then(r => r.data.data)
export const getDocs = () => client.get('/stoichdb/docs/').then(r => r.data.data)

export const getPhylogenyReleases = () => client.get('/stoichdb/phylogeny/releases/').then(r => r.data.data)
export const getPhylogenyRelease = (releaseId = 'protist_phylogeny_v1') => client.get(`/stoichdb/phylogeny/releases/${encodeURIComponent(releaseId)}/`).then(r => r.data.data)
export const getPhylogenyTree = (releaseId = 'protist_phylogeny_v1') => client.get(`/stoichdb/phylogeny/releases/${encodeURIComponent(releaseId)}/tree/`).then(r => r.data.data)
export const getPhylogenyValidation = (releaseId = 'protist_phylogeny_v1') => client.get(`/stoichdb/phylogeny/releases/${encodeURIComponent(releaseId)}/validation/`).then(r => r.data.data)
export const runPhylogeneticSignal = (payload = {}, config = {}) => client.post('/stoichdb/phylogeny/signal/', payload, config).then(r => r.data.data)
export const runPhylogenyPgls = (payload = {}, config = {}) => client.post('/stoichdb/phylogeny/pgls/', payload, config).then(r => r.data.data)
export const getCase1Phylogeny = (params = {}, config = {}) => client.get('/stoichdb/case-studies/case1/phylogeny/', { ...config, params }).then(r => r.data.data)
export const getSpeciesPhylogenyContext = (speciesId, config = {}) => client.get(`/stoichdb/species/${encodeURIComponent(speciesId)}/phylogeny/`, config).then(r => r.data.data)

export const searchPlatform = (query, limit = 16) => client.get('/stoichdb/search/', { params: { query, limit } }).then(r => r.data.data)

export const getSpeciesFacets = () => client.get('/stoichdb/species/facets/').then(r => r.data.data)

export const featureFileDownloadUrl = (fileId) => `/api/stoichdb/downloads/files/${encodeURIComponent(fileId)}/`
export const artifactDownloadUrl = (artifactId) => `/api/stoichdb/downloads/artifacts/${encodeURIComponent(artifactId)}/`
export const model8PlatformBundleDownloadUrl = () => '/api/stoichdb/case-studies/model8/download-bundle/'
export const model8PlatformFileDownloadUrl = (relativePath) => `/api/stoichdb/case-studies/model8/download/${String(relativePath || '').split('/').map(encodeURIComponent).join('/')}`
export const idMappingDownloadUrl = (kind = 'external', speciesId = '', division = '') => `/api/stoichdb/downloads/id-mapping/?kind=${encodeURIComponent(kind)}${speciesId ? `&species_id=${encodeURIComponent(speciesId)}` : ''}${division ? `&division=${encodeURIComponent(division)}` : ''}`
export const annotationDownloadUrl = (kind) => `/api/stoichdb/downloads/annotations/${encodeURIComponent(kind)}/`

export const getHomeVisuals = (params = {}, config = {}) => client.get('/stoichdb/home/visuals/', { ...config, params }).then(r => r.data.data)
export const getSpeciesAtlasVisuals = (params = {}, config = {}) => client.get('/stoichdb/species/atlas-visuals/', { ...config, params }).then(r => r.data.data)
