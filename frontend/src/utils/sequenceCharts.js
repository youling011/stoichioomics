import { number as fmt, escape as esc, label } from "./sequenceFormat.js";
import { cohortFigure as sharedCohortFigure } from "./proteomeCharts.js";
const colors = ["#2867A1", "#168579", "#B17A22", "#7765A2", "#A06136"], ink = "#18334A";
const seq = ["#F3F7FA", "#BCD9E3", "#5A9DB5", "#21516D"], div = ["#3472A8", "#A5CCE1", "#FAFAFA", "#DDBCA1", "#A06136"];
const item = (value2, tip = "", raw = {}) => ({ value: value2, tip, raw });
const value = (name = "", extra = {}) => ({ type: "value", name, nameLocation: "middle", nameGap: 32, scale: true, axisLabel: { fontSize: 11, color: ink, formatter: (v) => fmt(v, 3) }, axisLine: { show: true, lineStyle: { color: "#9BA9B3" } }, splitLine: { lineStyle: { color: "#EDF1F4" } }, ...extra });
const cat = (data, extra = {}) => ({ type: "category", data, axisLabel: { fontSize: 11, color: ink, interval: 0 }, axisTick: { show: false }, ...extra });
function base() {
  return { __scientificLayout: true, __semantic: { minPoints: 1, uniqueCount: false, aggregation: "complete population" }, animation: false, backgroundColor: "#fff", color: colors, textStyle: { color: ink, fontFamily: "Inter,system-ui,sans-serif", fontSize: 12 }, tooltip: { confine: true, formatter: (p) => p.data?.tip || `${esc(p.name || p.seriesName)}: ${fmt(p.value)}` }, grid: [], xAxis: [], yAxis: [], series: [], title: [] };
}
function grid(o, name = "", g = { left: 95, right: 40, top: 45, bottom: 65 }) {
  let i = o.grid.length;
  o.grid.push(g);
  o.xAxis.push(value(name, { gridIndex: i }));
  o.yAxis.push(value("", { gridIndex: i }));
  return i;
}
function title(o, text, g, i) {
  o.title.push({ text, left: g.left, top: typeof g.top === "number" ? g.top - 28 : `${parseFloat(g.top) - 5}%`, textStyle: { fontSize: 12, fontWeight: 600, color: ink, width: 180, overflow: "break" }, id: `title-${i}` });
}
function intervalSeries(ps, i) {
  return { type: "custom", xAxisIndex: i, yAxisIndex: i, encode: { x: [0, 1, 2, 3, 4, 5], y: 6 }, data: ps.flatMap((p, y) => p.quantiles ? [item([p.quantiles[1], p.quantiles[2], p.quantiles[3], p.quantiles[4], p.quantiles[5], p.mean, y], `${esc(label(p.field))}<br>${esc(p.unit)} \xB7 n=${p.n_valid}<br>Median ${fmt(p.quantiles[3])}<br>P05\u2013P95 ${fmt(p.quantiles[1])}\u2013${fmt(p.quantiles[5])}`)] : []), renderItem: (p, a) => {
    const y = a.value(6), cs = [0, 1, 2, 3, 4, 5].map((j) => a.coord([a.value(j), y]));
    return { type: "group", children: [{ type: "line", shape: { x1: cs[0][0], y1: cs[0][1], x2: cs[4][0], y2: cs[4][1] }, style: { stroke: colors[0], lineWidth: 1.3 } }, { type: "line", shape: { x1: cs[1][0], y1: cs[1][1], x2: cs[3][0], y2: cs[3][1] }, style: { stroke: colors[0], lineWidth: 7 } }, { type: "circle", shape: { cx: cs[2][0], cy: cs[2][1], r: 4 }, style: { stroke: colors[0], fill: "#fff", lineWidth: 1.5 } }, { type: "polygon", shape: { points: [[cs[5][0], cs[5][1] - 4], [cs[5][0] + 4, cs[5][1]], [cs[5][0], cs[5][1] + 4], [cs[5][0] - 4, cs[5][1]]] }, style: { fill: colors[2] } }] };
  } };
}
function intervals(o, ps, independent = false, narrow = false) {
  if (independent) {
    ps.forEach((p, j) => {
      const cols = narrow ? 2 : 4, col = j % cols, row = Math.floor(j / cols), g = { left: `${4 + col * 96 / cols}%`, width: `${88 / cols}%`, top: `${12 + row * (narrow ? 23 : 45)}%`, height: narrow ? "12%" : "25%", containLabel: true };
      const i = grid(o, "", g);
      o.yAxis[i] = cat([""], { gridIndex: i, show: false });
      title(o, `${label(p.field)}
${p.unit?.replace(/（.*?）/g, "").replace("percentage points", "pp")} \xB7 n=${p.n_valid}`, g, j);
      o.series.push(intervalSeries([p], i));
    });
  } else {
    const i = grid(o, ps[0]?.unit || "Original unit");
    o.yAxis[i] = cat(ps.map((p) => label(p.field)), { gridIndex: i, inverse: true, axisLabel: { fontSize: 10, width: 160, overflow: "break" } });
    o.grid[i].left = 185;
    o.series.push(intervalSeries(ps, i));
  }
  return o;
}
function hist(o, p, g, log = false) {
  const i = grid(o, `${p.axis_label||label(p.field)} (${p.unit || "source units"})`, g);
  o.yAxis[i].name = "Records";
  o.xAxis[i].type = log ? "log" : "value";
  const h = p.histogram || {}, edges = h.edges || [], counts = h.counts || [];
  o.series.push({ type: h.kind === "point_mass" ? "scatter" : "custom", xAxisIndex: i, yAxisIndex: i, encode: { x: [0, 1], y: 2 }, data: counts.map((c, j) => item([edges[j], edges[j + 1] ?? edges[j], c], `${fmt(edges[j])}\u2013${fmt(edges[j + 1] ?? edges[j])}<br>n=${c}`)), symbolSize: 10, renderItem: (p2, a) => {
    const lo = a.coord([a.value(0), 0]), hi = a.coord([a.value(1), a.value(2)]);
    return { type: "rect", shape: { x: lo[0], y: hi[1], width: Math.max(1, hi[0] - lo[0]), height: Math.max(1, lo[1] - hi[1]) }, style: { fill: colors[0], opacity: 0.8 } };
  } });
  if (h.kind === "point_mass") { const s=o.series[o.series.length-1]; s.encode={x:0,y:1}; s.data = [item([edges[0], counts[0]], `Point mass ${fmt(edges[0])}, n=${counts[0]}`)]; }
  return i;
}
function cdf(o, p, g, color = colors[1], name = "ECDF") {
  const i = grid(o, `${p.axis_label||label(p.field)} (${p.unit||'source units'})`, g);
  o.yAxis[i] = value("Cumulative fraction", { gridIndex: i, min: 0, max: 1.02 });
  const e = p.ecdf || { x: [], cdf: [] };
  const data = e.x.length === 1 ? [[e.x[0], 0], [e.x[0], 1]] : e.x.map((x, j) => [x, e.cdf[j]]);
  o.series.push({ type: "line", xAxisIndex: i, yAxisIndex: i, step: "end", showSymbol: false, name, data, lineStyle: { color, width: 1.8 } });
  return i;
}
function distribution(f) {
  const o = base(), p = f.data.profile || f.data.profiles?.[0];
  if (!p) return o;
  const narrow = f.__narrow;
  hist(o, p, narrow ? { left: 65, right: 25, top: 40, height: "34%" } : { left: 70, right: "48%", top: 40, bottom: 70 }, p.histogram?.axis_transform === "log10");
  cdf(o, p, narrow ? { left: 65, right: 25, top: "60%", height: "28%" } : { left: "65%", right: 30, top: 40, bottom: 70 });
  return o;
}
function heat(o, xnames, ynames, cells, { range = [-1, 1], sequential = false, labels = true, g = { left: 185, right: 35, top: 40, bottom: 110 }, columns = 0 } = {}) {
  const i = grid(o, "", g);
  o.xAxis[i] = cat(xnames, { gridIndex: i, axisLabel: { fontSize: 10, rotate: xnames.length > 6 ? 50 : 0, interval: 0, width: 130, overflow: "break" } });
  o.yAxis[i] = cat(ynames, { gridIndex: i, inverse: true, axisLabel: { fontSize: 10, interval: 0, width: 170, overflow: "break" } });
  const s = o.series.length;
  o.series.push({ type: "custom", xAxisIndex: i, yAxisIndex: i, encode: { x: 0, y: 1, tooltip: 2 }, data: cells, progressive: 0, renderItem: (p, a) => {
    const d = cells[p.dataIndex], pos = a.coord([a.value(0), a.value(1)]), size = a.size([1, 1]), w = Math.abs(size[0]), h = Math.abs(size[1]), v = d.value[2], missing = v === null || !Number.isFinite(v);
    return { type: "group", children: [{ type: "rect", shape: { x: pos[0] - w / 2, y: pos[1] - h / 2, width: w, height: h }, style: { fill: missing ? "#E2E6E9" : a.visual("color"), stroke: "#fff", lineWidth: 0.6 } }, ...labels && h > 17 ? [{ type: "text", style: { x: pos[0], y: pos[1], text: missing ? "NA" : d.display ?? fmt(v, 2), align: "center", verticalAlign: "middle", fontSize: 10, fill: missing ? ink : Math.abs(v) > Math.max(...range.map(Math.abs)) * 0.65 ? "#fff" : ink } }] : []] };
  } });
  o.visualMap = [...o.visualMap || [], { seriesIndex: s, min: range[0], max: range[1], dimension: 2, orient: "horizontal", left: typeof g.left === "number" ? g.left : "center", bottom: 8, itemWidth: 12, itemHeight: 150, inRange: { color: sequential ? seq : div }, textStyle: { fontSize: 10 } }];
  return o;
}
function violin(o, ps, g = { left: 185, right: 35, top: 35, bottom: 65 }) {
  const i = grid(o, ps[0]?.unit || "Source units", g);
  const domain=ps.flatMap(p=>p.kde?.x?.length?[p.kde.x[0],p.kde.x.at(-1)]:(p.quantiles?[p.quantiles[0],p.quantiles[6]]:[])).filter(Number.isFinite);
  if(domain.length&&Math.min(...domain)<Math.max(...domain)){o.xAxis[i].min=Math.min(...domain);o.xAxis[i].max=Math.max(...domain);}
  o.yAxis[i] = cat(ps.map((p) => `${p.display_label || label(p.field)} (n=${p.n_valid})`), { gridIndex: i, inverse: true, axisLabel: { fontSize: 10, width: 165, overflow: "break" } });
  ps.forEach((p, y) => {
    if (p.kde?.x?.length > 1) {
      const k = p.kde, max = Math.max(...k.density);
      const vertices = [...k.x.map((x, j) => [x, k.density[j] / max * 0.34]), ...k.x.map((x, j) => [x, -k.density[j] / max * 0.34]).reverse()];
      o.series.push({ type: "custom", clip:true, xAxisIndex: i, yAxisIndex: i, encode: { x: 0, y: 1 }, data: [item([p.quantiles[3], y])], renderItem: (q, a) => ({ type: "polygon", shape: { points: vertices.map(([x, offset]) => { const pos=a.coord([x,y]); return [pos[0],pos[1]+offset*Math.abs(a.size([0,1])[1])]; }) }, style: { fill: colors[y % 5], opacity: 0.25, stroke: colors[y % 5], lineWidth: 1 } }) });
    }
  });
  o.series.push(intervalSeries(ps, i));
  return o;
}
function pair(f) {
  const o = base(), d = f.data, narrow = f.__narrow, ordination = !!d.correlation_directions;
  const g = narrow ? { left: 70, right: 25, top: 40, height: "43%" } : { left: 75, right: "37%", top: 45, bottom: 110 }, i = grid(o, ordination ? `PC1 (${fmt((d.variance?.[0] || 0) * 100)}%)` : `${d.transform_x && d.transform_x !== "identity" ? d.transform_x + " " : ""}${label(d.x)} (${d.x_unit || ""})`, g);
  o.yAxis[i].name = ordination ? `PC2 (${fmt((d.variance?.[1] || 0) * 100)}%)` : `${d.transform_y && d.transform_y !== "identity" ? d.transform_y + " " : ""}${label(d.y)} (${d.y_unit || ""})`;
  o.yAxis[i].nameGap = 48;
  const bins = d.hex?.bins || [];
  o.series.push({ type: "custom", xAxisIndex: i, yAxisIndex: i, encode: { x: 0, y: 1, tooltip: 2 }, data: bins.map((b) => item([...b.center, Math.log1p(b.count)], `All-record hexagon<br>n=${b.count}<br>Click to inspect members`, { bin_id: b.bin_id, chart_id: f.chart_id, variant_id: f.variant_id })), renderItem: (p, a) => ({ type: "polygon", shape: { points: bins[p.dataIndex].polygon.map((q) => a.coord(q)) }, style: { fill: a.visual("color"), stroke: "#fff", lineWidth: 0.2 } }), progressive: 0 });
  o.visualMap = [{ seriesIndex: 0, dimension: 2, min: 0, max: Math.max(1, ...bins.map((b) => Math.log1p(b.count))), inRange: { color: seq }, orient: "horizontal", left: 80, bottom: 4, itemHeight: 140, itemWidth: 10, text: ["log1p(count)", ""] }];
  const groups = d.conditional || [];
  if (groups.length) {
    if(groups.length>1){const polygon=[...groups.map(g=>[g.x_median,g.quantiles[5]]),...groups.map(g=>[g.x_median,g.quantiles[1]]).reverse()];o.series.push({type:'custom',silent:true,xAxisIndex:0,yAxisIndex:0,encode:{x:0,y:1},data:groups.map(g=>[g.x_median,g.quantiles[3]]),renderItem:(p,a)=>p.dataIndex===0?{type:'polygon',shape:{points:polygon.map(q=>a.coord(q))},style:{fill:colors[2],opacity:.14}}:null})}
    o.series.push({ type: "line", xAxisIndex: 0, yAxisIndex: 0, data: groups.map((g2) => [g2.x_median, g2.quantiles[3]]), showSymbol: false, lineStyle: { color: colors[2], width: 2 }, silent: true });
    o.series.push({ type: "custom", silent: true, xAxisIndex: 0, yAxisIndex: 0, encode: { x: 0, y: [1, 2] }, data: groups.map((g2) => [g2.x_median, g2.quantiles[1], g2.quantiles[5]]), renderItem: (p, a) => {
      const q = a.coord([a.value(0), a.value(1)]), r = a.coord([a.value(0), a.value(2)]);
      return { type: "line", shape: { x1: q[0], y1: q[1], x2: r[0], y2: r[1] }, style: { stroke: colors[2], lineWidth: 4, opacity: 0.23 } };
    } });
  }
  const side=narrow?{left:70,right:25,top:'65%',height:'23%'}:{left:'79%',right:30,top:45,bottom:110};
  if(d.ratio_profile){const j=cdf(o,d.ratio_profile,side);o.series.push({type:'line',xAxisIndex:j,yAxisIndex:j,data:[],silent:true,markLine:{symbol:'none',data:[{xAxis:1}],lineStyle:{color:colors[4],type:'dashed'}}})}
  else if(d.profiles?.length&&!ordination)violin(o,d.profiles,narrow?{left:185,right:30,top:'65%',height:'23%'}:{left:'84%',right:30,top:45,bottom:110});
  else if(d.response||d.distance_profile)hist(o,d.distance_profile||d.response,side);
  if (ordination) {
    const diameter = Math.max(150, Math.min(230, (f.__width || 1e3) * 0.23 - 35)), g2 = narrow ? { left: 80, top: "65%", width: diameter, height: diameter } : { left: "77%", top: 65, width: diameter, height: diameter }, j = grid(o, "corr PC1", g2);
    o.xAxis[j] = { ...value("corr PC1"), gridIndex: j, min: -1.4, max: 1.4, splitNumber: 2 };
    o.yAxis[j] = { ...value("corr PC2"), gridIndex: j, min: -1.4, max: 1.4, splitNumber: 2, nameGap: 28 };
    o.series.push({ type: "line", xAxisIndex: j, yAxisIndex: j, symbol: "none", silent: true, data: Array.from({ length: 81 }, (_, i2) => [Math.cos(i2 * Math.PI / 40), Math.sin(i2 * Math.PI / 40)]), lineStyle: { color: "#dce4ea", width: 1 } });
    const directions = d.correlation_directions.map((r, i2) => ({ r, i: i2 })).sort((a, b) => Math.hypot(...b.r) - Math.hypot(...a.r)).slice(0, 6), placed = [];
    for (const side of [-1, 1]) {
      const group = directions.filter(({ r }) => (r[0] < 0 ? -1 : 1) === side).sort((a, b) => (b.r[1] || 0) - (a.r[1] || 0));
      let previous = 1.15;
      const rows = group.map((q) => {
        const y = Math.min(q.r[1] || 0, previous - 0.35);
        previous = y;
        return { ...q, y };
      }), shift = rows.length ? Math.max(0, -1.1 - rows.at(-1).y) : 0;
      rows.forEach((q) => placed.push({ ...q, y: q.y + shift, side }));
    }
    for (const { r, i: i2 } of directions) o.series.push({ type: "line", xAxisIndex: j, yAxisIndex: j, data: [[0, 0], item([r[0], r[1] || 0], `${esc(d.fields[i2])}<br>corr PC1=${fmt(r[0])}, PC2=${fmt(r[1] || 0)}`)], showSymbol: true, symbol: ["none", "arrow"], symbolSize: 6, lineStyle: { color: colors[i2 % 5], width: 1.5 } });
    o.series.push({ type: "custom", silent: true, xAxisIndex: j, yAxisIndex: j, encode: { x: [0, 2], y: [1, 3] }, data: placed.map((q) => [q.r[0], q.r[1] || 0, q.side * 1.25, q.y, q.i]), renderItem: (p, a) => {
      const end = a.coord([a.value(2), a.value(3)]), start = a.coord([a.value(0), a.value(1)]), key = d.fields[a.value(4)], short = key.match(/_([ACGTU]{2,3})_count/)?.[1] || key.match(/^aa_([A-Z])_count/)?.[1] || { "log_span": "log span", "log_transcripts": "log transcripts", "log_upstream": "log upstream", "exon_gc_percent": "exon GC", "promoter_gc_percent": "promoter GC", "exon_shannon_entropy_acgt": "exon entropy" }[key] || label(key);
      return { type: "group", children: [{ type: "line", shape: { x1: start[0], y1: start[1], x2: end[0], y2: end[1] }, style: { stroke: "#91A3AF", lineWidth: 0.7 } }, { type: "text", style: { x: end[0], y: end[1], text: short, align: a.value(2) > 0 ? "right" : "left", verticalAlign: "middle", fontSize: 10, fill: ink } }] };
    } });
  }
  for (const [j, level] of (d.contours?.paths || []).entries()) for (const points of level.lines) o.series.push({ type: "line", name: `${Math.round(level.mass * 100)}% smoothed count mass`, data: points, showSymbol: false, lineStyle: { color: colors[2], width: 1.4, type: ["solid", "dashed", "dotted"][j] }, silent: true });
  if (d.contours?.paths?.length) o.legend = { top: 4, left: 65, textStyle: { fontSize: 10 }, data: d.contours.paths.map((p) => `${Math.round(p.mass * 100)}% smoothed count mass`) };
  return o;
}
function matrix(f) {
  const o = base(), d = f.data;
  return heat(o, d.x_fields.map(label), d.y_fields.map(label), d.cells.filter((c) => d.kind === "rna_protein_cross_matrix" || c.x <= c.y).map((c) => item([c.x, c.y, c.rho], `${esc(label(c.y_field))} \xD7 ${esc(label(c.x_field))}<br>\u03C1=${fmt(c.rho)}<br>paired n=${c.n}<br>${c.reason || ""}`)), { range: [-1, 1] });
}
function bars(f) {
  const o = base(), d = f.data, rows = d.categories || [];
  const i = grid(o, "Sequence records", { left: 200, right: "48%", top: 35, bottom: 65 });
  o.yAxis[i] = cat(rows.map((r) => r.name || "unannotated"), { gridIndex: i, inverse: true, axisLabel: { width: 180, overflow: "break", fontSize: 11 } });
  o.series.push({ type: "bar", data: rows.map((r, y) => item([r.count, y], `${esc(r.name)}<br>${r.count} records`)), xAxisIndex: i, yAxisIndex: i, barMaxWidth: 22, itemStyle: { color: colors[0] }, label: { show: true, position: "right", fontSize: 10 } });
  const j = grid(o, d.kind === "biotype_gene_coverage" ? "Distinct linked gene IDs" : "Coding-data availability", { left: "76%", right: 35, top: 35, bottom: 65 });
  const labels = d.kind === "biotype_gene_coverage" ? rows.map((r) => r.name) : ["coding valid", "other"];
  o.yAxis[j] = cat(labels, { gridIndex: j, inverse: true, axisLabel: { width: 120, overflow: "break", fontSize: 10 } });
  o.series.push({ type: "bar", xAxisIndex: j, yAxisIndex: j, data: d.kind === "biotype_gene_coverage" ? rows.map((r, y) => [r.distinct_genes, y]) : [[d.coding_n, 0], [d.other_n, 1]], barMaxWidth: 22, itemStyle: { color: colors[1] } });
  return o;
}
function grammar(f) {
  const o = base(), panels = f.data.panels || [];
  panels.forEach((p, i) => {
    const cols = p.columns || 4, alphabet = f.omics === 'transcriptome' ? 'ACGU' : 'ACGT';
    const source = cols === 16 ? [...p.cells].sort((a,b) => {const aa=a.field.match(/[ACGTU]{3}(?=_freq|$)/)?.[0]||'',bb=b.field.match(/[ACGTU]{3}(?=_freq|$)/)?.[0]||'';return alphabet.indexOf(aa[2])-alphabet.indexOf(bb[2])||aa.slice(0,2).localeCompare(bb.slice(0,2))}) : p.cells;
    const names = source.map((c) => c.field.match(/[ACGTU]{2,3}(?=_freq|$)/)?.[0] || c.field), cells = source.map((c, j) => {
      const x = j % cols, y = Math.floor(j / cols), v = c.value;
      return { ...item([x, y, v === null ? null : p.diverging ? v : v * 100], `${esc(c.field)}<br>${p.diverging ? "mean log2 ratio" : "mean frequency (%)"} ${fmt(v === null ? null : p.diverging ? v : v * 100)}<br>valid n=${c.n}`), display: `${names[j]}
${fmt(v === null ? null : p.diverging ? v : v * 100, 3)}` };
    });
    const g = { left: 65, right: 35, top: `${10 + i * 45}%`, height: panels.length > 1 ? "29%" : "65%" };
    const vals = cells.map((c) => c.value[2]).filter(Number.isFinite);
    heat(o, Array.from({ length: cols }, (_, j) => cols === 4 ? names[j]?.slice(-1) : names[j]?.slice(0,2)), Array.from({ length: Math.ceil(cells.length / cols) }, (_, j) => cols===16 ? '3rd '+alphabet[j] : names[j * cols]?.[0] || ""), cells, { range: p.diverging ? [-Math.max(1, ...vals.map(Math.abs)), Math.max(1, ...vals.map(Math.abs))] : [0, Math.max(0.01, ...vals)], sequential: !p.diverging, g });
    title(o, p.name, g, i);
  });
  return o;
}
function context(f) {
  const o = base(), d = f.data, groups = d.groups || [], fields = d.fields || [];
  heat(o, fields.map(label), groups.map((g) => `${g.name || "Q" + (g.group_id + 1)} (n=${g.n})`), groups.flatMap((g, y) => (g.median_z || []).map((z, x) => item([x, y, z], `${esc(label(fields[x]))}<br>n=${g.n}<br>Median z=${fmt(z)}<br>Original median ${fmt(g.profiles?.[x]?.quantiles?.[3])}<br>Interval ${fmt(g.left)}\u2013${fmt(g.right)}`, { bin_id: String(g.group_id), chart_id: f.chart_id }))), { range: [-3, 3], g: { left: 190, right: 35, top: 65, bottom: 125 } });
  return o;
}
function candidates(f) {
  const o = base(), d = f.data, rows = d.rows || [], percent = d.kind === "candidate_union_evidence";
  return heat(o, d.fields.map(label), rows.map((r) => r.id), rows.flatMap((r, y) => (percent ? r.percentiles : r.values).map((v, x) => item([x, y, v], `${esc(r.id)}<br>${esc(label(d.fields[x]))}: ${fmt(r.values[x])}<br>${percent ? "Within-module percentile: " + fmt(v) : "Native module score"}<br>Available modules ${r.coverage}`, { entity_id: r.id, report_entity_key: r.id, species_id: f.species_id }))), { range: percent ? [0, 100] : [0, Math.max(1, ...rows.flatMap((r) => r.values).filter(Number.isFinite))], sequential: true, g: { left: 200, right: 30, top: 35, bottom: 140 } });
}
function budget(f) {
  const o = base(), d = f.data, rna = d.kind === "rna_composition_budget", ps = d.profiles || [], narrow = f.__narrow;
  const g = narrow ? { left: 175, right: 35, top: 40, height: "42%" } : { left: 180, right: "48%", top: 40, bottom: 70 };
  if (rna) violin(o, ps, g);
  else {
    const i = grid(o, "Atoms / canonical nucleotide", g);
    o.yAxis[i] = cat(ps.map((p) => label(p.field)), { gridIndex: i, inverse: true, axisLabel: { fontSize: 11, width: 160, overflow: "break" } });
    o.series.push(intervalSeries(ps, i));
  }
  const j = grid(o, rna ? "Base composition (%)" : "Pooled atom fraction (%)", narrow ? { left: 110, right: 35, top: "67%", height: "20%" } : { left: "74%", right: 35, top: 45, bottom: 70 });
  o.xAxis[j].min = 0;
  o.xAxis[j].max = rna ? 100 : void 0;
  if (rna) {
    o.yAxis[j] = cat(["Record mean", "Pooled nts"], { gridIndex: j, inverse: true });
    (d.labels || []).forEach((s, k) => o.series.push({ type: "bar", xAxisIndex: j, yAxisIndex: j, stack: "composition", name: s, barMaxWidth: 28, data: [item([(d.record_mean[k] || 0) * 100, 0], `Equal-record mean ${s}: ${fmt((d.record_mean[k] || 0) * 100)}%`), item([d.pooled[k] === null ? null : d.pooled[k] * 100, 1], `Validated nucleotide totals ${s}: ${fmt(d.pooled[k] === null ? null : d.pooled[k] * 100)}%<br>same-record n=${d.budget_n}`)], itemStyle: { color: colors[k] }, label: { show: true, formatter: (p) => fmt(p.value[0]) + "%", fontSize: 10, color: "#fff" } }));
    o.legend = { top: 5, right: 35, data: d.labels, textStyle: { fontSize: 11 } };
  } else {
    o.yAxis[j] = cat(d.labels, { gridIndex: j, inverse: true });
    o.series.push({ type: "bar", xAxisIndex: j, yAxisIndex: j, barMaxWidth: 24, data: d.pooled.map((x, i) => item([x === null ? null : x * 100, i], `Same-record pooled ${d.labels[i]} atoms: ${fmt(x === null ? null : x * 100)}%<br>n=${d.budget_n}`)), itemStyle: { color: colors[1] } });
  }
  return o;
}
function nativeCandidates(f) {
  const o = base(), d = f.data, rows = d.rows || [], fields = d.fields.slice(1), i = grid(o, "Native island proxy score", { left: 200, right: "51%", top: 40, bottom: 115 });
  o.yAxis[i] = cat(rows.map((r) => r.id), { gridIndex: i, inverse: true, axisLabel: { fontSize: 10, width: 180, overflow: "break" } });
  o.series.push({ type: "custom", xAxisIndex: i, yAxisIndex: i, encode: { x: 0, y: 1 }, data: rows.map((r, y) => item([r.values[0], y], `${esc(r.id)}<br>Native score ${fmt(r.values[0])}<br>${r.coverage}/3 evidence modules`, { entity_id: r.id, report_entity_key: r.id, species_id: f.species_id })), renderItem: (p, a) => {
    const p0 = a.coord([0, a.value(1)]), p1 = a.coord([a.value(0), a.value(1)]);
    return { type: "group", children: [{ type: "line", shape: { x1: p0[0], y1: p0[1], x2: p1[0], y2: p1[1] }, style: { stroke: colors[0], lineWidth: 1.5 } }, { type: "circle", shape: { cx: p1[0], cy: p1[1], r: 4 }, style: { fill: colors[0] } }] };
  } });
  heat(o, fields.map(label), rows.map((r) => r.id), rows.flatMap((r, y) => r.values.slice(1).map((v, x) => item([x, y, v], `${esc(r.id)} \xB7 ${esc(fields[x])}<br>${fmt(v)}`))), { range: [0, Math.max(1, ...rows.flatMap((r) => r.values.slice(1)).filter(Number.isFinite))], sequential: true, g: { left: "73%", right: 35, top: 40, bottom: 115 } });
  o.yAxis[1].show = false;
  return o;
}
function speciesLabel(id){const p=id.split('_'),tail=id.match(/gca_(\d+)/)?.[1]?.slice(-6);return `${p[0][0].toUpperCase()}. ${p[1]||''}${tail?' · '+tail:p.length>2?' ('+p.slice(2).join(' ')+')':''}`}
function cohort(f) {
  const o = base(), d = f.data.cohort || {}, names = d.species || [], fields = d.fields || [];
  if (f.data.kind === "species_distance") {
    const order = d.order || names.map((_, i2) => i2);
    return heat(o, order.map((i2) => names[i2].replaceAll("_", " ")), order.map((i2) => names[i2].replaceAll("_", " ")), order.flatMap((a, y) => order.map((b, x) => item([x, y, d.distance?.[a]?.[b] ?? null], `${esc(names[a])} \xD7 ${esc(names[b])}<br>distance ${fmt(d.distance?.[a]?.[b])}`))), { range: [0, Math.max(0.01, ...(d.distance || []).flat())], sequential: true, g: { left: 210, right: 35, top: 40, bottom: 160 } });
  }
  if (f.data.kind === "species_dispersion") {
    const order = fields.map((_, i3) => i3).sort((a, b) => (d.z_sd?.[b] || 0) - (d.z_sd?.[a] || 0)), i2 = grid(o, "Unweighted robust z", { left: 210, right: 35, top: 35, bottom: 65 });
    o.yAxis[i2] = cat(order.map((j) => label(fields[j])), { gridIndex: i2, inverse: true, axisLabel: { width: 190, overflow: "break", fontSize: 11 } });
    o.series.push({ type: "scatter", data: order.flatMap((j, y) => names.map((s, k) => ({ ...item([d.unweighted_z[k][j], y], `${esc(s)}<br>${esc(fields[j])}: mean ${fmt(d.raw_means[k][j])}<br>valid n=${d.counts[k][fields[j]]}`), symbolSize: s === d.current_species ? 11 : 7, itemStyle: { color: s === d.current_species ? colors[3] : colors[0], opacity: 0.7 } }))) });
    return o;
  }
  const i = grid(o, `PC1 (${fmt((d.pca?.variance?.[0] || 0) * 100)}%)`, f.__narrow?{left:70,right:35,top:40,height:'39%'}:{ left: 70, right: '38%', top: 40, bottom: 90 });
  o.yAxis[i].name = `PC2 (${fmt((d.pca?.variance?.[1] || 0) * 100)}%)`;
  o.series.push({ type: "scatter", data: (d.coordinates || []).map((c, j) => ({ ...item([c[0], c[1] || 0], `${esc(names[j])}<br>Whole-population fingerprint`), name: speciesLabel(names[j]), symbolSize: names[j] === d.current_species ? 13 : 9, itemStyle: { color: colors[j % 5], borderWidth: names[j] === d.current_species ? 2 : 0, borderColor: ink } })), label: { show: true, formatter: (p) => p.name, position: "top", fontSize: 10, width: 150, overflow: "break" }, labelLayout: { moveOverlap: "shiftY" }, labelLine: { show: true } });
  const j=grid(o,'PCA component coefficient',f.__narrow?{left:180,right:35,top:'63%',height:'27%'}:{left:'84%',right:30,top:40,bottom:90});o.yAxis[j]=cat(fields.map(label),{gridIndex:j,inverse:true,axisLabel:{fontSize:10,width:140,overflow:'break'}});
  for(let pc=0;pc<Math.min(2,d.pca?.components?.length||0);pc++)o.series.push({type:'bar',xAxisIndex:j,yAxisIndex:j,name:`PC${pc+1} coefficient`,barMaxWidth:10,data:d.pca.components[pc].map((x,k)=>item([x,k],`${esc(fields[k])}<br>PC${pc+1} coefficient ${fmt(x)}`)),itemStyle:{color:colors[pc]}});
  o.legend={top:0,right:35,type:'scroll',textStyle:{fontSize:10},data:['PC1 coefficient','PC2 coefficient']};
  return o;
}
export function sequenceOption(f) {
  if (!f?.data) return base();
  const d = f.data, k = d.kind, o = base();
  if (d.cohort && k === "species_distance") {
    const c = d.cohort;
    return sharedCohortFigure("D12", { current_species: c.current_species, data: { ...c, species: c.species.map((s, i) => ({ species_id: s, label: speciesLabel(s), means: Object.fromEntries(c.fields.map((k2, j) => [k2, c.raw_means[i][j]])), counts: c.counts[i] })), z: c.unweighted_z } });
  }
  if (d.cohort) return cohort(f);
  if (d.hex) {
    const result = pair(f);
    if (d.front) result.series.push({ type: "line", data: [...d.front].sort((a, b) => a.x - b.x).map((r) => item([r.x, r.y], r.id, { entity_id: r.id, report_entity_key: r.id, species_id: f.species_id })), symbolSize: 5, lineStyle: { color: colors[3], width: 2 } });
    return result;
  }
  if (["element_density_budget", "rna_composition_budget"].includes(k)) return budget(f);
  if (["independent_intervals", "aa20_intervals"].includes(k)) {
    const ps = k === "aa20_intervals" ? (d.profiles || []).map((p) => ({ ...p, unit: "%", quantiles: p.quantiles?.map((x) => x * 100), mean: p.mean === null ? null : p.mean * 100 })) : d.profiles || [];
    return intervals(o, ps, k === "independent_intervals", f.__narrow);
  }
  if (k === "region_violins") {
    const sets = [d.profiles.slice(0, 3), d.profiles.slice(3, 6), d.profiles.slice(6, 9)];
    sets.forEach((p, i) => violin(o, p.map(x=>({...x,display_label:label(x.field.split('_')[0]),unit:['GC (%)','Nitrogen (atoms/base)','Entropy (bits)'][i]})), { left: f.__narrow ? 165 : `${16 + i * 30}%`, width: f.__narrow ? void 0 : "20%", right: f.__narrow ? 30 : void 0, top: f.__narrow ? `${7 + i * 32}%` : 45, height: f.__narrow ? "22%" : "66%" }));
    return o;
  }
  if (k === "paired_delta_histograms") {
    d.profiles.forEach((p, j) => hist(o, p, { left: `${10 + j % 2 * 49}%`, width: "36%", top: `${10 + Math.floor(j / 2) * 47}%`, height: "28%" }));
    return o;
  }
  if (k === "distribution_ecdf") return distribution(f);
  if (k === "orf_length_stop_ecdf") {
    const result = distribution(f);
    result.series = result.series.filter((s) => s.xAxisIndex !== 1);
    for (const [j, g] of d.groups.entries()) {
      const e = g.profile.ecdf;
      result.series.push({ type: "line", xAxisIndex: 1, yAxisIndex: 1, name: `Stop ${g.name}, n=${e.n}`, step: "end", showSymbol: false, data: e.x.map((x, i) => [x, e.cdf[i]]), lineStyle: { color: colors[j] } });
    }
    result.legend = { top: 0, type: "scroll", textStyle: { fontSize: 10 } };
    return result;
  }
  if (k === "core_quantile_signature") {
    const rows = d.rows || [];
    return heat(o, ["Min", "P05", "P25", "Median", "P75", "P95", "Max"], rows.map((r) => label(r.field) + (r.constant ? " \xB7 constant" : "")), rows.flatMap((r, y) => r.z.map((z, x) => item([x, y, z], `${esc(r.field)}<br>n=${r.n}<br>Raw ${fmt(r.quantiles?.[x])}<br>Robust z ${fmt(z)}`))), { range: [-4, 4] });
  }
  if (["biotype_and_evidence_bars", "biotype_gene_coverage"].includes(k)) return bars(f);
  if (k === "biotype_length_violins") return violin(o, d.categories.map((c) => ({ ...c.profile, field: c.name })));
  if (k === "biotype_orf_evidence_matrix") {
    const rows = d.categories || [];
    return heat(o, ["Proxy valid + stop", "Proxy valid, no stop", "Invalid ORF proxy", "Stop unavailable"], rows.map((r) => r.name), rows.flatMap((r, y) => r.evidence.map((v, x) => ({ ...item([x, y, Math.log1p(v)], `${esc(r.name)}<br>n=${v} (${fmt(100 * v / r.count)}%)`), display: `${v}
${fmt(100 * v / r.count)}%` }))), { range: [0, Math.max(1, ...rows.flatMap((r) => r.evidence).map((v) => Math.log1p(v)))], sequential: true });
  }
  if (d.panels) return grammar(f);
  if (["quantile_strata_context", "kmeans_context"].includes(k)) return context(f);
  if (k === "gc3_entropy_stratified_violin") return violin(o, d.groups.map((g) => ({ ...g.profiles[0], field: `GC3 Q${g.group_id + 1} (${fmt(g.left)}\u2013${fmt(g.right)})` })));
  if (k === "gc_length_stratified_ecdf") {
    hist(o, d.profile, { left: 70, right: "48%", top: 40, bottom: 65 });
    d.groups.forEach((g, j) => {
      const i = 1;
      if (j === 0) grid(o, "GC fraction", { left: "65%", right: 35, top: 40, bottom: 65 });
      o.yAxis[i].max = 1.02;
      o.series.push({ type: "line", xAxisIndex: i, yAxisIndex: i, name: `Q${j + 1}, n=${g.n}`, step: "end", showSymbol: false, data: g.profiles[0].ecdf.x.map((x, k2) => [x, g.profiles[0].ecdf.cdf[k2]]), lineStyle: { color: colors[j] } });
    });
    o.legend = { type: "scroll", top: 0 };
    return o;
  }
  if (["pairwise_spearman_matrix", "rna_protein_cross_matrix"].includes(k)) return matrix(f);
  if (k === "threshold_network") {
    const threshold = f.__threshold ?? 0.65;
    const edges = d.cells.filter((c) => c.x > c.y && c.rho !== null && Math.abs(c.rho) >= threshold);
    o.series = [{ type: "graph", layout: "circular", roam: false, data: d.x_fields.map((s, i) => ({ name: label(s), id: String(i), symbolSize: 24, itemStyle: { color: colors[i % 5] } })), links: edges.map((c) => ({ source: String(c.x), target: String(c.y), value: c.rho, lineStyle: { color: c.rho < 0 ? colors[4] : colors[0], type: c.rho < 0 ? "dashed" : "solid", width: 1 + Math.abs(c.rho) * 3 }, tip: `${esc(label(c.x_field))} \xD7 ${esc(label(c.y_field))}<br>\u03C1=${fmt(c.rho)}, n=${c.n}` })), label: { show: true, fontSize: 11, width: 130, overflow: "break" }, left: 110, right: 110, top: 80, bottom: 80 }];
    return o;
  }
  if (k === "native_candidate_evidence") return nativeCandidates(f);
  if (k === "candidate_union_evidence") return candidates(f);
  if (["chromosome_cumulative_tracks", "chromosome_score_tracks"].includes(k)) {
    const tracks = (d.tracks || []).slice(0, 4);
    tracks.forEach((t, j) => {
      const i = grid(o, "Coordinate (bp)", { left: 90, right: 40, top: `${10 + j * 23}%`, height: "12%" });
      o.yAxis[i].name = k.includes("cumulative") ? "\u03A3(G\u2212C)" : "Island proxy";
      title(o, t.seqid, o.grid[i], j);
      if(k==='chromosome_score_tracks'){
        const segments=t.bins.slice(1).flatMap((b,q)=>{const a=t.bins[q];return [a.min,a.max,b.min,b.max].every(Number.isFinite)?[item([a.x,b.x,a.min,a.max,b.min,b.max])]:[]});
        o.series.push({type:'custom',silent:true,clip:true,xAxisIndex:i,yAxisIndex:i,encode:{x:[0,1],y:[2,3,4,5]},data:segments,renderItem:(p,a)=>({type:'polygon',shape:{points:[[a.value(0),a.value(2)],[a.value(1),a.value(4)],[a.value(1),a.value(5)],[a.value(0),a.value(3)]].map(p=>a.coord(p))},style:{fill:colors[j%5],opacity:.2}})});
      }
      o.series.push({ type: "line", xAxisIndex: i, yAxisIndex: i, showSymbol: false, connectNulls: false, data: t.bins.map((b) => item([b.x, b.value], `${esc(t.seqid)}<br>n=${b.count}<br>${fmt(b.value)}${k==='chromosome_score_tracks'?'<br>IQR '+fmt(b.min)+'–'+fmt(b.max):''}`, { bin_id: String(b.bin_id), chart_id: f.chart_id })), lineStyle: { color: colors[j % 5], width: 1.5 } });
    });
    return o;
  }
  return intervals(o, d.profiles || []);
}
export function sequenceHeight(f) {
  const k = f?.data?.kind;
  if(f.__narrow&&['species_fingerprint_pca','species_dinuc_pca'].includes(k))return k==='species_dinuc_pca'?1200:950;
  if (k === "core_quantile_signature") return Math.max(600, (f.data.rows?.length || 0) * 22 + 180);
  if (k === "candidate_union_evidence") return Math.max(640, (f.data.rows?.length || 0) * 30 + 200);
  if (k?.includes("chromosome")) return 900;
  if (k === "region_violins" && f.__narrow) return 1e3;
  if (k === "independent_intervals") return f.__narrow ? 900 : 520;
  if (k === "paired_delta_histograms") return 800;
  if (f?.data?.cohort?.species?.length > 8) return Math.max(660, f.data.cohort.species.length * 28 + 250);
  return 610;
}
