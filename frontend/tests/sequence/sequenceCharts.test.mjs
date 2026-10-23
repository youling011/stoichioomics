import test from 'node:test'
import assert from 'node:assert/strict'
import {sequenceOption} from '../../src/utils/sequenceCharts.js'
test('KDE violin keeps pixel width on a categorical axis that rounds ordinal coordinates',()=>{
 const fields=['locus_gc_percent','exon_gc_percent','promoter_gc_percent','locus_atoms_N_per_base','exon_atoms_N_per_base','promoter_atoms_N_per_base','locus_shannon_entropy_acgt','exon_shannon_entropy_acgt','promoter_shannon_entropy_acgt'];const profiles=fields.map(field=>({field,unit:'source',n_valid:10,mean:2,quantiles:[0,0,1,2,3,4,4],kde:{x:[0,1,2,3,4],density:[0,.5,1,.5,0]}}));const o=sequenceOption({data:{kind:'region_violins',profiles}})
 const polygons=o.series.filter(s=>s.type==='custom'&&s.data.length===1)
 assert.equal(polygons.length,9)
 for(const series of polygons){const shape=series.renderItem({}, {coord:([x,y])=>[x*10,Math.round(y)*100],size:()=>[10,-100]}).shape;const ys=shape.points.map(p=>p[1]);assert.ok(Math.max(...ys)-Math.min(...ys)>60,'density must have visible thickness');assert.ok(Math.max(...ys)-Math.min(...ys)<70,'density must stay inside its category band')}
 assert.deepEqual(o.xAxis.map(a=>a.name),['GC (%)','Nitrogen (atoms/base)','Entropy (bits)'])
 assert.ok(o.xAxis.every(a=>a.min===0&&a.max===4),'full KDE endpoints must determine the axis domain, not only medians or inner intervals')
})
test('Coordinate score ribbons display IQR and preserve gaps at empty windows',()=>{
 const bins=[{x:1,value:2,min:1,max:3,count:5},{x:2,value:4,min:2,max:6,count:7},{x:3,value:null,min:null,max:null,count:0},{x:4,value:3,min:2,max:4,count:4}];const o=sequenceOption({chart_id:'GD15',data:{kind:'chromosome_score_tracks',tracks:[{seqid:'s',bins}]}});const band=o.series.find(s=>s.type==='custom');assert.equal(band.data.length,1,'ribbons must not connect across an empty window');const points=band.renderItem({}, {value:i=>band.data[0].value[i],coord:p=>p}).shape.points;assert.deepEqual(points,[[1,1],[2,2],[2,6],[1,3]]);assert.equal(o.series.find(s=>s.type==='line').connectNulls,false)
})
test('A real constant zero distribution displays its full-count point and ECDF jump',()=>{
 const o=sequenceOption({data:{kind:'distribution_ecdf',profile:{field:'constant_zero',unit:'count',histogram:{kind:'point_mass',edges:[0],counts:[83]},ecdf:{x:[0],cdf:[1]}}}});const point=o.series.find(s=>s.type==='scatter');assert.deepEqual(point.encode,{x:0,y:1});assert.deepEqual(point.data[0].value,[0,83]);assert.deepEqual(o.series.find(s=>s.type==='line').data,[[0,0],[0,1]])
})
