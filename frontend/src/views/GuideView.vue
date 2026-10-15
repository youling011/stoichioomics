<template>
  <div v-if="guide" class="stack-lg">
    <section class="panel">
      <div class="section-header">
        <div>
          <div class="eyebrow">Usage guide</div>
          <h3>Suggested workflow across the whole site</h3>
          <p class="muted">{{ PLATFORM_POSITIONING }}</p>
          <p class="muted">Transcript sequence pages refer to sequence-derived stoichiometric features. Expression inputs are handled in the Expression/HVG Stoich Extension branch.</p>
        </div>
      </div>
      <ol class="clean-list numbered-list">
        <li v-for="item in guide.workflow" :key="item">{{ item }}</li>
      </ol>
    </section>

    <section class="panel">
      <div class="section-header compact"><h3>HVG vs non-HVG interpretation</h3></div>
      <ul class="clean-list compact-list">
        <li>The dedicated comparison tab tests the Core Transcriptome and/or Proteome feature blocks that were reliably mapped to the current gene-level job.</li>
        <li>Cliff’s delta, confidence intervals and global FDR describe direct group differences. They are distinct from Generic-M0/M1/M2/M3 prediction metrics and permutation importance.</li>
        <li>Adjusted results use gene-level expression, one detection/dropout measure and an applicable length variable. Cell- or sample-level batch, donor and cell type are not inserted as per-gene covariates.</li>
        <li>Composition and length-related fields carry interpretation warnings. Statistical association does not establish that stoichiometry causes HVG formation.</li>
      </ul>
    </section>

    <section class="grid grid-2">
      <article class="panel">
        <div class="section-header compact"><h3>Data contract</h3></div>
        <ul class="clean-list compact-list">
          <li v-for="item in guide.data_contract" :key="item">{{ item }}</li>
        </ul>
      </article>
      <article class="panel">
        <div class="section-header compact"><h3>Practical notes</h3></div>
        <ul class="clean-list compact-list">
          <li v-for="item in guide.notes" :key="item">{{ item }}</li>
        </ul>
      </article>
    </section>

    <section class="panel">
      <div class="section-header compact"><h3>Recommended interpretation path</h3></div>
      <div class="grid grid-4">
        <div class="mini-card">
          <div class="label">1</div>
          <div class="metric-inline">Screen</div>
          <p class="muted">Filter the species registry and choose a target species or omics branch.</p>
        </div>
        <div class="mini-card">
          <div class="label">2</div>
          <div class="metric-inline">Visualize</div>
          <p class="muted">Inspect distributions, feature relationships, and representative entities.</p>
        </div>
        <div class="mini-card">
          <div class="label">3</div>
          <div class="metric-inline">Analyze</div>
          <p class="muted">Move into strategy clusters, outliers, trade-offs, and coupling networks.</p>
        </div>
        <div class="mini-card">
          <div class="label">4</div>
          <div class="metric-inline">Run user data</div>
          <p class="muted">Use workflow pages for private inputs such as user-provided sequence bundles.</p>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { getGuide } from '../api/stoichdb'
import { PLATFORM_POSITIONING } from '../constants/platformTerminology'

const guide = ref(null)

onMounted(async () => {
  guide.value = await getGuide()
})
</script>
