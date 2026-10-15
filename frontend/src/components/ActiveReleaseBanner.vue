<template>
  <section class="panel release-banner">
    <div class="section-header compact">
      <div>
        <div class="eyebrow">Active release</div>
        <h3>{{ releaseLabel }}</h3>
        <p class="muted">{{ releaseDescription }}</p>
      </div>
      <router-link v-if="showReleaseLink" class="ghost-link" to="/release">Open release</router-link>
    </div>
    <div class="release-banner-grid">
      <div class="mini-card">
        <div class="label">Release ID</div>
        <div class="metric-inline">{{ releaseValue('release_id') }}</div>
      </div>
      <div class="mini-card">
        <div class="label">Species</div>
        <div class="metric-inline">{{ releaseValue('species_count') }}</div>
      </div>
      <div class="mini-card">
        <div class="label">Omics coverage</div>
        <div class="metric-inline">{{ omicsCoverageText }}</div>
      </div>
      <div class="mini-card">
        <div class="label">Data mode</div>
        <div class="metric-inline">{{ dataMode }}</div>
      </div>
      <div class="mini-card">
        <div class="label">Updated</div>
        <div class="metric-inline">{{ updatedAt }}</div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { omicsLabel } from '../constants/platformTerminology'

const props = defineProps({
  release: { type: Object, default: () => ({}) },
  omicsCoverage: { type: Array, default: () => [] },
  showReleaseLink: { type: Boolean, default: true },
})

const releaseLabel = computed(() => props.release?.label || props.release?.release_id || 'Fallback release metadata')
const releaseDescription = computed(() =>
  props.release?.description ||
  'Release metadata is shown from the active backend payload; missing values use fallback labels until the release record is registered.',
)

const dataMode = computed(() =>
  props.release?.metadata?.data_mode ||
  props.release?.manifest?.data_mode ||
  props.release?.database_engine ||
  'fallback',
)

const updatedAt = computed(() => props.release?.updated_at || props.release?.created_at || 'Not registered')

const omicsCoverageText = computed(() => {
  if (props.omicsCoverage?.length) {
    return props.omicsCoverage
      .map((row) => `${omicsLabel(row.omics)} ${row.count ?? row.dataset_count ?? row.row_count ?? 0}`)
      .join(' / ')
  }
  const datasetCount = props.release?.dataset_count
  return datasetCount === undefined || datasetCount === null ? 'Not registered' : `${datasetCount} datasets`
})

function releaseValue(key) {
  const value = props.release?.[key]
  return value === undefined || value === null || value === '' ? 'Not registered' : value
}
</script>
