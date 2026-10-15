<template>
  <div class="home-page">
    <section v-if="loading" class="home-loading">
      <div class="home-skeleton hero"></div>
      <div class="home-skeleton grid"></div>
    </section>

    <section v-else-if="loadError" class="home-load-error">
      <h2>Home data did not load</h2>
      <p>{{ loadError }}</p>
      <button class="home-primary-btn" type="button" @click="loadPage">Retry</button>
    </section>

    <template v-else-if="home">
      <HomeHero :home="home" />
      <HomeKpiStrip :kpis="home.kpis" />
      <HomeGlanceSection
        :clades="home.clade_distribution"
        :coverage="home.omics_coverage"
        :readiness="home.readiness_heatmap"
      />
      <HomeFeatureHubSpotlight
        :spotlight="home.feature_hub_spotlight"
        :representative-species="home.representative_species"
      />
      <HomeModuleGrid />
      <HomeFeaturedAnalyses />
      <HomeSpeciesStrip :species="home.representative_species" />
      <HomeValueChain />
      <HomeFooter :release="home.active_release" />
    </template>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import HomeFeaturedAnalyses from '../components/home/HomeFeaturedAnalyses.vue'
import HomeFeatureHubSpotlight from '../components/home/HomeFeatureHubSpotlight.vue'
import HomeFooter from '../components/home/HomeFooter.vue'
import HomeGlanceSection from '../components/home/HomeGlanceSection.vue'
import HomeHero from '../components/home/HomeHero.vue'
import HomeKpiStrip from '../components/home/HomeKpiStrip.vue'
import HomeModuleGrid from '../components/home/HomeModuleGrid.vue'
import HomeSpeciesStrip from '../components/home/HomeSpeciesStrip.vue'
import HomeValueChain from '../components/home/HomeValueChain.vue'
import { getPlatformHome } from '../api/stoichdb'

const home = ref(null)
const loading = ref(true)
const loadError = ref('')

async function loadPage() {
  loading.value = true
  loadError.value = ''
  try {
    home.value = await getPlatformHome()
  } catch (error) {
    home.value = null
    loadError.value = error?.response?.data?.message || error?.message || 'Backend request failed.'
  } finally {
    loading.value = false
  }
}

onMounted(loadPage)
</script>
