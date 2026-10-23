import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {gunzipSync} from 'node:zlib'
import * as echarts from 'echarts'
import {figureOption,cohortFigure,figureHeight} from '../../src/utils/proteomeCharts.js'
const real=JSON.parse(gunzipSync(readFileSync(new URL('./fixtures/yeast_core_real.json.gz',import.meta.url))))
for(const [id,value] of Object.entries(real.figures)){
  if(['B13','B14'].includes(id))continue
  test(`${id} renders complete real-data payload to SVG`,()=>{
    const f=value.chart_ref?real.figures[value.chart_ref]:value,option=['D11','D12','D16'].includes(id)?cohortFigure(id,real.cohort):figureOption({...f,chart_id:id})
    assert.equal(option.__scientificLayout,true);assert.ok(option.series.length)
    const chart=echarts.init(null,null,{renderer:'svg',ssr:true,width:1100,height:figureHeight(id)})
    try{chart.setOption(option);const svg=chart.renderToSVGString();assert.ok(svg.includes('<svg'));assert.ok(svg.length>1000);assert.ok(!/\b(?:NaN|Infinity)\b/.test(svg))}finally{chart.dispose()}
  })
}
test('All 52 Core field distributions render in original units, including constant Se',()=>{
  for(const f of real.manifest.fields.filter(f=>f.group!=='Full extensions')){
    const p=real.profiles[f.key];assert.ok(p,f.key)
    const option=figureOption({coverage:{n_source:p.n_source,n_valid:p.n_valid},data:{kind:'distribution',profile:p,log:f.key==='length_aa'}})
    const chart=echarts.init(null,null,{renderer:'svg',ssr:true,width:650,height:320})
    try{chart.setOption(option);assert.ok(!/\b(?:NaN|Infinity)\b/.test(chart.renderToSVGString()),f.key)}finally{chart.dispose()}
  }
})
test('Candidate lollipops retain the scientifically meaningful zero origin',()=>{
  const o=figureOption(real.figures.D14);assert.equal(o.xAxis[0].min,0);assert.equal(o.xAxis[1].min,0)
})
