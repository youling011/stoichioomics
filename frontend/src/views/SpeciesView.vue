<template>
  <div v-if="!species || species.species_id !== props.speciesId" class="stack-lg">
    <ModuleState
      v-if="!speciesError"
      state="loading"
      title="Loading species payload"
      :message="speciesLoading ? 'Retrieving species metadata and the cross-omics overview.' : 'Preparing the species request.'"
    />
    <ModuleState
      v-else
      state="error"
      title="Species payload unavailable"
      :message="speciesError"
      :retry="initializeForCurrentRoute"
    />
  </div>

  <div v-else class="local-shell species-explorer-shell" :class="{'proteome-v3-shell':isScientificVisualActive || isIntegrationVisualActive}">
    <aside class="local-side">
      <div class="sidebar-section">
        <div class="sidebar-label">Species</div>
        <h3>{{ species.display_name }}</h3>
        <p>{{ species.source_context || 'Local registry dataset' }}</p>
        <div class="metric-band">
          <span class="badge">Genome {{ species.genome_size_mb }} Mb</span>
          <span class="badge">{{ species.omics_cards?.length || 0 }} omics branches</span>
        </div>
        <div class="side-nav" style="margin-top: 12px">
          <router-link class="side-nav-link" :to="`/entity-search?species_id=${encodeURIComponent(species.species_id)}`">Entity Explorer</router-link>
          <router-link class="side-nav-link" :to="species.downloads_route">Source files</router-link>
          <a v-if="species.external_source_url" class="side-nav-link" :href="species.external_source_url" target="_blank" rel="noopener noreferrer">Original source DB</a>
        </div>
      </div>

      <div class="sidebar-section">
        <div class="sidebar-label">Explorer modules</div>
        <div class="side-nav">
          <button
            class="side-nav-link"
            :class="{ active: activePanel === 'overview' }"
            @click="openOverview"
          >
            Overview
          </button>

          <button
            class="side-nav-link"
            :class="{ active: activePanel === 'cross' }"
            @click="openCross"
          >
            Cross-omics
          </button>

          <button
            v-for="card in species.omics_cards"
            :key="card.omics"
            class="side-nav-link"
            :class="{ active: activePanel === card.omics }"
            @click="openOmics(card.omics)"
          >
            {{ card.display_name }}
          </button>
        </div>
      </div>

      <div class="sidebar-section" v-if="isOmicsPanel">
        <div class="sidebar-label">Omics mode</div>
        <div class="side-nav">
          <button
            class="side-nav-link"
            :class="{ active: omicsTab === 'basic' }"
            @click="setOmicsTab('basic')"
          >
            Basic visualization
          </button>
          <button
            class="side-nav-link"
            :class="{ active: omicsTab === 'analysis' }"
            @click="setOmicsTab('analysis')"
          >
            Deep analysis
          </button>
          <button
            class="side-nav-link"
            :class="{ active: omicsTab === 'table' }"
            @click="setOmicsTab('table')"
          >
            Feature table
          </button>
        </div>
      </div>

      <div class="sidebar-section" v-if="isOmicsPanel">
        <div class="sidebar-label">Data scope</div>
        <div class="side-nav">
          <button
            class="side-nav-link"
            :class="{ active: omicsScope === 'core' }"
            @click="setOmicsScope('core')"
          >
            Core
          </button>
          <button
            class="side-nav-link"
            :class="{ active: omicsScope === 'full' }"
            @click="setOmicsScope('full')"
            :disabled="!availableScopes.includes('full')"
          >
            Full
          </button>
        </div>
      </div>

      <div class="sidebar-section" v-if="isOmicsPanel || activePanel === 'cross' || isIntegrationVisualActive">
        <div class="sidebar-label">Computation</div>
        <p v-if="isIntegrationVisualActive" class="muted">Complete Core + optional Genome Full (3 supplemental columns)</p>
        <p v-else-if="isScientificVisualActive" class="muted">Complete dataset statistics</p>
        <div v-else class="side-nav">
          <button
            class="side-nav-link"
            :class="{ active: omicsCompute === 'stored' }"
            @click="setOmicsCompute('stored')"
          >
            Fast stored view
          </button>
          <button
            class="side-nav-link"
            :class="{ active: omicsCompute === 'complete_core' }"
            @click="setOmicsCompute('complete_core')"
          >
            Complete core compute
          </button>
        </div>
      </div>
    </aside>

    <div class="local-content stack-lg">
      <section class="panel">
        <div class="section-header">
          <div>
            <div class="eyebrow">Species explorer</div>
            <h3>{{ species.display_name }}</h3>
            <p class="muted">{{ species.source_context || 'Local registry dataset' }}</p>
          </div>
          <div class="metric-band">
            <span
              class="badge"
              v-for="(value, key) in species.fingerprint"
              :key="key"
            >
              {{ formatKey(key) }}: {{ value }}
            </span>
          </div>
        </div>
      </section>

      <section v-if="species.module_coverage" class="panel species-coverage-panel">
        <div class="section-header compact">
          <div>
            <div class="eyebrow">Data readiness map</div>
            <h3>Why a module is ready, limited, or blank</h3>
            <p class="muted">This status is evaluated after loading the species payload; it is separate from the temporary request-loading indicator.</p>
          </div>
          <div class="metric-band">
            <span class="badge status-ready">{{ species.module_coverage.summary?.ready || 0 }} ready</span>
            <span class="badge status-muted">{{ species.module_coverage.summary?.limited || 0 }} limited</span>
            <span class="badge status-muted">{{ species.module_coverage.summary?.missing || 0 }} missing</span>
          </div>
        </div>
        <div class="species-coverage-grid">
          <article v-for="item in species.module_coverage.modules || []" :key="item.key" class="species-coverage-item" :class="`species-coverage-${item.state}`">
            <div class="species-coverage-item-head">
              <strong>{{ item.label }}</strong>
              <span class="species-state-badge">{{ moduleStateLabel(item.state) }}</span>
            </div>
            <p>{{ item.reason }}</p>
          </article>
        </div>
        <p v-for="note in species.module_coverage.notes || []" :key="note" class="annotation">{{ note }}</p>
      </section>

      <template v-if="activePanel === 'overview'">
        <section class="grid grid-3">
          <article class="feature-card" v-for="card in species.omics_cards" :key="card.omics">
            <div class="section-header compact">
              <div>
                <div class="eyebrow">{{ card.display_name }}</div>
                <h4>{{ card.row_count }} rows</h4>
              </div>
              <button class="btn subtle" @click="openOmics(card.omics)">Open</button>
            </div>
            <p class="muted">{{ card.description }}</p>
            <ul class="clean-list compact-list">
              <li v-for="moduleName in (card.analysis_modules || []).slice(0, 5)" :key="moduleName">
                {{ moduleName }}
              </li>
            </ul>
            <div class="metric-band" style="margin-top: 12px">
              <router-link class="ghost-link" :to="card.source_page_route">Open source files</router-link>
              <span class="badge">{{ card.feature_files?.length || 0 }} files</span>
              <span class="badge">{{ card.artifacts?.length || 0 }} artifacts</span>
            </div>
          </article>
        </section>

        <section class="panel">
          <div class="section-header compact">
            <div>
              <div class="eyebrow">ID mapping summary</div>
              <h3>Gene-transcript-protein and external ID coverage</h3>
              <p class="muted">Mapping confidence and conflict rates come from the ID Resolution Layer QC summary.</p>
            </div>
            <router-link class="btn subtle" :to="`/entity-search?species_id=${encodeURIComponent(species.species_id)}`">Search IDs</router-link>
          </div>
          <ModuleState v-if="idMappingLoading" state="loading" title="Loading ID mapping summary" message="Retrieving identifier resolution and conflict coverage." />
          <p v-else-if="idMappingError" class="annotation">{{ idMappingError }}</p>
          <template v-else-if="idMappingSummary">
            <div class="grid grid-4">
              <div class="card"><div class="label">Complete chain</div><div class="kpi">{{ formatPercentNumber(idMappingSummary.complete_chain_rate) }}</div></div>
              <div class="card"><div class="label">Conflict rate</div><div class="kpi">{{ formatPercentNumber(idMappingSummary.conflict_rate) }}</div></div>
              <div class="card"><div class="label">UniProt coverage</div><div class="kpi">{{ formatPercentNumber(idMappingSummary.uniprot_coverage) }}</div></div>
              <div class="card"><div class="label">NCBI/INSDC coverage</div><div class="kpi">{{ formatPercentNumber(idMappingSummary.ncbi_or_insdc_coverage) }}</div></div>
            </div>
            <div class="metric-band" style="margin-top: 12px">
              <span class="badge">Grade {{ idMappingSummary.grade }}</span>
              <span class="badge">Rows {{ idMappingSummary.total_rows }}</span>
              <a class="ghost-link" :href="idMappingSummary.download_links?.all_species_internal_mapping">Internal mapping CSV</a>
              <a class="ghost-link" :href="idMappingSummary.download_links?.all_species_external_mapping">External mapping CSV</a>
            </div>
          </template>
        </section>

        <section class="panel">
          <div class="section-header compact">
            <div>
              <div class="eyebrow">Functional annotation summary</div>
              <h3>GO and KEGG standard records</h3>
              <p class="muted">Unsupported species are retained as no-standard-annotation and are not predicted.</p>
            </div>
            <router-link class="btn subtle" :to="species.downloads_route">Downloads</router-link>
          </div>
          <ModuleState v-if="functionalSummaryLoading" state="loading" title="Loading functional annotation summary" message="Retrieving registered GO and KEGG evidence for this species." />
          <p v-else-if="functionalSummaryError" class="annotation">{{ functionalSummaryError }}</p>
          <template v-else-if="functionalSummary">
            <div class="grid grid-4">
              <div class="card"><div class="label">Status</div><div class="kpi small-kpi">{{ functionalSummary.status?.status }}</div></div>
              <div class="card"><div class="label">GO rows</div><div class="kpi">{{ functionalSummary.go?.row_count || 0 }}</div></div>
              <div class="card"><div class="label">GO terms</div><div class="kpi">{{ functionalSummary.go?.unique_terms || 0 }}</div></div>
              <div class="card"><div class="label">KEGG links</div><div class="kpi">{{ functionalSummary.kegg?.link_row_count || 0 }}</div></div>
            </div>
            <div class="grid grid-2 compact-top">
              <div class="table-wrap">
                <table class="table compact-table">
                  <thead><tr><th>GO</th><th>Namespace</th><th>Entities</th></tr></thead>
                  <tbody>
                    <tr v-for="term in functionalSummary.go?.top_terms || []" :key="term.go_id">
                      <td>{{ term.go_id }}</td>
                      <td>{{ term.go_namespace }}</td>
                      <td>{{ term.entity_count }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div class="table-wrap">
                <table class="table compact-table">
                  <thead><tr><th>KEGG</th><th>Type</th><th>Entities</th></tr></thead>
                  <tbody>
                    <tr v-for="term in functionalSummary.kegg?.top_annotations || []" :key="term.annotation_type + term.annotation_id">
                      <td>{{ term.annotation_id }}</td>
                      <td>{{ term.annotation_type }}</td>
                      <td>{{ term.entity_count }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </template>
        </section>

        <OverviewVisuals v-if="isIntegrationVisualActive" :context="integrationContext" :species-id="species.species_id" @entity="integrationEntity" @cross="openCross" />
        <template v-else>
        <section class="grid grid-3">
          <article class="panel">
            <div class="section-header compact">
              <div>
                <div class="eyebrow">Cross-omics availability</div>
                <h3>X0 evidence preview</h3>
              </div>
            </div>
            <div class="metric-band">
              <span class="badge">Genome {{ overviewOmicsRowCount('genome') }}</span>
              <span class="badge">Transcript sequence {{ overviewOmicsRowCount('transcriptome') }}</span>
              <span class="badge">Proteome {{ overviewOmicsRowCount('proteome') }}</span>
            </div>
            <p class="annotation">Open Cross-omics Integration for matched_all_three, evidence level, missing fields and all X0-X8 modules.</p>
            <button class="btn subtle" @click="openCross">Open Cross-omics Integration</button>
          </article>

          <article class="panel chart-panel">
            <div class="section-header compact">
              <div>
                <div class="eyebrow">Cross-omics identity preview</div>
                <h3>X7 compact fingerprint</h3>
              </div>
            </div>
            <EChart :option="overviewFingerprintChart" :height="300" empty-reason="No cross-omics fingerprint values are available for this species." />
          </article>

          <article class="panel">
            <div class="section-header compact">
              <div>
                <div class="eyebrow">Candidate preview</div>
                <h3>X8 representative entries</h3>
              </div>
            </div>
            <div class="table-wrap">
              <table class="table compact-table">
                <thead>
                  <tr>
                    <th>gene_id</th>
                    <th>DNA-&gt;RNA N std</th>
                    <th>RNA-&gt;Protein N std</th>
                    <th>pI</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="row in (species.cross_omics_preview || []).slice(0, 5)" :key="row.gene_id">
                    <td>{{ row.gene_id }}</td>
                    <td>{{ row.dna_to_rna_n_shift_std ?? row.dna_to_rna_n_delta }}</td>
                    <td>{{ row.rna_to_protein_n_shift_std ?? row.rna_to_protein_n_delta }}</td>
                    <td>{{ row.pI }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </article>
        </section>

        <section class="grid grid-2">
          <article class="panel chart-panel">
            <div class="section-header compact">
              <div>
                <div class="eyebrow">Genome coordinate atlas</div>
                <h3>Stoich-island hotspot profile</h3>
              </div>
            </div>
            <EChart :option="genomeIslandProfileChart" :height="240" empty-reason="No genome stoich-island coordinate profile is available for this species." />
            <div class="annotation">Mini preview only; open Genome Deep Analysis for the full G6 hotspot module.</div>
          </article>
          <article class="panel chart-panel">
            <div class="section-header compact">
              <div>
                <div class="eyebrow">Genome coordinate atlas</div>
                <h3>Promoter-exon delta profile</h3>
              </div>
            </div>
            <EChart :option="genomeDeltaProfileChart" :height="240" empty-reason="No promoter-exon GC delta coordinate profile is available in the imported source fields for this species." />
            <div class="annotation">Mini preview only; open Genome Basic for the full G2 regulatory contrast module.</div>
          </article>
        </section>

        <section class="panel">
          <div class="section-header compact">
            <div>
              <div class="eyebrow">Genome quick actions</div>
              <h3>Open the integrated Genome workspace</h3>
            </div>
            <div class="metric-band">
              <button class="btn subtle" @click="openOmics('genome')">Open Genome Basic</button>
              <button class="btn subtle" @click="openGenomeAnalysis">Open Genome Deep Analysis</button>
              <button class="btn subtle" @click="openCross">Cross-omics compare</button>
              <router-link class="btn subtle" :to="species.downloads_route">Source files</router-link>
            </div>
          </div>
        </section>

        <section class="panel">
          <div class="section-header compact">
            <div>
              <div class="eyebrow">Transcript sequence quick actions</div>
              <h3>Open the integrated transcript sequence workspace</h3>
              <p class="muted">T1-T8 modules are integrated as the main RNA analysis flow; legacy generic tools are kept as downstream support.</p>
            </div>
            <div class="metric-band">
              <button class="btn subtle" @click="openOmics('transcriptome')">Open transcript sequence basic</button>
              <button class="btn subtle" @click="openTranscriptomeAnalysis">Open transcript sequence deep analysis</button>
              <button class="btn subtle" @click="openCross">Cross-omics compare</button>
              <router-link class="btn subtle" :to="species.downloads_route">Source files</router-link>
            </div>
          </div>
        </section>

        <section class="panel">
          <div class="section-header compact">
            <div>
              <div class="eyebrow">Proteome quick actions</div>
              <h3>Open the integrated Proteome workspace</h3>
              <p class="muted">P1-P8 modules add protein quality, elemental resource, N/S/Se, AA composition, physicochemical, structure-proxy, redox and cross-species fingerprint views.</p>
            </div>
            <div class="metric-band">
              <button class="btn subtle" @click="openOmics('proteome')">Open Proteome Basic</button>
              <button class="btn subtle" @click="openProteomeAnalysis">Open Proteome Deep Analysis</button>
              <button class="btn subtle" @click="openCross">Cross-omics compare</button>
              <router-link class="btn subtle" :to="species.downloads_route">Source files</router-link>
            </div>
          </div>
        </section>

        <section class="grid grid-2">
          <article class="panel chart-panel">
            <div class="section-header compact">
              <div>
                <div class="eyebrow">X1 shift preview</div>
                <h3>DNA to RNA N-shift sparkline</h3>
              </div>
            </div>
            <EChart :option="dnaToRnaShiftChart" :height="220" empty-reason="No DNA-to-RNA N-shift histogram bins are available in the cross-omics preview payload." />
          </article>
          <article class="panel chart-panel">
            <div class="section-header compact">
              <div>
                <div class="eyebrow">X1 shift preview</div>
                <h3>RNA to protein N-shift sparkline</h3>
              </div>
            </div>
            <EChart :option="rnaToProteinShiftChart" :height="220" empty-reason="No RNA-to-protein N-shift histogram bins are available in the cross-omics preview payload." />
          </article>
        </section>
        </template>
      </template>

      <template v-else-if="activePanel === 'cross'">
        <CrossOmicsWorkspace v-if="isIntegrationVisualActive" :context="integrationContext" :species-id="species.species_id" @entity="integrationEntity" />
        <template v-else>

        <ModuleState
          v-if="crossLoading"
          state="loading"
          title="Loading cross-omics module"
          message="Retrieving the stored X0-X8 integration payload for this species."
        />
        <ModuleState
          v-else-if="crossError"
          state="error"
          title="Cross-omics payload unavailable"
          :message="crossError"
          :retry="() => loadCrossOmics(props.speciesId, { force: true })"
        />
        <ModuleState v-else-if="!cross" state="missing" title="Cross-omics payload unavailable" message="The request completed, but no cross-omics payload is registered for this species." />

        <template v-else>

          <section v-if="crossModuleSuite" class="panel">
            <div class="section-header compact">
              <div>
                <div class="eyebrow">Cross-omics Integration</div>
                <h3>Unified X0-X8 module suite</h3>
                <p class="muted">{{ crossModuleSuite.method_metadata?.missing_policy }}</p>
              </div>
            </div>
            <div class="metric-band">
              <span class="badge">{{ crossModuleSuite.schema_version || 'module suite' }}</span>
              <span class="badge">Rows {{ crossModuleSuite.row_count || 0 }}</span>
              <span class="badge">Matched all three {{ crossModuleSuite.matched_all_three || 0 }}</span>
              <span class="badge">Scope {{ crossModuleSuite.scope }}</span>
              <span class="badge">{{ crossModuleSuite.method_metadata?.evidence_level }}</span>
              <span class="badge">Data scope {{ crossQualityFlags.data_scope || 'cross payload' }}</span>
            </div>
            <div class="grid grid-4" style="margin-top: 12px">
              <article class="feature-card" v-for="module in crossModuleCards" :key="module.id">
                <div class="section-header compact">
                  <div>
                    <div class="eyebrow">{{ module.id }}</div>
                    <h4>{{ module.name }}</h4>
                  </div>
                </div>
                <div class="metric-band">
                  <span class="badge">{{ module.status }}</span>
                  <span class="badge">{{ module.missing_count }} gaps</span>
                </div>
              </article>
            </div>
          </section>

          <ResultBlock
            v-if="crossModuleSuite"
            title="X0 Cross-omics data foundation"
            question="Are genome, transcript sequence, and proteome records sufficiently mapped for downstream X1-X8 interpretation?"
            :finding="crossX0Finding"
            :method="crossModuleMethod('X0')"
            normalization="raw row counts"
            missing-policy="coverage is reported before downstream filtering"
            :n="crossModuleSuite.matched_all_three || 0"
            caveat="Mapping coverage and conflict counts are interpretation preconditions. Low coverage or unresolved ID conflicts should be checked before reading cross-layer shifts."
            :downloads="crossX0Downloads"
          >
            <div class="metric-band">
              <span class="badge">All-three coverage {{ formatPercent(crossMappingCoverage.all_three) }}</span>
              <span class="badge">G-T coverage {{ formatPercent(crossMappingCoverage.genome_transcriptome) }}</span>
              <span class="badge">T-P coverage {{ formatPercent(crossMappingCoverage.transcriptome_proteome) }}</span>
              <span class="badge">Conflicts {{ crossMappingSummary.conflict_count || 0 }}</span>
              <span class="badge">Multi-transcript genes {{ crossMappingSummary.multi_mapping?.multi_transcript_gene_count || 0 }}</span>
            </div>
            <div class="grid grid-2" style="margin-top: 12px">
              <div class="chart-panel">
                <div class="section-header compact"><h3>X0 matched rows</h3></div>
                <EChart :option="crossX0CoverageChart" :height="320" empty-reason="No matched-row coverage values are available in the cross-omics payload." />
              </div>
              <div class="chart-panel">
                <div class="section-header compact"><h3>X0 match rates</h3></div>
                <EChart :option="crossX0RateChart" :height="320" empty-reason="No match-rate values are available in the cross-omics payload." />
              </div>
            </div>
          </ResultBlock>

          <section v-if="crossModuleSuite" class="panel">
            <div class="section-header compact">
              <div>
                <div class="eyebrow">B. Basic cross-layer relationships</div>
                <h3>X1-X3 resource shift, regulatory coupling and translation strategy</h3>
              </div>
            </div>
          </section>

          <section v-if="crossModuleSuite" class="grid grid-2">
            <article class="panel chart-panel">
              <div class="section-header compact"><h3>X1 DNA to RNA shift</h3></div>
              <EChart :option="crossX1DnaRnaChart" :height="300" />
            </article>
            <article class="panel chart-panel">
              <div class="section-header compact"><h3>X1 RNA to protein shift</h3></div>
              <EChart :option="crossX1RnaProteinChart" :height="300" />
            </article>
          </section>

          <section v-if="crossModuleSuite" class="grid grid-2">
            <article class="panel chart-panel">
              <div class="section-header compact"><h3>X1 paired shift map</h3></div>
              <EChart :option="crossX1ScatterChart" :height="360" />
              <MethodBadge
                :method="crossModuleMethod('X1')"
                normalization="raw directional shift proxies"
                missing-policy="matched rows with DNA/RNA/protein N fields only"
                :n="crossModule('X1').shift_scatter?.length || 0"
                exploratory
              />
            </article>
            <article class="panel chart-panel">
              <div class="section-header compact"><h3>X1 direction classes</h3></div>
              <EChart :option="crossX1QuadrantChart" :height="360" />
            </article>
          </section>

          <section v-if="crossModuleSuite" class="panel">
            <div class="section-header compact">
              <h3>X1 top shift candidates</h3>
              <button class="btn subtle" @click="exportCrossModuleTable('x1_resource_shift_candidates')" :disabled="!crossX1CandidateRows.length">Download CSV</button>
            </div>
            <div class="table-wrap">
              <table class="table compact-table">
                <thead>
                  <tr>
                    <th>gene_id</th>
                    <th>gene_name</th>
                    <th>DNA-&gt;RNA std</th>
                    <th>RNA-&gt;Protein std</th>
                    <th>driver</th>
                    <th>scope</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="row in crossX1CandidateRows.slice(0, 14)" :key="row.gene_id || row.canonical_gene_id">
                    <td>{{ row.gene_id || row.canonical_gene_id }}</td>
                    <td>{{ row.gene_name }}</td>
                    <td>{{ row.dna_to_rna_n_shift_std }}</td>
                    <td>{{ row.rna_to_protein_n_shift_std }}</td>
                    <td>{{ row.main_driver || row.direction_class }}</td>
                    <td>{{ row.data_scope || 'top_transformations' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <section v-if="crossModuleSuite" class="grid grid-2">
            <article class="panel chart-panel">
              <div class="section-header compact"><h3>X2 exon-transcript GC coupling</h3></div>
              <EChart :option="crossX2ScatterChart" :height="360" empty-reason="X2 primary exon/transcript GC fields are absent and no fallback residual candidate rows are available." />
              <div class="annotation">{{ crossModuleMethod('X2') }}</div>
            </article>
            <article class="panel">
              <div class="section-header compact">
                <h3>X2 high residual candidates</h3>
                <button class="btn subtle" @click="exportCrossModuleTable('x2_residual_candidates')" :disabled="!(crossModule('X2').residual_candidates || []).length">Download CSV</button>
              </div>
              <div class="table-wrap">
                <table class="table compact-table">
                  <thead>
                    <tr>
                      <th>gene_id</th>
                      <th>gene_name</th>
                      <th>DNA-&gt;RNA GC</th>
                      <th>RNA-&gt;Protein N std</th>
                      <th>discordance</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="row in (crossModule('X2').residual_candidates || []).slice(0, 14)" :key="row.gene_id || row.canonical_gene_id">
                      <td>{{ row.gene_id || row.canonical_gene_id }}</td>
                      <td>{{ row.gene_name }}</td>
                      <td>{{ row.exon_rna_gc_delta ?? row.dna_to_rna_gc_delta }}</td>
                      <td>{{ row.rna_to_protein_n_shift_std }}</td>
                      <td>{{ row.discordance_score }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </article>
          </section>

          <section v-if="crossModuleSuite" class="grid grid-3">
            <article class="panel chart-panel">
              <div class="section-header compact"><h3>X3 RNA GC vs protein N</h3></div>
              <EChart :option="crossX3GcProteinNChart" :height="320" empty-reason="X3 primary RNA-GC/protein-N fields are absent and no fallback discordance rows are available." />
            </article>
            <article class="panel chart-panel">
              <div class="section-header compact"><h3>X3 RNA GC vs pI</h3></div>
              <EChart :option="crossX3GcPiChart" :height="320" empty-reason="X3 primary RNA-GC/pI fields are absent and no fallback discordance rows are available." />
            </article>
            <article class="panel chart-panel">
              <div class="section-header compact"><h3>X3 RNA GC vs GRAVY</h3></div>
              <EChart :option="crossX3GcGravyChart" :height="320" empty-reason="X3 primary RNA-GC/GRAVY fields are absent and no fallback discordance rows are available." />
            </article>
          </section>

          <section v-if="crossModuleSuite" class="panel">
            <div class="section-header compact">
              <div>
                <div class="eyebrow">C. Deep mechanism modules</div>
                <h3>X4-X6 predicted/observed residuals, island propagation and coupling network</h3>
              </div>
            </div>
          </section>

          <section v-if="crossModuleSuite" class="grid grid-2">
            <article class="panel">
              <div class="section-header compact">
                <h3>X4 predicted/observed proteome status</h3>
              </div>
              <p class="muted">{{ crossModuleMethod('X4') }}</p>
              <div class="metric-band">
                <span class="badge">{{ crossModule('X4').status || 'partial' }}</span>
                <span class="badge">{{ (crossModule('X4').missing_fields || []).length }} required fields missing</span>
                <span class="badge">{{ crossX4CandidateRows.length }} residual candidates</span>
              </div>
              <EChart :option="crossX4PiResidualChart" :height="300" empty-reason="X4 predicted/observed proteome residual data are not available for this species." />
              <div class="mini-table-wrap" v-if="crossX4CandidateRows.length">
                <table class="mini-table">
                  <thead>
                    <tr>
                      <th>Gene</th>
                      <th>Transcript</th>
                      <th>Protein</th>
                      <th>pI residual</th>
                      <th>GRAVY residual</th>
                      <th>score</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="row in crossX4CandidateRows.slice(0, 12)" :key="row.gene_id || row.canonical_gene_id">
                      <td>{{ row.gene_id || row.canonical_gene_id }}</td>
                      <td>{{ row.transcript_id }}</td>
                      <td>{{ row.protein_id }}</td>
                      <td>{{ row.protein_pi_residual }}</td>
                      <td>{{ row.protein_gravy_residual }}</td>
                      <td>{{ row.candidate_score }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </article>
            <article class="panel chart-panel">
              <div class="section-header compact"><h3>X5 shared outlier propagation</h3></div>
              <EChart :option="crossX5SharedChart" :height="320" />
              <div class="annotation">{{ crossModuleMethod('X5') }}</div>
            </article>
          </section>

          <section v-if="crossModuleSuite" class="panel">
            <div class="section-header compact">
              <div>
                <div class="eyebrow">D. Species-level atlas</div>
                <h3>X7 cross-omics fingerprint atlas</h3>
              </div>
            </div>
          </section>

          <section v-if="crossModuleSuite" class="grid grid-2">
            <article class="panel chart-panel">
              <div class="section-header compact"><h3>X6 coupling heatmap</h3></div>
              <EChart :option="crossX6HeatmapChart" :height="420" />
              <MethodBadge
                :method="crossModuleMethod('X6')"
                normalization="pairwise complete matched features"
                missing-policy="features without enough matched values are omitted"
                :n="crossJoinSummary.matched_all_three || 0"
                exploratory
              />
            </article>
            <article class="panel">
              <div class="section-header compact">
                <h3>X6 top coupling edges</h3>
                <button class="btn subtle" @click="exportCrossModuleTable('x6_edge_ranking')" :disabled="!crossX6EdgeRows.length">Download CSV</button>
              </div>
              <div class="table-wrap">
                <table class="table compact-table">
                  <thead>
                    <tr>
                      <th>feature A</th>
                      <th>feature B</th>
                      <th>r</th>
                      <th>n</th>
                      <th>p</th>
                      <th>FDR</th>
                      <th>method</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="row in crossX6EdgeRows.slice(0, 14)" :key="`${row.feature_a}-${row.feature_b}`">
                      <td>{{ row.feature_a }}</td>
                      <td>{{ row.feature_b }}</td>
                      <td>{{ row.r }}</td>
                      <td>{{ row.n }}</td>
                      <td>{{ row.p_value }}</td>
                      <td>{{ row.fdr }}</td>
                      <td>{{ row.method }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </article>
          </section>

          <section v-if="crossModuleSuite" class="grid grid-2">
            <article class="panel chart-panel">
              <div class="section-header compact"><h3>X7 current species fingerprint</h3></div>
              <EChart :option="crossX7FingerprintChart" :height="360" />
            </article>
            <article class="panel chart-panel">
              <div class="section-header compact">
                <h3>X7 species ordination</h3>
                <select class="input select-inline" v-model="crossEmbeddingMode">
                  <option value="umap">UMAP</option>
                  <option value="pca">PCA</option>
                </select>
              </div>
              <EChart :option="crossX7SpeciesChart" :height="360" />
              <div class="annotation">{{ crossProjectionAnnotation(crossModule('X7').species_pca || {}) }}</div>
            </article>
          </section>

          <section v-if="crossModuleSuite" class="grid grid-2">
            <article class="panel chart-panel">
              <div class="section-header compact"><h3>X7 fingerprint distance matrix</h3></div>
              <EChart :option="crossX7DistanceChart" :height="420" />
            </article>
            <article class="panel">
              <div class="section-header compact">
                <h3>X7 feature ranking</h3>
                <button class="btn subtle" @click="exportCrossModuleTable('x7_feature_ranking')" :disabled="!crossX7FeatureRows.length">Download CSV</button>
              </div>
              <div class="table-wrap">
                <table class="table compact-table">
                  <thead>
                    <tr>
                      <th>feature</th>
                      <th>mean</th>
                      <th>std</th>
                      <th>range</th>
                      <th>n</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="row in crossX7FeatureRows.slice(0, 14)" :key="row.feature">
                      <td>{{ row.feature }}</td>
                      <td>{{ row.mean }}</td>
                      <td>{{ row.std }}</td>
                      <td>{{ row.range }}</td>
                      <td>{{ row.n_species }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </article>
          </section>

          <section v-if="crossModuleSuite" class="panel">
            <div class="section-header compact">
              <div>
                <div class="eyebrow">E. Candidate workbench and export</div>
                <h3>X8 integrated candidate table</h3>
              </div>
            </div>
          </section>

          <section v-if="crossModuleSuite" class="panel">
            <div class="section-header compact">
              <h3>X8 candidate workbench</h3>
              <button class="btn subtle" @click="exportCrossModuleTable('x8_candidate_workbench')" :disabled="!crossX8CandidateRows.length">Download CSV</button>
            </div>
            <div class="table-wrap">
              <table class="table compact-table">
                <thead>
                  <tr>
                    <th>gene_id</th>
                    <th>gene_name</th>
                    <th>candidate score</th>
                    <th>resource shift</th>
                    <th>discordance</th>
                    <th>class</th>
                    <th>source</th>
                    <th>scope</th>
                    <th>evidence</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="row in crossX8CandidateRows.slice(0, 24)" :key="`${row.gene_id}-${row.candidate_class || row.direction_class}`">
                    <td>{{ row.gene_id || row.canonical_gene_id }}</td>
                    <td>{{ row.gene_name }}</td>
                    <td>{{ row.candidate_score }}</td>
                    <td>{{ row.resource_shift_score }}</td>
                    <td>{{ row.discordance_score }}</td>
                    <td>{{ row.candidate_class || row.direction_class }}</td>
                    <td>{{ Array.isArray(row.source_modules) ? row.source_modules.join('; ') : row.source_modules }}</td>
                    <td>{{ row.data_scope }}</td>
                    <td>{{ row.evidence_level }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <section v-if="transitionProbabilityLinks.length" class="panel chart-panel">
            <div class="section-header compact">
              <div>
                <div class="eyebrow">X8 auxiliary</div>
                <h3>Strategy transition context</h3>
              </div>
            </div>
            <EChart :option="clusterTransitionChart" :height="360" />
            <MethodBadge
              method="source-normalized transition probability"
              normalization="percent of outgoing source links"
              missing-policy="matched entities with transition links only"
              :n="enhancedVisuals.paired_gene_count || 0"
              exploratory
              note="Auxiliary context only; X8 candidate ranking is driven by resource shift, discordance and shared outlier evidence."
            />
          </section>

          <section v-if="crossImplementationNotes.length" class="panel">
            <div class="section-header compact"><h3>X0-X8 implementation notes</h3></div>
            <div class="table-wrap">
              <table class="table compact-table">
                <thead>
                  <tr>
                    <th>module</th>
                    <th>status</th>
                    <th>remaining data / artifact</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="row in crossImplementationNotes" :key="`${row.module}-${row.missing}`">
                    <td>{{ row.module }}</td>
                    <td>{{ row.status }}</td>
                    <td>{{ row.missing }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>
        </template>
        </template>
      </template>

      <template v-else-if="isOmicsPanel">
        <ProteomeWorkspace v-if="isProteomeV3Active && omicsTab !== 'table'" :species-id="species.species_id" :scope="omicsScope" :section="omicsTab" @manifest="acceptProteomeManifest" />
        <SequenceWorkspace v-else-if="isSequenceV1Active && omicsTab !== 'table'" :key="activePanel + omicsScope" :species-id="species.species_id" :omics="activePanel" :scope="omicsScope" :section="omicsTab === 'analysis' ? 'deep' : omicsTab" @manifest="acceptSequenceManifest" />
        <ModuleState v-else-if="omicsLoading" state="loading" :title="`Loading ${activePanel} module`" message="Retrieving the summary, analysis payload, and available data scopes." />

        <ModuleState
          v-else-if="omicsError"
          state="error"
          :title="`${activePanel} module unavailable`"
          :message="omicsError"
          :retry="() => loadOmics(activePanel, { force: true })"
        />

        <template v-else-if="omicsSummary && omicsAnalysis">
          <section class="panel">
            <div class="section-header">
              <div>
                <div class="eyebrow">{{ activePanel }}</div>
                <h3>{{ omicsSummary.display_name }}</h3>
                <p class="muted">{{ omicsSummary.description }}</p>
                <div class="metric-band" style="margin-top: 12px">
                  <router-link class="ghost-link" :to="currentOmicsCard?.source_page_route || species.downloads_route">Open source files</router-link>
                  <a v-if="species.external_source_url" class="ghost-link" :href="species.external_source_url" target="_blank" rel="noopener noreferrer">Original source DB</a>
                </div>
              </div>
              <div class="metric-band">
                <span class="badge">Scope: {{ omicsScope }}</span>
                <span class="badge">{{ omicsComputeLabel }}</span>
                <span class="badge" v-for="item in omicsSummary.kpis || []" :key="item.label">
                  {{ item.label }}: {{ item.value }}
                </span>
              </div>
            </div>
          </section>

          <template v-if="omicsTab === 'basic'">
            <ModuleState
              v-if="currentOmicsModuleSuiteState === 'missing'"
              state="missing"
              :title="`${currentOmicsLabel} chart payload is not registered`"
              :message="currentOmicsModuleSuiteMissingMessage"
              suggestion="The request has completed. This is a true missing-data state, not a loading state."
            />

            <section v-if="activePanel === 'genome' && genomeModuleSuite" class="panel">
              <div class="section-header">
                <div>
                  <div class="eyebrow">Genome basic</div>
                  <h3>Data status & evidence</h3>
                  <p class="muted">{{ genomeEvidenceBanner }}</p>
                </div>
                <div class="metric-band">
                  <span class="badge">Rows: {{ genomeModuleSuite.row_count }}</span>
                  <span class="badge">Scope: {{ genomeModuleSuite.scope }}</span>
                  <span class="badge" v-if="genomeModuleSuite.requested_scope">Requested: {{ genomeModuleSuite.requested_scope }}</span>
                </div>
              </div>
              <div class="grid grid-4 dense-grid">
                <div class="mini-card" v-for="module in genomeModules" :key="module.id">
                  <div class="label">{{ module.id }}</div>
                  <div class="metric-inline">{{ module.status }}</div>
                  <p class="muted" style="margin: 8px 0 0">{{ module.name }}</p>
                </div>
              </div>
            </section>

            <section v-if="activePanel === 'genome' && genomeModuleSuite" class="grid grid-2">
              <article class="panel chart-panel">
                <div class="section-header compact"><h3>Genome key feature summary</h3></div>
                <EChart :option="genomeKeyFeatureChart" :height="330" />
                <div class="annotation">Merged from previous KPI cards and current-species G8 fingerprint; detailed topic-specific figures are placed in G1/G2/G5/G7.</div>
              </article>

              <article class="panel chart-panel">
                <div class="section-header compact"><h3>Current species genome fingerprint</h3></div>
                <EChart :option="genomeG8FingerprintChart" :height="330" />
                <div class="annotation">{{ genomeModuleMethod('G8') }}</div>
              </article>
            </section>

            <section v-if="activePanel === 'genome' && genomeModuleSuite" class="grid grid-2">
              <article class="panel chart-panel" id="g1-composition">
                <div class="section-header compact"><h3>G1 Composition & stoichiometric profile</h3></div>
                <EChart :option="genomeG1RegionChart" :height="330" />
                <div class="annotation">{{ genomeModuleMethod('G1') }}</div>
              </article>

              <article class="panel chart-panel" id="g2-regulatory-contrast">
                <div class="section-header compact"><h3>G2 Promoter-gene body contrast</h3></div>
                <EChart :option="genomeG2DeltaChart" :height="330" />
                <div class="annotation">{{ genomeG2FieldSummary }}</div>
              </article>
            </section>

            <section v-if="activePanel === 'genome' && genomeModuleSuite" class="grid grid-2">
              <article class="panel chart-panel">
                <div class="section-header compact"><h3>G2 Promoter vs exon GC</h3></div>
                <EChart :option="genomeG2ScatterChart" :height="340" />
              </article>

              <article class="panel">
                <div class="section-header compact">
                  <h3>G2 Top delta genes</h3>
                  <button class="btn subtle" @click="exportGenomeTable('g2_top_delta')" :disabled="!genomeG2TopDeltaRows.length">Download CSV</button>
                </div>
                <div class="table-wrap">
                  <table class="table compact-table">
                    <thead><tr><th>Direction</th><th>Gene</th><th>Delta</th><th>Location</th></tr></thead>
                    <tbody>
                      <tr v-for="row in genomeG2TopDeltaRows" :key="`${row.direction}-${row.entity_id}`">
                        <td>{{ row.direction }}</td>
                        <td>{{ row.gene_name || row.gene_id || row.entity_id }}</td>
                        <td>{{ row.value }}</td>
                        <td>{{ row.seqid }}:{{ row.start_1 }}-{{ row.end_1 }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </article>
            </section>

            <section v-if="activePanel === 'genome' && genomeModuleSuite" class="grid grid-2">
              <article class="panel chart-panel" id="g7-architecture">
                <div class="section-header compact"><h3>G7 Genome architecture context</h3></div>
                <EChart :option="genomeG7BiotypeChart" :height="330" />
                <div class="annotation">{{ genomeModuleMethod('G7') }}</div>
              </article>

              <article class="panel chart-panel">
                <div class="section-header compact"><h3>G7 Length vs exon GC</h3></div>
                <EChart :option="genomeG7LengthScatter" :height="330" />
              </article>
            </section>

            <section v-if="activePanel === 'transcriptome' && transcriptomeModuleSuite" class="panel">
              <div class="section-header">
                <div>
                  <div class="eyebrow">Transcript sequence basic</div>
                  <h3>Data status & evidence</h3>
                  <p class="muted">{{ transcriptomeEvidenceBanner }}</p>
                </div>
                <div class="metric-band">
                  <span class="badge">Rows: {{ transcriptomeModuleSuite.row_count }}</span>
                  <span class="badge">Coding rows: {{ transcriptomeModuleSuite.coding_row_count }}</span>
                  <span class="badge">Scope: {{ transcriptomeModuleSuite.scope }}</span>
                </div>
              </div>
              <div class="grid grid-4 dense-grid">
                <div class="mini-card" v-for="module in transcriptomeModules" :key="module.id">
                  <div class="label">{{ module.id }}</div>
                  <div class="metric-inline">{{ module.status }}</div>
                  <p class="muted" style="margin: 8px 0 0">{{ module.name }}</p>
                </div>
              </div>
            </section>

            <section v-if="activePanel === 'transcriptome' && transcriptomeModuleSuite" class="grid grid-2">
              <article class="panel chart-panel">
                <div class="section-header compact"><h3>Transcript sequence key feature summary</h3></div>
                <EChart :option="transcriptomeKeyFeatureChart" :height="320" />
                <div class="annotation">Merged T1/T2/T5 overview for RNA composition, elemental cost and ORF validity.</div>
              </article>

              <article class="panel chart-panel" id="t8-fingerprint">
                <div class="section-header compact"><h3>Current species transcript sequence fingerprint</h3></div>
                <EChart :option="transcriptomeT8FingerprintChart" :height="320" />
                <div class="annotation">{{ transcriptomeModuleMethod('T8') }}</div>
              </article>
            </section>

            <section v-if="activePanel === 'transcriptome' && transcriptomeModuleSuite" class="grid grid-2">
              <article class="panel chart-panel" id="t1-composition">
                <div class="section-header compact"><h3>T1 RNA composition overview</h3></div>
                <EChart :option="transcriptomeT1BaseChart" :height="320" />
                <div class="annotation">{{ transcriptomeModuleMethod('T1') }}</div>
              </article>

              <article class="panel chart-panel">
                <div class="section-header compact"><h3>T1 GC content distribution</h3></div>
                <EChart :option="transcriptomeT1GcChart" :height="320" />
              </article>
            </section>

            <section v-if="activePanel === 'transcriptome' && transcriptomeModuleSuite" class="grid grid-2">
              <article class="panel chart-panel" id="t2-elemental">
                <div class="section-header compact"><h3>T2 RNA elemental budget</h3></div>
                <EChart :option="transcriptomeT2ElementChart" :height="320" />
                <div class="annotation">{{ transcriptomeModuleMethod('T2') }}</div>
              </article>

              <article class="panel chart-panel">
                <div class="section-header compact"><h3>T2 N/P ratio distribution</h3></div>
                <EChart :option="transcriptomeT2NpChart" :height="320" />
              </article>
            </section>

            <section v-if="activePanel === 'transcriptome' && transcriptomeModuleSuite" class="grid grid-2">
              <article class="panel chart-panel" id="t4-biotype">
                <div class="section-header compact"><h3>T4 Transcript biotype context</h3></div>
                <EChart :option="transcriptomeT4BiotypeChart" :height="320" />
                <div class="annotation">{{ transcriptomeModuleMethod('T4') }}</div>
              </article>

              <article class="panel chart-panel">
                <div class="section-header compact"><h3>T4 Length by biotype</h3></div>
                <EChart :option="transcriptomeT4LengthByBiotypeChart" :height="320" />
              </article>
            </section>

            <section v-if="activePanel === 'transcriptome' && transcriptomeModuleSuite" class="grid grid-2">
              <article class="panel chart-panel" id="t5-orf">
                <div class="section-header compact"><h3>T5 ORF length distribution</h3></div>
                <EChart :option="transcriptomeT5OrfLengthChart" :height="320" />
                <div class="annotation">{{ transcriptomeModuleMethod('T5') }}</div>
              </article>

              <article class="panel chart-panel" id="t7-protein-preview">
                <div class="section-header compact"><h3>T7 Derived protein-like AA preview</h3></div>
                <EChart :option="transcriptomeT7AaChart" :height="320" />
                <div class="annotation">{{ transcriptomeModuleMethod('T7') }}</div>
              </article>
            </section>

            <section v-if="activePanel === 'proteome' && proteomeModuleSuite" class="panel">
              <div class="section-header">
                <div>
                  <div class="eyebrow">Proteome basic</div>
                  <h3>Data status & evidence</h3>
                  <p class="muted">{{ proteomeEvidenceBanner }}</p>
                </div>
                <div class="metric-band">
                  <span class="badge">Rows: {{ proteomeModuleSuite.row_count }}</span>
                  <span class="badge">Scope: {{ proteomeModuleSuite.scope }}</span>
                </div>
              </div>
              <div class="grid grid-4 dense-grid">
                <div class="mini-card" v-for="module in proteomeModules" :key="module.id">
                  <div class="label">{{ module.id }}</div>
                  <div class="metric-inline">{{ module.status }}</div>
                  <p class="muted" style="margin: 8px 0 0">{{ module.name }}</p>
                </div>
              </div>
            </section>

            <section v-if="activePanel === 'proteome' && proteomeModuleSuite" class="grid grid-2">
              <article class="panel chart-panel">
                <div class="section-header compact"><h3>Proteome key feature summary</h3></div>
                <EChart :option="proteomeKeyFeatureChart" :height="320" />
                <div class="annotation">Merged P2/P3/P5/P7 overview for protein resource cost, physicochemical state and redox proxy.</div>
              </article>

              <article class="panel chart-panel" id="p8-fingerprint">
                <div class="section-header compact"><h3>Current species proteome fingerprint</h3></div>
                <EChart :option="proteomeP8FingerprintChart" :height="320" />
                <div class="annotation">{{ proteomeModuleMethod('P8') }}</div>
              </article>
            </section>

            <section v-if="activePanel === 'proteome' && proteomeModuleSuite" class="grid grid-2">
              <article class="panel chart-panel" id="p1-quality">
                <div class="section-header compact"><h3>P1 Protein length distribution</h3></div>
                <EChart :option="proteomeP1LengthChart" :height="320" />
                <div class="annotation">{{ proteomeModuleMethod('P1') }}</div>
              </article>

              <article class="panel chart-panel">
                <div class="section-header compact"><h3>P1 Sequence quality levels</h3></div>
                <EChart :option="proteomeP1QualityChart" :height="320" />
              </article>
            </section>

            <section v-if="activePanel === 'proteome' && proteomeModuleSuite" class="grid grid-2">
              <article class="panel chart-panel" id="p2-resource">
                <div class="section-header compact"><h3>P2 Elemental resource budget</h3></div>
                <EChart :option="proteomeP2ElementChart" :height="320" />
                <div class="annotation">{{ proteomeModuleMethod('P2') }}</div>
              </article>

              <article class="panel chart-panel">
                <div class="section-header compact"><h3>P2 Nitrogen distribution</h3></div>
                <EChart :option="proteomeP2NChart" :height="320" />
              </article>
            </section>

            <section v-if="activePanel === 'proteome' && proteomeModuleSuite" class="grid grid-2">
              <article class="panel chart-panel" id="p5-physchem">
                <div class="section-header compact"><h3>P5 pI distribution</h3></div>
                <EChart :option="proteomeP5PiChart" :height="320" />
                <div class="annotation">{{ proteomeModuleMethod('P5') }}</div>
              </article>

              <article class="panel chart-panel">
                <div class="section-header compact"><h3>P5 GRAVY distribution</h3></div>
                <EChart :option="proteomeP5GravyChart" :height="320" />
              </article>
            </section>

            <section v-if="activePanel === 'proteome' && proteomeModuleSuite" class="grid grid-2">
              <article class="panel chart-panel" id="p4-aa">
                <div class="section-header compact"><h3>P4 20AA composition atlas</h3></div>
                <EChart :option="proteomeP4AaChart" :height="320" />
                <div class="annotation">{{ proteomeModuleMethod('P4') }}</div>
              </article>

              <article class="panel chart-panel" id="p3-ns-se">
                <div class="section-header compact"><h3>P3 N/S economy scatter</h3></div>
                <EChart :option="proteomeP3NsScatter" :height="320" />
                <div class="annotation">{{ proteomeModuleMethod('P3') }}</div>
              </article>
            </section>

            <section v-if="activePanel === 'proteome' && proteomeModuleSuite" class="grid grid-2">
              <article class="panel chart-panel" id="p6-structure">
                <div class="section-header compact"><h3>P6 Secondary structure proxy</h3></div>
                <EChart :option="proteomeP6StructureChart" :height="320" />
                <div class="annotation">{{ proteomeModuleMethod('P6') }}</div>
              </article>

              <article class="panel chart-panel" id="p7-redox">
                <div class="section-header compact"><h3>P7 ZC distribution</h3></div>
                <EChart :option="proteomeP7ZcChart" :height="320" />
                <div class="annotation">{{ proteomeModuleMethod('P7') }}</div>
              </article>
            </section>

            <section v-if="activePanel === 'proteome' && proteomeModuleSuite" class="panel">
              <div class="section-header compact">
                <div>
                  <h3>Proteome candidate dashboard</h3>
                  <p class="muted">Candidate proteins merged from P2 resource outliers, P3 N/S/Se economy, P4 AA composition, P5 physicochemical properties, P6 structure proxy, P7 redox and P8 fingerprint summary.</p>
                </div>
                <button class="btn subtle" @click="exportProteomeTable('proteome_candidate_dashboard')" :disabled="!proteomeCandidateRows.length">Download CSV</button>
              </div>
              <div class="table-wrap">
                <table class="table compact-table">
                  <thead><tr><th>Module</th><th>Protein</th><th>Gene</th><th>Length</th><th>Value</th></tr></thead>
                  <tbody>
                    <tr v-for="row in proteomeCandidateRows.slice(0, 24)" :key="`${row.module}-${row.entity_id}-${row.value}`">
                      <td>{{ row.module }}</td>
                      <td>{{ row.protein_id || row.entity_id }}</td>
                      <td>{{ row.gene_symbol || row.gene_id || '-' }}</td>
                      <td>{{ row.length_aa || '-' }}</td>
                      <td>{{ row.value }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>

            <section v-if="activePanel !== 'genome' && activePanel !== 'transcriptome' && activePanel !== 'proteome'" class="grid grid-4">
              <article class="mini-card" v-for="card in featureSummaryCards" :key="card.key">
                <div class="label">{{ formatKey(card.key) }}</div>
                <div class="metric-inline">{{ card.mean }}</div>
                <p class="muted" style="margin: 8px 0 0">
                  P05 {{ card.p05 }} / P95 {{ card.p95 }}
                </p>
              </article>
            </section>

            <section v-if="activePanel !== 'genome' && activePanel !== 'transcriptome' && activePanel !== 'proteome'" class="panel chart-panel">
              <div class="section-header compact">
                <div>
                  <div class="eyebrow">{{ activePanel }} first-screen module</div>
                  <h3>{{ omicsFirstScreenTitle }}</h3>
                </div>
              </div>
              <EChart :option="omicsFirstScreenChart" :height="360" />
              <div class="annotation">{{ omicsFirstScreenAnnotation }}</div>
              <MethodBadge
                :method="omicsFirstScreenMethod.method"
                :normalization="omicsFirstScreenMethod.normalization"
                :missing-policy="omicsFirstScreenMethod.missingPolicy"
                :n="omicsFirstScreenMethod.n"
                :n-features="omicsFirstScreenRows.length"
                :exploratory="omicsFirstScreenMethod.exploratory"
              />
            </section>

            <section v-if="activePanel !== 'genome' && activePanel !== 'transcriptome' && activePanel !== 'proteome'" class="grid grid-2">
              <article class="panel chart-panel">
                <div class="section-header compact">
                  <h3>{{ omicsSpecializedTitle }}</h3>
                  <select
                    v-if="derivedScatterOptions.length > 1"
                    class="input select-inline"
                    v-model="derivedScatterKey"
                  >
                    <option v-for="item in derivedScatterOptions" :key="item.key" :value="item.key">
                      {{ item.label }}
                    </option>
                  </select>
                </div>
                <EChart v-if="omicsSpecializedAvailable" :option="omicsSpecializedChart" :height="360" />
                <EmptyState
                  v-else
                  eyebrow="Missing fields"
                  :title="omicsSpecializedTitle"
                  :message="omicsSpecializedMissingMessage"
                />
                <div v-if="omicsSpecializedAvailable" class="annotation">{{ omicsSpecializedAnnotation }}</div>
                <ScatterInsightCard
                  v-if="omicsSpecializedAvailable"
                  :meta="omicsSpecializedMeta"
                  :title="omicsSpecializedTitle"
                />
                <CandidateLinkedTable
                  v-if="omicsSpecializedAvailable"
                  :candidates="omicsSpecializedCandidates"
                  :species-id="species.species_id"
                />
              </article>

              <article class="panel">
                <div class="section-header compact"><h3>{{ omicsFutureTitle }}</h3></div>
                <div v-if="derivedVisualPanel" class="table-wrap">
                  <table class="table compact-table">
                    <thead>
                      <tr>
                        <th>Feature</th>
                        <th>Status</th>
                        <th>Rows</th>
                        <th>Mean</th>
                        <th>Example</th>
                        <th>Calculation</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="row in derivedVisualRows" :key="row.field">
                        <td>{{ formatKey(row.field) }}</td>
                        <td>{{ row.available ? 'available' : 'missing' }}</td>
                        <td>{{ row.n_valid || '-' }}</td>
                        <td>{{ row.mean ?? '-' }}</td>
                        <td>{{ formatDerivedExample(row.example) }}</td>
                        <td>{{ row.calculation || '-' }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
                <div v-if="derivedVisualPanel" class="annotation">{{ derivedVisualAnnotation }}</div>
                <EmptyState
                  v-else
                  :eyebrow="omicsFutureEyebrow"
                  :title="omicsFutureTitle"
                  :message="omicsFutureMessage"
                />
              </article>
            </section>

            <section class="grid grid-2">
              <article class="panel chart-panel">
                <div class="section-header compact">
                  <h3>{{ activePanel === 'proteome' ? 'General feature explorer: distribution' : 'Feature distribution' }}</h3>
                  <select class="input select-inline" v-model="distributionKey">
                    <option v-for="key in distributionKeys" :key="key" :value="key">
                      {{ formatKey(key) }}
                    </option>
                  </select>
                </div>
                <EChart :option="distributionChart" :height="360" />
                <div class="annotation">{{ distributionAnnotation }}</div>
                <MethodBadge
                  method="field summary distribution"
                  normalization="raw"
                  :missing-policy="fieldSummaryPayload ? 'valid numeric values only' : 'precomputed summary payload'"
                  :n="fieldSummaryPayload?.n_valid || fieldSummaryPayload?.n || ''"
                />
              </article>

              <article class="panel chart-panel">
                <div class="section-header compact"><h3>Distribution summary (P05-P95)</h3></div>
                <EChart :option="distributionBoxplot" :height="360" />
              </article>
            </section>

            <section v-if="activePanel !== 'genome' && activePanel !== 'transcriptome' && activePanel !== 'proteome'" class="grid grid-2">
              <article class="panel chart-panel">
                <div class="section-header compact">
                  <h3>Feature landscape</h3>
                  <select class="input select-inline" v-model="scatterKey">
                    <option v-for="key in scatterKeys" :key="key" :value="key">
                      {{ formatScatterLabel(key) }}
                    </option>
                  </select>
                </div>
                <EChart :option="scatterChart" :height="380" />
              </article>

              <article class="panel chart-panel">
                <div class="section-header compact">
                  <h3>Feature coupling heatmap</h3>
                  <select class="input select-inline" v-model="omicsCorrMethod">
                    <option v-for="method in omicsCorrMethods" :key="method" :value="method">
                      {{ method.toUpperCase() }}
                    </option>
                  </select>
                </div>
                <EChart :option="couplingHeatmap" :height="380" />
              </article>
            </section>

            <section v-if="activePanel !== 'transcriptome'" class="panel chart-panel">
              <div class="section-header compact">
                <h3>Custom feature explorer</h3>
                <div class="row">
                  <select class="input select-inline" v-model="customScatterX">
                    <option v-for="field in dynamicFieldOptions" :key="`x-${field}`" :value="field">
                      X: {{ formatKey(field) }}
                    </option>
                  </select>
                  <select class="input select-inline" v-model="customScatterY">
                    <option v-for="field in dynamicFieldOptions" :key="`y-${field}`" :value="field">
                      Y: {{ formatKey(field) }}
                    </option>
                  </select>
                  <button class="btn subtle" @click="loadCustomScatter" :disabled="customScatterLoading">
                    {{ customScatterLoading ? 'Loading...' : 'Refresh' }}
                  </button>
                </div>
              </div>
              <EChart :option="customScatterChart" :height="380" />
              <div class="annotation">{{ customScatterAnnotation }}</div>
            </section>

            <section v-if="activePanel !== 'genome' && activePanel !== 'transcriptome' && activePanel !== 'proteome'" class="grid grid-2">
              <article class="panel chart-panel">
                <div class="section-header compact"><h3>Top ranked entities by selected feature</h3></div>
                <EChart :option="topEntitiesChart" :height="360" />
              </article>

              <article class="panel chart-panel">
                <div class="section-header compact"><h3>Lowest ranked entities by selected feature</h3></div>
                <EChart :option="bottomEntitiesChart" :height="360" />
              </article>
            </section>

            <section class="panel">
              <div class="section-header compact"><h3>Preview rows</h3></div>
              <div class="table-wrap">
                <table class="table compact-table">
                  <thead>
                    <tr>
                      <th v-for="column in previewColumns" :key="column">{{ column }}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(row, idx) in omicsSummary.preview_rows || []" :key="idx">
                      <td v-for="column in previewColumns" :key="column">{{ row[column] }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>
          </template>

          <template v-else-if="omicsTab === 'analysis'">
            <ModuleState
              v-if="currentOmicsModuleSuiteState === 'missing'"
              state="missing"
              :title="`${currentOmicsLabel} deep-analysis payload is not registered`"
              :message="currentOmicsModuleSuiteMissingMessage"
              suggestion="The summary payload loaded, but the module-specific analysis suite did not contain renderable chart data."
            />

            <section v-if="activePanel === 'genome' && genomeModuleSuite" class="panel">
              <div class="section-header">
                <div>
                  <div class="eyebrow">Genome deep analysis</div>
                  <h3>Evidence & method metadata</h3>
                  <p class="muted">{{ genomeEvidenceBanner }}</p>
                </div>
                <div class="metric-band">
                  <span class="badge">Evidence: {{ omicsAnalysis.evidence_level || 'exploratory' }}</span>
                  <span class="badge">Rows: {{ genomeModuleSuite.row_count }}</span>
                  <span class="badge">Scope: {{ genomeModuleSuite.scope }}</span>
                </div>
              </div>
              <div v-if="genomeImplementationNotes.length" class="table-wrap">
                <table class="table compact-table">
                  <thead><tr><th>Module</th><th>Implementation note</th></tr></thead>
                  <tbody>
                    <tr v-for="row in genomeImplementationNotes" :key="`${row.module}-${row.note}`">
                      <td>{{ row.module }}</td>
                      <td>{{ row.note }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>

            <section v-if="activePanel === 'genome' && genomeModuleSuite" class="grid grid-2">
              <article class="panel chart-panel" id="g3-skew">
                <div class="section-header compact"><h3>G3 GC/AT skew asymmetry</h3></div>
                <EChart :option="genomeG3SkewChart" :height="330" />
                <div class="annotation">{{ genomeModuleMethod('G3') }}</div>
              </article>

              <article class="panel chart-panel">
                <div class="section-header compact"><h3>G3 Cumulative GC skew</h3></div>
                <EChart :option="genomeG3CumulativeChart" :height="330" />
              </article>
            </section>

            <section v-if="activePanel === 'genome' && genomeModuleSuite" class="grid grid-2">
              <article class="panel chart-panel" id="g4-dinuc">
                <div class="section-header compact"><h3>G4 Dinucleotide genomic signature</h3></div>
                <EChart :option="genomeG4DinucHeatmap" :height="340" />
                <div class="annotation">{{ genomeModuleMethod('G4') }}</div>
              </article>

              <article class="panel chart-panel">
                <div class="section-header compact">
                  <h3>G4 Dinuc anomaly distance</h3>
                  <button class="btn subtle" @click="exportGenomeTable('g4_anomalies')" :disabled="!(genomeModule('G4').anomaly_ranking || []).length">Download CSV</button>
                </div>
                <EChart :option="genomeG4DistanceChart" :height="340" />
              </article>
            </section>

            <section v-if="activePanel === 'genome' && genomeModuleSuite" class="grid grid-2">
              <article class="panel chart-panel">
                <div class="section-header compact">
                  <h3>G4 Promoter signature ordination</h3>
                  <select class="input select-inline" v-model="genomeEmbeddingMode">
                    <option value="umap">UMAP</option>
                    <option value="pca">PCA</option>
                  </select>
                </div>
                <EChart :option="genomeG4PromoterPcaChart" :height="330" />
                <div class="annotation">{{ genomeG4PromoterEmbeddingAnnotation }}</div>
              </article>

              <article class="panel chart-panel">
                <div class="section-header compact">
                  <h3>G4 Cross-species dinuc ordination</h3>
                  <select class="input select-inline" v-model="genomeEmbeddingMode">
                    <option value="umap">UMAP</option>
                    <option value="pca">PCA</option>
                  </select>
                </div>
                <EChart :option="genomeG4SpeciesPcaChart" :height="330" />
                <div class="annotation">{{ genomeG4SpeciesEmbeddingAnnotation }}</div>
              </article>
            </section>

            <section v-if="activePanel === 'genome' && genomeModuleSuite" class="grid grid-2">
              <article class="panel chart-panel">
                <div class="section-header compact">
                  <h3>G2 Contrast ordination</h3>
                  <select class="input select-inline" v-model="genomeEmbeddingMode">
                    <option value="umap">UMAP</option>
                    <option value="pca">PCA</option>
                  </select>
                </div>
                <EChart :option="genomeG2ContrastPcaChart" :height="320" />
                <div class="annotation">{{ genomeG2EmbeddingAnnotation }}</div>
              </article>

              <article class="panel chart-panel">
                <div class="section-header compact"><h3>G2 Contrast clusters</h3></div>
                <EChart :option="genomeG2ClusterChart" :height="320" />
              </article>
            </section>

            <section v-if="activePanel === 'genome' && genomeModuleSuite" class="grid grid-2">
              <article class="panel chart-panel" id="g5-codon">
                <div class="section-header compact"><h3>G5 CDS codon & GC3 strategy</h3></div>
                <EChart :option="genomeG5GcChart" :height="320" />
                <div class="annotation">{{ genomeModuleMethod('G5') }}</div>
              </article>

              <article class="panel chart-panel">
                <div class="section-header compact"><h3>G5 Codon usage heatmap</h3></div>
                <EChart :option="genomeG5CodonHeatmap" :height="320" />
              </article>
            </section>

            <section v-if="activePanel === 'genome' && genomeModuleSuite" class="grid grid-2">
              <article class="panel chart-panel">
                <div class="section-header compact">
                  <h3>G5 Codon strategy ordination</h3>
                  <select class="input select-inline" v-model="genomeEmbeddingMode">
                    <option value="umap">UMAP</option>
                    <option value="pca">PCA</option>
                  </select>
                </div>
                <EChart :option="genomeG5CodonPcaChart" :height="320" />
                <div class="annotation">{{ genomeG5EmbeddingAnnotation }}</div>
              </article>

              <article class="panel chart-panel">
                <div class="section-header compact"><h3>G5 Codon strategy clusters</h3></div>
                <EChart :option="genomeG5ClusterChart" :height="320" />
              </article>
            </section>

            <section v-if="activePanel === 'genome' && genomeModuleSuite" class="grid grid-2">
              <article class="panel chart-panel">
                <div class="section-header compact">
                  <h3>G5 Codon entropy</h3>
                  <button class="btn subtle" @click="exportGenomeTable('g5_codon_anomalies')" :disabled="!(genomeModule('G5').codon_anomaly_genes || []).length">Download CSV</button>
                </div>
                <EChart :option="genomeG5EntropyChart" :height="320" />
              </article>

              <article class="panel chart-panel">
                <div class="section-header compact"><h3>G5 CDS-derived AA preview</h3></div>
                <EChart :option="genomeG5AaChart" :height="320" />
              </article>
            </section>

            <section v-if="activePanel === 'genome' && genomeModuleSuite" class="grid grid-2">
              <article class="panel chart-panel" id="g6-stoich-island">
                <div class="section-header compact"><h3>G6 Stoichiometric island / hotspot</h3></div>
                <EChart :option="genomeG6ProfileChart" :height="340" />
                <div class="annotation">{{ genomeModuleMethod('G6') }}</div>
              </article>

              <article class="panel chart-panel">
                <div class="section-header compact"><h3>G6 Island score distribution</h3></div>
                <EChart :option="genomeG6ScoreChart" :height="340" />
              </article>
            </section>

            <section v-if="activePanel === 'genome' && genomeModuleSuite" class="grid grid-2">
              <article class="panel">
                <div class="section-header compact">
                  <h3>G6 Top island genes</h3>
                  <button class="btn subtle" @click="exportGenomeTable('g6_top_island_genes')" :disabled="!genomeG6TopGenes.length">Download CSV</button>
                </div>
                <div class="table-wrap">
                  <table class="table compact-table">
                    <thead><tr><th>Gene</th><th>Score</th><th>Robust z</th><th>Location</th><th>Cluster</th></tr></thead>
                    <tbody>
                      <tr v-for="row in genomeG6TopGenes" :key="row.entity_id">
                        <td>{{ row.gene_name || row.gene_id || row.entity_id }}</td>
                        <td>{{ row.value }}</td>
                        <td>{{ row.robust_z }}</td>
                        <td>{{ row.seqid }}:{{ row.start_1 }}-{{ row.end_1 }}</td>
                        <td>{{ row.strategy_cluster || '-' }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </article>

              <article class="panel">
                <div class="section-header compact">
                  <h3>G6 Hotspot windows</h3>
                  <button class="btn subtle" @click="exportGenomeTable('g6_hotspot_windows')" :disabled="!genomeG6HotspotRows.length">Download CSV</button>
                </div>
                <div class="table-wrap">
                  <table class="table compact-table">
                    <thead><tr><th>Window</th><th>Start</th><th>End</th><th>Genes</th><th>Mean score</th></tr></thead>
                    <tbody>
                      <tr v-for="row in genomeG6HotspotRows" :key="row.window_id">
                        <td>{{ row.window_id }}</td>
                        <td>{{ row.window_start }}</td>
                        <td>{{ row.window_end }}</td>
                        <td>{{ row.n_genes }}</td>
                        <td>{{ row.mean_score }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </article>
            </section>

            <section v-if="activePanel === 'genome' && genomeModuleSuite" class="grid grid-2">
              <article class="panel chart-panel" id="genome-coupling">
                <div class="section-header compact">
                  <h3>Coupling matrix</h3>
                  <select class="input select-inline" v-model="omicsCorrMethod">
                    <option v-for="method in omicsCorrMethods" :key="method" :value="method">
                      {{ method.toUpperCase() }}
                    </option>
                  </select>
                </div>
                <EChart :option="couplingHeatmap" :height="380" />
              </article>

              <article class="panel chart-panel">
                <div class="section-header compact">
                  <h3>Coupling network</h3>
                  <label class="row" style="gap: 8px">
                    <span class="label">|r| >= {{ couplingMinAbs.toFixed(2) }}</span>
                    <input v-model.number="couplingMinAbs" type="range" min="0" max="0.95" step="0.05" />
                  </label>
                </div>
                <EChart :option="networkChart" :height="380" />
              </article>
            </section>

            <section v-if="activePanel === 'genome' && genomeModuleSuite" class="grid grid-2">
              <article class="panel chart-panel" id="genome-strategy">
                <div class="section-header compact">
                  <h3>Strategy typing ordination</h3>
                  <select class="input select-inline" v-model="genomeEmbeddingMode">
                    <option value="umap">UMAP</option>
                    <option value="pca">PCA</option>
                  </select>
                </div>
                <EChart :option="genomeG1PcaChart" :height="330" />
                <div class="annotation">{{ genomeG1EmbeddingAnnotation }}</div>
              </article>

              <article class="panel chart-panel">
                <div class="section-header compact"><h3>G2/G5 Strategy clusters</h3></div>
                <EChart :option="genomeStrategyClusterChart" :height="330" />
              </article>
            </section>

            <section v-if="activePanel === 'genome' && genomeModuleSuite" class="panel" id="genome-outliers">
              <div class="section-header compact">
                <h3>Global outlier summary</h3>
                <button class="btn subtle" @click="exportGenomeTable('genome_candidate_genes')" :disabled="!genomeGlobalOutlierRows.length">Download CSV</button>
              </div>
              <div class="table-wrap">
                <table class="table compact-table">
                  <thead><tr><th>Source</th><th>Gene</th><th>Score / value</th><th>Location</th><th>Evidence</th></tr></thead>
                  <tbody>
                    <tr v-for="row in genomeGlobalOutlierRows" :key="`${row.module}-${row.entity_id}`">
                      <td>{{ row.module }}</td>
                      <td>{{ row.gene_name || row.gene_id || row.entity_id }}</td>
                      <td>{{ row.value }}</td>
                      <td>{{ row.seqid }}:{{ row.start_1 }}-{{ row.end_1 }}</td>
                      <td>descriptive</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>

            <section v-if="activePanel === 'genome' && genomeModuleSuite" class="grid grid-2">
              <article class="panel chart-panel" id="genome-compare">
                <div class="section-header compact">
                  <h3>Genome compare ordination</h3>
                  <select class="input select-inline" v-model="genomeEmbeddingMode">
                    <option value="umap">UMAP</option>
                    <option value="pca">PCA</option>
                  </select>
                </div>
                <EChart :option="genomeG8SpeciesPcaChart" :height="340" />
                <div class="annotation">{{ genomeG8EmbeddingAnnotation }}</div>
              </article>

              <article class="panel chart-panel">
                <div class="section-header compact"><h3>G8 genome fingerprint distance matrix</h3></div>
                <EChart :option="genomeG8DistanceChart" :height="340" />
              </article>
            </section>

            <section v-if="activePanel === 'genome' && genomeModuleSuite" class="grid grid-2">
              <article class="panel">
                <div class="section-header compact">
                  <h3>Discriminative genome features</h3>
                  <button class="btn subtle" @click="exportGenomeTable('g8_feature_ranking')" :disabled="!genomeG8FeatureRanking.length">Download CSV</button>
                </div>
                <div class="table-wrap">
                  <table class="table compact-table">
                    <thead><tr><th>Feature</th><th>Range</th><th>Std</th><th>Species</th></tr></thead>
                    <tbody>
                      <tr v-for="row in genomeG8FeatureRanking" :key="row.feature">
                        <td>{{ formatKey(row.feature) }}</td>
                        <td>{{ row.range }}</td>
                        <td>{{ row.std }}</td>
                        <td>{{ row.n_species }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </article>

              <article v-if="hasTradeoffRows" class="panel chart-panel">
                <div class="section-header compact"><h3>Advanced optional: trade-off landscape</h3></div>
                <EChart :option="tradeoffChart" :height="340" />
                <div class="annotation">{{ tradeoffFormulaNote }}</div>
              </article>
            </section>

            <section v-if="activePanel === 'transcriptome' && transcriptomeModuleSuite" class="panel">
              <div class="section-header">
                <div>
                  <div class="eyebrow">Transcript sequence deep analysis</div>
                  <h3>Evidence & method metadata</h3>
                  <p class="muted">{{ transcriptomeEvidenceBanner }}</p>
                </div>
                <div class="metric-band">
                  <span class="badge">Rows: {{ transcriptomeModuleSuite.row_count }}</span>
                  <span class="badge">Coding rows: {{ transcriptomeModuleSuite.coding_row_count }}</span>
                  <span class="badge">Scope: {{ transcriptomeModuleSuite.scope }}</span>
                </div>
              </div>
              <div v-if="transcriptomeImplementationNotes.length" class="table-wrap">
                <table class="table compact-table">
                  <thead><tr><th>Module</th><th>Implementation note</th></tr></thead>
                  <tbody>
                    <tr v-for="row in transcriptomeImplementationNotes" :key="`${row.module}-${row.note}`">
                      <td>{{ row.module }}</td>
                      <td>{{ row.note }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>

            <section v-if="activePanel === 'transcriptome' && transcriptomeModuleSuite" class="grid grid-2">
              <article class="panel chart-panel">
                <div class="section-header compact">
                  <h3>T2 RNA stoich-space ordination</h3>
                  <select class="input select-inline" v-model="transcriptomeEmbeddingMode">
                    <option value="umap">UMAP</option>
                    <option value="pca">PCA</option>
                  </select>
                </div>
                <EChart :option="transcriptomeT2ProjectionChart" :height="330" />
                <div class="annotation">{{ transcriptomeT2ProjectionNote }}</div>
              </article>

              <article class="panel chart-panel">
                <div class="section-header compact"><h3>T2 Resource-strategy clusters</h3></div>
                <EChart :option="transcriptomeT2ClusterChart" :height="330" />
              </article>
            </section>

            <section v-if="activePanel === 'transcriptome' && transcriptomeModuleSuite" class="grid grid-2">
              <article class="panel">
                <div class="section-header compact">
                  <h3>T2 RNA resource outliers</h3>
                  <button class="btn subtle" @click="exportTranscriptomeTable('t2_resource_outliers')" :disabled="!(transcriptomeModule('T2').resource_outliers || []).length">Download CSV</button>
                </div>
                <div class="table-wrap">
                  <table class="table compact-table">
                    <thead><tr><th>Transcript</th><th>Gene</th><th>Biotype</th><th>Score</th></tr></thead>
                    <tbody>
                      <tr v-for="row in transcriptomeModule('T2').resource_outliers || []" :key="row.entity_id">
                        <td>{{ row.transcript_id || row.entity_id }}</td>
                        <td>{{ row.gene_symbol || row.gene_id || '-' }}</td>
                        <td>{{ row.transcript_biotype || '-' }}</td>
                        <td>{{ row.value }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </article>

              <article class="panel chart-panel" id="t3-pattern">
                <div class="section-header compact"><h3>T3 RNA dinucleotide signature</h3></div>
                <EChart :option="transcriptomeT3DinucHeatmap" :height="330" />
                <div class="annotation">{{ transcriptomeModuleMethod('T3') }}</div>
              </article>
            </section>

            <section v-if="activePanel === 'transcriptome' && transcriptomeModuleSuite" class="grid grid-2">
              <article class="panel chart-panel">
                <div class="section-header compact">
                  <h3>T3 Sequence-pattern ordination</h3>
                  <select class="input select-inline" v-model="transcriptomeEmbeddingMode">
                    <option value="umap">UMAP</option>
                    <option value="pca">PCA</option>
                  </select>
                </div>
                <EChart :option="transcriptomeT3ProjectionChart" :height="330" />
                <div class="annotation">{{ transcriptomeT3ProjectionNote }}</div>
              </article>

              <article class="panel chart-panel">
                <div class="section-header compact"><h3>T3 Stability proxy distribution</h3></div>
                <EChart :option="transcriptomeT3StabilityChart" :height="330" />
              </article>
            </section>

            <section v-if="activePanel === 'transcriptome' && transcriptomeModuleSuite" class="grid grid-2">
              <article class="panel">
                <div class="section-header compact">
                  <h3>T3 Low-complexity candidates</h3>
                  <button class="btn subtle" @click="exportTranscriptomeTable('t3_low_complexity')" :disabled="!(transcriptomeModule('T3').low_complexity_candidates || []).length">Download CSV</button>
                </div>
                <div class="table-wrap">
                  <table class="table compact-table">
                    <thead><tr><th>Transcript</th><th>Gene</th><th>Biotype</th><th>Value</th></tr></thead>
                    <tbody>
                      <tr v-for="row in transcriptomeModule('T3').low_complexity_candidates || []" :key="`${row.entity_id}-${row.value}`">
                        <td>{{ row.transcript_id || row.entity_id }}</td>
                        <td>{{ row.gene_symbol || row.gene_id || '-' }}</td>
                        <td>{{ row.transcript_biotype || '-' }}</td>
                        <td>{{ row.value }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </article>

              <article class="panel chart-panel">
                <div class="section-header compact"><h3>T3 Pattern coupling heatmap</h3></div>
                <EChart :option="transcriptomeT3CouplingChart" :height="330" />
              </article>
            </section>

            <section v-if="activePanel === 'transcriptome' && transcriptomeModuleSuite" class="grid grid-2">
              <article class="panel chart-panel">
                <div class="section-header compact"><h3>T5 ORF vs transcript length</h3></div>
                <EChart :option="transcriptomeT5OrfScatter" :height="330" />
              </article>

              <article class="panel chart-panel">
                <div class="section-header compact"><h3>T5 Biotype x ORF validity</h3></div>
                <EChart :option="transcriptomeT5OrfMatrix" :height="330" />
              </article>
            </section>

            <section v-if="activePanel === 'transcriptome' && transcriptomeModuleSuite" class="grid grid-2">
              <article class="panel" id="t5-orf-candidates">
                <div class="section-header compact">
                  <h3>T5 Coding-potential candidates</h3>
                  <button class="btn subtle" @click="exportTranscriptomeTable('t5_coding_candidates')" :disabled="!(transcriptomeModule('T5').coding_potential_candidates || []).length">Download CSV</button>
                </div>
                <div class="table-wrap">
                  <table class="table compact-table">
                    <thead><tr><th>Transcript</th><th>Gene</th><th>Biotype</th><th>Value</th></tr></thead>
                    <tbody>
                      <tr v-for="row in transcriptomeModule('T5').coding_potential_candidates || []" :key="`${row.entity_id}-${row.value}`">
                        <td>{{ row.transcript_id || row.entity_id }}</td>
                        <td>{{ row.gene_symbol || row.gene_id || '-' }}</td>
                        <td>{{ row.transcript_biotype || '-' }}</td>
                        <td>{{ row.value }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </article>

              <article class="panel chart-panel" id="t6-codon">
                <div class="section-header compact"><h3>T6 64-codon usage heatmap</h3></div>
                <EChart :option="transcriptomeT6CodonHeatmap" :height="330" />
                <div class="annotation">{{ transcriptomeModuleMethod('T6') }}</div>
              </article>
            </section>

            <section v-if="activePanel === 'transcriptome' && transcriptomeModuleSuite" class="grid grid-2">
              <article class="panel chart-panel">
                <div class="section-header compact">
                  <h3>T6 Codon strategy ordination</h3>
                  <select class="input select-inline" v-model="transcriptomeEmbeddingMode">
                    <option value="umap">UMAP</option>
                    <option value="pca">PCA</option>
                  </select>
                </div>
                <EChart :option="transcriptomeT6ProjectionChart" :height="330" />
                <div class="annotation">{{ transcriptomeT6ProjectionNote }}</div>
              </article>

              <article class="panel chart-panel">
                <div class="section-header compact"><h3>T6 Codon entropy</h3></div>
                <EChart :option="transcriptomeT6CodonEntropyChart" :height="330" />
              </article>
            </section>

            <section v-if="activePanel === 'transcriptome' && transcriptomeModuleSuite" class="grid grid-2">
              <article class="panel">
                <div class="section-header compact">
                  <h3>T6 Codon anomaly transcripts</h3>
                  <button class="btn subtle" @click="exportTranscriptomeTable('t6_codon_anomalies')" :disabled="!(transcriptomeModule('T6').codon_anomaly_transcripts || []).length">Download CSV</button>
                </div>
                <div class="table-wrap">
                  <table class="table compact-table">
                    <thead><tr><th>Transcript</th><th>Gene</th><th>Biotype</th><th>Value</th></tr></thead>
                    <tbody>
                      <tr v-for="row in transcriptomeModule('T6').codon_anomaly_transcripts || []" :key="row.entity_id">
                        <td>{{ row.transcript_id || row.entity_id }}</td>
                        <td>{{ row.gene_symbol || row.gene_id || '-' }}</td>
                        <td>{{ row.transcript_biotype || '-' }}</td>
                        <td>{{ row.value }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </article>

              <article class="panel chart-panel">
                <div class="section-header compact">
                  <h3>T7 RNA-to-protein preview ordination</h3>
                  <select class="input select-inline" v-model="transcriptomeEmbeddingMode">
                    <option value="umap">UMAP</option>
                    <option value="pca">PCA</option>
                  </select>
                </div>
                <EChart :option="transcriptomeT7ProjectionChart" :height="330" />
                <div class="annotation">{{ transcriptomeT7ProjectionNote }}</div>
              </article>
            </section>

            <section v-if="activePanel === 'transcriptome' && transcriptomeModuleSuite" class="grid grid-2">
              <article class="panel chart-panel">
                <div class="section-header compact"><h3>T7 RNA-to-protein coupling</h3></div>
                <EChart :option="transcriptomeT7CouplingChart" :height="330" />
              </article>

              <article class="panel">
                <div class="section-header compact">
                  <h3>T7 High-instability predicted proteins</h3>
                  <button class="btn subtle" @click="exportTranscriptomeTable('t7_instability_candidates')" :disabled="!(transcriptomeModule('T7').instability_candidates || []).length">Download CSV</button>
                </div>
                <div class="table-wrap">
                  <table class="table compact-table">
                    <thead><tr><th>Transcript</th><th>Gene</th><th>Biotype</th><th>Value</th></tr></thead>
                    <tbody>
                      <tr v-for="row in transcriptomeModule('T7').instability_candidates || []" :key="row.entity_id">
                        <td>{{ row.transcript_id || row.entity_id }}</td>
                        <td>{{ row.gene_symbol || row.gene_id || '-' }}</td>
                        <td>{{ row.transcript_biotype || '-' }}</td>
                        <td>{{ row.value }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </article>
            </section>

            <section v-if="activePanel === 'transcriptome' && transcriptomeModuleSuite" class="grid grid-2">
              <article class="panel chart-panel">
                <div class="section-header compact">
                  <h3>T8 transcript sequence species ordination</h3>
                  <select class="input select-inline" v-model="transcriptomeEmbeddingMode">
                    <option value="umap">UMAP</option>
                    <option value="pca">PCA</option>
                  </select>
                </div>
                <EChart :option="transcriptomeT8SpeciesChart" :height="340" />
                <div class="annotation">{{ transcriptomeT8ProjectionNote }}</div>
              </article>

              <article class="panel chart-panel">
                <div class="section-header compact"><h3>T8 transcript fingerprint distance matrix</h3></div>
                <EChart :option="transcriptomeT8DistanceChart" :height="340" />
              </article>
            </section>

            <section v-if="activePanel === 'transcriptome' && transcriptomeModuleSuite" class="grid grid-2">
              <article class="panel">
                <div class="section-header compact">
                  <h3>T8 Candidate summary</h3>
                  <button class="btn subtle" @click="exportTranscriptomeTable('t8_candidate_summary')" :disabled="!transcriptomeCandidateRows.length">Download CSV</button>
                </div>
                <div class="table-wrap">
                  <table class="table compact-table">
                    <thead><tr><th>Transcript</th><th>Gene</th><th>Biotype</th><th>Value</th></tr></thead>
                    <tbody>
                      <tr v-for="row in transcriptomeCandidateRows" :key="`${row.entity_id}-${row.value}`">
                        <td>{{ row.transcript_id || row.entity_id }}</td>
                        <td>{{ row.gene_symbol || row.gene_id || '-' }}</td>
                        <td>{{ row.transcript_biotype || '-' }}</td>
                        <td>{{ row.value }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </article>

              <article class="panel">
                <div class="section-header compact">
                  <h3>T8 discriminative transcript sequence features</h3>
                  <button class="btn subtle" @click="exportTranscriptomeTable('t8_feature_ranking')" :disabled="!transcriptomeT8FeatureRanking.length">Download CSV</button>
                </div>
                <div class="table-wrap">
                  <table class="table compact-table">
                    <thead><tr><th>Feature</th><th>Range</th><th>Std</th><th>Species</th></tr></thead>
                    <tbody>
                      <tr v-for="row in transcriptomeT8FeatureRanking" :key="row.feature">
                        <td>{{ formatKey(row.feature) }}</td>
                        <td>{{ row.range }}</td>
                        <td>{{ row.std }}</td>
                        <td>{{ row.n_species }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </article>
            </section>

            <section v-if="activePanel === 'proteome' && proteomeModuleSuite" class="panel">
              <div class="section-header">
                <div>
                  <div class="eyebrow">Proteome deep analysis</div>
                  <h3>Evidence & method metadata</h3>
                  <p class="muted">{{ proteomeEvidenceBanner }}</p>
                </div>
                <div class="metric-band">
                  <span class="badge">Rows: {{ proteomeModuleSuite.row_count }}</span>
                  <span class="badge">Scope: {{ proteomeModuleSuite.scope }}</span>
                </div>
              </div>
              <div v-if="proteomeImplementationNotes.length" class="table-wrap">
                <table class="table compact-table">
                  <thead><tr><th>Module</th><th>Implementation note</th></tr></thead>
                  <tbody>
                    <tr v-for="row in proteomeImplementationNotes" :key="`${row.module}-${row.note}`">
                      <td>{{ row.module }}</td>
                      <td>{{ row.note }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>

            <section v-if="activePanel === 'proteome' && proteomeModuleSuite" class="grid grid-2">
              <article class="panel chart-panel">
                <div class="section-header compact">
                  <h3>P2 Resource-space ordination</h3>
                  <select class="input select-inline" v-model="proteomeEmbeddingMode">
                    <option value="umap">UMAP</option>
                    <option value="pca">PCA</option>
                  </select>
                </div>
                <EChart :option="proteomeP2ProjectionChart" :height="330" />
                <div class="annotation">{{ proteomeP2ProjectionNote }}</div>
              </article>

              <article class="panel">
                <div class="section-header compact">
                  <h3>P2 Resource outliers</h3>
                  <button class="btn subtle" @click="exportProteomeTable('p2_resource_outliers')" :disabled="!(proteomeModule('P2').resource_outliers || []).length">Download CSV</button>
                </div>
                <div class="table-wrap">
                  <table class="table compact-table">
                    <thead><tr><th>Protein</th><th>Gene</th><th>Length</th><th>Score</th></tr></thead>
                    <tbody>
                      <tr v-for="row in proteomeModule('P2').resource_outliers || []" :key="row.entity_id">
                        <td>{{ row.protein_id || row.entity_id }}</td>
                        <td>{{ row.gene_symbol || row.gene_id || '-' }}</td>
                        <td>{{ row.length_aa || '-' }}</td>
                        <td>{{ row.value }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </article>
            </section>

            <section v-if="activePanel === 'proteome' && proteomeModuleSuite" class="grid grid-2">
              <article class="panel chart-panel">
                <div class="section-header compact"><h3>P3 N/S trade-off landscape</h3></div>
                <EChart :option="proteomeP3NsScatter" :height="330" />
              </article>

              <article class="panel">
                <div class="section-header compact">
                  <h3>P3 S-rich / Se candidates</h3>
                  <button class="btn subtle" @click="exportProteomeTable('p3_s_rich')" :disabled="!(proteomeModule('P3').s_rich_candidates || []).length">Download CSV</button>
                </div>
                <div class="table-wrap">
                  <table class="table compact-table">
                    <thead><tr><th>Protein</th><th>Gene</th><th>Length</th><th>Value</th></tr></thead>
                    <tbody>
                      <tr v-for="row in proteomeModule('P3').s_rich_candidates || []" :key="row.entity_id">
                        <td>{{ row.protein_id || row.entity_id }}</td>
                        <td>{{ row.gene_symbol || row.gene_id || '-' }}</td>
                        <td>{{ row.length_aa || '-' }}</td>
                        <td>{{ row.value }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </article>
            </section>

            <section v-if="activePanel === 'proteome' && proteomeModuleSuite" class="grid grid-2">
              <article class="panel chart-panel">
                <div class="section-header compact">
                  <h3>P4 AA composition ordination</h3>
                  <select class="input select-inline" v-model="proteomeEmbeddingMode">
                    <option value="umap">UMAP</option>
                    <option value="pca">PCA</option>
                  </select>
                </div>
                <EChart :option="proteomeP4ProjectionChart" :height="330" />
                <div class="annotation">{{ proteomeP4ProjectionNote }}</div>
              </article>

              <article class="panel chart-panel">
                <div class="section-header compact"><h3>P4 AA class profile</h3></div>
                <EChart :option="proteomeP4ClassChart" :height="330" />
              </article>
            </section>

            <section v-if="activePanel === 'proteome' && proteomeModuleSuite" class="grid grid-2">
              <article class="panel chart-panel">
                <div class="section-header compact">
                  <h3>P5 Property landscape</h3>
                  <select class="input select-inline" v-model="proteomeEmbeddingMode">
                    <option value="umap">UMAP</option>
                    <option value="pca">PCA</option>
                  </select>
                </div>
                <EChart :option="proteomeP5ProjectionChart" :height="330" />
                <div class="annotation">{{ proteomeP5ProjectionNote }}</div>
              </article>

              <article class="panel chart-panel">
                <div class="section-header compact"><h3>P5 Instability vs GRAVY</h3></div>
                <EChart :option="proteomeP5InstabilityGravyChart" :height="330" />
              </article>
            </section>

            <section v-if="activePanel === 'proteome' && proteomeModuleSuite" class="grid grid-2">
              <article class="panel chart-panel">
                <div class="section-header compact">
                  <h3>P6 Structure-proxy ordination</h3>
                  <select class="input select-inline" v-model="proteomeEmbeddingMode">
                    <option value="umap">UMAP</option>
                    <option value="pca">PCA</option>
                  </select>
                </div>
                <EChart :option="proteomeP6ProjectionChart" :height="330" />
                <div class="annotation">{{ proteomeP6ProjectionNote }}</div>
              </article>

              <article class="panel chart-panel">
                <div class="section-header compact"><h3>P6 Flexibility-accessibility scatter</h3></div>
                <EChart :option="proteomeP6FlexAccessChart" :height="330" />
              </article>
            </section>

            <section v-if="activePanel === 'proteome' && proteomeModuleSuite" class="grid grid-2">
              <article class="panel chart-panel">
                <div class="section-header compact">
                  <h3>P7 Redox/detectability ordination</h3>
                  <select class="input select-inline" v-model="proteomeEmbeddingMode">
                    <option value="umap">UMAP</option>
                    <option value="pca">PCA</option>
                  </select>
                </div>
                <EChart :option="proteomeP7ProjectionChart" :height="330" />
                <div class="annotation">{{ proteomeP7ProjectionNote }}</div>
              </article>

              <article class="panel chart-panel">
                <div class="section-header compact"><h3>P7 Redox vs GRAVY</h3></div>
                <EChart :option="proteomeP7RedoxScatter" :height="330" />
              </article>
            </section>

            <section v-if="activePanel === 'proteome' && proteomeModuleSuite" class="grid grid-2">
              <article class="panel chart-panel">
                <div class="section-header compact">
                  <h3>P8 Proteome species ordination</h3>
                  <select class="input select-inline" v-model="proteomeEmbeddingMode">
                    <option value="umap">UMAP</option>
                    <option value="pca">PCA</option>
                  </select>
                </div>
                <EChart :option="proteomeP8SpeciesChart" :height="340" />
                <div class="annotation">{{ proteomeP8ProjectionNote }}</div>
              </article>

              <article class="panel chart-panel">
                <div class="section-header compact"><h3>P8 proteome fingerprint distance matrix</h3></div>
                <EChart :option="proteomeP8DistanceChart" :height="340" />
              </article>
            </section>

            <section v-if="activePanel === 'proteome' && proteomeModuleSuite" class="grid grid-2">
              <article class="panel chart-panel">
                <div class="section-header compact"><h3>P8 Integrated feature coupling</h3></div>
                <EChart :option="proteomeP8CouplingChart" :height="330" />
              </article>

              <article class="panel">
                <div class="section-header compact">
                  <h3>P8 Discriminative proteome features</h3>
                  <button class="btn subtle" @click="exportProteomeTable('p8_feature_ranking')" :disabled="!proteomeP8FeatureRanking.length">Download CSV</button>
                </div>
                <div class="table-wrap">
                  <table class="table compact-table">
                    <thead><tr><th>Feature</th><th>Range</th><th>Std</th><th>Species</th></tr></thead>
                    <tbody>
                      <tr v-for="row in proteomeP8FeatureRanking" :key="row.feature">
                        <td>{{ formatKey(row.feature) }}</td>
                        <td>{{ row.range }}</td>
                        <td>{{ row.std }}</td>
                        <td>{{ row.n_species }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </article>
            </section>

            <section v-if="activePanel === 'proteome' && proteomeModuleSuite" class="panel">
              <div class="section-header compact">
                <div>
                  <h3>Integrated proteome candidate dashboard</h3>
                  <p class="muted">Unified protein candidates grouped by resource, N/S/Se economy, AA composition, physicochemical property, structure proxy, redox and P8 fingerprint signals.</p>
                </div>
                <button class="btn subtle" @click="exportProteomeTable('proteome_candidate_dashboard')" :disabled="!proteomeCandidateRows.length">Download CSV</button>
              </div>
              <div class="table-wrap">
                <table class="table compact-table">
                  <thead><tr><th>Module</th><th>Protein</th><th>Gene</th><th>Length</th><th>Value</th></tr></thead>
                  <tbody>
                    <tr v-for="row in proteomeCandidateRows" :key="`deep-${row.module}-${row.entity_id}-${row.value}`">
                      <td>{{ row.module }}</td>
                      <td>{{ row.protein_id || row.entity_id }}</td>
                      <td>{{ row.gene_symbol || row.gene_id || '-' }}</td>
                      <td>{{ row.length_aa || '-' }}</td>
                      <td>{{ row.value }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>

            <section v-if="activePanel !== 'genome' && activePanel !== 'transcriptome' && activePanel !== 'proteome'" class="panel">
              <div class="section-header compact"><h3>Method and evidence notes</h3></div>
              <div class="annotation">{{ analysisMethodAnnotation }}</div>
            </section>

            <section v-if="activePanel !== 'genome' && activePanel !== 'proteome'" class="grid grid-2">
              <article v-if="activePanel !== 'transcriptome'" class="panel chart-panel">
                <div class="section-header compact"><h3>Exploratory strategy landscape</h3></div>
                <EChart :option="centroidChart" :height="380" />
              </article>

              <article class="panel chart-panel">
                <div class="section-header compact">
                  <h3>{{ activePanel === 'transcriptome' ? 'Unified transcript sequence coupling overview' : 'Feature coupling network' }}</h3>
                  <label class="row" style="gap: 8px">
                    <span class="label">|r| ≥ {{ couplingMinAbs.toFixed(2) }}</span>
                    <input v-model.number="couplingMinAbs" type="range" min="0" max="0.95" step="0.05" />
                  </label>
                </div>
                <EChart :option="networkChart" :height="380" />
                <MethodBadge
                  :method="omicsAnalysis.method_metadata?.coupling_network?.method || 'spearman_association'"
                  normalization="edge weight r"
                  missing-policy="pairwise complete numeric rows"
                  :thresholds="{ min_abs_r: couplingMinAbs.toFixed(2), top_edges: filteredCouplingEdges.length }"
                  :n="filteredCouplingEdges.length"
                  exploratory
                />
                <div v-if="activePanel === 'transcriptome'" class="annotation">Global pairwise feature coupling is retained as the unified support layer after T2-T8 modules; module-specific RNA, codon, ORF and protein-coupling panels above remain the primary interpretation source.</div>
              </article>
            </section>

            <section v-if="activePanel !== 'genome' && activePanel !== 'proteome'" class="grid grid-2">
              <article class="panel chart-panel">
                <div class="section-header compact"><h3>{{ activePanel === 'transcriptome' ? 'Resource-function trade-off landscape' : 'Trade-off landscape' }}</h3></div>
                <EChart :option="tradeoffChart" :height="400" />
                <MethodBadge
                  :method="omicsAnalysis.method_metadata?.tradeoff_front?.method || 'non_dominated_sorting'"
                  normalization="raw cost/adapt axes from payload"
                  missing-policy="rows with finite cost_axis and adapt_axis"
                  :n="(omicsAnalysis.tradeoff_front || []).length"
                  :thresholds="omicsAnalysis.method_metadata?.tradeoff_front?.axes || ''"
                  exploratory
                  :note="tradeoffFormulaNote"
                />
              </article>

              <article v-if="activePanel !== 'transcriptome'" class="panel chart-panel">
                <div class="section-header compact"><h3>{{ analysisSpecificTitle }}</h3></div>
                <EChart :option="analysisSpecificChart" :height="400" />
                <div class="annotation">{{ analysisAnnotationNormalized }}</div>
              </article>
            </section>

            <section v-if="activePanel === 'transcriptome' && transcriptomeModuleSuite" class="panel">
              <div class="section-header compact">
                <div>
                  <h3>Candidate Transcript Dashboard</h3>
                  <p class="muted">Unified candidate list assembled from T2 resource outliers, T3 low-complexity transcripts, T5 coding-potential cases, T6 codon anomalies, T7 predicted protein instability and T8 cross-species summary.</p>
                </div>
                <button class="btn subtle" @click="exportTranscriptomeTable('transcriptome_candidate_dashboard')" :disabled="!transcriptomeCandidateDashboardRows.length">Download CSV</button>
              </div>
              <div class="table-wrap">
                <table class="table compact-table">
                  <thead><tr><th>Source</th><th>Transcript</th><th>Gene</th><th>Biotype</th><th>Value</th></tr></thead>
                  <tbody>
                    <tr v-for="row in transcriptomeCandidateDashboardRows" :key="`${row.module_source}-${row.entity_id}-${row.value}`">
                      <td>{{ row.module_source }}</td>
                      <td>{{ row.transcript_id || row.entity_id }}</td>
                      <td>{{ row.gene_symbol || row.gene_id || '-' }}</td>
                      <td>{{ row.transcript_biotype || '-' }}</td>
                      <td>{{ row.value }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>

            <section v-if="activePanel === 'transcriptome'" class="grid grid-2">
              <article class="panel chart-panel">
                <div class="section-header compact">
                  <h3>Relationship Explorer</h3>
                  <select
                    v-if="derivedScatterOptions.length > 1"
                    class="input select-inline"
                    v-model="derivedScatterKey"
                  >
                    <option v-for="item in derivedScatterOptions" :key="item.key" :value="item.key">
                      {{ item.label }}
                    </option>
                  </select>
                </div>
                <EChart v-if="omicsSpecializedAvailable" :option="omicsSpecializedChart" :height="360" />
                <EmptyState
                  v-else
                  eyebrow="Missing fields"
                  title="Relationship Explorer"
                  :message="omicsSpecializedMissingMessage"
                />
                <div v-if="omicsSpecializedAvailable" class="annotation">{{ omicsSpecializedAnnotation }}</div>
                <ScatterInsightCard
                  v-if="omicsSpecializedAvailable"
                  :meta="omicsSpecializedMeta"
                  :title="omicsSpecializedTitle"
                />
                <CandidateLinkedTable
                  v-if="omicsSpecializedAvailable"
                  :candidates="omicsSpecializedCandidates"
                  :species-id="species.species_id"
                />
              </article>

              <article class="panel chart-panel">
                <div class="section-header compact">
                  <h3>Custom feature explorer</h3>
                  <div class="row">
                    <select class="input select-inline" v-model="customScatterX">
                      <option v-for="field in dynamicFieldOptions" :key="`x-deep-${field}`" :value="field">
                        X: {{ formatKey(field) }}
                      </option>
                    </select>
                    <select class="input select-inline" v-model="customScatterY">
                      <option v-for="field in dynamicFieldOptions" :key="`y-deep-${field}`" :value="field">
                        Y: {{ formatKey(field) }}
                      </option>
                    </select>
                    <button class="btn subtle" @click="loadCustomScatter" :disabled="customScatterLoading">
                      {{ customScatterLoading ? 'Loading...' : 'Refresh' }}
                    </button>
                  </div>
                </div>
                <EChart :option="customScatterChart" :height="360" />
                <div class="annotation">{{ customScatterAnnotation }}</div>
              </article>
            </section>

            <section v-if="activePanel !== 'genome' && activePanel !== 'transcriptome' && activePanel !== 'proteome'" class="panel">
              <div class="section-header compact"><h3>Candidate outlier overview</h3></div>
              <EChart :option="outlierRankingChart" :height="320" />
              <MethodBadge
                :method="omicsAnalysis.method_metadata?.outliers?.method || 'robust_zscore'"
                :normalization="omicsAnalysis.method_metadata?.outliers?.scale || 'robust z-score / score quantile'"
                :missing-policy="omicsAnalysis.method_metadata?.outliers?.missing_policy || 'valid numeric rows only'"
                :n="outlierRankingRows.length"
                exploratory
              />
              <div class="grid grid-2">
                <div>
                  <div class="label">High-score candidate outliers</div>
                  <div class="table-wrap">
                    <table class="table compact-table">
                      <thead>
                        <tr>
                          <th v-for="key in outlierHighColumns" :key="key">{{ key }}</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr v-for="(row, idx) in omicsAnalysis.outliers?.high || []" :key="idx">
                          <td v-for="key in outlierHighColumns" :key="key">{{ row[key] }}</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>

                <div>
                  <div class="label">Low-score candidate outliers</div>
                  <div class="table-wrap">
                    <table class="table compact-table">
                      <thead>
                        <tr>
                          <th v-for="key in outlierLowColumns" :key="key">{{ key }}</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr v-for="(row, idx) in omicsAnalysis.outliers?.low || []" :key="idx">
                          <td v-for="key in outlierLowColumns" :key="key">{{ row[key] }}</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            </section>
          </template>

          <template v-else-if="omicsTab === 'table'">
            <section class="panel">
              <div class="toolbar-grid wide">
                <input
                  class="input"
                  v-model="rowQuery"
                  placeholder="Search entity_id, gene_name, or description"
                  @keyup.enter="loadRows"
                />

                <select class="input" v-model="rowCluster">
                  <option value="">All strategy clusters</option>
                  <option
                    v-for="cluster in rowsPayload.strategy_clusters || []"
                    :key="cluster"
                    :value="cluster"
                  >
                    {{ cluster }}
                  </option>
                </select>

                <select class="input" v-model="featureFilterKey">
                  <option value="">Filter feature</option>
                  <option
                    v-for="feature in rowsPayload.feature_options || []"
                    :key="feature"
                    :value="feature"
                  >
                    {{ feature }}
                  </option>
                </select>

                <input class="input" v-model="featureFilterMin" type="number" step="0.0001" placeholder="Feature min" />
                <input class="input" v-model="featureFilterMax" type="number" step="0.0001" placeholder="Feature max" />

                <select class="input" v-model="sortBy">
                  <option value="">Default order</option>
                  <option
                    v-for="feature in rowsPayload.feature_options || []"
                    :key="feature"
                    :value="feature"
                  >
                    {{ feature }}
                  </option>
                </select>

                <button class="btn subtle" @click="resetTableFilters" :disabled="rowsLoading">Reset</button>
                <button class="btn" @click="loadRows({ force: true })" :disabled="rowsLoading">{{ rowsLoading ? 'Loading...' : 'Apply' }}</button>
              </div>
            </section>

            <section class="panel">
              <ModuleState v-if="rowsLoading" state="loading" title="Loading feature rows" message="Applying the current scope, filters, sort, and page settings." />
              <div class="table-wrap">
                <table class="table">
                  <thead>
                    <tr>
                      <th v-for="column in rowsPayload.columns || []" :key="column">{{ column }}</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="row in rowsPayload.rows || []"
                      :key="row.entity_id || row.gene_id || row.protein_id || row.transcript_id"
                    >
                      <td v-for="column in rowsPayload.columns || []" :key="column">{{ row[column] }}</td>
                      <td><a href="#" @click.prevent="showDetail(row)">detail</a></td>
                    </tr>
                  </tbody>
                </table>
              </div>

              <div class="row" style="justify-content: space-between; margin-top: 12px">
                <div class="muted">{{ rowsPayload.total || 0 }} rows</div>
                <div class="row">
                  <button class="btn subtle" @click="changePage(-1)" :disabled="page <= 1">Prev</button>
                  <span class="label">Page {{ page }}</span>
                  <button
                    class="btn subtle"
                    @click="changePage(1)"
                    :disabled="page * pageSize >= (rowsPayload.total || 0)"
                  >
                    Next
                  </button>
                </div>
              </div>
            </section>

            <section class="panel" v-if="detailPayload || detailLoading">
              <div class="section-header compact">
                <h3>Row detail and linked entities</h3>
                <router-link v-if="detailReportRoute" class="btn subtle" :to="detailReportRoute">Open entity report</router-link>
              </div>
              <ModuleState v-if="detailLoading" state="loading" title="Loading row detail" message="Retrieving the selected entity and its feature traceability." />
              <pre v-else>{{ JSON.stringify(detailPayload, null, 2) }}</pre>
            </section>
          </template>
        </template>

        <ModuleState
          v-else
          state="missing"
          :title="`${activePanel} module returned no summary payload`"
          message="The module request finished, but neither summary nor analysis payload was returned for the selected species, omics layer, and scope."
          suggestion="Check the OmicsDataset summary_payload and analysis_payload cache for this exact selection."
        />
      </template>
    </div>
    <EntityDrawer :entity="chartEntity" :species-id="species.species_id" @close="chartEntity = null" />
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import EChart from '../components/EChart.vue'
import CandidateLinkedTable from '../components/CandidateLinkedTable.vue'
import EmptyState from '../components/EmptyState.vue'
import EntityDrawer from '../components/EntityDrawer.vue'
import ProteomeWorkspace from '../components/proteome/ProteomeWorkspace.vue'
import SequenceWorkspace from '../components/sequence/SequenceWorkspace.vue'
import OverviewVisuals from '../components/integration/OverviewVisuals.vue'
import CrossOmicsWorkspace from '../components/integration/CrossOmicsWorkspace.vue'
import { useIntegrationVisuals } from '../composables/useIntegrationVisuals'
import { sequenceGet } from '../api/sequenceVisuals'
import { getProteomeManifest } from '../api/proteomeVisuals'
import MethodBadge from '../components/MethodBadge.vue'
import ModuleState from '../components/ModuleState.vue'
import ResultBlock from '../components/result/ResultBlock.vue'
import ScatterInsightCard from '../components/ScatterInsightCard.vue'
import {
  getCrossOmics,
  getOmicsBundle,
  getOmicsFieldSummary,
  getOmicsRowDetail,
  getOmicsRows,
  getOmicsScatter,
  getSpecies,
  getSpeciesEnhanced,
  getSpeciesFunctionalSummary,
  getSpeciesIdMappingSummary,
} from '../api/stoichdb'
import {
  areaHistOption,
  continuousProfileOption,
  histogramOption,
  barOption,
  buildEnhancedScatterOption,
  buildFormulaCardOption,
  buildIdentityScatterOption,
  buildLogScatterOption,
  buildOrdinationOption,
  buildQuadrantScatterOption,
  boxplotSummaryOption,
  donutOption,
  heatmapOption,
  matrixHeatmapOption,
  networkOptionSafe,
  parallelOption,
  rankLollipopOption,
  sankeyOption,
  scatterOption,
  treemapOption,
} from '../utils/charts'

const props = defineProps({
  speciesId: String,
})

const route = useRoute()
const router = useRouter()

const species = ref(null)
const cross = ref(null)
const speciesEnhanced = ref(null)
const speciesLoading = ref(false)
const crossLoading = ref(false)

const activePanel = ref('overview')
const omicsTab = ref('basic')
const omicsScope = ref('core')
const omicsCompute = ref('stored')
const proteomeV3Enabled = ref(true)
const isProteomeV3Active = computed(() => activePanel.value === 'proteome' && proteomeV3Enabled.value)
const sequenceEnabled = reactive({genome: import.meta.env.VITE_SEQUENCE_VIZ_GENOME_ENABLED !== '0', transcriptome: import.meta.env.VITE_SEQUENCE_VIZ_TRANSCRIPTOME_ENABLED !== '0'})
const isSequenceV1Active = computed(() => ['genome','transcriptome'].includes(activePanel.value) && sequenceEnabled[activePanel.value])
const isScientificVisualActive = computed(() => isProteomeV3Active.value || isSequenceV1Active.value)
const integrationFlags = {overview:import.meta.env.VITE_INTEGRATION_OVERVIEW_ENABLED !== '0',cross:import.meta.env.VITE_INTEGRATION_CROSS_ENABLED !== '0'}
const isIntegrationVisualActive = computed(() => Boolean(integrationFlags[activePanel.value]))
const integrationContext = useIntegrationVisuals(computed(() => props.speciesId), isIntegrationVisualActive)
function integrationEntity(entity) { handleEntityChartClick({detail:entity}) }
const availableScopes = ref(['core'])

const omicsSummary = ref(null)
const omicsAnalysis = ref(null)
const rowsPayload = ref({
  rows: [],
  columns: [],
  total: 0,
  strategy_clusters: [],
  feature_options: [],
})
const detailPayload = ref(null)
const chartEntity = ref(null)

const omicsLoading = ref(false)
const rowsLoading = ref(false)
const detailLoading = ref(false)
const omicsError = ref('')
const speciesError = ref('')
const crossError = ref('')
const idMappingSummary = ref(null)
const idMappingLoading = ref(false)
const idMappingError = ref('')
const functionalSummary = ref(null)
const functionalSummaryLoading = ref(false)
const functionalSummaryError = ref('')

const distributionKey = ref('')
const scatterKey = ref('')
const derivedScatterKey = ref('')
const omicsCorrMethod = ref('spearman')
const crossCorrMethod = ref('spearman')
const genomeEmbeddingMode = ref('umap')
const transcriptomeEmbeddingMode = ref('umap')
const proteomeEmbeddingMode = ref('umap')
const crossEmbeddingMode = ref('umap')
const customScatterX = ref('')
const customScatterY = ref('')
const customScatterPayload = ref(null)
const customScatterLoading = ref(false)
const fieldSummaryPayload = ref(null)
const couplingMinAbs = ref(0.5)

const rowQuery = ref('')
const rowCluster = ref('')
const sortBy = ref('')
const featureFilterKey = ref('')
const featureFilterMin = ref('')
const featureFilterMax = ref('')
const page = ref(1)
const pageSize = ref(12)

let speciesRequestSeq = 0
let omicsRequestSeq = 0
let rowsRequestSeq = 0
let detailRequestSeq = 0
let crossRequestSeq = 0
let fieldSummaryRequestSeq = 0
let customScatterRequestSeq = 0
let routeSyncInFlight = false

const speciesCache = new Map()
const crossCache = new Map()
const speciesEnhancedCache = new Map()
const functionalSummaryCache = new Map()
const panelCache = new Map()
const rowsCache = new Map()
const detailCache = new Map()
const fieldSummaryCache = new Map()
const customScatterCache = new Map()

const DERIVED_SCATTER_CONFIG = {
  promoter_vs_exon_gc: {
    label: 'Promoter vs exon GC',
    title: 'Genome regulatory-coding GC contrast',
    xKey: 'exon_gc_percent',
    yKey: 'promoter_gc_percent',
    xName: 'Exon GC%',
    yName: 'Promoter GC%',
    annotation: 'Each point is a gene-level promoter/exon pair. The chart shows whether regulatory GC tracks coding GC across the current species payload.',
    required: 'exon_gc_percent and promoter_gc_percent',
  },
  promoter_delta_vs_n: {
    label: 'GC delta vs N density',
    title: 'Genome promoter-exon delta and nitrogen density',
    xKey: 'promoter_exon_gc_delta',
    yKey: 'exon_atoms_N_per_base',
    xName: 'Promoter minus exon GC',
    yName: 'Exon N / base',
    annotation: 'Promoter-exon GC delta is computed per entity and compared with exon nitrogen density to expose regulatory-coding resource contrast.',
    required: 'promoter_exon_gc_delta and exon_atoms_N_per_base',
  },
  gc_delta_vs_n: {
    label: 'GC delta vs N density',
    title: 'Genome promoter-exon delta and nitrogen density',
    xKey: 'gc_delta_promoter_minus_exon',
    yKey: 'exon_atoms_N_per_base',
    xName: 'Promoter minus exon GC',
    yName: 'Exon N / base',
    annotation: 'Promoter-exon GC delta is computed per entity and compared with exon nitrogen density to expose regulatory-coding resource contrast.',
    required: 'gc_delta_promoter_minus_exon and exon_atoms_N_per_base',
  },
  gc3_vs_n: {
    label: 'GC3 vs N density',
    title: 'Genome coding strategy: GC3 vs N density',
    xKey: 'gc3_percent',
    yKey: 'exon_atoms_N_per_base',
    xName: 'GC3 (%)',
    yName: 'Exon N / base',
    annotation: 'GC3 and exon nitrogen density are shown as a coding-strategy proxy. Codon-level and dinucleotide heatmaps require explicit codon/dinucleotide columns in the release.',
    required: 'gc3_percent and exon_atoms_N_per_base',
  },
  gc12_vs_gc3: {
    label: 'Estimated GC12 vs GC3',
    title: 'Genome codon-position GC contrast',
    xKey: 'gc12_percent_estimated',
    yKey: 'gc3_percent',
    xName: 'Estimated GC12 (%)',
    yName: 'GC3 (%)',
    annotation: 'GC12 is estimated as (3 * exon GC - GC3) / 2 where exon GC and GC3 are available, then compared with third-position GC.',
    required: 'exon_gc_percent and gc3_percent',
  },
  gc_vs_entropy: {
    label: 'RNA GC vs entropy',
    title: 'Transcript sequence complexity landscape',
    xKey: 'gc_content',
    yKey: 'nt_entropy',
    xName: 'RNA GC%',
    yName: 'nt entropy',
    annotation: 'Transcript GC content is plotted against nucleotide entropy to separate simple composition shifts from broader sequence-complexity changes.',
    required: 'gc_content and nt_entropy',
  },
  gc_vs_rna_mw: {
    label: 'RNA GC vs estimated MW',
    title: 'Transcript GC and estimated RNA NMP mass',
    xKey: 'gc_content',
    yKey: 'mw_rna_nmp_per_nt_Da_estimated',
    xName: 'RNA GC fraction',
    yName: 'Estimated RNA NMP MW (Da)',
    annotation: 'Average RNA NMP mass is estimated from GC content under balanced A/U and C/G composition assumptions.',
    required: 'gc_content',
  },
  rna_n_vs_cn_ratio: {
    label: 'RNA N vs estimated C/N',
    title: 'Transcript nitrogen cost and estimated C/N balance',
    xKey: 'atoms_per_nt_N',
    yKey: 'C_N_ratio_estimated',
    xName: 'RNA N / nt',
    yName: 'Estimated C/N',
    annotation: 'Estimated RNA C/N uses canonical RNA NMP carbon under balanced base assumptions divided by observed N/nt.',
    required: 'atoms_per_nt_N',
  },
  coupling_vs_gravy: {
    label: 'ORF coupling vs GRAVY proxy',
    title: 'Transcript ORF-to-protein proxy landscape',
    xKey: 'rna_orf_coupling_score',
    yKey: 'protein_gravy_proxy',
    xName: 'RNA-ORF coupling',
    yName: 'Protein GRAVY proxy',
    annotation: 'RNA-ORF coupling and protein GRAVY proxy are predicted from transcript-derived fields. This is not measured proteome evidence.',
    required: 'rna_orf_coupling_score and protein_gravy_proxy',
  },
  resource_n_vs_coding_density: {
    label: 'RNA N vs coding density',
    title: 'Transcript nitrogen cost and coding-density tradeoff',
    xKey: 'atoms_per_nt_N',
    yKey: 'coding_density_proxy',
    xName: 'RNA N / nt',
    yName: 'Coding density proxy',
    annotation: 'Nitrogen cost per nucleotide is compared with coding-density proxy values to show resource allocation patterns in transcript features.',
    required: 'atoms_per_nt_N and coding_density_proxy',
  },
  n_vs_pi: {
    label: 'Protein N vs pI',
    title: 'Proteome charge-resource spectrum',
    xKey: 'N_atoms_per_aa',
    yKey: 'pI',
    xName: 'N / aa',
    yName: 'pI',
    annotation: 'N/aa versus pI summarizes intrinsic charge-resource structure. Values are sequence-derived and not expression weighted.',
    required: 'N_atoms_per_aa and pI',
  },
  pi_vs_gravy: {
    label: 'pI vs GRAVY',
    title: 'Proteome charge-hydropathy landscape',
    xKey: 'pI',
    yKey: 'gravy',
    xName: 'pI',
    yName: 'GRAVY',
    annotation: 'pI and GRAVY are sequence-derived physicochemical descriptors, useful for screening charge and hydropathy regimes across proteins.',
    required: 'pI and gravy',
  },
  n_vs_s_resource: {
    label: 'Protein N vs S',
    title: 'Proteome nitrogen-sulfur resource budget',
    xKey: 'N_atoms_per_aa',
    yKey: 'S_atoms_per_aa',
    xName: 'N / aa',
    yName: 'S / aa',
    annotation: 'Nitrogen and sulfur atoms per amino acid are plotted together to expose amino-acid resource-budget differences between proteins.',
    required: 'N_atoms_per_aa and S_atoms_per_aa',
  },
  n_vs_ns_ratio: {
    label: 'Protein N vs N/S',
    title: 'Proteome nitrogen-sulfur ratio spectrum',
    xKey: 'N_atoms_per_aa',
    yKey: 'N_S_ratio',
    xName: 'N / aa',
    yName: 'N/S ratio',
    annotation: 'N/S ratio is computed directly from N_atoms_per_aa and S_atoms_per_aa when sulfur density is non-zero.',
    required: 'N_atoms_per_aa and S_atoms_per_aa',
  },
  sulfur_frac_vs_gravy: {
    label: 'Sulfur fraction vs GRAVY',
    title: 'Proteome sulfur-resource and hydropathy landscape',
    xKey: 'sulfur_aa_frac_estimated',
    yKey: 'gravy',
    xName: 'Estimated sulfur-aa fraction',
    yName: 'GRAVY',
    annotation: 'Sulfur amino-acid fraction is estimated from S_atoms_per_aa under the canonical assumption that Cys/Met each contribute one sulfur atom.',
    required: 'S_atoms_per_aa and gravy',
  },
  length_vs_resource_budget: {
    label: 'Length vs budget score',
    title: 'Proteome length and resource-budget score',
    xKey: 'length_aa',
    yKey: 'resource_budget_score',
    xName: 'Protein length (aa)',
    yName: 'Resource budget score',
    annotation: 'Protein length is compared with the release-provided resource budget score to show whether long proteins concentrate high-cost compositions.',
    required: 'length_aa and resource_budget_score',
  },
  s_vs_disulfide: {
    label: 'S vs disulfide density',
    title: 'Proteome sulfur-disulfide proxy',
    xKey: 'S_atoms_per_aa',
    yKey: 'disulfide_density',
    xName: 'S / aa',
    yName: 'Disulfide density',
    annotation: 'This panel is only meaningful when explicit disulfide-density fields are present in the release.',
    required: 'S_atoms_per_aa and disulfide_density',
  },
}

const DERIVED_SCATTER_PRIORITY = {
  genome: ['promoter_delta_vs_n', 'gc12_vs_gc3'],
  transcriptome: ['gc_vs_entropy', 'resource_n_vs_coding_density'],
  proteome: ['n_vs_pi', 'pi_vs_gravy', 'sulfur_frac_vs_gravy', 'length_vs_resource_budget', 's_vs_disulfide'],
}

const FORMULA_SCATTER_KEYS = new Set(['gc_vs_rna_mw', 'rna_n_vs_cn_ratio', 'n_vs_ns_ratio'])
const DUPLICATE_DEFAULT_SCATTER_KEYS = new Set(['promoter_vs_exon_gc', 'gc3_vs_n', 'n_vs_s_resource'])

const isOmicsPanel = computed(() =>
  ['genome', 'transcriptome', 'proteome'].includes(activePanel.value),
)

const currentOmicsCard = computed(() =>
  (species.value?.omics_cards || []).find((item) => item.omics === activePanel.value) || null,
)

const detailReportRoute = computed(() => {
  const row = detailPayload.value?.row || detailPayload.value || {}
  const entityKey = (isSequenceV1Active.value && (activePanel.value === 'transcriptome' ? row.transcript_id : row.gene_id)) || (isProteomeV3Active.value && row.protein_id) || row.gene_id || row.ensembl_gene_id || row.entity_id || row.protein_id || row.transcript_id
  if (!species.value?.species_id || !entityKey) return ''
  return `/species/${encodeURIComponent(species.value.species_id)}/entity/${encodeURIComponent(entityKey)}`
})

const distributionKeys = computed(() => {
  const fromDistributions = Object.keys(omicsSummary.value?.distributions || {})
  if (fromDistributions.length) return fromDistributions
  return dynamicFieldOptions.value
})

const scatterKeys = computed(() =>
  Object.keys(omicsSummary.value?.scatter || {}),
)

function scatterConfig(key) {
  const inferred = String(key || '').split('_vs_')
  const inferredX = inferred.length === 2 ? inferred[0] : 'x'
  const inferredY = inferred.length === 2 ? inferred[1] : 'y'
  return DERIVED_SCATTER_CONFIG[key] || {
    label: formatScatterLabel(key),
    title: formatScatterLabel(key),
    xKey: inferredX,
    yKey: inferredY,
    xName: formatKey(inferredX),
    yName: formatKey(inferredY),
    annotation: 'This scatter plot is supplied by the current omics summary payload.',
    required: key,
  }
}

function availableScatterKeys(scatterPayload = {}, panel = activePanel.value) {
  const keys = Object.keys(scatterPayload || {}).filter((key) =>
    (scatterPayload?.[key] || []).length &&
    !FORMULA_SCATTER_KEYS.has(key) &&
    !DUPLICATE_DEFAULT_SCATTER_KEYS.has(key),
  )
  const priority = DERIVED_SCATTER_PRIORITY[panel] || []
  return [
    ...priority.filter((key) => keys.includes(key)),
    ...keys.filter((key) => !priority.includes(key)),
  ]
}

function scatterMetaFor(key) {
  return omicsSummary.value?.scatter_meta?.[key] || {}
}

function handleEntityChartClick(event) {
  const raw = event?.detail || {}
  if (!raw.entity_id && !raw.gene_id && !raw.protein_id && !raw.transcript_id) return
  chartEntity.value = { ...raw, species_id: raw.species_id || species.value?.species_id }
}

function enhancedScatter(points, config, key = '', options = {}) {
  const meta = options.meta || scatterMetaFor(key)
  if (FORMULA_SCATTER_KEYS.has(key)) {
    const replacement = meta?.replacement_payload || {}
    return buildFormulaCardOption(
      replacement.title || config.title,
      replacement.formula || 'Derived ratio / formula relationship',
      replacement.reason || config.annotation,
    )
  }
  if (options.kind === 'identity') {
    return buildIdentityScatterOption(points, config.xKey, config.yKey, config.xName, config.yName, { ...options, meta, title: config.title })
  }
  if (options.kind === 'quadrant') {
    return buildQuadrantScatterOption(points, config.xKey, config.yKey, config.xName, config.yName, { ...options, meta, title: config.title })
  }
  if (options.kind === 'log') {
    return buildLogScatterOption(points, config.xKey, config.yKey, config.xName, config.yName, { ...options, meta, title: config.title })
  }
  return buildEnhancedScatterOption(points, config.xKey, config.yKey, config.xName, config.yName, { ...options, meta, title: config.title })
}

function preferredDerivedScatterKey(scatterPayload = {}, panel = activePanel.value) {
  return availableScatterKeys(scatterPayload, panel)[0] || ''
}

function setCustomScatterDefaults(summary = omicsSummary.value, panel = activePanel.value) {
  const preferredKey = preferredDerivedScatterKey(summary?.scatter || {}, panel)
  if (preferredKey) {
    const config = scatterConfig(preferredKey)
    customScatterX.value = config.xKey || ''
    customScatterY.value = config.yKey || config.xKey || ''
    return
  }
  customScatterX.value = dynamicFieldOptions.value[0] || ''
  customScatterY.value = dynamicFieldOptions.value[1] || dynamicFieldOptions.value[0] || ''
}

const derivedScatterOptions = computed(() =>
  availableScatterKeys(omicsSummary.value?.scatter || {}, activePanel.value).map((key) => ({
    key,
    ...scatterConfig(key),
  })),
)

const activeDerivedScatterKey = computed(() => {
  if (derivedScatterOptions.value.some((item) => item.key === derivedScatterKey.value)) {
    return derivedScatterKey.value
  }
  return derivedScatterOptions.value[0]?.key || ''
})

const dynamicFieldOptions = computed(() => {
  const fromMeta = (omicsSummary.value?.field_meta || [])
    .map((item) => item?.field)
    .filter(Boolean)
  const fromCards = Object.keys(omicsSummary.value?.feature_cards || {})
  const fromRows = rowsPayload.value?.feature_options || []
  const merged = [...fromMeta, ...fromCards, ...fromRows]
  return [...new Set(merged)]
})

const omicsCorrMethods = computed(() => {
  const keys = Object.keys(omicsSummary.value?.correlation_matrices || {})
  if (keys.length) return keys
  return ['spearman']
})

const crossCorrMethods = computed(() => {
  const keys = Object.keys(cross.value?.correlation_matrices || {})
  if (keys.length) return keys
  return ['spearman']
})

const featureSummaryCards = computed(() =>
  Object.entries(omicsSummary.value?.feature_cards || {}).map(([key, value]) => ({
    key,
    ...value,
  })),
)

function cardNumber(...keys) {
  const cards = omicsSummary.value?.feature_cards || {}
  for (const key of keys) {
    const payload = cards[key]
    const value = Number(payload?.mean ?? payload?.p50 ?? payload?.value)
    if (Number.isFinite(value)) return value
  }
  return null
}

const omicsFirstScreenRows = computed(() => {
  if (activePanel.value === 'genome') {
    return [
      { name: 'Promoter GC', value: cardNumber('promoter_gc_percent') },
      { name: 'Exon GC', value: cardNumber('exon_gc_percent') },
      { name: 'Promoter - exon GC', value: cardNumber('promoter_exon_gc_delta', 'gc_delta_promoter_minus_exon') },
      { name: 'Estimated GC12', value: cardNumber('gc12_percent_estimated') },
      { name: 'GC3', value: cardNumber('gc3_percent') },
      { name: 'Promoter N/base', value: cardNumber('promoter_atoms_N_per_base') },
      { name: 'Exon N/base', value: cardNumber('exon_atoms_N_per_base') },
      { name: 'Stoich island', value: cardNumber('stoich_island_score') },
    ].filter((row) => row.value !== null)
  }
  if (activePanel.value === 'transcriptome') {
    return [
      { name: 'RNA GC', value: cardNumber('gc_content', 'gc_percent_display') },
      { name: 'NT entropy', value: cardNumber('nt_entropy') },
      { name: 'Estimated C / nt', value: cardNumber('atoms_per_nt_C_estimated') },
      { name: 'N / nt', value: cardNumber('atoms_per_nt_N') },
      { name: 'P / nt', value: cardNumber('atoms_per_nt_P') },
      { name: 'Estimated C/N', value: cardNumber('C_N_ratio_estimated') },
      { name: 'N/P', value: cardNumber('N_P_ratio') },
      { name: 'Estimated NMP MW', value: cardNumber('mw_rna_nmp_per_nt_Da_estimated') },
      { name: 'Coding density', value: cardNumber('coding_density_proxy') },
      { name: 'RNA-ORF coupling', value: cardNumber('rna_orf_coupling_score') },
      { name: 'Protein GRAVY proxy', value: cardNumber('protein_gravy_proxy') },
    ].filter((row) => row.value !== null)
  }
  if (activePanel.value === 'proteome') {
    return [
      { name: 'N / aa', value: cardNumber('N_atoms_per_aa') },
      { name: 'S / aa', value: cardNumber('S_atoms_per_aa') },
      { name: 'N/S', value: cardNumber('N_S_ratio') },
      { name: 'Sulfur aa frac', value: cardNumber('sulfur_aa_frac_estimated') },
      { name: 'Length', value: cardNumber('length_aa') },
      { name: 'pI', value: cardNumber('pI') },
      { name: 'GRAVY', value: cardNumber('gravy') },
      { name: 'Budget score', value: cardNumber('resource_budget_score') },
      { name: 'Instability', value: cardNumber('instability_index', 'instability') },
      { name: 'Aromaticity', value: cardNumber('aromaticity') },
    ].filter((row) => row.value !== null)
  }
  return []
})

const omicsFirstScreenTitle = computed(() => {
  if (activePanel.value === 'genome') return 'Regulatory-coding stoichiometric contrast'
  if (activePanel.value === 'transcriptome') return 'RNA resource profile and ORF/protein proxy preview'
  if (activePanel.value === 'proteome') return 'Proteome resource budget and physicochemical spectrum'
  return 'Omics summary profile'
})

const omicsFirstScreenAnnotation = computed(() => {
  if (activePanel.value === 'genome') {
    return 'Promoter and exon features are compared from species-level summary statistics. Promoter-minus-exon GC is a computed contrast; the zero line is the meaningful reference for interpreting direction.'
  }
  if (activePanel.value === 'transcriptome') {
    return 'RNA resource fields summarize nucleotide composition and element-per-nt profiles. ORF/protein proxy fields are predicted from transcript-derived features and are not measured proteome abundance.'
  }
  if (activePanel.value === 'proteome') {
    return 'Proteome fields summarize sequence-intrinsic atom density and physicochemical properties. Values are not expression weighted unless the source payload explicitly provides abundance weighting.'
  }
  return ''
})

const omicsFirstScreenMethod = computed(() => ({
  method: activePanel.value === 'genome'
    ? 'species summary means and computed promoter-exon delta'
    : activePanel.value === 'transcriptome'
      ? 'species summary means from transcript feature table'
      : 'species summary means from proteome feature table',
  normalization: 'raw feature units',
  missingPolicy: 'display available summary fields only',
  n: omicsSummary.value?.row_count || currentOmicsCard.value?.row_count || '',
  exploratory: activePanel.value !== 'genome',
}))

const omicsFirstScreenChart = computed(() =>
  barOption(
    omicsFirstScreenRows.value.map((row) => row.name),
    omicsFirstScreenRows.value.map((row) => row.value),
    'Mean value',
    true,
  ),
)

const previewColumns = computed(() =>
  Object.keys(omicsSummary.value?.preview_rows?.[0] || {}),
)

const enhancedVisuals = computed(() =>
  speciesEnhanced.value || species.value?.enhanced_visuals || {},
)

const enhancedRankRows = computed(() =>
  enhancedVisuals.value?.global_feature_rank || [],
)

const overviewFingerprintChart = computed(() => {
  const fingerprint = {
    ...(species.value?.fingerprint || {}),
    ...(crossModule('X7').fingerprint || {}),
  }
  const rows = Object.entries(fingerprint)
    .map(([key, value]) => ({ key, value: Number(value) }))
    .filter((row) => Number.isFinite(row.value))
    .sort((a, b) => Math.abs(b.value) - Math.abs(a.value))
    .slice(0, 10)
  return barOption(rows.map((row) => formatKey(row.key)), rows.map((row) => row.value), 'Value', true)
})

const genomeIslandProfileChart = computed(() =>
  continuousProfileOption(
    enhancedVisuals.value?.coordinate_profiles?.genome_stoich_island || { centers: [], counts: [] },
    'Genome coordinate',
    'Mean stoich-island score',
  ),
)

const genomeDeltaProfileChart = computed(() =>
  continuousProfileOption(
    enhancedVisuals.value?.coordinate_profiles?.genome_gc_delta || { centers: [], counts: [] },
    'Genome coordinate',
    'Mean promoter-exon GC delta',
  ),
)

const dnaToRnaShiftChart = computed(() =>
  histogramOption(
    crossModule('X1').shift_histograms?.dna_to_rna_n_std || enhancedVisuals.value?.shift_histograms?.dna_to_rna_n_std || { centers: [], counts: [] },
    'DNA to RNA N shift std (robust-z delta)',
    'Count',
    { minPoints: 1, method: 'binned numeric distribution; a single zero bin means the matched rows have no DNA-to-RNA N-shift variance' },
  ),
)

const rnaToProteinShiftChart = computed(() =>
  histogramOption(
    crossModule('X1').shift_histograms?.rna_to_protein_n_std || enhancedVisuals.value?.shift_histograms?.rna_to_protein_n_std || { centers: [], counts: [] },
    'RNA to protein N shift std (robust-z delta)',
    'Count',
    { minPoints: 1 },
  ),
)

const transitionProbabilityLinks = computed(() => {
  const links = enhancedVisuals.value?.cluster_transition_links || []
  const totals = links.reduce((acc, link) => {
    acc[link.source] = (acc[link.source] || 0) + Number(link.value || 0)
    return acc
  }, {})
  return links.map((link) => {
    const total = totals[link.source] || 1
    const probability = (Number(link.value || 0) / total) * 100
    return {
      ...link,
      value: Number(probability.toFixed(4)),
      raw_count: link.value,
    }
  })
})

const clusterTransitionChart = computed(() =>
  sankeyOption(transitionProbabilityLinks.value),
)

const resourceBudgetChart = computed(() =>
  rankLollipopOption(
    (enhancedVisuals.value?.resource_budget_breakdown || []).map((row) => ({
      name: row.feature,
      value: row.mean,
    })),
    'name',
    'value',
    'Mean',
  ),
)

function overviewOmicsRowCount(omics) {
  return species.value?.omics_cards?.find((card) => card.omics === omics)?.row_count || 0
}

const currentFieldMeta = computed(() =>
  (omicsSummary.value?.field_meta || []).find((item) => item.field === distributionKey.value) || null,
)

const distributionSummary = computed(() =>
  fieldSummaryPayload.value?.summary || omicsSummary.value?.feature_cards?.[distributionKey.value] || null,
)

const distributionChart = computed(() =>
  areaHistOption(
    fieldSummaryPayload.value?.distribution || omicsSummary.value?.distributions?.[distributionKey.value],
    formatKey(distributionKey.value),
    'Count',
  ),
)

const distributionBoxplot = computed(() =>
  boxplotSummaryOption(distributionSummary.value, formatKey(distributionKey.value)),
)

const omicsCorrMatrix = computed(() => {
  const matrices = omicsSummary.value?.correlation_matrices || {}
  return matrices[omicsCorrMethod.value] || omicsSummary.value?.correlation_matrix || {}
})

const omicsCorrDetails = computed(() => {
  const edges = omicsSummary.value?.coupling_edges || []
  const method = omicsAnalysis.value?.method_metadata?.coupling_network?.method || omicsCorrMethod.value
  return (edges || []).map((edge) => ({
    feature_a: edge.source,
    feature_b: edge.target,
    r: edge.weight,
    n: edge.n,
    p_value: edge.p_value,
    fdr: edge.fdr,
    method,
  }))
})

const couplingHeatmap = computed(() =>
  heatmapOption(omicsCorrMatrix.value, {
    details: omicsCorrDetails.value,
    method: omicsAnalysis.value?.method_metadata?.coupling_network?.method || omicsCorrMethod.value,
    evidenceLevel: omicsAnalysis.value?.evidence_level || 'exploratory',
    missingPolicy: omicsAnalysis.value?.method_metadata?.outliers?.missing_policy || 'pairwise_complete',
  }),
)

const crossCorrMatrix = computed(() => {
  const matrices = cross.value?.correlation_matrices || {}
  return matrices[crossCorrMethod.value] || cross.value?.correlation_matrix || {}
})

const crossCorrDetails = computed(() =>
  cross.value?.correlation_details || [],
)

const crossJoinSummary = computed(() => cross.value?.join_summary || {})

const crossCoverageAnnotation = computed(() => {
  const summary = crossJoinSummary.value || {}
  const allThree = Number(summary.match_rate_all_three || 0) * 100
  const gt = Number(summary.match_rate_genome_transcriptome || 0) * 100
  const tp = Number(summary.match_rate_transcriptome_proteome || 0) * 100
  const corrMethod = crossCorrMethod.value || 'spearman'
  return `Genome->transcript sequence match ${gt.toFixed(2)}%, transcript sequence->proteome match ${tp.toFixed(2)}%, all-three match ${allThree.toFixed(2)}%. Correlation matrix currently displays ${corrMethod.toUpperCase()} associations and should be interpreted as exploratory statistical coupling.`
})

const crossHeatmap = computed(() =>
  heatmapOption(crossCorrMatrix.value, {
    details: crossCorrDetails.value,
    method: cross.value?.method_metadata?.correlation?.method || crossCorrMethod.value,
    evidenceLevel: cross.value?.evidence_level || 'exploratory',
    nFallback: crossJoinSummary.value?.matched_all_three || null,
    missingPolicy: cross.value?.method_metadata?.correlation?.missing_policy || 'pairwise_complete',
  }),
)

const crossScatter = computed(() =>
  scatterOption(
    cross.value?.cross_points || [],
    'exon_gc_percent',
    'N_atoms_per_aa',
    'Genome exon GC%',
    'Proteome N / aa',
  ),
)

const crossShiftRows = computed(() => {
  const rows = cross.value?.top_transformations || cross.value?.transformations || []
  return (rows || [])
    .map((row) => ({
      ...row,
      dna_to_rna_n_shift_std: Number(row.dna_to_rna_n_shift_std ?? row.dna_to_rna_n_delta),
      rna_to_protein_n_shift_std: Number(row.rna_to_protein_n_shift_std ?? row.rna_to_protein_n_delta),
      entity_id: row.gene_name || row.gene_id || row.entity_id,
    }))
    .filter((row) => Number.isFinite(row.dna_to_rna_n_shift_std) && Number.isFinite(row.rna_to_protein_n_shift_std))
})

const crossShiftPairChart = computed(() =>
  buildQuadrantScatterOption(
    crossShiftRows.value,
    'dna_to_rna_n_shift_std',
    'rna_to_protein_n_shift_std',
    'DNA to RNA N shift std',
    'RNA to protein N shift std',
    { title: 'DNA-RNA-Protein resource-shift quadrants' },
  ),
)

const crossShiftQuadrantChart = computed(() => {
  const counts = {
    'RNA up / protein up': 0,
    'RNA up / protein down': 0,
    'RNA down / protein up': 0,
    'RNA down / protein down': 0,
  }
  crossShiftRows.value.forEach((row) => {
    const dnaUp = row.dna_to_rna_n_shift_std >= 0
    const proteinUp = row.rna_to_protein_n_shift_std >= 0
    if (dnaUp && proteinUp) counts['RNA up / protein up'] += 1
    else if (dnaUp && !proteinUp) counts['RNA up / protein down'] += 1
    else if (!dnaUp && proteinUp) counts['RNA down / protein up'] += 1
    else counts['RNA down / protein down'] += 1
  })
  return donutOption(Object.entries(counts).map(([name, value]) => ({ name, value })))
})

const crossShiftRankChart = computed(() =>
  rankLollipopOption(
    crossShiftRows.value
      .map((row) => ({
        name: row.gene_name || row.gene_id || row.entity_id,
        value: Math.abs(row.dna_to_rna_n_shift_std) + Math.abs(row.rna_to_protein_n_shift_std),
      }))
      .sort((a, b) => b.value - a.value)
      .slice(0, 20),
    'name',
    'value',
    'Abs shift sum',
  ),
)

const crossModuleSuite = computed(() => cross.value?.cross_omics_module_suite || null)
const crossModules = computed(() => crossModuleSuite.value?.modules || [])
const crossQualityFlags = computed(() => crossModuleSuite.value?.quality_flags || {})
const crossExportTables = computed(() => crossModuleSuite.value?.export_tables || {})
const crossMappingSummary = computed(() => cross.value?.mapping_summary || {})
const crossMappingCoverage = computed(() => crossMappingSummary.value?.coverage || crossJoinSummary.value || {})
const crossX0Finding = computed(() => {
  const allThree = formatPercent(crossMappingCoverage.value?.all_three)
  const conflicts = crossMappingSummary.value?.conflict_count || 0
  return `All-three mapping coverage is ${allThree}; ${conflicts} mapping conflict(s) are reported for this payload.`
})
const crossX0Downloads = computed(() => [
  {
    label: 'Payload JSON',
    filename: `${species.value?.species_id || 'species'}_cross_x0_payload.json`,
    payload: {
      join_summary: crossJoinSummary.value,
      mapping_summary: crossMappingSummary.value,
      module: crossModule('X0'),
    },
  },
])

function crossModule(id) {
  return crossModules.value.find((module) => module.id === id) || {}
}

function crossModuleMethod(id) {
  return crossModule(id).method || crossModuleSuite.value?.method_metadata?.method || ''
}

const crossModuleCards = computed(() =>
  crossModules.value.map((module) => ({
    id: module.id,
    name: module.name,
    status: module.status || 'partial',
    missing_count: (module.missing_fields || []).length,
  })),
)

const crossX0CoverageChart = computed(() => {
  const rows = crossModule('X0').match_coverage_rows || []
  return barOption(rows.map((row) => row.name), rows.map((row) => Number(row.value || 0)), 'Rows', true)
})

const crossX0RateChart = computed(() => {
  const rows = crossModule('X0').match_rate_rows || []
  return barOption(rows.map((row) => row.name), rows.map((row) => Number(row.value || 0) * 100), 'Match rate %', true)
})

const crossX1DnaRnaChart = computed(() =>
  histogramOption(crossModule('X1').shift_histograms?.dna_to_rna_n_std || { centers: [], counts: [] }, 'DNA to RNA N shift std (robust-z delta)', 'Matched genes'),
)

const crossX1RnaProteinChart = computed(() =>
  histogramOption(crossModule('X1').shift_histograms?.rna_to_protein_n_std || { centers: [], counts: [] }, 'RNA to protein N shift std (robust-z delta)', 'Matched genes'),
)

const crossX1ScatterChart = computed(() =>
  buildQuadrantScatterOption(crossModule('X1').shift_scatter || [], 'dna_to_rna_n_shift_std', 'rna_to_protein_n_shift_std', 'DNA to RNA N shift std', 'RNA to protein N shift std', {
    meta: crossModule('X1').shift_scatter_meta || crossModule('X1').resource_shift_reference,
    title: 'X1 standardized DNA-RNA-Protein resource-shift quadrants',
  }),
)

const crossX1QuadrantChart = computed(() =>
  donutOption(crossModule('X1').quadrants || []),
)

const crossX1CandidateRows = computed(() =>
  crossExportTables.value?.['cross_omics_resource_shift.csv'] || crossModule('X1').candidate_table || [],
)

const crossX2ResidualRows = computed(() => crossModule('X2').residual_candidates || [])

const crossX2ScatterChart = computed(() => {
  const primary = crossModule('X2').exon_transcript_gc_scatter || []
  if (primary.length) {
    return buildIdentityScatterOption(primary, 'exon_gc_percent', 'transcript_gc', 'Exon GC%', 'Transcript GC', {
      meta: crossModule('X2').exon_transcript_gc_scatter_meta,
      title: 'X2 exon-transcript GC consistency',
    })
  }
  return buildEnhancedScatterOption(crossX2ResidualRows.value, 'dna_to_rna_gc_delta', 'rna_to_protein_n_shift_std', 'DNA to RNA GC delta', 'RNA to protein N shift std', {
    meta: crossModule('X2').exon_transcript_gc_scatter_meta,
    title: 'X2 residual candidate fallback',
    subtitle: 'The source payload lacks paired exon/transcript GC fields; the chart uses real candidate-level GC delta and RNA-protein N shift values.',
  })
})

const crossX3DiscordanceRows = computed(() => crossModule('X3').discordance_candidates || [])

const crossX3GcProteinNChart = computed(() => {
  const primary = crossModule('X3').gc_protein_n_scatter || []
  if (primary.length) {
    return buildEnhancedScatterOption(primary, 'transcript_gc', 'proteome_n_per_aa', 'Transcript GC', 'Protein N / aa', {
      meta: crossModule('X3').gc_protein_n_scatter_meta,
      title: 'X3 transcript GC vs protein N/aa',
    })
  }
  return buildEnhancedScatterOption(crossX3DiscordanceRows.value, 'rna_to_protein_n_shift_std', 'discordance_score', 'RNA to protein N shift std', 'Discordance score', {
    meta: crossModule('X3').gc_protein_n_scatter_meta,
    title: 'X3 translation-discordance fallback',
    subtitle: 'Transcript GC and protein N/aa paired fields are absent; the chart uses real candidate shift and discordance values.',
  })
})

const crossX3GcPiChart = computed(() => {
  const primary = crossModule('X3').gc_pi_scatter || []
  if (primary.length) {
    return buildEnhancedScatterOption(primary, 'transcript_gc', 'pI', 'Transcript GC', 'Observed proteome pI', {
      meta: crossModule('X3').gc_pi_scatter_meta,
      title: 'X3 transcript GC vs observed proteome pI',
    })
  }
  return buildEnhancedScatterOption(crossX3DiscordanceRows.value, 'pI', 'discordance_score', 'Observed proteome pI', 'Discordance score', {
    meta: crossModule('X3').gc_pi_scatter_meta,
    title: 'X3 pI-linked discordance fallback',
    subtitle: 'The source payload lacks transcript GC pairs; the chart uses real proteome pI and candidate discordance values.',
  })
})

const crossX3GcGravyChart = computed(() => {
  const primary = crossModule('X3').gc_gravy_scatter || []
  if (primary.length) {
    return buildEnhancedScatterOption(primary, 'transcript_gc', 'gravy', 'Transcript GC', 'Observed proteome GRAVY', {
      meta: crossModule('X3').gc_gravy_scatter_meta,
      title: 'X3 transcript GC vs observed proteome GRAVY',
    })
  }
  return buildEnhancedScatterOption(crossX3DiscordanceRows.value, 'gravy', 'discordance_score', 'Observed proteome GRAVY', 'Discordance score', {
    meta: crossModule('X3').gc_gravy_scatter_meta,
    title: 'X3 GRAVY-linked discordance fallback',
    subtitle: 'The source payload lacks transcript GC pairs; the chart uses real GRAVY and candidate discordance values.',
  })
})

const crossX4CandidateRows = computed(() =>
  crossExportTables.value?.['cross_omics_predicted_observed_residuals.csv'] || crossModule('X4').candidate_table || [],
)

const crossX4PiResidualChart = computed(() => {
  const primary = crossModule('X4').residual_scatter || []
  if (primary.some((row) => Number.isFinite(Number(row?.transcript_protein_pi)) && Number.isFinite(Number(row?.pI)))) {
    return buildIdentityScatterOption(primary, 'transcript_protein_pi', 'pI', 'Transcript-predicted pI', 'Observed proteome pI', {
      title: 'X4 predicted vs observed protein pI',
      meta: { source: 'matched transcriptome/proteome rows' },
    })
  }
  if (primary.some((row) => Number.isFinite(Number(row?.proteome_pI ?? row?.pI)) && Number.isFinite(Number(row?.candidate_score)))) {
    const rows = primary.map((row) => ({ ...row, pI: row?.pI ?? row?.proteome_pI }))
    return buildEnhancedScatterOption(rows, 'pI', 'candidate_score', 'Observed proteome pI', 'Integrated candidate score', {
      title: 'X4 Complete core proteome pI residual proxy',
      subtitle: 'Complete core computes this panel from current-species core gene chains; no stored predicted-pI artifact is reused.',
      meta: crossModule('X4').residual_scatter_meta,
    })
  }
  return buildEnhancedScatterOption(crossX4CandidateRows.value, 'protein_pi_residual', 'candidate_score', 'pI residual', 'Residual score', {
    title: 'X4 residual candidate fallback',
    subtitle: 'Predicted/observed paired pI values are absent; candidate-level residual scores are shown when available.',
  })
})

const crossX5SharedChart = computed(() =>
  donutOption(crossModule('X5').shared_outlier_counts || []),
)

const crossX6HeatmapChart = computed(() => {
  const payload = crossModule('X6').correlation_heatmap || {}
  return matrixHeatmapOption(payload.x_labels || [], payload.y_labels || [], payload.values || [], {
    min: -1,
    max: 1,
    details: payload.details || [],
  })
})

const crossX6EdgeRows = computed(() =>
  (crossModule('X6').edge_ranking || [])
    .map((row) => {
      const r = Number(row.r ?? row.weight ?? row.correlation)
      const featureA = row.feature_a || row.source_feature || row.source || row.x || ''
      const featureB = row.feature_b || row.target_feature || row.target || row.y || ''
      return {
        ...row,
        feature_a: featureA,
        feature_b: featureB,
        r: Number.isFinite(r) ? Number(r.toFixed(6)) : row.r,
        abs_r: Number.isFinite(r) ? Number(Math.abs(r).toFixed(6)) : row.abs_r,
        p_value: row.p_value ?? row.p ?? null,
        fdr: row.fdr ?? row.q_value ?? null,
        n: row.n ?? row.pair_n ?? null,
        method: row.method || 'feature_correlation',
      }
    })
    .filter((row) => row.feature_a && row.feature_b),
)

function crossProjectionEmbedding(payload = {}) {
  const useUmap = crossEmbeddingMode.value === 'umap' && (payload?.umap_points || []).length
  return {
    method: useUmap ? 'UMAP' : 'PCA',
    points: useUmap ? (payload?.umap_points || []) : (payload?.points || []),
    xKey: useUmap ? 'umap1' : 'pc1',
    yKey: useUmap ? 'umap2' : 'pc2',
    xLabel: useUmap ? 'UMAP1' : pcaAxisLabel('PC1', payload?.explained_variance_ratio || []),
    yLabel: useUmap ? 'UMAP2' : pcaAxisLabel('PC2', payload?.explained_variance_ratio || []),
    params: payload?.umap_params || {},
  }
}

function crossProjectionAnnotation(payload = {}) {
  const embedding = crossProjectionEmbedding(payload)
  if (embedding.method === 'UMAP') {
    const params = embedding.params || {}
    return `UMAP on cross-omics species fingerprint; n_neighbors=${params.n_neighbors ?? '-'}, min_dist=${params.min_dist ?? '-'}, random_state=${params.random_state ?? '-'}`
  }
  return `PCA/SVD on cross-omics species fingerprint; ${pcaAxisLabel('PC1', payload?.explained_variance_ratio || [])}, ${pcaAxisLabel('PC2', payload?.explained_variance_ratio || [])}`
}

const crossX7FingerprintRows = computed(() => {
  return fingerprintProfileRows(crossModule('X7'), 12)
})

const crossX7FingerprintChart = computed(() =>
  fingerprintProfileBarOption(crossX7FingerprintRows.value, 'Cross-omics fingerprint profile'),
)

const crossX7SpeciesChart = computed(() => {
  const embedding = crossProjectionEmbedding(crossModule('X7').species_pca || {})
  const points = (embedding.points || []).map((row) => ({
    ...row,
    entity_id: row.display_name || row.species_id,
  }))
  return buildOrdinationOption(points, embedding.xKey, embedding.yKey, embedding.xLabel, embedding.yLabel, {
    title: 'X7 cross-omics species ordination',
    currentSpeciesId: props.speciesId,
    meta: crossModule('X7').species_pca?.ordination_meta,
  })
})

const crossX7DistanceChart = computed(() => {
  const payload = crossModule('X7').distance_matrix || {}
  return matrixHeatmapOption(payload.x_labels || [], payload.y_labels || [], payload.values || [], {
    min: 0,
    max: 2,
    distance: true,
    scaleType: payload.scale_type || 'distance',
    method: payload.method,
  })
})

const crossX7FeatureRows = computed(() => crossModule('X7').feature_ranking || [])
const crossX8CandidateRows = computed(() => crossModule('X8').candidate_table || [])

const crossImplementationNotes = computed(() =>
  crossModules.value.flatMap((module) =>
    (module.missing_fields || []).map((field) => ({
      module: `${module.id} ${module.name}`,
      missing: field,
      status: module.status || 'partial',
    })),
  ),
)

const centroidChart = computed(() =>
  parallelOption(omicsSummary.value?.cluster_centroids || []),
)

const filteredCouplingEdges = computed(() =>
  (omicsSummary.value?.coupling_edges || [])
    .filter((edge) => Math.abs(Number(edge.weight || 0)) >= couplingMinAbs.value)
    .slice(0, 30),
)

const networkChart = computed(() =>
  networkOptionSafe(filteredCouplingEdges.value),
)

const tradeoffChart = computed(() =>
  scatterOption(
    omicsAnalysis.value?.tradeoff_front || [],
    'cost_axis',
    'adapt_axis',
    'Cost axis',
    'Adaptive axis',
    'front_score',
  ),
)

const outlierHighColumns = computed(() =>
  Object.keys(omicsAnalysis.value?.outliers?.high?.[0] || {}),
)

const outlierLowColumns = computed(() =>
  Object.keys(omicsAnalysis.value?.outliers?.low?.[0] || {}),
)

const outlierRankingRows = computed(() => {
  const rows = [
    ...(omicsAnalysis.value?.outliers?.high || []).map((row) => ({ ...row, direction: 'high' })),
    ...(omicsAnalysis.value?.outliers?.low || []).map((row) => ({ ...row, direction: 'low' })),
    ...(omicsAnalysis.value?.outliers?.multivariate || []).map((row) => ({ ...row, direction: 'multivariate' })),
  ]
  return rows
    .map((row) => ({
      name: row.gene_name || row.gene_id || row.transcript_id || row.protein_id || row.entity_id || row.direction,
      value: Number(row.outlier_score ?? row.score ?? row.strategy_score ?? row.robust_zscore ?? 0),
    }))
    .filter((row) => Number.isFinite(row.value))
    .sort((a, b) => Math.abs(b.value) - Math.abs(a.value))
    .slice(0, 20)
})

const outlierRankingChart = computed(() =>
  rankLollipopOption(outlierRankingRows.value, 'name', 'value', 'Outlier score'),
)

const tradeoffFormulaNote = computed(() => {
  const formula = omicsAnalysis.value?.method_metadata?.tradeoff_front?.formula || {}
  if (!Object.keys(formula).length) return 'Cost axis is minimized and adapt axis is maximized; results are exploratory Pareto candidates.'
  return `cost_axis: ${formula.cost_axis || 'minimize'}; adapt_axis: ${formula.adapt_axis || 'maximize'}.`
})

const scatterChart = computed(() => {
  const config = scatterConfig(scatterKey.value)
  return enhancedScatter(
    omicsSummary.value?.scatter?.[scatterKey.value] || [],
    config,
    scatterKey.value,
  )
})

const customScatterChart = computed(() =>
  scatterOption(
    customScatterPayload.value?.points || [],
    customScatterX.value,
    customScatterY.value,
    customScatterPayload.value?.x_meta?.label || formatKey(customScatterX.value),
    customScatterPayload.value?.y_meta?.label || formatKey(customScatterY.value),
  ),
)

const omicsSpecializedKey = computed(() => activeDerivedScatterKey.value)

const omicsSpecializedAvailable = computed(() =>
  Boolean(omicsSpecializedKey.value && (omicsSummary.value?.scatter?.[omicsSpecializedKey.value] || []).length),
)

const omicsSpecializedMeta = computed(() =>
  scatterMetaFor(omicsSpecializedKey.value),
)

const omicsSpecializedCandidates = computed(() =>
  omicsSpecializedMeta.value?.candidates || [],
)

const omicsSpecializedTitle = computed(() => {
  if (omicsSpecializedKey.value) return scatterConfig(omicsSpecializedKey.value).title
  return 'Specialized omics module'
})

const omicsSpecializedChart = computed(() => {
  const config = scatterConfig(omicsSpecializedKey.value)
  return enhancedScatter(
    omicsSummary.value?.scatter?.[omicsSpecializedKey.value] || [],
    config,
    omicsSpecializedKey.value,
  )
})

const omicsSpecializedAnnotation = computed(() => {
  if (omicsSpecializedKey.value) return scatterConfig(omicsSpecializedKey.value).annotation
  return omicsFutureMessage.value
})

const omicsSpecializedMissingMessage = computed(() =>
  `${omicsSpecializedTitle.value} requires ${scatterConfig(omicsSpecializedKey.value).required || 'fields'} that are not populated in this species/release payload.`,
)

const omicsFutureEyebrow = computed(() => {
  if (activePanel.value === 'genome') return 'Codon / dinucleotide'
  if (activePanel.value === 'transcriptome') return 'ORF length / codon usage'
  if (activePanel.value === 'proteome') return 'pI vs GRAVY / ridge plots'
  return 'Future module'
})

const omicsFutureTitle = computed(() => {
  if (activePanel.value === 'genome') return 'Codon and dinucleotide heatmaps need explicit fields'
  if (activePanel.value === 'transcriptome') return 'ORF length and codon-usage panels need ORF columns'
  if (activePanel.value === 'proteome') return 'Full physicochemical distribution needs GRAVY and class-fraction fields'
  return 'External or missing feature module'
})

const omicsFutureMessage = computed(() => {
  if (activePanel.value === 'genome') {
    return 'The current release exposes GC3 and N-density strategy proxies, but does not expose codon or dinucleotide count columns for a real heatmap.'
  }
  if (activePanel.value === 'transcriptome') {
    return 'The current release exposes RNA resource and ORF-proxy scores, but not ORF length or codon-usage matrices for this panel.'
  }
  if (activePanel.value === 'proteome') {
    return 'The current release exposes N/aa and pI for this species. GRAVY, instability, aromaticity, and residue-fraction distributions are displayed only when populated.'
  }
  return 'This module is intentionally empty until the required data are imported.'
})

const derivedVisualPanels = computed(() => {
  const raw = omicsSummary.value?.derived_visual_panels
  if (Array.isArray(raw)) return raw
  if (!raw || typeof raw !== 'object') return []
  const missingModules = raw.missing_modules || []
  return Object.entries(raw)
    .filter(([key, value]) => key !== 'missing_modules' && value && typeof value === 'object')
    .map(([key, value]) => ({
      key,
      omics: activePanel.value,
      ...value,
      missing_modules: value.missing_modules || missingModules,
    }))
})

const derivedVisualPanel = computed(() =>
  derivedVisualPanels.value.find((panel) => panel.omics === activePanel.value) || derivedVisualPanels.value[0] || null,
)

const derivedVisualRows = computed(() =>
  (derivedVisualPanel.value?.rows || [])
    .map((row) => ({
      ...row,
      available: Boolean(row.available ?? (row.value !== undefined && row.value !== null)),
      status: row.status || (row.value !== undefined && row.value !== null ? 'available' : 'missing'),
      mean: row.mean ?? row.value,
    }))
    .filter((row) => row.available || row.status === 'missing'),
)

const derivedVisualAnnotation = computed(() => {
  const panel = derivedVisualPanel.value
  if (!panel) return ''
  const available = (panel.rows || []).filter((row) => row.available).length
  const missing = (panel.missing_modules || []).map(formatMissingModule).filter(Boolean).join('; ')
  return `${available} feature groups are available from the current ${activePanel.value} data. Missing document-requested modules: ${missing || 'none reported'}.`
})

const genomeModuleSuite = computed(() => omicsSummary.value?.genome_module_suite || null)
const transcriptomeModuleSuite = computed(() => omicsSummary.value?.transcriptome_module_suite || null)
const proteomeModuleSuite = computed(() => omicsSummary.value?.proteome_module_suite || null)

const currentOmicsLabel = computed(() => {
  if (activePanel.value === 'genome') return 'Genome'
  if (activePanel.value === 'transcriptome') return 'Transcriptome'
  if (activePanel.value === 'proteome') return 'Proteome'
  return formatKey(activePanel.value)
})

const omicsComputeLabel = computed(() =>
  omicsCompute.value === 'complete_core'
    ? 'Complete core rows'
    : 'Fast stored payload',
)

const currentOmicsModuleSuite = computed(() => {
  if (activePanel.value === 'genome') return genomeModuleSuite.value
  if (activePanel.value === 'transcriptome') return transcriptomeModuleSuite.value
  if (activePanel.value === 'proteome') return proteomeModuleSuite.value
  return null
})

const currentOmicsModuleSuiteState = computed(() => {
  if (!['genome', 'transcriptome', 'proteome'].includes(activePanel.value)) return 'ready'
  if (currentOmicsModuleSuite.value) return 'ready'
  return 'missing'
})

const currentOmicsModuleSuiteMissingMessage = computed(() =>
  `${currentOmicsLabel.value} summary and analysis metadata were returned for ${species.value?.display_name || props.speciesId}, but the ${activePanel.value}_module_suite object is empty for scope=${omicsScope.value}. The charts below are therefore intentionally withheld instead of reusing another module's data.`,
)

const genomeModules = computed(() => genomeModuleSuite.value?.modules || [])
const transcriptomeModules = computed(() => transcriptomeModuleSuite.value?.modules || [])
const proteomeModules = computed(() => proteomeModuleSuite.value?.modules || [])

function genomeModule(id) {
  return genomeModules.value.find((module) => module.id === id) || {}
}

function genomeModuleMethod(id) {
  return genomeModule(id).method || genomeModuleSuite.value?.method_metadata?.method || ''
}

function transcriptomeModule(id) {
  return transcriptomeModules.value.find((module) => module.id === id) || {}
}

function transcriptomeModuleMethod(id) {
  return transcriptomeModule(id).method || transcriptomeModuleSuite.value?.method_metadata?.method || ''
}

function proteomeModule(id) {
  return proteomeModules.value.find((module) => module.id === id) || {}
}

function proteomeModuleMethod(id) {
  return proteomeModule(id).method || proteomeModuleSuite.value?.method_metadata?.method || ''
}

function pcaAxisLabel(axisName, ratios = []) {
  const index = axisName === 'PC1' ? 0 : 1
  const value = Number(ratios?.[index] || 0)
  if (!value) return axisName
  return `${axisName} (${(value * 100).toFixed(1)}%)`
}

function genomeProjectionEmbedding(payload = {}) {
  const useUmap = genomeEmbeddingMode.value === 'umap' && (payload?.umap_points || []).length
  return {
    method: useUmap ? 'UMAP' : 'PCA',
    points: useUmap ? (payload?.umap_points || []) : (payload?.points || []),
    xKey: useUmap ? 'umap1' : 'pc1',
    yKey: useUmap ? 'umap2' : 'pc2',
    xLabel: useUmap ? 'UMAP1' : pcaAxisLabel('PC1', payload?.explained_variance_ratio || []),
    yLabel: useUmap ? 'UMAP2' : pcaAxisLabel('PC2', payload?.explained_variance_ratio || []),
    params: payload?.umap_params || {},
  }
}

function genomeProjectionAnnotation(payload = {}) {
  const embedding = genomeProjectionEmbedding(payload)
  if (embedding.method === 'UMAP') {
    const params = embedding.params || {}
    return `UMAP on the same standardized feature matrix; n_neighbors=${params.n_neighbors ?? '-'}, min_dist=${params.min_dist ?? '-'}, random_state=${params.random_state ?? '-'}`
  }
  return `PCA/SVD on the standardized feature matrix; ${pcaAxisLabel('PC1', payload?.explained_variance_ratio || [])}, ${pcaAxisLabel('PC2', payload?.explained_variance_ratio || [])}`
}

function transcriptomeProjectionEmbedding(payload = {}) {
  const useUmap = transcriptomeEmbeddingMode.value === 'umap' && (payload?.umap_points || []).length
  return {
    method: useUmap ? 'UMAP' : 'PCA',
    points: useUmap ? (payload?.umap_points || []) : (payload?.points || []),
    xKey: useUmap ? 'umap1' : 'pc1',
    yKey: useUmap ? 'umap2' : 'pc2',
    xLabel: useUmap ? 'UMAP1' : pcaAxisLabel('PC1', payload?.explained_variance_ratio || []),
    yLabel: useUmap ? 'UMAP2' : pcaAxisLabel('PC2', payload?.explained_variance_ratio || []),
    params: payload?.umap_params || {},
  }
}

function transcriptomeProjectionAnnotation(payload = {}) {
  const embedding = transcriptomeProjectionEmbedding(payload)
  if (embedding.method === 'UMAP') {
    const params = embedding.params || {}
    return `UMAP on robust z-scored transcript features; n_neighbors=${params.n_neighbors ?? '-'}, min_dist=${params.min_dist ?? '-'}, random_state=${params.random_state ?? '-'}`
  }
  return `PCA/SVD on robust z-scored transcript features; ${pcaAxisLabel('PC1', payload?.explained_variance_ratio || [])}, ${pcaAxisLabel('PC2', payload?.explained_variance_ratio || [])}`
}

function proteomeProjectionEmbedding(payload = {}) {
  const useUmap = proteomeEmbeddingMode.value === 'umap' && (payload?.umap_points || []).length
  return {
    method: useUmap ? 'UMAP' : 'PCA',
    points: useUmap ? (payload?.umap_points || []) : (payload?.points || []),
    xKey: useUmap ? 'umap1' : 'pc1',
    yKey: useUmap ? 'umap2' : 'pc2',
    xLabel: useUmap ? 'UMAP1' : pcaAxisLabel('PC1', payload?.explained_variance_ratio || []),
    yLabel: useUmap ? 'UMAP2' : pcaAxisLabel('PC2', payload?.explained_variance_ratio || []),
    params: payload?.umap_params || {},
  }
}

function proteomeProjectionAnnotation(payload = {}) {
  const embedding = proteomeProjectionEmbedding(payload)
  if (embedding.method === 'UMAP') {
    const params = embedding.params || {}
    return `UMAP on robust z-scored protein features; n_neighbors=${params.n_neighbors ?? '-'}, min_dist=${params.min_dist ?? '-'}, random_state=${params.random_state ?? '-'}`
  }
  return `PCA/SVD on robust z-scored protein features; ${pcaAxisLabel('PC1', payload?.explained_variance_ratio || [])}, ${pcaAxisLabel('PC2', payload?.explained_variance_ratio || [])}`
}

function genomeMissingText(module) {
  const missing = module?.missing_fields || []
  const warnings = module?.warnings || []
  return [...missing, ...warnings].join('; ') || 'No missing fields reported.'
}

const genomeUnavailableModules = computed(() =>
  genomeModules.value.filter((module) => module.status !== 'implemented'),
)

const genomeEvidenceBanner = computed(() => {
  const metadata = genomeModuleSuite.value?.method_metadata || {}
  const source = genomeModuleSuite.value?.scope === 'full_registered_csv'
    ? 'core rows are stored in PostgreSQL; full CSV is read on demand for deep Genome modules'
    : 'current requested scope is used directly'
  return `${source}. Evidence level: ${metadata.evidence_level || 'descriptive / hypothesis-generating'}; missing policy: ${metadata.missing_policy || 'available fields only'}.`
})

const genomeKeyFeatureRows = computed(() => {
  const cards = omicsSummary.value?.feature_cards || {}
  const fingerprint = genomeModule('G8').fingerprint || {}
  const fields = [
    ['exon_gc_percent', 'Exon GC'],
    ['promoter_gc_percent', 'Promoter GC'],
    ['promoter_exon_gc_delta', 'Promoter - exon GC'],
    ['exon_atoms_N_per_base', 'Exon N/base'],
    ['stoich_island_score', 'Stoich island'],
    ['gc3_percent', 'GC3'],
  ]
  return fields
    .map(([field, label]) => {
      const card = cards[field] || {}
      const value = Number(card.mean ?? card.p50 ?? fingerprint[field])
      return Number.isFinite(value) ? { field, label, value } : null
    })
    .filter(Boolean)
})

const genomeKeyFeatureChart = computed(() =>
  barOption(
    genomeKeyFeatureRows.value.map((row) => row.label),
    genomeKeyFeatureRows.value.map((row) => row.value),
    'Mean value',
    true,
  ),
)

const genomeG1RegionChart = computed(() => {
  const rows = genomeModule('G1').region_comparison || []
  return barOption(
    rows.map((row) => `${row.region} ${row.feature}`),
    rows.map((row) => Number(row.mean || 0)),
    'Mean value',
    true,
  )
})

const genomeG2DeltaChart = computed(() =>
  histogramOption(genomeModule('G2').delta_histogram || { centers: [], counts: [] }, 'Promoter - exon GC delta', 'Gene count'),
)

const genomeG2ScatterChart = computed(() =>
  buildIdentityScatterOption(
    genomeModule('G2').promoter_exon_scatter || [],
    'exon_gc_percent',
    'promoter_gc_percent',
    'Exon GC%',
    'Promoter GC%',
    {
      meta: genomeModule('G2').promoter_exon_scatter_meta,
      title: 'G2 promoter-exon GC consistency',
    },
  ),
)

const genomeG2FieldSummary = computed(() => {
  const cards = genomeModule('G2').cards || {}
  return `promoter_exon_gc_delta = promoter_gc_percent - exon_gc_percent. Positive ratio ${cards.positive_delta_ratio ?? '-'}, negative ratio ${cards.negative_delta_ratio ?? '-'}, median delta ${cards.median_delta ?? '-'}.`
})

const genomeG2TopDeltaRows = computed(() => [
  ...(genomeModule('G2').top_positive_delta || []).slice(0, 6).map((row) => ({ ...row, direction: 'positive' })),
  ...(genomeModule('G2').top_negative_delta || []).slice(0, 6).map((row) => ({ ...row, direction: 'negative' })),
])

const genomeG1PcaChart = computed(() =>
  {
    const embedding = genomeProjectionEmbedding(genomeModule('G1').pca || {})
    return buildOrdinationOption(embedding.points, embedding.xKey, embedding.yKey, embedding.xLabel, embedding.yLabel, {
      title: 'G1 gene-level multivariate overview',
      meta: genomeModule('G1').pca?.ordination_meta,
    })
  },
)

const genomeG1EmbeddingAnnotation = computed(() => genomeProjectionAnnotation(genomeModule('G1').pca || {}))

const genomeG1CouplingChart = computed(() => {
  const heatmap = genomeModule('G1').coupling_heatmap || {}
  return matrixHeatmapOption(heatmap.x_labels || [], heatmap.y_labels || [], heatmap.values || [], {
    min: -1,
    max: 1,
    details: heatmap.details || [],
  })
})

const genomeG2ContrastPcaChart = computed(() =>
  {
    const embedding = genomeProjectionEmbedding(genomeModule('G2').contrast_pca || {})
    return buildOrdinationOption(embedding.points, embedding.xKey, embedding.yKey, embedding.xLabel, embedding.yLabel, {
      title: 'G2 promoter-exon contrast ordination',
      meta: genomeModule('G2').contrast_pca?.ordination_meta,
    })
  },
)

const genomeG2EmbeddingAnnotation = computed(() => genomeProjectionAnnotation(genomeModule('G2').contrast_pca || {}))

const genomeG2ClusterChart = computed(() =>
  donutOption(genomeModule('G2').contrast_cluster_counts || []),
)

const genomeG3SkewChart = computed(() =>
  histogramOption(genomeModule('G3').gc_skew_histogram || { centers: [], counts: [] }, 'Locus GC skew', 'Gene count'),
)

const genomeG3CumulativeChart = computed(() =>
  continuousProfileOption(genomeModule('G3').cumulative_gc_skew || { centers: [], counts: [] }, 'Genome coordinate order', 'Cumulative GC skew', { method: 'continuous cumulative GC skew profile; empty bins stay missing' }),
)

const genomeG4DinucHeatmap = computed(() => {
  const heatmap = genomeModule('G4').heatmap || {}
  return matrixHeatmapOption(heatmap.x_labels || [], heatmap.y_labels || [], heatmap.values || [], { min: 0, max: 0.2 })
})

const genomeG4DistanceChart = computed(() =>
  histogramOption(genomeModule('G4').distance_histogram || { centers: [], counts: [] }, 'Dinuc distance from background', 'Gene count'),
)

const genomeG4PromoterPcaChart = computed(() =>
  {
    const embedding = genomeProjectionEmbedding(genomeModule('G4').promoter_signature_pca || {})
    return buildOrdinationOption(embedding.points, embedding.xKey, embedding.yKey, embedding.xLabel, embedding.yLabel, {
      title: 'G4 promoter signature ordination',
      meta: genomeModule('G4').promoter_signature_pca?.ordination_meta,
    })
  },
)

const genomeG4PromoterEmbeddingAnnotation = computed(() => genomeProjectionAnnotation(genomeModule('G4').promoter_signature_pca || {}))

const genomeG4SpeciesPcaChart = computed(() => {
  const embedding = genomeProjectionEmbedding(genomeModule('G4').cross_species_dinuc_pca || {})
  const points = (embedding.points || []).map((row) => ({
    ...row,
    entity_id: row.display_name || row.species_id,
  }))
  return buildOrdinationOption(points, embedding.xKey, embedding.yKey, embedding.xLabel, embedding.yLabel, {
    title: 'G4 cross-species dinucleotide ordination',
    currentSpeciesId: props.speciesId,
    meta: genomeModule('G4').cross_species_dinuc_pca?.ordination_meta,
  })
})

const genomeG4SpeciesEmbeddingAnnotation = computed(() => genomeProjectionAnnotation(genomeModule('G4').cross_species_dinuc_pca || {}))

const genomeG5GcChart = computed(() => {
  const rows = (genomeModule('G5').gc_position_cards || [])
    .filter((row) => row.mean !== undefined && row.mean !== null)
  return barOption(
    rows.map((row) => row.label || row.field),
    rows.map((row) => Number(row.mean || 0)),
    'GC percent',
    true,
  )
})

const genomeG5CodonHeatmap = computed(() => {
  const heatmap = genomeModule('G5').codon_heatmap || {}
  return matrixHeatmapOption(heatmap.x_labels || [], heatmap.y_labels || [], heatmap.values || [], { min: 0, max: 0.08 })
})

const genomeG5EntropyChart = computed(() =>
  histogramOption(genomeModule('G5').codon_entropy_histogram || { centers: [], counts: [] }, 'Codon entropy bits', 'Coding gene count'),
)

const genomeG5AaChart = computed(() =>
  barOption(
    (genomeModule('G5').aa_composition || []).map((row) => row.name),
    (genomeModule('G5').aa_composition || []).map((row) => Number(row.value || 0)),
    'Mean AA frequency',
    true,
  ),
)

const genomeG5CodonPcaChart = computed(() =>
  {
    const embedding = genomeProjectionEmbedding(genomeModule('G5').codon_strategy_pca || {})
    return buildOrdinationOption(embedding.points, embedding.xKey, embedding.yKey, embedding.xLabel, embedding.yLabel, {
      title: 'G5 codon strategy ordination',
      meta: genomeModule('G5').codon_strategy_pca?.ordination_meta,
    })
  },
)

const genomeG5EmbeddingAnnotation = computed(() => genomeProjectionAnnotation(genomeModule('G5').codon_strategy_pca || {}))

const genomeG5ClusterChart = computed(() =>
  donutOption(genomeModule('G5').codon_strategy_cluster_counts || []),
)

const genomeG6ProfileChart = computed(() =>
  continuousProfileOption(genomeModule('G6').coordinate_profile || { centers: [], counts: [] }, 'Genome coordinate bins', 'Mean island score', { method: 'continuous stoichiometric island coordinate profile; empty bins stay missing' }),
)

const genomeG6ScoreChart = computed(() =>
  histogramOption(genomeModule('G6').score_histogram || { centers: [], counts: [] }, 'Stoich island score', 'Gene count'),
)

const genomeG6TopGenes = computed(() => genomeModule('G6').top_island_genes || [])

const genomeG6HotspotRows = computed(() => genomeModule('G6').hotspot_windows || [])

const genomeG7BiotypeChart = computed(() =>
  donutOption(genomeModule('G7').biotype_counts || []),
)

const genomeG7LengthScatter = computed(() =>
  buildLogScatterOption(
    genomeModule('G7').length_vs_gc_scatter || [],
    'gene_length_bp',
    'exon_gc_percent',
    'Gene length (bp)',
    'Exon GC%',
    {
      meta: genomeModule('G7').length_vs_gc_scatter_meta,
      title: 'G7 gene length vs exon GC',
    },
  ),
)

const genomeG8FingerprintChart = computed(() => {
  return fingerprintProfileBarOption(fingerprintProfileRows(genomeModule('G8'), 24), 'Genome fingerprint profile')
})

const genomeG8FeatureRanking = computed(() => genomeModule('G8').feature_ranking || [])

const genomeG8SpeciesPcaChart = computed(() => {
  const embedding = genomeProjectionEmbedding(genomeModule('G8').species_pca || {})
  const points = (embedding.points || []).map((row) => ({
    ...row,
    entity_id: row.display_name || row.species_id,
  }))
  return buildOrdinationOption(points, embedding.xKey, embedding.yKey, embedding.xLabel, embedding.yLabel, {
    title: 'G8 genome species ordination',
    currentSpeciesId: props.speciesId,
    meta: genomeModule('G8').species_pca?.ordination_meta,
  })
})

const genomeG8EmbeddingAnnotation = computed(() => genomeProjectionAnnotation(genomeModule('G8').species_pca || {}))

const genomeG8DistanceChart = computed(() => {
  const heatmap = genomeModule('G8').distance_matrix || {}
  return matrixHeatmapOption(heatmap.x_labels || [], heatmap.y_labels || [], heatmap.values || [], {
    min: 0,
    max: 2,
    distance: true,
    scaleType: heatmap.scale_type || 'distance',
    method: heatmap.method,
  })
})

const genomeCandidateRows = computed(() => {
  const g1Rows = (genomeModule('G1').outlier_ranking || []).slice(0, 6).map((row) => ({
    ...row,
    module: 'G1 profile',
  }))
  const skewRows = (genomeModule('G3').skew_outlier_genes || []).slice(0, 6).map((row) => ({
    ...row,
    module: 'G3 skew',
    value: row.locus_gc_skew ?? row.robust_z,
  }))
  const dinucRows = (genomeModule('G4').anomaly_ranking || []).slice(0, 6).map((row) => ({
    ...row,
    module: 'G4 dinuc',
  }))
  const codonRows = (genomeModule('G5').codon_anomaly_genes || []).slice(0, 6).map((row) => ({
    ...row,
    module: 'G5 codon',
  }))
  return [...g1Rows, ...skewRows, ...dinucRows, ...codonRows]
})

const genomeGlobalOutlierRows = computed(() => [
  ...genomeCandidateRows.value,
  ...genomeG2TopDeltaRows.value.slice(0, 8).map((row) => ({ ...row, module: `G2 delta ${row.direction}` })),
  ...genomeG6TopGenes.value.slice(0, 8).map((row) => ({ ...row, module: 'G6 island' })),
])

const genomeStrategyClusterChart = computed(() => {
  const rows = [
    ...(genomeModule('G2').contrast_cluster_counts || []).map((row) => ({ name: `G2 ${row.name}`, value: row.value })),
    ...(genomeModule('G5').codon_strategy_cluster_counts || []).map((row) => ({ name: `G5 ${row.name}`, value: row.value })),
  ]
  return donutOption(rows)
})

const transcriptomeEvidenceBanner = computed(() => {
  const metadata = transcriptomeModuleSuite.value?.method_metadata || {}
  const source = transcriptomeModuleSuite.value?.scope === 'full_registered_csv'
    ? 'core rows are stored in PostgreSQL; registered full CSV is read on demand for codon/bias/spacing fields'
    : 'current requested scope is used directly'
  return `${source}. Evidence level: ${metadata.evidence_level || 'descriptive / hypothesis-generating'}; missing policy: ${metadata.missing_policy || 'available fields only'}.`
})

const transcriptomeKeyFeatureChart = computed(() => {
  const cards = transcriptomeModule('T1').cards || {}
  const t2 = transcriptomeModule('T2').cards || {}
  const t5 = transcriptomeModule('T5').cards || {}
  const rows = [
    ['GC', cards.gc_content?.mean],
    ['Entropy', cards.nt_entropy?.mean],
    ['N / nt', t2.atoms_per_nt_N?.mean],
    ['P / nt', t2.atoms_per_nt_P?.mean],
    ['N/P', t2.N_P_ratio?.mean],
    ['ORF valid', t5.coding_valid_ratio],
  ].filter((row) => row[1] !== undefined && row[1] !== null)
  return barOption(rows.map((row) => row[0]), rows.map((row) => Number(row[1] || 0)), 'Mean / ratio', true)
})

const transcriptomeT1BaseChart = computed(() =>
  barOption(
    (transcriptomeModule('T1').base_composition || []).map((row) => row.name),
    (transcriptomeModule('T1').base_composition || []).map((row) => Number(row.value || 0)),
    'Mean fraction',
    true,
  ),
)

const transcriptomeT1GcChart = computed(() =>
  histogramOption(transcriptomeModule('T1').gc_histogram || { centers: [], counts: [] }, 'GC content', 'Transcript count'),
)

const transcriptomeT1LengthChart = computed(() =>
  histogramOption(transcriptomeModule('T1').length_histogram || { centers: [], counts: [] }, 'Transcript length', 'Transcript count'),
)

const transcriptomeT2ElementChart = computed(() =>
  barOption(
    (transcriptomeModule('T2').element_profile || []).map((row) => row.name),
    (transcriptomeModule('T2').element_profile || []).map((row) => Number(row.value || 0)),
    'Mean fraction / atoms per nt',
    true,
  ),
)

const transcriptomeT2NpChart = computed(() =>
  histogramOption(transcriptomeModule('T2').np_ratio_histogram || { centers: [], counts: [] }, 'N/P ratio', 'Transcript count'),
)

const transcriptomeT2ProjectionChart = computed(() => {
  const embedding = transcriptomeProjectionEmbedding(transcriptomeModule('T2').resource_projection || {})
  return buildOrdinationOption(embedding.points, embedding.xKey, embedding.yKey, embedding.xLabel, embedding.yLabel, {
    title: 'T2 RNA stoich-space ordination',
    meta: transcriptomeModule('T2').resource_projection?.ordination_meta,
  })
})

const transcriptomeT2ProjectionNote = computed(() => transcriptomeProjectionAnnotation(transcriptomeModule('T2').resource_projection || {}))

const transcriptomeT2ClusterChart = computed(() => donutOption(transcriptomeModule('T2').resource_cluster_counts || []))

const transcriptomeT3DinucHeatmap = computed(() => {
  const heatmap = transcriptomeModule('T3').dinuc_heatmap || {}
  return matrixHeatmapOption(heatmap.x_labels || [], heatmap.y_labels || [], heatmap.values || [], { min: 0, max: 0.2 })
})

const transcriptomeT3StabilityChart = computed(() =>
  histogramOption(transcriptomeModule('T3').stability_histogram || { centers: [], counts: [] }, 'Stability proxy', 'Transcript count'),
)

const transcriptomeT3ProjectionChart = computed(() => {
  const embedding = transcriptomeProjectionEmbedding(transcriptomeModule('T3').dinuc_projection || {})
  return buildOrdinationOption(embedding.points, embedding.xKey, embedding.yKey, embedding.xLabel, embedding.yLabel, {
    title: 'T3 sequence-pattern ordination',
    meta: transcriptomeModule('T3').dinuc_projection?.ordination_meta,
  })
})

const transcriptomeT3ProjectionNote = computed(() => transcriptomeProjectionAnnotation(transcriptomeModule('T3').dinuc_projection || {}))

const transcriptomeT3CouplingChart = computed(() => {
  const heatmap = transcriptomeModule('T3').pattern_coupling_heatmap || {}
  return matrixHeatmapOption(heatmap.x_labels || [], heatmap.y_labels || [], heatmap.values || [], { min: -1, max: 1, details: heatmap.details || [] })
})

const transcriptomeT4BiotypeChart = computed(() => donutOption(transcriptomeModule('T4').biotype_counts || []))

const transcriptomeT4LengthByBiotypeChart = computed(() =>
  barOption(
    (transcriptomeModule('T4').length_by_biotype || []).map((row) => row.group),
    (transcriptomeModule('T4').length_by_biotype || []).map((row) => Number(row.median || row.mean || 0)),
    'Median length',
    true,
  ),
)

const transcriptomeT5OrfLengthChart = computed(() =>
  histogramOption(transcriptomeModule('T5').orf_length_histogram || { centers: [], counts: [] }, 'ORF length aa', 'Transcript count'),
)

const transcriptomeT5OrfScatter = computed(() =>
  buildIdentityScatterOption(transcriptomeModule('T5').orf_vs_transcript_scatter || [], 'length_nt_acgu', 'orf_len_nt', 'Transcript length', 'ORF length nt', {
    meta: transcriptomeModule('T5').orf_vs_transcript_scatter_meta,
    title: 'T5 transcript length vs ORF length',
  }),
)

const transcriptomeT5OrfMatrix = computed(() => {
  const heatmap = transcriptomeModule('T5').biotype_orf_matrix || {}
  return matrixHeatmapOption(heatmap.x_labels || [], heatmap.y_labels || [], heatmap.values || [], { min: 0 })
})

const transcriptomeT6CodonHeatmap = computed(() => {
  const heatmap = transcriptomeModule('T6').codon_heatmap || {}
  return matrixHeatmapOption(heatmap.x_labels || [], heatmap.y_labels || [], heatmap.values || [], { min: 0, max: 0.08 })
})

const transcriptomeT6CodonEntropyChart = computed(() =>
  histogramOption(transcriptomeModule('T6').codon_entropy_histogram || { centers: [], counts: [] }, 'Codon entropy bits', 'Coding transcript count'),
)

const transcriptomeT6ProjectionChart = computed(() => {
  const embedding = transcriptomeProjectionEmbedding(transcriptomeModule('T6').codon_projection || {})
  return buildOrdinationOption(embedding.points, embedding.xKey, embedding.yKey, embedding.xLabel, embedding.yLabel, {
    title: 'T6 transcript codon strategy ordination',
    meta: transcriptomeModule('T6').codon_projection?.ordination_meta,
  })
})

const transcriptomeT6ProjectionNote = computed(() => transcriptomeProjectionAnnotation(transcriptomeModule('T6').codon_projection || {}))

const transcriptomeT7AaChart = computed(() =>
  barOption(
    (transcriptomeModule('T7').aa_composition || []).map((row) => row.name),
    (transcriptomeModule('T7').aa_composition || []).map((row) => Number(row.value || 0)),
    'Mean AA frequency',
    true,
  ),
)

const transcriptomeT7ProjectionChart = computed(() => {
  const embedding = transcriptomeProjectionEmbedding(transcriptomeModule('T7').protein_projection || {})
  return buildOrdinationOption(embedding.points, embedding.xKey, embedding.yKey, embedding.xLabel, embedding.yLabel, {
    title: 'T7 RNA-to-protein proxy ordination',
    subtitle: 'Transcript-derived protein proxy; confirm with observed proteome modules before biological interpretation.',
    meta: transcriptomeModule('T7').protein_projection?.ordination_meta,
  })
})

const transcriptomeT7ProjectionNote = computed(() => transcriptomeProjectionAnnotation(transcriptomeModule('T7').protein_projection || {}))

const transcriptomeT7CouplingChart = computed(() => {
  const heatmap = transcriptomeModule('T7').rna_protein_coupling_heatmap || {}
  return matrixHeatmapOption(heatmap.x_labels || [], heatmap.y_labels || [], heatmap.values || [], { min: -1, max: 1, details: heatmap.details || [] })
})

const transcriptomeT8FingerprintChart = computed(() => {
  return fingerprintProfileBarOption(fingerprintProfileRows(transcriptomeModule('T8'), 24), 'Transcript sequence fingerprint profile')
})

const transcriptomeT8SpeciesChart = computed(() => {
  const embedding = transcriptomeProjectionEmbedding(transcriptomeModule('T8').species_pca || {})
  const points = (embedding.points || []).map((row) => ({ ...row, entity_id: row.display_name || row.species_id }))
  return buildOrdinationOption(points, embedding.xKey, embedding.yKey, embedding.xLabel, embedding.yLabel, {
    title: 'T8 transcript sequence species ordination',
    currentSpeciesId: props.speciesId,
    meta: transcriptomeModule('T8').species_pca?.ordination_meta,
  })
})

const transcriptomeT8ProjectionNote = computed(() => transcriptomeProjectionAnnotation(transcriptomeModule('T8').species_pca || {}))

const transcriptomeT8DistanceChart = computed(() => {
  const heatmap = transcriptomeModule('T8').distance_matrix || {}
  return matrixHeatmapOption(heatmap.x_labels || [], heatmap.y_labels || [], heatmap.values || [], {
    min: 0,
    max: 2,
    distance: true,
    scaleType: heatmap.scale_type || 'distance',
    method: heatmap.method,
  })
})

const transcriptomeT8FeatureRanking = computed(() => transcriptomeModule('T8').feature_ranking || [])

const transcriptomeCandidateRows = computed(() => transcriptomeModule('T8').candidate_summary || [])

const transcriptomeCandidateDashboardRows = computed(() => {
  const take = (rows, source, limit = 8) =>
    (rows || []).slice(0, limit).map((row) => ({
      ...row,
      module_source: source,
    }))
  return [
    ...take(transcriptomeModule('T2').resource_outliers, 'T2 resource outlier'),
    ...take(transcriptomeModule('T3').low_complexity_candidates, 'T3 low-complexity'),
    ...take(transcriptomeModule('T5').coding_potential_candidates, 'T5 coding-potential'),
    ...take(transcriptomeModule('T6').codon_anomaly_transcripts, 'T6 codon anomaly'),
    ...take(transcriptomeModule('T7').instability_candidates, 'T7 instability'),
    ...take(transcriptomeCandidateRows.value, 'T8 cross-species summary', 12),
  ]
})

const proteomeEvidenceBanner = computed(() => {
  const metadata = proteomeModuleSuite.value?.method_metadata || {}
  const source = proteomeModuleSuite.value?.scope === 'full_registered_csv'
    ? 'core rows are stored in PostgreSQL; registered full CSV is read on demand for structure, redox and detectability fields'
    : 'current requested scope is used directly'
  return `${source}. Evidence level: ${metadata.evidence_level || 'sequence-derived descriptive / hypothesis-generating'}; missing policy: ${metadata.missing_policy || 'available fields only'}.`
})

const proteomeKeyFeatureChart = computed(() => {
  const p2 = proteomeModule('P2').cards || {}
  const p5 = proteomeModule('P5').cards || {}
  const p7 = proteomeModule('P7').cards || {}
  const rows = [
    ['N / aa', p2.N_atoms_per_aa?.mean],
    ['S / aa', p2.S_atoms_per_aa?.mean],
    ['C/N', p2.C_N_ratio?.mean],
    ['pI', p5.pI?.mean],
    ['GRAVY', p5.gravy?.mean],
    ['Instability', p5.instability_index?.mean],
    ['ZC', p7.avg_oxidation_state_C?.mean],
  ].filter((row) => row[1] !== undefined && row[1] !== null)
  return barOption(rows.map((row) => row[0]), rows.map((row) => Number(row[1] || 0)), 'Mean / ratio', true)
})

const proteomeP1LengthChart = computed(() =>
  histogramOption(proteomeModule('P1').length_histogram || { centers: [], counts: [] }, 'Protein length aa', 'Protein count'),
)

const proteomeP1QualityChart = computed(() => donutOption(proteomeModule('P1').quality_counts || []))

const proteomeP2ElementChart = computed(() =>
  barOption(
    (proteomeModule('P2').element_profile || []).map((row) => row.name),
    (proteomeModule('P2').element_profile || []).map((row) => Number(row.value || 0)),
    'Atoms per aa',
    true,
  ),
)

const proteomeP2NChart = computed(() =>
  histogramOption(proteomeModule('P2').n_histogram || { centers: [], counts: [] }, 'N atoms per aa', 'Protein count'),
)

const proteomeP2SChart = computed(() =>
  histogramOption(proteomeModule('P2').s_histogram || { centers: [], counts: [] }, 'S atoms per aa', 'Protein count'),
)

const proteomeP2ProjectionChart = computed(() => {
  const embedding = proteomeProjectionEmbedding(proteomeModule('P2').resource_projection || {})
  return buildOrdinationOption(embedding.points, embedding.xKey, embedding.yKey, embedding.xLabel, embedding.yLabel, {
    title: 'P2 resource-space ordination',
    meta: proteomeModule('P2').resource_projection?.ordination_meta,
  })
})

const proteomeP2ProjectionNote = computed(() => proteomeProjectionAnnotation(proteomeModule('P2').resource_projection || {}))

const proteomeP3NsScatter = computed(() =>
  buildEnhancedScatterOption(proteomeModule('P3').ns_tradeoff_scatter || [], 'N_atoms_per_aa', 'S_atoms_per_aa', 'N / aa', 'S / aa', {
    meta: proteomeModule('P3').ns_tradeoff_scatter_meta,
    title: 'P3 nitrogen-sulfur resource budget',
  }),
)

const proteomeP3SulfurChart = computed(() =>
  barOption(
    (proteomeModule('P3').sulfur_composition || []).map((row) => row.name),
    (proteomeModule('P3').sulfur_composition || []).map((row) => Number(row.value || 0)),
    'Mean count',
    true,
  ),
)

const proteomeP4AaChart = computed(() =>
  barOption(
    (proteomeModule('P4').aa_composition || []).map((row) => row.name),
    (proteomeModule('P4').aa_composition || []).map((row) => Number(row.value || 0)),
    'Mean AA percent',
    true,
  ),
)

const proteomeP4ClassChart = computed(() =>
  barOption(
    (proteomeModule('P4').aa_class_profile || []).map((row) => row.name),
    (proteomeModule('P4').aa_class_profile || []).map((row) => Number(row.value || 0)),
    'Mean fraction',
    true,
  ),
)

const proteomeP4ProjectionChart = computed(() => {
  const embedding = proteomeProjectionEmbedding(proteomeModule('P4').aa_projection || {})
  return buildOrdinationOption(embedding.points, embedding.xKey, embedding.yKey, embedding.xLabel, embedding.yLabel, {
    title: 'P4 AA composition ordination',
    meta: proteomeModule('P4').aa_projection?.ordination_meta,
  })
})

const proteomeP4ProjectionNote = computed(() => proteomeProjectionAnnotation(proteomeModule('P4').aa_projection || {}))

const proteomeP5PiChart = computed(() =>
  histogramOption(proteomeModule('P5').pi_histogram || { centers: [], counts: [] }, 'pI', 'Protein count'),
)

const proteomeP5GravyChart = computed(() =>
  histogramOption(proteomeModule('P5').gravy_histogram || { centers: [], counts: [] }, 'GRAVY', 'Protein count'),
)

const proteomeP5InstabilityGravyChart = computed(() =>
  buildEnhancedScatterOption(proteomeModule('P5').instability_gravy_scatter || [], 'gravy', 'instability_index', 'GRAVY', 'Instability index', {
    meta: proteomeModule('P5').instability_gravy_scatter_meta,
    title: 'P5 instability vs GRAVY',
    referenceLines: [{ kind: 'y', value: 40, label: 'instability=40' }, { kind: 'x', value: 0, label: 'GRAVY=0' }],
  }),
)

const proteomeP5ProjectionChart = computed(() => {
  const embedding = proteomeProjectionEmbedding(proteomeModule('P5').property_projection || {})
  return buildOrdinationOption(embedding.points, embedding.xKey, embedding.yKey, embedding.xLabel, embedding.yLabel, {
    title: 'P5 physicochemical property landscape',
    meta: proteomeModule('P5').property_projection?.ordination_meta,
  })
})

const proteomeP5ProjectionNote = computed(() => proteomeProjectionAnnotation(proteomeModule('P5').property_projection || {}))

const proteomeP6StructureChart = computed(() =>
  barOption(
    (proteomeModule('P6').secondary_structure_profile || []).map((row) => row.name),
    (proteomeModule('P6').secondary_structure_profile || []).map((row) => Number(row.value || 0)),
    'Mean fraction',
    true,
  ),
)

const proteomeP6FlexAccessChart = computed(() =>
  buildQuadrantScatterOption(proteomeModule('P6').flex_access_scatter || [], 'flex_mean', 'surface_access_em_mean', 'Flexibility mean', 'Surface accessibility mean', {
    meta: proteomeModule('P6').flex_access_scatter_meta,
    title: 'P6 flexibility-accessibility proxy',
  }),
)

const proteomeP6ProjectionChart = computed(() => {
  const embedding = proteomeProjectionEmbedding(proteomeModule('P6').structure_projection || {})
  return buildOrdinationOption(embedding.points, embedding.xKey, embedding.yKey, embedding.xLabel, embedding.yLabel, {
    title: 'P6 sequence-derived structure proxy ordination',
    subtitle: 'Sequence-derived proxy, not measured or predicted 3D structure.',
    meta: proteomeModule('P6').structure_projection?.ordination_meta,
  })
})

const proteomeP6ProjectionNote = computed(() => proteomeProjectionAnnotation(proteomeModule('P6').structure_projection || {}))

const proteomeP7ZcChart = computed(() =>
  histogramOption(proteomeModule('P7').zc_histogram || { centers: [], counts: [] }, 'Average oxidation state C', 'Protein count'),
)

const proteomeP7RedoxScatter = computed(() =>
  buildEnhancedScatterOption(proteomeModule('P7').redox_gravy_scatter || [], 'avg_oxidation_state_C', 'gravy', 'ZC', 'GRAVY', {
    meta: proteomeModule('P7').redox_gravy_scatter_meta,
    title: 'P7 redox vs GRAVY',
    referenceLines: [{ kind: 'y', value: 0, label: 'GRAVY=0' }],
  }),
)

const proteomeP7ProjectionChart = computed(() => {
  const embedding = proteomeProjectionEmbedding(proteomeModule('P7').redox_projection || {})
  return buildOrdinationOption(embedding.points, embedding.xKey, embedding.yKey, embedding.xLabel, embedding.yLabel, {
    title: 'P7 redox/detectability proxy ordination',
    subtitle: 'Detectability is a sequence-derived proxy unless external MS evidence is loaded.',
    meta: proteomeModule('P7').redox_projection?.ordination_meta,
  })
})

const proteomeP7ProjectionNote = computed(() => proteomeProjectionAnnotation(proteomeModule('P7').redox_projection || {}))

const proteomeP8FingerprintChart = computed(() => {
  return fingerprintProfileBarOption(fingerprintProfileRows(proteomeModule('P8'), 28), 'Proteome fingerprint profile')
})

const proteomeP8SpeciesChart = computed(() => {
  const embedding = proteomeProjectionEmbedding(proteomeModule('P8').species_pca || {})
  const points = (embedding.points || []).map((row) => ({ ...row, entity_id: row.display_name || row.species_id }))
  return buildOrdinationOption(points, embedding.xKey, embedding.yKey, embedding.xLabel, embedding.yLabel, {
    title: 'P8 proteome species ordination',
    currentSpeciesId: props.speciesId,
    meta: proteomeModule('P8').species_pca?.ordination_meta,
  })
})

const proteomeP8ProjectionNote = computed(() => proteomeProjectionAnnotation(proteomeModule('P8').species_pca || {}))

const proteomeP8DistanceChart = computed(() => {
  const heatmap = proteomeModule('P8').distance_matrix || {}
  return matrixHeatmapOption(heatmap.x_labels || [], heatmap.y_labels || [], heatmap.values || [], {
    min: 0,
    max: 2,
    distance: true,
    scaleType: heatmap.scale_type || 'distance',
    method: heatmap.method,
  })
})

const proteomeP8CouplingChart = computed(() => {
  const heatmap = proteomeModule('P8').coupling_heatmap || {}
  return matrixHeatmapOption(heatmap.x_labels || [], heatmap.y_labels || [], heatmap.values || [], { min: -1, max: 1, details: heatmap.details || [] })
})

const proteomeP8FeatureRanking = computed(() => proteomeModule('P8').feature_ranking || [])

const proteomeCandidateRows = computed(() => [
  ...(proteomeModule('P2').resource_outliers || []).slice(0, 8).map((row) => ({ ...row, module: 'P2 resource' })),
  ...(proteomeModule('P3').s_rich_candidates || []).slice(0, 8).map((row) => ({ ...row, module: 'P3 S-rich' })),
  ...(proteomeModule('P4').composition_anomalies || []).slice(0, 8).map((row) => ({ ...row, module: 'P4 AA composition' })),
  ...(proteomeModule('P5').hydrophobic_candidates || []).slice(0, 8).map((row) => ({ ...row, module: 'P5 hydrophobic' })),
  ...(proteomeModule('P6').disulfide_rich_candidates || []).slice(0, 8).map((row) => ({ ...row, module: 'P6 disulfide' })),
  ...(proteomeModule('P7').redox_outliers || []).slice(0, 8).map((row) => ({ ...row, module: 'P7 redox' })),
  ...(proteomeModule('P8').candidate_summary || []).slice(0, 10).map((row) => ({ ...row, module: 'P8 summary' })),
])

const transcriptomeImplementationNotes = computed(() =>
  transcriptomeModules.value.flatMap((module) =>
    (module.implementation_notes || []).map((note) => ({ module: `${module.id} ${module.name}`, note })),
  ),
)

const proteomeImplementationNotes = computed(() =>
  proteomeModules.value.flatMap((module) =>
    (module.implementation_notes || []).map((note) => ({ module: `${module.id} ${module.name}`, note })),
  ),
)

const hasTradeoffRows = computed(() =>
  (omicsAnalysis.value?.tradeoff_front || []).some((row) =>
    Number.isFinite(Number(row.cost_axis)) && Number.isFinite(Number(row.adapt_axis)),
  ),
)

const genomeImplementationNotes = computed(() =>
  genomeModules.value.flatMap((module) =>
    (module.implementation_notes || []).map((note) => ({ module: `${module.id} ${module.name}`, note })),
  ),
)

function formatMissingModule(item) {
  if (!item) return ''
  if (typeof item === 'string') return item
  const moduleName = item.module || item.name || 'missing module'
  const fields = (item.required_fields || item.fields || []).join(', ')
  return fields ? `${moduleName} (${fields})` : moduleName
}

function formatDerivedExample(example) {
  if (!example || example.value === undefined || example.value === null) return '-'
  const label = example.gene_name || example.gene_id || example.entity_id || 'example'
  return `${label}: ${example.value}`
}

const customScatterAnnotation = computed(() => {
  const payload = customScatterPayload.value
  if (!payload) return 'Choose any two fields to inspect pairwise structure in the current omics scope.'
  return `Showing ${payload.n_points} sampled points from ${payload.n_total} valid rows.`
})

const representativeValueKey = computed(() => {
  const first = omicsSummary.value?.top_entities?.top?.[0] || {}
  return Object.keys(first).find(
    (key) =>
      !['entity_id', 'gene_id', 'transcript_id', 'protein_id', 'gene_name', 'gene_symbol', 'description', 'strategy_cluster'].includes(key),
  )
})

const topEntitiesChart = computed(() => {
  const key = representativeValueKey.value
  const rows = (omicsSummary.value?.top_entities?.top || []).map((row) => ({
    name: row.gene_name || row.gene_symbol || row.gene_id || row.transcript_id || row.protein_id || row.entity_id,
    value: row[key],
  }))
  return key ? rankLollipopOption(rows, 'name', 'value', formatKey(key)) : rankLollipopOption([], 'name', 'value', '')
})

const bottomEntitiesChart = computed(() => {
  const key = representativeValueKey.value
  const rows = (omicsSummary.value?.top_entities?.bottom || []).map((row) => ({
    name: row.gene_name || row.gene_symbol || row.gene_id || row.transcript_id || row.protein_id || row.entity_id,
    value: row[key],
  }))
  return key ? rankLollipopOption(rows, 'name', 'value', formatKey(key)) : rankLollipopOption([], 'name', 'value', '')
})

const analysisSpecificRows = computed(() => {
  if (!omicsAnalysis.value) return []
  if (activePanel.value === 'genome') {
    return (omicsAnalysis.value.stoich_islands || []).map((row) => ({
      name: row.segment,
      value: row.mean_island_score,
    }))
  }
  if (activePanel.value === 'transcriptome') {
    return (omicsAnalysis.value.composition_themes || omicsAnalysis.value.motif_themes || []).map((row) => ({
      name: row.theme,
      value: row.count,
    }))
  }
  return (omicsAnalysis.value.sequence_intrinsic_resource_profile || omicsAnalysis.value.resource_budget || []).map((row) => ({
    name: row.feature,
    value: row.mean,
  }))
})

const analysisSpecificTitle = computed(() => {
  if (activePanel.value === 'genome') return 'Stoichiometric island candidate spectrum'
  if (activePanel.value === 'transcriptome') return 'Compositional theme spectrum'
  return 'Sequence-intrinsic resource profile'
})

const analysisSpecificChart = computed(() => {
  if (activePanel.value === 'genome') return treemapOption(analysisSpecificRows.value)
  if (activePanel.value === 'transcriptome') return donutOption(analysisSpecificRows.value)
  return rankLollipopOption(analysisSpecificRows.value, 'name', 'value', 'Mean')
})

const crossSankey = computed(() => {
  const rows = cross.value?.top_transformations || []
  if (!rows.length) return sankeyOption([])
  const dnaUp = rows.filter((r) => Number(r.dna_to_rna_n_shift_std ?? r.dna_to_rna_n_delta) >= 0).length
  const dnaDown = rows.length - dnaUp
  const proteinUp = rows.filter((r) => Number(r.rna_to_protein_n_shift_std ?? r.rna_to_protein_n_delta) >= 0).length
  const proteinDown = rows.length - proteinUp

  return sankeyOption([
    { source: 'Genome N landscape', target: 'RNA N increases', value: dnaUp },
    { source: 'Genome N landscape', target: 'RNA N decreases', value: dnaDown },
    { source: 'RNA N increases', target: 'Protein N increases', value: proteinUp },
    { source: 'RNA N decreases', target: 'Protein N decreases', value: proteinDown },
  ])
})

const distributionAnnotation = computed(() => {
  const summary = distributionSummary.value
  if (!summary) return ''
  const meta = currentFieldMeta.value
  const unit = meta?.unit ? ` (${meta.unit})` : ''
  const missing = fieldSummaryPayload.value
    ? ` Missing rate ${((fieldSummaryPayload.value.missing_rate || 0) * 100).toFixed(2)}%.`
    : ''
  return `Mean ${summary.mean}${unit}, standard deviation ${summary.std}, with the central 90% approximately spanning from ${summary.p05} to ${summary.p95}.${missing}`
})

const analysisAnnotation = computed(() => {
  if (activePanel.value === 'genome') {
    return 'Genome-specific analysis emphasizes genomic neighborhoods with unusual promoter-exon composition and elevated island structure.'
  }
  if (activePanel.value === 'transcriptome') {
    return 'Transcript sequence-specific analysis emphasizes motif-skewed sequence classes and coupling between RNA composition and coding proxies.'
  }
  return 'Proteome-specific analysis summarizes elemental resource allocation across protein property space, especially N / S-sensitive structure.'
})

const analysisAnnotationNormalized = computed(() => {
  if (activePanel.value === 'genome') {
    return 'Genome-specific analysis emphasizes genomic neighborhoods with unusual promoter-exon composition and elevated island structure.'
  }
  if (activePanel.value === 'transcriptome') {
    return 'Transcript sequence-specific analysis emphasizes motif-skewed sequence classes and coupling between RNA composition and coding proxies.'
  }
  if (activePanel.value === 'proteome') {
    return 'Proteome-specific analysis summarizes elemental resource allocation across protein property space, especially N / S-sensitive structure.'
  }
  return ''
})

const analysisMethodAnnotation = computed(() => {
  if (!omicsAnalysis.value) return ''
  const method = omicsAnalysis.value?.method_metadata || {}
  const outlierMethod = method?.outliers?.method || 'score_quantile_extremes'
  const tradeoffMethod = method?.tradeoff_front?.method || 'non_dominated_sorting'
  const couplingMethod = method?.coupling_network?.method || 'spearman_association'
  const evidence = omicsAnalysis.value?.evidence_level || 'exploratory'
  return `This panel presents ${evidence} analysis outputs. Outlier module: ${outlierMethod}; trade-off module: ${tradeoffMethod}; coupling module: ${couplingMethod}. Results are intended for hypothesis generation and should be interpreted with field units, sample size, and biological context.`
})

function formatKey(key) {
  return String(key || '').replaceAll('_', ' ')
}

function compactNumber(value) {
  const num = Number(value)
  if (!Number.isFinite(num)) return '-'
  if (Math.abs(num) >= 1000000 || (Math.abs(num) > 0 && Math.abs(num) < 0.0001)) return num.toExponential(3)
  return num.toLocaleString(undefined, { maximumFractionDigits: 6 })
}

function fingerprintProfileRows(modulePayload = {}, limit = 24) {
  const fingerprint = modulePayload?.fingerprint || {}
  let rows = Object.entries(fingerprint)
    .map(([key, value]) => ({ key, rawValue: Number(value), source: 'fingerprint' }))
    .filter((row) => Number.isFinite(row.rawValue))
  if (!rows.length && Array.isArray(modulePayload?.feature_ranking)) {
    rows = modulePayload.feature_ranking
      .map((row) => ({
        key: row.feature || row.key || row.name,
        rawValue: Number(row.value ?? row.mean ?? row.range ?? row.cv),
        source: 'feature_ranking',
      }))
      .filter((row) => row.key && Number.isFinite(row.rawValue))
  }
  rows = rows.slice(0, limit)
  const transformed = rows.map((row) => Math.sign(row.rawValue) * Math.log10(1 + Math.abs(row.rawValue)))
  const scale = Math.max(1e-9, ...transformed.map((value) => Math.abs(value)))
  return rows.map((row, index) => ({
    key: row.key,
    label: formatKey(row.key),
    raw_value: row.rawValue,
    display_value: Number((transformed[index] / scale).toFixed(6)),
    display_transform: 'signed_log10_1p_max_abs_normalized',
    source: row.source,
  }))
}

function fingerprintProfileBarOption(rows = [], title = 'Fingerprint profile') {
  const option = barOption(rows.map((row) => row.label), rows.map((row) => row.display_value), 'Normalized value', true)
  option.__exportName = `${title.toLowerCase().replaceAll(' ', '_')}.csv`
  option.__semantic = {
    minPoints: 2,
    totalCount: rows.length,
    displayedCount: rows.length,
    method: 'raw fingerprint values displayed with signed log10(1+abs(value)) max-absolute normalization',
    aggregation: 'current species feature summary',
  }
  option.__dataRows = rows
  option.tooltip = {
    ...(option.tooltip || {}),
    formatter: (params) => {
      const row = rows[params?.dataIndex] || {}
      return [
        row.label || '',
        `raw value: ${compactNumber(row.raw_value)}`,
        `display value: ${compactNumber(row.display_value)}`,
        `transform: ${row.display_transform || '-'}`,
      ].join('<br/>')
    },
  }
  if (option.series?.[0]) {
    option.series[0].name = title
    option.series[0].data = rows.map((row) => ({
      value: row.display_value,
      raw_value: row.raw_value,
      feature: row.key,
      display_transform: row.display_transform,
    }))
  }
  return option
}

function formatPercent(value) {
  const num = Number(value)
  if (!Number.isFinite(num)) return '-'
  return `${(num * 100).toFixed(2)}%`
}

function formatScatterLabel(key) {
  return {
    promoter_vs_exon_gc: 'Promoter vs exon GC',
    gc_delta_vs_n: 'Promoter-minus-exon delta GC vs N / base',
    gc_vs_entropy: 'RNA GC% vs nt entropy',
    coupling_vs_gravy: 'RNA-ORF coupling vs gravy proxy',
    n_vs_pi: 'N / aa vs pI',
    s_vs_disulfide: 'S / aa vs disulfide density',
  }[key] || formatKey(key)
}

function csvEscape(value) {
  if (value === null || value === undefined) return ''
  const text = String(value)
  if (text.includes(',') || text.includes('"') || text.includes('\n')) {
    return `"${text.replaceAll('"', '""')}"`
  }
  return text
}

function downloadCsv(filename, rows) {
  if (!rows?.length) return
  const headers = Array.from(
    rows.reduce((set, row) => {
      Object.keys(row || {}).forEach((key) => set.add(key))
      return set
    }, new Set()),
  )
  const lines = [headers.join(',')]
  rows.forEach((row) => {
    lines.push(headers.map((header) => csvEscape(row?.[header])).join(','))
  })
  const blob = new Blob([`\uFEFF${lines.join('\n')}`], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

function exportCrossTransformationsCsv() {
  const rows = cross.value?.top_transformations || []
  const speciesId = props.speciesId || species.value?.species_id || 'species'
  downloadCsv(`${speciesId}_cross_top_transformations.csv`, rows)
}

function exportCrossModuleTable(tableName) {
  const speciesId = props.speciesId || species.value?.species_id || 'species'
  const map = {
    x1_resource_shift_candidates: crossX1CandidateRows.value,
    x2_residual_candidates: crossModule('X2').residual_candidates || [],
    x3_translation_discordance: crossModule('X3').discordance_candidates || [],
    x5_propagation_candidates: crossModule('X5').candidate_table || [],
    x6_edge_ranking: crossX6EdgeRows.value,
    x7_feature_ranking: crossX7FeatureRows.value,
    x8_candidate_workbench: crossExportTables.value?.['cross_omics_candidate_workbench.csv'] || crossX8CandidateRows.value,
  }
  downloadCsv(`${speciesId}_${tableName}.csv`, map[tableName] || [])
}

function exportGenomeTable(tableName) {
  const speciesId = props.speciesId || species.value?.species_id || 'species'
  const map = {
    g2_top_delta: genomeG2TopDeltaRows.value,
    g4_anomalies: genomeModule('G4').anomaly_ranking || [],
    g5_codon_anomalies: genomeModule('G5').codon_anomaly_genes || [],
    g6_top_island_genes: genomeG6TopGenes.value,
    g6_hotspot_windows: genomeG6HotspotRows.value,
    genome_candidate_genes: genomeGlobalOutlierRows.value,
    g8_feature_ranking: genomeG8FeatureRanking.value,
  }
  downloadCsv(`${speciesId}_${tableName}.csv`, map[tableName] || [])
}

function exportTranscriptomeTable(tableName) {
  const speciesId = props.speciesId || species.value?.species_id || 'species'
  const map = {
    t2_resource_outliers: transcriptomeModule('T2').resource_outliers || [],
    t3_low_complexity: transcriptomeModule('T3').low_complexity_candidates || [],
    t5_coding_candidates: transcriptomeModule('T5').coding_potential_candidates || [],
    t6_codon_anomalies: transcriptomeModule('T6').codon_anomaly_transcripts || [],
    t7_instability_candidates: transcriptomeModule('T7').instability_candidates || [],
    t8_candidate_summary: transcriptomeCandidateRows.value,
    t8_feature_ranking: transcriptomeT8FeatureRanking.value,
    transcriptome_candidate_dashboard: transcriptomeCandidateDashboardRows.value,
  }
  downloadCsv(`${speciesId}_${tableName}.csv`, map[tableName] || [])
}

function exportProteomeTable(tableName) {
  const speciesId = props.speciesId || species.value?.species_id || 'species'
  const map = {
    p1_low_quality: proteomeModule('P1').low_quality_candidates || [],
    p2_resource_outliers: proteomeModule('P2').resource_outliers || [],
    p3_low_n: proteomeModule('P3').low_n_candidates || [],
    p3_s_rich: proteomeModule('P3').s_rich_candidates || [],
    p3_se_positive: proteomeModule('P3').se_positive_candidates || [],
    p4_composition_anomalies: proteomeModule('P4').composition_anomalies || [],
    p5_hydrophobic: proteomeModule('P5').hydrophobic_candidates || [],
    p5_unstable: proteomeModule('P5').unstable_candidates || [],
    p6_disulfide: proteomeModule('P6').disulfide_rich_candidates || [],
    p7_detectability: proteomeModule('P7').detectability_ranking || [],
    p7_redox: proteomeModule('P7').redox_outliers || [],
    p8_candidate_summary: proteomeModule('P8').candidate_summary || [],
    p8_feature_ranking: proteomeP8FeatureRanking.value,
    proteome_candidate_dashboard: proteomeCandidateRows.value,
  }
  downloadCsv(`${speciesId}_${tableName}.csv`, map[tableName] || [])
}

function resetOmicsState() {
  rowsRequestSeq += 1
  detailRequestSeq += 1
  fieldSummaryRequestSeq += 1
  customScatterRequestSeq += 1
  omicsSummary.value = null
  omicsAnalysis.value = null
  fieldSummaryPayload.value = null
  customScatterPayload.value = null
  customScatterLoading.value = false
  rowsPayload.value = {
    rows: [],
    columns: [],
    total: 0,
    strategy_clusters: [],
    feature_options: [],
  }
  detailPayload.value = null
  omicsError.value = ''
  availableScopes.value = ['core']
  distributionKey.value = ''
  scatterKey.value = ''
  derivedScatterKey.value = ''
  customScatterX.value = ''
  customScatterY.value = ''
  omicsCorrMethod.value = 'spearman'
  rowsLoading.value = false
  detailLoading.value = false
}

function preferredCorrMethod(matrices) {
  const methods = Object.keys(matrices || {})
  if (methods.includes('spearman')) return 'spearman'
  if (methods.includes('pearson')) return 'pearson'
  return methods[0] || 'spearman'
}

function currentRouteQueryFromState() {
  return {
    ...(activePanel.value !== 'overview' ? { panel: activePanel.value } : {}),
    ...(omicsTab.value !== 'basic' && isOmicsPanel.value ? { tab: omicsTab.value } : {}),
    ...(omicsScope.value !== 'core' && isOmicsPanel.value ? { scope: omicsScope.value } : {}),
    ...(isIntegrationVisualActive.value ? {} : isScientificVisualActive.value ? { compute: 'complete_core' } : omicsCompute.value !== 'stored' && (isOmicsPanel.value || activePanel.value === 'cross') ? { compute: omicsCompute.value } : {}),
    ...(rowQuery.value && isOmicsPanel.value && omicsTab.value === 'table' ? { q: rowQuery.value } : {}),
    ...(rowCluster.value && isOmicsPanel.value && omicsTab.value === 'table' ? { cluster: rowCluster.value } : {}),
    ...(sortBy.value && isOmicsPanel.value && omicsTab.value === 'table' ? { sort: sortBy.value } : {}),
    ...(featureFilterKey.value && isOmicsPanel.value && omicsTab.value === 'table' ? { fk: featureFilterKey.value } : {}),
    ...(featureFilterMin.value && isOmicsPanel.value && omicsTab.value === 'table' ? { fmin: featureFilterMin.value } : {}),
    ...(featureFilterMax.value && isOmicsPanel.value && omicsTab.value === 'table' ? { fmax: featureFilterMax.value } : {}),
  }
}

function sameQuery(a = {}, b = {}) {
  const aKeys = Object.keys(a).sort()
  const bKeys = Object.keys(b).sort()
  if (aKeys.length !== bKeys.length) return false
  return aKeys.every((key, idx) => key === bKeys[idx] && String(a[key]) === String(b[key]))
}

function syncRouteFromState() {
  const nextQuery = currentRouteQueryFromState()
  if (sameQuery(route.query, nextQuery)) return
  routeSyncInFlight = true
  router.replace({ query: nextQuery }).catch(() => {}).finally(() => {
    routeSyncInFlight = false
  })
}

function applyRouteState() {
  const panel = String(route.query.panel || '')
  const tab = String(route.query.tab || '')
  const scope = String(route.query.scope || '')
  const compute = String(route.query.compute || '')
  const q = String(route.query.q || '')
  const cluster = String(route.query.cluster || '')
  const sort = String(route.query.sort || '')
  const fk = String(route.query.fk || '')
  const fmin = String(route.query.fmin || '')
  const fmax = String(route.query.fmax || '')

  if (['overview', 'cross', 'genome', 'transcriptome', 'proteome'].includes(panel)) {
    activePanel.value = panel
  } else {
    activePanel.value = 'overview'
  }

  if (['basic', 'analysis', 'table'].includes(tab)) {
    omicsTab.value = tab
  } else {
    omicsTab.value = 'basic'
  }

  if (['core', 'full'].includes(scope)) {
    omicsScope.value = scope
  } else {
    omicsScope.value = 'core'
  }

  if (['stored', 'complete_core'].includes(compute)) {
    omicsCompute.value = compute
  } else if (compute === 'full') {
    omicsCompute.value = 'complete_core'
  } else {
    omicsCompute.value = 'stored'
  }
  if (isIntegrationVisualActive.value) {
    omicsCompute.value = 'stored'
    omicsScope.value = 'core'
  } else if (isScientificVisualActive.value) {
    omicsCompute.value = 'stored' // Legacy metadata stays lightweight; v3 always reads its complete artifacts.
    if (compute === 'full' && isProteomeV3Active.value) omicsScope.value = 'core'
  } else if (omicsCompute.value === 'complete_core') {
    omicsScope.value = 'core'
  }

  rowQuery.value = q
  rowCluster.value = cluster
  sortBy.value = sort
  featureFilterKey.value = fk
  featureFilterMin.value = fmin
  featureFilterMax.value = fmax
}

async function loadSpecies(targetSpeciesId = props.speciesId) {
  const seq = ++speciesRequestSeq
  speciesLoading.value = true
  speciesError.value = ''
  crossError.value = ''
  if (speciesCache.has(targetSpeciesId)) {
    species.value = speciesCache.get(targetSpeciesId)
  }
  const existingCrossCacheKey = `${targetSpeciesId}::${omicsCompute.value}`
  if (crossCache.has(existingCrossCacheKey)) {
    cross.value = crossCache.get(existingCrossCacheKey)
  } else {
    cross.value = null
  }
  const existingEnhancedCacheKey = `${targetSpeciesId}::${omicsCompute.value}`
  if (speciesEnhancedCache.has(existingEnhancedCacheKey)) {
    speciesEnhanced.value = speciesEnhancedCache.get(existingEnhancedCacheKey)
  } else {
    speciesEnhanced.value = null
  }

  try {
    const speciesPayload = speciesCache.has(targetSpeciesId)
      ? speciesCache.get(targetSpeciesId)
      : await getSpecies(targetSpeciesId, { lightweight: 1 })

    if (seq !== speciesRequestSeq || targetSpeciesId !== props.speciesId) return

    speciesCache.set(targetSpeciesId, speciesPayload)
    species.value = speciesPayload
    void loadIdMappingSummary(targetSpeciesId)
    void loadFunctionalSummary(targetSpeciesId)
    if (!isScientificVisualActive.value) void loadSpeciesEnhanced(targetSpeciesId)
    if (activePanel.value === 'overview' && !cross.value && !crossLoading.value) {
      void loadCrossOmics(targetSpeciesId, { background: true })
    }
    if (activePanel.value === 'cross') {
      void loadCrossOmics(targetSpeciesId)
    }
  } catch (error) {
    if (seq !== speciesRequestSeq || targetSpeciesId !== props.speciesId) return
    console.error('Failed to load species payload', error)
    speciesError.value =
      error?.response?.data?.error?.message ||
      error?.response?.data?.message ||
      error?.message ||
      'Failed to load species metadata.'
  } finally {
    if (seq === speciesRequestSeq) {
      speciesLoading.value = false
    }
  }
}

async function loadSpeciesEnhanced(targetSpeciesId = props.speciesId) {
  if (isIntegrationVisualActive.value) return
  const compute = omicsCompute.value
  const cacheKey = `${targetSpeciesId}::${compute}`
  if (speciesEnhancedCache.has(cacheKey)) {
    speciesEnhanced.value = speciesEnhancedCache.get(cacheKey)
    return
  }
  try {
    const payload = await getSpeciesEnhanced(targetSpeciesId, compute !== 'stored' ? { compute } : {})
    if (targetSpeciesId !== props.speciesId || compute !== omicsCompute.value) return
    speciesEnhancedCache.set(cacheKey, payload)
    speciesEnhanced.value = payload
  } catch (error) {
    if (targetSpeciesId !== props.speciesId) return
    speciesEnhanced.value = null
  }
}

function applyCrossPreviewToSpecies(targetSpeciesId, payload) {
  if (isIntegrationVisualActive.value) return
  if (!species.value || species.value.species_id !== targetSpeciesId) return
  species.value = {
    ...species.value,
    cross_omics_preview: (payload?.top_transformations || payload?.transformations || []).slice(0, 8),
  }
  speciesCache.set(targetSpeciesId, species.value)
}

async function loadCrossOmics(targetSpeciesId = props.speciesId, options = {}) {
  if (isIntegrationVisualActive.value) return
  const { force = false, background = false } = options
  const seq = ++crossRequestSeq
  crossError.value = ''
  const compute = omicsCompute.value
  const cacheKey = `${targetSpeciesId}::${compute}`
  if (!force && crossCache.has(cacheKey)) {
    const cached = crossCache.get(cacheKey)
    cross.value = cached
    crossCorrMethod.value = preferredCorrMethod(cached?.correlation_matrices)
    applyCrossPreviewToSpecies(targetSpeciesId, cached)
    return
  }
  if (!background) {
    crossLoading.value = true
  }
  try {
    const payload = await getCrossOmics(targetSpeciesId, compute !== 'stored' ? { compute } : {})
    if (seq !== crossRequestSeq || targetSpeciesId !== props.speciesId || compute !== omicsCompute.value) return
    crossCache.set(cacheKey, payload)
    cross.value = payload
    crossCorrMethod.value = preferredCorrMethod(payload?.correlation_matrices)
    applyCrossPreviewToSpecies(targetSpeciesId, payload)
  } catch (error) {
    if (seq !== crossRequestSeq || targetSpeciesId !== props.speciesId) return
    cross.value = null
    if (!background || activePanel.value === 'cross') {
      crossError.value =
        error?.response?.data?.error?.message ||
        error?.response?.data?.message ||
        error?.message ||
        'Failed to load cross-omics payload.'
    }
  } finally {
    if (seq === crossRequestSeq) {
      crossLoading.value = false
    }
  }
}

let functionalRequestSeq = 0, idMappingRequestSeq = 0
async function loadFunctionalSummary(targetSpeciesId) {
  const seq = ++functionalRequestSeq
  const current = () => seq === functionalRequestSeq && targetSpeciesId === props.speciesId
  functionalSummaryLoading.value = true; functionalSummaryError.value = ''
  try {
    const payload = functionalSummaryCache.has(targetSpeciesId) ? functionalSummaryCache.get(targetSpeciesId) : await getSpeciesFunctionalSummary(targetSpeciesId)
    functionalSummaryCache.set(targetSpeciesId,payload)
    if (current()) functionalSummary.value = payload
  } catch(error) { if(current()) {functionalSummary.value=null;functionalSummaryError.value=error?.response?.data?.error?.message||error.message} }
  finally {if(current()) functionalSummaryLoading.value=false}
}
async function loadIdMappingSummary(targetSpeciesId) {
  const seq = ++idMappingRequestSeq
  const current = () => seq === idMappingRequestSeq && targetSpeciesId === props.speciesId
  idMappingLoading.value=true;idMappingError.value=''
  try {const payload=await getSpeciesIdMappingSummary(targetSpeciesId);if(current())idMappingSummary.value=payload}
  catch(error){if(current()){idMappingSummary.value=null;idMappingError.value=error?.response?.data?.error?.message||error.message}}
  finally {if(current())idMappingLoading.value=false}
}

function formatPercentNumber(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return '-'
  return `${(n * 100).toFixed(2)}%`
}

function moduleStateLabel(state) {
  return {
    ready: 'Ready',
    limited: 'Limited',
    missing: 'Missing',
  }[state] || 'Unknown'
}

function panelCacheKey(speciesId, omics, scope, compute = omicsCompute.value) {
  return `${speciesId}::${omics}::${scope}::${compute}`
}

function rowsCacheKey() {
  return JSON.stringify({
    speciesId: props.speciesId,
    omics: activePanel.value,
    scope: omicsScope.value,
    q: rowQuery.value,
    cluster: rowCluster.value,
    sort: sortBy.value,
    fk: featureFilterKey.value,
    fmin: featureFilterMin.value,
    fmax: featureFilterMax.value,
    page: page.value,
    pageSize: pageSize.value,
  })
}

function loadOmicsAuxiliaryPayloads() {
  if (isScientificVisualActive.value) return
  void loadFieldSummaryForDistribution()
  void loadCustomScatter()
}

function acceptProteomeManifest(manifest) {
  proteomeV3Enabled.value = manifest.enabled !== false
  if (Array.isArray(manifest.available_scopes)) availableScopes.value = manifest.available_scopes
}

function acceptSequenceManifest(manifest) {
  if (['genome','transcriptome'].includes(activePanel.value)) sequenceEnabled[activePanel.value] = manifest.enabled !== false
  if (Array.isArray(manifest.available_scopes)) availableScopes.value = manifest.available_scopes
}

async function loadOmics(omics, options = {}) {
  if (['genome','transcriptome'].includes(omics) && sequenceEnabled[omics]) {
    const requestId = ++omicsRequestSeq, requestedSpecies = props.speciesId, requestedScope = omicsScope.value
    omicsLoading.value = true; omicsError.value = ''
    try {
      const manifest = await sequenceGet(requestedSpecies, omics, '', {scope:requestedScope})
      if (requestId !== omicsRequestSeq || requestedSpecies !== props.speciesId || requestedScope !== omicsScope.value || activePanel.value !== omics) return
      acceptSequenceManifest(manifest)
      if (manifest.enabled === false) { applyRouteState(); return loadOmics(omics, options) }
      omicsSummary.value = {display_name:omics==='genome'?'Genome':'Transcript sequence', description:'Complete-population sequence descriptors',available_scopes:manifest.available_scopes,kpis:[{label:'Records',value:manifest.n_source}],feature_fields:(manifest.fields||[]).map(f=>f.key)}
      omicsAnalysis.value = {}; syncRouteFromState()
      if (omicsTab.value === 'table') await loadRows({force:options.force||false})
      return
    } catch(error) { if(requestId===omicsRequestSeq && requestedSpecies===props.speciesId) omicsError.value=error?.response?.data?.error?.message||error.message; return }
    finally {if(requestId===omicsRequestSeq) omicsLoading.value=false}
  }

  if (omics === 'proteome' && proteomeV3Enabled.value) {
    const requestId = ++omicsRequestSeq
    const requestedSpecies = props.speciesId
    const requestedScope = omicsScope.value
    omicsLoading.value = true
    omicsError.value = ''
    try {
      const manifest = await getProteomeManifest(requestedSpecies, { scope: requestedScope })
      if (requestId !== omicsRequestSeq || requestedSpecies !== props.speciesId || requestedScope !== omicsScope.value || activePanel.value !== 'proteome') return
      acceptProteomeManifest(manifest)
      if (manifest.enabled === false) { applyRouteState(); return loadOmics(omics, options) }
      omicsSummary.value = { display_name:'Proteome', description:'Complete-population sequence descriptors', available_scopes:manifest.available_scopes, kpis:[{label:'Records',value:manifest.n_source}], feature_fields:(manifest.fields || []).map(f => f.key) }
      omicsAnalysis.value = {}
      omicsLoading.value = false
      syncRouteFromState()
      if (omicsTab.value === 'table') await loadRows({ force: options.force || false })
      return
    } catch (error) {
      if (requestId === omicsRequestSeq && requestedSpecies === props.speciesId) omicsError.value = error?.response?.data?.error?.message || error.message
      return
    } finally { if (requestId === omicsRequestSeq) omicsLoading.value = false }
  }
  const { force = false } = options
  const seq = ++omicsRequestSeq
  const speciesId = props.speciesId
  const scope = omicsScope.value
  const compute = omicsCompute.value
  const cacheKey = panelCacheKey(speciesId, omics, scope, compute)

  omicsLoading.value = true
  omicsError.value = ''
  resetOmicsState()

  if (!force && panelCache.has(cacheKey)) {
    const cached = panelCache.get(cacheKey)
    if (seq !== omicsRequestSeq || speciesId !== props.speciesId || omics !== activePanel.value || scope !== omicsScope.value || compute !== omicsCompute.value) return
    omicsSummary.value = cached.summary
    omicsAnalysis.value = cached.analysis
    availableScopes.value = cached.summary?.available_scopes || ['core']
    if (!availableScopes.value.includes(omicsScope.value)) {
      omicsScope.value = availableScopes.value[0] || 'core'
    }
    distributionKey.value = Object.keys(cached.summary?.distributions || {})[0] || dynamicFieldOptions.value[0] || ''
    scatterKey.value = Object.keys(cached.summary?.scatter || {})[0] || ''
    derivedScatterKey.value = preferredDerivedScatterKey(cached.summary?.scatter || {}, activePanel.value)
    setCustomScatterDefaults(cached.summary, activePanel.value)
    omicsCorrMethod.value = preferredCorrMethod(cached.summary?.correlation_matrices)
    omicsLoading.value = false
    loadOmicsAuxiliaryPayloads()
    if (omicsTab.value === 'table') {
      void loadRows({ force: false })
    }
    return
  }

  try {
    const payload = await getOmicsBundle(speciesId, omics, { scope, compute })
    if (seq !== omicsRequestSeq || speciesId !== props.speciesId || omics !== activePanel.value || scope !== omicsScope.value || compute !== omicsCompute.value) return

    panelCache.set(cacheKey, payload)
    omicsSummary.value = payload.summary || {}
    omicsAnalysis.value = payload.analysis || {}
    availableScopes.value = payload.summary?.available_scopes || ['core']
    if (!availableScopes.value.includes(omicsScope.value)) {
      omicsScope.value = availableScopes.value[0] || 'core'
    }
    distributionKey.value = Object.keys(payload.summary?.distributions || {})[0] || dynamicFieldOptions.value[0] || ''
    scatterKey.value = Object.keys(payload.summary?.scatter || {})[0] || ''
    derivedScatterKey.value = preferredDerivedScatterKey(payload.summary?.scatter || {}, activePanel.value)
    setCustomScatterDefaults(payload.summary, activePanel.value)
    omicsCorrMethod.value = preferredCorrMethod(payload.summary?.correlation_matrices)
    omicsLoading.value = false
    loadOmicsAuxiliaryPayloads()

    if (omicsTab.value === 'table') {
      page.value = 1
      void loadRows({ force: false })
    }
  } catch (error) {
    if (seq !== omicsRequestSeq || speciesId !== props.speciesId || omics !== activePanel.value || scope !== omicsScope.value || compute !== omicsCompute.value) return
    console.error('Failed to load omics panel', error)
    omicsError.value =
      error?.response?.data?.error?.message ||
      error?.message ||
      'Failed to load omics panel data.'
  } finally {
    if (seq === omicsRequestSeq && speciesId === props.speciesId && omics === activePanel.value && scope === omicsScope.value && compute === omicsCompute.value) {
      omicsLoading.value = false
    }
  }
}

async function loadRows(options = {}) {
  const { force = false } = options
  if (!isOmicsPanel.value || !omicsSummary.value || !omicsAnalysis.value) return

  const seq = ++rowsRequestSeq
  const speciesId = props.speciesId
  const omics = activePanel.value
  const scope = omicsScope.value
  const cacheKey = rowsCacheKey()
  syncRouteFromState()
  rowsLoading.value = true
  detailPayload.value = null

  if (!force && rowsCache.has(cacheKey)) {
    rowsPayload.value = rowsCache.get(cacheKey)
    if (!isScientificVisualActive.value) availableScopes.value = rowsPayload.value?.available_scopes || availableScopes.value
    rowsLoading.value = false
    return
  }

  try {
    const payload = await getOmicsRows(speciesId, omics, {
      scope,
      query: rowQuery.value,
      strategy_cluster: rowCluster.value,
      sort_by: sortBy.value,
      page: page.value,
      page_size: pageSize.value,
      feature_filters: featureFilterKey.value
        ? JSON.stringify([
            {
              key: featureFilterKey.value,
              min: featureFilterMin.value || undefined,
              max: featureFilterMax.value || undefined,
            },
          ])
        : '',
    })

    if (seq !== rowsRequestSeq || speciesId !== props.speciesId || omics !== activePanel.value || scope !== omicsScope.value || activePanel.value === 'overview' || activePanel.value === 'cross') return

    rowsCache.set(cacheKey, payload)
    rowsPayload.value = payload
    if (!isScientificVisualActive.value) availableScopes.value = payload?.available_scopes || availableScopes.value
  } catch (error) {
    if (seq !== rowsRequestSeq || speciesId !== props.speciesId || omics !== activePanel.value || scope !== omicsScope.value) return
    console.error('Failed to load rows', error)
    rowsPayload.value = {
      rows: [],
      columns: [],
      total: 0,
      strategy_clusters: [],
      feature_options: [],
    }
    omicsError.value =
      error?.response?.data?.error?.message ||
      error?.message ||
      'Failed to load feature table rows.'
  } finally {
    if (seq === rowsRequestSeq && speciesId === props.speciesId && omics === activePanel.value && scope === omicsScope.value) {
      rowsLoading.value = false
    }
  }
}

async function loadFieldSummaryForDistribution() {
  if (isScientificVisualActive.value) return
  if (!isOmicsPanel.value || !distributionKey.value) {
    fieldSummaryPayload.value = null
    return
  }
  const seq = ++fieldSummaryRequestSeq
  const speciesId = props.speciesId
  const omics = activePanel.value
  const scope = omicsScope.value
  const field = distributionKey.value
  const compute = omicsCompute.value
  const cacheKey = `${speciesId}::${omics}::${scope}::${compute}::${field}`
  if (fieldSummaryCache.has(cacheKey)) {
    if (seq === fieldSummaryRequestSeq && speciesId === props.speciesId && omics === activePanel.value && scope === omicsScope.value && compute === omicsCompute.value && field === distributionKey.value) {
      fieldSummaryPayload.value = fieldSummaryCache.get(cacheKey)
    }
    return
  }
  try {
    const payload = await getOmicsFieldSummary(speciesId, omics, {
      field,
      scope,
      ...(compute !== 'stored' ? { compute } : {}),
    })
    if (seq !== fieldSummaryRequestSeq || speciesId !== props.speciesId || omics !== activePanel.value || scope !== omicsScope.value || compute !== omicsCompute.value || field !== distributionKey.value) return
    fieldSummaryCache.set(cacheKey, payload)
    fieldSummaryPayload.value = payload
  } catch (error) {
    if (seq !== fieldSummaryRequestSeq || speciesId !== props.speciesId || omics !== activePanel.value || scope !== omicsScope.value || field !== distributionKey.value) return
    fieldSummaryPayload.value = null
  }
}

async function loadCustomScatter() {
  if (isScientificVisualActive.value) return
  if (!isOmicsPanel.value || !customScatterX.value || !customScatterY.value) {
    customScatterPayload.value = null
    return
  }
  const seq = ++customScatterRequestSeq
  const speciesId = props.speciesId
  const omics = activePanel.value
  const scope = omicsScope.value
  const x = customScatterX.value
  const y = customScatterY.value
  const compute = omicsCompute.value
  const cacheKey = `${speciesId}::${omics}::${scope}::${compute}::${x}::${y}`
  if (customScatterCache.has(cacheKey)) {
    if (seq === customScatterRequestSeq && speciesId === props.speciesId && omics === activePanel.value && scope === omicsScope.value && compute === omicsCompute.value && x === customScatterX.value && y === customScatterY.value) {
      customScatterPayload.value = customScatterCache.get(cacheKey)
    }
    return
  }
  customScatterLoading.value = true
  try {
    const payload = await getOmicsScatter(speciesId, omics, {
      x,
      y,
      scope,
      sample: compute === 'complete_core' ? 5000 : 1200,
      ...(compute !== 'stored' ? { compute } : {}),
    })
    if (seq !== customScatterRequestSeq || speciesId !== props.speciesId || omics !== activePanel.value || scope !== omicsScope.value || compute !== omicsCompute.value || x !== customScatterX.value || y !== customScatterY.value) return
    customScatterCache.set(cacheKey, payload)
    customScatterPayload.value = payload
  } catch (error) {
    if (seq !== customScatterRequestSeq || speciesId !== props.speciesId || omics !== activePanel.value || scope !== omicsScope.value || x !== customScatterX.value || y !== customScatterY.value) return
    customScatterPayload.value = { points: [], n_total: 0, n_points: 0 }
  } finally {
    if (seq === customScatterRequestSeq && speciesId === props.speciesId && omics === activePanel.value && scope === omicsScope.value && x === customScatterX.value && y === customScatterY.value) {
      customScatterLoading.value = false
    }
  }
}

async function setOmicsScope(scope) {
  if (!['core', 'full'].includes(scope)) return
  if (omicsScope.value === scope) return
  omicsScope.value = scope
  if (!isScientificVisualActive.value && scope === 'full' && omicsCompute.value === 'complete_core') {
    omicsCompute.value = 'stored'
  }
  rowsCache.clear()
  detailCache.clear()
  fieldSummaryCache.clear()
  customScatterCache.clear()
  page.value = 1
  syncRouteFromState()
  if (isOmicsPanel.value) {
    await loadOmics(activePanel.value, { force: true })
  }
}

async function setOmicsCompute(compute) {
  if (isIntegrationVisualActive.value) return
  if (isScientificVisualActive.value) return
  if (!['stored', 'complete_core'].includes(compute)) return
  if (omicsCompute.value === compute) return
  omicsCompute.value = compute
  if (compute === 'complete_core') {
    omicsScope.value = 'core'
  }
  panelCache.clear()
  speciesEnhancedCache.clear()
  speciesEnhanced.value = null
  void loadSpeciesEnhanced(props.speciesId)
  rowsCache.clear()
  detailCache.clear()
  fieldSummaryCache.clear()
  customScatterCache.clear()
  page.value = 1
  syncRouteFromState()
  if (isOmicsPanel.value) {
    await loadOmics(activePanel.value, { force: true })
  } else if (activePanel.value === 'cross' || activePanel.value === 'overview') {
    await loadCrossOmics(props.speciesId, { force: true })
  }
}

function resetTableFilters() {
  rowQuery.value = ''
  rowCluster.value = ''
  sortBy.value = ''
  featureFilterKey.value = ''
  featureFilterMin.value = ''
  featureFilterMax.value = ''
  page.value = 1
  rowsCache.clear()
  syncRouteFromState()
  loadRows({ force: true })
}

async function showDetail(row) {
  const entityId = (isSequenceV1Active.value && (activePanel.value === 'transcriptome' ? row.transcript_id : row.gene_id)) || (isProteomeV3Active.value && row.protein_id) || row.entity_id || row.gene_id || row.transcript_id || row.protein_id
  const speciesId = props.speciesId
  const omics = activePanel.value
  const scope = omicsScope.value
  const cacheKey = `${speciesId}::${omics}::${scope}::${entityId}`
  const seq = ++detailRequestSeq
  detailLoading.value = true

  if (detailCache.has(cacheKey)) {
    detailPayload.value = detailCache.get(cacheKey)
    detailLoading.value = false
    return
  }

  try {
    const payload = await getOmicsRowDetail(speciesId, omics, entityId, {
      scope,
    })
    if (seq !== detailRequestSeq || speciesId !== props.speciesId || omics !== activePanel.value || scope !== omicsScope.value) return
    detailCache.set(cacheKey, payload)
    detailPayload.value = payload
  } catch (error) {
    if (seq !== detailRequestSeq || speciesId !== props.speciesId || omics !== activePanel.value || scope !== omicsScope.value) return
    console.error('Failed to load row detail', error)
    detailPayload.value = { error: error?.message || 'Failed to load row detail.' }
  } finally {
    if (seq === detailRequestSeq && speciesId === props.speciesId && omics === activePanel.value && scope === omicsScope.value) detailLoading.value = false
  }
}

function changePage(delta) {
  page.value = Math.max(1, page.value + delta)
  loadRows({ force: false })
}

function openOverview() {
  activePanel.value = 'overview'
  omicsTab.value = 'basic'
  detailPayload.value = null
  omicsLoading.value = false
  resetOmicsState()
  syncRouteFromState()
  if (!speciesEnhanced.value) {
    void loadSpeciesEnhanced(props.speciesId)
  }
  if (!cross.value && !crossLoading.value) {
    void loadCrossOmics(props.speciesId, { background: true })
  }
}

async function openCross() {
  activePanel.value = 'cross'
  omicsTab.value = 'basic'
  detailPayload.value = null
  omicsLoading.value = false
  resetOmicsState()
  syncRouteFromState()
  if (!cross.value && !crossLoading.value) {
    await loadCrossOmics(props.speciesId)
  }
}

async function openOmics(omics, options = {}) {
  if (!['genome', 'transcriptome', 'proteome'].includes(omics)) return
  const tab = ['basic', 'analysis', 'table'].includes(options.tab) ? options.tab : 'basic'
  if (activePanel.value === omics && omicsSummary.value && omicsAnalysis.value) {
    omicsTab.value = tab
    syncRouteFromState()
    if (tab === 'table' && !(rowsPayload.value.rows || []).length) {
      page.value = 1
      await loadRows({ force: false })
    }
    return
  }
  omicsLoading.value = true
  omicsError.value = ''
  resetOmicsState()
  activePanel.value = omics
  omicsTab.value = tab
  page.value = 1
  syncRouteFromState()
  await nextTick()
  await loadOmics(omics, { force: false })
}

async function openGenomeAnalysis() {
  if (activePanel.value !== 'genome' || !omicsSummary.value || !omicsAnalysis.value) {
    await openOmics('genome', { tab: 'analysis' })
    return
  }
  omicsTab.value = 'analysis'
  syncRouteFromState()
}

async function openTranscriptomeAnalysis() {
  if (activePanel.value !== 'transcriptome' || !omicsSummary.value || !omicsAnalysis.value) {
    await openOmics('transcriptome', { tab: 'analysis' })
    return
  }
  omicsTab.value = 'analysis'
  syncRouteFromState()
}

async function openProteomeAnalysis() {
  if (activePanel.value !== 'proteome' || !omicsSummary.value || !omicsAnalysis.value) {
    await openOmics('proteome', { tab: 'analysis' })
    return
  }
  omicsTab.value = 'analysis'
  syncRouteFromState()
}

async function setOmicsTab(tab) {
  if (!['basic', 'analysis', 'table'].includes(tab)) return
  omicsTab.value = tab
  syncRouteFromState()
  if (isOmicsPanel.value && (!omicsSummary.value || !omicsAnalysis.value) && !omicsLoading.value) {
    omicsLoading.value = true
    await nextTick()
    await loadOmics(activePanel.value, { force: false })
  }
  if (tab === 'table' && isOmicsPanel.value && !(rowsPayload.value.rows || []).length && !omicsLoading.value) {
    page.value = 1
    await loadRows({ force: false })
  }
}

async function initializeForCurrentRoute() {
  speciesError.value = ''
  resetOmicsState()
  page.value = 1
  applyRouteState()
  await loadSpecies(props.speciesId)
  if (['genome', 'transcriptome', 'proteome'].includes(activePanel.value)) {
    await loadOmics(activePanel.value, { force: false })
  }
}

watch(
  () => props.speciesId,
  async () => {
    await initializeForCurrentRoute()
  },
)

watch(
  () => route.query,
  async () => {
    if (routeSyncInFlight) return

    const previousPanel = activePanel.value
    const previousTab = omicsTab.value
    const previousScope = omicsScope.value
    const previousCompute = omicsCompute.value
    const previousTableState = JSON.stringify({
      q: rowQuery.value,
      cluster: rowCluster.value,
      sort: sortBy.value,
      fk: featureFilterKey.value,
      fmin: featureFilterMin.value,
      fmax: featureFilterMax.value,
    })

    applyRouteState()

    if (
      activePanel.value !== previousPanel &&
      ['genome', 'transcriptome', 'proteome'].includes(activePanel.value)
    ) {
      page.value = 1
      await loadOmics(activePanel.value, { force: false })
      return
    }

    if (activePanel.value !== previousPanel && activePanel.value === 'cross') {
      await loadCrossOmics(props.speciesId)
      return
    }

    if (
      (previousScope !== omicsScope.value || previousCompute !== omicsCompute.value) &&
      ['genome', 'transcriptome', 'proteome'].includes(activePanel.value)
    ) {
      page.value = 1
      await loadOmics(activePanel.value, { force: true })
      return
    }

    if (
      previousTab !== omicsTab.value &&
      omicsTab.value === 'table' &&
      isOmicsPanel.value &&
      !omicsLoading.value
    ) {
      page.value = 1
      await loadRows({ force: false })
      return
    }

    const currentTableState = JSON.stringify({
      q: rowQuery.value,
      cluster: rowCluster.value,
      sort: sortBy.value,
      fk: featureFilterKey.value,
      fmin: featureFilterMin.value,
      fmax: featureFilterMax.value,
    })

    if (omicsTab.value === 'table' && currentTableState !== previousTableState && !omicsLoading.value) {
      page.value = 1
      await loadRows({ force: false })
    }
  },
)

watch(
  () => distributionKey.value,
  async () => {
    await loadFieldSummaryForDistribution()
  },
)

watch(
  () => derivedScatterOptions.value.map((item) => item.key).join('|'),
  () => {
    if (!derivedScatterOptions.value.length) {
      derivedScatterKey.value = ''
      return
    }
    if (!derivedScatterOptions.value.some((item) => item.key === derivedScatterKey.value)) {
      derivedScatterKey.value = derivedScatterOptions.value[0].key
    }
  },
)

watch(
  () => [customScatterX.value, customScatterY.value, omicsScope.value, activePanel.value],
  async () => {
    if (!isOmicsPanel.value) return
    await loadCustomScatter()
  },
)

watch(() => [activePanel.value, omicsCompute.value], () => {
  if (species.value?.species_id === props.speciesId && !isScientificVisualActive.value && !speciesEnhanced.value) void loadSpeciesEnhanced(props.speciesId)
})

onMounted(async () => {
  window.addEventListener('stoich-entity-chart-click', handleEntityChartClick)
  await initializeForCurrentRoute()
})

onBeforeUnmount(() => {
  window.removeEventListener('stoich-entity-chart-click', handleEntityChartClick)
  speciesRequestSeq += 1
  omicsRequestSeq += 1
  rowsRequestSeq += 1
  detailRequestSeq += 1
  crossRequestSeq += 1
  fieldSummaryRequestSeq += 1
  customScatterRequestSeq += 1
})
</script>

<style scoped>
.proteome-v3-shell .local-side p { overflow-wrap: anywhere; }
@media (max-width: 1200px) {
  .proteome-v3-shell { grid-template-columns: minmax(0, 1fr); min-width: 0; max-width: 100%; }
  .proteome-v3-shell .local-side { min-width: 0; }
  .proteome-v3-shell > .local-content > .panel p { overflow-wrap: anywhere; }
}
.species-coverage-panel { border-color: rgba(49, 126, 182, 0.2); }
.species-coverage-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.species-coverage-item { min-height: 116px; padding: 13px 14px; border: 1px solid rgba(57, 109, 170, 0.12); border-radius: 13px; background: rgba(248, 252, 255, 0.78); }
.species-coverage-item.species-coverage-limited { border-color: rgba(190, 139, 42, 0.26); background: rgba(255, 251, 239, 0.8); }
.species-coverage-item.species-coverage-missing { border-color: rgba(193, 92, 78, 0.22); background: rgba(255, 247, 245, 0.82); }
.species-coverage-item-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; color: #244e6e; }
.species-coverage-item-head strong { font-size: 0.88rem; line-height: 1.35; }
.species-coverage-item p { margin: 9px 0 0; color: #607d95; font-size: 0.79rem; line-height: 1.48; }
.species-state-badge { flex: 0 0 auto; border-radius: 999px; padding: 4px 7px; color: #2c6b9f; background: #e6f2fb; font-size: 0.67rem; font-weight: 800; }
.species-coverage-limited .species-state-badge { color: #8a641b; background: #fff3cf; }
.species-coverage-missing .species-state-badge { color: #9d4d43; background: #ffebe7; }
@media (max-width: 980px) {
  .species-coverage-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 620px) {
  .species-coverage-grid { grid-template-columns: 1fr; }
}
</style>

