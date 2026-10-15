<template>
  <div class="stack-lg">
    <section v-if="loading" class="panel">
      <p class="muted">Loading Stage 6 case-study gallery...</p>
    </section>

    <section v-else-if="loadError" class="panel">
      <p class="muted">{{ loadError }}</p>
      <button class="btn subtle" type="button" @click="load">Retry</button>
    </section>

    <template v-else-if="payload">
      <section class="panel">
        <div class="section-header">
          <div>
            <div class="eyebrow">Stage 6 internal-data delivery</div>
            <h3>{{ payload.title }}</h3>
            <p class="muted">These cases use the current platform release only. They are descriptive internal-data cases, not external biological validation.</p>
          </div>
          <span class="badge">{{ payload.release?.release_id }}</span>
        </div>
        <div class="case-kpi-grid">
          <div class="case-kpi">
            <span>Species</span>
            <strong>{{ payload.release?.species_count }}</strong>
          </div>
          <div class="case-kpi">
            <span>Datasets</span>
            <strong>{{ payload.release?.dataset_count }}</strong>
          </div>
          <div class="case-kpi">
            <span>Entity rows</span>
            <strong>{{ formatNumber(payload.release?.entity_row_count) }}</strong>
          </div>
          <div class="case-kpi">
            <span>Mode</span>
            <strong>{{ payload.scope?.implementation_mode }}</strong>
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="section-header compact">
          <div>
            <div class="eyebrow">Platform release contract</div>
            <h3>Full database coverage and Model-8 deep cases</h3>
            <p class="muted">The full database remains the coverage layer; the fixed eight-species Model-8 release is the reproducible deep-case layer. Case charts, tables, claims, and downloads are pinned to one release_id.</p>
          </div>
          <span class="badge">{{ model8PlatformManifest.release_id || payload.scope?.model8_platform_release?.release_id }}</span>
        </div>
        <div class="case-kpi-grid advanced-kpi-grid">
          <div class="case-kpi"><span>Model-8 artifacts</span><strong>{{ formatNumber(model8PlatformManifest.artifact_count || payload.scope?.model8_platform_release?.artifact_count) }}</strong></div>
          <div class="case-kpi"><span>Figure mappings</span><strong>{{ formatNumber(model8PlatformManifest.figure_mapping_count || payload.scope?.model8_platform_release?.figure_mapping_count) }}</strong></div>
          <div class="case-kpi"><span>Claims</span><strong>{{ formatNumber(model8PlatformClaims.length) }}</strong></div>
          <div class="case-kpi"><span>Species order</span><strong>{{ (model8PlatformManifest.model8_species_order || []).length || 8 }}</strong></div>
        </div>
        <div v-if="model8PlatformError" class="case-inline-state">
          <p class="muted">{{ model8PlatformError }}</p>
          <button class="btn subtle" type="button" @click="loadModel8PlatformRelease">Retry platform release</button>
        </div>
        <div class="download-row">
          <a class="btn subtle" :href="model8PlatformBundleDownloadUrl()">Download case bundle</a>
          <a class="btn subtle" :href="model8PlatformFileDownloadUrl('platform_release/case_artifact_registry.csv')">Artifact registry</a>
          <a class="btn subtle" :href="model8PlatformFileDownloadUrl('platform_release/figure_mapping.csv')">Figure mapping</a>
          <a class="btn subtle" :href="model8PlatformFileDownloadUrl('platform_release/claims.json')">Claims</a>
          <a class="btn subtle" :href="model8PlatformFileDownloadUrl('platform_release/model8_platform_release_manifest.json')">Manifest</a>
          <router-link class="btn subtle" :to="case4WorkflowRoute()">Case 4 workflow result</router-link>
          <router-link class="btn subtle" :to="case5WorkflowRoute()">Case 5 HVG result</router-link>
        </div>
        <div class="table-wrap compact-top">
          <table class="table compact-table">
            <thead><tr><th>Case</th><th>Status</th><th>Artifacts</th><th>Figure mappings</th><th>Version</th></tr></thead>
            <tbody>
              <tr v-for="(item, caseId) in model8PlatformManifest.case_status || {}" :key="caseId">
                <td>{{ caseId }}</td>
                <td>{{ item.status }}</td>
                <td>{{ formatNumber(item.artifact_count) }}</td>
                <td>{{ formatNumber(item.figure_mapping_count) }}</td>
                <td>{{ item.case_version }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <ResultBlock
        v-if="case1"
        title="Case 1. Cross-species fingerprint atlas"
        :question="case1.research_question"
        :finding="case1.finding"
        :method="case1.method"
        normalization="z-score across displayed complete-omics species"
        missing-policy="available stored fingerprint fields only"
        :n="case1.heatmap?.total_complete_species_count"
        :n-features="case1.heatmap?.x_labels?.length"
        :caveat="case1.limitations"
      >
        <div class="case-tab-row" role="tablist" aria-label="Case 1 views">
          <button type="button" :class="['case-tab', { active: case1Tab === 'basic' }]" @click="case1Tab = 'basic'">Basic atlas</button>
          <button type="button" :class="['case-tab', { active: case1Tab === 'model8' }]" @click="openModel8Case1">Model-8 Atlas</button>
          <button type="button" :class="['case-tab', { active: case1Tab === 'advanced' }]" @click="openCase1Advanced">Advanced taxonomy</button>
          <button type="button" :class="['case-tab', { active: case1Tab === 'phylogeny' }]" @click="case1Tab = 'phylogeny'">Phylogeny-aware</button>
        </div>

        <div v-if="case1Tab === 'basic'" class="grid grid-2">
          <div class="chart-panel">
            <EChart :option="case1Heatmap" :height="620" />
          </div>
          <div>
            <div class="section-header compact">
              <div>
                <div class="eyebrow">Variable features</div>
                <h3>Largest internal ranges</h3>
              </div>
            </div>
            <EChart :option="case1VariabilityChart" :height="300" />
            <div class="table-wrap">
              <table class="table compact-table">
                <thead>
                  <tr>
                    <th>Species</th>
                    <th>Cross points</th>
                    <th>Genome GC</th>
                    <th>Transcript GC</th>
                    <th>Proteome N/aa</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="row in case1.example_species || []" :key="row.species_id">
                    <td>{{ row.display_name }}</td>
                    <td>{{ row.cross_points_count }}</td>
                    <td>{{ formatValue(row.fingerprint?.genome_gc) }}</td>
                    <td>{{ formatValue(row.fingerprint?.transcript_gc) }}</td>
                    <td>{{ formatValue(row.fingerprint?.proteome_n_per_aa) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <div v-else-if="case1Tab === 'model8'" class="stack-lg">
          <section v-if="model8Case1Loading" class="case-inline-state">
            <p class="muted">Loading Model-8 Case 1 atlas...</p>
          </section>
          <section v-else-if="model8Case1Error" class="case-inline-state">
            <p class="muted">{{ model8Case1Error }}</p>
            <button class="btn subtle" type="button" @click="loadModel8Case1">Retry Model-8 Atlas</button>
          </section>
          <template v-else-if="model8Case1">
            <div class="caution-block">
              <strong>Model-8 Atlas</strong>
              <span>Fixed eight-species reference-coordinate analysis. It is separate from the whole-registry Case 1 preview and does not make ecology or phylogeny claims.</span>
            </div>
            <div class="case-kpi-grid advanced-kpi-grid">
              <div class="case-kpi"><span>Species</span><strong>{{ model8Case1.species_count }}</strong></div>
              <div class="case-kpi"><span>Features</span><strong>{{ model8Case1.feature_count }}</strong></div>
              <div class="case-kpi"><span>Bootstrap</span><strong>{{ model8Case1.statistical_plan?.n_bootstrap }}</strong></div>
              <div class="case-kpi"><span>Downloads</span><strong>{{ model8Case1.downloads?.length }}</strong></div>
            </div>
            <div class="grid grid-2">
              <div class="chart-panel">
                <div class="section-header compact"><div><div class="eyebrow">Frozen fingerprint matrix</div><h3>Eight species x feature z-score heatmap</h3></div></div>
                <EChart :option="model8Case1Heatmap" :height="430" />
              </div>
              <div class="chart-panel">
                <div class="section-header compact"><div><div class="eyebrow">Two-dimensional projection</div><h3>PCA over frozen median features</h3></div></div>
                <EChart :option="model8Case1PcaChart" :height="430" />
              </div>
            </div>
            <div class="grid grid-2">
              <div class="table-wrap">
                <div class="section-header compact"><div><div class="eyebrow">Predefined contrasts</div><h3>Pairwise effects preview</h3></div></div>
                <table class="table compact-table"><thead><tr><th>Contrast</th><th>Feature</th><th>SMD</th><th>Cliff</th><th>Wasserstein</th></tr></thead><tbody>
                  <tr v-for="row in model8PredefinedEffects.slice(0, 18)" :key="`${row.contrast}-${row.feature}`"><td>{{ row.contrast_label }}</td><td>{{ row.feature_label }}</td><td>{{ formatValue(row.standardized_median_difference) }}</td><td>{{ formatValue(row.cliffs_delta_sampled) }}</td><td>{{ formatValue(row.wasserstein_distance_quantile) }}</td></tr>
                </tbody></table>
              </div>
              <div class="table-wrap">
                <div class="section-header compact"><div><div class="eyebrow">Generated downloads</div><h3>Case 1 atlas artifacts</h3></div></div>
                <table class="table compact-table"><thead><tr><th>File</th><th>Bytes</th><th>Path</th></tr></thead><tbody>
                  <tr v-for="item in model8Case1.downloads || []" :key="item.name"><td>{{ item.name }}</td><td>{{ formatNumber(item.bytes) }}</td><td>{{ item.path }}</td></tr>
                </tbody></table>
              </div>
            </div>
          </template>
        </div>

        <div v-else-if="case1Tab === 'advanced'" class="stack-lg">
          <section v-if="case1AdvancedLoading" class="case-inline-state">
            <p class="muted">Loading taxonomy-aware Case 1 analysis...</p>
          </section>
          <section v-else-if="case1AdvancedError" class="case-inline-state">
            <p class="muted">{{ case1AdvancedError }}</p>
            <button class="btn subtle" type="button" @click="loadCase1Advanced">Retry taxonomy analysis</button>
          </section>
          <template v-else-if="case1Advanced">
            <div class="caution-block">
              <strong>Interpretation boundary</strong>
              <span>This is taxonomy-aware descriptive analysis. It is not ecological adaptation analysis and not phylogenetic signal analysis.</span>
            </div>

            <div class="case-kpi-grid advanced-kpi-grid">
              <div class="case-kpi">
                <span>Case 1 species</span>
                <strong>{{ case1Advanced.taxonomy_coverage?.species_total }}</strong>
              </div>
              <div class="case-kpi">
                <span>Taxonomy aligned</span>
                <strong>{{ case1Advanced.taxonomy_coverage?.matched_species_count }}</strong>
              </div>
              <div class="case-kpi">
                <span>Phylum coverage</span>
                <strong>{{ percentForRank('phylum') }}</strong>
              </div>
              <div class="case-kpi">
                <span>Kingdom</span>
                <strong>Unavailable</strong>
              </div>
            </div>

            <div class="grid grid-2">
              <div class="chart-panel">
                <div class="section-header compact">
                  <div>
                    <div class="eyebrow">Taxonomy coverage</div>
                    <h3>Rank completeness</h3>
                  </div>
                </div>
                <EChart :option="case1RankCoverageChart" :height="300" />
              </div>
              <div class="table-wrap">
                <table class="table compact-table">
                  <thead>
                    <tr>
                      <th>Rank</th>
                      <th>Present</th>
                      <th>Missing</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="row in case1Advanced.taxonomy_coverage?.rank_coverage || []" :key="row.rank">
                      <td>{{ row.rank }}</td>
                      <td>{{ row.present_count }}</td>
                      <td>{{ row.missing_count }}</td>
                      <td>{{ row.analysis_status }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            <div class="advanced-toolbar">
              <label>
                Rank
                <select class="input select-inline" v-model="advancedRank">
                  <option value="phylum">phylum</option>
                  <option value="class">class</option>
                  <option value="order">order</option>
                </select>
              </label>
              <label>
                Feature
                <select class="input select-inline" v-model="advancedFeature">
                  <option v-for="item in advancedFeatureOptions" :key="item.feature" :value="item.feature">{{ item.label }}</option>
                </select>
              </label>
            </div>

            <div class="grid grid-2">
              <div class="chart-panel">
                <div class="section-header compact">
                  <div>
                    <div class="eyebrow">Taxonomy-aware heatmap</div>
                    <h3>Species sorted by taxonomy</h3>
                  </div>
                </div>
                <EChart :option="case1AdvancedHeatmap" :height="620" />
              </div>
              <div class="chart-panel">
                <div class="section-header compact">
                  <div>
                    <div class="eyebrow">Group comparison</div>
                    <h3>{{ selectedFeatureLabel }} by {{ advancedRank }}</h3>
                  </div>
                </div>
                <EChart :option="case1GroupStatsChart" :height="300" />
                <div class="table-wrap compact-top">
                  <table class="table compact-table">
                    <thead>
                      <tr>
                        <th>Feature</th>
                        <th>Groups</th>
                        <th>H</th>
                        <th>p</th>
                        <th>q</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="row in filteredFeatureTests" :key="`${row.rank_level}-${row.feature}`">
                        <td>{{ row.feature_label }}</td>
                        <td>{{ row.eligible_group_count }}</td>
                        <td>{{ formatValue(row.kruskal_h) }}</td>
                        <td>{{ formatValue(row.kruskal_pvalue) }}</td>
                        <td>{{ formatValue(row.fdr_qvalue) }}</td>
                        <td>{{ row.statistical_status }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </div>

            <div class="grid grid-2">
              <div class="chart-panel">
                <div class="section-header compact">
                  <div>
                    <div class="eyebrow">PCA</div>
                    <h3>Fingerprint space colored by phylum</h3>
                  </div>
                </div>
                <EChart :option="case1PcaChart" :height="380" />
              </div>
              <div class="chart-panel">
                <div class="section-header compact">
                  <div>
                    <div class="eyebrow">PCA loading</div>
                    <h3>Feature contribution</h3>
                  </div>
                </div>
                <EChart :option="case1PcaLoadingChart" :height="380" />
              </div>
            </div>

            <div class="grid grid-2">
              <div class="chart-panel">
                <div class="section-header compact">
                  <div>
                    <div class="eyebrow">Clade signature</div>
                    <h3>Top signature features by {{ advancedRank }}</h3>
                  </div>
                </div>
                <EChart :option="case1SignatureHeatmap" :height="420" />
              </div>
              <div class="table-wrap">
                <table class="table compact-table">
                  <thead>
                    <tr>
                      <th>Taxon</th>
                      <th>n</th>
                      <th>Feature</th>
                      <th>Direction</th>
                      <th>q</th>
                      <th>Caution</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="row in filteredSignatures.slice(0, 18)" :key="`${row.rank_level}-${row.taxon_name}-${row.feature}`">
                      <td>{{ row.taxon_name }}</td>
                      <td>{{ row.n_species }}</td>
                      <td>{{ row.interpretation_label }}</td>
                      <td>{{ row.direction }}</td>
                      <td>{{ formatValue(row.qvalue) }}</td>
                      <td>{{ row.caution_flag || 'none' }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            <div class="grid grid-2">
              <div class="chart-panel">
                <div class="section-header compact">
                  <div>
                    <div class="eyebrow">Taxonomy-proxy distance</div>
                    <h3>Lineage distance vs fingerprint distance</h3>
                  </div>
                </div>
                <EChart :option="case1DistanceChart" :height="360" />
              </div>
              <div class="chart-panel">
                <div class="section-header compact">
                  <div>
                    <div class="eyebrow">Same vs different phylum</div>
                    <h3>Stoichiometric distance summary</h3>
                  </div>
                </div>
                <EChart :option="case1DistanceSummaryChart" :height="260" />
                <p class="annotation">Spearman correlation: {{ formatValue(case1Advanced.distance_taxonomy_alignment?.spearman_correlation) }}; permutation p: {{ formatValue(case1Advanced.distance_taxonomy_alignment?.permutation_pvalue) }}.</p>
              </div>
            </div>

            <div class="grid grid-2">
              <div class="table-wrap">
                <div class="section-header compact">
                  <div>
                    <div class="eyebrow">Representatives</div>
                    <h3>Nearest species to taxon centroid</h3>
                  </div>
                </div>
                <table class="table compact-table">
                  <thead>
                    <tr>
                      <th>Taxon</th>
                      <th>Species</th>
                      <th>Distance</th>
                      <th>Open</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="row in filteredRepresentatives.slice(0, 18)" :key="`rep-${row.rank_level}-${row.taxon_name}-${row.species_id}`">
                      <td>{{ row.taxon_name }}</td>
                      <td>{{ row.display_name }}</td>
                      <td>{{ formatValue(row.distance_to_centroid) }}</td>
                      <td><router-link :to="`/species/${row.species_id}`">Open</router-link></td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div class="table-wrap">
                <div class="section-header compact">
                  <div>
                    <div class="eyebrow">Outliers</div>
                    <h3>Farthest species from taxon centroid</h3>
                  </div>
                </div>
                <table class="table compact-table">
                  <thead>
                    <tr>
                      <th>Taxon</th>
                      <th>Species</th>
                      <th>Score</th>
                      <th>Top deviating features</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="row in filteredOutliers.slice(0, 18)" :key="`out-${row.rank_level}-${row.taxon_name}-${row.species_id}`">
                      <td>{{ row.taxon_name }}</td>
                      <td>{{ row.display_name }}</td>
                      <td>{{ formatValue(row.outlier_score) }}</td>
                      <td>{{ featureDeltaText(row.top_deviating_features) }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            <div class="table-wrap">
              <div class="section-header compact">
                <div>
                  <div class="eyebrow">Generated artifacts</div>
                  <h3>Case 1 advanced CSV outputs</h3>
                </div>
              </div>
              <table class="table compact-table">
                <thead>
                  <tr>
                    <th>File</th>
                    <th>Rows</th>
                    <th>Path</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="artifact in case1Advanced.artifacts || []" :key="artifact.name">
                    <td>{{ artifact.name }}</td>
                    <td>{{ artifact.row_count }}</td>
                    <td>{{ artifact.path }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </template>
        </div>
        <PhylogenyInsightPanel
          v-else
          title="Case 1 phylogeny-aware sensitivity"
          subtitle="The Case 1 fingerprint matrix is evaluated against the active subset30 branch-length tree for Pagel lambda and predefined OLS/PGLS comparison."
          :show-downloads-link="true"
        />
      </ResultBlock>

      <ResultBlock
        v-if="case2"
        title="Case 2. Single-species cross-omics coupling"
        :question="case2.research_question"
        :finding="case2.finding"
        :method="case2.method"
        normalization="stored species cross_omics_payload"
        missing-policy="available correlation_matrix, cross_points, and top_transformations"
        :n="case2.cross_points?.length"
        :n-features="Object.keys(case2.correlation_matrix || {}).length"
        :caveat="case2.limitations"
      >
        <div class="case-selected-row">
          <div>
            <span class="eyebrow">Selected species</span>
            <strong>{{ case2.selected_species?.display_name }}</strong>
            <p class="muted">{{ case2.selected_species?.selection_rule }}</p>
          </div>
          <router-link class="btn subtle" :to="`/species/${case2.selected_species?.species_id}`">Open species</router-link>
        </div>
        <div class="grid grid-2">
          <EChart :option="case2CorrelationChart" :height="340" />
          <EChart :option="case2ScatterChart" :height="340" />
        </div>
        <div class="grid grid-2">
          <div class="table-wrap">
            <table class="table compact-table">
              <thead>
                <tr>
                  <th>Candidate species</th>
                  <th>Cross points</th>
                  <th>Transformations</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in case2.candidate_species || []" :key="row.species_id">
                  <td>{{ row.display_name }}</td>
                  <td>{{ row.cross_points_count }}</td>
                  <td>{{ row.top_transformations_count }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="table-wrap">
            <table class="table compact-table">
              <thead>
                <tr>
                  <th>Gene</th>
                  <th>Transcript GC</th>
                  <th>Proteome N/aa</th>
                  <th>RNA to protein shift std</th>
                  <th>Legacy proxy</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in case2.top_transformations || []" :key="`${row.gene_id || row.gene_name}-${row.rna_to_protein_n_shift_std ?? row.rna_to_protein_n_shift}`">
                  <td>{{ row.gene_name || row.gene_id }}</td>
                  <td>{{ formatValue(row.transcript_gc) }}</td>
                  <td>{{ formatValue(row.proteome_n_per_aa) }}</td>
                  <td>{{ formatValue(row.rna_to_protein_n_shift_std ?? row.rna_to_protein_n_shift) }}</td>
                  <td>{{ formatValue(row.rna_to_protein_n_shift_legacy_proxy ?? row.rna_to_protein_n_shift) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
        <div class="case-tab-row" role="tablist" aria-label="Case 2 ID mapping">
          <button type="button" :class="['case-tab', { active: case2AdvancedOpen }]" @click="openCase2Advanced">Advanced ID chain</button>
          <button type="button" :class="['case-tab', { active: case2FunctionOpen }]" @click="openCase2Function">Functional chain</button>
          <button type="button" :class="['case-tab', { active: model8Case2Open }]" @click="openModel8Case2">Model-8 coupling</button>
        </div>
        <div v-if="case2AdvancedOpen" class="stack-lg">
          <section v-if="case2IdLoading" class="case-inline-state"><p class="muted">Loading Case 2 ID mapping payload...</p></section>
          <section v-else-if="case2IdError" class="case-inline-state">
            <p class="muted">{{ case2IdError }}</p>
            <button class="btn subtle" type="button" @click="loadCase2IdMapping">Retry ID mapping</button>
          </section>
          <template v-else-if="case2IdMapping">
            <div class="caution-block">
              <strong>High-confidence interpretation rule</strong>
              <span>Main Case 2 ID evidence uses mapping_status=ok and mapping_confidence=high by default; conflict rows remain visible for diagnostics.</span>
            </div>
            <div class="case-kpi-grid advanced-kpi-grid">
              <div class="case-kpi"><span>Selected species</span><strong>{{ case2IdMapping.selected_species?.species_id }}</strong></div>
              <div class="case-kpi"><span>Case2 score</span><strong>{{ formatValue(case2IdMapping.selected_species?.case2_score) }}</strong></div>
              <div class="case-kpi"><span>Complete chain</span><strong>{{ formatPercentValue(case2IdMapping.mapping_summary?.complete_chain_rate) }}</strong></div>
              <div class="case-kpi"><span>Conflict rate</span><strong>{{ formatPercentValue(case2IdMapping.mapping_summary?.conflict_rate) }}</strong></div>
            </div>
            <div class="grid grid-2">
              <EChart :option="case2IdCoverageChart" :height="300" />
              <div class="table-wrap">
                <table class="table compact-table">
                  <thead><tr><th>Candidate species</th><th>Score</th><th>Complete</th><th>Conflict</th><th>External</th></tr></thead>
                  <tbody>
                    <tr v-for="row in case2IdMapping.candidate_species || []" :key="row.species_id">
                      <td>{{ row.species_id }}</td>
                      <td>{{ formatValue(row.case2_score) }}</td>
                      <td>{{ formatPercentValue(row.complete_chain_rate) }}</td>
                      <td>{{ formatPercentValue(row.conflict_rate) }}</td>
                      <td>{{ formatPercentValue(row.external_high_confidence_rate) }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
            <div class="table-wrap">
              <div class="section-header compact">
                <div><h3>Gene-transcript-protein chain table</h3><p>First 250 canonical-ranked rows from the runtime mapping payload.</p></div>
              </div>
              <table class="table compact-table">
                <thead><tr><th>Gene</th><th>Transcript</th><th>Protein</th><th>Status</th><th>Confidence</th><th>External</th><th>Open</th></tr></thead>
                <tbody>
                  <tr v-for="row in case2IdMapping.chain_table || []" :key="`${row.gene_id}-${row.transcript_id}-${row.protein_id}`">
                    <td>{{ row.gene_id }}</td>
                    <td>{{ row.transcript_id || '-' }}</td>
                    <td>{{ row.protein_id || '-' }}</td>
                    <td><span :class="['badge', row.mapping_status === 'conflict' ? 'danger-badge' : '']">{{ row.mapping_status }}</span></td>
                    <td>{{ row.mapping_confidence }}</td>
                    <td>{{ externalIdSummary(row.external_ids) }}</td>
                    <td><router-link class="ghost-link" :to="`/species/${row.species_id}/entity/${row.gene_id}`">Report</router-link></td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div class="table-wrap">
              <div class="section-header compact">
                <div><h3>Conflict diagnostics</h3><p>Rows retained from internal mapping QC and excluded from strict interpretation.</p></div>
              </div>
              <table class="table compact-table">
                <thead><tr><th>Gene</th><th>Transcript</th><th>Protein</th><th>Reason</th></tr></thead>
                <tbody>
                  <tr v-for="row in case2IdMapping.conflict_table || []" :key="`${row.gene_id}-${row.transcript_id}-${row.protein_id}`">
                    <td>{{ row.gene_id }}</td>
                    <td>{{ row.transcript_id || '-' }}</td>
                    <td>{{ row.protein_id || '-' }}</td>
                    <td>{{ row.conflict_reason }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </template>
        </div>
        <div v-if="model8Case2Open" class="stack-lg">
          <section v-if="model8Case2Loading" class="case-inline-state"><p class="muted">Loading Model-8 Case 2 coupling...</p></section>
          <section v-else-if="model8Case2Error" class="case-inline-state">
            <p class="muted">{{ model8Case2Error }}</p>
            <button class="btn subtle" type="button" @click="loadModel8Case2">Retry Model-8 coupling</button>
          </section>
          <template v-else-if="model8Case2">
            <div class="caution-block"><strong>Interpretation boundary</strong><span>Sequence-derived DNA/CDS-RNA-Protein association. It does not imply expression regulation, protein abundance regulation, ecology, or phylogeny.</span></div>
            <div class="case-kpi-grid advanced-kpi-grid">
              <div class="case-kpi"><span>Main chains</span><strong>{{ formatNumber(model8Case2.main_entity_count) }}</strong></div>
              <div class="case-kpi"><span>Feature pairs</span><strong>{{ model8Case2.feature_pair_count }}</strong></div>
              <div class="case-kpi"><span>Null draws</span><strong>{{ model8Case2.n_null }}</strong></div>
              <div class="case-kpi"><span>Status</span><strong>{{ model8Case2.status }}</strong></div>
            </div>
            <div class="grid grid-2">
              <div class="chart-panel"><div class="section-header compact"><div><div class="eyebrow">Observed coupling</div><h3>Per-species Spearman matrix</h3></div></div><EChart :option="model8Case2Heatmap" :height="430" /></div>
              <div class="chart-panel"><div class="section-header compact"><div><div class="eyebrow">Observed vs null</div><h3>Excess association by null model</h3></div></div><EChart :option="model8Case2NullChart" :height="430" /></div>
            </div>
            <div class="grid grid-2">
              <div class="table-wrap"><div class="section-header compact"><div><div class="eyebrow">Chain QC</div><h3>Eight fixed species</h3></div></div><table class="table compact-table"><thead><tr><th>Species</th><th>Main chains</th><th>Chain rate</th><th>Conflict</th></tr></thead><tbody><tr v-for="row in model8Case2.chain_qc || []" :key="row.case_code"><td>{{ row.case_code }}</td><td>{{ formatNumber(row.main_chain_rows) }}</td><td>{{ formatPercentValue(row.chain_rate) }}</td><td>{{ formatPercentValue(row.conflict_rate) }}</td></tr></tbody></table></div>
              <div class="table-wrap"><div class="section-header compact"><div><div class="eyebrow">Generated downloads</div><h3>Case 2 coupling artifacts</h3></div></div><table class="table compact-table"><thead><tr><th>File</th><th>Bytes</th><th>Path</th></tr></thead><tbody><tr v-for="item in model8Case2.downloads || []" :key="item.name"><td>{{ item.name }}</td><td>{{ formatNumber(item.bytes) }}</td><td>{{ item.path }}</td></tr></tbody></table></div>
            </div>
            <div class="table-wrap"><div class="section-header compact"><div><div class="eyebrow">Top residual candidates</div><h3>High transformations, not drivers</h3></div></div><table class="table compact-table"><thead><tr><th>Species</th><th>Pair</th><th>Class</th><th>Residual z</th><th>Gene</th></tr></thead><tbody><tr v-for="row in model8Case2TopTransformations.slice(0, 20)" :key="`${row.case_code}-${row.pair_id}-${row.gene_id}-${row.residual_z}`"><td>{{ row.case_code }}</td><td>{{ row.pair_id }}</td><td>{{ row.residual_class }}</td><td>{{ formatValue(row.residual_z) }}</td><td>{{ row.gene_id }}</td></tr></tbody></table></div>
          </template>
        </div>

        <div v-if="case2FunctionOpen" class="stack-lg">
          <section v-if="case2FunctionLoading" class="case-inline-state"><p class="muted">Loading Case 2 functional chain...</p></section>
          <section v-else-if="case2FunctionError" class="case-inline-state">
            <p class="muted">{{ case2FunctionError }}</p>
            <button class="btn subtle" type="button" @click="loadCase2Function">Retry functional chain</button>
          </section>
          <template v-else-if="case2Function">
            <div class="case-kpi-grid advanced-kpi-grid">
              <div class="case-kpi"><span>Selected species</span><strong>{{ case2Function.selected_species?.species_id }}</strong></div>
              <div class="case-kpi"><span>Chain rows</span><strong>{{ case2Function.chain_table?.length || 0 }}</strong></div>
              <div class="case-kpi"><span>GO linked</span><strong>{{ case2Function.chain_table?.filter((row) => row.go_term_count).length || 0 }}</strong></div>
              <div class="case-kpi"><span>KEGG linked</span><strong>{{ case2Function.chain_table?.filter((row) => row.kegg_link_count).length || 0 }}</strong></div>
            </div>
            <div class="table-wrap">
              <table class="table compact-table">
                <thead><tr><th>Gene</th><th>Protein</th><th>UniProt</th><th>KEGG gene</th><th>GO</th><th>KEGG</th><th>Report</th></tr></thead>
                <tbody>
                  <tr v-for="row in case2Function.chain_table || []" :key="`${row.gene_id}-${row.protein_id}-${row.uniprot_accession}`">
                    <td>{{ row.gene_id }}</td>
                    <td>{{ row.protein_id }}</td>
                    <td>{{ row.uniprot_accession }}</td>
                    <td>{{ row.kegg_gene_id }}</td>
                    <td>{{ row.go_term_count }}</td>
                    <td>{{ row.kegg_link_count }}</td>
                    <td><router-link class="ghost-link" :to="`/species/${row.species_id}/entity/${row.gene_id || row.protein_id}`">Open</router-link></td>
                  </tr>
                </tbody>
              </table>
            </div>
          </template>
        </div>
      </ResultBlock>

      <ResultBlock
        v-if="case3"
        title="Case 3. Candidate protein report"
        :question="case3.research_question"
        :finding="case3.finding"
        :method="case3.method"
        normalization="same-species proteome percentile"
        missing-policy="available proteome EntityRecord numeric_summary / payload_json fields"
        :n="case3.feature_profile?.[0]?.coverage"
        :n-features="case3.feature_profile?.length"
        :caveat="case3.limitations"
      >
        <div class="case-selected-row">
          <div>
            <span class="eyebrow">{{ case3.selected_entity?.species_name }}</span>
            <strong>{{ case3.selected_entity?.protein_id }}</strong>
            <p class="muted">{{ case3.selected_entity?.description }}</p>
          </div>
          <router-link class="btn subtle" :to="`/species/${case3.selected_entity?.species_id}/entity/${case3.selected_entity?.protein_id}`">Open report</router-link>
        </div>
        <div class="grid grid-2">
          <EChart :option="case3PercentileChart" :height="340" />
          <div class="table-wrap">
            <table class="table compact-table">
              <thead>
                <tr>
                  <th>Feature</th>
                  <th>Value</th>
                  <th>Percentile</th>
                  <th>Coverage</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in case3.feature_profile || []" :key="row.field">
                  <td>{{ row.label }}</td>
                  <td>{{ formatValue(row.value) }} {{ row.unit }}</td>
                  <td>{{ formatValue(row.species_percentile) }}</td>
                  <td>{{ row.coverage }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
        <div v-if="case3.functional_evidence?.available" class="grid grid-2">
          <div class="table-wrap">
            <div class="section-header compact"><h3>GO evidence</h3></div>
            <table class="table compact-table">
              <thead><tr><th>GO</th><th>Namespace</th><th>Name</th></tr></thead>
              <tbody>
                <tr v-for="term in case3.functional_evidence.go?.terms || []" :key="term.go_id">
                  <td>{{ term.go_id }}</td>
                  <td>{{ term.go_namespace }}</td>
                  <td>{{ term.go_name }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="table-wrap">
            <div class="section-header compact"><h3>KEGG evidence</h3></div>
            <table class="table compact-table">
              <thead><tr><th>ID</th><th>Type</th><th>Name</th></tr></thead>
              <tbody>
                <tr v-for="term in case3.functional_evidence.kegg?.annotations || []" :key="term.annotation_type + term.annotation_id">
                  <td>{{ term.annotation_id }}</td>
                  <td>{{ term.annotation_type }}</td>
                  <td>{{ term.annotation_name }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
        <div class="case-tab-row" role="tablist" aria-label="Case 3 Model-8 evidence">
          <button type="button" :class="['case-tab', { active: model8Case3Open }]" @click="openModel8Case3">Model-8 evidence</button>
        </div>
        <div v-if="model8Case3Open" class="stack-lg">
          <section v-if="model8Case3Loading" class="case-inline-state"><p class="muted">Loading Model-8 Case 3 evidence chain...</p></section>
          <section v-else-if="model8Case3Error" class="case-inline-state">
            <p class="muted">{{ model8Case3Error }}</p>
            <button class="btn subtle" type="button" @click="loadModel8Case3">Retry Model-8 evidence</button>
          </section>
          <template v-else-if="model8Case3">
            <div class="caution-block"><strong>Interpretation boundary</strong><span>Model-8 case evidence identifies descriptive residual candidates and matched controls. It must not be named as driver, causal regulator, or adaptive proof.</span></div>
            <div class="case-kpi-grid advanced-kpi-grid">
              <div class="case-kpi"><span>Reports</span><strong>{{ model8Case3.formal_report_count }}</strong></div>
              <div class="case-kpi"><span>Primary</span><strong>{{ model8Case3.primary_candidate_count }}</strong></div>
              <div class="case-kpi"><span>Controls</span><strong>{{ model8Case3.matched_control_count }}</strong></div>
              <div class="case-kpi"><span>Annotated</span><strong>{{ model8Case3.annotation_available_count }}</strong></div>
            </div>
            <div class="grid grid-2">
              <div class="chart-panel"><div class="section-header compact"><div><div class="eyebrow">Candidate priority</div><h3>Residual evidence versus null excess</h3></div></div><EChart :option="model8Case3PriorityChart" :height="390" /></div>
              <div class="table-wrap"><div class="section-header compact"><div><div class="eyebrow">Generated downloads</div><h3>Case 3 evidence artifacts</h3></div></div><table class="table compact-table"><thead><tr><th>File</th><th>Bytes</th><th>Path</th></tr></thead><tbody><tr v-for="item in model8Case3.downloads || []" :key="item.name"><td>{{ item.name }}</td><td>{{ formatNumber(item.bytes) }}</td><td>{{ item.path }}</td></tr></tbody></table></div>
            </div>
            <div class="table-wrap">
              <div class="section-header compact"><div><div class="eyebrow">Formal reports</div><h3>Positive, negative, and matched-control entities</h3></div></div>
              <table class="table compact-table">
                <thead><tr><th>Species</th><th>Direction</th><th>Pair</th><th>Gene</th><th>Protein</th><th>Residual z</th><th>GO</th><th>KEGG</th><th>Open</th></tr></thead>
                <tbody>
                  <tr v-for="row in model8Case3ReportsIndex" :key="row.report_id">
                    <td>{{ row.case_code }}</td>
                    <td><span :class="['badge', row.direction === 'matched_control' ? 'muted-badge' : '']">{{ row.direction }}</span></td>
                    <td>{{ row.pair_id }}</td>
                    <td>{{ row.gene_id }}</td>
                    <td>{{ row.protein_id }}</td>
                    <td>{{ formatValue(row.residual_z) }}</td>
                    <td>{{ row.go_count }}</td>
                    <td>{{ row.kegg_count }}</td>
                    <td><router-link class="ghost-link" :to="`/species/${model8Case3SpeciesId(row.case_code)}/entity/${row.gene_id || row.protein_id}`">Report</router-link></td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div class="table-wrap">
              <div class="section-header compact"><div><div class="eyebrow">Matched controls</div><h3>GC, length, entropy, and composition distance</h3></div></div>
              <table class="table compact-table">
                <thead><tr><th>Species</th><th>Target</th><th>Control</th><th>Pair</th><th>Distance</th><th>Control residual z</th></tr></thead>
                <tbody>
                  <tr v-for="row in model8Case3Candidates?.matched_controls || []" :key="`${row.case_code}-${row.control_protein_id}`">
                    <td>{{ row.case_code }}</td>
                    <td>{{ row.target_protein_id || row.target_gene_id }}</td>
                    <td>{{ row.control_protein_id || row.control_gene_id }}</td>
                    <td>{{ row.pair_id }}</td>
                    <td>{{ formatValue(row.matched_control_distance) }}</td>
                    <td>{{ formatValue(row.control_residual_z) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </template>
        </div>
      </ResultBlock>

      <ResultBlock
        v-if="case4"
        id="case4"
        title="Case 4. Sequence upload gold standard"
        :question="case4.research_question"
        :finding="case4.finding"
        :method="case4.method"
        normalization="independent expected features versus frozen full-release feature tables"
        missing-policy="explicit degraded/unavailable status for CDS and GFF3 proxy cases"
        :n="model8Case4?.protein_gold_records"
        :n-features="model8Case4Validation?.agreement?.total_checks"
        :caveat="case4.limitations"
      >
        <div class="case-tab-row" role="tablist" aria-label="Case 4 upload gold standard">
          <button type="button" :class="['case-tab', { active: model8Case4Open }]" @click="openModel8Case4">Model-8 upload gold</button>
          <router-link class="case-tab" :to="case4WorkflowRoute()">Open {{ selectedModel8Case4Species }} workflow result</router-link>
          <router-link class="case-tab" to="/sequence-analysis">New upload workflow</router-link>
        </div>
        <div v-if="model8Case4Open" class="stack-lg">
          <section v-if="model8Case4Loading" class="case-inline-state"><p class="muted">Loading Model-8 Case 4 upload gold standard...</p></section>
          <section v-else-if="model8Case4Error" class="case-inline-state">
            <p class="muted">{{ model8Case4Error }}</p>
            <button class="btn subtle" type="button" @click="loadModel8Case4">Retry Model-8 upload gold</button>
          </section>
          <template v-else-if="model8Case4">
            <div class="caution-block"><strong>Runtime privacy boundary</strong><span>Gold-standard examples are public fixed inputs; ordinary user uploads remain runtime-isolated, TTL-scoped, and outside the public registry.</span></div>
            <div class="case-kpi-grid advanced-kpi-grid">
              <div class="case-kpi"><span>Protein gold</span><strong>{{ formatNumber(model8Case4.protein_gold_records) }}</strong></div>
              <div class="case-kpi"><span>Nucleotide gold</span><strong>{{ formatNumber(model8Case4.nucleotide_gold_records) }}</strong></div>
              <div class="case-kpi"><span>Field checks</span><strong>{{ formatNumber(model8Case4Validation?.agreement?.total_checks) }}</strong></div>
              <div class="case-kpi"><span>Pass rate</span><strong>{{ formatPercentValue(model8Case4Validation?.agreement?.pass_rate) }}</strong></div>
            </div>
            <div class="grid grid-2">
              <div class="table-wrap"><div class="section-header compact"><div><div class="eyebrow">Tolerance report</div><h3>Independent expected vs stored release features</h3></div></div><table class="table compact-table"><thead><tr><th>Omics</th><th>Field</th><th>Checked</th><th>Pass</th><th>Max delta</th><th>Tolerance</th></tr></thead><tbody><tr v-for="row in model8Case4Gold?.tolerance_report || []" :key="`${row.omics}-${row.field}`"><td>{{ row.omics }}</td><td>{{ row.field }}</td><td>{{ formatNumber(row.checked_count) }}</td><td>{{ formatNumber(row.pass_count) }}</td><td>{{ formatValue(row.max_abs_delta) }}</td><td>{{ row.tolerance }}</td></tr></tbody></table></div>
              <div class="table-wrap"><div class="section-header compact"><div><div class="eyebrow">Generated downloads</div><h3>Gold-standard artifacts</h3></div></div><table class="table compact-table"><thead><tr><th>File</th><th>Bytes</th><th>Path</th></tr></thead><tbody><tr v-for="item in model8Case4.downloads || []" :key="item.name"><td>{{ item.name }}</td><td>{{ formatNumber(item.bytes) }}</td><td>{{ item.path }}</td></tr></tbody></table></div>
            </div>
            <div class="grid grid-2">
              <div class="table-wrap"><div class="section-header compact"><div><div class="eyebrow">Workflow examples</div><h3>Upload routes for users</h3></div></div><table class="table compact-table"><thead><tr><th>ID</th><th>Analysis</th><th>Omics</th><th>Group</th><th>Reference</th></tr></thead><tbody><tr v-for="row in model8Case4Workflows?.workflow_examples || []" :key="row.workflow_id"><td>{{ row.workflow_id }}</td><td>{{ row.analysis_type }}</td><td>{{ row.omics_type }}</td><td>{{ row.group_field || '-' }}</td><td>{{ row.reference_group || '-' }}</td></tr></tbody></table></div>
              <div class="table-wrap"><div class="section-header compact"><div><div class="eyebrow">Privacy and safety</div><h3>Upload controls</h3></div></div><table class="table compact-table"><thead><tr><th>Control</th><th>Status</th><th>Evidence</th></tr></thead><tbody><tr v-for="row in model8Case4Workflows?.privacy_security_checks || []" :key="row.control"><td>{{ row.control }}</td><td>{{ row.platform_status }}</td><td>{{ row.evidence }}</td></tr></tbody></table></div>
            </div>
            <div id="case4-species-results" class="species-workbench">
              <div class="section-header compact">
                <div><div class="eyebrow">Species-level results</div><h3>Upload gold-standard details by model organism</h3></div>
                <router-link class="btn subtle" :to="case4WorkflowRoute()">Open {{ selectedModel8Case4Species }} in workflow</router-link>
              </div>
              <div class="case-tab-row species-tabs" role="tablist" aria-label="Case 4 species detail">
                <button v-for="code in model8SpeciesCodes" :key="`case4-${code}`" type="button" :class="['case-tab', { active: selectedModel8Case4Species === code }]" @click="loadModel8Case4Species(code)">{{ code }}</button>
              </div>
              <section v-if="model8Case4SpeciesLoading" class="case-inline-state"><p class="muted">Loading {{ selectedModel8Case4Species }} gold-standard rows...</p></section>
              <section v-else-if="model8Case4SpeciesError" class="case-inline-state"><p class="muted">{{ model8Case4SpeciesError }}</p></section>
              <template v-else-if="model8Case4Species">
                <div class="case-kpi-grid advanced-kpi-grid">
                  <div class="case-kpi"><span>Species</span><strong>{{ model8Case4Species.species_status?.scientific_name || model8Case4Species.case_code }}</strong></div>
                  <div class="case-kpi"><span>Protein records</span><strong>{{ formatNumber(model8Case4Species.species_status?.protein_records) }}</strong></div>
                  <div class="case-kpi"><span>Nucleotide records</span><strong>{{ formatNumber(model8Case4Species.species_status?.nucleotide_records) }}</strong></div>
                  <div class="case-kpi"><span>Agreement preview</span><strong>{{ formatNumber(model8Case4Species.kpis?.agreement_rows_previewed) }}</strong></div>
                </div>
                <div class="download-row compact-top">
                  <a class="btn subtle" :href="model8Case4Species.downloads?.protein_gold_fasta">Protein FASTA</a>
                  <a class="btn subtle" :href="model8Case4Species.downloads?.nucleotide_gold_fasta">CDS/transcript FASTA</a>
                  <a class="btn subtle" :href="model8Case4Species.downloads?.gff3_subset">GFF3 subset</a>
                  <a class="btn subtle" :href="model8Case4Species.downloads?.platform_gold_agreement">Agreement CSV</a>
                </div>
                <div class="grid grid-2">
                  <div class="table-wrap"><div class="section-header compact"><div><div class="eyebrow">Protein features</div><h3>{{ selectedModel8Case4Species }} expected protein chemistry</h3></div></div><table class="table compact-table"><thead><tr><th v-for="col in tableColumns(model8Case4Species.tables?.expected_protein_features?.rows)" :key="col">{{ col }}</th></tr></thead><tbody><tr v-for="(row, idx) in compactRows(model8Case4Species.tables?.expected_protein_features?.rows)" :key="`case4-protein-${idx}`"><td v-for="col in tableColumns(model8Case4Species.tables?.expected_protein_features?.rows)" :key="col">{{ formatValue(row[col]) }}</td></tr></tbody></table></div>
                  <div class="table-wrap"><div class="section-header compact"><div><div class="eyebrow">CDS/transcript features</div><h3>{{ selectedModel8Case4Species }} expected nucleotide chemistry</h3></div></div><table class="table compact-table"><thead><tr><th v-for="col in tableColumns(model8Case4Species.tables?.expected_cds_transcript_features?.rows)" :key="col">{{ col }}</th></tr></thead><tbody><tr v-for="(row, idx) in compactRows(model8Case4Species.tables?.expected_cds_transcript_features?.rows)" :key="`case4-cds-${idx}`"><td v-for="col in tableColumns(model8Case4Species.tables?.expected_cds_transcript_features?.rows)" :key="col">{{ formatValue(row[col]) }}</td></tr></tbody></table></div>
                </div>
                <div class="grid grid-2">
                  <div class="table-wrap"><div class="section-header compact"><div><div class="eyebrow">Agreement rows</div><h3>Expected values versus stored platform values</h3></div></div><table class="table compact-table"><thead><tr><th v-for="col in tableColumns(model8Case4Species.tables?.platform_gold_agreement?.rows)" :key="col">{{ col }}</th></tr></thead><tbody><tr v-for="(row, idx) in compactRows(model8Case4Species.tables?.platform_gold_agreement?.rows)" :key="`case4-agree-${idx}`"><td v-for="col in tableColumns(model8Case4Species.tables?.platform_gold_agreement?.rows)" :key="col">{{ formatValue(row[col]) }}</td></tr></tbody></table></div>
                  <div class="table-wrap"><div class="section-header compact"><div><div class="eyebrow">Selected records</div><h3>Fixed-seed representatives for this species</h3></div></div><table class="table compact-table"><thead><tr><th v-for="col in tableColumns(model8Case4Species.tables?.selected_gold_records?.rows)" :key="col">{{ col }}</th></tr></thead><tbody><tr v-for="(row, idx) in compactRows(model8Case4Species.tables?.selected_gold_records?.rows)" :key="`case4-select-${idx}`"><td v-for="col in tableColumns(model8Case4Species.tables?.selected_gold_records?.rows)" :key="col">{{ formatValue(row[col]) }}</td></tr></tbody></table></div>
                </div>
              </template>
            </div>
          </template>
        </div>
      </ResultBlock>

      <ResultBlock
        v-if="case5"
        id="case5"
        title="Case 5. Eight-model-organism HVG-Stoich flagship system"
        :question="case5.research_question"
        :finding="case5.finding"
        :method="case5.method"
        normalization="expression HVG consensus linked to versioned transcript/protein stoichiometric features"
        missing-policy="datasets below the declared feature-mapping threshold remain Phase 1 evidence only"
        :n="case5.hvg_stoich?.phase1_complete_count"
        :n-features="case5.hvg_stoich?.phase2_complete_count"
        :caveat="case5.limitations"
      >
        <div class="case-tab-row" role="tablist" aria-label="Case 5 HVG-Stoich flagship workflow">
          <router-link class="case-tab active" :to="case5WorkflowRoute()">Open {{ selectedModel8Case5Species }} workflow result</router-link>
          <a class="case-tab" :href="model8PlatformFileDownloadUrl('case5_hvg_stoich/candidate_genes.csv')">Candidate genes CSV</a>
          <a class="case-tab" :href="model8PlatformFileDownloadUrl('case5_hvg_stoich/enrichment_results.csv')">Enrichment CSV</a>
        </div>
        <div class="case-kpi-grid advanced-kpi-grid">
          <div class="case-kpi"><span>Phase 1 species</span><strong>{{ formatNumber(case5.hvg_stoich?.phase1_complete_count) }}</strong></div>
          <div class="case-kpi"><span>Phase 2 species</span><strong>{{ formatNumber(case5.hvg_stoich?.phase2_complete_count) }}</strong></div>
          <div class="case-kpi"><span>Mapping threshold</span><strong>{{ formatPercentValue(case5.hvg_stoich?.mapping_threshold_phase2) }}</strong></div>
          <div class="case-kpi"><span>Acceptance</span><strong>{{ case5.hvg_stoich?.meets_plan_minimum ? 'passed' : 'boundary' }}</strong></div>
        </div>
        <div class="table-wrap">
          <div class="section-header compact"><div><div class="eyebrow">Eight fixed species</div><h3>HVG-Stoich ingest and mapping status</h3></div></div>
          <table class="table compact-table">
            <thead><tr><th>Species</th><th>Ingest</th><th>Phase 1</th><th>Phase 2</th><th>Genes</th><th>Cells/samples</th><th>Mapped</th><th>Rate</th><th>Workflow</th></tr></thead>
            <tbody>
              <tr v-for="row in case5.hvg_stoich?.species_status || []" :key="row.case_code">
                <td>{{ row.case_code }}</td>
                <td>{{ row.ingest_status }}</td>
                <td>{{ row.phase1_status }}</td>
                <td>{{ row.phase2_status }}</td>
                <td>{{ formatNumber(row.genes_profiled) }}</td>
                <td>{{ formatNumber(row.cells_or_samples) }}</td>
                <td>{{ formatNumber(row.mapped_genes) }}</td>
                <td>{{ formatPercentValue(row.mapping_rate) }}</td>
                <td><router-link class="btn subtle table-action-btn" :to="case5WorkflowRoute(row.case_code)">Open</router-link></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div id="case5-species-results" class="species-workbench">
          <div class="section-header compact">
            <div><div class="eyebrow">Species-level results</div><h3>HVG-Stoich detailed result tables by model organism</h3></div>
            <router-link class="btn subtle" :to="case5WorkflowRoute()">Open {{ selectedModel8Case5Species }} in HVG workflow</router-link>
          </div>
          <div class="case-tab-row species-tabs" role="tablist" aria-label="Case 5 species detail">
            <button v-for="code in model8SpeciesCodes" :key="`case5-${code}`" type="button" :class="['case-tab', { active: selectedModel8Case5Species === code }]" @click="loadModel8Case5Species(code)">{{ code }}</button>
          </div>
          <section v-if="model8Case5SpeciesLoading" class="case-inline-state"><p class="muted">Loading {{ selectedModel8Case5Species }} HVG-Stoich rows...</p></section>
          <section v-else-if="model8Case5SpeciesError" class="case-inline-state"><p class="muted">{{ model8Case5SpeciesError }}</p></section>
          <template v-else-if="model8Case5Species">
            <div class="case-kpi-grid advanced-kpi-grid">
              <div class="case-kpi"><span>Phase 2 mode</span><strong>{{ model8Case5Species.species_status?.phase2_mode || model8Case5Species.species_status?.phase2_status }}</strong></div>
              <div class="case-kpi"><span>Genes profiled</span><strong>{{ formatNumber(model8Case5Species.kpis?.genes_profiled) }}</strong></div>
              <div class="case-kpi"><span>Mapped genes</span><strong>{{ formatNumber(model8Case5Species.kpis?.mapped_genes) }}</strong></div>
              <div class="case-kpi"><span>Mapping rate</span><strong>{{ formatPercentValue(model8Case5Species.kpis?.mapping_rate) }}</strong></div>
            </div>
            <div class="download-row compact-top">
              <a class="btn subtle" :href="model8Case5Species.downloads?.joined_hvg_stoich">Joined HVG-Stoich</a>
              <a class="btn subtle" :href="model8Case5Species.downloads?.hvg_consensus">HVG consensus</a>
              <a class="btn subtle" :href="model8Case5Species.downloads?.candidate_genes">Candidate genes</a>
              <a class="btn subtle" :href="model8Case5Species.downloads?.enrichment_results">Enrichment</a>
            </div>
            <div class="grid grid-2">
              <div class="table-wrap"><div class="section-header compact"><div><div class="eyebrow">Phase 1</div><h3>{{ selectedModel8Case5Species }} top HVG consensus rows</h3></div></div><table class="table compact-table"><thead><tr><th v-for="col in tableColumns(model8Case5Species.tables?.top_hvg_consensus?.rows)" :key="col">{{ col }}</th></tr></thead><tbody><tr v-for="(row, idx) in compactRows(model8Case5Species.tables?.top_hvg_consensus?.rows)" :key="`case5-hvg-${idx}`"><td v-for="col in tableColumns(model8Case5Species.tables?.top_hvg_consensus?.rows)" :key="col">{{ formatValue(row[col]) }}</td></tr></tbody></table></div>
              <div class="table-wrap"><div class="section-header compact"><div><div class="eyebrow">Model evidence</div><h3>{{ selectedModel8Case5Species }} B0-B3 comparison</h3></div></div><table class="table compact-table"><thead><tr><th v-for="col in tableColumns(model8Case5Species.tables?.model_comparison?.rows)" :key="col">{{ col }}</th></tr></thead><tbody><tr v-for="(row, idx) in compactRows(model8Case5Species.tables?.model_comparison?.rows)" :key="`case5-model-${idx}`"><td v-for="col in tableColumns(model8Case5Species.tables?.model_comparison?.rows)" :key="col">{{ formatValue(row[col]) }}</td></tr></tbody></table></div>
            </div>
            <div class="grid grid-2">
              <div class="table-wrap"><div class="section-header compact"><div><div class="eyebrow">Candidate genes</div><h3>Prioritized genes with stoich components</h3></div></div><table class="table compact-table"><thead><tr><th v-for="col in tableColumns(model8Case5Species.tables?.candidate_genes?.rows)" :key="col">{{ col }}</th></tr></thead><tbody><tr v-for="(row, idx) in compactRows(model8Case5Species.tables?.candidate_genes?.rows)" :key="`case5-candidate-${idx}`"><td v-for="col in tableColumns(model8Case5Species.tables?.candidate_genes?.rows)" :key="col">{{ formatValue(row[col]) }}</td></tr></tbody></table></div>
              <div class="table-wrap"><div class="section-header compact"><div><div class="eyebrow">Joined evidence</div><h3>Expression HVG joined to transcript/protein stoich</h3></div></div><table class="table compact-table"><thead><tr><th v-for="col in tableColumns(model8Case5Species.tables?.joined_hvg_stoich?.rows)" :key="col">{{ col }}</th></tr></thead><tbody><tr v-for="(row, idx) in compactRows(model8Case5Species.tables?.joined_hvg_stoich?.rows)" :key="`case5-joined-${idx}`"><td v-for="col in tableColumns(model8Case5Species.tables?.joined_hvg_stoich?.rows)" :key="col">{{ formatValue(row[col]) }}</td></tr></tbody></table></div>
            </div>
            <div class="grid grid-2">
              <div class="table-wrap"><div class="section-header compact"><div><div class="eyebrow">Feature associations</div><h3>Stoichiometric feature summaries</h3></div></div><table class="table compact-table"><thead><tr><th v-for="col in tableColumns(model8Case5Species.tables?.feature_summary?.rows)" :key="col">{{ col }}</th></tr></thead><tbody><tr v-for="(row, idx) in compactRows(model8Case5Species.tables?.feature_summary?.rows)" :key="`case5-feature-${idx}`"><td v-for="col in tableColumns(model8Case5Species.tables?.feature_summary?.rows)" :key="col">{{ formatValue(row[col]) }}</td></tr></tbody></table></div>
              <div class="table-wrap"><div class="section-header compact"><div><div class="eyebrow">Downstream</div><h3>Enrichment and matched controls</h3></div></div><table class="table compact-table"><thead><tr><th v-for="col in tableColumns([...(model8Case5Species.tables?.enrichment_results?.rows || []), ...(model8Case5Species.tables?.matched_controls?.rows || [])])" :key="col">{{ col }}</th></tr></thead><tbody><tr v-for="(row, idx) in compactRows([...(model8Case5Species.tables?.enrichment_results?.rows || []), ...(model8Case5Species.tables?.matched_controls?.rows || [])])" :key="`case5-downstream-${idx}`"><td v-for="col in tableColumns([...(model8Case5Species.tables?.enrichment_results?.rows || []), ...(model8Case5Species.tables?.matched_controls?.rows || [])])" :key="col">{{ formatValue(row[col]) }}</td></tr></tbody></table></div>
            </div>
          </template>
        </div>
      </ResultBlock>

      <section class="panel">
        <div class="section-header compact">
          <div>
            <div class="eyebrow">Scope and release readiness</div>
            <h3>Implemented, deferred, and missing evidence</h3>
          </div>
        </div>
        <div class="grid grid-2">
          <div>
            <h4>Current data supports</h4>
            <ul class="clean-list compact-list">
              <li v-for="item in payload.support_matrix?.current_data_supports || []" :key="item">{{ item }}</li>
            </ul>
          </div>
          <div>
            <h4>Still missing for full Stage 6</h4>
            <ul class="clean-list compact-list">
              <li v-for="item in payload.support_matrix?.current_data_missing || []" :key="item">{{ item }}</li>
            </ul>
          </div>
        </div>
        <div class="deferred-row">
          <span v-for="item in payload.scope?.deferred_cases || []" :key="item.id" class="badge">{{ item.id }} deferred</span>
        </div>
      </section>
    </template>

    <section v-else class="panel">
      <p class="muted">No Stage 6 case-study payload is available.</p>
    </section>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import EChart from '../components/EChart.vue'
import PhylogenyInsightPanel from '../components/PhylogenyInsightPanel.vue'
import ResultBlock from '../components/result/ResultBlock.vue'
import { getCaseStudies, getCase1TaxonomyAdvanced, getCase2FunctionChain, getCase2IdMapping, getModel8Case1Matrix, getModel8Case1Pairwise, getModel8Case1Sensitivity, getModel8Case1Summary, getModel8Case2Coupling, getModel8Case2NullModels, getModel8Case2Sensitivity, getModel8Case2Summary, getModel8Case3Candidates, getModel8Case3Reports, getModel8Case3Sensitivity, getModel8Case3Summary, getModel8Case4Gold, getModel8Case4Species, getModel8Case4Summary, getModel8Case4Validation, getModel8Case4Workflows, getModel8Case5Species, getModel8PlatformRelease, model8PlatformBundleDownloadUrl, model8PlatformFileDownloadUrl } from '../api/stoichdb'

const payload = ref(null)
const route = useRoute()
const loading = ref(false)
const loadError = ref('')
const case1Tab = ref('basic')
const case1Advanced = ref(null)
const case1AdvancedLoading = ref(false)
const case1AdvancedError = ref('')
const model8Case1 = ref(null)
const model8Case1Matrix = ref(null)
const model8Case1Pairwise = ref(null)
const model8Case1Sensitivity = ref(null)
const model8Case1Loading = ref(false)
const model8Case1Error = ref('')
const case2AdvancedOpen = ref(false)
const case2FunctionOpen = ref(false)
const model8Case2Open = ref(false)
const case2IdMapping = ref(null)
const case2IdLoading = ref(false)
const case2IdError = ref('')
const case2Function = ref(null)
const case2FunctionLoading = ref(false)
const case2FunctionError = ref('')
const model8Case2 = ref(null)
const model8Case2Coupling = ref(null)
const model8Case2NullModels = ref(null)
const model8Case2Sensitivity = ref(null)
const model8Case2Loading = ref(false)
const model8Case2Error = ref('')
const model8Case3Open = ref(false)
const model8Case3 = ref(null)
const model8Case3Candidates = ref(null)
const model8Case3Reports = ref(null)
const model8Case3Sensitivity = ref(null)
const model8Case3Loading = ref(false)
const model8Case3Error = ref('')
const model8Case4Open = ref(false)
const model8Case4 = ref(null)
const model8Case4Gold = ref(null)
const model8Case4Workflows = ref(null)
const model8Case4Validation = ref(null)
const model8Case4Loading = ref(false)
const model8Case4Error = ref('')
const model8SpeciesCodes = ['ECOLI', 'BSUB', 'ORYSA', 'DROME', 'YEAST', 'ARATH', 'DANRE', 'MOUSE']
function normalizeModel8SpeciesCode(value) {
  const code = String(value || '').toUpperCase()
  return model8SpeciesCodes.includes(code) ? code : ''
}
const selectedModel8Case4Species = ref(normalizeModel8SpeciesCode(route.query.case4Species) || 'ECOLI')
const selectedModel8Case5Species = ref(normalizeModel8SpeciesCode(route.query.case5Species) || 'ECOLI')
const model8Case4Species = ref(null)
const model8Case4SpeciesLoading = ref(false)
const model8Case4SpeciesError = ref('')
const model8Case5Species = ref(null)
const model8Case5SpeciesLoading = ref(false)
const model8Case5SpeciesError = ref('')
const model8PlatformRelease = ref(null)
const model8PlatformLoading = ref(false)
const model8PlatformError = ref('')
const advancedRank = ref('phylum')
const advancedFeature = ref('proteome_n_per_aa')

const case1 = computed(() => (payload.value?.cases || []).find((item) => item.id === 'case1'))
const case2 = computed(() => (payload.value?.cases || []).find((item) => item.id === 'case2'))
const case3 = computed(() => (payload.value?.cases || []).find((item) => item.id === 'case3'))
const case4 = computed(() => (payload.value?.cases || []).find((item) => item.id === 'case4'))
const case5 = computed(() => (payload.value?.cases || []).find((item) => item.id === 'case5'))
const model8PlatformManifest = computed(() => model8PlatformRelease.value?.manifest || payload.value?.scope?.model8_platform_release || {})
const model8PlatformClaims = computed(() => model8PlatformRelease.value?.claims || [])

function formatNumber(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return value || ''
  return n.toLocaleString()
}

function compactRows(rows, limit = 12) {
  return (rows || []).slice(0, limit)
}

function tableColumns(rows, limit = 10) {
  return rows?.length ? Object.keys(rows[0]).slice(0, limit) : []
}

function formatValue(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return value ?? ''
  if (Math.abs(n) >= 100) return n.toFixed(1)
  if (Math.abs(n) >= 10) return n.toFixed(2)
  return n.toFixed(4).replace(/0+$/, '').replace(/\.$/, '')
}

function formatPercentValue(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return '-'
  return `${(n * 100).toFixed(2)}%`
}

const MODEL8_CASE4_STANDARD_SEQUENCE_JOBS = {
  ECOLI: 'seq_model8_full_ECOLI_genome_single_sequence',
  YEAST: 'seq_model8_full_YEAST_genome_single_sequence',
}

function case4WorkflowRoute(caseCode = selectedModel8Case4Species.value) {
  const code = normalizeModel8SpeciesCode(caseCode) || selectedModel8Case4Species.value
  if (MODEL8_CASE4_STANDARD_SEQUENCE_JOBS[code]) {
    return `/sequence-analysis/${MODEL8_CASE4_STANDARD_SEQUENCE_JOBS[code]}`
  }
  return `/sequence-analysis/model8-case4-${code}`
}

function case5WorkflowRoute(caseCode = selectedModel8Case5Species.value) {
  const code = normalizeModel8SpeciesCode(caseCode) || selectedModel8Case5Species.value
  return `/hvg/model8-case5-${code}`
}

async function focusCase4SpeciesResults() {
  if (route.hash !== '#case4-species-results' && !route.query.case4Species) return
  model8Case4Open.value = true
  if (!model8Case4.value && !model8Case4Loading.value) {
    await loadModel8Case4()
  }
  await nextTick()
  document.getElementById('case4-species-results')?.scrollIntoView({ block: 'start' })
}

async function focusCase5SpeciesResults() {
  if (route.hash !== '#case5-species-results' && !route.query.case5Species) return
  await nextTick()
  document.getElementById('case5-species-results')?.scrollIntoView({ block: 'start' })
}

function externalIdSummary(ids = {}) {
  const parts = []
  if ((ids.uniprot || []).length) parts.push(`UniProt ${ids.uniprot.length}`)
  if ((ids.ncbi_gene || []).length) parts.push(`NCBI Gene ${ids.ncbi_gene.length}`)
  if ((ids.ncbi_protein || []).length) parts.push(`NCBI Protein ${ids.ncbi_protein.length}`)
  if ((ids.insdc_protein || []).length || (ids.insdc_region || []).length) parts.push('INSDC')
  return parts.join('; ') || '-'
}

function featureDeltaText(rows = []) {
  return rows.map((row) => `${row.label}: ${formatValue(row.z_delta_from_centroid)}`).join('; ')
}

function heatmapData(matrix = []) {
  const points = []
  matrix.forEach((row, y) => {
    ;(row || []).forEach((value, x) => {
      if (value !== null && value !== undefined) points.push([x, y, value])
    })
  })
  return points
}

function percentForRank(rank) {
  const row = (case1Advanced.value?.taxonomy_coverage?.rank_coverage || []).find((item) => item.rank === rank)
  if (!row) return ''
  return `${Math.round((Number(row.coverage) || 0) * 1000) / 10}%`
}

function openModel8Case1() {
  case1Tab.value = 'model8'
  if (!model8Case1.value && !model8Case1Loading.value) loadModel8Case1()
}

async function loadModel8Case1() {
  model8Case1Loading.value = true
  model8Case1Error.value = ''
  try {
    const [summary, matrix, pairwise, sensitivity] = await Promise.all([
      getModel8Case1Summary(),
      getModel8Case1Matrix(),
      getModel8Case1Pairwise(),
      getModel8Case1Sensitivity(),
    ])
    model8Case1.value = summary
    model8Case1Matrix.value = matrix
    model8Case1Pairwise.value = pairwise
    model8Case1Sensitivity.value = sensitivity
  } catch (error) {
    model8Case1Error.value = error?.response?.data?.error || error?.message || 'Failed to load Model-8 Case 1 atlas.'
  } finally {
    model8Case1Loading.value = false
  }
}

function openCase1Advanced() {
  case1Tab.value = 'advanced'
  if (!case1Advanced.value && !case1AdvancedLoading.value) loadCase1Advanced()
}

async function loadCase1Advanced() {
  case1AdvancedLoading.value = true
  case1AdvancedError.value = ''
  try {
    case1Advanced.value = await getCase1TaxonomyAdvanced()
    const firstFeature = advancedFeatureOptions.value[0]?.feature
    if (firstFeature && !advancedFeatureOptions.value.some((item) => item.feature === advancedFeature.value)) {
      advancedFeature.value = firstFeature
    }
  } catch (error) {
    case1AdvancedError.value = error?.response?.data?.error || error?.message || 'Failed to load Case 1 taxonomy analysis.'
  } finally {
    case1AdvancedLoading.value = false
  }
}

function openModel8Case2() {
  model8Case2Open.value = !model8Case2Open.value
  if (model8Case2Open.value && !model8Case2.value && !model8Case2Loading.value) loadModel8Case2()
}

async function loadModel8Case2() {
  model8Case2Loading.value = true
  model8Case2Error.value = ''
  try {
    const [summary, coupling, nullModels, sensitivity] = await Promise.all([
      getModel8Case2Summary(),
      getModel8Case2Coupling(),
      getModel8Case2NullModels(),
      getModel8Case2Sensitivity(),
    ])
    model8Case2.value = summary
    model8Case2Coupling.value = coupling
    model8Case2NullModels.value = nullModels
    model8Case2Sensitivity.value = sensitivity
  } catch (error) {
    model8Case2Error.value = error?.response?.data?.error || error?.message || 'Failed to load Model-8 Case 2 coupling.'
  } finally {
    model8Case2Loading.value = false
  }
}

function openModel8Case3() {
  model8Case3Open.value = !model8Case3Open.value
  if (model8Case3Open.value && !model8Case3.value && !model8Case3Loading.value) loadModel8Case3()
}

async function loadModel8Case3() {
  model8Case3Loading.value = true
  model8Case3Error.value = ''
  try {
    const [summary, candidates, reports, sensitivity] = await Promise.all([
      getModel8Case3Summary(),
      getModel8Case3Candidates(),
      getModel8Case3Reports(),
      getModel8Case3Sensitivity(),
    ])
    model8Case3.value = summary
    model8Case3Candidates.value = candidates
    model8Case3Reports.value = reports
    model8Case3Sensitivity.value = sensitivity
  } catch (error) {
    model8Case3Error.value = error?.response?.data?.error || error?.message || 'Failed to load Model-8 Case 3 evidence chain.'
  } finally {
    model8Case3Loading.value = false
  }
}

function openModel8Case4() {
  model8Case4Open.value = !model8Case4Open.value
  if (model8Case4Open.value && !model8Case4.value && !model8Case4Loading.value) loadModel8Case4()
}

async function loadModel8Case4() {
  model8Case4Loading.value = true
  model8Case4Error.value = ''
  try {
    const [summary, gold, workflows, validation] = await Promise.all([
      getModel8Case4Summary(),
      getModel8Case4Gold(),
      getModel8Case4Workflows(),
      getModel8Case4Validation(),
    ])
    model8Case4.value = summary
    model8Case4Gold.value = gold
    model8Case4Workflows.value = workflows
    model8Case4Validation.value = validation
    if (!model8Case4Species.value) loadModel8Case4Species(selectedModel8Case4Species.value)
  } catch (error) {
    model8Case4Error.value = error?.response?.data?.error || error?.message || 'Failed to load Model-8 Case 4 upload gold standard.'
  } finally {
    model8Case4Loading.value = false
  }
}

async function loadModel8Case4Species(caseCode = selectedModel8Case4Species.value) {
  selectedModel8Case4Species.value = caseCode
  model8Case4SpeciesLoading.value = true
  model8Case4SpeciesError.value = ''
  try {
    model8Case4Species.value = await getModel8Case4Species(caseCode)
  } catch (error) {
    model8Case4SpeciesError.value = error?.response?.data?.error || error?.message || `Failed to load Case 4 species detail for ${caseCode}.`
  } finally {
    model8Case4SpeciesLoading.value = false
  }
}

async function loadModel8Case5Species(caseCode = selectedModel8Case5Species.value) {
  selectedModel8Case5Species.value = caseCode
  model8Case5SpeciesLoading.value = true
  model8Case5SpeciesError.value = ''
  try {
    model8Case5Species.value = await getModel8Case5Species(caseCode)
  } catch (error) {
    model8Case5SpeciesError.value = error?.response?.data?.error || error?.message || `Failed to load Case 5 species detail for ${caseCode}.`
  } finally {
    model8Case5SpeciesLoading.value = false
  }
}

function openCase2Advanced() {
  case2AdvancedOpen.value = !case2AdvancedOpen.value
  if (case2AdvancedOpen.value && !case2IdMapping.value && !case2IdLoading.value) loadCase2IdMapping()
}

function openCase2Function() {
  case2FunctionOpen.value = !case2FunctionOpen.value
  if (case2FunctionOpen.value && !case2Function.value && !case2FunctionLoading.value) loadCase2Function()
}

async function loadCase2IdMapping() {
  case2IdLoading.value = true
  case2IdError.value = ''
  try {
    case2IdMapping.value = await getCase2IdMapping()
  } catch (error) {
    case2IdError.value = error?.response?.data?.error || error?.message || 'Failed to load Case 2 ID mapping payload.'
  } finally {
    case2IdLoading.value = false
  }
}

async function loadCase2Function() {
  case2FunctionLoading.value = true
  case2FunctionError.value = ''
  try {
    case2Function.value = await getCase2FunctionChain()
  } catch (error) {
    case2FunctionError.value = error?.response?.data?.error || error?.message || 'Failed to load Case 2 functional chain.'
  } finally {
    case2FunctionLoading.value = false
  }
}

const advancedFeatureOptions = computed(() => {
  const tests = case1Advanced.value?.feature_group_tests || []
  const seen = new Map()
  tests.forEach((row) => {
    if (!seen.has(row.feature)) seen.set(row.feature, { feature: row.feature, label: row.feature_label || row.feature })
  })
  return Array.from(seen.values())
})

const selectedFeatureLabel = computed(() => advancedFeatureOptions.value.find((item) => item.feature === advancedFeature.value)?.label || advancedFeature.value)

const filteredFeatureTests = computed(() =>
  (case1Advanced.value?.feature_group_tests || []).filter((row) => row.rank_level === advancedRank.value)
)

const filteredGroupSummary = computed(() =>
  (case1Advanced.value?.rank_group_summary || [])
    .filter((row) => row.rank_level === advancedRank.value && row.feature === advancedFeature.value)
    .slice()
    .sort((a, b) => Math.abs(Number(b.effect_size) || 0) - Math.abs(Number(a.effect_size) || 0))
)

const filteredSignatures = computed(() =>
  (case1Advanced.value?.clade_signatures || [])
    .filter((row) => row.rank_level === advancedRank.value)
    .slice()
    .sort((a, b) => Math.abs(Number(b.signature_score) || 0) - Math.abs(Number(a.signature_score) || 0))
)

const filteredRepresentatives = computed(() =>
  (case1Advanced.value?.representative_species_by_taxon || [])
    .filter((row) => row.rank_level === advancedRank.value)
)

const filteredOutliers = computed(() =>
  (case1Advanced.value?.outlier_species_by_taxon || [])
    .filter((row) => row.rank_level === advancedRank.value)
)

const model8PredefinedEffects = computed(() =>
  (model8Case1Pairwise.value?.effects || []).filter((row) => row.predefined_contrast)
)

const model8Case1Heatmap = computed(() => {
  const block = model8Case1Matrix.value?.zscore_matrix || {}
  return {
    tooltip: { position: 'top' },
    grid: { left: 170, right: 36, top: 34, bottom: 105 },
    xAxis: { type: 'category', data: block.x_labels || [], axisLabel: { rotate: 35 } },
    yAxis: { type: 'category', data: block.y_labels || [] },
    visualMap: { min: -2.5, max: 2.5, calculable: true, orient: 'horizontal', left: 'center', bottom: 8 },
    series: [{ type: 'heatmap', data: heatmapData(block.values || []), emphasis: { itemStyle: { borderColor: '#1f5d9a', borderWidth: 1 } } }],
  }
})

const model8Case1PcaChart = computed(() => {
  const pca = model8Case1Matrix.value?.pca || {}
  const points = pca.points || []
  return {
    tooltip: { trigger: 'item', formatter: (params) => `${params.data?.raw?.scientific_name || ''}<br/>${params.data?.raw?.division || ''}` },
    grid: { left: 70, right: 30, top: 30, bottom: 58 },
    xAxis: { type: 'value', name: `PC1 ${formatValue((pca.explained_variance_ratio || [])[0] * 100)}%` },
    yAxis: { type: 'value', name: `PC2 ${formatValue((pca.explained_variance_ratio || [])[1] * 100)}%` },
    series: [{ type: 'scatter', symbolSize: 11, data: points.map((row) => ({ value: [row.pc1, row.pc2], raw: row })) }],
  }
})

const case1Heatmap = computed(() => {
  const block = case1.value?.heatmap || {}
  return {
    tooltip: { position: 'top' },
    grid: { left: 190, right: 40, top: 40, bottom: 100 },
    xAxis: { type: 'category', data: block.x_labels || [], axisLabel: { rotate: 35 } },
    yAxis: { type: 'category', data: block.y_labels || [] },
    visualMap: { min: -2.5, max: 2.5, calculable: true, orient: 'horizontal', left: 'center', bottom: 10 },
    series: [{ type: 'heatmap', data: heatmapData(block.values || []), emphasis: { itemStyle: { borderColor: '#1f5d9a', borderWidth: 1 } } }],
  }
})

const case1RankCoverageChart = computed(() => {
  const rows = case1Advanced.value?.taxonomy_coverage?.rank_coverage || []
  return {
    tooltip: { trigger: 'axis' },
    legend: { top: 0 },
    grid: { left: 100, right: 24, top: 42, bottom: 40 },
    xAxis: { type: 'value', max: 1 },
    yAxis: { type: 'category', data: rows.map((row) => row.rank).reverse() },
    series: [
      { name: 'present', type: 'bar', stack: 'coverage', data: rows.map((row) => row.coverage || 0).reverse(), itemStyle: { color: '#2370cf' } },
      { name: 'missing', type: 'bar', stack: 'coverage', data: rows.map((row) => 1 - (row.coverage || 0)).reverse(), itemStyle: { color: '#d7e4f2' } },
    ],
  }
})

const case1AdvancedHeatmap = computed(() => {
  const block = case1Advanced.value?.taxonomy_annotated_heatmap || {}
  return {
    tooltip: {
      formatter: (params) => {
        const annotation = (block.row_annotations || [])[params.data?.[1]] || {}
        const label = (block.x_labels || [])[params.data?.[0]] || ''
        return `${annotation.display_name || ''}<br/>${label}: ${formatValue(params.data?.[2])}<br/>${advancedRank.value}: ${annotation[advancedRank.value] || 'Missing'}`
      },
    },
    grid: { left: 190, right: 38, top: 36, bottom: 96 },
    xAxis: { type: 'category', data: block.x_labels || [], axisLabel: { rotate: 35 } },
    yAxis: { type: 'category', data: block.y_labels || [], axisLabel: { fontSize: 10 } },
    visualMap: { min: -2.5, max: 2.5, calculable: true, orient: 'horizontal', left: 'center', bottom: 8 },
    series: [{ type: 'heatmap', data: heatmapData(block.values || []), emphasis: { itemStyle: { borderColor: '#1f5d9a', borderWidth: 1 } } }],
  }
})

const case1GroupStatsChart = computed(() => {
  const rows = filteredGroupSummary.value.slice(0, 18).reverse()
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 142, right: 28, top: 28, bottom: 46 },
    xAxis: { type: 'value', name: 'Median delta' },
    yAxis: { type: 'category', data: rows.map((row) => row.taxon_name) },
    series: [{
      type: 'bar',
      data: rows.map((row) => row.delta_from_global || 0),
      itemStyle: { color: (params) => (Number(params.value) >= 0 ? '#2370cf' : '#8a6fbd') },
    }],
  }
})

const case1PcaChart = computed(() => {
  const pca = case1Advanced.value?.dimension_reduction?.pca || {}
  const points = pca.points || []
  const phyla = [...new Set(points.map((row) => row.phylum || 'Missing'))].slice(0, 18)
  return {
    tooltip: {
      trigger: 'item',
      formatter: (params) => {
        const row = params.data?.raw || {}
        return `${row.display_name}<br/>phylum: ${row.phylum}<br/>class: ${row.class}<br/>PC1: ${formatValue(row.pc1)}<br/>PC2: ${formatValue(row.pc2)}`
      },
    },
    legend: { type: 'scroll', top: 0 },
    grid: { left: 70, right: 30, top: 48, bottom: 58 },
    xAxis: { type: 'value', name: `PC1 ${formatValue((pca.explained_variance_ratio || [])[0] * 100)}%` },
    yAxis: { type: 'value', name: `PC2 ${formatValue((pca.explained_variance_ratio || [])[1] * 100)}%` },
    series: phyla.map((phylum) => ({
      name: phylum,
      type: 'scatter',
      symbolSize: 7,
      data: points.filter((row) => row.phylum === phylum).map((row) => ({ value: [row.pc1, row.pc2], raw: row })),
    })),
  }
})

const case1PcaLoadingChart = computed(() => {
  const rows = (case1Advanced.value?.dimension_reduction?.pca?.loadings || []).slice()
  return {
    tooltip: { trigger: 'axis' },
    legend: { top: 0 },
    grid: { left: 138, right: 28, top: 42, bottom: 40 },
    xAxis: { type: 'value' },
    yAxis: { type: 'category', data: rows.map((row) => row.label).reverse() },
    series: [
      { name: 'PC1', type: 'bar', data: rows.map((row) => row.pc1).reverse(), itemStyle: { color: '#2370cf' } },
      { name: 'PC2', type: 'bar', data: rows.map((row) => row.pc2).reverse(), itemStyle: { color: '#2a9d8f' } },
    ],
  }
})

const case1SignatureHeatmap = computed(() => {
  const rows = filteredSignatures.value.slice(0, 90)
  const taxa = [...new Set(rows.map((row) => row.taxon_name))].slice(0, 14)
  const features = [...new Set(rows.map((row) => row.feature_label))]
  const data = []
  taxa.forEach((taxon, y) => {
    features.forEach((feature, x) => {
      const found = rows.find((row) => row.taxon_name === taxon && row.feature_label === feature)
      if (found) data.push([x, y, found.signature_score])
    })
  })
  return {
    tooltip: { formatter: (params) => `${taxa[params.data?.[1]]}<br/>${features[params.data?.[0]]}: ${formatValue(params.data?.[2])}` },
    grid: { left: 126, right: 24, top: 30, bottom: 96 },
    xAxis: { type: 'category', data: features, axisLabel: { rotate: 35 } },
    yAxis: { type: 'category', data: taxa },
    visualMap: { min: -2, max: 2, calculable: true, orient: 'horizontal', left: 'center', bottom: 4 },
    series: [{ type: 'heatmap', data }],
  }
})

const case1DistanceChart = computed(() => {
  const rows = case1Advanced.value?.distance_taxonomy_alignment?.sampled_pairs || []
  return {
    tooltip: { trigger: 'item' },
    grid: { left: 76, right: 28, top: 28, bottom: 58 },
    xAxis: { type: 'value', name: 'Taxonomy-proxy distance' },
    yAxis: { type: 'value', name: 'Stoich distance' },
    series: [{
      type: 'scatter',
      symbolSize: 5,
      data: rows.map((row) => ({
        value: [row.taxonomy_proxy_distance, row.stoichiometric_distance],
        itemStyle: { color: row.same_phylum ? '#2370cf' : '#9b6fc5' },
      })),
    }],
  }
})

const case1DistanceSummaryChart = computed(() => {
  const alignment = case1Advanced.value?.distance_taxonomy_alignment || {}
  const same = alignment.same_phylum_box || {}
  const different = alignment.different_phylum_box || {}
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 90, right: 24, top: 28, bottom: 40 },
    xAxis: { type: 'value', name: 'Median distance' },
    yAxis: { type: 'category', data: ['same phylum', 'different phylum'] },
    series: [{ type: 'bar', data: [same.median || 0, different.median || 0], itemStyle: { color: '#2370cf' } }],
  }
})

const case1VariabilityChart = computed(() => {
  const rows = (case1.value?.feature_variability || []).slice(0, 8)
  return {
    tooltip: {},
    grid: { left: 150, right: 30, top: 30, bottom: 40 },
    xAxis: { type: 'value', name: 'Range' },
    yAxis: { type: 'category', data: rows.map((row) => row.label) },
    series: [{ type: 'bar', data: rows.map((row) => row.range || 0), itemStyle: { color: '#2a7abf' } }],
  }
})

const model8Case2TopTransformations = computed(() => model8Case2Coupling.value?.top_transformations || [])

const model8Case3ReportsIndex = computed(() => model8Case3Reports.value?.report_index || [])

function model8Case3SpeciesId(caseCode) {
  return (model8Case3.value?.filters?.species || []).find((row) => row.case_code === caseCode)?.species_id || caseCode
}

const model8Case2Heatmap = computed(() => {
  const block = model8Case2Coupling.value?.heatmap || {}
  return {
    tooltip: { position: 'top' },
    grid: { left: 90, right: 30, top: 34, bottom: 120 },
    xAxis: { type: 'category', data: block.x_labels || [], axisLabel: { rotate: 35 } },
    yAxis: { type: 'category', data: block.y_labels || [] },
    visualMap: { min: -1, max: 1, calculable: true, orient: 'horizontal', left: 'center', bottom: 8 },
    series: [{ type: 'heatmap', data: heatmapData(block.values || []), emphasis: { itemStyle: { borderColor: '#1f5d9a', borderWidth: 1 } } }],
  }
})

const model8Case3PriorityChart = computed(() => {
  const rows = (model8Case3Candidates.value?.selected_entities || []).filter((row) => row.candidate_direction !== 'matched_control')
  return {
    tooltip: {
      trigger: 'item',
      formatter: (params) => {
        const row = params.data?.raw || {}
        return `${row.case_code}<br/>${row.candidate_direction}<br/>${row.pair_id}<br/>residual z: ${formatValue(row.residual_z)}<br/>priority: ${formatValue(row.candidate_priority)}`
      },
    },
    legend: { top: 0 },
    grid: { left: 82, right: 28, top: 44, bottom: 60 },
    xAxis: { type: 'value', name: '|residual z|' },
    yAxis: { type: 'value', name: 'observed-null' },
    series: ['positive_residual', 'negative_residual'].map((direction) => ({
      name: direction,
      type: 'scatter',
      symbolSize: 11,
      data: rows
        .filter((row) => row.candidate_direction === direction)
        .map((row) => ({
          value: [Math.abs(Number(row.residual_z) || 0), Math.abs(Number(row.excess ?? row.observed_minus_null) || 0)],
          raw: row,
        })),
    })),
  }
})

const model8Case2NullChart = computed(() => {
  const rows = (model8Case2NullModels.value?.results || []).filter((row) => row.status !== 'not_applicable_current_features').slice(0, 36)
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 150, right: 28, top: 30, bottom: 84 },
    xAxis: { type: 'category', data: rows.map((row) => `${row.case_code}:${row.pair_id}`), axisLabel: { rotate: 35 } },
    yAxis: { type: 'value', name: 'Observed-null' },
    series: [{ type: 'bar', data: rows.map((row) => row.excess || 0), itemStyle: { color: '#2370cf' } }],
  }
})

const case2CorrelationChart = computed(() => {
  const matrix = case2.value?.correlation_matrix || {}
  const labels = Object.keys(matrix)
  const data = []
  labels.forEach((rowLabel, y) => {
    labels.forEach((colLabel, x) => data.push([x, y, matrix[rowLabel]?.[colLabel] ?? null]))
  })
  return {
    tooltip: {},
    grid: { left: 130, right: 30, top: 40, bottom: 80 },
    xAxis: { type: 'category', data: labels, axisLabel: { rotate: 25 } },
    yAxis: { type: 'category', data: labels },
    visualMap: { min: -1, max: 1, calculable: true, orient: 'horizontal', left: 'center', bottom: 4 },
    series: [{ type: 'heatmap', data }],
  }
})

const case2ScatterChart = computed(() => {
  const rows = case2.value?.cross_points || []
  return {
    __exportName: 'case2_gc_vs_proteome_n_scatter',
    __semantic: {
      minPoints: 3,
      totalCount: rows.length,
      displayedCount: rows.filter((row) => Number.isFinite(Number(row.exon_gc_percent)) && Number.isFinite(Number(row.proteome_n_per_aa))).length,
      method: 'paired real gene/transcript/protein points; standardized shift fields retained in export rows',
      aggregation: 'matched entity point',
    },
    __dataRows: rows.map((row) => ({
      gene_id: row.gene_id,
      gene_name: row.gene_name,
      exon_gc_percent: row.exon_gc_percent,
      proteome_n_per_aa: row.proteome_n_per_aa,
      dna_to_rna_n_shift_std: row.dna_to_rna_n_shift_std,
      rna_to_protein_n_shift_std: row.rna_to_protein_n_shift_std,
      rna_to_protein_n_shift_legacy_proxy: row.rna_to_protein_n_shift_legacy_proxy,
    })),
    tooltip: { trigger: 'item' },
    grid: { left: 80, right: 30, top: 35, bottom: 70 },
    xAxis: { type: 'value', name: 'Exon GC percent' },
    yAxis: { type: 'value', name: 'Proteome N/aa' },
    series: [{
      type: 'scatter',
      data: rows.map((row) => [row.exon_gc_percent, row.proteome_n_per_aa, row.gene_name]),
      symbolSize: 7,
      itemStyle: { color: '#17866d' },
    }],
  }
})

const case2IdCoverageChart = computed(() => {
  const summary = case2IdMapping.value?.mapping_summary || {}
  const rows = [
    ['Complete chain', summary.complete_chain_rate || 0],
    ['High confidence', summary.high_confidence_rate || 0],
    ['External high', summary.external_high_confidence_rate || 0],
    ['UniProt', summary.uniprot_coverage || 0],
    ['NCBI/INSDC', summary.ncbi_or_insdc_coverage || 0],
    ['Conflict', summary.conflict_rate || 0],
  ]
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 130, right: 24, top: 28, bottom: 42 },
    xAxis: { type: 'value', min: 0, max: 1 },
    yAxis: { type: 'category', data: rows.map((row) => row[0]).reverse() },
    series: [{ type: 'bar', data: rows.map((row) => row[1]).reverse(), itemStyle: { color: '#2370cf' } }],
  }
})

const case3PercentileChart = computed(() => {
  const rows = case3.value?.feature_profile || []
  return {
    tooltip: {},
    grid: { left: 150, right: 30, top: 30, bottom: 50 },
    xAxis: { type: 'value', name: 'Same-species percentile', min: 0, max: 100 },
    yAxis: { type: 'category', data: rows.map((row) => row.label) },
    series: [{ type: 'bar', data: rows.map((row) => row.species_percentile || 0), itemStyle: { color: '#8167b5' } }],
  }
})

async function loadModel8PlatformRelease() {
  model8PlatformLoading.value = true
  model8PlatformError.value = ''
  try {
    model8PlatformRelease.value = await getModel8PlatformRelease()
  } catch (error) {
    model8PlatformError.value = error?.response?.data?.error || error?.message || 'Failed to load Model-8 platform release.'
  } finally {
    model8PlatformLoading.value = false
  }
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const [casePayload, platformPayload] = await Promise.all([
      getCaseStudies(),
      getModel8PlatformRelease().catch((error) => {
        model8PlatformError.value = error?.response?.data?.error || error?.message || 'Failed to load Model-8 platform release.'
        return null
      }),
    ])
    payload.value = casePayload
    model8PlatformRelease.value = platformPayload
    await Promise.all([
      loadModel8Case4Species(selectedModel8Case4Species.value),
      loadModel8Case5Species(selectedModel8Case5Species.value),
    ])
  } catch (error) {
    loadError.value = error?.response?.data?.error || error?.message || 'Failed to load Stage 6 case-study payload.'
  } finally {
    loading.value = false
  }
}

watch(
  () => [route.query.case4Species, route.query.case5Species, route.hash],
  async ([case4Species, case5Species]) => {
    const case4Code = normalizeModel8SpeciesCode(case4Species)
    const case5Code = normalizeModel8SpeciesCode(case5Species)
    if (case4Code && case4Code !== selectedModel8Case4Species.value) {
      await loadModel8Case4Species(case4Code)
    }
    if (case5Code && case5Code !== selectedModel8Case5Species.value) {
      await loadModel8Case5Species(case5Code)
    }
    await Promise.all([focusCase4SpeciesResults(), focusCase5SpeciesResults()])
  },
)

onMounted(async () => {
  await load()
  await Promise.all([focusCase4SpeciesResults(), focusCase5SpeciesResults()])
})
</script>

<style scoped>
.case-kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.case-kpi {
  border: 1px solid rgba(42, 89, 140, 0.14);
  border-radius: 8px;
  padding: 12px;
  background: #f8fbff;
}

.case-kpi span {
  display: block;
  color: #66788a;
  font-size: 0.78rem;
  margin-bottom: 4px;
}

.case-kpi strong {
  color: #163d63;
  font-size: 1rem;
  overflow-wrap: anywhere;
}

.danger-badge {
  background: #fff1f0;
  border-color: #e59b93;
  color: #9d2f26;
}

.case-selected-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.case-selected-row strong {
  display: block;
  color: #163d63;
  font-size: 1.05rem;
  margin: 4px 0;
  overflow-wrap: anywhere;
}

.case-tab-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 14px;
  border-bottom: 1px solid rgba(42, 89, 140, 0.14);
}

.case-tab {
  border: 0;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: #496b89;
  padding: 9px 12px;
  font-weight: 700;
}

.case-tab:hover {
  color: #163d63;
}

.case-tab.active {
  color: #1f5d9a;
  border-bottom-color: #1f5d9a;
}

.case-inline-state {
  border: 1px solid rgba(42, 89, 140, 0.14);
  border-radius: 8px;
  padding: 14px;
  background: #f8fbff;
}

.caution-block {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  border: 1px solid rgba(168, 111, 42, 0.28);
  border-radius: 8px;
  background: #fff8ed;
  color: #5d3c12;
  padding: 12px 14px;
}

.caution-block strong {
  flex: 0 0 auto;
  color: #4c320e;
}

.advanced-kpi-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.advanced-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: end;
}

.advanced-toolbar label {
  display: flex;
  flex-direction: column;
  gap: 5px;
  color: #5d7287;
  font-size: 0.82rem;
  font-weight: 700;
}

.select-inline {
  min-width: 180px;
}

.compact-top {
  margin-top: 12px;
  max-height: 270px;
  overflow: auto;
}

.download-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 12px;
}

.species-workbench {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-top: 16px;
}

.species-tabs {
  padding-bottom: 4px;
}

.compact-top {
  margin-top: 10px;
}

.deferred-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 14px;
}

@media (max-width: 900px) {
  .case-kpi-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .case-selected-row {
    flex-direction: column;
  }

  .advanced-kpi-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .caution-block {
    flex-direction: column;
  }
}
</style>
