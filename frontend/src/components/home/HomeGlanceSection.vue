<template>
  <section class="home-section home-glance-section">
    <div class="home-section-head"><div><h2><span aria-hidden="true">▮</span> Platform at a Glance</h2></div><router-link to="/quality">View all statistics <span aria-hidden="true">›</span></router-link></div>
    <div class="home-glance-grid">
      <article v-for="(id,i) in ids" :key="id" class="home-chart-card" :class="{ 'home-readiness-card': i === 1 }">
        <div class="home-card-frame">
        <div class="home-chart-budget" aria-hidden="true" inert>
          <h3>{{ originalTitles[i] }}</h3>
          <div class="echart-shell"><div class="chart-export-row"><button v-for="label in ['PNG 4x','SVG','CSV','TSV']" :key="label" class="chart-export-btn">{{ label }}</button></div><div class="chart-host" style="height:320px"></div></div>
        </div>
        <div class="home-current-content" :data-chart-id="id">
          <h3>{{ titles[i] }}</h3>
          <div class="home-current-plot">
            <ModuleState v-if="loading" state="loading" />
            <ModuleState v-else-if="error" state="error" :message="error" :retry="retry" />
            <HomeAtlasPlot v-else-if="payload?.cards?.[id]" :card="payload.cards[id]" :meta="payload.meta" :show-exports="true" />
            <ModuleState v-else state="missing" message="Chart data unavailable." />
          </div>
        </div>
        </div>
      </article>
    </div>
  </section>
</template>
<script setup>
import HomeAtlasPlot from '../HomeAtlasPlot.vue'
import ModuleState from '../ModuleState.vue'
defineProps({ payload:Object, loading:Boolean, error:String, retry:Function, clades:Array, coverage:Array, readiness:Object })
const ids=['H1','H2','H3']
const originalTitles=['1. Species Distribution (Six Clades)','2. Omics Coverage Across Clades','3. Feature Family Readiness (Representative Species)']
const titles=['1. Species Scale Across Six Groups','2. Core Record Composition Across Omics','3. Original Core Field Families']
</script>
<style scoped>
.home-card-frame { position:relative; }
.home-readiness-card .home-card-frame { height:calc(322px - 2 * 10px - 2px); }
.home-chart-budget { visibility:hidden;pointer-events:none;user-select:none; }
.home-chart-budget .chart-export-row { display:flex;gap:6px; }
.home-chart-budget .chart-export-btn { border:1px solid rgba(42,89,140,.16);background:rgba(255,255,255,.9);color:#1f5d9a;border-radius:999px;padding:5px 10px;font-size:.75rem; }
.home-current-content { position:absolute;inset:0;display:flex;flex-direction:column;min-width:0;min-height:0; }
.home-current-content h3 { flex-shrink:0; }
.home-current-plot { flex:1;min-height:0;min-width:0; }
</style>
