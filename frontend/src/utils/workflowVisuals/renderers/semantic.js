// Primitives for declared scientific semantics; composition is in figure.js.
export function extraPanel(p,o,{finite,color,colors,fmt,escape}) {
 if(p.type==='base_composition'){
  const rows=p.rows||[],groups=[...new Set(rows.map(r=>r.group))],bases=['A','C','G','U'];o.xAxis={type:'category',data:bases,axisLabel:{fontSize:10}};o.yAxis.min=0;o.yAxis.name=p.y_label;o.series=groups.map((name,i)=>({type:'scatter',name,symbolSize:8,itemStyle:{color:color(i)},data:bases.map(base=>{const r=rows.find(r=>r.group===name&&r.field==='frac_'+base);return{value:[base,r?.value??null],raw:r}})}));return true
 }
 if(p.type==='effect_lollipop'){
  const rows=(p.rows||[]).slice().sort((a,b)=>a.cliffs_delta-b.cliffs_delta),labels=rows.map(r=>r.feature||r.feature_key||r.feature_name);o.legend.show=false;o.grid.left=150;o.yAxis={type:'category',data:labels,inverse:true,axisLabel:{fontSize:8}};
  o.series=[{type:'custom',renderItem:(params,api)=>{const r=rows[params.dataIndex];if(!finite(r.cliffs_delta))return null;const a=api.coord([0,params.dataIndex]),b=api.coord([r.cliffs_delta,params.dataIndex]);return{type:'group',children:[{type:'line',shape:{x1:a[0],y1:a[1],x2:b[0],y2:b[1]},style:{stroke:colors.grid,lineWidth:2}},{type:'circle',shape:{cx:b[0],cy:b[1],r:3},style:{fill:r.fdr_bh<.05?colors.blue:colors.gray}}]}},data:rows.map((r,i)=>({value:[r.cliffs_delta,i],raw:r,panel_id:p.panel_id}))}];return true
 }
 if(p.type==='hit_rug'){
  o.legend.show=false;o.yAxis.show=false;o.xAxis.min=1;o.xAxis.max=p.rank_max;o.series=[{type:'scatter',symbol:'rect',symbolSize:[1,18],progressive:0,itemStyle:{color:colors.blue,opacity:.5},data:(p.hits||[]).map(x=>[x,.5])}];return true
 }
 if(p.type==='quantile_intervals'){
  const rows=p.rows||[];o.legend.show=false;o.grid.left=110;o.xAxis.name=p.x_label;o.yAxis={type:'category',data:rows.map(r=>r.group),inverse:true,axisLabel:{fontSize:9},axisTick:{show:false},axisLine:{show:false}};
  const bounds=rows.flatMap(r=>[r.q05,r.q95]).filter(finite);if(bounds.length){o.xAxis.min=Math.min(...bounds);o.xAxis.max=Math.max(...bounds)}
  o.series=[{type:'custom',progressive:0,renderItem:(params,api)=>{const r=rows[params.dataIndex];if(![r.q05,r.q25,r.q50,r.q75,r.q95].every(finite))return null;const point=v=>api.coord([v,params.dataIndex]);const a=point(r.q05),b=point(r.q95),l=point(r.q25),h=point(r.q75),m=point(r.q50),c=color(params.dataIndex);return{type:'group',children:[{type:'line',shape:{x1:a[0],x2:b[0],y1:a[1],y2:b[1]},style:{stroke:c,lineWidth:1.5}},{type:'line',shape:{x1:l[0],x2:h[0],y1:l[1],y2:h[1]},style:{stroke:c,lineWidth:6}},{type:'circle',shape:{cx:m[0],cy:m[1],r:3},style:{fill:c}}]};},data:rows.map((r,i)=>({value:[r.q50,i,r.q05,r.q95],raw:r,panel_id:p.panel_id}))}];o.tooltip.formatter=x=>{const r=x.data.raw;return escape(r.group)+' · n='+fmt(r.n)+'<br>'+['q05','q25','q50','q75','q95'].map(k=>k+': '+fmt(r[k])).join('<br>')};return true
 }
 if(p.type==='validity_curve'){
  o.legend.show=false;o.yAxis.min=0;o.yAxis.max=1;o.xAxis.type='category';o.xAxis.data=(p.rows||[]).map(r=>r.field);o.xAxis.axisLabel.show=false;o.yAxis.name='Valid / N';o.series=[{type:'line',showSymbol:false,lineStyle:{color:colors.teal,width:1.2},data:p.rows.map(r=>({value:r.valid_fraction,raw:r}))}];return true
 }
 if(p.type==='sequence_curve'){
  o.series=(p.curves||[]).map((r,i)=>({type:'line',name:r.name,symbolSize:4,lineStyle:{width:1.3,color:color(i)},itemStyle:{color:color(i)},data:r.points}));return true
 }
 if(p.type==='model_curve'){
  o.legend.show=false;o.xAxis={type:'category',data:p.x_categories,axisLabel:{fontSize:8,formatter:v=>String(v).replaceAll('_','\n')},axisTick:{show:false}};o.series=[{type:'line',name:'Saved model R²',data:p.rows.map(r=>({value:r.r2,raw:r})),symbolSize:7,lineStyle:{color:colors.blue},itemStyle:{color:colors.blue}}];return true
 }
 if(p.type==='status_matrix'){
  const xs=p.x_categories,ys=p.y_categories;o.legend.show=false;o.xAxis={type:'category',data:xs,axisLabel:{fontSize:8}};o.yAxis={type:'category',data:ys,inverse:true,axisLabel:{fontSize:8,formatter:v=>String(v).replaceAll('_',' '),width:130,overflow:'break'}};o.grid.left=140;o.grid.right=16;
  const max=Math.max(1,...p.rows.map(r=>r.value));o.visualMap={show:false,min:0,max:Math.log1p(max),dimension:2,inRange:{color:['#EFF6FB','#93BED9','#173B64']}};
  o.series=[{type:'heatmap',data:p.rows.map(r=>({value:[xs.indexOf(r.x),ys.indexOf(r.y),Math.log1p(r.value)],raw:r})),label:{show:true,fontSize:10,formatter:x=>Number(x.data.raw.value).toLocaleString('en-US'),color:'#173B64',textBorderColor:'#fff',textBorderWidth:2},itemStyle:{borderColor:'#fff',borderWidth:1}}];o.tooltip.formatter=x=>escape(x.data.raw.y)+'<br>'+escape(x.data.raw.x)+': '+fmt(x.data.raw.value);return true
 }
 return false
}

