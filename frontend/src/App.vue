<template>
  <div class="app-shell">
    <header class="global-header" :class="{ 'landing-header': isLanding }">
      <div class="brand-row">
        <router-link class="brand-block" to="/">
          <img class="brand-logo" src="./assets/home/stoichioomics-logo.svg" alt="" aria-hidden="true" />
          <div>
            <div class="brand-title">Stoichioomics Platform</div>
            <div v-if="!isLanding" class="brand-subtitle">{{ PLATFORM_POSITIONING }}</div>
          </div>
        </router-link>

        <div class="header-actions">
          <a class="header-search-button" href="/#home-search" aria-label="Search the platform">
            <span aria-hidden="true">⌕</span>
          </a>
          <router-link class="open-platform-btn" to="/database">Open Platform</router-link>
        </div>
      </div>

      <nav class="top-nav">
        <router-link v-for="item in topNav" :key="item.to" :to="item.to" class="top-nav-link" :class="{ active: isTopNavActive(item) }">
          {{ item.label }}
        </router-link>
      </nav>
    </header>

    <template v-if="isLanding">
      <main class="landing-main">
        <router-view />
      </main>
    </template>

    <template v-else>
      <div class="app-body" :class="{ 'no-sidebar': noSidebar }">
        <aside v-if="!noSidebar" class="context-sidebar">
          <div class="sidebar-section sidebar-emphasis">
            <div class="sidebar-label">Primary domain</div>
            <h3>{{ currentSection.title }}</h3>
            <p>{{ currentSection.description }}</p>
          </div>

          <div
            v-for="group in sidebarGroups"
            :key="group.label"
            class="sidebar-section sidebar-nav-group"
          >
            <div class="sidebar-label">{{ group.label }}</div>
            <p v-if="group.description" class="sidebar-group-copy">{{ group.description }}</p>
            <div class="side-nav">
              <template v-for="item in group.links" :key="`${group.label}-${item.label}`">
                <router-link
                  v-if="item.type !== 'anchor'"
                  :to="item.to"
                  class="side-nav-link"
                  :class="{ active: isSideNavActive(item) }"
                >
                  <span>{{ item.label }}</span>
                  <small v-if="item.level">{{ item.level }}</small>
                </router-link>
                <a v-else :href="item.to" class="side-nav-link">
                  <span>{{ item.label }}</span>
                  <small v-if="item.level">{{ item.level }}</small>
                </a>
              </template>
            </div>
          </div>

          <div class="sidebar-section sidebar-note-box">
            <div class="sidebar-label">Navigation rule</div>
            <ul class="clean-list compact-list">
              <li>Primary domain defines the current workspace.</li>
              <li>Domain modules stay within that workspace.</li>
              <li>Related areas are cross-domain exits only.</li>
            </ul>
          </div>
        </aside>

        <main class="content-shell">
          <section class="page-banner">
            <div>
              <div class="eyebrow">{{ currentSection.banner }}</div>
              <h1>{{ pageTitle }}</h1>
              <p>{{ pageSubtitle }}</p>
            </div>
            <div class="page-banner-badges">
              <span class="badge">Blue academic research UI</span>
              <span class="badge">Species registry + user workflows</span>
              <span class="badge">Schema-aligned omics artifacts</span>
            </div>
          </section>

          <router-view />
        </main>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { PLATFORM_POSITIONING } from './constants/platformTerminology'

const route = useRoute()

const topNav = [
  { label: 'Home', to: '/', sections: ['landing', 'overview'] },
  { label: 'Database', to: '/database', sections: ['screening', 'databaseResults', 'visualization', 'analysis'] },
  { label: 'Feature Hub', to: '/feature-hub', section: 'features' },
  { label: 'Compare', to: '/compare', section: 'compare' },
  { label: 'Workflows', to: '/workflows', section: 'workflows' },
  { label: 'Release/QC', to: '/release', section: 'releaseQc' },
  { label: 'Docs', to: '/docs', section: 'docs' },
]

const sectionConfig = {
  landing: {
    title: 'Gateway',
    banner: 'Platform gateway',
    description: 'Main entry portal with global search, module cards, featured species, and project-facing overview.',
    primaryLabel: 'Gateway modules',
    primaryLinks: [
      { label: 'Gateway', to: '/', exact: true },
      { label: 'Overview', to: '/overview', exact: true },
    ],
    relatedLinks: [
      { label: 'Species registry', to: '/database' },
      { label: 'Feature Hub', to: '/feature-hub' },
      { label: 'Workflows', to: '/workflows' },
    ],
  },
  overview: {
    title: 'Overview',
    banner: 'Platform overview',
    description: 'Entry point for the platform mission, registry scale, supported workflows, and research-facing feature map.',
    primaryLabel: 'Overview modules',
    primaryLinks: [
      { label: 'Gateway', to: '/', exact: true },
      { label: 'Overview', to: '/overview', exact: true },
    ],
    relatedLinks: [
      { label: 'Database', to: '/database' },
      { label: 'Feature Hub', to: '/feature-hub' },
      { label: 'Workflows', to: '/workflows' },
      { label: 'Release/QC', to: '/release' },
    ],
  },
  screening: {
    title: 'Screening and registry',
    banner: 'Search and filter',
    description: 'Browse species, filter omics layers, inspect fingerprints, and open species-level explorers.',
    primaryLabel: 'Registry modules',
    primaryLinks: [
      { label: 'Species registry', to: '/database', exact: true },
      { label: 'Results hub', to: '/database-results', exact: true },
      { label: 'Entity Explorer', to: '/entity-search' },
    ],
    relatedLinks: [
      { label: 'Feature Hub', to: '/feature-hub' },
      { label: 'Compare species', to: '/compare' },
      { label: 'Release/QC', to: '/release' },
    ],
  },
  databaseResults: {
    title: 'Results & analysis hub',
    banner: 'Stored species results and analysis',
    description: 'Unified internal hub for database results, foundational visualization, deep analysis, entity reports, and feature-table browsing.',
    primaryLabel: 'Data exploration modules',
    primaryLinks: [
      { label: 'Results hub', to: '/database-results', exact: true },
      { label: 'Entity Explorer', to: '/entity-search' },
      { label: 'Visualization hub', to: '/visualization' },
      { label: 'Analysis hub', to: '/analysis' },
      { label: 'Case studies', to: '/case-studies' },
    ],
    relatedLinks: [
      { label: 'Species registry', to: '/database' },
      { label: 'Compare species', to: '/compare' },
      { label: 'Feature Hub', to: '/feature-hub' },
    ],
  },
  features: {
    title: 'Feature Hub',
    banner: 'Feature tables and ML-ready Core matrices',
    description: 'Explore complete Core/Full feature schemas, preview real records, run Core QC, and export traceable ML packages.',
    primaryLabel: 'Feature modules',
    primaryLinks: [
      { label: 'Feature overview', to: '/feature-hub', exact: true },
      { label: 'Catalog', to: '/feature-hub/catalog' },
      { label: 'Browse', to: '/feature-hub/browse' },
      { label: 'Builder', to: '/feature-hub/builder' },
      { label: 'QC', to: '/feature-hub/qc' },
      { label: 'Exports', to: '/feature-hub/exports' },
    ],
    relatedLinks: [
      { label: 'Source downloads', to: '/downloads' },
      { label: 'Species registry', to: '/database' },
    ],
  },
  releaseQc: {
    title: 'Release/QC',
    banner: 'Release, quality, and downloads',
    description: 'Formal release registration, source-file downloads, QC reporting, and provenance for the database platform.',
    primaryLabel: 'Release modules',
    primaryLinks: [
      { label: 'Release', to: '/release', exact: true },
      { label: 'Quality control', to: '/quality', exact: true },
      { label: 'Downloads', to: '/downloads', exact: true },
    ],
    relatedLinks: [
      { label: 'Species registry', to: '/database' },
      { label: 'Docs', to: '/docs' },
    ],
  },
  visualization: {
    title: 'Foundational visualization',
    banner: 'Feature-table visualization',
    description: 'Genome, transcript sequence, proteome, and cross-omics visual summaries driven by stoichiometric feature tables.',
    primaryLabel: 'Visualization module',
    primaryLinks: [
      { label: 'Visualization hub', to: '/visualization', exact: true },
    ],
    pageLinks: [
      { label: 'Genome section', to: '/visualization#genome', type: 'anchor' },
      { label: 'Transcript sequence section', to: '/visualization#transcriptome', type: 'anchor' },
      { label: 'Proteome section', to: '/visualization#proteome', type: 'anchor' },
    ],
    relatedLinks: [
      { label: 'Species registry', to: '/database' },
      { label: 'Analysis hub', to: '/analysis' },
      { label: 'Compare species', to: '/compare' },
    ],
  },
  analysis: {
    title: 'Deep analysis',
    banner: 'Artifact-driven analysis',
    description: 'Strategy typing, outliers, trade-offs, coupling networks, and omics-specific modules are organized here.',
    primaryLabel: 'Analysis module',
    primaryLinks: [
      { label: 'Analysis hub', to: '/analysis', exact: true },
    ],
    pageLinks: [
      { label: 'Genome modules', to: '/analysis#genome-analysis', type: 'anchor' },
      { label: 'Transcript sequence modules', to: '/analysis#transcriptome-analysis', type: 'anchor' },
      { label: 'Proteome modules', to: '/analysis#proteome-analysis', type: 'anchor' },
    ],
    relatedLinks: [
      { label: 'Species registry', to: '/database' },
      { label: 'Visualization hub', to: '/visualization' },
      { label: 'Compare species', to: '/compare' },
    ],
  },
  compare: {
    title: 'Cross-species comparison',
    banner: 'Comparative stoichiometric landscape',
    description: 'Compare species fingerprints, pairwise distances, and multi-species patterns across omics.',
    primaryLabel: 'Comparison module',
    primaryLinks: [
      { label: 'Compare species', to: '/compare', exact: true },
    ],
    relatedLinks: [
      { label: 'Species registry', to: '/database' },
      { label: 'Visualization hub', to: '/visualization' },
      { label: 'Analysis hub', to: '/analysis' },
    ],
  },
  workflows: {
    title: 'User workflows',
    banner: 'Run analysis on your own data',
    description: 'Launch user-owned sequence stoichiometry jobs and Expression/HVG Stoich Extension analyses from two workflow branches.',
    primaryLabel: 'Workflow modules',
    primaryLinks: [
      { label: 'Workflow hub', to: '/workflows', exact: true },
      { label: 'Sequence stoichiometry', to: '/sequence-analysis' },
      { label: 'Expression/HVG workflow', to: '/hvg-workflow', exact: true },
      { label: 'Expression/HVG registry', to: '/registry' },
      { label: 'Expression/HVG compare', to: '/hvg-compare' },
      { label: 'Jobs', to: '/jobs' },
    ],
    relatedLinks: [
      { label: 'Guide', to: '/guide' },
      { label: 'Docs', to: '/docs' },
    ],
  },
  docs: {
    title: 'Docs',
    banner: 'Guide, API, and support',
    description: 'User guide, API/data dictionary, tutorials, platform scope, and contact information.',
    primaryLabel: 'Reference modules',
    primaryLinks: [
      { label: 'Docs', to: '/docs', exact: true },
      { label: 'Guide', to: '/guide' },
      { label: 'Contact', to: '/contact' },
      { label: 'Other modules', to: '/more' },
    ],
    relatedLinks: [
      { label: 'Case studies', to: '/case-studies' },
      { label: 'Downloads', to: '/downloads' },
      { label: 'Release/QC', to: '/release' },
    ],
  },
  other: {
    title: 'Other modules',
    banner: 'Operations and reference',
    description: 'Release, quality control, documentation, guide, contact, and legacy workflow utilities are grouped here.',
    primaryLabel: 'Reference modules',
    primaryLinks: [
      { label: 'Other modules', to: '/more', exact: true },
      { label: 'Docs', to: '/docs', exact: true },
      { label: 'Guide', to: '/guide' },
      { label: 'Contact', to: '/contact' },
    ],
    relatedLinks: [
      { label: 'Release/QC', to: '/release' },
    ],
  },
  guide: {
    title: 'Guide',
    banner: 'User guide',
    description: 'Working assumptions, feature-table contracts, and practical steps for using the platform.',
    primaryLabel: 'Reference modules',
    primaryLinks: [
      { label: 'Docs', to: '/docs', exact: true },
      { label: 'Guide', to: '/guide' },
      { label: 'Contact', to: '/contact' },
    ],
    relatedLinks: [
      { label: 'Sequence upload', to: '/sequence-analysis' },
    ],
  },
  contact: {
    title: 'Contact and scope',
    banner: 'Project coordination',
    description: 'Scope notes, suggested roles, and collaboration-facing summary of the platform.',
    primaryLabel: 'Reference modules',
    primaryLinks: [
      { label: 'Docs', to: '/docs', exact: true },
      { label: 'Guide', to: '/guide' },
      { label: 'Contact', to: '/contact' },
    ],
    relatedLinks: [
      { label: 'Gateway', to: '/' },
    ],
  },
}

const isLanding = computed(() => Boolean(route.meta?.landing))
const noSidebar = computed(() => Boolean(route.meta?.noSidebar))
const currentSection = computed(() => sectionConfig[route.meta?.section || 'overview'])
const pageTitle = computed(() => route.meta?.title || 'Stoichioomics Platform')
const pageSubtitle = computed(() => route.meta?.subtitle || currentSection.value.description)
const sidebarGroups = computed(() => {
  const section = currentSection.value || {}
  const groups = []
  const domainLinks = section.primaryLinks || section.links || []
  const pageLinks = route.meta?.pageLinks || section.pageLinks || []
  const relatedLinks = section.relatedLinks || []
  if (domainLinks.length) {
    groups.push({
      label: section.primaryLabel || 'Domain modules',
      description: section.primaryDescription || '',
      links: domainLinks,
    })
  }
  if (pageLinks.length) {
    groups.push({
      label: 'Current page tools',
      description: 'Anchors and controls that stay on this page.',
      links: pageLinks,
    })
  }
  if (relatedLinks.length) {
    groups.push({
      label: 'Related areas',
      description: 'Cross-domain exits kept separate from this workspace.',
      links: relatedLinks,
    })
  }
  return groups
})

function isTopNavActive(item) {
  if (item.sections?.includes(route.meta?.section)) return true
  if (item.section && route.meta?.section === item.section) return true
  return route.path === item.to
}

function isSideNavActive(item) {
  if (!item?.to || item.type === 'anchor') return false
  const target = typeof item.to === 'string' ? item.to : item.to.path
  if (!target) return false
  if (target === '/') return route.path === '/'
  if (item.exact) return route.path === target
  return route.path === target || route.path.startsWith(`${target}/`)
}
</script>
