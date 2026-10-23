<template>
  <section class="panel" data-chart-id="B13" data-status="available" :data-species-id="speciesId" data-testid="proteome-field-atlas">
    <div class="section-header"><div><h3>Complete field distribution atlas</h3><p class="muted">{{ manifest.fields.length }} numeric fields · every field uses all of its valid records</p></div><span class="badge">52 Core fields covered</span></div>
    <div class="proteome-controls"><label>Find field<input v-model="query" class="input" placeholder="Field name or group" /></label><label>Group<select v-model="group" class="input"><option value="">All groups</option><option v-for="g in groups" :key="g">{{ g }}</option></select></label><label>Page<select v-model.number="page" class="input" data-testid="field-page"><option v-for="i in Math.max(1,Math.ceil(filtered.length/6))" :key="i" :value="i">{{ i }} / {{ Math.max(1,Math.ceil(filtered.length/6)) }}</option></select></label><span>{{ filtered.length }} matching fields</span></div>
    <p v-if="error" class="muted">{{ error }}</p><div class="proteome-downloads"><a :href="quantileDownload('csv')">Download all field quantiles (CSV)</a><a :href="quantileDownload('tsv')">Download all field quantiles (TSV)</a></div>
    <div class="proteome-field-grid"><section v-for="field in visible" :key="field.key" :data-field="field.key"><h4>{{ label(field.key) }} <span class="muted">({{ field.unit }})</span></h4><EChart v-if="profiles[field.key]" :option="chart(profiles[field.key])" :height="320" :show-data-exports="false" :auto-loading="false" :export-name="`${speciesId}_${scope}_${field.key}_${manifest.artifact_version}`" /><p v-else>{{ loading?'Loading complete field result…':'Field unavailable' }}</p></section></div>
    <div data-chart-id="B14" data-status="available" data-testid="proteome-quantile-table"><h4>Quantiles in original units</h4><p class="muted">P05–P95 summaries describe sequence distributions, not Tukey outlier boxes.</p><div class="table-wrap"><table><thead><tr><th>Field</th><th>Valid / source</th><th>Missing</th><th>Zero</th><th v-for="q in ['Min','P05','P25','Median','P75','P95','Max','Mean']" :key="q">{{ q }}</th></tr></thead><tbody><tr v-for="f in visible" :key="f.key"><td>{{ f.key }}</td><td>{{ profiles[f.key]?.n_valid }} / {{ manifest.n_source }}</td><td>{{ profiles[f.key]?.n_missing }}</td><td>{{ profiles[f.key]?.n_zero }}</td><td v-for="(v,i) in [...(profiles[f.key]?.quantiles||Array(7).fill(null)),profiles[f.key]?.mean]" :key="i">{{ number(v) }}</td></tr></tbody></table></div></div>
  </section>
</template>
<script setup>
import {ref,computed,watch,onBeforeUnmount} from 'vue'
import EChart from '../EChart.vue'
import {getProteomeFields,proteomeExportUrl} from '../../api/proteomeVisuals'
import {figureOption} from '../../utils/proteomeCharts'
import {label,number} from '../../utils/proteomeFormat'
const props=defineProps({speciesId:String,scope:String,manifest:Object});const query=ref(''),group=ref(''),page=ref(1),profiles=ref({}),loading=ref(false),error=ref('');let controller,seq=0
function quantileDownload(format){return proteomeExportUrl(props.speciesId,{scope:props.scope,chart_id:'B14',kind:'chart',format,artifact_version:props.manifest.artifact_version,source_hash:props.manifest.source_hash})}
const groups=computed(()=>[...new Set(props.manifest.fields.map(f=>f.group))]);const filtered=computed(()=>props.manifest.fields.filter(f=>(!group.value||f.group===group.value)&&(`${f.key} ${f.group}`.toLowerCase().includes(query.value.toLowerCase()))));const visible=computed(()=>filtered.value.slice((page.value-1)*6,page.value*6))
watch([query,group],()=>{page.value=1})
watch(()=>[props.speciesId,props.scope,props.manifest.artifact_version,visible.value.map(f=>f.key).join(',')],async()=>{
  const current=++seq;controller?.abort();controller=new AbortController();profiles.value={};if(!visible.value.length)return;loading.value=true;error.value=''
  try{const r=await getProteomeFields(props.speciesId,{scope:props.scope,fields:visible.value.map(f=>f.key).join(','),artifact_version:props.manifest.artifact_version},{signal:controller.signal});if(current===seq)profiles.value=Object.fromEntries(r.profiles.map(p=>[p.field,p]))}catch(e){if(current===seq&&!controller.signal.aborted)error.value=e.message}finally{if(current===seq)loading.value=false}
},{immediate:true})
onBeforeUnmount(()=>{seq++;controller?.abort()})
function chart(profile){const o=figureOption({coverage:{n_source:profile.n_source,n_valid:profile.n_valid},data:{kind:'distribution',profile,log:profile.field==='length_aa'}});o.grid[0].height='48%';o.grid[1].top='66%';o.grid[1].height='14%';return o}
</script>
