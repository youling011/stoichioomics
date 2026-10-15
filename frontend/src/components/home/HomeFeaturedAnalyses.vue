<template>
  <section class="home-section compact">
    <div class="home-section-head">
      <h2>Featured Analyses</h2>
      <router-link to="/case-studies">View all case studies <span aria-hidden="true">›</span></router-link>
    </div>
    <div class="home-analysis-grid">
      <router-link v-for="item in cards" :key="item.to" class="home-analysis-card" :to="item.to">
        <img :src="item.art" alt="" aria-hidden="true" />
        <div>
          <h3>{{ item.title }}</h3>
          <p>{{ item.description }}</p>
          <span>{{ item.cta }} <b aria-hidden="true">›</b></span>
        </div>
      </router-link>
    </div>
  </section>
</template>

<script setup>
import compareArt from '../../assets/home/analysis-compare.svg'
import sequenceArt from '../../assets/home/analysis-sequence.svg'
import hvgArt from '../../assets/home/analysis-hvg.svg'

const cards = [
  {
    title: 'Cross-species Compare',
    to: '/compare',
    art: compareArt,
    cta: 'Open Analysis',
    description: 'Compare feature landscapes across clades and identify lineage-specific patterns.',
  },
  {
    title: 'Sequence Stoichiometry Workflow',
    to: '/sequence-analysis',
    art: sequenceArt,
    cta: 'Open Workflow',
    description: 'From sequence to stoichiometric features in a reproducible workflow.',
  },
  {
    title: 'Expression / HVG Extension',
    to: '/workflows',
    art: hvgArt,
    cta: 'Open Analysis',
    description: 'Identify highly variable genes across species and extend features to expression space.',
  },
]
</script>
