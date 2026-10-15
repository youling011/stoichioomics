<template>
  <section class="home-section home-glance-section">
    <div class="home-section-head">
      <div>
        <h2><span aria-hidden="true">▮</span> Platform at a Glance</h2>
      </div>
      <router-link to="/quality">View all statistics <span aria-hidden="true">›</span></router-link>
    </div>

    <div class="home-glance-grid">
      <article class="home-chart-card">
        <h3>1. Species Distribution (Six Clades)</h3>
        <EChart :option="treemapOption" :height="250" export-name="home_species_distribution" />
      </article>
      <article class="home-chart-card home-readiness-card">
        <h3>2. Omics Coverage Across Clades</h3>
        <EChart :option="coverageOption" :height="250" export-name="home_omics_coverage" />
      </article>
      <article class="home-chart-card">
        <h3>3. Feature Family Readiness (Representative Species)</h3>
        <EChart v-if="hasReadinessData" :option="readinessOption" :height="250" export-name="home_feature_readiness" />
        <div v-else class="home-na-heatmap">
          <div class="home-na-head">
            <span></span>
            <span v-for="column in readiness.columns" :key="column">{{ column }}</span>
          </div>
          <div v-for="row in readiness.rows" :key="row.species_id" class="home-na-row">
            <strong>{{ row.label }}</strong>
            <span v-for="column in readiness.columns" :key="column">N/A</span>
          </div>
          <p>{{ readiness.method || 'No cached Feature Hub readiness profile is available.' }}</p>
        </div>
      </article>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import EChart from '../EChart.vue'
import { homeOmicsCoverageOption, homeReadinessHeatmapOption, homeTreemapOption } from '../../utils/homeCharts'

const props = defineProps({
  clades: { type: Array, default: () => [] },
  coverage: { type: Array, default: () => [] },
  readiness: { type: Object, default: () => ({ columns: [], rows: [] }) },
})

const treemapOption = computed(() => homeTreemapOption(props.clades))
const coverageOption = computed(() => homeOmicsCoverageOption(props.coverage))
const readinessOption = computed(() => homeReadinessHeatmapOption(props.readiness))
const hasReadinessData = computed(() => (props.readiness?.rows || []).some(row => (row.values || []).some(value => value !== null && value !== undefined)))
</script>
