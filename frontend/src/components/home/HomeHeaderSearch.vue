<template>
  <div id="home-search" class="home-search">
    <div class="home-search-row">
      <span class="home-search-icon" aria-hidden="true">⌕</span>
      <input
        v-model="query"
        class="home-search-input"
        placeholder="Search species, genes, features, GO terms, pathways..."
        @keyup.enter="submitSearch"
      />
      <button class="home-search-submit" type="button" :disabled="searching" @click="submitSearch">Search</button>
    </div>

    <div v-if="searching" class="home-search-state">Searching registry, entities, and modules...</div>
    <div v-else-if="searchResults" class="home-search-results">
      <article v-for="group in searchResultGroups" :key="group.key" class="home-search-group">
        <div class="home-search-group-head">
          <strong>{{ group.label }}</strong>
          <span>{{ group.count }}</span>
        </div>
        <button
          v-for="item in group.items"
          :key="item.key"
          type="button"
          class="home-search-result"
          @click="go(item.route)"
        >
          <strong>{{ item.title }}</strong>
          <span>{{ item.subtitle }}</span>
        </button>
      </article>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { searchPlatform } from '../../api/stoichdb'

const router = useRouter()
const query = ref('')
const searching = ref(false)
const searchResults = ref(null)

const searchResultGroups = computed(() => {
  const payload = searchResults.value || {}
  return [
    {
      key: 'species',
      label: 'Species',
      count: payload.species?.length || 0,
      items: (payload.species || []).slice(0, 4).map(item => ({
        key: `species-${item.species_id}`,
        route: item.route,
        title: item.display_name,
        subtitle: item.source_context || 'Registry species',
      })),
    },
    {
      key: 'entities',
      label: 'Entities',
      count: payload.entities?.length || 0,
      items: (payload.entities || []).slice(0, 4).map(item => ({
        key: `entity-${item.species_id}-${item.omics}-${item.entity_id}`,
        route: item.route,
        title: item.entity_id,
        subtitle: `${item.gene_name || '-'} / ${item.species_name || item.species_id} / ${item.omics}`,
      })),
    },
    {
      key: 'modules',
      label: 'Modules',
      count: payload.modules?.length || 0,
      items: (payload.modules || []).slice(0, 4).map(item => ({
        key: `module-${item.route}`,
        route: item.route,
        title: item.label,
        subtitle: item.summary,
      })),
    },
  ]
})

function go(route) {
  if (route) router.push(route)
}

async function submitSearch() {
  const value = query.value.trim()
  if (!value) {
    searchResults.value = null
    return
  }
  searching.value = true
  try {
    const result = await searchPlatform(value, 12)
    searchResults.value = result
    if (result.species?.length === 1 && !result.entities?.length) {
      router.push(result.species[0].route)
    }
  } finally {
    searching.value = false
  }
}
</script>
