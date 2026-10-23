import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {gunzipSync} from 'node:zlib'
import * as echarts from 'echarts'
import {integrationOption,integrationDistribution,integrationNumber,integrationAxisTick} from '../../src/utils/integrationCharts.js'
const real=JSON.parse(gunzipSync(readFileSync(new URL('./fixtures/arabidopsis_real.json.gz',import.meta.url))))
for(const [id,f] of Object.entries(real.figures))test(`${id} complete real artifact renders valid SVG`,()=>{assert.equal(f.artifact_version,real.artifact_version);const chart=echarts.init(null,null,{renderer:'svg',ssr:true,width:1400,height:id==='OV02'?1300:650});try{const o=integrationOption(f);assert.equal(o.__scientificLayout,true);chart.setOption(o);const svg=chart.renderToSVGString();assert(svg.startsWith('<svg'));assert(svg.length>1000)}finally{chart.dispose()}})
test('count labels preserve every integer digit',()=>{assert.equal(integrationNumber(129513),'129,513')})
test('tiny constant is positioned at its actual value, not a rounded bin midpoint',()=>{const p={kind:'point_mass',median:1e-30,p25:1e-30,p75:1e-30,histogram:{edges:[-.5,.5],counts:[3]},ecdf:{values:[1e-30],counts:[3],cdf:[1]}};const o=integrationDistribution(p,'source unit');assert.deepEqual(o.series[0].data,[[1e-30,3]]);assert.deepEqual(o.series[1].data,[[1e-30,0],[1e-30,1]])})
test('missing correlations render explicit grey cells with original null/reason',()=>{const f=real.figures.CGT;const o=integrationOption(f);assert.equal(o.visualMap.min,-1);assert.equal(o.visualMap.max,1);assert.equal(o.series[0].data.length+o.series[1].data.length,146*74);assert(o.series[1].data.every(r=>r.raw.rho===null&&r.raw.reason))})
test('density color mapping only touches hex counts, not reference/trend lines',()=>{for(const id of ['CX05','CX07','CX08','CX11']){const f=real.figures[id],o=integrationOption(f);assert.equal(o.visualMap.seriesIndex,0);assert.equal(f.data.hex.bins.reduce((s,b)=>s+b.count,0),f.n_valid)}})
test('every selected candidate remains in the evidence matrix',()=>{assert.equal(real.figures.XS03.data.rows.length,1379);const o=integrationOption(real.figures.XS03);assert.equal(o.series[0].data.length,1379*3);assert(o.dataZoom.length>0)})


test('fingerprint axis includes complete cohort IQR and current values',()=>{const f=real.figures.OV01,o=integrationOption(f),d=f.data;for(const v of [...d.q25,...d.q75,...d.median,...d.matrix.flat()]){if(d.matrix[d.included_species.indexOf(f.species_id)]?.includes(v)||d.q25.includes(v)||d.q75.includes(v)||d.median.includes(v)){assert(o.xAxis.min<=v);assert(o.xAxis.max>=v)}}})
test('conditional quantile ribbons use explicit full data axis bounds',()=>{const f=real.figures.CX10,o=integrationOption(f);assert(Number.isFinite(o.xAxis.min));assert(Number.isFinite(o.xAxis.max));assert(Number.isFinite(o.yAxis.min));assert(Number.isFinite(o.yAxis.max));for(const s of o.series.filter(s=>s.type==='line'))for(const [x,y] of s.data){assert(x>=o.xAxis.min&&x<=o.xAxis.max);assert(y>=o.yAxis.min&&y<=o.yAxis.max)}})
test('normalized coordinate track initially shows every one of 60 windows',()=>{const o=integrationOption(real.figures.OV03);assert.equal(o.xAxis.data.length,60);assert.equal(o.dataZoom,undefined);const fixed=integrationOption({...real.figures.OV03,data:{...real.figures.OV03.data,coordinate_color_limit:25}});assert.equal(fixed.visualMap.min,-25);assert.equal(fixed.visualMap.max,25)})

test('dark count and transition cells use white text for readable contrast',()=>{for(const id of ['CX06','CX17']){const o=integrationOption(real.figures[id]);assert(o.series[0].data.some(d=>d.label.color==='#fff'));assert(o.series[0].data.some(d=>d.label.color!=='#fff'))}})

test('constant density axes are explicit without altering any source coordinates',()=>{const f=structuredClone(real.figures.CX05);f.data.hex.range=[0,0,-1,1];const original=JSON.stringify(f),o=integrationOption(f);assert.equal(o.xAxis.min,-.5);assert.equal(o.xAxis.max,.5);assert.equal(o.yAxis.min,-1);assert.equal(o.yAxis.max,1);assert(o.graphic.some(g=>g.style.text.includes('Constant X = 0')));assert.equal(JSON.stringify(f),original)})

test('compact scientific tick labels preserve coordinate magnitude without shortening count labels',()=>{assert.equal(integrationAxisTick(10000000),'1.0e7');assert.equal(integrationAxisTick(1.2e-7),'1.2e-7');assert.equal(integrationNumber(129513),'129,513');const o=integrationDistribution(real.figures.OV04.data.distribution,'bp');assert.equal(o.xAxis.splitNumber,4)})
