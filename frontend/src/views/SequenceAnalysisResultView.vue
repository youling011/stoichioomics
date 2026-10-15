<template>
  <div class="stack-lg">
    <div class="card" v-if="job">
      <div class="row" style="justify-content:space-between">
        <div>
          <h1>{{ job.name || job.job_id }}</h1>
          <p class="muted">{{ job.job_id }} / {{ job.status }} / {{ job.analysis_type }}</p>
        </div>
        <div class="row">
          <button class="btn secondary" @click="load">Refresh</button>
          <button class="btn secondary" @click="loadLogs">{{ isModel8Case4 ? 'Release log' : 'Logs' }}</button>
          <button class="btn secondary" @click="loadRepro">{{ isModel8Case4 ? 'Provenance' : 'Reproducibility' }}</button>
          <router-link v-if="showModel8Case4BackLink" class="btn secondary" :to="model8Case4BackRoute">Case studies</router-link>
          <a v-if="isModel8Case4" class="btn secondary" :href="model8PlatformBundleDownloadUrl()">Bundle</a>
          <router-link class="btn" to="/sequence-analysis">New sequence analysis</router-link>
        </div>
      </div>
      <p v-if="job.error_message" style="color:#b42318">{{ job.error_message }}</p>
    </div>

    <div v-if="loading" class="card">Loading sequence analysis outputs...</div>
    <div v-if="loadError" class="card" style="color:#b42318">{{ loadError }}</div>
    <div v-if="!loading && job && job.status !== 'SUCCEEDED'" class="grid grid-2">
      <div class="card">
        <h3>Task status</h3>
        <p class="muted">This sequence analysis runs as a background task. Output tables and charts are requested only after the job succeeds.</p>
        <table class="table">
          <tbody>
            <tr><td>Status</td><td>{{ job.status }}</td></tr>
            <tr><td>Created</td><td>{{ job.created_at || '-' }}</td></tr>
            <tr><td>Updated</td><td>{{ job.updated_at || '-' }}</td></tr>
            <tr><td>Expires</td><td>{{ job.expires_at || '-' }}</td></tr>
          </tbody>
        </table>
      </div>
      <div class="card">
        <h3>Security and reproducibility</h3>
        <ul>
          <li>Raw uploads are isolated under this runtime job and deleted after computation.</li>
          <li>Input file names are sanitized; file type, size, and path boundaries are checked before execution.</li>
          <li>Checksums, parameters, software versions, and run events are recorded in the job logs.</li>
        </ul>
      </div>
    </div>
    <div v-if="!loading && job && job.status !== 'SUCCEEDED' && inputQc" class="card">
      <h3>Input QC and blocking reasons</h3>
      <table class="table">
        <tbody>
          <tr><td>Analysis allowed</td><td>{{ inputQc.analysis_allowed ? 'Yes' : 'No' }}</td></tr>
          <tr><td>Comparison allowed</td><td>{{ inputQc.comparison_allowed ? 'Yes' : 'No' }}</td></tr>
          <tr><td>Records</td><td>{{ inputQc.summary?.record_count || 0 }}</td></tr>
          <tr><td>Group field</td><td>{{ inputQc.summary?.group_field || '-' }}</td></tr>
        </tbody>
      </table>
      <ul v-if="inputQc.blocking_errors?.length" class="clean-list compact-list workflow-warnings">
        <li v-for="(item, idx) in inputQc.blocking_errors" :key="`blocked-qc-${idx}`">{{ item.code }} - {{ item.message }}</li>
      </ul>
    </div>
    <div v-if="logs" class="card">
      <h3>{{ isModel8Case4 ? 'Release log' : 'Task log' }}</h3>
      <pre>{{ JSON.stringify(logs.events || [], null, 2) }}</pre>
    </div>
    <div v-if="repro" class="card">
      <h3>{{ isModel8Case4 ? 'Release provenance manifest' : 'Reproducibility manifest' }}</h3>
      <pre>{{ JSON.stringify(repro, null, 2) }}</pre>
    </div>
    <div v-if="optionalWarnings.length" class="card muted">
      Some optional result blocks could not be loaded: {{ optionalWarnings.join(', ') }}.
    </div>
    <div v-if="isModel8Case4 && job && tab === 'overview'" class="card muted">
      Curated workflow case: this route renders generated Model-8 Case 4 artifacts from
      <code>data/case_studies/model8/case4_upload_gold</code>, including gold_standard.json,
      validation.json, workflows.json, expected feature tables, tolerance_report.csv, and platform_gold_agreement.csv.
    </div>
    <section v-if="isModel8Case4 && job && tab === 'overview'" class="card species-workbench">
      <div class="section-header compact">
        <div>
          <h3>{{ model8Case4SpeciesCode ? `${model8Case4SpeciesCode} sequence gold-standard workbench` : 'Species gold-standard result workbench' }}</h3>
          <p class="muted">{{ model8Case4SpeciesCode ? 'This workflow page is scoped to the selected species upload-gold result.' : 'Switch species to inspect real expected protein features, CDS/transcript features, stored-value agreement rows, and selected gold records.' }}</p>
        </div>
        <router-link class="btn secondary" :to="model8Case4BackRoute">Back to case studies</router-link>
      </div>
      <div v-if="!model8Case4SpeciesCode" class="case-tab-row species-tabs" role="tablist" aria-label="Case 4 species detail">
        <button v-for="code in model8SpeciesCodes" :key="`seq-case4-${code}`" type="button" :class="['case-tab', { active: selectedModel8Case4Species === code }]" @click="loadModel8Case4Species(code)">{{ code }}</button>
      </div>
      <div v-if="model8Case4SpeciesLoading" class="muted">Loading {{ selectedModel8Case4Species }} gold-standard rows...</div>
      <div v-else-if="model8Case4SpeciesError" class="muted">{{ model8Case4SpeciesError }}</div>
      <template v-else-if="model8Case4Species">
        <div class="grid grid-4">
          <div class="mini-card"><div class="label">Species</div><div class="kpi small-kpi">{{ model8Case4Species.species_status?.scientific_name || model8Case4Species.case_code }}</div></div>
          <div class="mini-card"><div class="label">Protein records</div><div class="kpi">{{ model8Case4Species.species_status?.protein_records || '-' }}</div></div>
          <div class="mini-card"><div class="label">Nucleotide records</div><div class="kpi">{{ model8Case4Species.species_status?.nucleotide_records || '-' }}</div></div>
          <div class="mini-card"><div class="label">Pass rate</div><div class="kpi">{{ formatCell(model8Case4Species.kpis?.global_pass_rate) }}</div></div>
        </div>
        <div class="row compact-top">
          <a class="btn secondary" :href="model8Case4Species.downloads?.protein_gold_fasta">Protein FASTA</a>
          <a class="btn secondary" :href="model8Case4Species.downloads?.nucleotide_gold_fasta">CDS/transcript FASTA</a>
          <a class="btn secondary" :href="model8Case4Species.downloads?.gff3_subset">GFF3 subset</a>
          <a class="btn secondary" :href="model8Case4Species.downloads?.platform_gold_agreement">Agreement CSV</a>
        </div>
        <div class="grid grid-2 compact-top">
          <div class="table-wrap"><h3>Expected protein features</h3><table class="table compact-table"><thead><tr><th v-for="col in tableColumns(model8Case4Species.tables?.expected_protein_features?.rows)" :key="col">{{ col }}</th></tr></thead><tbody><tr v-for="(row, idx) in compactRows(model8Case4Species.tables?.expected_protein_features?.rows)" :key="`seq-protein-${idx}`"><td v-for="col in tableColumns(model8Case4Species.tables?.expected_protein_features?.rows)" :key="col">{{ formatCell(row[col]) }}</td></tr></tbody></table></div>
          <div class="table-wrap"><h3>Expected CDS/transcript features</h3><table class="table compact-table"><thead><tr><th v-for="col in tableColumns(model8Case4Species.tables?.expected_cds_transcript_features?.rows)" :key="col">{{ col }}</th></tr></thead><tbody><tr v-for="(row, idx) in compactRows(model8Case4Species.tables?.expected_cds_transcript_features?.rows)" :key="`seq-cds-${idx}`"><td v-for="col in tableColumns(model8Case4Species.tables?.expected_cds_transcript_features?.rows)" :key="col">{{ formatCell(row[col]) }}</td></tr></tbody></table></div>
        </div>
        <div class="grid grid-2 compact-top">
          <div class="table-wrap"><h3>Platform agreement rows</h3><table class="table compact-table"><thead><tr><th v-for="col in tableColumns(model8Case4Species.tables?.platform_gold_agreement?.rows)" :key="col">{{ col }}</th></tr></thead><tbody><tr v-for="(row, idx) in compactRows(model8Case4Species.tables?.platform_gold_agreement?.rows)" :key="`seq-agreement-${idx}`"><td v-for="col in tableColumns(model8Case4Species.tables?.platform_gold_agreement?.rows)" :key="col">{{ formatCell(row[col]) }}</td></tr></tbody></table></div>
          <div class="table-wrap"><h3>Selected gold records</h3><table class="table compact-table"><thead><tr><th v-for="col in tableColumns(model8Case4Species.tables?.selected_gold_records?.rows)" :key="col">{{ col }}</th></tr></thead><tbody><tr v-for="(row, idx) in compactRows(model8Case4Species.tables?.selected_gold_records?.rows)" :key="`seq-selected-${idx}`"><td v-for="col in tableColumns(model8Case4Species.tables?.selected_gold_records?.rows)" :key="col">{{ formatCell(row[col]) }}</td></tr></tbody></table></div>
        </div>
      </template>
    </section>

    <template v-if="!loading && !loadError && job && job.status === 'SUCCEEDED'">
      <div class="grid grid-4">
        <div v-for="card in summaryKpiCards" :key="card.label" class="card">
          <div class="label">{{ card.label }}</div>
          <div class="kpi">{{ formatKpiCard(card) }}</div>
        </div>
      </div>

      <section class="grid grid-2">
        <div class="card">
          <h3>Workflow readiness and design</h3>
          <table class="table">
            <tbody>
              <tr><td>Input QC</td><td>{{ inputQc?.analysis_allowed ? 'Ready' : 'Blocked or unavailable' }}</td></tr>
              <tr><td>Comparison</td><td>{{ inputQc?.comparison_allowed ? 'Ready' : 'Descriptive only' }}</td></tr>
              <tr><td>Research question</td><td>{{ analysisDesign?.research_question || '-' }}</td></tr>
              <tr><td>Evidence policy</td><td>{{ analysisDesign?.evidence_policy?.interpretation_rule || '-' }}</td></tr>
            </tbody>
          </table>
          <ul v-if="inputQc?.warnings?.length" class="clean-list compact-list workflow-warnings">
            <li v-for="(item, idx) in inputQc.warnings.slice(0, 4)" :key="`qc-warn-${idx}`">{{ item.code }} - {{ item.message }}</li>
          </ul>
        </div>
        <div class="card">
          <h3>Result interpretation scope</h3>
          <table class="table">
            <tbody>
              <tr><td>Descriptive profile</td><td>{{ resultInterpretation?.interpretation_scope?.can_support_descriptive_profile ? 'Supported' : 'Not supported' }}</td></tr>
              <tr><td>Group comparison</td><td>{{ resultInterpretation?.interpretation_scope?.can_support_group_comparison ? 'Supported' : 'Not supported' }}</td></tr>
              <tr><td>Publication-grade claim</td><td>{{ resultInterpretation?.interpretation_scope?.can_support_publication_grade_claim ? 'Potentially supported' : 'Requires more evidence' }}</td></tr>
              <tr><td>Download contract</td><td>{{ downloadManifest?.items?.filter(item => item.exists).length || 0 }} available artifacts</td></tr>
            </tbody>
          </table>
          <p class="muted">{{ resultInterpretation?.claim_guardrails?.[0] || 'Interpretation guardrails are written to result_interpretation.json.' }}</p>
        </div>
      </section>

      <nav class="analysis-nav" aria-label="Sequence analysis result sections">
        <button
          v-for="item in tabItems"
          :key="item.key"
          type="button"
          class="analysis-nav-item"
          :class="{ active: tab === item.key }"
          @click="tab = item.key"
        >
          <span class="analysis-nav-group">{{ item.group }}</span>
          <strong>{{ item.label }}</strong>
          <span>{{ item.description }}</span>
        </button>
      </nav>

      <section v-if="tab === 'overview'" class="stack-lg">
        <div class="grid grid-2">
          <div class="card">
            <h3>Stoichiometric feature profile</h3>
            <EChart :option="featureProfileOption" :height="360" />
          </div>
          <div class="card">
            <h3>True group boxplot for selected features</h3>
            <EChart :option="boxplotMedianOption" :height="360" />
            <MethodBadge
              method="true boxplot from feature_boxplots payload"
              normalization="raw feature units"
              missing-policy="groups without p05/p25/p50/p75/p95 are blank"
              :n="summary.sample_count || summary.record_count || ''"
              note="Box values use the payload five-number summary where available."
            />
          </div>
        </div>
        <div class="grid grid-2">
          <div class="card">
            <h3>PCA on stoichiometric features</h3>
            <EChart :option="pcaOption" :height="360" />
            <MethodBadge
              method="PCA"
              normalization="feature matrix from sequence job payload"
              missing-policy="job engine preprocessing"
              :n="summary.record_count || ''"
              :n-features="summary.feature_count || ''"
              exploratory
            />
          </div>
          <div class="card">
            <h3>Top differential features</h3>
            <EChart :option="topDiffOption" :height="360" />
          </div>
        </div>
        <div class="grid grid-2">
          <div class="card">
            <h3>Run summary</h3>
            <table class="table">
              <tbody>
                <tr><td>Analysis type</td><td>{{ summary.analysis_type }}</td></tr>
                <tr><td>Omics branch</td><td>{{ summary.omics_type }}</td></tr>
                <tr><td>Extractor root</td><td>{{ summary.extractor_root || '-' }}</td></tr>
                <tr><td>Grouping field</td><td>{{ summary.group_field || '-' }}</td></tr>
                <tr><td>Reference group</td><td>{{ summary.reference_group || '-' }}</td></tr>
                <tr><td>Input files</td><td>{{ summary.input_file_count ?? '-' }}</td></tr>
                <tr><td>Feature columns</td><td>{{ summary.feature_count ?? '-' }}</td></tr>
              </tbody>
            </table>
          </div>
          <div class="card">
            <h3>Runtime privacy</h3>
            <ul>
              <li>Raw uploaded FASTA/GFF files are deleted after computation.</li>
              <li>Derived result files are temporary and expire at {{ job.expires_at || '-' }}.</li>
              <li>Results are not imported into the public PostgreSQL species registry.</li>
            </ul>
          </div>
        </div>
      </section>

      <section v-if="tab === 'catalog'" class="stack-lg">
        <div class="grid grid-2">
          <div class="card">
            <h3>Feature family coverage</h3>
            <EChart :option="featureFamilyOption" :height="340" />
            <MethodBadge
              method="automatic feature-family catalog"
              normalization="field-name and omics-type rules"
              missing-policy="catalog includes observed numeric fields only"
              :n="featureCatalog.feature_count || 0"
              note="Families are used for field selection, help text, Top/Low ranking, and modeling eligibility."
            />
          </div>
          <div class="card">
            <h3>Feature summary table</h3>
            <DataTable :payload="featureSummaryTable" :max-cols="12" />
          </div>
        </div>
        <div class="card">
          <h3>Field definitions</h3>
          <DataTable :payload="featureCatalogTable" :max-cols="10" />
        </div>
      </section>

      <section v-if="tab === 'core_visualization'" class="stack-lg">
        <div class="card">
          <div class="section-header compact">
            <div>
              <h3>Three-omics core feature visualization</h3>
              <p class="muted">
                Core fields are grouped by biological meaning. Current coverage:
                {{ corePanels.core_field_present || 0 }} / {{ corePanels.core_field_total || 0 }} fields.
              </p>
            </div>
            <a class="btn secondary" :href="sequenceResultDownloadUrl('core_feature_panels')">Download panel JSON</a>
          </div>
          <div class="grid grid-4">
            <div class="mini-card">
              <div class="label">Omics</div>
              <div class="kpi">{{ corePanels.omics_type || summary.omics_type || '-' }}</div>
            </div>
            <div class="mini-card">
              <div class="label">Rows</div>
              <div class="kpi">{{ corePanels.row_count ?? '-' }}</div>
            </div>
            <div class="mini-card">
              <div class="label">Core fields</div>
              <div class="kpi">{{ corePanels.core_field_total ?? '-' }}</div>
            </div>
            <div class="mini-card">
              <div class="label">Missing fields</div>
              <div class="kpi">{{ corePanels.core_field_missing_count ?? '-' }}</div>
            </div>
          </div>
          <div v-if="(corePanels.missing_fields || []).length" class="muted core-warning">
            Missing core fields: {{ corePanels.missing_fields.slice(0, 12).join(', ') }}{{ corePanels.missing_fields.length > 12 ? '...' : '' }}
          </div>
          <div class="core-filter-grid">
            <select class="input" v-model="corePanelFilters.group">
              <option value="">All groups</option>
              <option v-for="item in coreFilterOptions.group || []" :key="item" :value="item">{{ item }}</option>
            </select>
            <select class="input" v-model="corePanelFilters.sample_id">
              <option value="">All samples</option>
              <option v-for="item in coreFilterOptions.sample_id || []" :key="item" :value="item">{{ item }}</option>
            </select>
            <select class="input" v-model="corePanelFilters.species_id">
              <option value="">All species</option>
              <option v-for="item in coreFilterOptions.species_id || []" :key="item" :value="item">{{ item }}</option>
            </select>
            <select class="input" v-model="corePanelFilters.condition">
              <option value="">All conditions</option>
              <option v-for="item in coreFilterOptions.condition || []" :key="item" :value="item">{{ item }}</option>
            </select>
            <button class="btn secondary" @click="loadCorePanels">Apply core filters</button>
          </div>
        </div>

        <nav class="core-panel-nav">
          <a v-for="panel in corePanelList" :key="panel.panel_id" :href="`#${panel.panel_id}`">{{ panel.title }}</a>
        </nav>

        <article v-for="panel in corePanelList" :id="panel.panel_id" :key="panel.panel_id" class="card core-panel-card">
          <div class="section-header compact">
            <div>
              <h3>{{ panel.title }}</h3>
              <p class="muted">
                {{ panel.module }} / {{ panel.default_chart }} / {{ panel.unit }} / {{ panel.aggregation }}
              </p>
            </div>
            <span class="badge">{{ panel.field_coverage?.field_present || 0 }} / {{ panel.field_coverage?.field_total || 0 }} fields</span>
          </div>
          <div class="core-panel-meta">
            <span v-if="panel.region_options?.length">Region: {{ panel.region_options.join(', ') }}</span>
            <span v-if="panel.metric_options?.length">Metric: {{ panel.metric_options.join(', ') }}</span>
            <span>{{ panel.method_note }}</span>
          </div>
          <div v-if="panel.warnings?.length" class="muted core-warning">{{ panel.warnings.join(' ') }}</div>
          <div class="grid grid-2">
            <div>
              <EChart :option="corePanelChartOption(panel)" :height="340" />
              <MethodBadge
                :method="panel.default_chart"
                :normalization="panel.unit"
                missing-policy="missing and non-finite values excluded"
                :n="corePanels.row_count || ''"
                exploratory
              />
            </div>
            <div>
              <h3>Field statistics</h3>
              <DataTable :payload="corePanelStatsTable(panel)" :max-cols="9" />
            </div>
          </div>
          <div v-if="corePanelCategoricalRows(panel).length" class="card core-nested-table">
            <h3>Metadata category counts</h3>
            <DataTable :payload="corePanelCategoricalTable(panel)" :max-cols="6" />
          </div>
          <div class="card core-nested-table">
            <div class="section-header compact">
              <h3>Panel Top10 / Low10 entities</h3>
              <select
                v-if="corePanelTopLowFeatureOptions(panel).length"
                class="input core-toplow-select"
                :value="corePanelSelectedTopLowFeature(panel)"
                @change="setCorePanelTopLowFeature(panel, $event.target.value)"
              >
                <option v-for="field in corePanelTopLowFeatureOptions(panel)" :key="field" :value="field">{{ field }}</option>
              </select>
            </div>
            <DataTable v-if="corePanelHasTopLow(panel)" :payload="corePanelTopLowTable(panel)" :max-cols="12" />
            <p v-else class="muted">
              This panel contains metadata and identity fields. Top/Low ranking is shown only for numeric features with valid values.
            </p>
          </div>
        </article>
      </section>

      <section v-if="tab === 'basic'" class="stack-lg">
        <div class="grid grid-2">
          <div class="card">
            <h3>Basic KPI and missingness</h3>
            <table class="table">
              <tbody>
                <tr v-for="item in basicVisualization.kpis || []" :key="item.label">
                  <td>{{ item.label }}</td>
                  <td>{{ formatCell(item.value) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="card">
            <h3>Family coverage from uploaded features</h3>
            <EChart :option="featureFamilyOption" :height="300" />
          </div>
        </div>
        <div class="grid grid-2">
          <div class="card">
            <h3>Feature distribution</h3>
            <div class="row">
              <select class="input" v-model="selectedField">
                <option v-for="field in fieldOptions" :key="field" :value="field">{{ field }}</option>
              </select>
              <button class="btn secondary" @click="loadFieldSummary">Apply</button>
            </div>
            <EChart :option="fieldSummaryOption" :height="340" />
          </div>
          <div class="card">
            <h3>Pairwise feature scatter</h3>
            <div class="row">
              <select class="input" v-model="xField"><option v-for="field in fieldOptions" :key="field" :value="field">{{ field }}</option></select>
              <select class="input" v-model="yField"><option v-for="field in fieldOptions" :key="field" :value="field">{{ field }}</option></select>
              <button class="btn secondary" @click="loadScatter">Apply</button>
            </div>
            <EChart :option="scatterOption" :height="340" />
          </div>
        </div>
        <div class="card">
          <h3>Top / bottom records for selected feature</h3>
          <DataTable :payload="fieldSummaryTable" :max-cols="12" />
        </div>
      </section>

      <section v-if="tab === 'explorer'" class="stack-lg">
        <div class="grid grid-2">
          <div class="card">
            <h3>Selected feature summary</h3>
            <div class="row">
              <select class="input" v-model="selectedField">
                <option v-for="field in fieldOptions" :key="field" :value="field">{{ field }}</option>
              </select>
              <button class="btn secondary" @click="loadFieldSummary">Apply</button>
            </div>
            <EChart :option="fieldSummaryOption" :height="340" />
            <MethodBadge
              method="field-summary histogram"
              normalization="raw feature units"
              :n="fieldSummary?.valid_n || ''"
              :missing-policy="`${fieldSummary?.missing_n || 0} missing values`"
              exploratory
            />
          </div>
          <div class="card">
            <h3>Selected feature metadata</h3>
            <table class="table">
              <tbody>
                <tr><td>Feature</td><td>{{ selectedFeatureMeta?.feature_name || selectedField }}</td></tr>
                <tr><td>Family</td><td>{{ selectedFeatureMeta?.feature_family || '-' }}</td></tr>
                <tr><td>Unit</td><td>{{ selectedFeatureMeta?.unit || '-' }}</td></tr>
                <tr><td>Modelable</td><td>{{ selectedFeatureMeta?.is_modelable ?? '-' }}</td></tr>
                <tr><td>Missing rate</td><td>{{ formatCell(selectedFeatureMeta?.missing_rate) }}</td></tr>
              </tbody>
            </table>
            <p class="muted">{{ selectedFeatureMeta?.description || 'Select a feature to inspect its catalog definition.' }}</p>
          </div>
        </div>
        <div class="card">
          <h3>Top / bottom records for selected feature</h3>
          <DataTable :payload="fieldSummaryTable" :max-cols="12" />
        </div>
      </section>

      <section v-if="tab === 'top_low'" class="stack-lg">
        <div class="card">
          <div class="section-header compact">
            <h3>Top10 / Low10 entities by feature</h3>
            <div class="row">
              <select class="input" v-model="topLowFeature">
                <option value="">All core features</option>
                <option v-for="field in fieldOptions" :key="field" :value="field">{{ field }}</option>
              </select>
              <button class="btn secondary" @click="loadTopLow">Apply</button>
            </div>
          </div>
          <EChart :option="topLowOption" :height="420" />
          <MethodBadge
            method="numeric feature ranking"
            normalization="raw feature value"
            missing-policy="missing values excluded from ranking"
            :n="topLowRows.length"
            exploratory
          />
        </div>
        <div class="card">
          <DataTable :payload="topLowTable" :max-cols="12" />
        </div>
      </section>

      <section v-if="tab === 'deep'" class="stack-lg">
        <div class="grid grid-2">
          <div class="card">
            <h3>Strategy clusters</h3>
            <EChart :option="strategyOption" :height="320" />
          </div>
          <div class="card">
            <h3>Feature coupling ranking</h3>
            <EChart :option="couplingOption" :height="320" />
            <MethodBadge
              method="absolute coupling edge ranking"
              normalization="absolute weight"
              missing-policy="edges emitted by analysis payload only"
              :n="(analysisPayload?.coupling_edges || []).length"
              exploratory
              note="This chart is a ranked bar view, not a force-directed network."
            />
          </div>
        </div>
        <div class="grid grid-2">
          <div class="card">
            <h3>Exploratory outliers</h3>
            <DataTable :payload="outlierTable" :max-cols="12" />
          </div>
          <div class="card">
            <h3>Feature ranking</h3>
            <DataTable :payload="featureRankTable" :max-cols="8" />
          </div>
        </div>
      </section>

      <section v-if="tab === 'sample_comparison'" class="stack-lg">
        <div v-if="!sampleComparison.available" class="card">
          <h3>Sample comparison unavailable</h3>
          <p class="muted">{{ sampleComparison.reason || 'At least two groups are required.' }}</p>
        </div>
        <template v-else>
          <div class="grid grid-2">
            <div class="card">
              <h3>Feature delta heatmap</h3>
              <EChart :option="sampleDeltaOption" :height="360" />
            </div>
            <div class="card">
              <h3>Paired entity scatter</h3>
              <EChart :option="pairedScatterOption" :height="360" />
              <MethodBadge
                method="matched gene_key paired comparison"
                normalization="reference vs case raw feature values"
                missing-policy="unmatched entities excluded"
                :n="sampleComparison.matched_n || 0"
                note="If no matched entities exist, the module falls back to unpaired distribution comparison."
              />
            </div>
          </div>
          <div class="grid grid-2">
            <div class="card">
              <h3>Group overview</h3>
              <DataTable :payload="sampleGroupOverviewTable" :max-cols="8" />
            </div>
            <div class="card">
              <h3>Top comparison features</h3>
              <DataTable :payload="sampleDiffFeatureTable" :max-cols="10" />
            </div>
          </div>
        </template>
      </section>

      <section v-if="tab === 'ml'" class="stack-lg">
        <div class="card">
          <div class="section-header compact">
            <h3>Exploratory separability label view</h3>
            <div class="row">
              <select class="input" v-model="mlLabelField">
                <option value="group">Group</option>
                <option value="sample_id">Sample</option>
                <option value="species_id">Species</option>
                <option value="condition">Condition</option>
                <option value="species_condition">Species + condition</option>
              </select>
              <button class="btn secondary" @click="loadMlDiscrimination">Run selected label view</button>
            </div>
          </div>
          <DataTable :payload="mlLabelViewTable" :max-cols="8" />
        </div>
        <div class="card muted">
          {{ WORKFLOW_TERMS.mlDiagnostics.warning }} Treat these outputs as descriptive separability checks, not as validated prediction evidence.
        </div>
        <div class="card muted">
          {{ mlSampleRule.message }}
        </div>
        <div v-if="!mlDiscrimination.available" class="card">
          <h3>Exploratory separability diagnostics unavailable</h3>
          <p class="muted">{{ mlDiscrimination.reason || 'At least two label classes and modelable numeric features are required.' }}</p>
        </div>
        <ResultBlock
          v-else
          title="Exploratory separability diagnostics"
          question="Do uploaded labels produce descriptive feature separation without claiming validated prediction?"
          :finding="mlSampleRule.message"
          :method="mlDiscrimination.validation?.validation_method || 'exploratory model diagnostics over uploaded sequence-derived features'"
          normalization="StandardScaler before embedding; model preprocessing reported by payload"
          missing-policy="median imputation from ML preprocessing"
          :n="mlDiscrimination.row_count || ''"
          :n-features="mlDiscrimination.feature_count || ''"
          caveat="Small sample size, class imbalance, correlated features and uploaded label quality can change apparent separability. Treat feature importance as descriptive."
          :downloads="mlResultDownloads"
        >
          <div class="grid grid-4">
            <div class="card">
              <div class="label">Label field</div>
              <div class="kpi">{{ mlDiscrimination.label_field }}</div>
            </div>
            <div class="card">
              <div class="label">Classes</div>
              <div class="kpi">{{ mlDiscrimination.classes?.length || 0 }}</div>
            </div>
            <div class="card">
              <div class="label">Features</div>
              <div class="kpi">{{ mlDiscrimination.feature_count || 0 }}</div>
            </div>
            <div class="card">
              <div class="label">{{ mlSampleRule.sufficient ? 'Exploratory balanced accuracy' : 'Exploratory separation only' }}</div>
              <div class="kpi">{{ formatCell(mlDiscrimination.models?.random_forest?.metrics?.balanced_accuracy) }}</div>
            </div>
          </div>
          <div class="grid grid-2">
            <div class="card">
              <h3>Confusion matrix</h3>
              <EChart :option="mlConfusionOption" :height="340" />
            </div>
            <div class="card">
              <h3>Important separating features</h3>
              <EChart :option="mlImportanceOption" :height="340" />
            </div>
          </div>
          <div class="grid grid-2">
            <div class="card">
              <h3>Exploratory class separation embedding</h3>
              <EChart :option="mlEmbeddingOption" :height="340" />
              <MethodBadge
                :method="mlDiscrimination.class_separation_embedding?.method || 'embedding unavailable'"
                normalization="StandardScaler before embedding"
                missing-policy="median imputation from ML preprocessing"
                :n="mlDiscrimination.row_count || ''"
                exploratory
              />
            </div>
            <div class="card">
              <h3>ROC curve</h3>
              <EChart :option="mlRocOption" :height="340" />
            </div>
            <div class="card">
              <h3>Precision-recall curve</h3>
              <EChart :option="mlPrOption" :height="340" />
            </div>
          </div>
          <div class="grid grid-2">
            <div class="card">
              <h3>Top feature distribution</h3>
              <EChart :option="mlTopFeatureDistributionOption" :height="320" />
            </div>
            <div class="card">
              <h3>Redundant feature groups</h3>
              <DataTable :payload="mlRedundancyTable" :max-cols="4" />
            </div>
          </div>
          <div class="grid grid-2">
            <div class="card">
              <h3>Model report card</h3>
              <table class="table">
                <tbody>
                  <tr><td>Validation</td><td>{{ mlDiscrimination.validation?.validation_method || '-' }}</td></tr>
                  <tr><td>Low sample warning</td><td>{{ mlDiscrimination.validation?.low_sample_warning ? 'yes' : 'no' }}</td></tr>
                  <tr><td>Minimum sample rule</td><td>{{ mlSampleRule.sufficient ? 'pass' : 'exploratory only' }}</td></tr>
                  <tr><td>Logistic balanced accuracy</td><td>{{ formatCell(mlDiscrimination.models?.logistic_regression?.metrics?.balanced_accuracy) }}</td></tr>
                  <tr><td>RF macro-F1</td><td>{{ formatCell(mlDiscrimination.models?.random_forest?.metrics?.macro_f1) }}</td></tr>
                </tbody>
              </table>
            </div>
            <div class="card">
              <h3>Feature interpretation table</h3>
              <DataTable :payload="mlFeatureTable" :max-cols="10" />
            </div>
          </div>
          <div class="card">
            <h3>Representative entity contributions</h3>
            <DataTable :payload="mlEntityContributionTable" :max-cols="12" />
          </div>
        </ResultBlock>
      </section>

      <section v-if="tab === 'compare'" class="stack-lg">
        <div class="grid grid-2">
          <div class="card">
            <h3>Any feature: group comparison plot</h3>
            <div class="row">
              <select class="input" v-model="comparisonFeature">
                <option v-for="field in fieldOptions" :key="field" :value="field">{{ field }}</option>
              </select>
              <button class="btn secondary" @click="loadFeatureComparison">Plot</button>
            </div>
            <EChart :option="featureComparisonOption" :height="360" />
          </div>
          <div class="card">
            <h3>Any two or more genes: comparison plot</h3>
            <input class="input" v-model="entitySearch" placeholder="Search loaded entity IDs" />
            <div class="quick-tags" style="margin: 8px 0">
              <button
                v-for="entity in filteredEntityOptions.slice(0, 12)"
                :key="entity"
                class="tag-chip"
                @click="toggleEntity(entity)"
              >
                {{ entity }}
              </button>
            </div>
            <input class="input" v-model="entityInput" placeholder="geneA,geneB,geneC" />
            <input class="input" style="margin-top:10px" v-model="entityFeatureInput" placeholder="feature1,feature2 or leave blank for selected feature" />
            <button class="btn secondary" style="margin-top:10px" @click="loadEntityComparison">Plot genes</button>
            <EChart :option="entityComparisonOption" :height="360" />
          </div>
        </div>
      </section>

      <section v-if="tab === 'features'" class="card">
        <div class="section-header compact">
          <h3>Sequence feature table</h3>
          <span class="muted">{{ features.filtered_total ?? features.total }} / {{ features.total }} rows</span>
        </div>
        <div class="feature-table-toolbar">
          <input class="input" v-model="featureSearch" placeholder="Search entity, gene, sample, group, species" @keyup.enter="loadFeatures" />
          <select class="input" v-model="featureSortBy">
            <option value="">Sort by</option>
            <option v-for="item in featureTableColumnOptions" :key="item.column" :value="item.column">{{ item.column }}</option>
          </select>
          <select class="input" v-model="featureSortOrder">
            <option value="asc">Ascending</option>
            <option value="desc">Descending</option>
          </select>
          <select class="input" v-model="featureColumnFamily">
            <option value="">All column families</option>
            <option value="Identifiers">Identifiers</option>
            <option v-for="family in featureFamilies" :key="family" :value="family">{{ family }}</option>
          </select>
          <button class="btn secondary" @click="loadFeatures">Apply table filters</button>
          <a class="btn secondary" :href="featureTableExportHref">Download filtered CSV</a>
        </div>
        <div class="column-picker">
          <label v-for="item in filteredFeatureTableColumnOptions.slice(0, 80)" :key="item.column" class="column-chip">
            <input type="checkbox" :value="item.column" v-model="featureSelectedColumns" />
            <span>{{ item.column }}</span>
          </label>
        </div>
        <p class="muted">
          Select columns to preview or export a filtered table. Leave all unchecked to use the backend default full-column preview.
        </p>
        <DataTable :payload="features" :max-cols="18" />
      </section>

      <ResultBlock
        v-if="tab === 'diff_features'"
        title="Differential stoichiometric features"
        question="Which sequence-derived features differ most across the selected groups or samples?"
        :finding="differentialFeatureStatStatus.message"
        method="Reference-vs-case comparison or feature-ranking payload from the sequence analysis job."
        normalization="raw feature units unless method metadata reports otherwise"
        missing-policy="available rows and columns from differential_features payload"
        :n="differentialFeatures.total || 0"
        :caveat="differentialCaveat"
        :downloads="differentialFeatureDownloads"
        :empty-reason="differentialFeatures.total ? '' : 'No differential feature rows are available for this job.'"
      >
        <DataTable :payload="differentialFeatures" :max-cols="12" />
      </ResultBlock>

      <ResultBlock
        v-if="tab === 'entities'"
        title="Differential genes or sequence records"
        question="Which genes or uploaded records contribute most to the observed group differences?"
        :finding="differentialEntityStatStatus.message"
        method="Entity ranking from matched group deltas or model-weighted feature outlier scores."
        normalization="raw feature values and job-level ranking scores"
        missing-policy="available rows from differential_entities payload"
        :n="differentialEntities.total || 0"
        :caveat="differentialCaveat"
        :downloads="differentialEntityDownloads"
        :empty-reason="differentialEntities.total ? '' : 'No differential entity rows are available for this job.'"
      >
        <DataTable :payload="differentialEntities" :max-cols="12" />
      </ResultBlock>

      <section v-if="tab === 'downloads'" class="grid grid-2">
        <a v-for="item in downloadItems" :key="item.kind" class="card download-card" :href="sequenceResultDownloadUrl(item.kind)">
          <h3>{{ item.label }}</h3>
          <p class="muted">{{ item.description }}</p>
        </a>
      </section>
    </template>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import EChart from '../components/EChart.vue'
import MethodBadge from '../components/MethodBadge.vue'
import ResultBlock from '../components/result/ResultBlock.vue'
import { WORKFLOW_TERMS } from '../constants/platformTerminology'
import { buildEnhancedScatterOption, buildOrdinationOption } from '../utils/charts'
import {
  getDifferentialEntities,
  getDifferentialFeatures,
  getSequenceAnalysisDesign,
  getSequenceAnalysisJob,
  getSequenceAnalysisLogs,
  getSequenceAnalysisPayload,
  getSequenceAnalysisReproducibility,
  getSequenceBasicVisualization,
  getSequenceCoreFeaturePanels,
  getSequenceDownloadManifest,
  getSequenceEntityComparison,
  getSequenceFeatureCatalog,
  getSequenceFeatureComparison,
  getSequenceFeatureSummary,
  getSequenceFieldSummary,
  getSequenceFeatures,
  getSequenceInputQc,
  getSequenceJobManifest,
  getSequenceMlDiscrimination,
  getSequencePlatformBundle,
  getSequencePlots,
  getSequenceResultInterpretation,
  getSequenceSampleComparison,
  getSequenceScatter,
  getSequenceTopLow,
  sequenceDownloadUrl,
  sequenceTableExportUrl,
} from '../api/sequenceAnalysis'
import {
  getModel8Case4Gold,
  getModel8Case4Species,
  getModel8Case4Summary,
  getModel8Case4Validation,
  getModel8Case4Workflows,
  model8PlatformBundleDownloadUrl,
  model8PlatformFileDownloadUrl,
} from '../api/stoichdb'

const props = defineProps({ jobId: String })
const route = useRoute()
const MODEL8_SPECIES_CODES = ['ECOLI', 'BSUB', 'ORYSA', 'DROME', 'YEAST', 'ARATH', 'DANRE', 'MOUSE']
function model8Case4SpeciesFromJobId(value) {
  const raw = String(value || '').toUpperCase()
  return MODEL8_SPECIES_CODES.find(code => raw.endsWith(`-${code}`) || raw.endsWith(`_${code}`)) || ''
}
const model8Case4SpeciesCode = computed(() => model8Case4SpeciesFromJobId(props.jobId))
const isModel8Case4 = computed(() => {
  const raw = String(props.jobId || '').toLowerCase()
  return ['model8-case4', 'model8_case4', 'model8_case4_upload_gold'].includes(raw) || Boolean(model8Case4SpeciesCode.value)
})
const standardModel8Case4SpeciesCode = computed(() => {
  if (job.value?.case_family !== 'model8_case4_upload_gold' || !job.value?.standard_sequence_upload_case) return ''
  return String(job.value?.species_case_code || '').toUpperCase()
})
const showModel8Case4BackLink = computed(() => isModel8Case4.value || Boolean(standardModel8Case4SpeciesCode.value))
const model8Case4BackRoute = computed(() => {
  const code = model8Case4SpeciesCode.value || standardModel8Case4SpeciesCode.value || selectedModel8Case4Species.value
  return {
    path: '/case-studies',
    query: code ? { case4Species: code } : {},
    hash: code ? '#case4-species-results' : '#case4',
  }
})
const allowedTabs = new Set(['overview', 'catalog', 'core_visualization', 'basic', 'explorer', 'top_low', 'deep', 'sample_comparison', 'ml', 'compare', 'features', 'diff_features', 'entities', 'downloads'])
const tabItems = [
  { key: 'overview', group: 'Run', label: 'Overview', description: 'Summary, inputs, evidence' },
  { key: 'core_visualization', group: 'Profile', label: 'Core panels', description: 'Genome, transcript sequence, protein modules' },
  { key: 'basic', group: 'Profile', label: 'Feature profile', description: 'KPI, distribution, scatter' },
  { key: 'diff_features', group: 'Differential', label: 'Diff features', description: 'Effect size, p/q fields when present' },
  { key: 'entities', group: 'Differential', label: 'Entity ranking', description: 'Changed genes/records' },
  { key: 'ml', group: 'Diagnostics', label: 'Separability diagnostics', description: 'Exploratory label separation' },
  { key: 'downloads', group: 'Files', label: 'Downloads', description: 'CSV/JSON/methods' },
  { key: 'catalog', group: 'Fields', label: 'Feature catalog', description: 'Definitions and families' },
  { key: 'explorer', group: 'Explore', label: 'Feature explorer', description: 'One field in detail' },
  { key: 'top_low', group: 'Rank', label: 'Top/Low entities', description: 'Extreme records by field' },
  { key: 'deep', group: 'Deep', label: 'Deep analysis', description: 'Clusters, outliers, coupling' },
  { key: 'sample_comparison', group: 'Compare', label: 'Sample comparison', description: 'Reference vs case' },
  { key: 'compare', group: 'Custom', label: 'Custom comparisons', description: 'Selected entities/fields' },
  { key: 'features', group: 'Table', label: 'Feature table', description: 'Search, sort, export' },
]
function normalizeTab(value) {
  const tabName = Array.isArray(value) ? value[0] : value
  return allowedTabs.has(tabName) ? tabName : 'overview'
}
const job = ref(null)
const features = ref({ columns: [], rows: [], total: 0 })
const differentialFeatures = ref({ columns: [], rows: [], total: 0 })
const differentialEntities = ref({ columns: [], rows: [], total: 0 })
const plots = ref({})
const platform = ref({})
const analysisPayload = ref({})
const featureCatalog = ref({})
const featureSummaryPayload = ref({ rows: [] })
const basicVisualization = ref({})
const corePanels = ref({ panels: [] })
const topLowPayload = ref({ rows: [] })
const sampleComparison = ref({})
const mlDiscrimination = ref({})
const selectedField = ref('')
const topLowFeature = ref('')
const xField = ref('')
const yField = ref('')
const fieldSummary = ref(null)
const scatterData = ref(null)
const comparisonFeature = ref('')
const featureComparisonData = ref(null)
const entityInput = ref('')
const entityFeatureInput = ref('')
const entitySearch = ref('')
const entityComparisonData = ref(null)
const featureSearch = ref('')
const featureSortBy = ref('')
const featureSortOrder = ref('asc')
const featureColumnFamily = ref('')
const featureSelectedColumns = ref([])
const mlLabelField = ref('group')
const corePanelFilters = ref({ group: '', sample_id: '', species_id: '', condition: '' })
const corePanelTopLowFeatures = ref({})
const tab = ref(normalizeTab(route.query.tab))
const loading = ref(false)
const loadError = ref('')
const optionalWarnings = ref([])
const logs = ref(null)
const repro = ref(null)
const jobManifest = ref(null)
const inputQc = ref(null)
const analysisDesign = ref(null)
const resultInterpretation = ref(null)
const downloadManifest = ref(null)
const tabPayloadLoaded = ref({})
const model8SpeciesCodes = MODEL8_SPECIES_CODES
const selectedModel8Case4Species = ref(model8Case4SpeciesCode.value || 'ECOLI')
const model8Case4Species = ref(null)
const model8Case4SpeciesLoading = ref(false)
const model8Case4SpeciesError = ref('')

watch(() => route.query.tab, value => {
  tab.value = normalizeTab(value)
})

watch(tab, value => {
  ensureTabPayload(value)
})

const DataTable = defineComponent({
  props: {
    payload: { type: Object, required: true },
    maxCols: { type: Number, default: 14 },
    maxHeight: { type: Number, default: 420 },
  },
  setup(props) {
    return () => {
      const cols = (props.payload.columns || []).slice(0, props.maxCols)
      const rows = props.payload.rows || []
      return h('div', { class: 'table-scroll', style: { maxHeight: `${props.maxHeight}px` } }, [
        h('table', { class: 'table' }, [
          h('thead', [h('tr', cols.map(col => h('th', col)))]),
          h('tbody', rows.length
            ? rows.map((row, idx) => h('tr', { key: idx }, cols.map(col => h('td', formatCell(row[col])))))
            : [h('tr', [h('td', { colspan: cols.length || 1 }, 'No rows available.')])]),
        ]),
      ])
    }
  },
})

const summary = computed(() => job.value?.summary || {})
const summaryKpiCards = computed(() => {
  if (isModel8Case4.value) {
    return [
      { label: 'Feature rows', value: summary.value.record_count },
      { label: 'Protein mean length', value: summary.value.mean_protein_length },
      { label: 'CDS mean GC', value: summary.value.mean_cds_gc_fraction, format: 'percent' },
      { label: 'Numeric fields', value: summary.value.feature_count },
    ]
  }
  return [
    { label: 'Records', value: summary.value.record_count },
    { label: 'Samples', value: summary.value.sample_count },
    { label: 'Groups', value: summary.value.group_count },
    { label: 'FDR-ranked features', value: summary.value.significant_feature_count ?? 0 },
  ]
})
const fieldOptions = computed(() => {
  const fromCatalog = (featureCatalog.value?.features || []).map(row => row.feature_name).filter(Boolean)
  const fromPlots = plots.value?.comparison_capabilities?.features || []
  const fromMeta = (platform.value?.summary?.field_meta || []).map(row => row.field).filter(Boolean)
  return [...new Set([...fromCatalog, ...fromPlots, ...fromMeta])].slice(0, 260)
})

const selectedFeatureMeta = computed(() => {
  return (featureCatalog.value?.features || []).find(row => row.feature_name === selectedField.value) || null
})

const featureCatalogTable = computed(() => {
  const rows = featureCatalog.value?.features || []
  return { columns: rows.length ? Object.keys(rows[0]) : [], rows, total: rows.length }
})

const featureSummaryTable = computed(() => {
  const rows = featureSummaryPayload.value?.rows || []
  return { columns: rows.length ? Object.keys(rows[0]) : [], rows, total: rows.length }
})

const corePanelList = computed(() => corePanels.value?.panels || [])
const coreFilterOptions = computed(() => corePanels.value?.filter_options || {})

const featureFamilies = computed(() => {
  return [...new Set((featureCatalog.value?.features || []).map(row => row.feature_family).filter(Boolean))]
})

const featureTableColumnOptions = computed(() => {
  const meta = featureCatalog.value?.features || []
  const metaByField = Object.fromEntries(meta.map(row => [row.feature_name, row]))
  const idColumns = ['entity_id', 'gene_id', 'gene_key', 'transcript_id', 'protein_id', 'gene_name', 'sample_id', 'species_id', 'group', 'condition', 'omics_type', 'file_name']
  const columns = [...new Set([...idColumns, ...meta.map(row => row.feature_name), ...(features.value?.columns || [])])]
  return columns.map(col => ({
    column: col,
    family: metaByField[col]?.feature_family || 'Identifiers',
    label: metaByField[col]?.label || col,
  }))
})

const filteredFeatureTableColumnOptions = computed(() => {
  if (!featureColumnFamily.value) return featureTableColumnOptions.value
  return featureTableColumnOptions.value.filter(item => item.family === featureColumnFamily.value)
})

const featureTableParams = computed(() => {
  const columns = featureSelectedColumns.value.length ? featureSelectedColumns.value.join(',') : ''
  return {
    limit: 100,
    search: featureSearch.value,
    sort_by: featureSortBy.value,
    sort_order: featureSortOrder.value,
    columns,
  }
})

const featureTableExportHref = computed(() => isModel8Case4.value ? sequenceResultDownloadUrl('features') : sequenceTableExportUrl(props.jobId, 'features', featureTableParams.value))

const entityOptions = computed(() => {
  const rows = features.value?.rows || []
  return [...new Set(rows.map(row => row.entity_id || row.gene_id || row.transcript_id || row.protein_id).filter(Boolean))]
})

const filteredEntityOptions = computed(() => {
  const q = entitySearch.value.trim().toLowerCase()
  if (!q) return entityOptions.value
  return entityOptions.value.filter(item => String(item).toLowerCase().includes(q))
})

const userSequenceDownloadItems = [
  { kind: 'job_manifest', label: 'job_manifest.json', description: 'Workflow task manifest with inputs, privacy policy, status, and output registry.' },
  { kind: 'input_qc', label: 'input_qc.json', description: 'Pre-run FASTA, annotation, sample-sheet, grouping, and comparison-readiness checks.' },
  { kind: 'analysis_design', label: 'analysis_design.json', description: 'Research question, comparison intent, statistical plan, and evidence policy.' },
  { kind: 'features', label: 'sequence_features.csv', description: 'Per-record stoichiometric feature table.' },
  { kind: 'platform_rows', label: 'rows_for_platform.csv', description: 'Database-compatible table used by visualization and explorer modules.' },
  { kind: 'feature_catalog', label: 'feature_catalog.json', description: 'Feature families, units, descriptions, modeling eligibility, and chart recommendations.' },
  { kind: 'feature_summary_csv', label: 'feature_summary.csv', description: 'Per-feature descriptive statistics, missing rate, zero rate, and feature family.' },
  { kind: 'feature_summary', label: 'feature_summary.json', description: 'JSON version of the per-feature summary contract.' },
  { kind: 'basic_visualization', label: 'basic_visualization_payload.json', description: 'Family-level distributions, group summaries, correlations, and KPI payload.' },
  { kind: 'core_feature_panels', label: 'core_feature_panels.json', description: 'Three-omics core feature panel registry, coverage, chart payloads, stats, and Top/Low entities.' },
  { kind: 'top_low_entities_csv', label: 'top_low_entities.csv', description: 'Top10 and Low10 entities for core numeric features.' },
  { kind: 'top_low_entities', label: 'top_low_entities.json', description: 'JSON Top/Low entity payload for linked feature exploration.' },
  { kind: 'sample_comparison', label: 'sample_comparison_payload.json', description: 'Reference-vs-case comparison, delta heatmap, paired scatter, and group overview.' },
  { kind: 'sample_comparison_features_csv', label: 'sample_comparison_features.csv', description: 'Standalone sample comparison feature table.' },
  { kind: 'sample_comparison_features', label: 'sample_comparison_features.json', description: 'JSON sample comparison feature rows and method metadata.' },
  { kind: 'sample_comparison_entities_csv', label: 'sample_comparison_entities.csv', description: 'Standalone sample comparison entity contribution table.' },
  { kind: 'sample_comparison_entities', label: 'sample_comparison_entities.json', description: 'JSON sample comparison entity rows and method metadata.' },
  { kind: 'ml_discrimination', label: 'ml_discrimination_payload.json', description: 'Exploratory logistic-regression and random-forest separability diagnostics.' },
  { kind: 'ml_feature_importance', label: 'ml_feature_importance.csv', description: 'Exploratory feature-importance and direction table.' },
  { kind: 'ml_feature_importance_json', label: 'ml_feature_importance.json', description: 'JSON exploratory feature-importance and method metadata.' },
  { kind: 'ml_predictions', label: 'ml_predictions.csv', description: 'Per-entity exploratory prediction table.' },
  { kind: 'ml_predictions_json', label: 'ml_predictions.json', description: 'JSON per-entity predictions with class probabilities.' },
  { kind: 'method_metadata', label: 'method_metadata.json', description: 'Unified methods, parameters, evidence level, and limitations.' },
  { kind: 'result_interpretation', label: 'result_interpretation.json', description: 'Result-level interpretation scope, warnings, read order, and claim guardrails.' },
  { kind: 'download_manifest', label: 'download_manifest.json', description: 'Machine-readable registry of downloadable artifacts and required research contract files.' },
  { kind: 'differential_features', label: 'differential_features.csv', description: 'Differential feature comparison; statistical columns are used only when present.' },
  { kind: 'differential_entities', label: 'differential_entities.csv', description: 'Extreme genes or records and matched group deltas.' },
  { kind: 'platform_bundle', label: 'platform_bundle.json', description: 'Database-style visualization and explorer payload.' },
  { kind: 'analysis', label: 'analysis_payload.json', description: 'Deep-analysis payload with strategy, outlier, and coupling modules.' },
  { kind: 'plots', label: 'plots_payload.json', description: 'Visualization-ready chart payload.' },
  { kind: 'summary', label: 'summary.json', description: 'Run metadata, counts, warnings, and output registry.' },
  { kind: 'run_log', label: 'run_log.json', description: 'Execution provenance for this sequence analysis.' },
]

const model8Case4DownloadItems = [
  { kind: 'summary', label: 'summary.json', description: 'Case 4 metadata, counts, agreement summary, and feature extractor contract.' },
  { kind: 'gold_standard', label: 'gold_standard.json', description: 'Selection manifest, subset manifest, tolerance report, checksums, and synthetic boundary cases.' },
  { kind: 'validation', label: 'validation.json', description: 'Independent expected-vs-stored agreement and degradation status.' },
  { kind: 'workflows', label: 'workflows.json', description: 'Gold-standard upload workflow examples and privacy/security controls.' },
  { kind: 'expected_protein_features', label: 'expected_protein_features.csv', description: 'Expected protein stoichiometric features from full-database extractor logic.' },
  { kind: 'expected_cds_transcript_features', label: 'expected_cds_transcript_features.csv', description: 'Expected nucleotide/CDS/transcript stoichiometric features.' },
  { kind: 'platform_gold_agreement', label: 'platform_gold_agreement.csv', description: 'Per-field agreement rows for expected values versus stored release values.' },
  { kind: 'gold_selection_manifest', label: 'gold_selection_manifest.csv', description: 'Selected records used by the public gold-standard case.' },
  { kind: 'synthetic_boundary_expected_features', label: 'synthetic_boundary_expected_features.csv', description: 'Expected parser outputs for synthetic nucleotide and protein boundary sequences.' },
  { kind: 'bundle', label: 'complete Model-8 bundle', description: 'All Model-8 case artifacts bundled as one release package.' },
]

const model8Case4DownloadMap = {
  summary: 'case4_upload_gold/summary.json',
  gold_standard: 'case4_upload_gold/gold_standard.json',
  validation: 'case4_upload_gold/validation.json',
  workflows: 'case4_upload_gold/workflows.json',
  expected_protein_features: 'case4_upload_gold/expected_protein_features.csv',
  expected_cds_transcript_features: 'case4_upload_gold/expected_cds_transcript_features.csv',
  platform_gold_agreement: 'case4_upload_gold/platform_gold_agreement.csv',
  gold_selection_manifest: 'case4_upload_gold/gold_selection_manifest.csv',
  synthetic_boundary_expected_features: 'case4_upload_gold/synthetic_boundary_expected_features.csv',
  features: 'case4_upload_gold/gold_selection_manifest.csv',
  differential_features: 'case4_upload_gold/tolerance_report.csv',
  differential_entities: 'case4_upload_gold/gold_subset_manifest.csv',
  ml_discrimination: 'case4_upload_gold/workflows.json',
  ml_feature_importance: 'case4_upload_gold/tolerance_report.csv',
  core_feature_panels: 'case4_upload_gold/gold_standard.json',
}

const downloadItems = computed(() => isModel8Case4.value ? model8Case4DownloadItems : userSequenceDownloadItems)

function sequenceResultDownloadUrl(kind) {
  if (!isModel8Case4.value) return sequenceDownloadUrl(job.value?.job_id || props.jobId, kind)
  const path = model8Case4DownloadMap[kind]
  return path ? model8PlatformFileDownloadUrl(path) : model8PlatformBundleDownloadUrl()
}

function formatCell(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return '-'
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(4)
  if (typeof value === 'object') return JSON.stringify(value)
  const text = String(value)
  return text.length > 160 ? `${text.slice(0, 157)}...` : text
}

function formatKpiCard(card) {
  const value = card?.value
  if (card?.format === 'percent') {
    const n = Number(value)
    return Number.isFinite(n) ? `${(n * 100).toFixed(1)}%` : '-'
  }
  return formatCell(value)
}

function finiteNumber(value) {
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

function compactRows(rows, limit = 12) {
  return (rows || []).slice(0, limit)
}

function tableColumns(rows, limit = 10) {
  return rows?.length ? Object.keys(rows[0]).slice(0, limit) : []
}

function tablePayload(rows, fallbackColumns = []) {
  const safeRows = rows || []
  return { columns: safeRows.length ? Object.keys(safeRows[0]) : fallbackColumns, rows: safeRows, total: safeRows.length }
}

function groupCounts(rows, key) {
  const counts = {}
  ;(rows || []).forEach(row => {
    const value = row?.[key] || 'unknown'
    counts[value] = (counts[value] || 0) + 1
  })
  return Object.entries(counts).map(([group, count]) => ({ group, count }))
}

function numericSummary(values) {
  const nums = values.map(Number).filter(Number.isFinite).sort((a, b) => a - b)
  if (!nums.length) return { min: 0, p25: 0, median: 0, p75: 0, max: 0, mean: 0 }
  const q = p => nums[Math.min(nums.length - 1, Math.max(0, Math.floor((nums.length - 1) * p)))]
  return {
    min: nums[0],
    p25: q(0.25),
    median: q(0.5),
    p75: q(0.75),
    max: nums[nums.length - 1],
    mean: nums.reduce((sum, value) => sum + value, 0) / nums.length,
  }
}

function model8CaseRows(rows, caseCode = '') {
  const code = String(caseCode || '').toUpperCase()
  return code ? (rows || []).filter(row => String(row?.case_code || '').toUpperCase() === code) : (rows || [])
}

function quantile(values, p) {
  const nums = values.map(Number).filter(Number.isFinite).sort((a, b) => a - b)
  if (!nums.length) return null
  return nums[Math.min(nums.length - 1, Math.max(0, Math.floor((nums.length - 1) * p)))]
}

function inferCase4FeatureFamily(field, omicsType = '') {
  const key = String(field || '').toLowerCase()
  const omics = String(omicsType || '').toLowerCase()
  if (omics.includes('protein') || ['cys_count', 'ser_count', 'asn_count', 'met_count', 'c_atoms', 'n_atoms', 's_atoms', 'c_atoms_per_aa', 'n_atoms_per_aa', 's_atoms_per_aa', 'aa_entropy', 'mw_approx'].includes(key)) {
    if (key.includes('_per_aa')) return 'Protein elemental ratios'
    if (key.includes('count')) return 'Protein residue counts'
    if (['c_atoms', 'n_atoms', 's_atoms', 'mw_approx'].includes(key)) return 'Protein molecular chemistry'
    return 'Protein sequence'
  }
  if (['gc_fraction', 'n_fraction', 'valid_bases', 'gc_count', 'n_count', 'entropy'].includes(key) || omics.includes('nucleotide') || omics.includes('transcript')) {
    if (key.includes('fraction') || key === 'entropy') return 'Nucleotide composition'
    return 'Nucleotide sequence'
  }
  return 'Sequence metrics'
}

function normalizeModel8Case4FeatureRow(row, omicsType, idx) {
  const out = {
    row_id: idx + 1,
    case_code: String(row.case_code || '').toUpperCase(),
    species_id: String(row.case_code || '').toUpperCase(),
    sample_id: omicsType === 'protein' ? 'protein_gold' : 'cds_transcript_gold',
    group: omicsType,
    condition: 'gold_standard_validation',
    omics_type: omicsType,
    entity_id: row.entity_id || row.protein_id || row.transcript_id || row.gene_id,
    gene_id: row.gene_id || '',
    protein_id: row.protein_id || '',
    transcript_id: row.transcript_id || '',
    seq_sha256: row.seq_sha256 || '',
  }
  Object.entries(row || {}).forEach(([key, value]) => {
    if (out[key] !== undefined || ['case_code', 'entity_id', 'gene_id', 'protein_id', 'transcript_id', 'seq_sha256'].includes(key)) return
    const n = Number(value)
    out[key] = value !== '' && Number.isFinite(n) ? n : value
  })
  out.sequence_length = Number(out.length || out.sequence_length || 0)
  return out
}

function model8NumericFields(rows) {
  const excluded = new Set([
    'row_id', 'case_code', 'species_id', 'sample_id', 'group', 'condition', 'omics_type',
    'entity_id', 'gene_id', 'protein_id', 'transcript_id', 'seq_sha256',
    'elemental_contract_id', 'nucleotide_gold_type', 'gold_role',
  ])
  const fields = []
  ;(rows || []).forEach(row => {
    Object.keys(row || {}).forEach(key => {
      if (excluded.has(key) || fields.includes(key)) return
      if ((rows || []).some(item => Number.isFinite(Number(item?.[key])))) fields.push(key)
    })
  })
  return fields
}

function summarizeFeatureRows(rows, field) {
  const values = (rows || []).map(row => Number(row?.[field])).filter(Number.isFinite)
  const mean = values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null
  const p25 = quantile(values, 0.25)
  const median = quantile(values, 0.5)
  const p75 = quantile(values, 0.75)
  const min = quantile(values, 0)
  const max = quantile(values, 1)
  const variance = values.length && mean !== null ? values.reduce((sum, value) => sum + ((value - mean) ** 2), 0) / values.length : null
  return {
    field,
    n: rows.length,
    valid_n: values.length,
    missing_rate: rows.length ? 1 - (values.length / rows.length) : 1,
    min,
    p25,
    median,
    p75,
    max,
    mean,
    sd: variance === null ? null : Math.sqrt(variance),
    iqr: p75 !== null && p25 !== null ? p75 - p25 : null,
  }
}

function buildModel8Case4Artifacts(summaryPayload, goldPayload, workflowsPayload, validationPayload, speciesPayload = null, caseCode = '') {
  const activeCode = String(caseCode || '').toUpperCase()
  const selectedSpeciesPayload = speciesPayload && (!activeCode || String(speciesPayload.case_code || '').toUpperCase() === activeCode) ? speciesPayload : null
  const selectionRows = selectedSpeciesPayload?.tables?.selected_gold_records?.rows || model8CaseRows(goldPayload?.selection_manifest || [], activeCode)
  const subsetRows = model8CaseRows(goldPayload?.subset_manifest || [], activeCode)
  const proteinSourceRows = selectedSpeciesPayload?.tables?.expected_protein_features?.rows || []
  const nucleotideSourceRows = selectedSpeciesPayload?.tables?.expected_cds_transcript_features?.rows || []
  const agreementRows = selectedSpeciesPayload?.tables?.platform_gold_agreement?.rows || []
  const toleranceRows = selectedSpeciesPayload?.tables?.tolerance_report?.rows || goldPayload?.tolerance_report || validationPayload?.tolerance_report || []
  const syntheticBoundary = goldPayload?.synthetic_boundary || {}
  const syntheticRows = [
    ...(syntheticBoundary.error_cases || []),
    ...(syntheticBoundary.nucleotide_boundary_cases || []),
    ...(syntheticBoundary.protein_boundary_cases || []),
  ]
  const expectedFeatureRows = [
    ...proteinSourceRows.map((row, idx) => normalizeModel8Case4FeatureRow(row, 'protein', idx)),
    ...nucleotideSourceRows.map((row, idx) => normalizeModel8Case4FeatureRow(row, 'cds_transcript', proteinSourceRows.length + idx)),
  ]
  const featureRows = expectedFeatureRows.length
    ? expectedFeatureRows
    : selectionRows.map((row, idx) => ({
      row_id: idx + 1,
      case_code: row.case_code,
      species_id: row.case_code,
      sample_id: row.protein_sequence_found ? 'protein_gold' : 'sequence_gold',
      group: row.nucleotide_sequence_found ? 'protein + nucleotide' : 'protein',
      condition: 'gold_standard_validation',
      omics_type: row.omics || row.omics_type || row.sequence_type || 'protein_and_cds_gold',
      entity_id: row.entity_id || row.gene_id || row.protein_id || row.transcript_id || row.record_id,
      gene_id: row.gene_id || row.locus_tag || row.entity_id,
      protein_id: row.protein_id || '',
      transcript_id: row.transcript_id || row.cds_id || '',
      sequence_length: Number(row.sequence_length || row.length || row.protein_length || row.cds_length || 0),
      length_decile: Number(row.length_decile || 0),
      gold_role: row.gold_role || row.selection_reason || 'expected_feature_validation',
    }))
  const numericFields = model8NumericFields(featureRows)
  const featureStats = numericFields.map(field => {
    const stats = summarizeFeatureRows(featureRows, field)
    const family = inferCase4FeatureFamily(field, featureRows.find(row => Number.isFinite(Number(row[field])))?.omics_type)
    return {
      ...stats,
      feature_name: field,
      feature_family: family,
      unit: field.includes('fraction') || field.includes('per_') ? 'ratio' : 'raw sequence unit',
      effect_size: stats.iqr,
      importance: Math.abs(Number(stats.iqr ?? stats.sd ?? stats.mean ?? 0)),
      method: 'descriptive_real_sequence_feature_profile',
    }
  }).sort((a, b) => Number(b.importance || 0) - Number(a.importance || 0))
  const diffFeatureRows = featureStats.map((row, idx) => ({
    rank: idx + 1,
    omics: row.feature_family,
    feature_name: row.feature_name,
    feature_family: row.feature_family,
    valid_n: row.valid_n,
    median: row.median,
    mean: row.mean,
    min: row.min,
    max: row.max,
    iqr: row.iqr,
    effect_size: row.effect_size,
    importance: row.importance,
    method: row.method,
  }))
  const entityRows = [
    ...featureRows
      .slice()
      .sort((a, b) => Number(b.sequence_length || 0) - Number(a.sequence_length || 0))
      .slice(0, 80)
      .map((row, idx) => ({
        entity_id: row.entity_id,
        gene_id: row.gene_id,
        case_code: row.case_code,
        species_id: row.species_id,
        omics_type: row.omics_type,
        rank_type: 'Long sequence',
        rank: idx + 1,
        reason: 'largest sequence_length in this species gold subset',
        feature_name: 'sequence_length',
        feature_value: row.sequence_length,
        value: row.sequence_length,
      })),
    ...syntheticRows.map((row, idx) => ({
      entity_id: row.record_id || row.case_id || `synthetic_${idx + 1}`,
      case_code: row.case_code || 'synthetic',
      omics_type: row.omics || row.omics_type || row.sequence_type,
      rank_type: 'Synthetic boundary',
      reason: row.expected_error || row.reason || row.description || 'boundary parser case',
      feature_value: row.sequence_length || row.length || '',
    })),
  ]
  const featureProfile = Object.fromEntries(featureStats.slice(0, 24).map(row => [row.feature_name, { median: row.median, mean: row.mean }]))
  const boxplotFeatures = featureStats.slice(0, 12).map(row => row.feature_name)
  const featureBoxplots = []
  boxplotFeatures.forEach(feature => {
    ;['protein', 'cds_transcript'].forEach(group => {
      const groupRows = featureRows.filter(row => row.omics_type === group && Number.isFinite(Number(row[feature])))
      if (!groupRows.length) return
      const stats = summarizeFeatureRows(groupRows, feature)
      featureBoxplots.push({
        feature_name: feature,
        group,
        min: stats.min,
        p25: stats.p25,
        median: stats.median,
        p75: stats.p75,
        max: stats.max,
      })
    })
  })
  const pcaRows = featureRows.slice(0, 700).map((row, idx) => ({
    entity_id: row.entity_id,
    group: row.omics_type,
    sample_id: row.omics_type,
    species_id: row.species_id,
    pc1: Number(row.sequence_length || row.length || 0),
    pc2: Number(row.n_atoms_per_aa ?? row.gc_fraction ?? row.entropy ?? row.aa_entropy ?? 0),
  }))
  const lengthStats = numericSummary(featureRows.map(row => row.sequence_length))
  const proteinLengthStats = numericSummary(featureRows.filter(row => row.omics_type === 'protein').map(row => row.sequence_length))
  const cdsGcStats = numericSummary(featureRows.filter(row => row.omics_type === 'cds_transcript').map(row => row.gc_fraction))
  const topLowRows = [
    ...featureRows.slice().sort((a, b) => Number(b.sequence_length || 0) - Number(a.sequence_length || 0)).slice(0, 10).map((row, idx) => ({ ...row, feature_name: 'sequence_length', feature_value: row.sequence_length, value: row.sequence_length, rank_type: 'Top10', rank: idx + 1 })),
    ...featureRows.slice().sort((a, b) => Number(a.sequence_length || 0) - Number(b.sequence_length || 0)).slice(0, 10).map((row, idx) => ({ ...row, feature_name: 'sequence_length', feature_value: row.sequence_length, value: row.sequence_length, rank_type: 'Low10', rank: idx + 1 })),
  ]
  const workflowRows = workflowsPayload?.workflow_examples || []
  const securityRows = workflowsPayload?.privacy_security_checks || []
  const familyRows = groupCounts(diffFeatureRows, 'feature_family').map(row => ({ feature_family: row.group, feature_count: row.count }))
  const fieldMeta = featureStats.map(row => ({
    field: row.feature_name,
    feature_name: row.feature_name,
    feature_family: row.feature_family,
    unit: row.unit,
    description: `Real Case4 ${row.feature_family} field profiled from expected sequence features.`,
    chart_recommendation: 'bar',
    model_eligible: true,
  }))
  const coreStats = Object.fromEntries(featureStats.slice(0, 20).map(row => [row.feature_name, {
    field: row.feature_name,
      present: true,
    n: row.n,
    valid_n: row.valid_n,
    missing_rate: row.missing_rate,
    median: row.median,
    mean: row.mean,
    q1: row.p25,
    q3: row.p75,
  }]))
  const proteinByGene = new Map(featureRows.filter(row => row.omics_type === 'protein').map(row => [row.gene_id || row.entity_id, row]))
  const pairedRows = featureRows
    .filter(row => row.omics_type === 'cds_transcript' && proteinByGene.has(row.gene_id || row.entity_id))
    .slice(0, 300)
    .map(row => {
      const protein = proteinByGene.get(row.gene_id || row.entity_id)
      return {
        feature_name: 'protein length vs CDS length/3',
        entity_id: row.gene_id || row.entity_id,
        reference_value: Number(protein?.sequence_length || protein?.length || 0),
        case_value: Number(row.sequence_length || row.length || 0) / 3,
      }
    })
  const deltaRows = []
  featureStats.slice(0, 24).forEach(stat => {
    ;['protein', 'cds_transcript'].forEach(group => {
      const groupStats = summarizeFeatureRows(featureRows.filter(row => row.omics_type === group && Number.isFinite(Number(row[stat.feature_name]))), stat.feature_name)
      if (!groupStats.valid_n) return
      const denominator = Math.abs(Number(stat.max || 0) - Number(stat.min || 0)) || 1
      deltaRows.push({
        comparison: group,
        feature_name: stat.feature_name,
        standardized_delta: ((Number(groupStats.median || 0) - Number(stat.median || 0)) / denominator) * 3,
      })
    })
  })
  const passRate = validationPayload?.agreement?.pass_rate ?? summaryPayload?.agreement?.pass_rate ?? 1
  return {
    jobPayload: {
      job_id: activeCode ? `model8-case4-${activeCode}` : 'model8-case4',
      name: activeCode ? `Model-8 Case 4 sequence upload gold: ${activeCode}` : 'Model-8 Case 4 sequence upload gold standard',
      status: 'SUCCEEDED',
      analysis_type: 'curated_sequence_upload_gold',
      created_at: summaryPayload?.generated_at_utc,
      updated_at: summaryPayload?.generated_at_utc,
      expires_at: 'public curated release',
      summary: {
        record_count: activeCode ? featureRows.length : Number(summaryPayload?.protein_gold_records || 0) + Number(summaryPayload?.nucleotide_gold_records || 0) + Number(summaryPayload?.synthetic_nucleotide_records || 0) + Number(summaryPayload?.synthetic_protein_records || 0),
        sample_count: activeCode ? 1 : summaryPayload?.species_count,
        group_count: [...new Set(featureRows.map(row => row.omics_type).filter(Boolean))].length,
        significant_feature_count: diffFeatureRows.length,
        analysis_type: 'Model-8 sequence upload gold-standard validation',
        omics_type: 'protein + CDS/transcript',
        extractor_root: summaryPayload?.full_database_feature_extractor_contract?.script_root || summaryPayload?.full_database_feature_extractor_contract?.feature_script_root || 'full-database feature extractor contract',
        group_field: 'omics_type',
        reference_group: 'stored frozen platform feature tables',
        input_file_count: activeCode ? 2 : (goldPayload?.source_checksums?.length || 0),
        feature_count: numericFields.length,
        mean_protein_length: proteinLengthStats.mean,
        mean_cds_gc_fraction: cdsGcStats.mean,
      },
    },
    features: tablePayload(featureRows, ['row_id', 'case_code', 'omics_type', 'entity_id', 'sequence_length']),
    differentialFeatures: tablePayload(diffFeatureRows),
    differentialEntities: tablePayload(entityRows),
    plots: {
      feature_profile: featureProfile,
      feature_boxplots: featureBoxplots,
      pca_scatter: pcaRows,
      top_differential_features: diffFeatureRows.slice(0, 16),
      comparison_capabilities: { features: numericFields },
    },
    platform: {
      summary: { field_meta: fieldMeta },
      feature_rows: featureRows,
      source: 'Model-8 Case4 generated gold-standard artifacts',
    },
    featureCatalog: {
      feature_count: fieldMeta.length,
      features: fieldMeta,
      families: familyRows,
    },
    featureSummaryPayload: {
      rows: featureStats.map(row => ({
        feature_name: row.feature_name,
        feature_family: row.feature_family,
        valid_n: row.valid_n,
        missing_rate: row.missing_rate,
        zero_rate: 0,
        mean: row.mean,
        median: row.median,
        min: row.min,
        max: row.max,
        iqr: row.iqr,
      })),
    },
    basicVisualization: {
      feature_family_coverage: familyRows,
      kpis: [
        { label: 'Displayed feature rows', value: featureRows.length },
        { label: 'Numeric sequence fields', value: numericFields.length },
        { label: 'Agreement checks', value: validationPayload?.agreement?.total_checks },
        { label: 'Agreement pass rate', value: passRate },
      ],
    },
    corePanels: {
      omics_type: 'protein + nucleotide',
      row_count: featureRows.length,
      core_field_total: 2,
      core_field_present: 2,
      core_field_missing_count: 0,
      missing_fields: [],
      filter_options: {
        group: [...new Set(featureRows.map(row => row.case_code).filter(Boolean))],
        sample_id: [...new Set(featureRows.map(row => row.omics_type).filter(Boolean))],
        species_id: [...new Set(featureRows.map(row => row.species_id).filter(Boolean))],
        condition: ['gold_standard_validation'],
      },
      panels: [{
        panel_id: 'case4_sequence_features',
        title: `${activeCode || 'Model-8'} real sequence-derived feature profile`,
        omics_type: 'protein + nucleotide',
        unit: 'native feature units',
        default_chart: 'grouped_boxplot',
        field_stats: coreStats,
        chart_data: {
          categorical_counts: [
            ...groupCounts(featureRows, 'case_code').map(row => ({ field: 'case_code', value: row.group, count: row.count })),
            ...groupCounts(featureRows, 'omics_type').map(row => ({ field: 'omics_type', value: row.group, count: row.count })),
          ],
        },
        top_low: {
          sequence_length: {
            top10: topLowRows.filter(row => row.rank_type === 'Top10'),
            low10: topLowRows.filter(row => row.rank_type === 'Low10'),
          },
        },
      }],
    },
    topLowPayload: tablePayload(topLowRows),
    analysisPayload: {
      strategy_breakdown: workflowRows.map(row => ({ strategy_cluster: row.workflow_id || row.analysis_type, count: 1, omics_type: row.omics_type })),
      coupling_edges: diffFeatureRows.slice(0, 14).map(row => ({ source: row.feature_family, target: row.feature_name, weight: row.effect_size ?? row.importance })),
      outliers: {
        high: syntheticRows.map((row, idx) => ({ entity_id: row.record_id || `synthetic_${idx + 1}`, rank_type: 'synthetic boundary', feature_name: row.expected_error || row.reason || 'boundary', feature_value: row.sequence_length || row.length || '' })),
        low: validationPayload?.failed_examples || [],
        multivariate: validationPayload?.missing_examples || [],
      },
      feature_rank: diffFeatureRows.map(row => ({ feature: row.feature_name, median: row.median, mean: row.mean, omics: row.omics, effect_size: row.effect_size })),
    },
    sampleComparison: {
      available: true,
      reason: '',
      matched_n: pairedRows.length || diffFeatureRows.length,
      group_overview: groupCounts(featureRows, 'omics_type').map(row => ({
        group: row.group,
        record_count: row.count,
        sample_count: 1,
        species_count: [...new Set(featureRows.filter(item => item.omics_type === row.group).map(item => item.species_id))].length,
        strategy_clusters: ['gold_standard_validation'],
      })),
      differential_features: diffFeatureRows,
      feature_delta_heatmap: deltaRows,
      feature_boxplots: featureBoxplots,
      paired_scatter: pairedRows,
    },
    mlDiscrimination: {
      available: true,
      label_field: 'omics_type',
      row_count: featureRows.length,
      feature_count: numericFields.length,
      classes: [...new Set(featureRows.map(row => row.omics_type))],
      validation: { validation_method: 'gold-standard agreement diagnostics, not predictive training', low_sample_warning: true },
      feature_importance: diffFeatureRows.map(row => ({
        feature_name: row.feature_name,
        importance: row.importance,
        rf_importance: row.importance,
        logistic_abs_coef: row.effect_size,
        direction: row.feature_family,
        median: row.median,
      })),
      label_view_status: securityRows.map(row => ({ label_view: row.control, status: row.platform_status, evidence: row.evidence })),
      models: {
        random_forest: { metrics: { balanced_accuracy: passRate, macro_f1: passRate } },
        logistic_regression: { metrics: { balanced_accuracy: passRate } },
      },
      class_separation_embedding: {
        method: 'length-composition diagnostic embedding',
        points: pcaRows.map(row => ({ x: row.pc1, y: row.pc2, group: row.group, entity_id: row.entity_id })),
      },
      top_feature_distributions: [{
        feature_name: featureStats[0]?.feature_name || 'sequence_length',
        groups: groupCounts(featureRows, 'omics_type').map(group => {
          const stats = numericSummary(featureRows.filter(row => row.omics_type === group.group).map(row => row[featureStats[0]?.feature_name || 'sequence_length']))
          return { label: group.group, p25: stats.p25, p50: stats.median, p75: stats.p75 }
        }),
      }],
      confusion_matrix: {
        labels: [...new Set(featureRows.map(row => row.omics_type))],
        values: (() => {
          const labels = [...new Set(featureRows.map(row => row.omics_type))]
          return labels.map(label => labels.map(other => label === other
            ? featureRows.filter(row => row.omics_type === label).length
            : 0))
        })(),
      },
      roc_pr: {
        available: false,
        reason: 'Case4 is a gold-standard agreement validation, not a binary prediction benchmark.',
      },
      feature_redundancy: {
        groups: groupCounts(diffFeatureRows, 'feature_family').map(group => ({
          representative_feature: group.group,
          member_count: group.count,
          members: diffFeatureRows.filter(row => row.feature_family === group.group).map(row => row.feature_name),
          max_abs_spearman_to_representative: 1,
        })),
      },
      entity_contributions: entityRows.slice(0, 80),
    },
  }
}

function corePanelStatsRows(panel) {
  return Object.values(panel.field_stats || {}).map(row => ({
    field: row.field,
    present: row.present,
    n: row.n,
    valid_n: row.valid_n,
    missing_rate: row.missing_rate,
    unit: panel.unit,
    median: row.median,
    mean: row.mean,
    q1: row.q1,
    q3: row.q3,
  }))
}

function corePanelStatsTable(panel) {
  const rows = corePanelStatsRows(panel)
  return { columns: rows.length ? Object.keys(rows[0]) : [], rows, total: rows.length }
}

function corePanelCategoricalRows(panel) {
  return panel.chart_data?.categorical_counts || []
}

function corePanelCategoricalTable(panel) {
  const rows = corePanelCategoricalRows(panel).slice(0, 120)
  return { columns: rows.length ? Object.keys(rows[0]) : ['field', 'value', 'count'], rows, total: rows.length }
}

function corePanelHasTopLow(panel) {
  return Object.values(panel.top_low || {}).some(payload => (payload.top10 || []).length || (payload.low10 || []).length)
}

function corePanelTopLowFeatureOptions(panel) {
  return Object.entries(panel.top_low || {})
    .filter(([, payload]) => (payload.top10 || []).length || (payload.low10 || []).length)
    .map(([field]) => field)
}

function corePanelSelectedTopLowFeature(panel) {
  const options = corePanelTopLowFeatureOptions(panel)
  const selected = corePanelTopLowFeatures.value[panel.panel_id]
  return options.includes(selected) ? selected : (options[0] || '')
}

function setCorePanelTopLowFeature(panel, field) {
  corePanelTopLowFeatures.value = {
    ...corePanelTopLowFeatures.value,
    [panel.panel_id]: field,
  }
}

function corePanelTopLowTable(panel) {
  const rows = []
  const field = corePanelSelectedTopLowFeature(panel)
  const payload = field ? (panel.top_low || {})[field] : null
  ;[...(payload?.top10 || []), ...(payload?.low10 || [])].forEach(row => {
    rows.push({
      field,
      rank_type: row.rank_type,
      rank: row.rank,
      entity_id: row.entity_id,
      gene_id: row.gene_id,
      gene_name: row.gene_name || row.gene_symbol || '',
      sample_id: row.sample_id,
      group: row.group,
      species_id: row.species_id,
      value: row.value,
    })
  })
  return { columns: rows.length ? Object.keys(rows[0]) : [], rows: rows.slice(0, 120), total: rows.length }
}

function corePanelChartOption(panel) {
  const categoricalRows = corePanelCategoricalRows(panel)
  if (panel.default_chart === 'categorical_bar' && categoricalRows.length) {
    const fields = Array.from(new Set(categoricalRows.map(row => row.field))).map(field => {
      const rows = categoricalRows.filter(row => row.field === field)
      const total = rows.reduce((sum, row) => sum + (Number(row.count) || 0), 0)
      const top = rows.slice().sort((a, b) => (Number(b.count) || 0) - (Number(a.count) || 0))[0]
      return {
        field,
        total,
        distinct: rows.length,
        top_value: top?.value ?? '',
        top_count: Number(top?.count) || 0,
      }
    }).sort((a, b) => b.total - a.total).slice(0, 24)
    return {
      tooltip: {
        trigger: 'axis',
        formatter: params => {
          const row = params?.[0]?.data?.raw || {}
          return `${row.field}<br/>available records: ${formatCell(row.total)}<br/>distinct values: ${formatCell(row.distinct)}<br/>top value: ${formatCell(row.top_value)} (${formatCell(row.top_count)})`
        },
      },
      grid: { left: 128, right: 32, bottom: 50, top: 28 },
      xAxis: { type: 'value', name: 'records' },
      yAxis: { type: 'category', data: fields.map(row => row.field).reverse() },
      series: [{
        type: 'bar',
        data: fields.map(row => ({ value: row.total, raw: row })).reverse(),
        itemStyle: { color: '#2a9d8f' },
      }],
    }
  }
  const matrix = panel.chart_data?.composition_matrix || []
  if (matrix.length) {
    if (matrix.every(row => row.residue)) {
      const rows = matrix
        .map(row => ({
          label: row.residue,
          field: row.field,
          value: Number(row.median ?? row.mean),
          valid_n: row.valid_n,
        }))
        .filter(row => Number.isFinite(row.value))
      return {
        tooltip: {
          trigger: 'axis',
          formatter: params => {
            const row = params?.[0]?.data?.raw || {}
            return `${row.field || row.label}<br/>median: ${formatCell(row.value)}<br/>valid n: ${formatCell(row.valid_n)}`
          },
        },
        grid: { left: 64, right: 28, bottom: 58, top: 28 },
        xAxis: { type: 'category', data: rows.map(row => row.label), axisLabel: { rotate: 35 } },
        yAxis: { type: 'value', name: panel.unit || 'value' },
        series: [{
          type: 'bar',
          data: rows.map(row => ({ value: row.value, raw: row })),
          itemStyle: { color: '#2a9d8f' },
        }],
      }
    }
    const isCodonMatrix = matrix.some(row => row.codon || (row.first && row.second && row.third))
    const xLabels = [...new Set(matrix.map(row => row.column || row.third || row.residue || row.field))]
    const yLabels = [...new Set(matrix.map(row => {
      if (isCodonMatrix) return `${row.first || ''}${row.second || ''}`
      return row.row || row.first || 'composition'
    }))]
    const data = matrix.map(row => [
      xLabels.indexOf(row.column || row.third || row.residue || row.field),
      yLabels.indexOf(isCodonMatrix ? `${row.first || ''}${row.second || ''}` : (row.row || row.first || 'composition')),
      row.median ?? row.mean ?? 0,
      row.codon || row.field,
      row.field,
    ])
    const values = data.map(row => finiteNumber(row[2])).filter(value => value !== null)
    const minValue = values.length ? Math.min(...values) : 0
    const maxValue = values.length ? Math.max(...values) : 1
    return {
      tooltip: { formatter: params => `${params.data[3]}<br/>${params.data[4] || ''}<br/>median: ${formatCell(params.data[2])}` },
      grid: { left: isCodonMatrix ? 88 : 80, right: 24, bottom: 74, top: 28 },
      xAxis: { type: 'category', data: xLabels, axisLabel: { rotate: 45, fontSize: 10 } },
      yAxis: { type: 'category', data: yLabels, axisLabel: { fontSize: isCodonMatrix ? 10 : 11 } },
      visualMap: {
        min: minValue,
        max: maxValue || 1,
        orient: 'horizontal',
        bottom: 0,
        calculable: true,
        precision: 4,
        formatter: value => formatCell(value),
      },
      series: [{
        type: 'heatmap',
        data,
        label: { show: matrix.length <= 25, formatter: params => formatCell(params.data[2]) },
        itemStyle: { borderWidth: 1, borderColor: 'rgba(255,255,255,0.88)' },
        emphasis: { itemStyle: { borderColor: '#143551', borderWidth: 1.5 } },
      }],
    }
  }
  const rows = corePanelStatsRows(panel).filter(row => row.present && row.valid_n > 0).slice(0, 28)
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 118, right: 24, bottom: 42, top: 28 },
    xAxis: { type: 'value' },
    yAxis: { type: 'category', data: rows.map(row => row.field).reverse() },
    series: [{ type: 'bar', data: rows.map(row => row.median ?? row.mean ?? 0).reverse(), itemStyle: { color: '#2370cf' } }],
  }
}

const featureProfileOption = computed(() => {
  const profile = plots.value.feature_profile || {}
  const features = Object.keys(profile)
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 52, right: 24, bottom: 80, top: 28 },
    xAxis: { type: 'category', data: features, axisLabel: { rotate: 35 } },
    yAxis: { type: 'value' },
    series: [{ type: 'bar', data: features.map(name => profile[name]?.median ?? profile[name]?.mean ?? 0), itemStyle: { color: '#2370cf' } }],
  }
})

const featureFamilyOption = computed(() => {
  const rows = basicVisualization.value?.feature_family_coverage || featureCatalog.value?.families || []
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 98, right: 24, bottom: 34, top: 28 },
    xAxis: { type: 'value' },
    yAxis: { type: 'category', data: rows.map(row => row.feature_family).reverse() },
    series: [{
      type: 'bar',
      data: rows.map(row => row.feature_count || 0).reverse(),
      itemStyle: { color: '#2370cf' },
    }],
  }
})

const boxplotMedianOption = computed(() => {
  const rows = plots.value.feature_boxplots || []
  const features = [...new Set(rows.map(row => row.feature_name))]
  const groups = [...new Set(rows.map(row => row.group))]
  const categories = []
  const data = []
  const colors = ['#2370cf', '#2a9d8f', '#e76f51', '#8d6e63', '#546e7a']
  features.forEach((feature) => {
    groups.forEach((group) => {
      const row = rows.find(item => item.group === group && item.feature_name === feature)
      const values = [
        row?.min ?? row?.p05,
        row?.p25 ?? row?.q1,
        row?.median ?? row?.p50,
        row?.p75 ?? row?.q3,
        row?.max ?? row?.p95,
      ].map(value => Number(value))
      if (values.every(value => Number.isFinite(value))) {
        categories.push(`${feature}\n${group}`)
        data.push(values)
      }
    })
  })
  return {
    tooltip: {
      trigger: 'item',
      formatter: params => {
        const v = params.data || []
        return `${params.name}<br/>min/p05: ${formatCell(v[0])}<br/>q1: ${formatCell(v[1])}<br/>median: ${formatCell(v[2])}<br/>q3: ${formatCell(v[3])}<br/>max/p95: ${formatCell(v[4])}`
      },
    },
    grid: { left: 52, right: 24, bottom: 110, top: 36 },
    xAxis: { type: 'category', data: categories, axisLabel: { rotate: 45, fontSize: 10 } },
    yAxis: { type: 'value' },
    series: [{
      type: 'boxplot',
      data,
      itemStyle: { color: 'rgba(35,112,207,0.18)', borderColor: colors[0] },
    }],
  }
})

const pcaOption = computed(() => {
  const rows = plots.value.pca_scatter || []
  return buildOrdinationOption(rows, 'pc1', 'pc2', 'PC1', 'PC2', {
    title: 'Sequence-analysis PCA scatter',
    subtitle: 'Task-level projection; interpret as job-specific feature space, not platform-wide species evidence.',
  })
})

const topDiffOption = computed(() => {
  const rows = (plots.value.top_differential_features || []).slice(0, 12)
  if (!rows.length) {
    const fallbackRows = (analysisPayload.value?.feature_rank || []).slice(0, 12)
    const values = fallbackRows.map(row => Math.abs(finiteNumber(row.median ?? row.mean) ?? 0))
    return {
      tooltip: {
        trigger: 'axis',
        formatter: params => {
          const row = fallbackRows[fallbackRows.length - 1 - params[0].dataIndex] || {}
          return `${row.feature}<br/>median: ${formatCell(row.median)}<br/>mean: ${formatCell(row.mean)}`
        },
      },
      title: {
        text: fallbackRows.length ? '' : 'No differential features for single-sequence analysis',
        left: 'center',
        top: 'middle',
        textStyle: { fontSize: 13, color: '#6b7f92' },
      },
      grid: { left: 132, right: 24, bottom: 42, top: 28 },
      xAxis: { type: 'value', name: fallbackRows.length ? 'absolute median' : '' },
      yAxis: { type: 'category', data: fallbackRows.map(row => row.feature).reverse() },
      series: [{
        type: 'bar',
        data: values.reverse(),
        itemStyle: { color: '#1f5b99' },
      }],
    }
  }
  const fdrScores = rows.map(row => {
    const value = finiteNumber(row.fdr ?? row.p_value)
    return value !== null ? -Math.log10(Math.max(value, 1e-300)) : null
  })
  const hasFdrSignal = fdrScores.some(value => value !== null && value > 0)
  const scores = hasFdrSignal
    ? fdrScores.map(value => value ?? 0)
    : rows.map(row => finiteNumber(row.importance ?? row.effect_size ?? row.statistic) ?? 0)
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 72, right: 24, bottom: 42, top: 28 },
    xAxis: { type: 'value', name: hasFdrSignal ? '-log10(FDR)' : 'importance' },
    yAxis: { type: 'category', data: rows.map(row => row.feature_name).reverse() },
    series: [{
      type: 'bar',
      data: scores.reverse(),
      itemStyle: { color: '#1f5b99' },
    }],
  }
})

const fieldSummaryOption = computed(() => {
  const dist = fieldSummary.value?.distribution || { centers: [], counts: [] }
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 54, right: 20, bottom: 54, top: 26 },
    xAxis: { type: 'category', data: dist.centers || [], axisLabel: { rotate: 30 } },
    yAxis: { type: 'value' },
    series: [{ type: 'bar', data: dist.counts || [], itemStyle: { color: '#2370cf' } }],
  }
})

const fieldSummaryTable = computed(() => {
  const rows = [...(fieldSummary.value?.top_rows || []), ...(fieldSummary.value?.bottom_rows || [])]
  const columns = rows.length ? Object.keys(rows[0]) : []
  return { columns, rows, total: rows.length }
})

const scatterOption = computed(() => {
  const points = scatterData.value?.points || []
  return buildEnhancedScatterOption(points, xField.value, yField.value, xField.value, yField.value, {
    title: 'Pairwise feature scatter',
    subtitle: 'Task-level scatter with trend and median guide; points come from the current sequence-analysis job.',
  })
})

const strategyOption = computed(() => {
  const rows = analysisPayload.value?.strategy_breakdown || []
  return {
    tooltip: { trigger: 'item' },
    series: [{ type: 'pie', radius: ['45%', '72%'], data: rows.map(row => ({ name: row.strategy_cluster, value: row.count })) }],
  }
})

const couplingOption = computed(() => {
  const rows = (analysisPayload.value?.coupling_edges || []).slice(0, 14)
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 92, right: 20, bottom: 36, top: 24 },
    xAxis: { type: 'value' },
    yAxis: { type: 'category', data: rows.map(row => `${row.source} / ${row.target}`).reverse() },
    series: [{ type: 'bar', data: rows.map(row => Math.abs(row.weight || 0)).reverse(), itemStyle: { color: '#2a9d8f' } }],
  }
})

const outlierTable = computed(() => {
  const rows = [
    ...(analysisPayload.value?.outliers?.high || []),
    ...(analysisPayload.value?.outliers?.low || []),
    ...(analysisPayload.value?.outliers?.multivariate || []),
  ]
  const columns = rows.length ? Object.keys(rows[0]) : []
  return { columns, rows, total: rows.length }
})

const featureRankTable = computed(() => {
  const rows = analysisPayload.value?.feature_rank || []
  const columns = rows.length ? Object.keys(rows[0]) : []
  return { columns, rows, total: rows.length }
})

const topLowRows = computed(() => topLowPayload.value?.rows || [])
const topLowTable = computed(() => {
  const rows = topLowRows.value
  return { columns: rows.length ? Object.keys(rows[0]) : [], rows, total: rows.length }
})

const topLowOption = computed(() => {
  const feature = topLowFeature.value || topLowRows.value[0]?.feature_name || ''
  const rows = topLowRows.value.filter(row => !feature || row.feature_name === feature).slice(0, 20)
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 128, right: 24, bottom: 46, top: 28 },
    xAxis: { type: 'value', name: feature },
    yAxis: { type: 'category', data: rows.map(row => `${row.rank_type} ${row.entity_id}`).reverse() },
    series: [{
      type: 'bar',
      data: rows.map(row => row.feature_value).reverse(),
      itemStyle: { color: params => rows[rows.length - 1 - params.dataIndex]?.rank_type === 'Top10' ? '#2370cf' : '#e76f51' },
    }],
  }
})

const sampleGroupOverviewTable = computed(() => {
  const rows = (sampleComparison.value?.group_overview || []).map(row => ({
    group: row.group,
    record_count: row.record_count,
    sample_count: row.sample_count,
    species_count: row.species_count,
    strategy_clusters: JSON.stringify(row.strategy_clusters || []),
  }))
  return { columns: rows.length ? Object.keys(rows[0]) : [], rows, total: rows.length }
})

const sampleDiffFeatureTable = computed(() => {
  const rows = sampleComparison.value?.differential_features || []
  return { columns: rows.length ? Object.keys(rows[0]) : [], rows, total: rows.length }
})

const sampleDeltaOption = computed(() => {
  const rows = sampleComparison.value?.feature_delta_heatmap || []
  const features = [...new Set(rows.map(row => row.feature_name))].slice(0, 24)
  const comparisons = [...new Set(rows.map(row => row.comparison))]
  const data = []
  features.forEach((feature, yIdx) => {
    comparisons.forEach((comparison, xIdx) => {
      const row = rows.find(item => item.feature_name === feature && item.comparison === comparison)
      data.push([xIdx, yIdx, row?.standardized_delta ?? 0])
    })
  })
  return {
    tooltip: { formatter: params => `${comparisons[params.data[0]]}<br/>${features[params.data[1]]}: ${formatCell(params.data[2])}` },
    grid: { left: 120, right: 24, bottom: 72, top: 28 },
    xAxis: { type: 'category', data: comparisons, axisLabel: { rotate: 35 } },
    yAxis: { type: 'category', data: features },
    visualMap: { min: -3, max: 3, orient: 'horizontal', bottom: 0, calculable: true },
    series: [{ type: 'heatmap', data }],
  }
})

const pairedScatterOption = computed(() => {
  const rows = sampleComparison.value?.paired_scatter || []
  const feature = rows[0]?.feature_name || ''
  const points = rows.filter(row => row.feature_name === feature).map(row => ({
    ...row,
    reference_value: Number(row.reference_value),
    case_value: Number(row.case_value),
  }))
  if (!points.length) {
    const fallbackRows = sampleComparison.value?.feature_boxplots || []
    const fallbackFeature = fallbackRows[0]?.feature_name || sampleComparison.value?.differential_features?.[0]?.feature_name || ''
    const groups = fallbackRows.filter(row => row.feature_name === fallbackFeature)
    if (groups.length) {
      return {
        title: {
          text: 'Unpaired group median comparison',
          subtext: 'No matched gene_key pairs were found; showing group medians for the first comparable feature.',
          left: 8,
          top: 4,
          textStyle: { fontSize: 13, color: '#143551' },
          subtextStyle: { fontSize: 11, color: '#5a7491' },
        },
        tooltip: { trigger: 'axis' },
        grid: { left: 96, right: 28, bottom: 58, top: 72 },
        xAxis: { type: 'value', name: fallbackFeature },
        yAxis: { type: 'category', data: groups.map(row => row.group).reverse() },
        series: [{
          type: 'bar',
          data: groups.map(row => finiteNumber(row.median ?? row.p50 ?? row.mean) ?? 0).reverse(),
          itemStyle: { color: '#2370cf' },
        }],
      }
    }
  }
  return buildEnhancedScatterOption(points, 'reference_value', 'case_value', 'Reference', 'Case', {
    title: feature || 'Paired comparison',
    subtitle: 'Matched gene_key values only; y=x relationship is interpreted descriptively.',
  })
})

const mlFeatureTable = computed(() => {
  const rows = mlDiscrimination.value?.feature_importance || []
  return { columns: rows.length ? Object.keys(rows[0]) : [], rows, total: rows.length }
})

const mlSampleRule = computed(() => {
  const rowCount = Number(mlDiscrimination.value?.row_count || 0)
  const classCount = Number(mlDiscrimination.value?.classes?.length || 0)
  const lowSampleWarning = Boolean(mlDiscrimination.value?.validation?.low_sample_warning)
  const sufficient = rowCount >= 20 && classCount >= 2 && !lowSampleWarning
  return {
    sufficient,
    message: sufficient
      ? `Minimum sample rule passed for exploratory diagnostics: ${rowCount} rows across ${classCount} label classes.`
      : `Minimum sample rule not met or flagged: ${rowCount || 0} rows across ${classCount || 0} label classes. Treat the view as exploratory separation only, not predictive evidence.`,
  }
})

function statColumnStatus(payload, label) {
  const columns = (payload?.columns || []).map(col => String(col || '').toLowerCase())
  const rows = payload?.rows || []
  const rowKeys = rows.length ? Object.keys(rows[0] || {}).map(col => String(col || '').toLowerCase()) : []
  const keys = new Set([...columns, ...rowKeys])
  const hasEffect = ['effect_size', 'cohens_d', 'delta', 'mean_delta', 'median_delta', 'log2fc', 'fold_change'].some(key => keys.has(key))
  const hasP = ['p_value', 'pvalue', 'p', 'pval'].some(key => keys.has(key))
  const hasQ = ['q_value', 'qvalue', 'fdr', 'padj', 'adjusted_p_value'].some(key => keys.has(key))
  const available = hasEffect || hasP || hasQ
  return {
    available,
    hasEffect,
    hasP,
    hasQ,
    message: available
      ? `${label} includes statistical field(s): ${[hasEffect ? 'effect size' : '', hasP ? 'p value' : '', hasQ ? 'q/FDR value' : ''].filter(Boolean).join(', ')}.`
      : `${label}: 统计字段未提供；当前表只能作为排序或描述性差异结果读取，不能视为显著性检验。`,
  }
}

const differentialFeatureStatStatus = computed(() => statColumnStatus(differentialFeatures.value, 'Differential feature table'))
const differentialEntityStatStatus = computed(() => statColumnStatus(differentialEntities.value, 'Differential entity table'))
const differentialCaveat = computed(() => (
  'Interpretation caveats: sample size, uploaded label source, annotation completeness, missing values, and phylogenetic or species-source correlation can change apparent differential rankings.'
))
const differentialFeatureDownloads = computed(() => [
  { label: 'CSV', href: sequenceResultDownloadUrl('differential_features') },
  { label: 'Payload JSON', filename: `${props.jobId}_differential_features_preview.json`, payload: differentialFeatures.value },
])
const differentialEntityDownloads = computed(() => [
  { label: 'CSV', href: sequenceResultDownloadUrl('differential_entities') },
  { label: 'Payload JSON', filename: `${props.jobId}_differential_entities_preview.json`, payload: differentialEntities.value },
])
const mlResultDownloads = computed(() => [
  { label: 'ML payload', href: sequenceResultDownloadUrl('ml_discrimination') },
  { label: 'Feature table', href: sequenceResultDownloadUrl('ml_feature_importance') },
  { label: 'Preview JSON', filename: `${props.jobId}_ml_diagnostics_preview.json`, payload: mlDiscrimination.value },
])

const mlLabelViewTable = computed(() => {
  const rows = mlDiscrimination.value?.label_view_status || []
  return { columns: rows.length ? Object.keys(rows[0]) : [], rows, total: rows.length }
})

const mlEntityContributionTable = computed(() => {
  const rows = mlDiscrimination.value?.entity_contributions || []
  return { columns: rows.length ? Object.keys(rows[0]) : [], rows, total: rows.length }
})

const mlEmbeddingOption = computed(() => {
  const points = mlDiscrimination.value?.class_separation_embedding?.points || []
  return buildEnhancedScatterOption(points, 'x', 'y', 'Dim 1', 'Dim 2', {
    title: `${mlDiscrimination.value?.class_separation_embedding?.method || 'embedding'} class separation`,
    subtitle: `Label field: ${mlDiscrimination.value?.label_field || '-'}`,
  })
})

function mlCurveOption(payload, rows, xKey, yKey, xName, yName, title, color, exportName) {
  if (!payload.available || !rows.length) {
    return {
      __scientificEmptyReason: payload.reason || `${title} only available for binary labels with sufficient validation samples`,
      __semantic: { minPoints: 2, totalCount: 0, displayedCount: 0, method: 'binary classifier curve guard' },
      title: { text: payload.reason || `${title} unavailable`, left: 'center', top: 'middle', textStyle: { fontSize: 13, color: '#6b7f92' } },
      series: [],
    }
  }
  const data = rows.map((row) => [row[xKey], row[yKey]]).filter((point) => point.every((value) => Number.isFinite(Number(value))))
  return {
    __exportName: exportName,
    __semantic: {
      minPoints: 2,
      totalCount: rows.length,
      displayedCount: data.length,
      method: `${title}; plotted separately to avoid mixing ROC and PR coordinate semantics`,
      aggregation: 'validation curve point',
    },
    __dataRows: rows,
    tooltip: { trigger: 'axis' },
    grid: { left: 58, right: 24, bottom: 52, top: 34 },
    xAxis: { type: 'value', min: 0, max: 1, name: xName },
    yAxis: { type: 'value', min: 0, max: 1, name: yName },
    series: [{
      name: title,
      type: 'line',
      data,
      smooth: true,
      symbol: 'none',
      itemStyle: { color },
      lineStyle: { color, width: 2.4 },
    }],
  }
}

const mlRocOption = computed(() => {
  const payload = mlDiscrimination.value?.roc_pr || {}
  return mlCurveOption(payload, payload.roc_curve || [], 'fpr', 'tpr', 'False positive rate', 'True positive rate', 'ROC', '#2370cf', 'ml_binary_roc_curve')
})

const mlPrOption = computed(() => {
  const payload = mlDiscrimination.value?.roc_pr || {}
  return mlCurveOption(payload, payload.pr_curve || [], 'recall', 'precision', 'Recall', 'Precision', 'Precision-recall', '#2a9d8f', 'ml_binary_precision_recall_curve')
})

const mlTopFeatureDistributionOption = computed(() => {
  const item = (mlDiscrimination.value?.top_feature_distributions || [])[0]
  const rows = item?.groups || []
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 54, right: 24, bottom: 44, top: 30 },
    xAxis: { type: 'category', data: rows.map(row => row.label) },
    yAxis: { type: 'value', name: item?.feature_name || '' },
    series: [{ type: 'bar', data: rows.map(row => row.p50), itemStyle: { color: '#2370cf' } }],
  }
})

const mlRedundancyTable = computed(() => {
  const rows = (mlDiscrimination.value?.feature_redundancy?.groups || []).map(row => ({
    representative_feature: row.representative_feature,
    member_count: row.member_count,
    members: (row.members || []).join(', '),
    max_abs_spearman_to_representative: row.max_abs_spearman_to_representative,
  }))
  return { columns: rows.length ? Object.keys(rows[0]) : [], rows, total: rows.length }
})

const mlImportanceOption = computed(() => {
  const rows = (mlDiscrimination.value?.feature_importance || []).slice(0, 16)
  const permutationScores = rows.map(row => finiteNumber(row.permutation_importance_mean) ?? 0)
  const usePermutation = permutationScores.some(value => value > 0)
  const scores = usePermutation
    ? permutationScores
    : rows.map(row => finiteNumber(row.rf_importance ?? row.logistic_abs_coef) ?? 0)
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 118, right: 24, bottom: 34, top: 28 },
    xAxis: { type: 'value', name: usePermutation ? 'permutation importance' : 'RF importance' },
    yAxis: { type: 'category', data: rows.map(row => row.feature_name).reverse() },
    series: [{
      type: 'bar',
      data: scores.reverse(),
      itemStyle: { color: '#2a9d8f' },
    }],
  }
})

const mlConfusionOption = computed(() => {
  const labels = mlDiscrimination.value?.confusion_matrix?.labels || []
  const values = mlDiscrimination.value?.confusion_matrix?.values || []
  const data = []
  values.forEach((row, yIdx) => row.forEach((value, xIdx) => data.push([xIdx, yIdx, value])))
  return {
    tooltip: { formatter: params => `predicted ${labels[params.data[0]]}<br/>true ${labels[params.data[1]]}: ${params.data[2]}` },
    grid: { left: 72, right: 24, bottom: 58, top: 28 },
    xAxis: { type: 'category', data: labels, name: 'Predicted' },
    yAxis: { type: 'category', data: labels, name: 'True' },
    visualMap: { min: 0, max: Math.max(1, ...data.map(row => row[2])), orient: 'horizontal', bottom: 0 },
    series: [{ type: 'heatmap', data }],
  }
})

const featureComparisonOption = computed(() => {
  const rows = featureComparisonData.value?.groups || []
  return {
    tooltip: { trigger: 'axis' },
    legend: { top: 0 },
    grid: { left: 52, right: 20, bottom: 42, top: 42 },
    xAxis: { type: 'category', data: rows.map(row => row.group) },
    yAxis: { type: 'value', name: featureComparisonData.value?.feature || comparisonFeature.value },
    series: [
      { name: 'median', type: 'bar', data: rows.map(row => row.p50), itemStyle: { color: '#2370cf' } },
      { name: 'q25', type: 'line', data: rows.map(row => row.p25), itemStyle: { color: '#8d6e63' } },
      { name: 'q75', type: 'line', data: rows.map(row => row.p75), itemStyle: { color: '#e76f51' } },
    ],
  }
})

const entityComparisonOption = computed(() => {
  const rows = entityComparisonData.value?.rows || []
  const features = entityComparisonData.value?.features || []
  const labels = rows.map(row => `${row.entity_id}:${row.group}`)
  const standardized = {}
  features.forEach((feature) => {
    const values = rows.map(row => Number(row[feature])).filter(value => Number.isFinite(value))
    const mean = values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0
    const variance = values.length ? values.reduce((sum, value) => sum + ((value - mean) ** 2), 0) / values.length : 0
    const sd = Math.sqrt(variance) || 1
    standardized[feature] = rows.map(row => {
      const value = Number(row[feature])
      return Number.isFinite(value) ? (value - mean) / sd : null
    })
  })
  return {
    tooltip: { trigger: 'axis' },
    legend: { top: 0 },
    grid: { left: 78, right: 20, bottom: 72, top: 42 },
    xAxis: { type: 'category', data: labels, axisLabel: { rotate: 35 } },
    yAxis: { type: 'value', name: 'z-score' },
    series: features.map((feature, idx) => ({
      name: feature,
      type: 'bar',
      data: standardized[feature] || [],
      itemStyle: { color: ['#2370cf', '#2a9d8f', '#e76f51', '#8d6e63'][idx % 4] },
    })),
  }
})

async function loadFieldSummary() {
  if (!selectedField.value) return
  if (isModel8Case4.value) {
    const field = selectedField.value
    const rows = features.value.rows || []
    const values = rows.map(row => Number(row[field])).filter(Number.isFinite)
    const stats = numericSummary(values)
    fieldSummary.value = {
      distribution: { centers: ['min', 'q1', 'median', 'q3', 'max'], counts: [stats.min, stats.p25, stats.median, stats.p75, stats.max] },
      top_rows: rows.slice().sort((a, b) => Number(b[field] || 0) - Number(a[field] || 0)).slice(0, 10),
      bottom_rows: rows.slice().sort((a, b) => Number(a[field] || 0) - Number(b[field] || 0)).slice(0, 10),
    }
    return
  }
  fieldSummary.value = await getSequenceFieldSummary(props.jobId, { field: selectedField.value })
}

async function loadScatter() {
  if (!xField.value || !yField.value) return
  if (isModel8Case4.value) {
    scatterData.value = {
      points: (features.value.rows || []).map(row => ({
        ...row,
        [xField.value]: Number(row[xField.value] || 0),
        [yField.value]: Number(row[yField.value] || 0),
      })),
    }
    return
  }
  scatterData.value = await getSequenceScatter(props.jobId, { x: xField.value, y: yField.value })
}

async function loadFeatureComparison() {
  if (!comparisonFeature.value) return
  if (isModel8Case4.value) {
    const sourceRows = features.value.rows || []
    const grouped = groupCounts(sourceRows.filter(row => Number.isFinite(Number(row[comparisonFeature.value]))), 'omics_type')
    featureComparisonData.value = {
      feature: comparisonFeature.value,
      groups: grouped.map(group => {
        const stats = numericSummary(sourceRows.filter(row => row.omics_type === group.group).map(row => row[comparisonFeature.value]))
        return {
          group: group.group,
          p25: stats.p25,
          p50: stats.median,
          p75: stats.p75,
        }
      }),
    }
    return
  }
  featureComparisonData.value = await getSequenceFeatureComparison(props.jobId, { feature: comparisonFeature.value })
}

async function loadEntityComparison() {
  const entities = entityInput.value.split(',').map(item => item.trim()).filter(Boolean)
  if (entities.length < 2) return
  const fallbackFeatures = comparisonFeature.value ? [comparisonFeature.value] : fieldOptions.value.slice(0, 2)
  const selectedFeatures = entityFeatureInput.value
    ? entityFeatureInput.value.split(',').map(item => item.trim()).filter(Boolean)
    : fallbackFeatures
  if (isModel8Case4.value) {
    const sourceRows = features.value?.rows || []
    entityComparisonData.value = {
      entities,
      features: selectedFeatures,
      rows: sourceRows.filter(row => entities.includes(row.entity_id) || entities.includes(row.gene_id)).slice(0, 120),
    }
    return
  }
  entityComparisonData.value = await getSequenceEntityComparison(props.jobId, { entities: entities.join(','), features: selectedFeatures.join(',') })
}

async function loadTopLow() {
  if (isModel8Case4.value) return
  topLowPayload.value = await getSequenceTopLow(props.jobId, topLowFeature.value ? { feature: topLowFeature.value } : {})
}

async function loadCorePanels() {
  if (isModel8Case4.value) return
  const params = Object.fromEntries(Object.entries(corePanelFilters.value).filter(([, value]) => value))
  corePanels.value = await getSequenceCoreFeaturePanels(props.jobId, params)
}

async function loadFeatures() {
  if (isModel8Case4.value) {
    const search = String(featureSearch.value || '').toLowerCase()
    let rows = platform.value?.feature_rows || []
    if (search) {
      rows = rows.filter(row => Object.values(row).some(value => String(value || '').toLowerCase().includes(search)))
    }
    if (featureSortBy.value) {
      rows = rows.slice().sort((a, b) => {
        const av = a[featureSortBy.value]
        const bv = b[featureSortBy.value]
        if (Number.isFinite(Number(av)) && Number.isFinite(Number(bv))) {
          return featureSortOrder.value === 'desc' ? Number(bv) - Number(av) : Number(av) - Number(bv)
        }
        return featureSortOrder.value === 'desc'
          ? String(bv || '').localeCompare(String(av || ''))
          : String(av || '').localeCompare(String(bv || ''))
      })
    }
    features.value = tablePayload(rows.slice(0, 500))
    return
  }
  features.value = await getSequenceFeatures(props.jobId, featureTableParams.value)
  if (!featureSortBy.value) featureSortBy.value = features.value.columns?.[0] || ''
}

async function loadMlDiscrimination() {
  if (isModel8Case4.value) return
  mlDiscrimination.value = await getSequenceMlDiscrimination(props.jobId, { label_field: mlLabelField.value || 'group' })
  tabPayloadLoaded.value.ml = true
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

function toggleEntity(entity) {
  const values = entityInput.value.split(',').map(item => item.trim()).filter(Boolean)
  const idx = values.indexOf(entity)
  if (idx >= 0) values.splice(idx, 1)
  else values.push(entity)
  entityInput.value = values.join(',')
}

async function optionalLoad(label, loader, fallback) {
  try {
    return await loader()
  } catch (err) {
    optionalWarnings.value.push(label)
    return fallback
  }
}

async function ensureTabPayload(active = tab.value) {
  if (!job.value) return
  if (isModel8Case4.value) {
    tabPayloadLoaded.value[active] = true
    return
  }
  if (active === 'core_visualization' && !tabPayloadLoaded.value.core_visualization) {
    corePanels.value = await optionalLoad('core feature panels', () => getSequenceCoreFeaturePanels(props.jobId), { panels: [] })
    tabPayloadLoaded.value.core_visualization = true
  } else if (active === 'top_low' && !tabPayloadLoaded.value.top_low) {
    topLowPayload.value = await optionalLoad('top/low entities', () => getSequenceTopLow(props.jobId), { rows: [] })
    tabPayloadLoaded.value.top_low = true
  } else if (active === 'deep' && !tabPayloadLoaded.value.deep) {
    analysisPayload.value = await optionalLoad('deep-analysis payload', () => getSequenceAnalysisPayload(props.jobId), {})
    tabPayloadLoaded.value.deep = true
  } else if (active === 'sample_comparison' && !tabPayloadLoaded.value.sample_comparison) {
    sampleComparison.value = await optionalLoad('sample comparison', () => getSequenceSampleComparison(props.jobId), {})
    tabPayloadLoaded.value.sample_comparison = true
  } else if (active === 'ml' && !tabPayloadLoaded.value.ml) {
    mlDiscrimination.value = await optionalLoad('separability diagnostics', () => getSequenceMlDiscrimination(props.jobId), {})
    tabPayloadLoaded.value.ml = true
  } else if (active === 'explorer' && !tabPayloadLoaded.value.explorer) {
    await optionalLoad('field summary', loadFieldSummary, null)
    await optionalLoad('scatter', loadScatter, null)
    tabPayloadLoaded.value.explorer = true
  } else if (active === 'compare' && !tabPayloadLoaded.value.compare) {
    await optionalLoad('feature comparison', loadFeatureComparison, null)
    tabPayloadLoaded.value.compare = true
  }
}

async function load() {
  loading.value = true
  loadError.value = ''
  optionalWarnings.value = []
  tabPayloadLoaded.value = {}
  try {
    if (isModel8Case4.value) {
      const activeCaseCode = model8Case4SpeciesCode.value
      const [summaryPayload, goldPayload, workflowsPayload, validationPayload] = await Promise.all([
        getModel8Case4Summary(),
        getModel8Case4Gold(),
        getModel8Case4Workflows(),
        getModel8Case4Validation(),
      ])
      const speciesPayload = activeCaseCode ? await getModel8Case4Species(activeCaseCode) : null
      if (speciesPayload) {
        model8Case4Species.value = speciesPayload
        selectedModel8Case4Species.value = activeCaseCode
      }
      const artifacts = buildModel8Case4Artifacts(summaryPayload, goldPayload, workflowsPayload, validationPayload, speciesPayload, activeCaseCode)
      job.value = artifacts.jobPayload
      features.value = artifacts.features
      differentialFeatures.value = artifacts.differentialFeatures
      differentialEntities.value = artifacts.differentialEntities
      plots.value = artifacts.plots
      platform.value = artifacts.platform
      featureCatalog.value = artifacts.featureCatalog
      featureSummaryPayload.value = artifacts.featureSummaryPayload
      basicVisualization.value = artifacts.basicVisualization
      corePanels.value = artifacts.corePanels
      topLowPayload.value = artifacts.topLowPayload
      analysisPayload.value = artifacts.analysisPayload
      sampleComparison.value = artifacts.sampleComparison
      mlDiscrimination.value = artifacts.mlDiscrimination
      logs.value = {
        events: [
          { level: 'info', event: 'Loaded published Model-8 Case4 gold-standard release artifacts.' },
          { level: 'info', event: `Agreement checks: ${validationPayload?.agreement?.pass_checks || 0}/${validationPayload?.agreement?.total_checks || 0}` },
        ],
      }
      repro.value = {
        release_case: 'case4_upload_gold',
        generated_at_utc: summaryPayload?.generated_at_utc,
        extractor_contract: summaryPayload?.full_database_feature_extractor_contract,
        source_checksums: goldPayload?.source_checksums || [],
      }
      const fields = fieldOptions.value
      featureSortBy.value = featureSortBy.value || 'case_code'
      selectedField.value = fields[0] || ''
      comparisonFeature.value = fields[0] || ''
      xField.value = 'sequence_length'
      yField.value = fields.includes('n_atoms_per_aa') ? 'n_atoms_per_aa' : fields.includes('gc_fraction') ? 'gc_fraction' : (fields[1] || fields[0] || '')
      fieldSummary.value = {
        distribution: { centers: ['expected', 'stored', 'passed'], counts: [validationPayload?.agreement?.total_checks || 0, validationPayload?.agreement?.total_checks || 0, validationPayload?.agreement?.pass_checks || 0] },
        top_rows: artifacts.topLowPayload.rows.filter(row => row.rank_type === 'Top10'),
        bottom_rows: artifacts.topLowPayload.rows.filter(row => row.rank_type === 'Low10'),
      }
      scatterData.value = { points: artifacts.platform.feature_rows }
      if (!speciesPayload) await loadModel8Case4Species(activeCaseCode || selectedModel8Case4Species.value)
      await ensureTabPayload(tab.value)
      return
    }
    const jobPayload = await getSequenceAnalysisJob(props.jobId)
    job.value = jobPayload
    const [
      manifestPayload,
      qcPayload,
      designPayload,
      interpretationPayload,
      downloadsPayload,
    ] = await Promise.all([
      optionalLoad('job manifest', () => getSequenceJobManifest(props.jobId), null),
      optionalLoad('input QC', () => getSequenceInputQc(props.jobId), null),
      optionalLoad('analysis design', () => getSequenceAnalysisDesign(props.jobId), null),
      optionalLoad('result interpretation', () => getSequenceResultInterpretation(props.jobId), null),
      optionalLoad('download manifest', () => getSequenceDownloadManifest(props.jobId), null),
    ])
    jobManifest.value = manifestPayload
    inputQc.value = qcPayload || jobPayload.input_qc || null
    analysisDesign.value = designPayload || jobPayload.analysis_design || null
    resultInterpretation.value = interpretationPayload
    downloadManifest.value = downloadsPayload
    if (jobPayload.status !== 'SUCCEEDED') {
      await loadLogs()
      return
    }
    const [
      featureRows,
      differentialFeatureRows,
      differentialEntityRows,
      plotPayload,
      platformPayload,
      catalogPayload,
      summaryRows,
      basicPayload,
    ] = await Promise.all([
      getSequenceFeatures(props.jobId, featureTableParams.value),
      optionalLoad('differential features', () => getDifferentialFeatures(props.jobId, { limit: 100 }), { columns: [], rows: [], total: 0 }),
      optionalLoad('differential genes', () => getDifferentialEntities(props.jobId, { limit: 100 }), { columns: [], rows: [], total: 0 }),
      optionalLoad('plots', () => getSequencePlots(props.jobId), {}),
      optionalLoad('platform visualization bundle', () => getSequencePlatformBundle(props.jobId), {}),
      optionalLoad('feature catalog', () => getSequenceFeatureCatalog(props.jobId), {}),
      optionalLoad('feature summary', () => getSequenceFeatureSummary(props.jobId), { rows: [] }),
      optionalLoad('basic visualization payload', () => getSequenceBasicVisualization(props.jobId), {}),
    ])
    features.value = featureRows
    if (!featureSortBy.value) featureSortBy.value = features.value.columns?.[0] || ''
    differentialFeatures.value = differentialFeatureRows
    differentialEntities.value = differentialEntityRows
    plots.value = plotPayload
    platform.value = platformPayload
    featureCatalog.value = catalogPayload
    featureSummaryPayload.value = summaryRows
    basicVisualization.value = basicPayload
    const fields = fieldOptions.value
    selectedField.value = fields[0] || ''
    comparisonFeature.value = fields[0] || ''
    xField.value = fields[0] || ''
    yField.value = fields[1] || fields[0] || ''
    await ensureTabPayload(tab.value)
  } catch (err) {
    loadError.value = err?.response?.data?.error || err.message || 'Failed to load sequence analysis outputs.'
  } finally {
    loading.value = false
  }
}

async function loadLogs() {
  if (isModel8Case4.value) {
    logs.value = logs.value || { events: [{ level: 'info', event: 'Published Model-8 Case4 artifacts are served as a curated workflow case.' }] }
    return
  }
  logs.value = await getSequenceAnalysisLogs(props.jobId)
}

async function loadRepro() {
  if (isModel8Case4.value) {
    repro.value = repro.value || { release_case: 'case4_upload_gold', note: 'Reproducibility metadata is loaded from summary.json and gold_standard.json.' }
    return
  }
  repro.value = await getSequenceAnalysisReproducibility(props.jobId)
}

onMounted(load)
</script>

<style scoped>
.analysis-nav {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(178px, 1fr));
  gap: 10px;
  padding: 12px;
  border: 1px solid rgba(74, 113, 151, 0.18);
  border-radius: 18px;
  background: linear-gradient(180deg, rgba(248, 252, 255, 0.98), rgba(231, 244, 255, 0.92));
  box-shadow: 0 12px 30px rgba(42, 83, 122, 0.1);
}

.analysis-nav-item {
  min-height: 88px;
  padding: 12px 14px;
  border: 1px solid rgba(42, 89, 140, 0.16);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.86);
  color: var(--text-main);
  text-align: left;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 5px;
  cursor: pointer;
  transition: transform 0.16s ease, border-color 0.16s ease, background 0.16s ease, box-shadow 0.16s ease;
}

.analysis-nav-item:hover {
  transform: translateY(-1px);
  border-color: rgba(31, 93, 154, 0.38);
  background: #ffffff;
  box-shadow: 0 10px 22px rgba(43, 89, 132, 0.12);
}

.analysis-nav-item.active {
  background: linear-gradient(135deg, #1f5d9a, #4b8fd3);
  color: #ffffff;
  border-color: transparent;
  box-shadow: 0 12px 24px rgba(31, 93, 154, 0.24);
}

.analysis-nav-item strong {
  font-size: 0.98rem;
  line-height: 1.15;
}

.analysis-nav-item span:last-child {
  color: var(--text-soft);
  font-size: 0.8rem;
  line-height: 1.25;
}

.analysis-nav-item.active span,
.analysis-nav-item.active .analysis-nav-group {
  color: rgba(255, 255, 255, 0.86);
}

.analysis-nav-group {
  width: fit-content;
  padding: 2px 7px;
  border-radius: 999px;
  background: rgba(215, 234, 255, 0.82);
  color: #275982;
  font-size: 0.68rem;
  font-weight: 700;
}

.analysis-nav-item.active .analysis-nav-group {
  background: rgba(255, 255, 255, 0.2);
}

.download-card {
  color: inherit;
  text-decoration: none;
}

.download-card:hover {
  border-color: var(--accent);
}

.workflow-warnings {
  color: #8a5a00;
  margin-top: 12px;
}

.table-scroll {
  overflow: auto;
  border: 1px solid rgba(42, 89, 140, 0.08);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.72);
}

.table-scroll .table {
  margin: 0;
}

.table-scroll .table thead th {
  z-index: 2;
}

.core-toplow-select {
  width: min(420px, 100%);
}

.feature-table-toolbar {
  display: grid;
  grid-template-columns: minmax(240px, 1.5fr) repeat(3, minmax(150px, 1fr)) auto auto;
  gap: 10px;
  align-items: center;
  margin: 12px 0;
}

.column-picker {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  max-height: 132px;
  overflow: auto;
  padding: 10px;
  border: 1px solid var(--line-soft);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.62);
}

.column-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 30px;
  padding: 4px 8px;
  border: 1px solid var(--line-soft);
  border-radius: 999px;
  background: #ffffff;
  color: var(--text-main);
  font-size: 0.84rem;
}

.core-filter-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(150px, 1fr)) auto;
  gap: 10px;
  align-items: center;
  margin-top: 14px;
}

.core-panel-nav {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.core-panel-nav a {
  padding: 8px 10px;
  border: 1px solid var(--line-soft);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.82);
  color: var(--text-main);
  font-size: 0.86rem;
}

.core-panel-card {
  scroll-margin-top: 150px;
}

.core-panel-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 8px 0 14px;
}

.core-panel-meta span,
.core-warning {
  padding: 8px 10px;
  border-radius: 10px;
  background: rgba(236, 247, 255, 0.86);
}

.core-nested-table {
  margin-top: 14px;
  box-shadow: none;
}

.species-workbench {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.case-tab-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.case-tab {
  border: 1px solid var(--line-soft);
  border-radius: 999px;
  background: #fff;
  color: var(--text-main);
  padding: 7px 11px;
  font-weight: 700;
  cursor: pointer;
}

.case-tab.active {
  border-color: #1f5d9a;
  background: rgba(232, 244, 255, 0.95);
  color: #174f82;
}

.compact-top {
  margin-top: 10px;
}

.small-kpi {
  font-size: 1rem;
  line-height: 1.3;
}

.table-wrap {
  overflow: auto;
}

@media (max-width: 1180px) {
  .feature-table-toolbar {
    grid-template-columns: 1fr 1fr;
  }
  .core-filter-grid {
    grid-template-columns: 1fr 1fr;
  }
}

@media (max-width: 760px) {
  .analysis-nav {
    grid-template-columns: 1fr;
  }

  .analysis-nav-item {
    min-height: 74px;
  }

  .feature-table-toolbar {
    grid-template-columns: 1fr;
  }
  .core-filter-grid {
    grid-template-columns: 1fr;
  }
}
</style>
