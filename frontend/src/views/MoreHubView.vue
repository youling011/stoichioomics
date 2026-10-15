<template>
  <div class="stack-lg">
    <section class="hero-panel hub-hero">
      <div class="hero-copy">
        <div class="eyebrow">Other modules</div>
        <h1>Operations, reference, and support pages</h1>
        <p>
          Modules that are not part of the core top navigation are preserved here. This keeps the main navigation compact
          while retaining release, quality, documentation, guide, contact, and legacy utility pages.
        </p>
      </div>
      <div class="panel hub-note">
        <div class="eyebrow">Navigation rule</div>
        <p class="muted">
          Nothing has been removed. These entries are grouped to reduce top-bar noise and keep the main platform path clear.
        </p>
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
    to: '/release',
    tag: 'Operations',
    title: 'Release and provenance',
    description: 'Inspect the active PostgreSQL release, import manifest, provenance chain, and registered counts.',
    badge: 'Release',
  },
  {
    to: '/quality',
    tag: 'Operations',
    title: 'Quality control',
    description: 'Review omics completeness, QC coverage, source-file health, and artifact readiness.',
    badge: 'QC',
  },
  {
    to: '/docs',
    tag: 'Reference',
    title: 'API and data dictionary',
    description: 'Read backend endpoints, data contracts, and schema-level field descriptions.',
    badge: 'Docs',
  },
  {
    to: '/guide',
    tag: 'Reference',
    title: 'Platform guide',
    description: 'Review usage flow, assumptions, feature-table contracts, and practical operating notes.',
    badge: 'Guide',
  },
  {
    to: '/contact',
    tag: 'Support',
    title: 'Contact and scope',
    description: 'Open collaboration notes, platform scope, and coordination-facing information.',
    badge: 'Contact',
  },
  {
    to: '/jobs',
    tag: 'Legacy utility',
    title: 'Job utilities',
    description: 'Access the earlier generic job list and creation pages retained for compatibility.',
    badge: 'Jobs',
  },
]
</script>
