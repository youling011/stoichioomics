<template>
  <div class="key-feature-map">
    <article v-for="group in groups" :key="group.omics" class="key-feature-column">
      <div class="key-feature-head">
        <div class="eyebrow">{{ group.label }}</div>
        <strong>{{ group.items.length }} displayed fields</strong>
      </div>
      <div class="key-feature-families">
        <section v-for="family in group.families" :key="`${group.omics}-${family.name}`" class="feature-family-block">
          <div class="feature-family-title">{{ formatFamily(family.name) }}</div>
          <div class="feature-chip-wrap">
            <span
              v-for="item in family.items"
              :key="item.field"
              class="feature-chip"
              :title="item.description_short || item.description || item.field"
            >
              {{ item.label || item.field }}
            </span>
          </div>
        </section>
      </div>
    </article>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  schema: { type: Object, default: () => ({}) },
  limitPerFamily: { type: Number, default: 6 },
})

const omicsLabels = {
  genome: 'Genome',
  transcriptome: 'Transcript sequence',
  proteome: 'Proteome',
}

const groups = computed(() => {
  const schemaOmics = props.schema?.omics || {}
  return ['genome', 'transcriptome', 'proteome']
    .filter((omics) => Array.isArray(schemaOmics[omics]))
    .map((omics) => {
      const items = schemaOmics[omics].filter((item) => item?.allow_in_basic !== false)
      const familiesByName = new Map()
      for (const item of items) {
        const family = item.family || 'other'
        if (!familiesByName.has(family)) familiesByName.set(family, [])
        familiesByName.get(family).push(item)
      }
      const families = [...familiesByName.entries()].map(([name, familyItems]) => ({
        name,
        items: familyItems.slice(0, props.limitPerFamily),
      }))
      return {
        omics,
        label: omicsLabels[omics] || omics,
        items,
        families,
      }
    })
})

function formatFamily(value) {
  return String(value || 'other').replaceAll('_', ' ')
}
</script>
