<template>
 <div ref="host" class="workflow-figure" :data-design-id="packet.chart_id" :data-design-parts="parts">
  <div class="workflow-figure-tools"><button class="chart-export-btn" :disabled="exporting" type="button" @click="exportFigure('png')">PNG complete figure</button><button class="chart-export-btn" :disabled="exporting" type="button" @click="exportFigure('svg')">SVG complete figure</button></div>
  <span v-for="p in visibleParts(packet,{detailField})" :key="p.panel_id" hidden :data-design-part="p.panel_id" />
  <EChart :option="figure.option" :height="figure.height" :auto-loading="false" :show-exports="false" :show-data-exports="false" :export-name="packet.chart_id+'_figure'" @chart-click="clicked" />
  <p v-if="error" role="alert" class="workflow-figure-error">{{error}}</p>
 </div>
</template>
<script setup>
import {ref,computed,onMounted,onBeforeUnmount,toRaw} from 'vue'
import * as echarts from 'echarts'
import EChart from '../EChart.vue'
import {buildFigureOption,visibleParts} from '../../utils/workflowVisuals/figure'
const props=defineProps({packet:Object,height:{type:Number,default:360},detailField:String})
const emit=defineEmits(['inspect']);const host=ref(null),width=ref(800),exporting=ref(false),error=ref('')
const figure=computed(()=>buildFigureOption(toRaw(props.packet),{width:width.value,height:props.height,detailField:props.detailField}))
const parts=computed(()=>visibleParts(props.packet,{detailField:props.detailField}).map(p=>p.panel_id).join(' '))
function clicked(event){const id=event.data?.panel_id||figure.value.option.series[event.seriesIndex]?.workflowPanelId;const p=props.packet.data.panels.find(p=>p.panel_id===id);if(p)emit('inspect',p,event)}
async function exportFigure(format){
 exporting.value=true;error.value='';let chart,sourceURL
 try{
  const full=buildFigureOption(toRaw(props.packet),{width:Math.max(1100,width.value),height:props.height,detailField:props.detailField,full:true})
  chart=echarts.init(null,null,{renderer:'svg',ssr:true,width:full.width,height:full.height});chart.setOption(full.option)
  let blob=new Blob([chart.renderToSVGString()],{type:'image/svg+xml'})
  if(format==='png'){
   sourceURL=URL.createObjectURL(blob);const img=new Image();img.src=sourceURL;await img.decode()
   const canvas=document.createElement('canvas'),scale=Math.min(2,16380/full.height);canvas.width=Math.ceil(full.width*scale);canvas.height=Math.ceil(full.height*scale)
   const ctx=canvas.getContext('2d');ctx.fillStyle='#fff';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.drawImage(img,0,0,canvas.width,canvas.height)
   blob=await new Promise((resolve,reject)=>canvas.toBlob(b=>b?resolve(b):reject(new Error('Image conversion failed')),'image/png'));canvas.width=canvas.height=0
  }
  const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=props.packet.chart_id+'_complete_figure.'+format;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)
 }catch(e){error.value='Complete figure export failed: '+e.message}finally{if(sourceURL)URL.revokeObjectURL(sourceURL);chart?.dispose();exporting.value=false}
}
let observer
onMounted(()=>{width.value=host.value.clientWidth||800;observer=new ResizeObserver(entries=>width.value=entries[0]?.contentRect.width||800);observer.observe(host.value)})
onBeforeUnmount(()=>observer?.disconnect())
</script>
<style scoped>
.workflow-figure{min-width:0;width:100%}.workflow-figure-tools{display:flex;justify-content:flex-end}.chart-export-btn{border:1px solid var(--line-soft,#d6e2ef);background:#fff;color:#1f5d9a;border-radius:999px;padding:5px 10px;font-size:.75rem;cursor:pointer}.chart-export-btn:focus-visible{outline:2px solid #2468C7}.workflow-figure-error{color:#9b2c20;font-size:.8rem}
</style>
