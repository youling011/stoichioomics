<template>
  <section class="home-section compact">
    <h2>Representative Species</h2>
    <div class="home-species-strip">
      <router-link
        v-for="item in species"
        :key="item.species_id"
        class="home-species-card"
        :to="`/species/${item.species_id}`"
      >
        <img :src="speciesIcon(item)" alt="" aria-hidden="true" />
        <div>
          <strong>{{ displayName(item) }}</strong>
          <span>{{ item.source_division || item.domain || 'Published species' }}</span>
        </div>
      </router-link>
    </div>
  </section>
</template>

<script setup>
import ecoliIcon from '../../assets/home/species-ecoli.svg'
import bsubtilisIcon from '../../assets/home/species-bsubtilis.svg'
import yeastIcon from '../../assets/home/species-yeast.svg'
import arabidopsisIcon from '../../assets/home/species-arabidopsis.svg'
import riceIcon from '../../assets/home/species-rice.svg'
import flyIcon from '../../assets/home/species-fly.svg'
import zebrafishIcon from '../../assets/home/species-zebrafish.svg'
import mouseIcon from '../../assets/home/species-mouse.svg'

defineProps({
  species: { type: Array, default: () => [] },
})

const icons = [ecoliIcon, yeastIcon, arabidopsisIcon, riceIcon, flyIcon, zebrafishIcon, mouseIcon, bsubtilisIcon]

function displayName(item) {
  return item.preferred_display_name || item.short_name || item.display_name || item.species_id
}

function speciesIcon(item) {
  const key = `${item.species_id || ''} ${item.display_name || ''}`.toLowerCase()
  if (key.includes('coli')) return ecoliIcon
  if (key.includes('subtilis')) return bsubtilisIcon
  if (key.includes('cerevisiae') || key.includes('yeast')) return yeastIcon
  if (key.includes('thaliana')) return arabidopsisIcon
  if (key.includes('sativa') || key.includes('rice')) return riceIcon
  if (key.includes('melanogaster')) return flyIcon
  if (key.includes('rerio')) return zebrafishIcon
  if (key.includes('musculus') || key.includes('mouse')) return mouseIcon
  return icons[Math.abs(String(item.species_id || '').length) % icons.length]
}
</script>
