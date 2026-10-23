<template>
  <div class="stack-lg">
    <section class="hero-panel">
      <div class="hero-copy">
        <div class="eyebrow">Create job</div>
        <h1 style="font-size:2rem">Launch a user-data workflow</h1>
        <p>
          The platform supports user-owned workflows in parallel with the public registry. Typical inputs are sequence-oriented files or expression matrix plus metadata bundles prepared for the Expression/HVG Stoich Extension.
        </p>
      </div>
      <div class="panel" style="padding:20px">
        <div class="label">Suggested use cases</div>
        <ul class="clean-list compact-list">
          <li>Private Expression/HVG exploration on uploaded expression inputs</li>
          <li>Validation of newly generated sequence-derived feature tables</li>
          <li>Workflow staging before promotion into the curated registry</li>
        </ul>
      </div>
    </section>

    <section class="panel" style="max-width:820px">
      <div class="section-header compact">
        <div>
          <div class="eyebrow">Expression/HVG workflow</div>
          <h3>New analysis workspace</h3>
        </div>
        <span class="badge">Unified workflow</span>
      </div>
      <div class="grid grid-2">
        <div>
          <div class="label">Name</div>
          <input class="input" v-model="name" placeholder="Example: yeast_timecourse_hvg" />
        </div>
        <div>
          <div class="label">Run objective</div>
          <select class="input" v-model="runObjective">
            <option value="stoich_functional_characterization">Unified HVG, context and stoichiometric research</option>
          </select>
        </div>
      </div>
      <div style="height:12px"></div>
      <div class="label">Research question</div>
      <input class="input" v-model="researchQuestion" placeholder="Example: Do stoichiometric features explain condition-specific HVG signals?" />
      <div style="height:12px"></div>
      <div class="label">Dataset context</div>
      <textarea rows="4" v-model="datasetContext" placeholder="Species, tissue/cell type, experimental groups, expected matrix format, and available stoichiometric feature table."></textarea>
      <div style="height:12px"></div>
      <div class="grid grid-3">
        <div>
          <div class="label">Species ID</div>
          <input class="input" v-model="speciesId" placeholder="Example: Saccharomyces_cerevisiae" />
        </div>
        <div>
          <div class="label">Omics type</div>
          <select class="input" v-model="omicsType">
            <option value="transcriptome">transcriptome</option>
            <option value="genome">genome</option>
            <option value="proteome">proteome</option>
          </select>
        </div>
        <div>
          <div class="label">Feature set</div>
          <select class="input" v-model="featureSet">
            <option value="core">core</option>
            <option value="full">full</option>
          </select>
        </div>
      </div>
      <div style="height:12px"></div>
      <div class="label">Sequence feature job ID</div>
      <input class="input" v-model="sequenceFeatureJobId" placeholder="Optional: completed sequence-analysis job used when registry features are unavailable" />
      <div class="check-grid">
        <label><input type="checkbox" v-model="expectedInputs.expression" /> Expression matrix</label>
        <label><input type="checkbox" v-model="expectedInputs.metadata" /> Metadata/sample sheet</label>
        <label><input type="checkbox" v-model="expectedInputs.stoich" /> User stoich feature table</label>
        <label><input type="checkbox" v-model="promoteIntent" /> Promote when complete</label>
      </div>
      <p class="muted" style="margin-top:12px">
        A private job workspace and access token are created for this browser. Uploaded files stay in the job workspace,
        are extension/size checked, and are not imported into the public registry unless explicitly promoted later.
        The workspace writes job_manifest.json, input_qc.json, analysis_design.json, result_interpretation.json,
        download_manifest.json, and reproducibility_manifest.json as the analysis progresses.
      </p>
      <div style="height:12px"></div>
      <button class="btn" @click="submit">Create job</button>
      <p v-if="created" style="margin-top:12px">Created: <router-link :to="`/jobs/${created.job_id}`">{{ created.job_id }}</router-link></p>
    </section>
  </div>
</template>
<script setup>
import { ref } from 'vue'
import { createJob } from '../api/jobs'
const name = ref('')
const runObjective = ref('stoich_functional_characterization')
const researchQuestion = ref('')
const datasetContext = ref('')
const speciesId = ref('')
const omicsType = ref('transcriptome')
const featureSet = ref('core')
const sequenceFeatureJobId = ref('')
const promoteIntent = ref(false)
const expectedInputs = ref({
  expression: true,
  metadata: true,
  stoich: false,
})
const created = ref(null)
const submit = async () => {
  created.value = await createJob({
    name: name.value,
    metadata_json: {
      workflow_module: 'Expression/HVG Stoich Extension',
      run_objective: runObjective.value,
      research_question: researchQuestion.value,
      dataset_context: datasetContext.value,
      species_id: speciesId.value,
      omics_type: omicsType.value,
      feature_set: featureSet.value,
      sequence_feature_job_id: sequenceFeatureJobId.value,
      stoich_feature_strategy: 'user_upload_then_registry_then_sequence_upload',
      expected_inputs: expectedInputs.value,
      promote_intent: promoteIntent.value,
    },
  })
}
</script>

<style scoped>
.check-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-top: 12px;
}

.check-grid label {
  border: 1px solid var(--line-soft);
  border-radius: 10px;
  padding: 10px;
  background: #fff;
}

@media (max-width: 760px) {
  .check-grid {
    grid-template-columns: 1fr;
  }
}
</style>
