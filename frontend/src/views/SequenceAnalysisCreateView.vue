<template>
  <div class="stack-lg">
    <section class="hero-panel">
      <div class="hero-copy">
        <div class="eyebrow">Sequence stoichiometry</div>
        <h1 style="font-size:2rem">Upload sequences for stoichiometric feature analysis</h1>
        <p>
          Analyze one FASTA file, compare multiple samples from the same species, or compare sequence-derived
          stoichiometric fingerprints across species. Results include feature tables, differential feature
          differences, Top/Low entities, sample comparison, and exploratory separability diagnostics.
        </p>
      </div>
      <div class="panel" style="padding:20px">
        <div class="label">Supported inputs</div>
        <ul class="clean-list compact-list">
          <li>Genome: FASTA plus matching GFF3 annotation</li>
          <li>Transcript sequence: cDNA / transcript FASTA</li>
          <li>Proteome: protein FASTA</li>
          <li>Optional sample sheet for sample, condition, species, and genome GFF pairing</li>
        </ul>
      </div>
    </section>

    <section v-if="model8Jobs.length" class="panel">
      <div class="section-header compact">
        <div>
          <h3>Model-8 sequence upload case jobs</h3>
          <p class="muted">Each model organism opens as a complete sequence workflow result built from the full-omics source sequences and matched feature tables.</p>
        </div>
        <span class="badge">Curated examples</span>
      </div>
      <div class="sequence-case-grid">
        <router-link
          v-for="job in model8Jobs"
          :key="job.job_id"
          class="sequence-case-card"
          :to="{ path: `/sequence-analysis/${job.job_id}`, query: { tab: 'overview' } }"
        >
          <div class="case-card-head">
            <div>
              <span class="badge">{{ job.species_case_code }}</span>
              <h4>{{ job.name }}</h4>
            </div>
            <span :class="['status-pill', statusClass(job.status)]">{{ job.status }}</span>
          </div>
          <div class="case-metrics">
            <div v-for="metric in caseMetricRows(job)" :key="metric.label">
              <span>{{ metric.label }}</span><strong>{{ metric.value }}</strong>
            </div>
          </div>
          <div class="case-card-foot">
            <span>{{ caseFooterPrimary(job) }}</span>
            <span>{{ caseFooterSecondary(job) }}</span>
          </div>
        </router-link>
      </div>
    </section>

    <section class="panel">
      <div class="section-header compact">
        <h3>Create sequence analysis job</h3>
        <span class="badge">Background task</span>
      </div>

      <div class="grid grid-2">
        <div>
          <div class="label">Job name</div>
          <input class="input" v-model="name" placeholder="Example: drought_gene_stoich_compare" />
        </div>
        <div>
          <div class="label">Omics branch</div>
          <select class="input" v-model="omicsType">
            <option value="transcriptome">Transcript sequence FASTA</option>
            <option value="proteome">Proteome FASTA</option>
            <option value="genome">Genome FASTA + GFF3</option>
          </select>
        </div>
      </div>

      <div class="mode-grid">
        <button
          v-for="mode in modes"
          :key="mode.value"
          type="button"
          class="mode-card"
          :class="{ active: analysisType === mode.value }"
          @click="analysisType = mode.value"
        >
          <strong>{{ mode.label }}</strong>
          <span>{{ mode.description }}</span>
        </button>
      </div>

      <div class="grid grid-2">
        <div>
          <div class="label">Research question</div>
          <input class="input" v-model="projectQuestion" placeholder="Example: Which stoichiometric features separate stress and control sequences?" />
        </div>
        <div>
          <div class="label">Comparison intent</div>
          <select class="input" v-model="comparisonIntent">
            <option value="descriptive">Descriptive profiling</option>
            <option value="group_comparison">Group comparison</option>
            <option value="species_comparison">Species comparison</option>
            <option value="candidate_ranking">Candidate entity ranking</option>
          </select>
        </div>
      </div>

      <div class="grid grid-2">
        <div>
          <div class="label">FASTA files</div>
          <input type="file" multiple accept=".fa,.fasta,.faa,.fna,.fas,.txt" @change="handleFiles" />
          <p class="muted">{{ files.length ? `${files.length} file(s) selected` : 'Upload one or more FASTA files.' }}</p>
        </div>
        <div v-if="omicsType === 'genome'">
          <div class="label">GFF3 annotation files</div>
          <input type="file" multiple accept=".gff,.gff3,.gtf,.txt" @change="handleAnnotationFiles" />
          <p class="muted">{{ annotationFiles.length ? `${annotationFiles.length} annotation file(s) selected` : 'Genome mode requires matching GFF3 files.' }}</p>
        </div>
        <div>
          <div class="label">Sample sheet (optional)</div>
          <input type="file" accept=".csv,.tsv,.txt" @change="handleSampleSheet" />
          <p class="muted">{{ sampleSheet ? sampleSheet.name : 'Columns: file_name, sample_id, condition, species_id, gff_file.' }}</p>
          <a class="ghost-link" :href="templateHref">Download sample sheet template</a>
        </div>
      </div>

      <div class="grid grid-2">
        <div>
          <div class="label">Grouping field</div>
          <input class="input" v-model="groupField" :placeholder="analysisType === 'multi_species' ? 'species_id' : 'condition'" />
          <p class="muted">Used for statistical comparison in multi-sample and multi-species modes.</p>
        </div>
        <div>
          <div class="label">Genetic code</div>
          <input class="input" v-model="geneticCode" placeholder="1 or 11" />
          <p class="muted">Transcript sequence mode defaults to 1; bacterial genome commonly uses 11.</p>
        </div>
      </div>

      <div class="grid grid-2">
        <div>
          <div class="label">Reference / normal group (optional)</div>
          <input class="input" v-model="referenceGroup" placeholder="Example: control" :disabled="analysisType === 'single_sequence'" />
          <p class="muted">
            Used for matched entity deltas, such as control vs stress. If blank, the first uploaded group is used.
          </p>
        </div>
        <div>
          <div class="label">Replicate design</div>
          <select class="input" v-model="replicateType">
            <option value="not_specified">Not specified</option>
            <option value="biological">Biological replicates</option>
            <option value="technical">Technical replicates</option>
            <option value="mixed">Mixed / batch-aware</option>
          </select>
          <p class="muted">Recorded into analysis_design.json and result interpretation guardrails.</p>
        </div>
      </div>

      <div class="panel soft-contract">
        <div class="section-header compact">
          <div>
            <div class="label">Input prevalidation</div>
            <p class="muted">Checks FASTA readability, genome annotation availability, sample-sheet mapping, comparison readiness, and reference-group consistency before launching the job.</p>
          </div>
          <button class="btn secondary" @click="prevalidate" :disabled="prevalidating || !files.length">
            {{ prevalidating ? 'Checking...' : 'Prevalidate inputs' }}
          </button>
        </div>
        <div v-if="inputQc" class="qc-grid">
          <div><span class="muted">Analysis</span><strong>{{ inputQc.analysis_allowed ? 'Ready' : 'Blocked' }}</strong></div>
          <div><span class="muted">Comparison</span><strong>{{ inputQc.comparison_allowed ? 'Ready' : 'Not available' }}</strong></div>
          <div><span class="muted">Records</span><strong>{{ formatNumber(inputQc.summary?.record_count) }}</strong></div>
          <div><span class="muted">Files</span><strong>{{ inputQc.summary?.file_count || 0 }}</strong></div>
        </div>
        <ul v-if="inputQc?.blocking_errors?.length" class="clean-list compact-list blocked-list">
          <li v-for="(item, idx) in inputQc.blocking_errors" :key="`block-${idx}`">{{ item.code }} - {{ item.message }}</li>
        </ul>
        <ul v-if="inputQc?.warnings?.length" class="clean-list compact-list warning-list">
          <li v-for="(item, idx) in inputQc.warnings" :key="`warn-${idx}`">{{ item.code }} - {{ item.message }}</li>
        </ul>
      </div>

      <div class="panel soft-contract">
        <div class="label">Output contract</div>
        <p class="muted">
          The backend writes sequence_features.csv, differential_features.csv,
          differential_entities.csv, rows_for_platform.csv, platform_bundle.json,
          analysis_payload.json, feature_catalog.json, feature_summary.csv/json,
          basic_visualization_payload.json, top_low_entities.csv/json,
          sample_comparison_payload.json, ml_discrimination_payload.json,
          plots_payload.json, summary.json, and run_log.json.
          Raw uploads are extension-checked, size-limited, checksum-tracked, isolated per job, and deleted after the run; derived runtime results expire automatically.
          Reproducibility metadata records input checksums, parameters, software versions, and the current code revision when available.
        </p>
      </div>

      <div class="row" style="justify-content:space-between; margin-top:18px">
        <div v-if="errorMessage" style="color:#b42318">{{ errorMessage }}</div>
        <div v-else class="muted">No database rebuild is required. This workflow creates a user result job.</div>
        <button class="btn" @click="submit" :disabled="submitting || !canSubmit">
          {{ submitting ? 'Submitting...' : 'Submit sequence analysis' }}
        </button>
      </div>
    </section>

    <section class="panel">
      <div class="section-header compact">
        <h3>Recent sequence analysis jobs</h3>
        <button class="btn secondary" @click="loadJobs">Refresh</button>
      </div>
      <table class="table">
        <thead>
          <tr>
            <th>job</th>
            <th>mode</th>
            <th>source</th>
            <th>status</th>
            <th>records</th>
            <th>groups</th>
            <th>updated</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="job in jobs" :key="job.job_id">
            <td><router-link :to="{ path: `/sequence-analysis/${job.job_id}`, query: { tab: 'basic' } }">{{ job.name || job.job_id }}</router-link></td>
            <td>{{ job.analysis_type }}</td>
            <td><span class="badge">{{ job.is_example ? 'Example' : 'Runtime' }}</span></td>
            <td>{{ job.status }}</td>
            <td>{{ job.summary?.record_count ?? '-' }}</td>
            <td>{{ job.summary?.group_count ?? '-' }}</td>
            <td>{{ job.updated_at || '-' }}</td>
          </tr>
          <tr v-if="!jobs.length"><td colspan="7">No sequence analysis jobs yet.</td></tr>
        </tbody>
      </table>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  createSequenceAnalysisJob,
  listSequenceAnalysisJobs,
  prevalidateSequenceAnalysisJob,
  sequenceSampleSheetTemplateUrl,
} from '../api/sequenceAnalysis'

const router = useRouter()
const name = ref('')
const analysisType = ref('single_sequence')
const omicsType = ref('transcriptome')
const groupField = ref('')
const referenceGroup = ref('')
const geneticCode = ref('1')
const projectQuestion = ref('')
const comparisonIntent = ref('group_comparison')
const replicateType = ref('not_specified')
const files = ref([])
const annotationFiles = ref([])
const sampleSheet = ref(null)
const submitting = ref(false)
const prevalidating = ref(false)
const errorMessage = ref('')
const inputQc = ref(null)
const jobs = ref([])
const model8Jobs = computed(() => jobs.value.filter(job => job.case_family === 'model8_case4_upload_gold'))

const modes = [
  {
    value: 'single_sequence',
    label: 'Single species / single sample',
    description: 'Inspect one species or sequence set with feature table, family-level plots, deep analysis, and Top/Low entities.',
  },
  {
    value: 'multi_sample',
    label: 'Single species / multi-sample',
    description: 'Compare samples or conditions within one species and rank differential features and entities.',
  },
  {
    value: 'multi_species',
    label: 'Multi-species / multi-sample',
    description: 'Compare species, samples, or conditions and produce exploratory separability diagnostics with interpretable feature ranking.',
  },
]

watch(analysisType, (value) => {
  if (value === 'multi_species' && !groupField.value) groupField.value = 'species_id'
  if (value === 'multi_sample' && !groupField.value) groupField.value = 'condition'
  if (value === 'single_sequence') {
    groupField.value = ''
    referenceGroup.value = ''
  }
})

const inferredGroupField = computed(() => {
  if (analysisType.value === 'multi_species') return groupField.value || 'species_id'
  if (analysisType.value === 'multi_sample') return groupField.value || 'condition'
  return ''
})

const canSubmit = computed(() => {
  if (!files.value.length) return false
  if (omicsType.value === 'genome' && !annotationFiles.value.length) return false
  if (inputQc.value && inputQc.value.analysis_allowed === false) return false
  return true
})

const templateHref = computed(() => sequenceSampleSheetTemplateUrl(analysisType.value, omicsType.value))

function formatNumber(value) {
  const n = Number(value)
  return Number.isFinite(n) ? n.toLocaleString() : '-'
}

function percent(value) {
  const n = Number(value)
  return Number.isFinite(n) ? `${(n * 100).toFixed(1)}%` : '-'
}

function caseMetricRows(job) {
  if (job?.standard_sequence_upload_case) {
    return [
      { label: 'Records', value: formatNumber(job.summary?.record_count) },
      { label: 'Samples', value: formatNumber(job.summary?.sample_count) },
      { label: 'Features', value: formatNumber(job.summary?.feature_count) },
    ]
  }
  return [
    { label: 'Records', value: formatNumber(job.summary?.record_count) },
    { label: 'Protein', value: formatNumber(job.summary?.protein_records) },
    { label: 'Nucleotide', value: formatNumber(job.summary?.nucleotide_records) },
  ]
}

function caseFooterPrimary(job) {
  if (job?.standard_sequence_upload_case) {
    return `${formatNumber(job.summary?.group_count)} groups`
  }
  return `${percent(job.summary?.pass_rate)} agreement`
}

function caseFooterSecondary(job) {
  if (job?.standard_sequence_upload_case) {
    return `${job.analysis_type} / ${job.omics_type}`
  }
  return job?.omics_type || '-'
}

function statusClass(value) {
  const status = String(value || '').toLowerCase()
  if (status.includes('succeed') || status.includes('complete')) return 'ready'
  if (status.includes('fail') || status.includes('blocked')) return 'blocked'
  return 'pending'
}

function handleFiles(event) {
  files.value = Array.from(event.target.files || [])
  inputQc.value = null
}

function handleAnnotationFiles(event) {
  annotationFiles.value = Array.from(event.target.files || [])
  inputQc.value = null
}

function handleSampleSheet(event) {
  sampleSheet.value = (event.target.files || [])[0] || null
  inputQc.value = null
}

async function loadJobs() {
  jobs.value = await listSequenceAnalysisJobs()
}

function buildForm() {
  const form = new FormData()
  form.append('name', name.value)
  form.append('analysis_type', analysisType.value)
  form.append('omics_type', omicsType.value)
  form.append('group_field', inferredGroupField.value)
  form.append('reference_group', referenceGroup.value)
  form.append('feature_set', 'core')
  form.append('genetic_code', geneticCode.value || '1')
  form.append('project_question', projectQuestion.value)
  form.append('comparison_intent', comparisonIntent.value)
  form.append('replicate_type', replicateType.value)
  files.value.forEach(file => form.append('files', file))
  annotationFiles.value.forEach(file => form.append('annotation_files', file))
  if (sampleSheet.value) form.append('sample_sheet', sampleSheet.value)
  return form
}

async function prevalidate() {
  if (!files.value.length) return
  prevalidating.value = true
  errorMessage.value = ''
  try {
    inputQc.value = await prevalidateSequenceAnalysisJob(buildForm())
  } catch (err) {
    errorMessage.value = err?.response?.data?.error || err.message || 'Input prevalidation failed.'
  } finally {
    prevalidating.value = false
  }
}

async function submit() {
  if (!files.value.length) return
  submitting.value = true
  errorMessage.value = ''
  const form = buildForm()
  try {
    const job = await createSequenceAnalysisJob(form)
    await router.push({ path: `/sequence-analysis/${job.job_id}`, query: { tab: 'basic' } })
  } catch (err) {
    errorMessage.value = err?.response?.data?.error || err.message || 'Sequence analysis failed.'
  } finally {
    submitting.value = false
  }
}

onMounted(loadJobs)
</script>

<style scoped>
.mode-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin: 18px 0;
}

.mode-card {
  border: 1px solid var(--line-soft);
  border-radius: 18px;
  background: linear-gradient(135deg, #ffffff, #f5f9ff);
  color: var(--text-main);
  cursor: pointer;
  padding: 16px;
  text-align: left;
}

.mode-card strong,
.mode-card span {
  display: block;
}

.mode-card span {
  color: var(--text-muted);
  font-size: 0.88rem;
  margin-top: 8px;
}

.mode-card.active {
  border-color: var(--accent);
  box-shadow: 0 14px 34px rgba(35, 112, 207, 0.18);
}

.soft-contract {
  margin-top: 16px;
  padding: 14px 16px;
}

.qc-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-top: 12px;
}

.qc-grid div {
  border: 1px solid var(--line-soft);
  border-radius: 10px;
  padding: 10px;
  background: #fff;
}

.qc-grid span,
.qc-grid strong {
  display: block;
}

.blocked-list {
  color: #b42318;
  margin-top: 12px;
}

.warning-list {
  color: #8a5a00;
  margin-top: 12px;
}

.sequence-case-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 12px;
}

.sequence-case-card {
  min-height: 170px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 14px;
  padding: 14px;
  border: 1px solid var(--line-soft);
  border-radius: 12px;
  background: #fff;
  color: inherit;
  text-decoration: none;
  transition: border-color 0.16s ease, box-shadow 0.16s ease, transform 0.16s ease;
}

.sequence-case-card:hover {
  transform: translateY(-1px);
  border-color: rgba(31, 93, 154, 0.38);
  box-shadow: 0 8px 16px rgba(42, 83, 122, 0.08);
}

.case-card-head,
.case-card-foot {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.case-card-head h4 {
  margin: 8px 0 0;
  line-height: 1.25;
}

.case-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.case-metrics div {
  padding: 8px;
  border-radius: 10px;
  background: rgba(244, 248, 252, 0.9);
}

.case-metrics span,
.case-card-foot {
  color: var(--text-muted);
  font-size: 0.78rem;
}

.case-metrics strong {
  display: block;
  margin-top: 3px;
  color: var(--text-main);
}

.status-pill {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 3px 8px;
  border-radius: 999px;
  border: 1px solid rgba(74, 113, 151, 0.18);
  background: rgba(240, 246, 252, 0.9);
  color: #31566f;
  font-size: 0.76rem;
  font-weight: 700;
}

.status-pill.ready {
  border-color: rgba(42, 157, 143, 0.28);
  background: rgba(232, 249, 246, 0.95);
  color: #17695e;
}

.status-pill.blocked {
  border-color: rgba(180, 35, 24, 0.22);
  background: rgba(255, 241, 240, 0.95);
  color: #9f1f17;
}

@media (max-width: 900px) {
  .mode-grid {
    grid-template-columns: 1fr;
  }

  .case-metrics {
    grid-template-columns: 1fr;
  }

  .qc-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
