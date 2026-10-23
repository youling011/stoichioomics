<template>
  <div v-if="state.available || state.loading || state.error" class="card hvg-research-scope">
    <div class="row" v-if="state.available">
      <label>Analysis run<select class="input" v-model="state.run"><option v-for="r in state.runs" :key="r.analysis_run_id" :value="r.analysis_run_id">{{r.analysis_run_id}} · {{r.research_status}}</option></select></label>
      <label>Analysis context<select class="input" v-model="state.context"><option v-for="c in state.summary.contexts || []" :key="c.context_id" :value="c.context_id">{{c.context_id}} · H {{c.H}} / N {{c.N}}</option></select></label>
      <button class="btn secondary" :disabled="state.loading" @click="state.refresh">Refresh status</button>
    </div>
    <p v-if="state.loading" role="status">Loading run results…</p>
    <p v-if="state.error" role="alert">{{state.error}} <button class="btn secondary" @click="state.refresh">Retry</button></p>
    <p v-if="state.available" class="muted">Research status: {{state.summary.status}} · Annotation release: {{state.summary.presentation?.annotation_snapshot_id || 'Not recorded'}} <template v-if="state.summary.model_policy !== 'removed'">· Historical optional model: {{state.summary.model_status || 'Not run'}}</template><template v-else>· Unified non-model workflow</template>. All ten sections use this run and context.</p>
  </div>
</template>
<script setup>
defineProps({state:{type:Object,required:true}})
</script>
<style scoped>
.hvg-research-scope label{display:flex;flex-direction:column;gap:6px;max-width:100%;min-width:160px}.hvg-research-scope .row{align-items:end}.hvg-research-scope select{max-width:100%;overflow:hidden}.hvg-research-scope p{overflow-wrap:anywhere;margin-bottom:0;font-size:.85rem;color:var(--text-soft)}.hvg-research-scope label{font-size:.85rem;font-weight:600}.hvg-research-scope .row{gap:16px}.hvg-research-scope label:first-child{flex:1;min-width:220px;max-width:640px}.hvg-research-scope .input{min-height:40px}@media(max-width:760px){.hvg-research-scope label,.hvg-research-scope label:first-child{width:100%;min-width:0;max-width:100%}.hvg-research-scope .input,.hvg-research-scope .btn{min-height:44px}}
</style>
