export const omics = ['genome','transcriptome','proteome']
export const omicsNames = ['Genome','Transcriptome','Proteome']
export const omicsColors = ['#0E9F91','#2468C7','#7850CA']
export const groupColors = {Bacteria:'#169E88',Fungi:'#D79B33',Protists:'#27A5B4',Plants:'#59A45F',Metazoa:'#8A69C9',Vertebrates:'#5389D2',Unclassified:'#8194A5'}
const ink='#173B64', muted='#536E88', blue=['#F0F7FC','#AECFE4','#5691BE','#245887','#163958']
const esc=v=>String(v??'N/A').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))
export const formatRaw=v=>v===null||v===undefined||!Number.isFinite(Number(v))?'N/A':Math.abs(v)>0&&Math.abs(v)<.01?Number(v).toExponential(2):Number(v).toLocaleString('en-US',{maximumFractionDigits:Number.isInteger(v)?0:2})
export const symlog=(x,L=2)=>Math.sign(x)*(Math.abs(x)<=L?Math.abs(x)/.9:L*(1/.9+Math.log10(Math.abs(x)/L)))
export const inverseSymlog=(y,L=2)=>Math.sign(y)*(Math.abs(y)<=L/.9?Math.abs(y)*.9:L*10**(Math.abs(y)/L-1/.9))
const color=g=>groupColors[g]||'#8194A5'
const txt=(x,y,text,extra={})=>({type:'text',style:{x,y,text:String(text),fill:ink,font:'10px Inter,Arial,sans-serif',...extra},silent:true})
const empty=c=>!c||c.n_source===0||['empty','error','unavailable'].includes(c.status)
const base=c=>({animation:false,__scientificLayout:true,__semantic:{minPoints:1,uniqueCount:false},__scientificEmptyReason:c?.warnings?.join('; ')||'No applicable records under this context.',textStyle:{fontFamily:'Inter,Arial,sans-serif',color:ink,fontSize:10},tooltip:{trigger:'item',appendToBody:true},__dataRows:c?buildHomeAtlasDataRows(c):[],series:[]})
export function contrastText(rgb){
 const lum=rgb.map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((n,v,i)=>n+v*[.2126,.7152,.0722][i],0)
 const candidates=[['#173B64',[23,59,100]],['#FFFFFF',[255,255,255]],['#000000',[0,0,0]]]
 return candidates.map(([c,values])=>{const l=values.map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((n,v,i)=>n+v*[.2126,.7152,.0722][i],0);return [c,(Math.max(l,lum)+.05)/(Math.min(l,lum)+.05)]}).sort((a,b)=>b[1]-a[1])[0][0]
}
function paletteText(t,palette){
 const p=Math.max(0,Math.min(1,t))*(palette.length-1),a=Math.floor(p),b=Math.min(palette.length-1,a+1),f=p-a
 const parse=c=>[1,3,5].map(i=>parseInt(c.slice(i,i+2),16))
 const x=parse(palette[a]),y=parse(palette[b]);return contrastText(x.map((v,i)=>v+(y[i]-v)*f))
}

export function buildHomeAtlasDataRows(card,{detail='matrix'}={}){
 const d=card?.data||{}, id=card?.chart_id;let rows=[]
 if(id==='H1')rows=d.groups||[]
 if(id==='H2')rows=d.links||[]
 if(id==='H3')rows=d.fields||[]
 if(id==='D1')rows=(d.rows||[]).flatMap(r=>omics.map(m=>({group:r.group,species_count:r.species_count,omics:m,...r.layers[m]})))
 if(id==='D2')rows=(d.groups||[]).flatMap(r=>r.points.map(p=>({group:r.group,...p,n_source:r.n_source,n_excluded:r.n_excluded})))
 if(id==='D3')rows=(d.full_patterns||[]).map(r=>({...r,...Object.fromEntries(d.core_ready_counts.map(x=>['core_ready_'+x.n_ready_layers,x.n_species])),full_basis:d.full_basis}))
 if(id==='D4')rows=[...(d.source_counts||[]).map(r=>({record_type:'source_method',...r})),...(d.layers||[]).flatMap(r=>r.ecdf?r.ecdf.x_missing_cells.map((x,i)=>({record_type:'ecdf_frequency',omics:r.omics,missing_cells:x,frequency:r.ecdf.frequency[i],cdf:r.ecdf.cdf[i],denominator:r.n_summary})):[])]
 if(id==='D5')rows=d.cells||[]
 return rows.map(r=>Object.fromEntries(Object.entries({chart_id:id,scope_id:card.scope_id,source_revision:card.source_revision,population_unit:card.population_unit,denominator:card.n_source,applied_filters:JSON.stringify(card.applied_filters||{}),ignored_for_context:JSON.stringify(card.ignored_for_context||{}),...r}).map(([k,v])=>[k,typeof v==='string'&&/^[=+\-@]/.test(v.trimStart())?"'"+v:v])))
}

export function buildH1SpeciesOption(card){
 const o=base(card);if(empty(card))return o
 const rows=[...card.data.groups].sort((a,b)=>b.species_count-a.species_count||a.group.localeCompare(b.group)),positive=rows.filter(r=>r.species_count>0).map(r=>r.species_count),floor=positive.length?Math.max(.1,Math.min(...positive)*.75):1
 o.grid={left:92,right:112,top:34,bottom:48}
 o.xAxis={type:'log',min:floor,max:Math.max(floor*2,...positive.map(n=>n*1.5)),name:'Registered species (log)',nameGap:29,axisLabel:{formatter:formatRaw},splitLine:{lineStyle:{color:'#E7EFF5'}}}
 o.yAxis={type:'category',data:rows.map(r=>r.group),inverse:true,axisTick:{show:false},axisLine:{show:false},axisLabel:{fontSize:10,color:muted}}
 o.graphic=[txt(6,4,formatRaw(card.data.total_species)+' registered species',{font:'bold 11px Inter,Arial'})]
 o.series=[{type:'custom',data:rows.map((r,i)=>({value:[r.species_count||floor,i],raw:r})),renderItem:(p,api)=>{const r=rows[p.dataIndex],a=api.coord([floor,p.dataIndex]),b=api.coord([r.species_count||floor,p.dataIndex]);return {type:'group',children:[{type:'line',shape:{x1:a[0],y1:a[1],x2:b[0],y2:b[1]},style:{stroke:'#DCE7F1',lineWidth:2}},...(r.species_count?[{type:'circle',shape:{cx:b[0],cy:b[1],r:4.5},style:{fill:color(r.group)}}]:[]),txt(api.getWidth()-105,b[1],formatRaw(r.species_count),{verticalAlign:'middle',font:'bold 10px Inter,Arial'}),txt(api.getWidth()-48,b[1],r.share_pct.toFixed(2)+'%',{verticalAlign:'middle',fill:muted,font:'9px Inter,Arial'})]}}}]
 o.tooltip.formatter=p=>esc(p.data.raw.group)+'<br>'+formatRaw(p.data.raw.species_count)+' / '+formatRaw(card.n_source)+' species'
 return o
}

export function buildH2RecordFlowOption(card){
 const o=base(card);if(empty(card))return o
 const d=card.data,groups=Object.keys(d.source_totals),total=d.total_core_records
 if(!total){o.__scientificEmptyReason='Registered datasets contain zero Core records.';return o}
 const left={},right={},usedL={},usedR={};let run=0
 for(const g of groups){left[g]=run;usedL[g]=run;run+=d.source_totals[g]/total}run=0
 for(const m of omics){right[m]=run;usedR[m]=run;run+=d.target_totals[m]/total}
 const flows=d.links.map(r=>{const h=r.registered_core_rows/total,item={...r,y0:usedL[r.group],y1:usedR[r.omics],h};usedL[r.group]+=h;usedR[r.omics]+=h;return item})
 o.grid={left:82,right:82,top:37,bottom:32};o.xAxis={type:'value',min:0,max:1,show:false};o.yAxis={type:'value',min:0,max:1,inverse:true,show:false}
 o.graphic=[txt(4,4,(total/1e6).toFixed(2)+'M registered Core records',{font:'bold 11px Inter,Arial'})]
 o.series=[{type:'custom',data:flows.map((r,i)=>({value:[i],raw:r})),renderItem:(p,api)=>{const r=flows[p.dataIndex];if(!r.h)return;const [x0,y0]=api.coord([.12,r.y0]),[x1,y1]=api.coord([.88,r.y1]),[,a]=api.coord([.12,r.y0+r.h]),[,b]=api.coord([.88,r.y1+r.h]),dx=(x1-x0)*.42;return {type:'path',shape:{pathData:'M'+x0+','+y0+' C'+(x0+dx)+','+y0+' '+(x1-dx)+','+y1+' '+x1+','+y1+' L'+x1+','+b+' C'+(x1-dx)+','+b+' '+(x0+dx)+','+a+' '+x0+','+a+' Z'},style:{fill:color(r.group),opacity:.38}}}},
 {type:'custom',data:[...groups,...omics].map((x,i)=>({value:[i]})),renderItem:(p,api)=>{const isGroup=p.dataIndex<groups.length,i=isGroup?p.dataIndex:p.dataIndex-groups.length,key=isGroup?groups[i]:omics[i],start=isGroup?left[key]:right[key],n=isGroup?d.source_totals[key]:d.target_totals[key],x=isGroup?.09:.88,[px,py]=api.coord([x,start]),[,end]=api.coord([x,start+n/total]),middle=(py+end)/2,labelY=isGroup?api.coord([0,.07+.86*i/Math.max(1,groups.length-1)])[1]:middle;return {type:'group',children:[{type:'rect',shape:{x:px,y:py,width:7,height:Math.max(0,end-py)},style:{fill:isGroup?color(key):omicsColors[i]}},...(isGroup?[{type:'polyline',shape:{points:[[px-14,labelY],[px-6,labelY],[px,middle]]},style:{stroke:color(key),lineWidth:.7,fill:null}}]:[]),txt(isGroup?px-17:px+12,labelY,isGroup?key:omicsNames[i]+'\n'+(n/1e6).toFixed(2)+'M',{align:isGroup?'right':'left',verticalAlign:'middle',font:'10px Inter,Arial',lineHeight:15})]}}}]
 o.tooltip.formatter=p=>p.data.raw?esc(p.data.raw.group)+' → '+esc(p.data.raw.omics)+'<br>'+formatRaw(p.data.raw.registered_core_rows)+' Core records':'Registered Core composition'
 return o
}

export function buildH3FieldFamiliesOption(card){
 const o=base(card);if(empty(card))return o
 const d=card.data,labels=d.family_order.map(x=>x.replace(' / ',' /\n').replace('Dinucleotide patterns','Dinucleotide\npatterns').replace('Amino-acid composition','Amino-acid\ncomposition'))
 o.grid={left:135,right:16,top:34,bottom:44}
 o.xAxis={type:'category',data:omics.map((m,i)=>omicsNames[i]+'\n'+d.column_counts[m]+' fields'),axisLabel:{fontSize:9,interval:0,hideOverlap:false},axisTick:{show:false},axisLine:{show:false}}
 o.yAxis={type:'category',inverse:true,data:labels,axisLabel:{fontSize:9,lineHeight:11,interval:0,hideOverlap:false},axisTick:{show:false},axisLine:{show:false}}
 o.series=omics.map((m,i)=>({type:'scatter',symbolSize:v=>Math.max(12,1.35*Math.sqrt(38+7*v[2])),itemStyle:{color:['#B7E4DE','#BED3ED','#D7CAEE'][i],opacity:1},data:d.cells.filter(r=>r.omics===m).map(r=>({value:[i,d.family_order.indexOf(r.family),r.field_count],raw:r})),label:{show:true,color:ink,fontSize:10,formatter:p=>String(p.value[2])}}))
 o.graphic=[txt(4,4,card.n_source+' original Core columns · schema composition',{font:'bold 10px Inter,Arial'})]
 o.tooltip.formatter=p=>esc(p.data.raw.family)+'<br>'+esc(p.data.raw.omics)+': '+p.data.raw.field_count+' columns'
 return o
}

export function buildD1CoverageOption(card,{mode='count'}={}){
 const o=base(card);if(empty(card))return o
 const rows=card.data.rows,cells=rows.flatMap((r,i)=>omics.map((m,j)=>{const raw=r.layers[m],n=mode==='pct'?raw.coverage_pct:raw.record_count_core;return {value:[j,i,mode==='pct'?n:n>0?Math.log10(n):0],raw:{group:r.group,omics:m,...raw}}}))
 o.grid={left:100,right:25,top:28,bottom:45};o.xAxis={type:'category',data:omicsNames};o.yAxis={type:'category',data:rows.map(r=>r.group),inverse:true}
 o.visualMap={show:false,min:0,max:Math.max(1,...cells.map(r=>r.value[2])),inRange:{color:blue}}
 o.series=[{type:'heatmap',data:cells,label:{show:true,formatter:p=>mode==='pct'?formatRaw(p.data.raw.coverage_pct)+'%':formatRaw(p.data.raw.record_count_core),fontSize:10}}]
 return o
}

export function buildD2GenomeDistributionOption(card,{mode='violin'}={}){
 const o=base(card);if(empty(card))return o
 const groups=card.data.groups,points=groups.flatMap((r,i)=>r.points.map(p=>({value:[Math.log10(p.mb),i+.14+Math.sin(p.offset_index*2.399963)*.055],raw:{...p,group:r.group}})))
 if(!points.length){o.__scientificEmptyReason='No finite positive registered Mb values.';return o}
 const min=Math.floor(points.reduce((n,p)=>Math.min(n,p.value[0]),Infinity)),max=Math.ceil(points.reduce((n,p)=>Math.max(n,p.value[0]),-Infinity))
 o.grid={left:91,right:136,top:36,bottom:47}
 o.xAxis={type:'value',min,max:max>min?max:min+1,name:'Registry-reported genome size (Mb; log axis)',nameGap:31,interval:1,axisLine:{onZero:false},axisLabel:{formatter:v=>formatRaw(10**v),fontSize:9},splitLine:{lineStyle:{color:'#E7EFF5'}}}
 o.yAxis={type:'value',min:-.5,max:groups.length-.5,interval:1,inverse:true,axisLabel:{show:false},axisTick:{show:false},axisLine:{show:false},splitLine:{show:false}}
 o.series=[{type:'scatter',symbolSize:2,progressive:0,large:false,animation:false,data:points,itemStyle:{opacity:.16,color:p=>color(p.data.raw.group)}}]
 if(mode==='violin')o.series.push({type:'custom',silent:true,data:groups.map((r,i)=>({value:[i]})),renderItem:(p,api)=>{const r=groups[p.dataIndex],k=r.kde;if(!k)return;const edge=k.x_mb.map((x,j)=>api.coord([Math.log10(x),p.dataIndex-.08-k.density_normalized[j]*.27])),flat=[...k.x_mb].reverse().map(x=>api.coord([Math.log10(x),p.dataIndex-.08]));return {type:'polygon',shape:{points:[...edge,...flat]},style:{fill:color(r.group),stroke:color(r.group),lineWidth:.6,opacity:.24}}}})
 o.series.push({type:'custom',silent:true,data:groups.map((r,i)=>({value:[i]})),renderItem:(p,api)=>{
  const r=groups[p.dataIndex];if(!r.n_valid){const a=api.coord([min,p.dataIndex]);return {type:'group',children:[txt(a[0]-10,a[1],r.group,{align:'right',verticalAlign:'middle'}),txt(api.getWidth()-125,a[1],'0',{verticalAlign:'middle'}),txt(api.getWidth()-65,a[1],'N/A',{verticalAlign:'middle'})]}}
  const y=p.dataIndex-.035,a=api.coord([Math.log10(r.q25_mb),y]),b=api.coord([Math.log10(r.q75_mb),y]),m=api.coord([Math.log10(r.median_mb),y]),c=color(r.group),children=[]
  if(mode==='box'){const l=api.coord([Math.log10(r.whisker_low_mb),y]),h=api.coord([Math.log10(r.whisker_high_mb),y]);children.push({type:'line',shape:{x1:l[0],y1:l[1],x2:h[0],y2:h[1]},style:{stroke:c}},...[l,h].map(v=>({type:'line',shape:{x1:v[0],x2:v[0],y1:v[1]-5,y2:v[1]+5},style:{stroke:c}})),{type:'rect',shape:{x:a[0],y:a[1]-7,width:Math.max(1,b[0]-a[0]),height:14},style:{fill:c,opacity:.3,stroke:c}})}
  children.push({type:'line',shape:{x1:a[0],y1:a[1],x2:b[0],y2:b[1]},style:{stroke:c,lineWidth:mode==='box'?1:5}},{type:'circle',shape:{cx:m[0],cy:m[1],r:2.5},style:{fill:'white',stroke:c,lineWidth:1}})
  const labelY=api.coord([min,p.dataIndex])[1];children.push(txt(api.coord([min,p.dataIndex])[0]-10,labelY,r.group,{align:'right',verticalAlign:'middle'}),txt(api.getWidth()-125,labelY,formatRaw(r.n_valid),{verticalAlign:'middle'}),txt(api.getWidth()-65,labelY,formatRaw(r.median_mb),{verticalAlign:'middle',font:'9px Inter,Arial'}));return {type:'group',children}
 }})
 o.graphic=[{type:'text',right:111,top:9,style:{text:'n',fill:ink,font:'bold 10px Inter,Arial'}},{type:'text',right:12,top:9,style:{text:'Median Mb',fill:ink,font:'bold 10px Inter,Arial'}}]
 o.tooltip.formatter=p=>p.data.raw?esc(p.data.raw.species_id)+'<br>'+esc(p.data.raw.group)+': '+formatRaw(p.data.raw.mb)+' Mb':''
 return o
}

function tickSeries(ticks,L,orientation){
 return {type:'custom',silent:true,data:ticks.map(x=>({value:[x]})),renderItem:(p,api)=>{const raw=ticks[p.dataIndex],a=orientation==='y'?api.coord([0,symlog(raw,L)]):api.coord([symlog(raw,L),0]);return txt(a[0]-(orientation==='y'?9:0),a[1]+(orientation==='x'?10:0),formatRaw(raw),{align:orientation==='y'?'right':'center',verticalAlign:orientation==='y'?'middle':'top',fill:muted,font:'9px Inter,Arial'})}}
}
export function buildD3MembershipOption(card,{selectedPattern=''}={}){
 const o=base(card);if(empty(card))return o
 const rows=card.data.full_patterns,maximum=Math.max(10,...rows.map(r=>r.n_species))
 o.grid=[{left:57,right:14,top:42,height:'43%'},{left:57,right:14,top:'65%',bottom:35}]
 o.xAxis=[{type:'category',data:rows.map(r=>r.pattern),axisLabel:{show:false},axisTick:{show:false},axisLine:{show:false}},{type:'category',gridIndex:1,data:rows.map(r=>r.pattern),axisLabel:{fontSize:9,interval:0,hideOverlap:false},axisTick:{show:false},axisLine:{show:false}}]
 o.yAxis=[{type:'value',min:0,max:symlog(maximum*3,10),axisLabel:{show:false},splitLine:{show:false}},{type:'category',gridIndex:1,inverse:true,data:['Genome','RNA','Protein'],axisLabel:{fontSize:9},axisTick:{show:false},axisLine:{show:false}}]
 o.series=[{type:'bar',barWidth:'60%',data:rows.map(r=>({value:symlog(r.n_species,10),raw:r,itemStyle:{color:r.pattern==='000'?'#C28D48':'#32688B',opacity:selectedPattern&&selectedPattern!==r.pattern?.3:1}})),label:{show:true,position:'top',fontSize:9,color:ink,formatter:p=>formatRaw(p.data.raw.n_species)}},tickSeries([0,10,100,1000,10000].filter(x=>x<=maximum*3),10,'y'),
 {type:'custom',xAxisIndex:1,yAxisIndex:1,data:rows.map((r,i)=>({value:[i],raw:r})),renderItem:(p,api)=>{const r=rows[p.dataIndex],on=[...r.pattern].map((c,i)=>c==='1'?i:-1).filter(i=>i>=0),children=[];if(on.length>1){const a=api.coord([p.dataIndex,on[0]]),b=api.coord([p.dataIndex,on.at(-1)]);children.push({type:'line',shape:{x1:a[0],y1:a[1],x2:b[0],y2:b[1]},style:{stroke:ink,lineWidth:1}})}for(let i=0;i<3;i++){const a=api.coord([p.dataIndex,i]);children.push({type:'circle',shape:{cx:a[0],cy:a[1],r:3},style:{fill:r.pattern[i]==='1'?ink:'#DBE5EF'}})}return {type:'group',children}}}]
 const all=card.data.core_ready_counts.find(r=>r.n_ready_layers===3)?.n_species||0
 o.graphic=[txt(4,3,'Core: '+formatRaw(all)+' with all three layers',{font:'bold 10px Inter,Arial'}),txt(4,19,'Full path registration · species (symlog L=10)',{fill:muted,font:'9px Inter,Arial'})]
 o.tooltip.formatter=p=>p.data?.raw?esc(p.data.raw.pattern)+' · '+formatRaw(p.data.raw.n_species)+' species<br>Bits: Genome / RNA / Protein Full paths':''
 return o
}

export function buildD4MissingnessOption(card){
 const o=base(card);if(empty(card))return o
 const layers=card.data.layers,eligible=layers.filter(r=>r.ecdf),summary=layers.reduce((n,r)=>n+r.n_summary,0),headers=layers.reduce((n,r)=>n+r.n_header_only,0)
 if(!eligible.length){o.__scientificEmptyReason=formatRaw(headers)+' header-only entries; no summary ECDF is available.';return o}
 const maximum=Math.max(10,...eligible.flatMap(r=>r.ecdf.x_missing_cells))
 o.grid={left:51,right:15,top:63,bottom:49}
 o.xAxis={type:'value',min:0,max:symlog(maximum*1.12,2),name:'Cached missing cells (symlog L=2)',nameGap:31,axisLabel:{show:false},axisTick:{show:false},splitLine:{show:false}}
 o.yAxis={type:'value',min:0,max:1.02,interval:.25,name:'Fraction',nameGap:31,axisLabel:{fontSize:9},splitLine:{lineStyle:{color:'#E7EFF5'}}}
 o.series=eligible.flatMap(r=>{const c=omicsColors[omics.indexOf(r.omics)],e=r.ecdf,points=e.x_missing_cells.map((x,i)=>[symlog(x,2),e.cdf[i]]);return [{name:omicsNames[omics.indexOf(r.omics)],type:'line',step:'end',showSymbol:false,data:[[points[0][0],0],...points,[symlog(maximum*1.1,2),1]],itemStyle:{color:c},lineStyle:{color:c,width:1.8}},...(points.length===1?[{type:'scatter',data:points,symbolSize:6,itemStyle:{color:c}}]:[])]})
 o.series.push(tickSeries([0,1,10,100,1000,10000,100000].filter(x=>x<=maximum*1.12),2,'x'))
 o.legend={top:40,right:2,itemWidth:12,textStyle:{fontSize:9,color:muted},data:eligible.map(r=>omicsNames[omics.indexOf(r.omics)])}
 o.graphic=[txt(4,2,formatRaw(summary)+' summary assessments',{font:'bold 10px Inter,Arial'}),txt(4,20,formatRaw(headers)+' header-only; excluded from ECDF',{fill:'#94652A',font:'9px Inter,Arial'})]
 o.tooltip.formatter=p=>p.seriesName?esc(p.seriesName)+'<br>Missing cells: '+formatRaw(inverseSymlog(p.value[0],2))+'<br>CDF: '+Number(p.value[1]).toFixed(4):''
 return o
}

export function buildD5CoreDiagnosticsOption(card,{width=700}={}){
 const o=base(card);if(empty(card))return o
 const d=card.data,members=d.cohort.members,ready=d.cells.filter(r=>r.status==='ready'),unavailable=d.cells.filter(r=>r.status!=='ready'),maxC=Math.max(1,...ready.map(r=>r.constant_count)),maxM=Math.max(1,...ready.map(r=>Math.log1p(r.missing_numeric_cells)))
 o.grid=[{left:55,right:14,top:36,height:'24%'},{left:55,right:14,top:'57%',height:'24%'}]
 o.xAxis=[0,1].map(i=>({type:'category',gridIndex:i,data:members.map(r=>r.sid),axisLabel:{show:i===1,interval:0,hideOverlap:false,fontSize:9},axisLine:{show:false},axisTick:{show:false}}))
 o.yAxis=[0,1].map(i=>({type:'category',gridIndex:i,inverse:true,data:['Genome','RNA','Protein'],axisLabel:{fontSize:9},axisLine:{show:false},axisTick:{show:false}}))
 o.visualMap=[{show:false,seriesIndex:0,min:0,max:maxC,inRange:{color:['#FFF9E7','#F5CD7C','#A96C26']}},{show:false,seriesIndex:1,min:0,max:maxM,inRange:{color:blue}}]
 o.series=[0,1].map(i=>({type:'heatmap',xAxisIndex:i,yAxisIndex:i,data:ready.map(r=>({value:[members.findIndex(x=>x.sid===r.sid),omics.indexOf(r.omics),i?Math.log1p(r.missing_numeric_cells):r.constant_count],raw:r,label:{color:paletteText(i?Math.log1p(r.missing_numeric_cells)/maxM:r.constant_count/maxC,i?blue:['#FFF9E7','#F5CD7C','#A96C26'])}})),itemStyle:{borderWidth:1,borderColor:'white'},label:{show:true,fontSize:(width-70)/members.length>=27?9:8,color:ink,formatter:p=>String(i?p.data.raw.missing_numeric_cells:p.data.raw.constant_count)}}))
 for(let i=0;i<2;i++)o.series.push({type:'custom',xAxisIndex:i,yAxisIndex:i,data:unavailable.map(r=>({value:[members.findIndex(x=>x.sid===r.sid),omics.indexOf(r.omics)],raw:r})),renderItem:(p,api)=>{const a=api.coord([api.value(0),api.value(1)]),size=api.size([1,1]);return {type:'group',children:[{type:'rect',shape:{x:a[0]-size[0]/2,y:a[1]-size[1]/2,width:size[0]-1,height:size[1]-1},style:{fill:'#EDF2F7'}},txt(a[0],a[1],'N/A',{align:'center',verticalAlign:'middle',fill:muted,font:'8px Inter,Arial'})]}}})
 o.graphic=[txt(55,10,'Constant numeric fields',{font:'bold 10px Inter,Arial'}),{type:'text',left:55,top:'48%',style:{text:'Missing original numeric cells',fill:ink,font:'bold 10px Inter,Arial'}}]
 o.tooltip.formatter=p=>{const r=p.data.raw;return esc(r.sid)+' · '+esc(r.species_id)+'<br>'+esc(r.omics)+(r.status==='ready'?'<br>Constant fields: '+formatRaw(r.constant_count)+' / '+formatRaw(r.n_numeric)+'<br>Missing original numeric cells: '+formatRaw(r.missing_numeric_cells)+'<br>Whole-source rows: '+formatRaw(r.n_rows):'<br>N/A: '+esc(r.reason))}
 return o
}
