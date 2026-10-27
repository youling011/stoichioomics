<template>
 <div v-if="panels.length" class="workflow-status-summary" data-design-part="diagnostics">
  <p><span v-for="p in panels" :key="p.panel_id"><strong>{{p.title}}:</strong> {{summary(p)}}. </span></p>
  <details><summary>All states and exclusions</summary><div class="workflow-status-table"><table class="table compact-table"><thead><tr><th>Evidence</th><th>Context / group</th><th>State</th><th>Saved count</th></tr></thead><tbody><template v-for="p in panels" :key="p.panel_id"><tr v-for="(r,i) in p.rows" :key="p.panel_id+i"><td>{{p.title}}</td><td>{{r.group==='All'?'Complete saved scope':r.group}}</td><td>{{String(r.category).replaceAll('_',' ')}}</td><td>{{r.count.toLocaleString('en-US')}}</td></tr></template></tbody></table></div></details>
 </div>
</template>
<script setup>
defineProps({panels:{type:Array,default:()=>[]}})
function summary(p){const rows=p.rows||[],total=rows.reduce((n,r)=>n+r.count,0);if(rows.length<=3)return rows.map(r=>`${r.count.toLocaleString('en-US')} ${String(r.category).replaceAll('_',' ')}`).join(' · ');return `${total.toLocaleString('en-US')} records across ${rows.length} saved state/group combinations`}
</script>
<style scoped>
.workflow-status-summary{font-size:.74rem;color:var(--text-soft,#536E88);line-height:1.55;padding:5px 0;min-width:0}.workflow-status-summary p{margin:0 0 3px}.workflow-status-summary details{margin:3px 0}.workflow-status-summary summary{cursor:pointer;font-weight:600;color:var(--text-main,#173B64)}.workflow-status-table{max-height:240px;overflow:auto}.workflow-status-table td{overflow-wrap:anywhere}
</style>
