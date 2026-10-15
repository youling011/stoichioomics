<template>
  <div class="stack-lg">
    <section class="hero-panel hub-hero">
      <div class="hero-copy">
        <div class="eyebrow">Results & analysis hub</div>
        <h1>Stored species results and analysis</h1>
        <p>
          This internal hub keeps stored-database result browsing, visualization, analysis, and comparison under one
          entry. It uses curated genome, transcript sequence, and proteome feature tables already registered in the
          database and does not launch user-owned runtime workflows.
        </p>
        <div class="metric-band">
          <span class="divider-chip">Existing species data</span>
          <span class="divider-chip">Visualization + analysis</span>
          <span class="divider-chip">Cross-species comparison</span>
        </div>
      </div>
      <div class="panel hub-note">
        <div class="eyebrow">Recommended order</div>
        <ol class="numbered-list">
          <li>Start with species query and filtering.</li>
          <li>Open one species explorer for genome, transcript sequence, or proteome results.</li>
          <li>Use visualization, deep analysis, or comparison modules as needed.</li>
        </ol>
      </div>
    </section>

    <section class="hub-card-grid">
      <router-link v-for="item in modules" :key="item.to" :to="item.to" class="feature-card hub-card">
        <div class="eyebrow">{{ item.tag }}</div>
        <h3>{{ item.title }}</h3>
        <p class="muted">{{ item.description }}</p>
        <div class="hub-card-footer">
          <span class="badge">{{ item.badge }}</span>
          <span class="ghost-link">Open</span>
        </div>
      </router-link>
    </section>
  </div>
</template>

<script setup>
const modules = [
  {
    to: '/database',
    tag: 'Step 1',
    title: 'Species query and registry',
    description: 'Search, filter, and select stored species records. This is the main query entrance for existing database data.',
    badge: 'Query',
  },
  {
    to: '/visualization',
    tag: 'Step 2',
    title: 'Foundational visualization',
    description: 'Open genome, transcript sequence, proteome, and cross-omics visual summaries based on stored feature tables.',
    badge: 'Basic plots',
  },
  {
    to: '/analysis',
    tag: 'Step 3',
    title: 'Deep analysis modules',
    description: 'Inspect strategy typing, outliers, coupling networks, trade-offs, and omics-specific analysis artifacts.',
    badge: 'Deep analysis',
  },
  {
    to: '/compare',
    tag: 'Step 4',
    title: 'Cross-species comparison',
    description: 'Compare multiple species with stoichiometric fingerprints, rankings, distances, and grouped summaries.',
    badge: 'Compare',
  },
  {
    to: '/case-studies',
    tag: 'Step 5',
    title: 'Stage 6 case studies',
    description: 'Open internal-data descriptive cases for species fingerprints, cross-omics coupling, and candidate protein interpretation.',
    badge: 'Case study',
  },
]
</script>
