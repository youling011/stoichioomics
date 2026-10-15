<template>
  <div class="stack-lg">
    <section v-if="loading" class="panel">
      <p class="muted">Loading release payload...</p>
    </section>

    <section v-else-if="loadError" class="panel">
      <p class="muted">{{ loadError }}</p>
      <button class="btn subtle" @click="load">Retry</button>
    </section>

    <template v-else-if="payload">
      <ActiveReleaseBanner :release="payload.active_release" :show-release-link="false" />

      <section class="panel">
        <div class="section-header">
          <div>
            <div class="eyebrow">Active release</div>
            <h3>{{ payload.active_release.label }}</h3>
            <p class="muted">{{ payload.active_release.description || 'Formal release record registered for the active PostgreSQL registry.' }}</p>
          </div>
        </div>
        <div class="grid grid-4">
          <div class="mini-card">
            <div class="label">Release ID</div>
            <div class="metric-inline">{{ payload.active_release.release_id }}</div>
          </div>
          <div class="mini-card">
            <div class="label">Database</div>
            <div class="metric-inline">{{ payload.active_release.database_engine }}</div>
          </div>
          <div class="mini-card">
            <div class="label">Species</div>
            <div class="metric-inline">{{ payload.active_release.species_count }}</div>
          </div>
          <div class="mini-card">
            <div class="label">Rows</div>
            <div class="metric-inline">{{ payload.active_release.entity_row_count }}</div>
          </div>
        </div>
      </section>

      <section v-if="payload.model_release?.available" class="panel release-grade-panel">
        <div class="section-header compact">
          <div>
            <div class="eyebrow">Scoped model-organism release</div>
            <h3>{{ payload.model_release.release.label }}</h3>
            <p class="muted">Release-grade StorageObject, Parquet read layer and gate status for the model-organism scope.</p>
          </div>
          <span :class="['badge', payload.model_release.release.status === 'published' ? 'status-ready' : 'status-muted']">
            {{ payload.model_release.release.status }}
          </span>
        </div>
        <div class="grid grid-4">
          <div class="mini-card"><div class="label">Release ID</div><div class="metric-inline">{{ payload.model_release.release.release_id }}</div></div>
          <div class="mini-card"><div class="label">Species</div><div class="metric-inline">{{ payload.model_release.release.species_count }}</div></div>
          <div class="mini-card"><div class="label">Datasets</div><div class="metric-inline">{{ payload.model_release.release.dataset_count }}</div></div>
          <div class="mini-card"><div class="label">Schema</div><div class="metric-inline">{{ payload.model_release.release.schema_version || '-' }}</div></div>
        </div>
        <div class="table-wrap compact-top">
          <table class="table compact-table">
            <thead><tr><th>Gate</th><th>Status</th><th>Targets</th></tr></thead>
            <tbody>
              <tr v-for="gate in payload.model_release.qc_gates || []" :key="gate.gate">
                <td>{{ gate.gate }}</td>
                <td><span :class="['badge', gate.status === 'pass' ? 'status-ready' : 'status-muted']">{{ gate.status }}</span></td>
                <td>{{ gate.summary?.targets || gate.summary?.gate_summary?.G5_file_qc?.parquet_pass || '-' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="metric-band compact-top">
          <span class="badge">Immutable {{ payload.model_release.release.is_immutable ? 'yes' : 'no' }}</span>
          <span class="badge">Manifest SHA256 {{ payload.model_release.release.manifest_sha256 ? 'registered' : 'pending' }}</span>
          <span class="badge">Schemas {{ payload.model_release.schema_registry?.active || 0 }} / {{ payload.model_release.schema_registry?.total || 0 }}</span>
        </div>
      </section>

      <section v-if="payload.functional_annotation_release" class="panel">
        <div class="section-header compact">
          <div>
            <div class="eyebrow">Functional annotation release</div>
            <h3>{{ payload.functional_annotation_release.label }}</h3>
            <p class="muted">{{ payload.functional_annotation_release.source_dir }}</p>
          </div>
          <router-link class="btn subtle" to="/downloads">Download annotations</router-link>
        </div>
        <div class="grid grid-4">
          <div class="mini-card"><div class="label">Species</div><div class="metric-inline">{{ payload.functional_annotation_release.species_total }}</div></div>
          <div class="mini-card"><div class="label">GO species</div><div class="metric-inline">{{ payload.functional_annotation_release.go_species_count }}</div></div>
          <div class="mini-card"><div class="label">KEGG species</div><div class="metric-inline">{{ payload.functional_annotation_release.kegg_species_count }}</div></div>
          <div class="mini-card"><div class="label">KEGG links</div><div class="metric-inline">{{ payload.functional_annotation_release.kegg_link_count }}</div></div>
        </div>
      </section>

      <section v-if="payload.phylogeny_release" class="panel">
        <div class="section-header compact">
          <div>
            <div class="eyebrow">Phylogeny release</div>
            <h3>{{ payload.phylogeny_release.label }}</h3>
            <p class="muted">Active tree release bound to platform P3 phylogeny-aware views and runtime statistics.</p>
          </div>
          <router-link class="btn subtle" to="/downloads">View tree files</router-link>
        </div>
        <div class="grid grid-4">
          <div class="mini-card"><div class="label">Release ID</div><div class="metric-inline">{{ payload.phylogeny_release.release_id }}</div></div>
          <div class="mini-card"><div class="label">Taxonomy tips</div><div class="metric-inline">{{ payload.phylogeny_release.summary?.tip_count }}</div></div>
          <div class="mini-card"><div class="label">Analysis tips</div><div class="metric-inline">{{ payload.phylogeny_release.p2?.analysis_grade_tree?.tip_count || '-' }}</div></div>
          <div class="mini-card"><div class="label">PGLS</div><div class="metric-inline">{{ payload.phylogeny_release.p2?.analysis_readiness?.pgls_eligible ? 'ready' : 'blocked' }}</div></div>
        </div>
      </section>

      <section class="grid grid-2">
        <article class="panel">
          <div class="section-header compact"><h3>Provenance</h3></div>
          <ul class="clean-list compact-list">
            <li><strong>Storage:</strong> {{ payload.provenance.storage_engine }}</li>
            <li><strong>Import mode:</strong> {{ payload.provenance.import_mode }}</li>
            <li><strong>Release registration:</strong> {{ payload.provenance.release_registration }}</li>
            <li><strong>Source root:</strong> {{ payload.active_release.source_root || 'Not registered' }}</li>
            <li><strong>Pipeline root:</strong> {{ payload.active_release.pipeline_root || 'Not registered' }}</li>
          </ul>
        </article>
        <article class="panel">
          <div class="section-header compact"><h3>Manifest snapshot</h3></div>
          <pre>{{ JSON.stringify(payload.active_release.manifest || {}, null, 2) }}</pre>
        </article>
      </section>

      <section class="panel">
        <div class="section-header compact"><h3>Release history</h3></div>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>Label</th>
                <th>Release ID</th>
                <th>Created</th>
                <th>Species</th>
                <th>Datasets</th>
                <th>Rows</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in payload.history || []" :key="row.release_id">
                <td>{{ row.label }}</td>
                <td>{{ row.release_id }}</td>
                <td>{{ row.created_at || 'NA' }}</td>
                <td>{{ row.species_count }}</td>
                <td>{{ row.dataset_count }}</td>
                <td>{{ row.entity_row_count }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>

    <section v-else class="panel">
      <p class="muted">No release payload is available.</p>
    </section>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import ActiveReleaseBanner from '../components/ActiveReleaseBanner.vue'
import { getRelease } from '../api/stoichdb'

const payload = ref(null)
const loading = ref(true)
const loadError = ref('')

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    payload.value = await getRelease()
  } catch (error) {
    payload.value = null
    loadError.value =
      error?.response?.data?.error?.message ||
      error?.response?.data?.message ||
      error?.message ||
      'Failed to load release payload.'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>
