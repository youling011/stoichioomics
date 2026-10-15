<template>
  <div class="panel">
    <div class="section-header compact">
      <div>
        <h3>{{ exportState.export_id || 'No export selected' }}</h3>
        <p class="muted">{{ exportState.status || 'Idle' }}</p>
      </div>
      <a v-if="exportState.status === 'completed'" class="btn" :href="downloadUrl(exportState.export_id)">Download ZIP</a>
    </div>
    <div v-if="exportState.manifest" class="table-wrap">
      <table class="table compact-table">
        <tbody>
          <tr><th>Omics</th><td>{{ exportState.manifest.omics }}</td></tr>
          <tr><th>Scope</th><td>{{ exportState.manifest.scope }}</td></tr>
          <tr><th>Rows</th><td>{{ exportState.manifest.row_count }}</td></tr>
          <tr><th>Features</th><td>{{ (exportState.manifest.selected_features || []).join(', ') }}</td></tr>
        </tbody>
      </table>
    </div>
    <div v-if="exportState.error" class="annotation">{{ exportState.error }}</div>
  </div>
</template>

<script setup>
import { featureHubExportDownloadUrl } from '../../api/stoichdb'

defineProps({ exportState: { type: Object, default: () => ({}) } })

function downloadUrl(id) {
  return featureHubExportDownloadUrl(id)
}
</script>

