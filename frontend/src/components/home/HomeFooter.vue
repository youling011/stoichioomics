<template>
  <footer class="home-footer">
    <div class="home-footer-brand">
      <img :src="logo" alt="" aria-hidden="true" />
      <strong>Stoichioomics Platform</strong>
      <p>Research-use database and workflow platform for multi-species multi-omics stoichiometric analysis.</p>
    </div>
    <nav v-for="group in groups" :key="group.title" class="home-footer-col" :aria-label="group.title">
      <strong>{{ group.title }}</strong>
      <router-link v-for="link in group.links" :key="link.to" :to="link.to">{{ link.label }}</router-link>
    </nav>
    <div class="home-footer-release">
      <strong>Latest Data Release</strong>
      <p>{{ release?.label || release?.release_id || 'Active release' }}</p>
      <router-link class="home-primary-btn slim" to="/release">View latest release</router-link>
    </div>
    <div class="home-footer-bottom">
      <span>© {{ year }} Stoichioomics Platform. All rights reserved.</span>
    </div>
  </footer>
</template>

<script setup>
import logo from '../../assets/home/stoichioomics-logo.svg'

defineProps({
  release: { type: Object, default: () => ({}) },
})

const year = new Date().getFullYear()
const groups = [
  { title: 'Platform', links: [{ label: 'Home', to: '/' }, { label: 'Database', to: '/database' }, { label: 'Feature Hub', to: '/feature-hub' }, { label: 'Entity Explorer', to: '/entity-search' }] },
  { title: 'Analysis', links: [{ label: 'Compare', to: '/compare' }, { label: 'Workflows', to: '/workflows' }, { label: 'Case Studies', to: '/case-studies' }] },
  { title: 'Resources', links: [{ label: 'Release/QC', to: '/release' }, { label: 'Docs', to: '/docs' }, { label: 'API', to: '/docs' }, { label: 'Download', to: '/downloads' }] },
  { title: 'About', links: [{ label: 'Guide', to: '/guide' }, { label: 'Contact', to: '/contact' }, { label: 'Platform scope', to: '/overview' }] },
]
</script>
