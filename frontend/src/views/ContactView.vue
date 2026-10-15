<template>
  <div v-if="payload" class="stack-lg">
    <section class="panel">
      <div class="section-header">
        <div>
          <div class="eyebrow">Project contact</div>
          <h3>Coordination and platform scope</h3>
        </div>
      </div>
      <div class="grid grid-3">
        <div class="feature-card" v-for="item in payload.contacts" :key="item.label">
          <div class="label">{{ item.label }}</div>
          <p>{{ item.value }}</p>
        </div>
      </div>
    </section>

    <section class="panel">
      <div class="section-header compact"><h3>Current capability summary</h3></div>
      <ul class="clean-list compact-list">
        <li v-for="item in payload.capabilities" :key="item">{{ item }}</li>
      </ul>
      <div class="annotation">For a production-scale release, these capabilities connect to a far larger public registry while preserving the same frontend layout and API contract.</div>
    </section>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { getContact } from '../api/stoichdb'

const payload = ref(null)

onMounted(async () => {
  payload.value = await getContact()
})
</script>
