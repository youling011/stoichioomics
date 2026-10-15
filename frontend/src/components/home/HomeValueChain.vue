<template>
  <section class="home-section compact">
    <h2>Why Stoichioomics</h2>
    <div class="home-value-chain">
      <article v-for="(item, index) in steps" :key="item.title" class="home-value-step">
        <img :src="item.icon" alt="" aria-hidden="true" />
        <div>
          <strong>{{ index + 1 }}. {{ item.title }}</strong>
          <p>{{ item.text }}</p>
        </div>
      </article>
    </div>
  </section>
</template>

<script setup>
import sequenceIcon from '../../assets/home/value-sequence.svg'
import extractionIcon from '../../assets/home/value-extraction.svg'
import featureIcon from '../../assets/home/value-feature-space.svg'
import analysisIcon from '../../assets/home/value-analysis.svg'
import builderIcon from '../../assets/home/value-builder.svg'

const steps = [
  { title: 'Sequence / Annotation', icon: sequenceIcon, text: 'High-quality public genome, transcriptome, and proteome sequences with annotations.' },
  { title: 'Stoichiometric Feature Extraction', icon: extractionIcon, text: 'Derive biologically meaningful features with domain knowledge.' },
  { title: 'Multi-omics Feature Space', icon: featureIcon, text: 'Integrate genome, transcriptome and proteome features.' },
  { title: 'Visualization & Analysis', icon: analysisIcon, text: 'Explore patterns, compare species and generate insights.' },
  { title: 'ML / DL Dataset Builder', icon: builderIcon, text: 'Build curated datasets ready for machine learning.' },
]
</script>
