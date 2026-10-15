<template>
  <section class="home-section compact">
    <h2>Explore the Platform</h2>
    <div class="home-module-grid">
      <router-link v-for="item in modules" :key="item.to" class="home-module-card" :to="item.to">
        <img :src="item.icon" alt="" aria-hidden="true" />
        <h3>{{ item.title }}</h3>
        <p>{{ item.description }}</p>
        <span>{{ item.cta }} <b aria-hidden="true">›</b></span>
      </router-link>
    </div>
  </section>
</template>

<script setup>
import databaseIcon from '../../assets/home/module-database.svg'
import featureIcon from '../../assets/home/module-feature-hub.svg'
import entityIcon from '../../assets/home/module-entity.svg'
import compareIcon from '../../assets/home/module-compare.svg'
import workflowsIcon from '../../assets/home/module-workflows.svg'
import releaseIcon from '../../assets/home/module-release.svg'

const modules = [
  { title: 'Database', to: '/database', icon: databaseIcon, cta: 'Go to Database', description: 'Search and browse multi-omics data across species.' },
  { title: 'Feature Hub', to: '/feature-hub', icon: featureIcon, cta: 'Go to Feature Hub', description: 'Build ML-ready feature matrices with powerful filters.' },
  { title: 'Entity Explorer', to: '/entity-search', icon: entityIcon, cta: 'Explore Now', description: 'Explore genes, transcripts, proteins and mapped identifiers.' },
  { title: 'Compare', to: '/compare', icon: compareIcon, cta: 'Start Compare', description: 'Cross-species and cross-omics comparative analysis.' },
  { title: 'Workflows', to: '/workflows', icon: workflowsIcon, cta: 'View Workflows', description: 'Run end-to-end workflows for feature generation.' },
  { title: 'Release/QC', to: '/release', icon: releaseIcon, cta: 'View Releases', description: 'Release notes, QC metrics and data provenance.' },
]
</script>
