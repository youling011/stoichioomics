import {palette as C,number as fmt,label,escape as esc,signedColor} from './proteomeFormat.js'

const sequential=['#F3F7FA','#BBD9E3','#5A9DB5','#21516D']
const diverging=['#3472A8','#A5CCE1','#FAFAFA','#DDBCA1','#A06136']
function base(figure){return {__scientificLayout:true,__semantic:{minPoints:1,uniqueCount:false,n:figure.coverage?.n_valid,totalCount:figure.coverage?.n_source,method:figure.method?.name,aggregation:'complete population'},animation:false,backgroundColor:'#fff',color:[C.blue,C.teal,C.gold,C.purple],textStyle:{fontFamily:'Inter, system-ui, sans-serif',fontSize:12,color:C.ink},tooltip:{trigger:'item',confine:true,formatter:p=>p.data?.tip||`${esc(p.seriesName)}: ${fmt(p.value)}`},grid:[],xAxis:[],yAxis:[],series:[]}}
function valueAxis(name='',extra={}){return {type:'value',name,nameLocation:'middle',nameGap:32,nameTextStyle:{color:C.ink,fontSize:12},axisLabel:{color:C.muted,formatter:v=>fmt(v,3)},axisLine:{show:true,lineStyle:{color:'#9BA9B3'}},axisTick:{show:false},splitLine:{show:true,lineStyle:{color:'#EDF1F4'}},scale:true,...extra}}
function categoryAxis(data,extra={}){return {type:'category',data,axisLabel:{color:C.ink,fontSize:11},axisTick:{show:false},axisLine:{lineStyle:{color:C.line}},splitLine:{show:false},...extra}}
function title(text,left,top=0){return {text,left,top,textStyle:{fontSize:12,fontWeight:600,color:C.ink}}}
function dot(value,raw={},tip=''){return {value,raw,tip}}
function custom(data,renderItem,extra={}){return {type:'custom',data,renderItem,clip:true,...extra}}
function segment(a,b,color=C.blue,width=2){return {type:'line',shape:{x1:a[0],y1:a[1],x2:b[0],y2:b[1]},style:{stroke:color,lineWidth:width}}}
function intervalSeries(profiles,grid=0,horizontal=true){
  const data=profiles.flatMap((p,i)=>p.quantiles?[dot([p.quantiles[1],p.quantiles[2],p.quantiles[3],p.quantiles[4],p.quantiles[5],p.mean,i],{},`${esc(label(p.field))}<br>n=${p.n_valid.toLocaleString()} · ${esc(p.unit)}<br>P05–P95: ${fmt(p.quantiles[1])} – ${fmt(p.quantiles[5])}<br>Median: ${fmt(p.quantiles[3])} · Mean: ${fmt(p.mean)}`)]:[])
  return custom(data,(params,api)=>{
    const i=api.value(6),a=api.coord([api.value(0),i]),b=api.coord([api.value(4),i]),q1=api.coord([api.value(1),i]),q3=api.coord([api.value(3),i]),med=api.coord([api.value(2),i]),mean=api.coord([api.value(5),i])
    return {type:'group',children:[segment(a,b,C.blue,1.2),segment(q1,q3,C.blue,7),{type:'circle',shape:{cx:med[0],cy:med[1],r:4},style:{fill:'#fff',stroke:C.blue,lineWidth:1.8}},{type:'polygon',shape:{points:[[mean[0],mean[1]-5],[mean[0]+4,mean[1]],[mean[0],mean[1]+5],[mean[0]-4,mean[1]]]},style:{fill:C.gold}}]}
  },{xAxisIndex:grid,yAxisIndex:grid,encode:{x:[0,1,2,3,4,5],y:6},name:'P05–P95 · IQR · median ○ · mean ◇'})
}
function intervals(figure){
  const o=base(figure),d=figure.data,ps=d.profiles||[]
  if(d.independent_axes){
    o.title=[]
    ps.forEach((p,i)=>{const columns=figure.__narrow?2:4,col=i%columns,row=Math.floor(i/columns),left=3+col*(figure.__narrow?49:24.7),top=figure.__narrow?13+row*22:12+row*46;o.grid.push({left:`${left}%`,top:`${top}%`,width:figure.__narrow?'44%':'21%',height:figure.__narrow?'13%':'25%',containLabel:true});o.xAxis.push(valueAxis('',{gridIndex:i,splitNumber:3}));o.yAxis.push(categoryAxis([label(p.field)],{gridIndex:i,show:false}));o.title.push(title(label(p.field),`${left}%`,`${top-(figure.__narrow?6:9)}%`));o.series.push(intervalSeries([p],i))})
  }else{o.grid=[{left:150,right:55,top:20,bottom:40}];o.xAxis=[valueAxis(ps[0]?.unit==='%'?'Amino acid (%)':'Original unit')];o.yAxis=[categoryAxis(ps.map(p=>label(p.field)),{inverse:true})];o.series=[intervalSeries(ps)]}
  return o
}
function heat(o,xnames,ynames,cells,{range=[-3,3],sequentialScale=false,grid={left:190,right:50,top:35,bottom:80},labelValues=false}={}){
  o.grid=[grid];o.xAxis=[categoryAxis(xnames,{axisLabel:{color:C.ink,fontSize:11,rotate:xnames.length>8?40:0,interval:0}})];o.yAxis=[categoryAxis(ynames,{inverse:true,axisLabel:{color:C.ink,fontSize:10,interval:0,width:175,overflow:'truncate'}})]
  o.visualMap={type:'continuous',min:range[0],max:range[1],calculable:false,orient:'horizontal',left:'center',bottom:5,itemWidth:12,itemHeight:180,inRange:{color:sequentialScale?sequential:diverging},textStyle:{color:C.muted},text:sequentialScale?['high','low']:['positive','negative']}
  o.series=[custom(cells,(params,api)=>{
    const cell=cells[params.dataIndex],v=cell.value[2],p=api.coord([api.value(0),api.value(1)]),size=api.size([1,1]),w=Math.abs(size[0]),h=Math.abs(size[1]),missing=v===null||!Number.isFinite(v),children=[{type:'rect',shape:{x:p[0]-w/2,y:p[1]-h/2,width:w,height:h},style:{fill:missing?C.missing:api.visual('color'),stroke:'#F0F3F5',lineWidth:.5}}]
    if(labelValues&&h>=12)children.push({type:'text',style:{text:missing?'NA':fmt(v,3),x:p[0],y:p[1],align:'center',verticalAlign:'middle',fontSize:10,fill:missing?C.muted:sequentialScale?(v>65?'#fff':C.ink):(Math.abs(v)>range[1]*.65?'#fff':C.ink)}})
    return {type:'group',children}
  },{encode:{x:0,y:1,tooltip:2},progressive:0})]
  return o
}
function signature(figure){
  const o=base(figure),names=[...new Set(figure.data.rows.map(r=>r.group))],quantiles=['Min','P05','P25','Median','P75','P95','Max'];o.title=[]
  names.forEach((name,i)=>{
    const rows=figure.data.rows.filter(r=>r.group===name),left=figure.__narrow?150:`${[15,51,83][i]}%`,grid=figure.__narrow?{left,right:25,top:`${6+i*31}%`,height:'24%'}:{left,width:i===2?'14%':'19%',top:55,bottom:95}
    const cells=rows.flatMap((r,y)=>r.z.map((z,x)=>dot([x,y,z],{},`${esc(r.group)} · ${esc(r.field)}<br>n=${r.n.toLocaleString()} · ${esc(r.unit)}<br>${quantiles[x]}: ${fmt(r.quantiles?.[x])}<br>Robust z: ${fmt(z)}${r.constant?'<br>Constant value':''}`)))
    const part=heat(base(figure),quantiles,rows.map(r=>`${label(r.field)}${r.constant?' · const':''}`),cells,{range:[-4,4],grid});part.xAxis[0].gridIndex=i;part.xAxis[0].axisLabel={fontSize:9,rotate:45,interval:0};part.yAxis[0].gridIndex=i;part.yAxis[0].axisLabel.width=figure.__narrow?130:125;part.series[0].xAxisIndex=i;part.series[0].yAxisIndex=i
    o.grid.push(grid);o.xAxis.push(part.xAxis[0]);o.yAxis.push(part.yAxis[0]);o.series.push(part.series[0]);o.title.push(title(`${name} (${rows.length})`,left,figure.__narrow?`${2+i*31}%`:12));o.visualMap={...part.visualMap,seriesIndex:names.map((_,j)=>j)}
  });return o
}
function histSeries(p,index=0,density=false,color=C.blue,horizontal=false){
  const h=p.histogram||{},edges=h.edges||[],counts=h.counts||[]
  if(h.kind==='point_mass')return {type:'scatter',xAxisIndex:index,yAxisIndex:index,symbolSize:9,data:[dot(horizontal?[counts[0],edges[0]]:[edges[0],counts[0]],{},`Point mass ${fmt(edges[0])}<br>n=${counts[0]}`)],itemStyle:{color}}
  const data=counts.map((count,i)=>dot([edges[i],edges[i+1],density?count/Math.max(1,p.n_valid)/(edges[i+1]-edges[i]):count],{},`${esc(p.field)}: [${fmt(edges[i])}, ${fmt(edges[i+1])}]<br>count=${count.toLocaleString()}`))
  return custom(data,(params,api)=>{if(api.value(2)===0)return null;let a,b;if(horizontal){a=api.coord([0,api.value(0)]);b=api.coord([api.value(2),api.value(1)])}else{a=api.coord([api.value(0),0]);b=api.coord([api.value(1),api.value(2)])}return {type:'rect',shape:{x:Math.min(a[0],b[0]),y:Math.min(a[1],b[1]),width:Math.max(.5,Math.abs(b[0]-a[0])-.5),height:Math.max(.5,Math.abs(b[1]-a[1])-.5)},style:{fill:color,opacity:.38}}},{xAxisIndex:index,yAxisIndex:index,encode:horizontal?{x:2,y:[0,1]}:{x:[0,1],y:2},name:density?'Histogram density':'Protein count'})
}
function distribution(figure){
  const o=base(figure),d=figure.data,p=d.profile,h=p.histogram||{},isLog=d.log
  o.grid=[{left:65,right:55,top:25,height:'55%'},{left:65,right:55,top:'74%',height:'15%'}]
  o.xAxis=[valueAxis('',{type:isLog?'log':'value',gridIndex:0,axisLabel:{show:false}}),valueAxis(`${label(p.field)}${p.unit==='dimensionless'?'':` (${p.unit})`}`,{type:isLog?'log':'value',gridIndex:1})]
  o.yAxis=[valueAxis(isLog?'Proteins':h.kind==='point_mass'?'Proteins (point mass)':'Density',{gridIndex:0,min:0,nameGap:43}),valueAxis('ECDF',{gridIndex:1,min:0,max:1,splitNumber:2})]
  o.series=[histSeries(p,0,!isLog),{type:'line',xAxisIndex:1,yAxisIndex:1,step:'end',showSymbol:false,data:(p.ecdf?.x||[]).map((x,i)=>[x,p.ecdf.cdf[i]]),lineStyle:{color:C.teal,width:2},name:'ECDF'}]
  if(h.kind==='point_mass'&&p.quantiles){const value=p.quantiles[3],span=Math.max(1,Math.abs(value)*.05);o.series[1].data=[[value-span,0],[value,1],[value+span,1]]}
  if(!isLog&&p.kde?.kind==='gaussian_kde')o.series.push({type:'line',showSymbol:false,data:p.kde.x.map((x,i)=>[x,p.kde.density[i]]),lineStyle:{color:C.blue,width:2.3},name:'Scott Gaussian KDE'})
  if(p.quantiles)o.series.push({type:'line',data:[],markLine:{symbol:'none',label:{formatter:'Median'},lineStyle:{color:C.gold,type:'dashed'},data:[{xAxis:p.quantiles[3]},...(d.reference!==undefined?[{xAxis:d.reference,name:'Reference',label:{formatter:String(d.reference)}}]:[])]}})
  return o
}
function quality(figure){
  const o=base(figure),d=figure.data,total=figure.coverage.n_source;const rows=[{name:'Sequence quality',values:d.categories.map(q=>q.count)},...d.annotation.filter(a=>['gene_id','gene_symbol','description','source_protein_id'].includes(a.field)).map(a=>({name:label(a.field),values:[a.nonempty,0,0,a.n-a.nonempty]}))]
  o.grid=[{left:160,right:100,top:25,bottom:55}];o.xAxis=[valueAxis('Records (%)',{min:0,max:100})];o.yAxis=[categoryAxis(rows.map(r=>r.name),{inverse:true})]
  o.series=['High / present','Medium','Low','Unavailable / missing'].map((name,j)=>({type:'bar',stack:'coverage',name,barMaxWidth:28,data:rows.map(r=>dot(total?r.values[j]/total*100:0,{},`${esc(r.name)} · ${esc(name)}<br>${r.values[j].toLocaleString()} / ${total.toLocaleString()}`)),itemStyle:{color:[C.teal,C.gold,'#A06136',C.missing][j]},label:{show:j===0||j===3,position:'inside',formatter:p=>p.value>=10?`${fmt(p.value,3)}%`:''}}));o.legend={bottom:0,data:o.series.map(s=>s.name),textStyle:{fontSize:11,color:C.ink}};return o
}
function elements(figure){
  const o=base(figure),d=figure.data,major=d.profiles.filter(p=>!/^(S|Se)_/.test(p.field)),trace=d.profiles.filter(p=>/^(S|Se)_/.test(p.field))
  o.grid=[{left:100,right:'54%',top:30,height:'52%'},{left:'64%',right:45,top:30,height:'52%'},{left:100,right:45,top:'78%',height:30}];o.xAxis=[valueAxis('Atoms / aa',{gridIndex:0}),valueAxis('S / Se atoms per aa',{gridIndex:1}),valueAxis('Share of all atoms (%)',{gridIndex:2,min:0,max:100})];o.yAxis=[categoryAxis(major.map(p=>label(p.field)),{inverse:true,gridIndex:0}),categoryAxis(trace.map(p=>label(p.field)),{inverse:true,gridIndex:1}),categoryAxis(['Total budget'],{gridIndex:2})];o.series=[intervalSeries(major,0),intervalSeries(trace,1)]
  d.budget.forEach((b,i)=>o.series.push({type:'bar',name:b.element,xAxisIndex:2,yAxisIndex:2,stack:'budget',data:[dot((b.share||0)*100,{},`${b.element}: ${fmt(b.atoms,6)} atoms<br>share ${fmt((b.share||0)*100)}%`)],itemStyle:{color:[C.blue,C.teal,'#79A8BC',C.purple,C.gold,'#A06136'][i]},label:{show:true,position:'inside',formatter:()=>b.share>.07?b.element:''}}));return o
}
function violin(figure){
  const o=base(figure),d=figure.data,groups=d.groups||[];o.grid=[{left:180,right:80,top:20,bottom:55}];o.xAxis=[valueAxis(label(d.field))];o.yAxis=[categoryAxis(groups.map(g=>g.label?label(g.label):`${fmt(g.left,3)}–${fmt(g.right,3)} · n=${g.n}`),{inverse:true})]
  const support=groups.flatMap(g=>g.kde?.x||g.summary?.quantiles||[]).filter(Number.isFinite);if(support.length){o.xAxis[0].min=Math.min(...support);o.xAxis[0].max=Math.max(...support)}
  o.series=[custom(groups.flatMap((g,i)=>g.summary?.quantiles?[dot([i,g.summary.quantiles[3]],{},`${esc(g.label||`${fmt(g.left)}–${fmt(g.right)}`)}<br>n=${g.n.toLocaleString()}<br>Median ${fmt(g.summary.quantiles[3])}<br>P05–P95 ${fmt(g.summary.quantiles[1])} – ${fmt(g.summary.quantiles[5])}`)]:[]),(params,api)=>{
    const i=api.value(0),g=groups[i],p=g.kde,mid=api.coord([g.summary.quantiles[3],i]),half=Math.min(30,api.size([0,1])[1]*.35);const children=[]
    if(p?.kind==='gaussian_kde'){
      const maximum=Math.max(...p.density),upper=p.x.map((x,j)=>[api.coord([x,i])[0],mid[1]-half*p.density[j]/maximum]),lower=p.x.map((x,j)=>[api.coord([x,i])[0],mid[1]+half*p.density[j]/maximum]).reverse();children.push({type:'polygon',shape:{points:[...upper,...lower]},style:{fill:C.teal,opacity:.27,stroke:C.teal,lineWidth:1}})
    }
    const q=g.summary.quantiles;children.push(segment(api.coord([q[1],i]),api.coord([q[5],i]),C.teal,1),segment(api.coord([q[2],i]),api.coord([q[4],i]),C.teal,5),{type:'circle',shape:{cx:mid[0],cy:mid[1],r:4},style:{fill:'#fff',stroke:C.teal,lineWidth:2}});return {type:'group',children}
  },{encode:{x:1,y:0}})];return o
}
function stratified(figure){const o=distribution(figure),d=figure.data;o.series=o.series.filter(s=>s.xAxisIndex!==1);d.groups.forEach((g,i)=>o.series.push({type:'line',xAxisIndex:1,yAxisIndex:1,name:`${fmt(g.left)}–${fmt(g.right)} aa (n=${g.n})`,showSymbol:false,step:'end',data:g.ecdf.x.map((x,j)=>[x,g.ecdf.cdf[j]]),itemStyle:{color:[C.blue,C.teal,C.gold,C.purple][i%4]},lineStyle:{width:1.8,color:[C.blue,C.teal,C.gold,C.purple][i%4]}}));o.grid[1].top='69%';o.grid[1].height='23%';o.legend={top:0,type:'scroll',textStyle:{fontSize:10},data:o.series.filter(s=>s.xAxisIndex===1).map(s=>s.name)};return o}
function hexPlot(figure){
  const o=base(figure),d=figure.data,h=d.hex||{},isPca=d.kind==='ordination',aux=isPca||d.conditional?.length>0,mainWidth=aux?'57%':'79%';o.grid=[{left:70,top:35,width:mainWidth,bottom:75}];const axisName=f=>label(f)+(/_pct$/.test(f)?' (%)':''),ord=d.ordination||{},xName=isPca?`PC1 (${fmt(100*(ord.variance?.[0]||0),3)}%)`:axisName(d.x),yName=isPca?(ord.variance?.length>1?`PC2 (${fmt(100*ord.variance[1],3)}%)`:'Rank-one baseline'):axisName(d.y)
  o.xAxis=[valueAxis(xName)];o.yAxis=[valueAxis(yName,{nameGap:48})];const bins=h.bins||[];const vmax=Math.max(1,...bins.map(b=>b.count))
  o.visualMap={min:0,max:Math.log1p(vmax),dimension:2,seriesIndex:0,orient:'horizontal',left:70,bottom:8,itemWidth:12,itemHeight:180,inRange:{color:sequential},formatter:v=>fmt(Math.expm1(v),3),text:['Proteins / hexagon',''],textStyle:{fontSize:10}}
  o.series=[custom(bins.map(b=>dot([b.center[0],b.center[1],Math.log1p(b.count),b.index],{bin_id:b.bin_id,chart_id:figure.requested_chart_id||figure.chart_id,variant_id:figure.variant_id},`Count: ${b.count.toLocaleString()}<br>${esc(xName)} ${fmt(b.center[0])}<br>${esc(yName)} ${fmt(b.center[1])}<br>Click to inspect all members`)),(params,api)=>({type:'polygon',shape:{points:bins[api.value(3)].polygon.map(p=>api.coord(p))},style:{fill:api.visual('color'),stroke:'none'}}),{name:'Complete population hexagons'})]
  const gg=d.conditional||[]
  if(gg.length){
    const top=gg.map(g=>[g.x_median,g.quantiles[5]]),bottom=gg.map(g=>[g.x_median,g.quantiles[1]]).reverse();o.series.push(custom(gg.map((g,i)=>[g.x_median,g.quantiles[3],i]),(p,api)=>p.dataIndex===0?{type:'polygon',shape:{points:[...top,...bottom].map(q=>api.coord(q))},style:{fill:C.gold,opacity:.18}}:null,{silent:true,name:'Conditional P10–P90'}),{type:'line',showSymbol:true,symbolSize:4,data:gg.map(g=>[g.x_median,g.quantiles[3]]),lineStyle:{color:C.gold,width:2},itemStyle:{color:C.gold},name:'Conditional median'})
    o.grid.push({left:'76%',right:25,top:35,bottom:75});o.xAxis.push(valueAxis(label(d.y),{gridIndex:1,splitNumber:3}));o.yAxis.push(categoryAxis(gg.map(g=>`${fmt(g.left,2)}–${fmt(g.right,2)}`),{gridIndex:1,inverse:true,axisLabel:{fontSize:9}}));o.series.push(custom(gg.map((g,i)=>dot([g.quantiles[1],g.quantiles[3],g.quantiles[5],i],{},`n=${g.n}<br>P10 ${fmt(g.quantiles[1])} · Median ${fmt(g.quantiles[3])} · P90 ${fmt(g.quantiles[5])}`)),(p,api)=>({type:'group',children:[segment(api.coord([api.value(0),api.value(3)]),api.coord([api.value(2),api.value(3)]),C.gold,2),{type:'circle',shape:{cx:api.coord([api.value(1),api.value(3)])[0],cy:api.coord([api.value(1),api.value(3)])[1],r:3},style:{fill:C.gold}}]}),{xAxisIndex:1,yAxisIndex:1,encode:{x:[0,1,2],y:3},name:'Conditional S interval'}))
  }
  if(isPca){
    if(ord.variance?.length===1){o.grid[0].width='79%';return o}
    const diameter=Math.max(140,Math.min(260,(figure.__width||1100)*.25-25));o.__plotWidth=figure.__width||1100
    o.grid.push({left:'75%',width:diameter,top:35,height:diameter});o.xAxis.push(valueAxis('corr(feature, PC1)',{gridIndex:1,min:-1.3,max:1.3,splitNumber:2}));o.yAxis.push(valueAxis('corr(feature, PC2)',{gridIndex:1,min:-1.3,max:1.3,splitNumber:2,nameGap:30}));const directions=ord.directions||[],all=directions.map((r,i)=>({r,i})).filter(({r})=>r.every(Number.isFinite)).sort((a,b)=>b.r.reduce((s,x)=>s+x*x,0)-a.r.reduce((s,x)=>s+x*x,0)).slice(0,d.entropy?6:directions.length)
    o.series.push({type:'line',xAxisIndex:1,yAxisIndex:1,symbol:'none',silent:true,data:Array.from({length:81},(_,i)=>[Math.cos(i*Math.PI/40),Math.sin(i*Math.PI/40)]),lineStyle:{color:C.line,width:1}})
    all.forEach(({r,i})=>{o.series.push({type:'line',xAxisIndex:1,yAxisIndex:1,symbol:['none','arrow'],symbolSize:6,data:[[0,0],[r[0]||0,r[1]||0]],itemStyle:{color:C.blue},lineStyle:{color:C.blue,width:1.3},labelLayout:{hideOverlap:true,moveOverlap:'shiftY'},label:{show:!d.entropy,position:'top',formatter:p=>p.dataIndex===1?label(d.input_fields[i]).replace(' count',''):''}})})
    if(d.entropy){
      const text=[]
      for(const side of [-1,1]){const group=all.map((item,index)=>({...item,index})).filter(item=>(item.r[0]<0?-1:1)===side).sort((a,b)=>b.r[1]-a.r[1]);let previous=1.2;const placed=group.map(item=>{const y=Math.min(item.r[1],previous-.24);previous=y;return {...item,y}}),shift=placed.length?Math.max(0,-1.1-placed.at(-1).y):0;placed.forEach(item=>text.push([item.r[0],item.r[1],side*1.25,item.y+shift,item.index]))}
      o.series.push(custom(text,(p,api)=>{const x=api.value(2),y=api.value(3),anchor=api.coord([x,y]);return {type:'group',children:[segment(api.coord([api.value(0),api.value(1)]),api.coord([x>0?1:-1,y]),'#91A3AF',.7),{type:'text',style:{text:label(d.input_fields[all[api.value(4)].i]).replace(' count',''),x:anchor[0],y:anchor[1],align:x>0?'right':'left',verticalAlign:'middle',fontSize:10,fill:C.ink}}]}},{xAxisIndex:1,yAxisIndex:1,encode:{x:[0,2],y:[1,3]},silent:true}))
    }
    if(d.entropy){o.grid.push({left:'75%',right:25,top:'70%',height:'17%'});o.xAxis.push(valueAxis('AA entropy (bits)',{gridIndex:2,splitNumber:3}));o.yAxis.push(valueAxis('Proteins',{gridIndex:2,min:0,splitNumber:2,nameGap:28}));o.series.push(histSeries(d.entropy,2,false,C.purple))}
    if(d.extremes?.length)o.series.push({type:'scatter',data:d.extremes.map(e=>dot([e.coordinate[0],e.coordinate[1]||0],{protein_id:e.protein_id,entity_id:e.protein_id,report_entity_key:e.protein_id,species_id:figure.species_id},esc(e.protein_id))),symbolSize:6,itemStyle:{color:C.gold},label:{show:true,formatter:p=>p.data.raw.protein_id,width:130,overflow:'truncate',position:'top',fontSize:9},labelLayout:{hideOverlap:true,moveOverlap:'shiftY'}})
  }
  if(d.reference_x!==undefined||d.reference_y!==undefined)o.series.push({type:'line',data:[],markLine:{silent:true,symbol:'none',lineStyle:{type:'dashed',color:C.muted},data:[...(d.reference_x!==undefined?[{xAxis:d.reference_x}]:[]),...(d.reference_y!==undefined?[{yAxis:d.reference_y}]:[])]}})
  return o
}
function contours(figure){
  const o=hexPlot({...figure,data:{...figure.data,conditional:[]}}),d=figure.data;o.grid[0]={left:70,right:135,top:100,bottom:70};o.grid.push({left:70,right:135,top:15,height:50},{right:15,width:65,top:100,bottom:70});o.xAxis.push(valueAxis('',{gridIndex:1,axisLabel:{show:false}}),valueAxis('Count',{gridIndex:2,splitNumber:2,min:0}));o.yAxis.push(valueAxis('',{gridIndex:1,show:false,min:0}),valueAxis('',{gridIndex:2,show:false}));o.series.push(histSeries(d.x_profile,1,false,C.blue),histSeries(d.y_profile,2,false,C.teal,true))
  ;(d.contours?.paths||[]).forEach((region,i)=>region.paths.forEach(path=>o.series.push({type:'line',showSymbol:false,data:path,itemStyle:{color:[C.blue,C.teal,C.gold][i]},lineStyle:{color:[C.blue,C.teal,C.gold][i],width:1.8,type:['solid','dashed','dotted'][i]},name:`${Math.round(region.mass*100)}% KDE mass`})));o.legend={top:72,left:70,textStyle:{fontSize:10},data:(d.contours?.paths||[]).map(p=>`${Math.round(p.mass*100)}% KDE mass`)};return o
}
function quantileBands(figure){
  const o=base(figure),rows=figure.data.rows;o.grid=[{left:65,right:35,top:25,bottom:95}];o.xAxis=[categoryAxis(rows.map(r=>label(r.field)),{axisLabel:{fontSize:11,rotate:25,interval:0}})];o.yAxis=[valueAxis('Within-feature robust z')]
  for(const [lo,hi,opacity,color] of [[1,5,.15,C.blue],[2,4,.32,C.blue]])o.series.push(custom(rows.flatMap((r,i)=>r.scaled.quantiles?[dot([i,r.scaled.quantiles[lo],r.scaled.quantiles[hi]],{},`${esc(label(r.field))}<br>Original median ${fmt(r.original.quantiles?.[3])} ${esc(r.original.unit)}`)]:[]),(params,api)=>{const i=api.value(0),next=rows[i+1]?.scaled.quantiles;if(!next)return null;return {type:'polygon',shape:{points:[[i,api.value(1)],[i+1,next[lo]],[i+1,next[hi]],[i,api.value(2)]].map(p=>api.coord(p))},style:{fill:color,opacity}}},{encode:{x:0,y:[1,2]}}))
  o.series.push({type:'line',data:rows.map((r,i)=>[i,r.scaled.quantiles?.[3]??null]),showSymbol:true,lineStyle:{color:C.ink,width:1.3},name:'Median (zero by robust centering)'})
  return o
}
function structure(figure){const o=base(figure),d=figure.data;if(d.rows){return heat(o,d.fields.map(label),d.rows.map(r=>r.protein_id),d.rows.flatMap((r,i)=>r.z.map((z,j)=>dot([j,i,z],{protein_id:r.protein_id,gene_id:r.gene_id,entity_id:r.protein_id,report_entity_key:r.protein_id,species_id:figure.species_id},`${esc(r.protein_id)}<br>${esc(label(d.fields[j]))}: ${fmt(r.values[j])}<br>Robust z ${fmt(z)}`))),{range:[-3,3],grid:{left:185,right:35,top:30,bottom:100}})}return heat(o,d.fields.map(label),d.blocks.map((b,i)=>i%Math.max(1,Math.floor(d.blocks.length/10))===0?`${b.rank_start+1}–${b.rank_end}`:''),d.blocks.flatMap((b,i)=>b.median_z.map((z,j)=>dot([j,i,z],{rank_start:b.rank_start},`Sorted ranks ${b.rank_start+1}–${b.rank_end}<br>${b.n} records · valid ${b.n_valid[j]}<br>${esc(label(d.fields[j]))}: median robust z ${fmt(z)}<br>Click to open a precise window`))),{range:[-3,3],grid:{left:90,right:35,top:30,bottom:100}})}
function strataMatrix(figure){const o=base(figure),rows=figure.data.rows;return heat(o,['ZC Q1','ZC Q2','ZC Q3','ZC Q4'],rows.map(r=>label(r.field)),rows.flatMap((r,i)=>Array.from({length:4},(_,j)=>{const g=r.groups.find(g=>g.group_id===j);return dot([j,i,g?.summary?.quantiles?.[3]??null],{},`${esc(label(r.field))} · ZC group ${j+1}<br>n=${g?.n??0}<br>Median robust z ${fmt(g?.summary?.quantiles?.[3])}<br>IQR ${fmt(g?.summary?.quantiles?.[2])} – ${fmt(g?.summary?.quantiles?.[4])}`)})),{range:[-3,3],labelValues:true})}
function correlationMatrix(figure){const o=base(figure),d=figure.data,order=d.order||d.fields.map((_,i)=>i);return heat(o,order.map(i=>label(d.fields[i])),order.map(i=>label(d.fields[i])),order.flatMap((a,i)=>order.flatMap((b,j)=>j<=i?[dot([j,i,d.matrix[a][b]],{},`${esc(label(d.fields[a]))} × ${esc(label(d.fields[b]))}<br>Spearman ρ=${fmt(d.matrix[a][b])}<br>pair n=${d.pair_n[a][b].toLocaleString()}`)]:[])),{range:[-1,1],labelValues:true})}
function candidates(figure){
  const o=base(figure),d=figure.data;o.grid=[{left:170,right:'56%',top:30,bottom:50},{left:'73%',right:50,top:30,bottom:50}];o.xAxis=[valueAxis('Resource score',{gridIndex:0,min:Math.min(0,...(d.top.Resource||[]).map(r=>r.score))}),valueAxis('S-rich score',{gridIndex:1,min:Math.min(0,...(d.top['S-rich']||[]).map(r=>r.score))})];o.yAxis=[]
  ;['Resource','S-rich'].forEach((name,j)=>{const rows=[...(d.top[name]||[])].reverse();o.yAxis.push(categoryAxis(rows.map(r=>r.protein_id),{gridIndex:j,axisLabel:{fontSize:10,width:145,overflow:'truncate'}}));o.series.push(custom(rows.map((r,i)=>dot([r.score,i],{...r,entity_id:r.protein_id,report_entity_key:r.protein_id,species_id:figure.species_id},`${esc(r.protein_id)}<br>${esc(name)} score ${fmt(r.score,6)}`)),(p,api)=>{const end=api.coord([api.value(0),api.value(1)]),start=api.coord([0,api.value(1)]);return {type:'group',children:[segment(start,end,j?C.teal:C.blue,1.5),{type:'circle',shape:{cx:end[0],cy:end[1],r:4.5},style:{fill:j?C.teal:C.blue}}]}},{xAxisIndex:j,yAxisIndex:j,name}))});return o
}
function candidateMatrix(figure){const o=base(figure),d=figure.data;return heat(o,d.modules,d.rows.map(r=>r.protein_id),d.rows.flatMap((r,i)=>r.values.map((v,j)=>dot([j,i,v],{...r,entity_id:r.protein_id,report_entity_key:r.protein_id,species_id:figure.species_id},`${esc(r.protein_id)} · ${esc(d.modules[j])}<br>Within-module percentile ${fmt(v)}<br>Original score ${fmt(r.scores[j],6)}`))),{range:[0,100],sequentialScale:true,labelValues:true})}

export function cohortFigure(id,response){
  const d=response.data||{},rows=d.species||[],p=d.pca||{},o=base({coverage:{n_valid:rows.length,n_source:rows.length}}),current=response.current_species,colors={Bacteria:C.gold,Fungi:C.purple,Plants:C.teal,Protists:'#7C8071',Metazoa:C.blue,Vertebrates:'#3D7D98'}
  if(id==='D11'){
    o.grid=[{left:70,right:'37%',top:35,bottom:65},{left:'80%',right:30,top:35,bottom:65}];o.xAxis=[valueAxis(`PC1 (${fmt((p.variance?.[0]||0)*100,3)}%)`),valueAxis('Coefficient',{gridIndex:1})];o.yAxis=[valueAxis(`PC2 (${fmt((p.variance?.[1]||0)*100,3)}%)`),categoryAxis(d.fields?.map(label)||[],{gridIndex:1,axisLabel:{fontSize:9,width:115,overflow:'truncate'}})]
    o.series=[{type:'scatter',symbolSize:(v,p)=>p.data.raw.species_id===current?13:9,data:(p.coordinates||[]).map((v,i)=>({...dot([v[0],v[1]||0],{species_id:rows[i].species_id,entity_type:'species'},`${esc(rows[i].label)}<br>n=${rows[i].n.toLocaleString()}<br>${esc(rows[i].species_id)}`),name:rows[i].label,itemStyle:{color:colors[rows[i].domain]||C.blue,borderWidth:rows[i].species_id===current?2:1,borderColor:rows[i].species_id===current?C.purple:'#fff'}})),label:{show:rows.length<=16,formatter:p=>p.name,position:'top',fontSize:10,width:160,overflow:'truncate'},labelLayout:{hideOverlap:true,moveOverlap:'shiftY'}}]
    for(let j=0;j<Math.min(2,p.components?.length||0);j++)o.series.push({type:'bar',xAxisIndex:1,yAxisIndex:1,name:`PC${j+1}`,barMaxWidth:12,data:p.components[j].map((v,i)=>[v,i]),itemStyle:{color:j?C.teal:C.blue}})
    return o
  }
  if(id==='D12'){
    const order=d.order||rows.map((_,i)=>i),names=order.map(i=>rows[i].label);o.grid=[{left:180,right:'40%',top:110,bottom:95},{left:'69%',right:25,top:110,bottom:95}];o.xAxis=[categoryAxis(names,{axisLabel:{fontSize:9,rotate:55,width:95,overflow:'truncate',interval:0}}),categoryAxis(d.fields.map(label),{gridIndex:1,axisLabel:{fontSize:9,rotate:70,interval:0}})];o.yAxis=[categoryAxis(names,{inverse:true,axisLabel:{fontSize:10,width:165,overflow:'truncate',interval:0}}),categoryAxis(names,{gridIndex:1,inverse:true,show:false})]
    const cells=order.flatMap((a,i)=>order.map((b,j)=>dot([j,i,d.distance[a][b]],{},`${esc(rows[a].label)} × ${esc(rows[b].label)}<br>Fingerprint distance ${fmt(d.distance[a][b],5)}`))),context=order.flatMap((a,i)=>d.fields.map((f,j)=>({...dot([j,i,d.z[a][j]],{},`${esc(rows[a].label)} · ${esc(label(f))}<br>Robust z ${fmt(d.z[a][j])}<br>Original mean ${fmt(rows[a].means[f])}`),itemStyle:{color:signedColor(d.z[a][j],3)}})))
    o.series=[{type:'heatmap',data:cells,label:{show:rows.length<=10,fontSize:9,formatter:p=>fmt(p.value[2],2)},itemStyle:{borderColor:'#fff',borderWidth:.5}},{type:'heatmap',xAxisIndex:1,yAxisIndex:1,data:context,itemStyle:{borderColor:'#fff',borderWidth:.4}}];o.visualMap=[{seriesIndex:0,min:0,max:Math.max(1e-12,...d.distance.flat()),orient:'horizontal',left:180,bottom:0,itemHeight:150,itemWidth:12,inRange:{color:sequential},text:['Distance','']},{seriesIndex:1,min:-3,max:3,orient:'horizontal',right:25,bottom:0,itemHeight:130,itemWidth:12,inRange:{color:diverging},text:['Context z','']}]
    // Leaves use precisely the same optimized order as both matrices.
    const positions=new Map(order.map((original,i)=>[original,[i,0]])),branches=[]
    for(let i=0;i<(d.linkage||[]).length;i++){
      const [a,b,h]=d.linkage[i],pa=positions.get(a),pb=positions.get(b)
      if(!pa||!pb)continue
      branches.push([pa[0],pa[1],pa[0],h],[pb[0],pb[1],pb[0],h],[pa[0],h,pb[0],h]);positions.set(rows.length+i,[(pa[0]+pb[0])/2,h])
    }
    o.grid.push({left:180,right:'40%',top:18,height:65})
    o.xAxis.push(valueAxis('',{gridIndex:2,min:-.5,max:rows.length-.5,show:false}));o.yAxis.push(valueAxis('',{gridIndex:2,min:0,max:Math.max(1e-12,...(d.linkage||[]).map(r=>r[2])),show:false}))
    o.series.push(custom(branches,(p,a)=>segment(a.coord([a.value(0),a.value(1)]),a.coord([a.value(2),a.value(3)]),'#57758A',1.2),{xAxisIndex:2,yAxisIndex:2,encode:{x:[0,2],y:[1,3]},silent:true}))
    return o
  }
  const order=d.dispersion.map((v,i)=>[v,i]).sort((a,b)=>b[0]-a[0]).map(r=>r[1]);o.grid=[{left:170,right:50,top:25,bottom:55}];o.xAxis=[valueAxis('Species descriptor, robust z')];o.yAxis=[categoryAxis(order.map(i=>label(d.fields[i])),{inverse:true})];o.series=[{type:'scatter',data:order.flatMap((f,y)=>rows.map((r,i)=>({...dot([d.z[i][f],y],{species_id:r.species_id,entity_type:'species'},`${esc(r.label)} · ${esc(label(d.fields[f]))}<br>Mean ${fmt(r.means[d.fields[f]])}<br>valid n=${r.counts[d.fields[f]]?.toLocaleString()}`),symbolSize:r.species_id===current?10:6,itemStyle:{color:r.species_id===current?C.purple:'#8FA0AB',opacity:r.species_id===current?1:.65}})))}];return o
}

export function figureOption(figure){
  if(!figure?.data)return {__scientificLayout:true,series:[]}
  const kind=figure.data.kind
  const factories={intervals,signature,distribution,quality,elements,violin,stratified_ecdf:stratified,hex_conditional:hexPlot,ordination:hexPlot,probability_contours:contours,quantile_bands:quantileBands,structure_atlas:structure,strata_matrix:strataMatrix,correlation_matrix:correlationMatrix,candidates,candidate_matrix:candidateMatrix}
  if(kind==='density_rows'){
    const groups=figure.data.profiles.map(p=>({label:p.field,n:p.n_valid,summary:p,kde:p.kde}));return violin({...figure,data:{...figure.data,groups,field:'Structure propensity (overlapping sets)'}})
  }
  const option=factories[kind]?factories[kind](figure):intervals({...figure,data:{profiles:figure.data.profiles||[]}})
  return responsiveLayout(option,figure.chart_id,figure.__narrow)
}

export function responsiveLayout(option,id,narrow){
  if(!narrow)return option
  const o={...option,grid:(option.grid||[]).map(g=>({...g})),xAxis:(option.xAxis||[]).map(a=>({...a})),yAxis:(option.yAxis||[]).map(a=>({...a}))}
  if(['D01','D02','D03','B10','B15','D06'].includes(id)&&o.grid.length>1){
    o.grid[0]={left:60,right:25,top:25,height:'43%'}
    o.grid[1]={left:id==='D02'||id==='B10'||id==='B15'||id==='D06'?130:65,right:30,top:'60%',height:id==='D03'?'19%':'29%'}
    if(id==='D03'&&o.grid[2])o.grid[2]={left:65,right:30,top:'86%',height:'8%'}
    if(['D01','D03'].includes(id)&&o.grid[1]){const width=o.__plotWidth||320,size=Math.max(120,Math.min(260,width-100));o.grid[1]={left:Math.max(45,(width-size)/2),top:'60%',width:size,height:size}}
  }
  if(id==='D14'){o.grid=[{left:150,right:35,top:25,height:'35%'},{left:150,right:35,top:'57%',height:'33%'}]}
  if(id==='D11'&&o.grid.length>1){o.grid=[{left:65,right:30,top:25,height:'43%'},{left:155,right:30,top:'60%',height:'29%'}]}
  return o
}

export function figureHeight(id){
  return ({B01:490,B02:700,B03:440,B04:360,B05:500,B07:480,B09:680,B11:400,D01:540,D03:590,D07:760,D11:600,D12:760,D13:570,D14:510,D15:650,D16:550})[id]||460
}


