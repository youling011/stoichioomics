<template>
  <div class="stack-lg">
    <section v-if="loading" class="panel">
      <div class="section-header compact">
        <div>
          <div class="eyebrow">Loading</div>
          <h3>Loading homepage data</h3>
          <p class="muted">The frontend is waiting for the registry summary and featured species.</p>
        </div>
      </div>
    </section>

    <section v-else-if="loadError" class="panel">
      <div class="section-header compact">
        <div>
          <div class="eyebrow">Load error</div>
          <h3>Homepage data did not load</h3>
          <p class="muted">{{ loadError }}</p>
        </div>
        <button class="btn" @click="loadPage">Retry</button>
      </div>
    </section>

    <template v-else-if="home">
      <section class="hero-panel dark-hero">
        <div class="hero-copy">
          <div class="eyebrow">Integrated academic database platform</div>
          <h1>{{ home.project.name }}</h1>
          <p>{{ PLATFORM_POSITIONING }}</p>
          <div class="metric-band">
            <span class="divider-chip">Release {{ home.active_release.label }}</span>
            <span class="divider-chip">{{ home.active_release.database_engine }}</span>
            <span class="divider-chip">{{ home.platform_scope.loaded_species_count }} species</span>
          </div>
          <div class="row actions-row">
            <router-link class="btn secondary" to="/database">Enter database</router-link>
            <router-link class="btn" to="/release">Open release</router-link>
            <router-link class="btn subtle" to="/quality">Open QC</router-link>
          </div>
        </div>

        <div class="hero-visual-stack">
          <div class="grid grid-2">
            <div class="stat-card-dark" v-for="stat in home.stats" :key="stat.label">
              <div class="label">{{ stat.label }}</div>
              <div class="kpi">{{ stat.value }}</div>
            </div>
          </div>
          <div class="glass-card">
            <div class="section-header compact">
              <div>
                <div class="eyebrow">Release context</div>
                <h4>What this build now includes</h4>
              </div>
            </div>
            <ul class="clean-list compact-list">
              <li>Formal PostgreSQL storage with active release registration</li>
              <li>QC, downloads, artifact registry, and source-file routing</li>
              <li>API docs and data dictionary embedded in the platform</li>
            </ul>
          </div>
        </div>
      </section>

      <ActiveReleaseBanner :release="home.active_release" :omics-coverage="home.omics_breakdown" />

      <section class="grid grid-2">
        <article class="panel chart-panel">
          <div class="section-header compact">
            <div>
              <div class="eyebrow">Registry scope</div>
              <h3>Release omics coverage matrix</h3>
            </div>
          </div>
          <EChart :option="omicsChart" :height="330" />
        </article>

        <article class="panel chart-panel">
          <div class="section-header compact">
            <div>
              <div class="eyebrow">Cross-omics key feature map</div>
              <h3>Displayed feature families</h3>
            </div>
          </div>
          <KeyFeatureMap :schema="meta?.feature_display_schema" />
          <MethodBadge
            method="feature display schema"
            normalization="none"
            missing-policy="schema metadata only; no species values on overview"
            note="Feature names are grouped by omics and family so the page does not imply cross-species numeric comparison."
          />
        </article>
      </section>

      <section class="grid grid-4">
        <article class="feature-card" v-for="track in home.analysis_tracks" :key="track.title">
          <div class="eyebrow">Capability branch</div>
          <h3>{{ track.title }}</h3>
          <p class="muted">{{ track.description }}</p>
        </article>
      </section>

      <section class="grid grid-2">
        <article class="panel">
          <div class="section-header compact">
            <div>
              <div class="eyebrow">Platform modules</div>
              <h3>Formal database-platform layers</h3>
            </div>
          </div>
          <ul class="clean-list compact-list">
            <li><router-link to="/release">Release registry</router-link> for version, counts, manifest, and provenance.</li>
            <li><router-link to="/quality">Quality control</router-link> for omics completeness, file coverage, and registry health.</li>
            <li><router-link to="/downloads">Downloads</router-link> for source feature tables and analysis artifacts.</li>
            <li><router-link to="/docs">Docs</router-link> for API contracts and data dictionary.</li>
          </ul>
        </article>
        <article class="panel">
          <div class="section-header compact">
            <div>
              <div class="eyebrow">Release facts</div>
              <h3>Active release snapshot</h3>
            </div>
          </div>
          <ul class="clean-list compact-list">
            <li><strong>Release ID:</strong> {{ home.active_release.release_id }}</li>
            <li><strong>Source root:</strong> {{ home.active_release.source_root || 'Not registered' }}</li>
            <li><strong>Pipeline root:</strong> {{ home.active_release.pipeline_root || 'Not registered' }}</li>
            <li><strong>Feature files:</strong> {{ home.active_release.feature_file_count }}</li>
          </ul>
        </article>
      </section>

      <section class="panel">
        <div class="section-header">
          <div>
            <div class="eyebrow">Featured species · release-grade first</div>
            <h3>Open a species explorer</h3>
          </div>
          <router-link class="ghost-link" to="/database">Browse full registry</router-link>
        </div>
        <div class="grid grid-2">
          <router-link class="species-card" v-for="species in featuredSpecies" :key="species.species_id" :to="`/species/${species.species_id}`">
            <div class="section-header compact">
              <div>
                <h4>{{ species.display_name }}</h4>
                <p class="muted">{{ species.source_context || 'Local registry dataset' }}</p>
              </div>
              <span class="badge" :class="species.is_model_organism ? 'cool-badge' : ''">
                {{ species.is_model_organism ? 'Model release · Parquet' : 'Open species' }}
              </span>
            </div>
            <div class="grid grid-3 dense-grid">
              <div class="mini-card">
                <div class="label">Genome GC%</div>
                <div class="metric-inline">{{ species.genome_gc }}</div>
              </div>
              <div class="mini-card">
                <div class="label">Proteome pI</div>
                <div class="metric-inline">{{ species.proteome_pi }}</div>
              </div>
              <div class="mini-card">
                <div class="label">Omics explorer</div>
                <div class="metric-inline">3 branches</div>
              </div>
            </div>
          </router-link>
        </div>
      </section>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import ActiveReleaseBanner from '../components/ActiveReleaseBanner.vue'
import EChart from '../components/EChart.vue'
import KeyFeatureMap from '../components/KeyFeatureMap.vue'
import MethodBadge from '../components/MethodBadge.vue'
import { getPlatformHome, getPlatformMeta } from '../api/stoichdb'
import { PLATFORM_POSITIONING } from '../constants/platformTerminology'
import { matrixHeatmapOption } from '../utils/charts'

const home = ref(null)
const meta = ref(null)
const loading = ref(true)
const loadError = ref('')

const featuredSpecies = computed(() => home.value?.featured_species || [])
const omicsChart = computed(() => {
  const rows = home.value?.omics_breakdown || []
  const labels = rows.map((row) => row.omics)
  const values = rows.map((row, index) => [index, 0, row.count])
  return matrixHeatmapOption(labels, ['Active release'], values, {
    min: 0,
    max: Math.max(1, ...rows.map((row) => Number(row.count) || 0)),
    scaleType: 'coverage',
    showLabel: true,
  })
})

async function loadPage() {
  loading.value = true
  loadError.value = ''
  try {
    const [homePayload, metaPayload] = await Promise.all([getPlatformHome(), getPlatformMeta()])
    home.value = homePayload
    meta.value = metaPayload
  } catch (error) {
    home.value = null
    meta.value = null
    loadError.value = error?.response?.data?.message || error?.message || 'Backend request failed.'
  } finally {
    loading.value = false
  }
}

onMounted(loadPage)
</script>
