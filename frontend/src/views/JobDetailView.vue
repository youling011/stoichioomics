<template>
  <div v-if="job">
    <div class="card">
      <div class="row" style="justify-content:space-between">
        <div>
          <h1>{{ job.name || job.job_id }}</h1>
          <p class="muted">{{ job.job_id }} / {{ job.status }}</p>
        </div>
        <div class="row">
          <button class="btn secondary" @click="load">Refresh</button>
          <button class="btn secondary" @click="cancel" :disabled="!canCancel">Cancel</button>
          <router-link class="btn" v-if="job.status === 'SUCCEEDED'" :to="`/hvg/${job.job_id}`">Open Expression/HVG case</router-link>
        </div>
      </div>
    </div>

    <div class="card">
      <h3>Research workflow contract</h3>
      <table class="table">
        <tbody>
          <tr><td>Workflow module</td><td>{{ job.metadata_json?.workflow_module || job.module_name }}</td></tr>
          <tr><td>Run objective</td><td>{{ job.metadata_json?.run_objective || '-' }}</td></tr>
          <tr><td>Research question</td><td>{{ job.metadata_json?.research_question || '-' }}</td></tr>
          <tr><td>Dataset context</td><td>{{ job.metadata_json?.dataset_context || '-' }}</td></tr>
          <tr><td>Species / omics</td><td>{{ job.metadata_json?.species_id || '-' }} / {{ job.metadata_json?.omics_type || 'transcriptome' }}</td></tr>
          <tr><td>Sequence feature job</td><td>{{ job.metadata_json?.sequence_feature_job_id || '-' }}</td></tr>
          <tr><td>Stoich feature strategy</td><td>{{ job.metadata_json?.stoich_feature_strategy || 'user upload or registry lookup' }}</td></tr>
          <tr><td>Contract directory</td><td>{{ job.workspace_path }}/workflow_contracts</td></tr>
        </tbody>
      </table>
      <p class="muted">
        The backend writes job_manifest.json, input_qc.json, analysis_design.json,
        result_interpretation.json, download_manifest.json, and reproducibility_manifest.json
        as the job moves through upload, auto-detection, preflight, run, and registry promotion.
      </p>
    </div>

    <div class="grid grid-2">
      <div class="card">
        <h3>1. Upload files</h3>
        <p class="muted">Files are stored inside this job workspace only. Allowed inputs include CSV/TSV/TXT/JSON/YAML/H5AD/MTX/FASTA/GFF/GTF archives; each file is size-limited and checksum-tracked.</p>
        <input type="file" multiple @change="handleFiles" />
        <button class="btn" style="margin-top:12px" @click="upload" :disabled="!files.length">Upload</button>
        <ul>
          <li v-for="f in job.files" :key="f.id">{{ f.file_name }} <span class="muted">({{ f.relative_path }})</span></li>
        </ul>
      </div>
      <div class="card">
        <h3>2. Auto-detect and confirm</h3>
        <div class="label">Run profile</div>
        <select v-model="profile">
          <option value="quick_exploratory">quick_exploratory</option>
          <option value="standard_guided">standard_guided</option>
          <option value="publication_grade">publication_grade</option>
        </select>
        <button class="btn" style="margin-top:12px" @click="autoconfigure" :disabled="!job.files?.length">Auto-detect files</button>
        <div v-if="autoConfig" style="margin-top:14px">
          <h4>Recommended run plan</h4>
          <table class="table">
            <tbody>
              <tr><td>Expression</td><td>{{ autoConfig.recommended_run_plan?.expression_matrix?.status || '-' }} / {{ autoConfig.recommended_run_plan?.expression_matrix?.detected_format || '-' }}</td></tr>
              <tr><td>Metadata</td><td>{{ autoConfig.recommended_run_plan?.metadata?.status || '-' }} / {{ (autoConfig.recommended_run_plan?.metadata?.detected_fields || []).join(', ') || 'none' }}</td></tr>
              <tr><td>Stoich source</td><td>{{ autoConfig.recommended_run_plan?.stoich_registry_resolution?.status || '-' }} / {{ autoConfig.recommended_run_plan?.stoich_registry_resolution?.source || '-' }}</td></tr>
              <tr><td>Stoich file</td><td>{{ autoConfig.recommended_run_plan?.stoich_registry_resolution?.file || autoConfig.recommended_run_plan?.stoich_features?.source_file || '-' }}</td></tr>
              <tr><td>Phase 1</td><td>{{ autoConfig.recommended_run_plan?.phase1?.will_run }} / {{ autoConfig.recommended_run_plan?.phase1?.primary_mode }}</td></tr>
              <tr><td>Phase 2</td><td>{{ autoConfig.recommended_run_plan?.phase2?.will_run }} / {{ autoConfig.recommended_run_plan?.phase2?.model_type || '-' }}</td></tr>
              <tr><td>Ready</td><td>{{ autoConfig.ready_to_run }}</td></tr>
            </tbody>
          </table>
          <div v-if="autoConfig.recommended_run_plan?.stoich_registry_resolution?.sequence_upload_required" class="notice">
            <strong>Sequence-derived features required.</strong>
            <span>{{ autoConfig.recommended_run_plan?.stoich_registry_resolution?.message }}</span>
            <router-link class="btn secondary" to="/sequence-analysis">Open sequence upload</router-link>
          </div>
          <div v-if="autoConfig.warnings?.length">
            <h4>Warnings and skipped items</h4>
            <ul>
              <li v-for="(w, idx) in autoConfig.warnings" :key="idx">[{{ w.severity }}] {{ w.code }} - {{ w.message }}</li>
            </ul>
          </div>
          <details>
            <summary>Show auto-detect report</summary>
            <pre>{{ JSON.stringify(autoConfig.auto_detect_report, null, 2) }}</pre>
          </details>
        </div>
      </div>
      <div class="card">
        <h3>Manual advanced configuration</h3>
        <div class="label">Pipeline type</div>
        <select v-model="pipelineType"><option value="full">full</option><option value="preanalysis">preanalysis</option></select>
        <div class="label" style="margin-top:10px">Input mode</div>
        <select v-model="inputMode">
          <option value="h5ad">h5ad</option>
          <option value="h5ad_multi">h5ad_multi</option>
          <option value="tenx">tenx</option>
          <option value="tenx_multi">tenx_multi</option>
          <option value="matrix_csv">matrix_csv</option>
        </select>
        <div class="label" style="margin-top:10px">Expression config (JSON)</div>
        <textarea rows="10" v-model="expressionJson"></textarea>
        <div class="label" style="margin-top:10px">Metadata file (optional)</div>
        <input class="input" v-model="metadataFile" placeholder="metadata.csv" />
        <div class="label" style="margin-top:10px">Stoich config (JSON)</div>
        <textarea rows="6" v-model="stoichJson"></textarea>
        <div class="label" style="margin-top:10px">Expression/HVG analysis overrides (JSON)</div>
        <textarea rows="10" v-model="analysisJson"></textarea>
        <button class="btn" style="margin-top:12px" @click="configure">Save config</button>
      </div>
    </div>

    <div class="card">
      <h3>3. Run analysis</h3>
      <p class="muted">Config path: {{ job.config_path || '-' }}</p>
      <p class="muted">Runs are submitted to the in-process background executor. Logs, checksums, parameters, software versions, and code revision are written to the job workspace for reproducibility.</p>
      <div class="row">
        <button class="btn secondary" @click="preflight" :disabled="!job.config_path">Preflight</button>
        <button class="btn" @click="run" :disabled="!job.config_path">Run</button>
        <button class="btn secondary" @click="loadLogs">Logs</button>
        <button class="btn secondary" @click="loadRepro">Reproducibility</button>
      </div>
      <pre v-if="preflightResult">{{ JSON.stringify(preflightResult, null, 2) }}</pre>
      <pre v-if="job.error_message">{{ job.error_message }}</pre>
    </div>

    <div class="grid grid-2">
      <div class="card">
        <h3>Task log</h3>
        <p class="muted">{{ logs?.log_path || 'No log loaded.' }}</p>
        <pre v-if="logs">{{ JSON.stringify(logs.events || [], null, 2) }}</pre>
      </div>
      <div class="card">
        <h3>Reproducibility manifest</h3>
        <p class="muted">{{ job.reproducibility_path || 'Generated after configuration.' }}</p>
        <pre v-if="repro">{{ JSON.stringify(repro, null, 2) }}</pre>
      </div>
    </div>
  </div>
</template>
<script setup>
import { computed, ref, onMounted } from 'vue'
import { getJob, uploadJobFiles, configureJob, autoconfigureJob, preflightJob, runJob, cancelJob, getJobLogs, getJobReproducibility } from '../api/jobs'
const props = defineProps({ jobId: String })
const job = ref(null)
const files = ref([])
const preflightResult = ref(null)
const autoConfig = ref(null)
const logs = ref(null)
const repro = ref(null)
const profile = ref('standard_guided')
const pipelineType = ref('full')
const inputMode = ref('h5ad')
const metadataFile = ref('')
const expressionJson = ref(JSON.stringify({ file: 'expression.h5ad', value_semantics: 'raw_counts' }, null, 2))
const stoichJson = ref(JSON.stringify({ file: 'stoich_features.csv', require: false }, null, 2))
const analysisJson = ref(JSON.stringify({
  phase1_analysis: {
    hvg_method: 'seurat_v3',
    n_top_genes: 2000,
    enable_scanpy_backend: false,
    enable_seurat_r_backend: false
  },
  phase2_stoich: {
    feature_set: 'core',
    model_type: 'elasticnet',
    hvg_target_type: 'score',
    permutation_repeats: 8,
    bootstrap_repeats: 40
  }
}, null, 2))
const canCancel = computed(() => job.value && !['SUCCEEDED', 'FAILED', 'CANCELLED'].includes(job.value.status))
const load = async () => { job.value = await getJob(props.jobId) }
const handleFiles = (e) => { files.value = Array.from(e.target.files || []) }
const upload = async () => { await uploadJobFiles(props.jobId, files.value); files.value = []; await load() }
const autoconfigure = async () => {
  autoConfig.value = await autoconfigureJob(props.jobId, {
    profile: profile.value,
    pipeline_type: pipelineType.value,
    user_overrides: {}
  })
  await load()
}
const configure = async () => {
  await configureJob(props.jobId, {
    pipeline_type: pipelineType.value,
    input_mode: inputMode.value,
    expression_cfg: JSON.parse(expressionJson.value),
    metadata_file: metadataFile.value || null,
    stoich_cfg: JSON.parse(stoichJson.value),
    analysis_overrides: JSON.parse(analysisJson.value),
  })
  await load()
}
const preflight = async () => { preflightResult.value = await preflightJob(props.jobId) }
const run = async () => { await runJob(props.jobId); await load() }
const cancel = async () => { await cancelJob(props.jobId); await load(); await loadLogs() }
const loadLogs = async () => { logs.value = await getJobLogs(props.jobId) }
const loadRepro = async () => { repro.value = await getJobReproducibility(props.jobId) }
onMounted(load)
</script>

<style scoped>
.notice {
  display: grid;
  gap: 10px;
  margin-top: 14px;
  padding: 12px;
  border: 1px solid var(--line-soft);
  border-left: 4px solid #b7791f;
  border-radius: 8px;
  background: #fffaf0;
}
</style>
