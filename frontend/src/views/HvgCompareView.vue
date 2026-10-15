<template>
  <div>
    <div class="panel">
      <div class="section-header">
        <div>
          <div class="eyebrow">Expression/HVG Stoich Extension</div>
          <h3>Compare promoted expression/HVG cases</h3>
          <p class="muted">Compare saved extension cases generated from expression matrices, sample metadata, and mapped stoichiometric feature context.</p>
        </div>
      </div>
      <div class="toolbar-grid">
        <input class="input" v-model="ids" placeholder="case1,case2" />
        <button class="btn" @click="run">Compare Expression/HVG cases</button>
      </div>
    </div>
    <div class="panel" v-if="rows.length">
      <table class="table">
        <thead><tr><th v-for="k in columns" :key="k">{{ k }}</th></tr></thead>
        <tbody><tr v-for="(r,idx) in rows" :key="idx"><td v-for="k in columns" :key="k">{{ r[k] }}</td></tr></tbody>
      </table>
    </div>
  </div>
</template>
<script setup>
import { ref, computed } from 'vue'
import { compareCases } from '../api/registry'
const ids = ref('')
const rows = ref([])
const columns = computed(() => rows.value.length ? Object.keys(rows.value[0]) : [])
const run = async () => { rows.value = await compareCases(ids.value.split(',').map(x => x.trim()).filter(Boolean)) }
</script>
