import * as echarts from 'echarts'
export async function exportIntegration(option,{name='integration',format='svg',width=1400,height=600,title=''}={}){
 if(title){const grids=option.grid;const move=g=>({...g,...(typeof g.top==='number'?{top:g.top+32}:{})});option={...option,title:{text:title,left:16,top:6,textStyle:{fontFamily:'Inter, system-ui, sans-serif',fontSize:16,color:'#15344f'}},...(grids?{grid:Array.isArray(grids)?grids.map(move):move(grids)}:{}),...(option.graphic?{graphic:(Array.isArray(option.graphic)?option.graphic:[option.graphic]).map(move)}:{}),...(option.legend?{legend:{...option.legend,top:30}}:{})};height+=40}
 const host=document.createElement('div');host.style.cssText=`position:fixed;left:-30000px;top:0;width:${width}px;height:${height}px`;document.body.appendChild(host);let chart
 try{chart=echarts.init(host,null,{renderer:format==='svg'?'svg':'canvas',width,height});chart.setOption(option,true);await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))
  let blob;if(format==='svg'){const uri=chart.getDataURL({type:'svg',backgroundColor:'#fff'});const content=decodeURIComponent(uri.slice(uri.indexOf(',')+1));if(!content.trimStart().startsWith('<svg'))throw new Error('SVG renderer did not produce an SVG document. Use PNG export.');blob=new Blob([content],{type:'image/svg+xml'})}
  else{const uri=chart.getDataURL({type:'png',pixelRatio:4,backgroundColor:'#fff'});if(!uri.startsWith('data:image/png;base64,'))throw new Error('PNG renderer returned an invalid image');blob=await (await fetch(uri)).blob()}
  const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`${name}.${format}`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);return blob
 }finally{chart?.dispose();host.remove()}
}
