<template>
  <div class="stack-lg">
    <section class="panel">
      <div class="section-header">
        <div>
          <div class="eyebrow">Feature Hub</div>
          <h3>Multi-omics Feature Explorer & ML-ready Dataset Builder</h3>
          <p class="muted">Core tables provide machine-learning inputs. Full tables remain available for browsing, field inspection, and download.</p>
        </div>
        <button class="btn subtle" @click="load" :disabled="loading">Refresh</button>
      </div>
      <div v-if="error" class="annotation">{{ error }}</div>
      <div class="grid grid-4">
        <article class="mini-card">
          <div class="label">Species</div>
          <div class="metric-inline">{{ summary.species_count || 0 }}</div>
        </article>
        <article class="mini-card">
          <div class="label">Core columns</div>
          <div class="metric-inline">{{ summary.core_schema_columns || 309 }}</div>
        </article>
        <article class="mini-card">
          <div class="label">Full columns</div>
          <div class="metric-inline">{{ summary.full_schema_columns || 776 }}</div>
        </article>
        <article class="mini-card">
          <div class="label">ML eligible Core</div>
          <div class="metric-inline">{{ summary.ml_eligible_core_fields || 0 }}</div>
        </article>
      </div>
    </section>

    <section class="grid grid-3">
      <router-link class="feature-card" to="/feature-hub/catalog">
        <h4>Feature Catalog</h4>
        <p class="muted">Search every registered Core and Full field with units, ML role, applicability, and composition flags.</p>
      </router-link>
      <router-link class="feature-card" to="/feature-hub/browse">
        <h4>Feature Browser</h4>
        <p class="muted">Preview real rows through server-side paging and inspect cached field profiles.</p>
      </router-link>
      <router-link class="feature-card" to="/feature-hub/builder">
        <h4>ML Dataset Builder</h4>
        <p class="muted">Build Core-only X matrices with metadata, QC report, manifest, recipe, and checksums.</p>
      </router-link>
    </section>

    <section class="panel">
      <div class="section-header compact">
        <div>
          <div class="eyebrow">Registered schemas</div>
          <h3>Core and Full schema coverage</h3>
        </div>
      </div>
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr><th>Omics</th><th>Scope</th><th>Columns</th><th>Status</th><th>Schema</th></tr>
          </thead>
          <tbody>
            <tr v-for="schema in summary.schemas || []" :key="schema.schema_id">
              <td>{{ schema.omics }}</td>
              <td><span class="badge" :class="schema.scope === 'full' ? 'warning-badge' : 'success-badge'">{{ schema.scope }}</span></td>
              <td>{{ schema.column_count }}</td>
              <td>{{ schema.status }}</td>
              <td>{{ schema.schema_id }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="panel">
      <div class="section-header compact">
        <div>
          <div class="eyebrow">Data policy</div>
          <h3>Machine-learning boundary</h3>
        </div>
      </div>
      <ul class="clean-list">
        <li>Core is the only scope available to ML Dataset Builder.</li>
        <li>Full is browse/download only and is never marked ML-ready.</li>
        <li>Identifiers, annotation text, coordinates, and categorical codes are metadata by default.</li>
        <li>Scaler, imputer, PCA, and supervised selectors are emitted as recipe instructions, not fitted globally.</li>
      </ul>
    </section>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { getFeatureHubOverview } from '../api/stoichdb'

const summary = ref({})
const loading = ref(false)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    summary.value = await getFeatureHubOverview()
  } catch (err) {
    error.value = err?.response?.data?.error || err.message || 'Failed to load Feature Hub overview.'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

