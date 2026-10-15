<template>
  <div class="stack-lg">
    <section class="panel">
      <div class="section-header">
        <div>
          <div class="eyebrow">User workflow jobs</div>
          <h3>Expression/HVG and custom analysis tasks</h3>
          <p class="muted">This branch is intended for user-owned inputs, especially sequence-oriented files and Expression/HVG Stoich Extension jobs.</p>
        </div>
        <div class="row">
          <router-link class="btn secondary" to="/create">Create a new job</router-link>
          <button class="btn" @click="load">Refresh</button>
        </div>
      </div>
      <div class="table-wrap">
        <table class="table">
          <thead><tr><th>Job ID</th><th>Name</th><th>Status</th><th>Mode</th><th>Updated</th><th></th></tr></thead>
          <tbody>
            <tr v-for="job in jobs" :key="job.job_id">
              <td>{{ job.job_id }}</td>
              <td>{{ job.name }}</td>
              <td><span class="badge">{{ job.status }}</span></td>
              <td>{{ job.recommended_mode || '-' }}</td>
              <td>{{ job.updated_at }}</td>
              <td><router-link :to="`/jobs/${job.job_id}`">Open</router-link></td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { listJobs } from '../api/jobs'
const jobs = ref([])
const load = async () => jobs.value = await listJobs()
onMounted(load)
</script>
