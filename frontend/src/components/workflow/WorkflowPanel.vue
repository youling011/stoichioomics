<template>
 <div ref="host" class="workflow-panel-viewport" :style="{minHeight:(height+34)+'px'}">
  <template v-if="visible">
   <div v-if="option.dataZoom?.length || panel.type==='heatmap'" class="workflow-full-export"><button class="chart-export-btn" type="button" :disabled="exporting" @click="exportFullSVG">SVG all rows</button><span>Zoom changes the view; CSV/TSV retain all saved rows.</span></div>
   <EChart :option="option" :height="height" :auto-loading="false" :show-data-exports="false" :export-name="exportName+(option.dataZoom?.length?'_viewport':'')" @chart-click="event=>$emit('chart-click',event)" />
   <p v-if="exportError" role="alert">{{ exportError }}</p>
  </template>
  <p v-else class="workflow-panel-placeholder">Scroll to view this complete saved-data panel.</p>
 </div>
</template>
<script setup>
import {ref,computed,toRaw,onMounted,onBeforeUnmount} from 'vue'
import EChart from '../EChart.vue'
import {buildPanelOption} from '../../utils/workflowVisuals/shared'
import * as echarts from 'echarts'
const props=defineProps({panel:Object,height:Number,exportName:String})
const width=ref(900)
const option=computed(()=>buildPanelOption(toRaw(props.panel),{width:width.value,height:props.height}))
defineEmits(['chart-click'])
const host=ref(null),visible=ref(false)
const exporting=ref(false),exportError=ref('')
async function exportFullSVG(){
 exporting.value=true;exportError.value='';let chart
 try{
  const panel=toRaw(props.panel),rows=panel.y_categories?.length||new Set((panel.rows||[]).map(r=>r.field||r.feature_key||r.category)).size
  const fullHeight=Math.max(props.height,rows*17+150),fullWidth=Math.max(900,(panel.x_categories?.length||0)*24)
  const full=buildPanelOption(panel,{width:fullWidth,height:fullHeight});delete full.dataZoom
  chart=echarts.init(null,null,{renderer:'svg',ssr:true,width:fullWidth,height:fullHeight});chart.setOption(full)
  const blob=new Blob([chart.renderToSVGString()],{type:'image/svg+xml;charset=utf-8'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=props.exportName+'_all_rows.svg';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)
 }catch(e){exportError.value='Full-range SVG export failed: '+e.message}finally{chart?.dispose();exporting.value=false}
}
let observer,resizeObserver
onMounted(()=>{
 width.value=host.value.clientWidth||900;resizeObserver=new ResizeObserver(entries=>{width.value=entries[0]?.contentRect.width||900});resizeObserver.observe(host.value)
 if(typeof IntersectionObserver==='undefined'){visible.value=true;return}
 observer=new IntersectionObserver(entries=>{visible.value=entries.some(e=>e.isIntersecting)},{root:host.value.closest('.workflow-panels'),rootMargin:'100px 0px',threshold:0})
 observer.observe(host.value)
})
onBeforeUnmount(()=>{observer?.disconnect();resizeObserver?.disconnect()})
</script>
<style scoped>
.workflow-panel-viewport{width:100%;min-width:0}.workflow-panel-placeholder{color:#536E88;font-size:.76rem;padding:15px 4px}
.workflow-full-export{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:.7rem;color:#536E88}.chart-export-btn{border:1px solid rgba(42,89,140,.16);background:#fff;color:#1f5d9a;border-radius:999px;padding:5px 10px;font-size:.75rem;cursor:pointer}
</style>
