import {buildPanelOption,colors} from './shared.js'
export function visibleParts(packet,{detailField=null}={}){
 const panels=packet?.data?.panels||[]
 return panels.filter(p=>['primary','secondary'].includes(p.role||'primary')||(p.role==='detail'&&p.panel_id===detailField))
}
export function figureLayout(packet,{width=900,height=360,detailField=null,full=false}={}){
 const panels=visibleParts(packet,{detailField}),chart=packet.chart_id
 if(width>=760&&panels.length===2&&panels[1].type==='status_matrix'&&panels[1].role==='secondary'){
  const primaryHeight=Math.max(300,Math.min(460,height-20)),sideWidth=Math.max(240,Math.round(width*.29))
  return{width,height:primaryHeight,columns:2,cells:[{panel:panels[0],left:0,top:0,width:width-sideWidth-24,height:primaryHeight},{panel:panels[1],left:width-sideWidth,top:0,width:sideWidth,height:Math.max(160,Math.min(230,(panels[1].y_categories?.length||2)*29+95))}]}
 }
 let columns=width>=440&&panels.length>1?2:1
 if(chart==='S20')columns=width>900?4:width>620?3:2
 if(['S01','S23','S24','S25','H02','H23','H31','H16'].includes(chart)||packet.data?.core_panel_id)columns=1
 if(chart==='H06')columns=width>900?3:width>=620?2:1
 const gap=18,cellWidth=(width-gap*(columns-1))/columns
 let y=0,rowHeight=0,col=0;const cells=[]
 for(const panel of panels){
  const compact=panel.compact_strip,secondary=panel.role==='secondary'
  let h=panel.type==='hit_rug'?115:panel.type==='validity_curve'?110:compact?155:panel.type==='status_matrix'?Math.max(155,Math.min(230,(panel.y_categories?.length||2)*29+95)):chart==='S20'?195:Math.max(280,Math.min(460,height-20))
  if(panel.type==='categories'){const n=['S13','H01'].includes(chart)?new Set(panel.rows.map(r=>r.group)).size:new Set(panel.rows.map(r=>r.category)).size;h=Math.max(165,Math.min(280,n*24+110))}
  if(full&&['heatmap','composition_intervals'].includes(panel.type)&&!compact){const rows=panel.y_categories?.length||panel.rows?.length||0;h=Math.max(h,Math.min(14000,rows*16+140))}
  if(compact&&full)h=Math.max(h,(panel.y_categories?.length||1)*24+125)
  if(col===columns){y+=rowHeight+gap;col=0;rowHeight=0}
  cells.push({panel,left:col*(cellWidth+gap),top:y,width:cellWidth,height:h});rowHeight=Math.max(rowHeight,h);col++
 }
 return {cells,width,height:Math.max(180,y+rowHeight),columns}
}
export function buildFigureOption(packet,viewport={}){
 const layout=figureLayout(packet,viewport),o={animation:false,__scientificLayout:true,__semantic:{minPoints:1},textStyle:{fontFamily:'Inter,Arial,sans-serif',color:colors.ink},title:[],legend:[],grid:[],xAxis:[],yAxis:[],series:[],visualMap:[],dataZoom:[],tooltip:{trigger:'item',confine:true}}
 for(const {panel:p,left,top,width,height} of layout.cells){
  const q=buildPanelOption(p,{width,height}),i=o.grid.length,start=o.series.length
  const grid=q.grid||{},l=Math.min(width*.33,grid.left||66),right=Math.min(width*.26,grid.right||25),bottom=grid.bottom||58
  o.grid.push({...grid,left:left+l,right:undefined,top:top+(grid.top||56),bottom:undefined,width:Math.max(50,width-l-right),height:Math.max(40,height-(grid.top||56)-bottom),containLabel:false})
  const axis=(a,side)=>({...a,gridIndex:i,nameTextStyle:{fontSize:9,color:colors.ink},axisLabel:{...a?.axisLabel,fontSize:8},name:side==='y'&&p.compact_strip?'':String(a?.name||'').replaceAll('_',' '),nameGap:side==='x'?27:36,nameLocation:'middle'})
  o.xAxis.push(axis(q.xAxis,'x'));o.yAxis.push(axis(q.yAxis,'y'))
  if(p.type==='gsea_curve'){o.xAxis.at(-1).min=1;o.xAxis.at(-1).max=Math.max(...p.points.map(r=>r[0]));}
  const titles=Array.isArray(q.title)?q.title:[q.title]
  for(const title of titles.filter(Boolean))o.title.push({...title,left:left+4,top:top+2,textStyle:{...title.textStyle,fontSize:11,width:width-12,overflow:'truncate'}})
  const names=(q.series||[]).map(s=>s.name).filter(Boolean)
  if(q.legend?.show!==false&&names.length)o.legend.push({...q.legend,data:[...new Set(names)],left:left+5,top:top+25,width:width-15,textStyle:{fontSize:8,color:colors.ink},type:'scroll'})
  for(const series of q.series||[]){
   const s={...series,workflowPanelId:p.panel_id,tooltip:{...(q.tooltip||{}),...(series.tooltip||{})},animation:false}
   if(Array.isArray(s.data))s.data=s.data.map(d=>d&&typeof d==='object'&&!Array.isArray(d)?{...d,panel_id:p.panel_id}:d)
   if(s.type==='graph'){const size=Math.max(100,Math.min(width-100,height-150));s.left=left+(width-size)/2;s.top=top+75;s.width=size;s.height=size}
   else {s.xAxisIndex=i;s.yAxisIndex=i}
   o.series.push(s)
  }
  for(const v of (Array.isArray(q.visualMap)?q.visualMap:q.visualMap?[q.visualMap]:[]))o.visualMap.push({...v,seriesIndex:Array.from({length:q.series.length},(_,j)=>start+j),left:left+width-right+12,right:undefined,top:top+65,bottom:undefined,itemHeight:Math.min(95,height-145),textStyle:{fontSize:8,color:colors.ink}})
  if(!viewport.full)for(const z of q.dataZoom||[]){const which=z.yAxisIndex!==undefined?'yAxisIndex':'xAxisIndex';o.dataZoom.push({...z,[which]:i,right:undefined,left:z.type==='slider'?left+width-right-10:undefined,top:z.type==='slider'?top+55:undefined,height:z.type==='slider'?Math.max(40,height-125):undefined})}
 }
 if(viewport.full){
  const diagnostics=(packet.data?.panels||[]).filter(p=>p.role==='diagnostic')
  const lines=[packet.title,'Complete saved evidence · '+(packet.context_id||'task population'),...diagnostics.map(p=>p.title+': '+(p.rows||[]).map(r=>(r.category||r.y||'')+' '+(r.count??r.value??'')).join('; ')),[packet.method?.name,packet.method?.transform,packet.method?.unit].filter(Boolean).join(' · '),'Independent populations: '+(packet.provenance?.source_tables||[]).map(s=>s.table+' '+s.scope_rows+'/'+s.source_rows).join('; ')]
  const maxChars=Math.max(40,Math.floor(layout.width/6.5)),wrapped=lines.flatMap(line=>String(line).match(new RegExp('.{1,'+maxChars+'}(?:\\s|$)|.{1,'+maxChars+'}','g'))||[''])
  o.graphic=[{type:'text',left:12,top:layout.height+12,style:{text:wrapped.join('\n'),font:'11px Arial',lineHeight:17,fill:colors.ink}}]
  layout.height+=wrapped.length*17+35
 }
 return {option:o,...layout}
}
