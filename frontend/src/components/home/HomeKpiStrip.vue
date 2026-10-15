<template>
  <section class="home-kpi-strip" aria-label="Homepage key metrics">
    <article v-for="item in items" :key="item.label" class="home-kpi-card">
      <img :src="item.icon" alt="" aria-hidden="true" />
      <div>
        <strong>{{ item.value }}</strong>
        <span>{{ item.label }}</span>
        <small>{{ item.note }}</small>
      </div>
    </article>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import speciesIcon from '../../assets/home/kpi-species.svg'
import omicsIcon from '../../assets/home/kpi-omics.svg'
import coreIcon from '../../assets/home/kpi-core.svg'
import fullIcon from '../../assets/home/kpi-full.svg'
import entitiesIcon from '../../assets/home/kpi-entities.svg'
import casesIcon from '../../assets/home/kpi-cases.svg'

const props = defineProps({
  kpis: { type: Object, default: () => ({}) },
})

const items = computed(() => [
  {
    label: 'Species',
    value: props.kpis?.species?.label ?? '—',
    note: 'Across 6 clades',
    icon: speciesIcon,
  },
  {
    label: 'Omics Layers',
    value: props.kpis?.omics_layers ?? '—',
    note: 'Genome · Transcriptome · Proteome',
    icon: omicsIcon,
  },
  {
    label: 'Core Features',
    value: props.kpis?.core_fields ?? '—',
    note: 'Curated for ML',
    icon: coreIcon,
  },
  {
    label: 'Full Fields',
    value: props.kpis?.full_fields ?? '—',
    note: 'Browse & Download',
    icon: fullIcon,
  },
  {
    label: 'Indexed Entities',
    value: props.kpis?.indexed_entities?.label ?? '—',
    note: 'Genes · Transcripts · Proteins',
    icon: entitiesIcon,
  },
  {
    label: 'Case Studies',
    value: props.kpis?.case_stage ?? 'N/A',
    note: `${props.kpis?.case_count ?? 0} real-world analyses`,
    icon: casesIcon,
  },
])
</script>
