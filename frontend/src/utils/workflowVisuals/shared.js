import {extraPanel} from './renderers/semantic.js'
export const VERSION='workflow_viz_v2'
export const colors={ink:'#173B64',muted:'#536E88',blue:'#2468C7',teal:'#0E9F91',gold:'#D79B33',purple:'#7850CA',brown:'#A96C26',gray:'#9AAAB7',grid:'#E3EBF2'}
const palette=[colors.blue,colors.teal,colors.gold,colors.purple,colors.brown,colors.gray]
export const escape=value=>String(value??'Unavailable').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))
const finite=v=>v!==null&&v!==undefined&&Number.isFinite(Number(v))
const fmt=v=>finite(v)?Number(v).toLocaleString('en-US',{maximumFractionDigits:5}):'Unavailable'
const short=v=>String(v).length>34?String(v).slice(0,31)+'…':String(v)
const axisNumber=v=>{const n=Number(v);return !Number.isFinite(n)?'':n===0?'0':Math.abs(n)>=10000||Math.abs(n)<.001?n.toExponential(1):String(Number(n.toPrecision(3)))}
const color=i=>palette[i%palette.length]
const semanticColor=(name,i)=>{const n=String(name).toLowerCase();return n==='true'||n==='hvg'?colors.blue:n==='false'||n==='non-hvg'?colors.gray:n.startsWith('global')?colors.blue:n.startsWith('untreated')?colors.teal:n.startsWith('heat_shock')?colors.gold:n==='genome'?colors.teal:n==='transcriptome'?colors.blue:n==='proteome'?colors.purple:color(i)}
export function isV2(packet){return packet?.schema_version===VERSION}
export function metadata(packet){if(!packet)return '';if(!isV2(packet))return 'Legacy saved preview';const c=packet.counts||{};return [packet.source_kind,packet.context_id,fmt(c.scope_rows)+' source units',fmt(c.finite_rows)+' finite',c.non_estimable_rows?fmt(c.non_estimable_rows)+' non-estimable':'',packet.data?.panels?.length>1?'Counts are declared separately for each panel':''].filter(Boolean).join(' · ')}
export function panelHeight(p){return p?.type==='heatmap'?Math.max(270,Math.min(750,(p.y_categories?.length||1)*13+120)):p?.type==='composition_intervals'?Math.max(300,Math.min(650,(new Set((p.rows||[]).map(r=>r.field||r.feature_key))).size*18+100)):340}
export function buildPanelOption(p,viewport={}){
 const width=viewport.width||900,height=viewport.height||650,windowRows=Math.max(8,Math.min(40,Math.floor((height-135)/15)))
 const o={animation:false,__scientificLayout:true,__semantic:{minPoints:1,uniqueCount:false},__dataRows:p.plot_rows||[],textStyle:{fontFamily:'Inter,Arial,sans-serif',color:colors.ink,fontSize:10},
  title:{text:p.title||'',left:8,top:4,textStyle:{fontSize:12,fontWeight:600,color:colors.ink,width:620,overflow:'truncate'}},
  grid:{left:78,right:36,top:58,bottom:68,containLabel:false},legend:{top:25,type:'scroll',textStyle:{fontSize:10,color:colors.ink}},
  tooltip:{trigger:'item',confine:true,formatter:x=>escape(x.name||x.seriesName)+': '+escape(Array.isArray(x.value)?x.value.map(fmt).join(' / '):fmt(x.value))},
  xAxis:{type:'value',name:p.x_label||'',nameLocation:'middle',nameGap:32,nameTextStyle:{fontSize:10},splitLine:{lineStyle:{color:colors.grid}},axisLabel:{fontSize:9,color:colors.muted}},
  yAxis:{type:'value',name:p.y_label||'',nameTextStyle:{fontSize:10},splitLine:{lineStyle:{color:colors.grid}},axisLabel:{fontSize:9,color:colors.muted}},series:[]}
 if(p.type==='scatter'){
  const categories=[...new Set((p.points||[]).map(r=>String(r[2])))];if(categories.length===1&&categories[0]==='All')o.legend.show=false;o.series=categories.map((name,i)=>({type:'scatter',name:p.categories?.every(x=>['True','False','true','false'].includes(x))?(['True','true'].includes(name)?(p.design_id==='H07'?'Strong raw evidence':'HVG'):(p.design_id==='H07'?'Other estimates':'non-HVG')):name,progressive:0,large:false,symbolSize:(p.points?.length||0)<100?6:3,symbol:(_,params)=>p.symbol_field?(p.annotations?.[params.data.record_id]?'circle':'cross'):'circle',animation:false,itemStyle:{color:semanticColor(name,i),opacity:(p.points?.length||0)<100?.8:categories.length>3?.35:.45},
   data:(p.points||[]).filter(r=>String(r[2])===name).map(r=>({value:[r[0],r[1]],record_id:r[3],panel_id:p.panel_id}))}))
 }else if(p.type==='hexbin'){
  const bins=p.bins||[],max=Math.max(1,...bins.map(r=>r.count));o.legend.show=false;o.grid.right=104
  const vertices=bins.flatMap(b=>b.vertices);if(vertices.length){o.xAxis.min=Math.min(...vertices.map(v=>v[0]));o.xAxis.max=Math.max(...vertices.map(v=>v[0]));o.yAxis.min=Math.min(...vertices.map(v=>v[1]));o.yAxis.max=Math.max(...vertices.map(v=>v[1]))}
  o.visualMap={type:'continuous',min:0,max:Math.max(1,Math.log10(max)),dimension:2,orient:'vertical',right:6,top:65,bottom:70,itemHeight:100,itemWidth:9,inRange:{color:['#EAF3FA','#89BCD9','#2468C7','#173B64']},text:['log10 count','0'],textStyle:{fontSize:9}}
  o.series=[{type:'custom',coordinateSystem:'cartesian2d',encode:{x:0,y:1,tooltip:3},progressive:0,
   renderItem:(params,api)=>{const bin=bins[params.dataIndex];if(!bin)return null;return {type:'polygon',shape:{points:bin.vertices.map(v=>api.coord(v))},style:{fill:api.visual('color'),stroke:'#FFFFFF',lineWidth:.25}}},
   data:bins.map(bin=>({value:[bin.x,bin.y,Math.log10(bin.count),bin.count],bin_id:bin.bin_id,panel_id:p.panel_id,raw:bin}))}]
  o.tooltip.formatter=x=>{const b=x.data?.raw;return b?'Saved rows: <b>'+fmt(b.count)+'</b><br>Exact hexagon '+escape(b.bin_id)+'<br>Click to inspect all members.':''}
 }else if(p.type==='ecdf'){
  o.yAxis.min=0;o.yAxis.max=1
  o.series=(p.curves||[]).map((c,i)=>({type:'line',name:c.name+' (n='+c.n+')',step:'end',showSymbol:c.x.length===1,symbolSize:5,connectNulls:false,sampling:undefined,
   lineStyle:{width:1.6,color:semanticColor(c.name,i)},itemStyle:{color:semanticColor(c.name,i)},data:c.x.length?[[c.x[0],0],...c.x.map((x,j)=>[x,c.cdf[j]])]:[],
   markPoint:{silent:true,symbolSize:5,data:finite(c.quantiles?.q50)?[{coord:[c.quantiles.q50,.5],value:'Median'}]:[]},
   markArea:finite(c.quantiles?.q25)&&finite(c.quantiles?.q75)?{silent:true,itemStyle:{color:color(i),opacity:.035},data:[[{xAxis:c.quantiles.q25},{xAxis:c.quantiles.q75}]]}:undefined}))
 }else if(p.type==='rank'){
  o.series=(p.curves||[]).flatMap((c,i)=>[{type:'line',name:c.name,showSymbol:false,connectNulls:false,progressive:0,lineStyle:{color:color(i),width:1.2,opacity:.7},data:c.points.map(r=>({value:[r[0],r[1]],raw:{[p.identity_field||'id']:r[2]},record_id:r[4],panel_id:p.panel_id}))},
   {type:'scatter',name:c.name+' saved members',symbolSize:6,itemStyle:{color:colors.gold},progressive:0,data:c.points.filter(r=>r[3]).map(r=>({value:[r[0],r[1]],raw:{[p.identity_field||'id']:r[2]},record_id:r[4],panel_id:p.panel_id}))}])
  o.series=o.series.filter(s=>s.data?.length);if(o.series.length===1&&o.series[0].name==='All')o.legend.show=false
 }else if(p.type==='heatmap'){
  const xs=p.x_categories||[],ys=p.y_categories||[],rows=p.rows||[];o.legend.show=false;o.grid={left:Math.min(230,Math.max(78,Math.max(0,...ys.map(x=>String(x).length))*4)),right:100,top:48,bottom:85}
  o.xAxis={...o.xAxis,type:'category',data:xs,axisLabel:{fontSize:9,rotate:xs.length>6?35:0,formatter:v=>p.compact_strip?'':short(v),interval:'auto'},splitArea:{show:false}};o.yAxis={...o.yAxis,type:'category',data:ys,inverse:true,axisLabel:{fontSize:8,formatter:short,interval:Math.max(0,Math.floor(ys.length/24))},splitLine:{show:false}}
  o.visualMap={type:'continuous',min:p.color_domain?.[0]??0,max:p.color_domain?.[1]??1,dimension:2,right:8,top:75,itemHeight:90,itemWidth:9,calculable:false,
   inRange:{color:p.color_kind==='diverging'?['#A96C26','#F4F6F9','#2468C7']:['#EFF6FB','#B7D6E8','#5797C5','#173B64']},text:['High','Low'],textStyle:{fontSize:9,color:colors.ink}}
  if(p.category_states)o.visualMap={type:'piecewise',dimension:2,right:4,top:62,itemWidth:9,itemHeight:9,textStyle:{fontSize:8,color:colors.ink},pieces:p.category_states.map((label,i)=>({value:i,label:short(label),color:label.includes('metadata')?colors.gray:label==='empty'||label.includes('missing')?colors.brown:label.includes('alias')?colors.purple:label==='constant'||label.includes('descriptive')?colors.gold:colors.blue}))}
  o.series=[{type:'heatmap',progressive:0,data:rows.filter(r=>finite(r.value)).map(r=>({value:[xs.indexOf(r.x),ys.indexOf(r.y),r.value],raw:r,panel_id:p.panel_id,record_id:r.record_id})),itemStyle:{borderColor:'#FFFFFF',borderWidth:.3}}]
  if(p.design_id==='S16')o.series[0].label={show:true,formatter:v=>fmt(v.value[2]),fontSize:11,color:colors.ink,textBorderColor:'#fff',textBorderWidth:2}
  if(p.design_id==='S06'||xs.length&&xs.every(v=>/codon_[ACGTU]{3}_freq$/.test(String(v))))o.xAxis.axisLabel.formatter=v=>String(v).match(/codon_([ACGTU]{3})_freq$/)?.[1]||short(v)
  else if(xs.length>60&&(p.compact_strip||ys.every(y=>/^q(05|25|50|75|95)$/.test(y))))o.xAxis.axisLabel.formatter=(v,i)=>'F'+String(i+1).padStart(3,'0')
  const missing=rows.filter(r=>!finite(r.value))
  if(missing.length)o.series.push({type:'custom',silent:true,renderItem:(params,api)=>{const pos=api.coord([api.value(0),api.value(1)]),size=api.size([1,1]);return{type:'rect',shape:{x:pos[0]-size[0]/2,y:pos[1]-size[1]/2,width:size[0],height:size[1]},style:{fill:'#D9E0E6',stroke:'#FFFFFF',lineWidth:.3}}},data:missing.map(r=>[xs.indexOf(r.x),ys.indexOf(r.y)])})
  o.tooltip.formatter=x=>{const r=x.data?.raw;return r?escape(r.y)+'<br>'+escape(r.x)+'<br>'+escape(p.value_key||'Value')+': '+fmt(r.value)+(r.raw_quantile!==undefined?'<br>Original quantile: '+fmt(r.raw_quantile):'')+(r.raw_value!==undefined?'<br>Original value: '+escape(r.raw_value):'')+(r.n!==undefined?'<br>Finite n: '+fmt(r.n):''):''}
  if(ys.length>Math.max(24,windowRows)&&!p.compact_strip)o.dataZoom=[{type:'slider',yAxisIndex:0,filterMode:'none',right:75,width:10,start:0,end:100},{type:'inside',yAxisIndex:0,filterMode:'none'}]
 }else if(p.type==='categories'){
  const cats=[...new Set((p.rows||[]).map(r=>String(r.category)))],groups=[...new Set((p.rows||[]).map(r=>String(r.group??'All')))];o.yAxis={...o.yAxis,type:'category',data:cats,inverse:true,axisLabel:{fontSize:9,formatter:short},splitLine:{show:false}};o.xAxis.name='Saved records';o.yAxis.name='';o.grid.left=145;o.legend.show=groups.length>1||groups[0]!=='All';
  o.series=groups.map((name,i)=>({type:'bar',name,stack:'composition',barMaxWidth:26,itemStyle:{color:color(i)},data:cats.map(cat=>({value:(p.rows||[]).find(r=>String(r.category)===cat&&String(r.group??'All')===name)?.count??0,raw:{category:cat,group:name,stoich_class:p.panel_id==='saved_model_classes'?cat:undefined}}))}))
  if(p.design_id==='S13'||p.design_id==='H01'){
   o.yAxis.data=groups;o.legend.show=true
   o.series=cats.map((cat,i)=>({type:'bar',name:cat,stack:'strategy',barMaxWidth:26,itemStyle:{color:cat==='non-HVG'||cat==='Unannotated genes'?colors.gray:cat==='HVG'?colors.blue:color(i)},data:groups.map(group=>({value:(p.rows||[]).find(r=>String(r.category)===cat&&String(r.group??'All')===group)?.count??0,raw:{category:cat,group}}))}))
  }
  if(cats.length>24)o.dataZoom=[{type:'slider',yAxisIndex:0,filterMode:'none',startValue:0,endValue:23},{type:'inside',yAxisIndex:0,filterMode:'none'}]
 }else if(p.type==='intervals'){
  const rows=p.rows||[];o.legend.show=false
  const bounds=rows.filter(r=>r.ci_available).flatMap(r=>[r.low,r.high]).filter(finite)
  if(bounds.length){o.yAxis.min=Math.min(...bounds);o.yAxis.max=Math.max(...bounds)}
  o.series=[{type:'custom',progressive:0,renderItem:(params,api)=>{const r=rows[params.dataIndex];if(!r?.ci_available)return null;const low=api.coord([r.rank,r.low]),high=api.coord([r.rank,r.high]),center=api.coord([r.rank,r.estimate]);return {type:'group',children:[{type:'line',shape:{x1:low[0],y1:low[1],x2:high[0],y2:high[1]},style:{stroke:colors.blue,lineWidth:1,opacity:.4}},{type:'circle',shape:{cx:center[0],cy:center[1],r:1.5},style:{fill:colors.blue,opacity:.8}}]}},data:rows.map(r=>({value:[r.rank,r.estimate,r.low,r.high],raw:r,panel_id:p.panel_id}))}]
  o.tooltip.formatter=x=>escape(x.data?.raw?.feature_key)+'<br>Estimate '+fmt(x.data?.raw?.estimate)+'<br>Saved CI '+fmt(x.data?.raw?.low)+' — '+fmt(x.data?.raw?.high)
 }else if(p.type==='composition_intervals'){
  const rows=p.rows||[],labels=[...new Set(rows.map(r=>String(r.field||r.feature_key)))],groups=[...new Set(rows.map(r=>String(r.group??'All')))];o.legend.show=true;o.grid.left=132
  o.yAxis={...o.yAxis,type:'category',data:labels,inverse:true,axisLabel:{fontSize:8,formatter:v=>String(v).replace(/^AA_([A-Z])_pct$/,'$1').replace(/^aa_([A-Z])_freq$/,'$1')}};o.xAxis.name=p.x_label||'Original units; median and IQR'
  const extent=rows.flatMap(r=>[r.low??r.q25,r.high??r.q75]).filter(finite);if(extent.length){o.xAxis.min=Math.min(0,...extent);o.xAxis.max=Math.max(...extent)}
  o.series=groups.map((name,i)=>({type:'custom',name,progressive:0,renderItem:(params,api)=>{const r=rows.filter(x=>String(x.group??'All')===name)[params.dataIndex];const lo=r.low??r.q25,hi=r.high??r.q75,med=r.estimate??r.median;if(![lo,hi,med].every(finite))return null;const index=labels.indexOf(String(r.field||r.feature_key)),offset=(i-(groups.length-1)/2)*4,a=api.coord([lo,index]),b=api.coord([hi,index]),m=api.coord([med,index]);return {type:'group',children:[{type:'line',shape:{x1:a[0],y1:a[1]+offset,x2:b[0],y2:b[1]+offset},style:{stroke:color(i),lineWidth:3,opacity:.6}},{type:'circle',shape:{cx:m[0],cy:m[1]+offset,r:2.5},style:{fill:color(i)}}]}},data:rows.filter(r=>String(r.group??'All')===name).map(r=>({value:[r.estimate??r.median,labels.indexOf(String(r.field||r.feature_key))],raw:r,panel_id:p.panel_id}))}))
  if(labels.length>Math.max(24,windowRows))o.dataZoom=[{type:'slider',yAxisIndex:0,filterMode:'none',right:8,startValue:0,endValue:windowRows-1},{type:'inside',yAxisIndex:0,filterMode:'none'}]
 }else if(p.type==='parallel_ranks'){
  const metrics=p.metrics||[],features=[...new Set((p.rows||[]).map(r=>r.feature))];o.xAxis={...o.xAxis,type:'category',data:metrics,axisLabel:{formatter:v=>({rf_importance:'RF rank',logistic_abs_coef:'|Logistic β| rank',permutation_importance_mean:'Permutation rank'}[v]||short(v)),fontSize:9}};o.yAxis.inverse=true;o.yAxis.name='Separate descending min-rank'
  o.series=features.map((name,i)=>({type:'line',name,showSymbol:true,symbolSize:2,progressive:0,lineStyle:{color:i<6?colors.blue:colors.gray,opacity:i<6?.8:.3,width:i<6?1.5:.7},data:metrics.map(k=>{const r=p.rows.find(x=>x.feature===name&&x.metric===k);return{value:r?.rank??null,raw:r}})}));o.legend.show=false
 }else if(p.type==='dumbbell'){
  const rows=p.rows||[];o.yAxis={...o.yAxis,type:'category',data:rows.map(r=>r.model)};o.xAxis.min=0;o.xAxis.max=1;o.xAxis.name='Balanced accuracy: saved train / CV'
  o.series=[...rows.map((r,i)=>({type:'line',silent:true,lineStyle:{color:colors.grid,width:4},symbol:'none',data:[[r.cv,i],[r.train,i]]})),...['train','cv'].map((k,i)=>({type:'scatter',name:k==='train'?'Fitted training':'Saved CV mean',symbolSize:9,itemStyle:{color:i?colors.blue:colors.gold},data:rows.map((r,j)=>[r[k],j])}))]
 }else if(p.type==='curve'||p.type==='gsea_curve'){
  o.series=[{type:'line',name:p.type==='gsea_curve'?'Saved-rank ES':'Saved fitted curve',showSymbol:false,step:p.type==='curve'?'end':false,data:p.points||[],lineStyle:{color:colors.teal,width:1.7}}]
  if(p.panel_id==='roc_curve')o.series.push({type:'line',name:'Chance reference',symbol:'none',data:[[0,0],[1,1]],lineStyle:{type:'dashed',color:colors.gray}})
  if(p.panel_id==='pr_curve'&&finite(p.baseline))o.series.push({type:'line',name:'Saved positive prevalence',symbol:'none',data:[[0,p.baseline],[1,p.baseline]],lineStyle:{type:'dashed',color:colors.gray}})
  if(p.type==='gsea_curve'&&!p.member_rug)o.series.push({type:'scatter',name:'All term hits',symbol:'rect',symbolSize:[1,10],itemStyle:{color:colors.ink},progressive:0,data:(p.hits||[]).map(x=>[x,0])})
 }else if(p.type==='network'){
  const rows=p.rows||[],nodes=[...new Set(rows.flatMap(r=>[r.source,r.target]))];o.xAxis.show=false;o.yAxis.show=false;o.legend.show=false;o.title.subtext='Blue: positive · Brown dashed: negative';o.title.subtextStyle={fontSize:9,color:colors.ink}
  o.series=[{type:'graph',layout:'none',roam:true,data:nodes.map((name,i)=>({name,x:Math.cos(i/nodes.length*Math.PI*2)*160,y:Math.sin(i/nodes.length*Math.PI*2)*120,symbolSize:16,label:{show:true,fontSize:9,color:colors.ink}})),links:rows.map(r=>({source:r.source,target:r.target,value:r.weight,raw:r,lineStyle:{color:r.weight<0?colors.brown:colors.blue,width:1+Math.abs(r.weight)*3,type:r.weight<0?'dashed':'solid',curveness:.08}})),edgeSymbol:['none','none'],label:{show:true}}]
 }else if(!extraPanel(p,o,{finite,color,colors,fmt,escape}))throw new Error('Unsupported workflow panel type '+p.type)
 if(p.source_fields?.some(k=>['q_global','global_fdr','adjusted_global_fdr'].includes(k))&&o.series[0])o.series[0].markLine={silent:true,symbol:'none',label:{show:false},lineStyle:{type:'dashed',color:colors.gray},data:[{yAxis:-Math.log10(.05)}]};
 if(width<440){o.title.textStyle.width=Math.max(120,width-20);o.title.textStyle.fontSize=11;o.grid.left=p.type==='heatmap'?92:p.type==='composition_intervals'?94:58;o.grid.right=p.type==='hexbin'?82:p.type==='heatmap'?65:20;if(o.visualMap){o.visualMap.right=2;o.visualMap.itemWidth=8}for(const z of o.dataZoom||[])if(z.yAxisIndex===0&&z.type==='slider')z.right=p.type==='heatmap'?52:6}
 for(const axis of [o.xAxis,o.yAxis])if(axis?.type==='value')axis.axisLabel={...axis.axisLabel,formatter:axisNumber}
 if(width<440&&p.type==='heatmap')o.yAxis.axisLabel.formatter=v=>String(v).length>18?String(v).slice(0,16)+'…':String(v)
 return o
}
export function buildPacketOptions(packet){if(!isV2(packet))throw new Error('Unsupported workflow packet version');return (packet.data?.panels||[]).map(p=>({panel:p,option:buildPanelOption(p)}))}


