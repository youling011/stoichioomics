<template>
  <section class="home-hero">
    <img class="home-hero-world" :src="worldDots" alt="" aria-hidden="true" />
    <img class="home-hero-bio-left" :src="dnaProtein" alt="" aria-hidden="true" />
    <img class="home-hero-globe-right" :src="globeNetwork" alt="" aria-hidden="true" />
    <div class="home-hero-center">
      <h1>Multi-species Multi-omics<br />Stoichiometric Feature Atlas</h1>
      <p>
        Explore genome, transcriptome, and proteome features across the tree of life
        and build ML-ready handcrafted feature datasets.
      </p>
      <HomeHeaderSearch />
      <div class="home-hero-actions">
        <router-link class="home-primary-btn" to="/database">Explore Database <span aria-hidden="true">›</span></router-link>
        <router-link class="home-secondary-btn" to="/feature-hub">Open Feature Hub <span aria-hidden="true">›</span></router-link>
      </div>
    </div>
  </section>
</template>

<script setup>
import HomeHeaderSearch from './HomeHeaderSearch.vue'
import dnaProtein from '../../assets/home/hero-dna-protein.svg'
import globeNetwork from '../../assets/home/hero-globe-network.svg'
import worldDots from '../../assets/home/hero-world-dots.svg'
</script>
