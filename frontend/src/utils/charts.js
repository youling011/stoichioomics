const axisColor = '#5e7993'
const textColor = '#163550'
const splitColor = 'rgba(42, 89, 140, 0.08)'
const palette = ['#2F77C8', '#58A6D8', '#8B5CF6', '#10B981', '#F59E0B', '#EF4444', '#3B82F6', '#14B8A6']
const softPalette = ['rgba(47,119,200,0.16)', 'rgba(88,166,216,0.16)', 'rgba(139,92,246,0.16)', 'rgba(16,185,129,0.16)', 'rgba(245,158,11,0.18)', 'rgba(239,68,68,0.15)']
const missingColor = '#d7dde5'
const divergingColors = ['#1f5d9a', '#9fc5e8', '#f7fafc', '#f2b06d', '#c43c39']
const sequentialColors = ['#eef6ff', '#cfe5fb', '#93bee7', '#4f8dcf', '#1f5d9a']
const distanceColors = ['#f7fbff', '#d8ebfb', '#9dc8ec', '#5a98d5', '#205b96']

export const baseGrid = { top: 76, right: 56, bottom: 88, left: 118, containLabel: true }

function wrapLabel(label = '', max = 14) {
  const text = String(label || '').replaceAll('_', ' ')
  if (text.length <= max) return text
  const words = text.split(' ')
  const lines = []
  let current = ''
  for (const word of words) {
    const next = current ? `${current} ${word}` : word
    if (next.length > max && current) {
      lines.push(current)
      current = word
      if (lines.length === 1) break
    } else {
      current = next
    }
  }
  if (current) lines.push(current)
  return lines.slice(0, 2).join('\n')
}

function formatAxisValue(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return String(value ?? '')
  if (Math.abs(n) < 0.005) return '0'
  if (Math.abs(n) >= 1000000) return n.toExponential(1)
  if (Math.abs(n) >= 1000) return n.toLocaleString(undefined, { maximumFractionDigits: 0 })
  const fixed = n.toFixed(2)
  return fixed.replace(/\.00$/, '').replace(/(\.\d)0$/, '$1')
}

function isNumericLike(value) {
  if (value === null || value === undefined || value === '') return false
  return Number.isFinite(Number(value))
}

function formatCategoryAxisLabel(value, max = 14) {
  if (isNumericLike(value)) return formatAxisValue(value)
  return wrapLabel(value, max)
}

function shortMetricLabel(key = '') {
  return String(key || '')
    .replaceAll('_per_', ' / ')
    .replaceAll('_vs_', ' vs ')
    .replaceAll('_', ' ')
}

function chartBase(extra = {}) {
  return {
    color: palette,
    animationDuration: 500,
    textStyle: { color: textColor, fontFamily: 'Inter, system-ui, sans-serif' },
    tooltip: {
      backgroundColor: 'rgba(255,255,255,0.96)',
      borderColor: 'rgba(42,89,140,0.12)',
      borderWidth: 1,
      textStyle: { color: '#163550' },
      extraCssText: 'box-shadow: 0 16px 44px rgba(63,112,170,0.14); border-radius: 14px;',
      confine: true,
    },
    ...extra,
  }
}

function finiteNumber(value, fallback = 0) {
  const n = Number(value)
  return Number.isFinite(n) ? n : fallback
}

function nullableNumber(value) {
  if (value === null || value === undefined || value === '') return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

function toMetricKeys(rows = [], exclusions = []) {
  const keys = new Set()
  rows.forEach((row) => {
    Object.keys(row || {}).forEach((key) => {
      if (!exclusions.includes(key)) keys.add(key)
    })
  })
  return [...keys]
}

function metricValues(rows = [], key = '') {
  return rows.map((row) => finiteNumber(row?.[key], NaN)).filter((v) => Number.isFinite(v))
}

function stableExtent(values = [], opts = {}) {
  const { padRatio = 0.12, includeZero = false, fallbackMin = 0, fallbackMax = 1 } = opts
  const finite = values.filter((v) => Number.isFinite(v))
  if (!finite.length) return { min: fallbackMin, max: fallbackMax, span: fallbackMax - fallbackMin }

  let min = Math.min(...finite)
  let max = Math.max(...finite)
  if (includeZero) {
    min = Math.min(min, 0)
    max = Math.max(max, 0)
  }

  if (min === max) {
    const anchor = Math.abs(min) || 1
    const pad = anchor * 0.3
    return { min: min - pad, max: max + pad, span: pad * 2 }
  }

  const span = max - min
  const pad = span * padRatio
  return { min: min - pad, max: max + pad, span: span + pad * 2 }
}

function normalizeValue(value, extent) {
  if (!extent || !Number.isFinite(extent.min) || !Number.isFinite(extent.max)) return 0.5
  const span = extent.max - extent.min
  if (!span) return 0.5
  const scaled = (finiteNumber(value) - extent.min) / span
  return Math.max(0, Math.min(1, scaled))
}

function formatValue(value, digits = 2) {
  const n = Number(value)
  if (!Number.isFinite(n)) return 'NA'
  if (Math.abs(n) >= 1000) return n.toLocaleString(undefined, { maximumFractionDigits: 0 })
  if (Math.abs(n) >= 100) return n.toFixed(1)
  if (Math.abs(n) >= 10) return n.toFixed(Math.min(2, digits))
  return n.toFixed(digits)
}

function correlation(rows = [], xIndex = 0, yIndex = 1) {
  if (rows.length < 3) return null
  const xs = rows.map((row) => finiteNumber(row.value?.[xIndex], NaN)).filter((v) => Number.isFinite(v))
  const ys = rows.map((row) => finiteNumber(row.value?.[yIndex], NaN)).filter((v) => Number.isFinite(v))
  if (xs.length !== ys.length || xs.length < 3) return null
  const meanX = xs.reduce((sum, v) => sum + v, 0) / xs.length
  const meanY = ys.reduce((sum, v) => sum + v, 0) / ys.length
  const numerator = xs.reduce((sum, v, i) => sum + ((v - meanX) * (ys[i] - meanY)), 0)
  const denomX = Math.sqrt(xs.reduce((sum, v) => sum + ((v - meanX) ** 2), 0))
  const denomY = Math.sqrt(ys.reduce((sum, v) => sum + ((v - meanY) ** 2), 0))
  if (!denomX || !denomY) return null
  return numerator / (denomX * denomY)
}

function rankedValues(values = []) {
  const sorted = values
    .map((value, index) => ({ value, index }))
    .sort((a, b) => a.value - b.value)
  const ranks = Array(values.length).fill(0)
  let i = 0
  while (i < sorted.length) {
    let j = i + 1
    while (j < sorted.length && sorted[j].value === sorted[i].value) j += 1
    const rank = (i + j + 1) / 2
    for (let k = i; k < j; k += 1) ranks[sorted[k].index] = rank
    i = j
  }
  return ranks
}

function spearmanCorrelation(rows = []) {
  if (rows.length < 3) return null
  const xs = rows.map((row) => finiteNumber(row.value?.[0], NaN))
  const ys = rows.map((row) => finiteNumber(row.value?.[1], NaN))
  if (xs.some((v) => !Number.isFinite(v)) || ys.some((v) => !Number.isFinite(v))) return null
  const rx = rankedValues(xs)
  const ry = rankedValues(ys)
  return correlation(rx.map((x, index) => ({ value: [x, ry[index]] })))
}

function median(values = []) {
  const finite = values.filter((v) => Number.isFinite(v)).sort((a, b) => a - b)
  if (!finite.length) return null
  const mid = Math.floor(finite.length / 2)
  return finite.length % 2 ? finite[mid] : (finite[mid - 1] + finite[mid]) / 2
}

function trendLineData(values = []) {
  if (values.length < 3) return []
  const xs = values.map((row) => row.value[0])
  const ys = values.map((row) => row.value[1])
  const meanX = xs.reduce((sum, v) => sum + v, 0) / xs.length
  const meanY = ys.reduce((sum, v) => sum + v, 0) / ys.length
  const denom = xs.reduce((sum, v) => sum + ((v - meanX) ** 2), 0)
  if (!denom) return []
  const slope = xs.reduce((sum, v, i) => sum + ((v - meanX) * (ys[i] - meanY)), 0) / denom
  const intercept = meanY - slope * meanX
  const minX = Math.min(...xs)
  const maxX = Math.max(...xs)
  return [[minX, slope * minX + intercept], [maxX, slope * maxX + intercept]]
}

function binnedMedianData(values = [], binCount = 24) {
  if (values.length < 30) return []
  const xs = values.map((row) => row.value[0])
  const minX = Math.min(...xs)
  const maxX = Math.max(...xs)
  if (minX === maxX) return []
  const bins = Array.from({ length: binCount }, () => [])
  values.forEach((row) => {
    const idx = Math.min(binCount - 1, Math.max(0, Math.floor(((row.value[0] - minX) / (maxX - minX)) * binCount)))
    bins[idx].push(row.value[1])
  })
  return bins
    .map((bucket, idx) => {
      const y = median(bucket)
      if (y === null) return null
      const x = minX + ((idx + 0.5) / binCount) * (maxX - minX)
      return [x, y]
    })
    .filter(Boolean)
}

function statsSummary(values = [], meta = {}) {
  const n = meta?.stats?.n ?? values.length
  const pearson = meta?.stats?.pearson_r ?? correlation(values)
  const spearman = meta?.stats?.spearman_r ?? spearmanCorrelation(values)
  const parts = [`n=${n}`]
  if (Number.isFinite(Number(pearson))) parts.push(`Pearson r=${Number(pearson).toFixed(3)}`)
  if (Number.isFinite(Number(spearman))) parts.push(`Spearman rho=${Number(spearman).toFixed(3)}`)
  if (meta?.recommended_view) parts.push(`view=${meta.recommended_view}`)
  return parts.join(' · ')
}

function scatterRows(points = [], xKey, yKey, sizeKey = null, opts = {}) {
  return points
    .map((row) => {
      const xSource = opts.xTransform ? opts.xTransform(row?.[xKey], row) : row?.[xKey]
      const ySource = opts.yTransform ? opts.yTransform(row?.[yKey], row) : row?.[yKey]
      const x = finiteNumber(xSource, NaN)
      const y = finiteNumber(ySource, NaN)
      if (!Number.isFinite(x) || !Number.isFinite(y)) return null
      const pair = [x, y]
      if (sizeKey) pair.push(Math.max(0.1, finiteNumber(row?.[sizeKey], 1)))
      return { value: pair, raw: row }
    })
    .filter(Boolean)
}

function valueAxis(name = '', extra = {}) {
  const isYAxis = extra?.__axis === 'y'
  return {
    type: 'value',
    name,
    nameLocation: extra.nameLocation || 'middle',
    nameGap: extra.nameGap || (isYAxis ? 82 : 46),
    nameTextStyle: { color: axisColor, width: isYAxis ? 150 : 120, overflow: 'truncate', ellipsis: '...' },
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: {
      color: axisColor,
      formatter: formatAxisValue,
      hideOverlap: true,
      margin: 10,
      width: 70,
      overflow: 'truncate',
    },
    splitLine: { lineStyle: { color: splitColor } },
    splitNumber: 5,
    scale: true,
    ...extra,
    __axis: undefined,
  }
}

function categoryAxis(data = [], name = '', rotate = 0) {
  const numericLike = (data || []).filter((value) => value !== null && value !== undefined && value !== '').every(isNumericLike)
  return {
    type: 'category',
    data,
    name,
    nameLocation: 'middle',
    nameGap: rotate ? 58 : 46,
    nameTextStyle: { color: axisColor },
    axisLine: { lineStyle: { color: 'rgba(42,89,140,0.18)' } },
    axisTick: { show: false },
    axisLabel: {
      color: axisColor,
      rotate,
      hideOverlap: true,
      interval: 'auto',
      overflow: 'truncate',
      width: rotate ? 86 : 124,
      margin: 10,
      formatter: (value) => numericLike ? formatAxisValue(value) : formatCategoryAxisLabel(value, rotate ? 9 : 14),
    },
  }
}

export function barOption(categories = [], values = [], name = '', horizontal = false) {
  const extent = stableExtent(values.map((v) => finiteNumber(v)), { includeZero: true })
  return chartBase({
    grid: baseGrid,
    xAxis: horizontal ? valueAxis(name, { min: extent.min, max: extent.max }) : categoryAxis(categories, '', categories.length > 6 ? 24 : 0),
    yAxis: horizontal ? categoryAxis(categories) : valueAxis(name, { min: extent.min, max: extent.max, __axis: 'y' }),
    series: [{
      type: 'bar',
      data: values,
      barMaxWidth: 34,
      clip: true,
      itemStyle: {
        borderRadius: horizontal ? [0, 10, 10, 0] : [10, 10, 0, 0],
        color: (params) => palette[params.dataIndex % palette.length],
      },
      emphasis: { itemStyle: { opacity: 0.9 } },
    }],
  })
}

export function areaHistOption(hist, xName = '', yName = 'Count') {
  return histogramOption(hist, xName, yName)
}

export function histogramOption(hist, xName = '', yName = 'Count', opts = {}) {
  const centers = (hist?.centers || hist?.bin_centers || []).map((value) => nullableNumber(value)).filter((value) => value !== null)
  const counts = (hist?.counts || hist?.values || []).map((v) => nullableNumber(v))
  const values = counts.map((value) => value ?? 0)
  const extent = stableExtent(counts, { includeZero: true })
  return chartBase({
    __exportName: opts.exportName || 'histogram_distribution',
    __semantic: {
      minPoints: opts.minPoints ?? 2,
      totalCount: hist?.total_count ?? hist?.n ?? counts.length,
      displayedCount: counts.filter((value) => value !== null).length,
      method: opts.method || hist?.method || 'binned numeric distribution',
      aggregation: opts.aggregation || hist?.aggregation || 'bin_count',
      release: opts.release || hist?.release,
    },
    __dataRows: centers.map((center, index) => ({
      bin_center: center,
      count: values[index] ?? 0,
      bin_n: hist?.bin_n?.[index] ?? hist?.bin_counts?.[index] ?? values[index] ?? 0,
      bin_start: hist?.bin_start?.[index],
      bin_end: hist?.bin_end?.[index],
    })),
    grid: baseGrid,
    xAxis: valueAxis(xName),
    yAxis: valueAxis(yName, { min: extent.min, max: extent.max, __axis: 'y' }),
    series: [{
      type: 'bar',
      clip: true,
      barWidth: '78%',
      itemStyle: {
        color: 'rgba(47,119,200,0.7)',
        borderRadius: [4, 4, 0, 0],
      },
      data: centers.map((center, index) => [center, values[index] ?? 0]),
    }],
  })
}

export const continuousHistogramOption = histogramOption

export function continuousProfileOption(profile, xName = 'Coordinate', yName = 'Mean value', opts = {}) {
  const centers = profile?.centers || profile?.bin_centers || []
  const values = profile?.counts || profile?.values || []
  const binN = profile?.bin_n || profile?.bin_counts || []
  const rows = centers
    .map((center, index) => {
      const x = nullableNumber(center)
      const y = nullableNumber(values[index])
      if (x === null) return null
      return {
        value: [x, y],
        bin_n: Number(binN[index] || 0),
        bin_start: profile?.bin_start?.[index],
        bin_end: profile?.bin_end?.[index],
      }
    })
    .filter(Boolean)
  const finiteY = rows.map((row) => row.value[1]).filter((value) => value !== null)
  const extent = stableExtent(finiteY, { includeZero: opts.includeZero === true })
  return chartBase({
    __exportName: opts.exportName || 'coordinate_profile',
    __semantic: {
      minPoints: opts.minPoints ?? 3,
      totalCount: profile?.n ?? rows.reduce((sum, row) => sum + Number(row.bin_n || 0), 0),
      displayedCount: rows.filter((row) => row.value[1] !== null).length,
      method: opts.method || 'continuous coordinate profile; empty bins remain missing',
      aggregation: opts.aggregation || profile?.aggregation || 'binned mean',
      release: opts.release || profile?.release,
    },
    __dataRows: rows.map((row) => ({
      x: row.value?.[0],
      y: row.value?.[1],
      bin_n: row.bin_n ?? 0,
      bin_start: row.bin_start,
      bin_end: row.bin_end,
    })),
    grid: baseGrid,
    tooltip: {
      ...chartBase().tooltip,
      formatter: (params) => {
        const row = params.data || {}
        const y = row.value?.[1]
        const lines = [
          `${xName}: ${formatValue(row.value?.[0])}`,
          `${yName}: ${y === null ? 'missing' : formatValue(y)}`,
          `bin_n: ${row.bin_n ?? 0}`,
        ]
        if (row.bin_start !== undefined || row.bin_end !== undefined) {
          lines.push(`bin: ${formatValue(row.bin_start)} to ${formatValue(row.bin_end)}`)
        }
        return lines.join('<br/>')
      },
    },
    xAxis: valueAxis(xName),
    yAxis: valueAxis(yName, { min: extent.min, max: extent.max, __axis: 'y' }),
    series: [{
      type: 'line',
      smooth: false,
      connectNulls: false,
      showSymbol: rows.length <= 80,
      symbolSize: 5,
      areaStyle: opts.area === false ? undefined : { color: 'rgba(47,119,200,0.12)' },
      lineStyle: { color: '#2F77C8', width: 2 },
      data: rows,
    }],
  })
}

export const coordinateProfileOption = continuousProfileOption

export function boxplotSummaryOption(summary, xName = 'Distribution summary') {
  const p05 = finiteNumber(summary?.p05, NaN)
  const p25 = finiteNumber(summary?.p25, NaN)
  const p50 = finiteNumber(summary?.p50, NaN)
  const p75 = finiteNumber(summary?.p75, NaN)
  const p95 = finiteNumber(summary?.p95, NaN)
  const hasData = [p05, p25, p50, p75, p95].every((v) => Number.isFinite(v))
  const values = hasData ? [[p05, p25, p50, p75, p95]] : []
  const extent = stableExtent(hasData ? [p05, p95] : [], { includeZero: false })
  return chartBase({
    grid: baseGrid,
    xAxis: categoryAxis([xName], ''),
    yAxis: valueAxis('', { min: extent.min, max: extent.max, __axis: 'y' }),
    series: [{
      type: 'boxplot',
      data: values,
      itemStyle: {
        color: 'rgba(47,119,200,0.2)',
        borderColor: 'rgba(47,119,200,0.9)',
        borderWidth: 2,
      },
    }],
  })
}

export function buildEnhancedScatterOption(points = [], xKey, yKey, xName = '', yName = '', opts = {}) {
  const sizeKey = typeof opts === 'string' ? opts : opts?.sizeKey || null
  const meta = typeof opts === 'object' ? opts?.meta || {} : {}
  const values = scatterRows(points, xKey, yKey, sizeKey, opts || {})

  const sizeValues = sizeKey ? values.map((x) => x.value[2]) : [1]
  const minSize = Math.min(...sizeValues)
  const maxSize = Math.max(...sizeValues)
  const includeZero = Boolean(opts?.includeZero || opts?.quadrant)
  const xExtent = stableExtent(values.map((row) => row.value[0]), { includeZero })
  const yExtent = stableExtent(values.map((row) => row.value[1]), { includeZero })
  const trend = opts?.showTrend === false ? [] : trendLineData(values)
  const binned = opts?.showBinnedMedian === false ? [] : binnedMedianData(values, opts?.bins || 24)
  const pointCount = values.length
  const useSmallPoints = pointCount > 1000
  const currentId = String(opts?.currentSpeciesId || opts?.currentEntityId || '')
  const currentPoints = currentId
    ? values.filter((row) => [row.raw?.species_id, row.raw?.entity_id, row.raw?.gene_id, row.raw?.transcript_id, row.raw?.protein_id].map((v) => String(v || '')).includes(currentId))
    : []
  const backgroundValues = currentPoints.length
    ? values.filter((row) => !currentPoints.includes(row))
    : values
  const markLineData = []
  ;(meta?.reference_lines || opts?.referenceLines || []).forEach((line) => {
    if (!line) return
    if (line.kind === 'x' || line.axis === 'x') markLineData.push({ xAxis: Number(line.value || 0), name: line.label || 'x reference' })
    if (line.kind === 'y' || line.axis === 'y') markLineData.push({ yAxis: Number(line.value || 0), name: line.label || 'y reference' })
    if (line.kind === 'identity') markLineData.push([{ coord: [xExtent.min, xExtent.min], name: line.label || 'y=x' }, { coord: [xExtent.max, xExtent.max] }])
  })
  if (opts?.quadrant) {
    markLineData.push({ xAxis: 0, name: 'x=0' }, { yAxis: 0, name: 'y=0' })
  }

  return chartBase({
    title: opts?.title ? {
      text: opts.title,
      subtext: wrapLabel(opts?.subtitle || statsSummary(values, meta), 68),
      textStyle: { fontSize: 14, color: textColor },
      subtextStyle: { fontSize: 11, color: axisColor, lineHeight: 15 },
      left: 8,
      top: 4,
    } : undefined,
    grid: baseGrid,
    tooltip: {
      ...chartBase().tooltip,
      formatter: (params) => {
        const d = params.data.raw || {}
        const parts = [d.gene_name || d.gene_id || d.protein_id || d.transcript_id || d.entity_id || 'entity']
        parts.push(`${xName || xKey}: ${formatValue(params.data.value[0])}`)
        parts.push(`${yName || yKey}: ${formatValue(params.data.value[1])}`)
        if (sizeKey) parts.push(`${sizeKey}: ${formatValue(d[sizeKey])}`)
        return parts.join('<br/>')
      },
    },
    xAxis: valueAxis(xName || xKey, { min: xExtent.min, max: xExtent.max }),
    yAxis: valueAxis(yName || yKey, { min: yExtent.min, max: yExtent.max, __axis: 'y' }),
    series: [
      {
        name: 'points',
        type: 'scatter',
        clip: true,
        data: backgroundValues,
        symbolSize: (data) => {
          if (!sizeKey) return useSmallPoints ? 6 : 9
          const v = finiteNumber(data[2], 1)
          const denom = maxSize - minSize || 1
          return Math.max(7, Math.min(28, 7 + ((v - minSize) / denom) * 18))
        },
        itemStyle: { color: useSmallPoints ? 'rgba(47,119,200,0.38)' : 'rgba(47,119,200,0.66)', borderColor: 'rgba(255,255,255,0.55)', borderWidth: 0.5 },
        emphasis: { itemStyle: { color: palette[2] } },
        markLine: markLineData.length ? {
          symbol: 'none',
          silent: true,
          label: { color: axisColor, formatter: '{b}' },
          lineStyle: { color: 'rgba(15,23,42,0.42)', type: 'dashed', width: 1.2 },
          data: markLineData,
        } : undefined,
      },
      ...(currentPoints.length ? [{
        name: 'current',
        type: 'scatter',
        clip: true,
        data: currentPoints,
        symbolSize: 15,
        itemStyle: { color: '#D94B45', borderColor: '#7F1D1D', borderWidth: 1.5 },
        z: 10,
      }] : []),
      ...(trend.length ? [{
        name: 'trend',
        type: 'line',
        data: trend,
        symbol: 'none',
        lineStyle: { color: '#F59E0B', width: 2 },
        tooltip: { show: false },
      }] : []),
      ...(binned.length ? [{
        name: 'binned median',
        type: 'line',
        data: binned,
        symbol: 'circle',
        symbolSize: 4,
        lineStyle: { color: '#8B5CF6', width: 2, type: 'dashed' },
        itemStyle: { color: '#8B5CF6' },
      }] : []),
    ],
  })
}

export function scatterOption(points = [], xKey, yKey, xName = '', yName = '', sizeKey = null) {
  return buildEnhancedScatterOption(points, xKey, yKey, xName, yName, { sizeKey })
}

export function buildQuadrantScatterOption(points = [], xKey, yKey, xName = '', yName = '', opts = {}) {
  return buildEnhancedScatterOption(points, xKey, yKey, xName, yName, {
    ...opts,
    quadrant: true,
    includeZero: true,
    title: opts.title || `${xName || xKey} vs ${yName || yKey}`,
    subtitle: opts.subtitle || 'Quadrant scatter: x=0 and y=0 separate same-direction and opposite-direction shifts.',
  })
}

export function buildIdentityScatterOption(points = [], xKey, yKey, xName = '', yName = '', opts = {}) {
  return buildEnhancedScatterOption(points, xKey, yKey, xName, yName, {
    ...opts,
    referenceLines: [...(opts.referenceLines || []), { kind: 'identity', label: 'y=x' }],
    title: opts.title || `${xName || xKey} consistency`,
    subtitle: opts.subtitle || 'Identity scatter: points near y=x indicate agreement; distant points are residual candidates.',
  })
}

export function buildLogScatterOption(points = [], xKey, yKey, xName = '', yName = '', opts = {}) {
  return buildEnhancedScatterOption(points, xKey, yKey, `log10 ${xName || xKey}`, yName, {
    ...opts,
    xTransform: (value) => {
      const num = finiteNumber(value, NaN)
      return Number.isFinite(num) && num > 0 ? Math.log10(num) : NaN
    },
    title: opts.title || `${xName || xKey} vs ${yName || yKey}`,
    subtitle: opts.subtitle || 'Length axis is log10-transformed to avoid long-tail compression.',
  })
}

export function buildOrdinationOption(points = [], xKey, yKey, xName = '', yName = '', opts = {}) {
  return buildEnhancedScatterOption(points, xKey, yKey, xName, yName, {
    ...opts,
    showTrend: false,
    showBinnedMedian: false,
    title: opts.title || 'Ordination map',
    subtitle: opts.subtitle || 'Distances are descriptive in projected feature space; this is not a phylogenetic tree.',
  })
}

export function buildFormulaCardOption(title = '', formula = '', note = '') {
  return chartBase({
    grid: baseGrid,
    xAxis: { show: false },
    yAxis: { show: false },
    graphic: [
      { type: 'text', left: 24, top: 34, style: { text: title, fill: textColor, fontSize: 16, fontWeight: 700 } },
      { type: 'text', left: 24, top: 92, style: { text: formula, fill: '#2F77C8', fontSize: 18, fontWeight: 700 } },
      { type: 'text', left: 24, right: 24, top: 150, style: { text: note, fill: axisColor, fontSize: 13, lineHeight: 20, width: 520 } },
    ],
    series: [],
  })
}

export function heatmapOption(matrixObj = {}, options = {}) {
  const {
    details = [],
    method = '',
    evidenceLevel = '',
    nFallback = null,
    missingPolicy = '',
  } = options || {}
  const keys = Object.keys(matrixObj || {})
  const data = []
  keys.forEach((rowKey, i) => {
    keys.forEach((colKey, j) => {
      const value = nullableNumber(matrixObj?.[rowKey]?.[colKey])
      data.push(value === null
        ? { value: [j, i, null], itemStyle: { color: missingColor }, missing: true }
        : [j, i, value])
    })
  })
  const detailMap = new Map()
  ;(details || []).forEach((item) => {
    if (!item) return
    const a = String(item.feature_a || item.source || '').trim()
    const b = String(item.feature_b || item.target || '').trim()
    if (!a || !b) return
    detailMap.set(`${a}||${b}`, item)
    detailMap.set(`${b}||${a}`, item)
  })
  return chartBase({
    grid: { top: 70, right: 20, bottom: 62, left: 128, containLabel: true },
    tooltip: {
      ...chartBase().tooltip,
      formatter: (params) => {
        const xKey = keys[params?.data?.[0]] || ''
        const yKey = keys[params?.data?.[1]] || ''
        const datum = params?.data?.value || params?.data || []
        const corrValue = datum?.[2]
        const detail = detailMap.get(`${xKey}||${yKey}`) || null
        const lines = [`${shortMetricLabel(yKey)} vs ${shortMetricLabel(xKey)}`]
        lines.push(corrValue === null || corrValue === undefined ? 'r: missing' : `r: ${formatValue(corrValue, 4)}`)
        const nValue = detail?.n ?? nFallback
        if (nValue !== null && nValue !== undefined && nValue !== '') {
          lines.push(`n: ${nValue}`)
        }
        const pValue = detail?.p_value
        if (pValue !== null && pValue !== undefined) {
          lines.push(`p-value: ${formatValue(pValue, 6)}`)
        }
        const fdr = detail?.fdr
        if (fdr !== null && fdr !== undefined) {
          lines.push(`FDR: ${formatValue(fdr, 6)}`)
        }
        const detailMethod = detail?.method || method
        if (detailMethod) {
          lines.push(`method: ${detailMethod}`)
        }
        if (missingPolicy) {
          lines.push(`missing: ${missingPolicy}`)
        }
        if (evidenceLevel) {
          lines.push(`evidence: ${evidenceLevel}`)
        }
        return lines.join('<br/>')
      },
    },
    xAxis: categoryAxis(keys, '', 26),
    yAxis: categoryAxis(keys),
    visualMap: {
      min: -1,
      max: 1,
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: 10,
      inRange: { color: divergingColors },
      text: ['positive', 'negative'],
      textStyle: { color: axisColor },
    },
    series: [{ type: 'heatmap', data, itemStyle: { borderColor: 'rgba(255,255,255,0.78)', borderWidth: 1 } }],
  })
}

export const divergingHeatmapOption = heatmapOption

export function matrixHeatmapOption(xLabels = [], yLabels = [], values = [], opts = {}) {
  const min = Number.isFinite(Number(opts.min)) ? Number(opts.min) : 0
  const max = Number.isFinite(Number(opts.max)) ? Number(opts.max) : 1
  const scaleType = opts.scaleType || opts.scale_type || (
    min < 0 && max > 0 ? 'effect' : (opts.distance ? 'distance' : 'coverage')
  )
  const visualColors = ['correlation', 'zscore', 'z-score', 'effect', 'signed'].includes(scaleType)
    ? divergingColors
    : (scaleType === 'distance' ? distanceColors : sequentialColors)
  const visualMin = ['correlation', 'zscore', 'z-score', 'effect', 'signed'].includes(scaleType) ? Math.min(min, -Math.abs(max)) : min
  const visualMax = ['correlation', 'zscore', 'z-score', 'effect', 'signed'].includes(scaleType) ? Math.max(max, Math.abs(min)) : max
  const detailMap = new Map()
  ;(opts.details || []).forEach((item) => {
    if (!item) return
    const key = `${item.field || item.x || ''}||${item.omics || item.y || ''}`
    detailMap.set(key, item)
  })
  return chartBase({
    __exportName: opts.exportName || 'matrix_heatmap',
    __semantic: {
      minPoints: opts.minPoints ?? 1,
      totalCount: values.length,
      displayedCount: values.filter((item) => nullableNumber(item?.[2]) !== null).length,
      method: opts.method || `${scaleType} matrix heatmap; null cells rendered as missing`,
      aggregation: opts.aggregation || 'matrix cell',
    },
    __dataRows: values.map((item) => ({
      x_index: item?.[0],
      y_index: item?.[1],
      x_label: xLabels[item?.[0]],
      y_label: yLabels[item?.[1]],
      value: nullableNumber(item?.[2]),
      scale_type: scaleType,
    })),
    grid: { top: 74, right: 26, bottom: 68, left: 142, containLabel: true },
    tooltip: {
      ...chartBase().tooltip,
      formatter: (params) => {
        const xLabel = xLabels[params?.data?.[0]] || ''
        const yLabel = yLabels[params?.data?.[1]] || ''
        const datum = params?.data?.value || params?.data || []
        const value = datum?.[2]
        const detail = detailMap.get(`${xLabel}||${yLabel}`) || null
        const lines = [`${yLabel} / ${xLabel}`, value === null || value === undefined ? 'value: missing' : `value: ${formatValue(value)}`]
        if (detail) {
          if (detail.present_count !== undefined) lines.push(`present: ${detail.present_count}`)
          if (detail.total !== undefined) lines.push(`total: ${detail.total}`)
          if (detail.missing_ratio !== undefined) lines.push(`missing ratio: ${formatValue(detail.missing_ratio)}`)
          if (detail.reason) lines.push(`reason: ${detail.reason}`)
        }
        return lines.join('<br/>')
      },
    },
    xAxis: categoryAxis(xLabels, '', xLabels.length > 8 ? 28 : 14),
    yAxis: categoryAxis(yLabels),
    visualMap: {
      min: visualMin,
      max: visualMax,
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: 12,
      inRange: { color: visualColors },
      textStyle: { color: axisColor },
    },
    series: [{
      type: 'heatmap',
      data: values.map((item) => {
        const value = nullableNumber(item?.[2])
        return value === null
          ? { value: [item?.[0], item?.[1], null], itemStyle: { color: missingColor }, missing: true }
          : [item?.[0], item?.[1], value]
      }),
      itemStyle: { borderColor: 'rgba(255,255,255,0.82)', borderWidth: 1 },
      label: {
        show: opts.showLabel === true,
        formatter: (params) => {
          const v = Number(params.value?.[2])
          if (!Number.isFinite(v)) return ''
          if (Number.isInteger(v)) return String(v)
          return v.toFixed(2)
        },
        color: '#0f2a44',
      },
    }],
  })
}

function buildRadarExtents(rows, metricKeys, mode) {
  const extents = {}
  metricKeys.forEach((key) => {
    const vals = metricValues(rows, key)
    extents[key] = stableExtent(vals, { includeZero: false })
  })
  if (rows.length === 1 && mode === 'normalize') {
    metricKeys.forEach((key) => {
      const value = finiteNumber(rows[0]?.[key])
      const anchor = Math.abs(value) || 1
      extents[key] = { min: value - anchor * 0.35, max: value + anchor * 0.35, span: anchor * 0.7 }
    })
  }
  return extents
}

export function radarOption(rows = [], options = {}) {
  const {
    mode = rows.length > 1 ? 'normalize' : 'raw',
    exclusions = ['species_id', 'display_name'],
    labelMax = 15,
    allowRawSingle = false,
    metrics = null,
    metricKeys: explicitMetricKeys = null,
    maxMetrics = 6,
  } = options
  const allMetricKeys = explicitMetricKeys || metrics || toMetricKeys(rows, exclusions)
  const metricKeys = allMetricKeys
    .filter((key) => rows.some((row) => Number.isFinite(Number(row?.[key]))))
    .slice(0, maxMetrics)
  const invalidRawSingle = rows.length <= 1 && mode === 'raw' && !allowRawSingle
  const tooManyMetrics = allMetricKeys.length > maxMetrics && mode !== 'normalize'
  const tooFewMetrics = metricKeys.length < 3
  if (invalidRawSingle || tooManyMetrics || tooFewMetrics) {
    return chartBase({
      __scientificEmptyReason: invalidRawSingle
        ? 'Single-row mixed-unit raw radar is disabled. Show raw values as metric cards or provide a reference cohort for percentile/robust-z profiling.'
        : (tooFewMetrics ? 'Radar requires at least three finite standardized metrics.' : 'Radar is disabled because more than 6 non-standardized metrics would be unreadable.'),
      graphic: [{
        type: 'text',
        left: 24,
        top: 36,
        right: 24,
        style: {
          text: invalidRawSingle
            ? 'Raw mixed-unit radar disabled. Use reference percentile or raw metric cards.'
            : (tooFewMetrics ? 'Radar hidden: fewer than three finite metrics.' : 'Too many metrics for radar. Use heatmap or parallel coordinates.'),
          fill: axisColor,
          fontSize: 14,
          lineHeight: 20,
          width: 420,
        },
      }],
      series: [],
    })
  }
  const extents = buildRadarExtents(rows, metricKeys, mode)
  const indicators = metricKeys.map((key) => {
    if (mode === 'normalize') {
      return { name: wrapLabel(shortMetricLabel(key), labelMax), min: 0, max: 1 }
    }
    const extent = extents[key] || { min: 0, max: 1 }
    return { name: wrapLabel(shortMetricLabel(key), labelMax), min: extent.min, max: extent.max }
  })

  const seriesData = rows.map((row, idx) => {
    const rawValues = metricKeys.map((key) => finiteNumber(row?.[key]))
    const chartValues = metricKeys.map((key, index) => {
      if (mode === 'normalize') return normalizeValue(rawValues[index], extents[key])
      return rawValues[index]
    })
    return {
      name: row.display_name || row.species_id || `row-${idx + 1}`,
      value: chartValues,
      rawValues,
      areaStyle: { color: softPalette[idx % softPalette.length] },
      lineStyle: { color: palette[idx % palette.length], width: 2.5 },
      symbol: 'circle',
      symbolSize: 6,
      itemStyle: { color: palette[idx % palette.length] },
    }
  })

  const legendHeight = rows.length > 4 ? 46 : 26
  const radius = rows.length > 4 ? '41%' : '46%'

  return chartBase({
    __exportName: options.exportName || 'fingerprint_radar',
    __semantic: {
      minPoints: Math.max(2, rows.length ? 1 : 2),
      totalCount: rows.length,
      displayedCount: rows.length,
      method: mode === 'normalize' ? 'per-metric normalized radar using selected reference cohort extents' : 'raw-unit radar with explicit guard',
      aggregation: 'species fingerprint',
    },
    __dataRows: rows.map((row) => {
      const out = { species_id: row.species_id, display_name: row.display_name }
      metricKeys.forEach((key) => { out[key] = row[key] })
      return out
    }),
    legend: {
      type: 'scroll',
      top: 0,
      left: 0,
      right: 0,
      pageIconColor: palette[0],
      pageIconInactiveColor: 'rgba(94,121,147,0.45)',
      pageTextStyle: { color: axisColor },
      textStyle: { color: axisColor },
    },
    tooltip: {
      ...chartBase().tooltip,
      formatter: (params) => {
        const row = seriesData.find((item) => item.name === params.name)
        const lines = [`<strong>${params.name}</strong>`]
        metricKeys.forEach((key, idx) => {
          const label = shortMetricLabel(key)
          const raw = row?.rawValues?.[idx]
          if (mode === 'normalize') {
            lines.push(`${label}: ${formatValue(raw)} <span style="color:#5e7993">(normalized ${formatValue(params.value[idx], 2)})</span>`)
          } else {
            lines.push(`${label}: ${formatValue(raw)}`)
          }
        })
        return lines.join('<br/>')
      },
    },
    radar: {
      indicator: indicators,
      center: ['50%', rows.length > 4 ? '61%' : '58%'],
      radius,
      splitNumber: 4,
      splitLine: { lineStyle: { color: 'rgba(42,89,140,0.09)' } },
      splitArea: { areaStyle: { color: ['rgba(47,119,200,0.015)', 'rgba(47,119,200,0.04)'] } },
      axisName: { color: axisColor, fontSize: 12 },
      axisLine: { lineStyle: { color: 'rgba(42,89,140,0.10)' } },
    },
    series: [{
      type: 'radar',
      top: legendHeight,
      data: seriesData,
    }],
  })
}

export function donutOption(rows = [], nameKey = 'name', valueKey = 'value') {
  const normalizedRows = (rows || [])
    .map((row) => ({
      ...row,
      [nameKey]: row?.[nameKey] ?? row?.label ?? row?.category ?? 'Unknown',
      [valueKey]: finiteNumber(row?.[valueKey] ?? row?.count ?? row?.n, 0),
    }))
    .filter((row) => Number(row[valueKey]) > 0)
  return chartBase({
    __exportName: 'donut_summary',
    __semantic: {
      minPoints: 1,
      totalCount: normalizedRows.length,
      displayedCount: normalizedRows.length,
      method: 'category count / composition summary',
      aggregation: 'donut chart',
    },
    __dataRows: normalizedRows,
    legend: { orient: 'vertical', right: 0, top: 'center', textStyle: { color: axisColor } },
    series: [{
      type: 'pie',
      radius: ['46%', '72%'],
      center: ['34%', '52%'],
      itemStyle: { borderRadius: 10, borderColor: '#ffffff', borderWidth: 2 },
      label: { color: textColor, formatter: '{b}\n{d}%' },
      color: palette,
      data: normalizedRows.map((row) => ({ name: row[nameKey], value: row[valueKey], raw: row })),
    }],
  })
}

export function treemapOption(rows = [], nameKey = 'name', valueKey = 'value') {
  return chartBase({
    tooltip: {
      ...chartBase().tooltip,
      formatter: (params) => `${params.name}<br/>${formatValue(params.value)}`,
    },
    series: [{
      type: 'treemap',
      roam: false,
      breadcrumb: { show: false },
      itemStyle: { borderColor: '#ffffff', borderWidth: 2, gapWidth: 2 },
      upperLabel: { show: false },
      label: { color: '#ffffff', formatter: '{b}', overflow: 'truncate' },
      levels: [{ color: palette }],
      data: rows.map((row, idx) => ({ name: row[nameKey], value: finiteNumber(row[valueKey]), itemStyle: { color: palette[idx % palette.length] } })),
    }],
  })
}

export function networkOption(edges = []) {
  const nodesMap = new Map()
  edges.forEach((edge) => {
    const score = Math.min(1, Math.abs(finiteNumber(edge.weight)))
    nodesMap.set(edge.source, Math.max(score, nodesMap.get(edge.source) || 0))
    nodesMap.set(edge.target, Math.max(score, nodesMap.get(edge.target) || 0))
  })
  const nodes = [...nodesMap.entries()].map(([name, score], idx) => ({
    name,
    value: score,
    symbolSize: 16 + score * 22,
    itemStyle: { color: palette[idx % palette.length] },
  }))
  return chartBase({
    tooltip: {
      ...chartBase().tooltip,
      formatter: (params) => {
        if (params.dataType === 'edge') return `${params.data.source} → ${params.data.target}<br/>weight: ${formatValue(params.data.value)}`
        return `${params.name}<br/>centrality proxy: ${formatValue(params.value)}`
      },
    },
    series: [{
      type: 'graph',
      layout: 'force',
      roam: true,
      force: { repulsion: 240, edgeLength: 128 },
      label: { show: true, color: textColor },
      lineStyle: {
        color: 'source',
        width: 2,
        curveness: 0.18,
        opacity: 0.55,
      },
      edgeSymbol: ['none', 'none'],
      data: nodes,
      links: edges.map((edge) => ({
        source: edge.source,
        target: edge.target,
        value: finiteNumber(edge.weight),
        lineStyle: { color: finiteNumber(edge.weight) >= 0 ? palette[0] : '#8da8c0', width: 1 + Math.min(1, Math.abs(finiteNumber(edge.weight))) * 3 },
      })),
    }],
  })
}

export function networkOptionSafe(edges = []) {
  const option = networkOption(edges)
  return {
    ...option,
    tooltip: {
      ...(option.tooltip || {}),
      formatter: (params) => {
        if (params.dataType === 'edge') {
          return `${params.data.source} -> ${params.data.target}<br/>weight: ${formatValue(params.data.value)}`
        }
        return `${params.name}<br/>centrality proxy: ${formatValue(params.value)}`
      },
    },
  }
}

export function parallelOption(rows = [], metrics = null, nameKey = 'cluster', options = {}) {
  const { mode = 'normalize' } = options
  const metricKeys = metrics || toMetricKeys(rows, [nameKey, 'count'])
  const extents = Object.fromEntries(metricKeys.map((key) => [key, stableExtent(metricValues(rows, key), { includeZero: false })]))

  const axes = metricKeys.map((key, idx) => ({
    dim: idx,
    name: wrapLabel(shortMetricLabel(key), 12),
    min: mode === 'normalize' ? 0 : extents[key].min,
    max: mode === 'normalize' ? 1 : extents[key].max,
  }))

  return chartBase({
    tooltip: {
      ...chartBase().tooltip,
      formatter: (params) => {
        const raw = params.data?.raw || {}
        const title = raw[nameKey] || raw.display_name || 'profile'
        const lines = [`<strong>${title}</strong>`]
        metricKeys.forEach((key) => lines.push(`${shortMetricLabel(key)}: ${formatValue(raw[key])}`))
        return lines.join('<br/>')
      },
    },
    parallelAxis: axes,
    parallel: {
      left: 56,
      right: 36,
      bottom: 48,
      top: 82,
      layout: 'horizontal',
      parallelAxisDefault: {
        nameTextStyle: { color: axisColor, fontSize: 12 },
        axisLabel: { color: axisColor },
        axisLine: { lineStyle: { color: 'rgba(42,89,140,0.14)' } },
        splitLine: { lineStyle: { color: splitColor } },
      },
    },
    series: rows.map((row, idx) => ({
      type: 'parallel',
      lineStyle: { width: 3, color: palette[idx % palette.length], opacity: 0.86 },
      emphasis: { lineStyle: { width: 4.5, opacity: 1 } },
      smooth: 0,
      clip: true,
      name: row[nameKey] || row.display_name || `row-${idx + 1}`,
      data: [{
        value: metricKeys.map((k) => {
          const raw = finiteNumber(row?.[k])
          return mode === 'normalize' ? normalizeValue(raw, extents[k]) : raw
        }),
        raw: row,
      }],
    })),
  })
}

export function rankLollipopOption(rows = [], categoryKey = 'name', valueKey = 'value', xName = '', opts = {}) {
  const categories = rows.map((r) => r[categoryKey])
  const values = rows.map((r) => finiteNumber(r[valueKey]))
  const extent = stableExtent(values, { includeZero: true })
  return chartBase({
    __exportName: opts.exportName || 'rank_lollipop',
    __semantic: {
      minPoints: opts.minPoints ?? 1,
      totalCount: opts.totalCount ?? rows.length,
      displayedCount: rows.length,
      method: opts.method || 'ranked top-N values; see table/download for full context',
      aggregation: opts.aggregation || 'ranked value',
    },
    __dataRows: rows.map((row, index) => ({ rank: index + 1, category: row[categoryKey], value: row[valueKey], ...row })),
    grid: { top: 34, right: 28, bottom: 40, left: 150, containLabel: true },
    tooltip: {
      ...chartBase().tooltip,
      formatter: (params) => `${categories[params.data[0]]}<br/>${xName || valueKey}: ${formatValue(params.data[1])}`,
    },
    xAxis: valueAxis(xName, { min: extent.min, max: extent.max }),
    yAxis: categoryAxis(categories),
    series: [
      {
        type: 'custom',
        clip: true,
        renderItem: (params, api) => {
          const y = api.coord([0, api.value(0)])[1]
          const start = api.coord([0, api.value(0)])
          const end = api.coord([api.value(1), api.value(0)])
          return {
            type: 'group',
            children: [
              { type: 'line', shape: { x1: start[0], y1: y, x2: end[0], y2: y }, style: { stroke: '#74a9de', lineWidth: 3 } },
              { type: 'circle', shape: { cx: end[0], cy: y, r: 6 }, style: { fill: palette[0] } },
            ],
          }
        },
        encode: { x: 1, y: 0 },
        data: categories.map((c, i) => [i, values[i]]),
      },
    ],
  })
}

export function ecdfOption(values = [], xName = 'Value', opts = {}) {
  const finite = values.map(nullableNumber).filter((value) => value !== null).sort((a, b) => a - b)
  const points = finite.map((value, index) => [value, (index + 1) / finite.length])
  const xExtent = stableExtent(finite, { includeZero: opts.includeZero === true })
  return chartBase({
    __exportName: opts.exportName || 'ecdf_distribution',
    __semantic: { minPoints: 3, totalCount: values.length, displayedCount: finite.length, method: opts.method || 'empirical cumulative distribution' },
    grid: baseGrid,
    xAxis: valueAxis(xName, { min: xExtent.min, max: xExtent.max }),
    yAxis: valueAxis('Cumulative fraction', { min: 0, max: 1, __axis: 'y' }),
    series: [{
      type: 'line',
      step: 'end',
      showSymbol: false,
      data: points,
      lineStyle: { color: '#1f5d9a', width: 2.4 },
    }],
  })
}

export function rangeOrBoxOption(rows = [], categoryKey = 'name', opts = {}) {
  const categories = rows.map((row) => row[categoryKey] || row.name || row.feature || '')
  const ranges = rows.map((row) => {
    const low = nullableNumber(row.low ?? row.p25 ?? row.q25 ?? row.ci_low)
    const medianValue = nullableNumber(row.median ?? row.p50 ?? row.value ?? row.mean)
    const high = nullableNumber(row.high ?? row.p75 ?? row.q75 ?? row.ci_high)
    return [low, medianValue, high]
  })
  const all = ranges.flat().filter((value) => value !== null)
  const extent = stableExtent(all, { includeZero: opts.includeZero === true })
  return chartBase({
    __exportName: opts.exportName || 'range_or_box',
    __semantic: { minPoints: 2, totalCount: rows.length, displayedCount: rows.length, method: opts.method || 'range plot: interval plus median/point estimate' },
    grid: { top: 42, right: 34, bottom: 46, left: 156, containLabel: true },
    tooltip: {
      ...chartBase().tooltip,
      formatter: (params) => {
        const row = rows[params.dataIndex] || {}
        const [low, med, high] = ranges[params.dataIndex] || []
        return [
          row[categoryKey] || row.name || row.feature || 'item',
          `low: ${low === null ? 'missing' : formatValue(low)}`,
          `median: ${med === null ? 'missing' : formatValue(med)}`,
          `high: ${high === null ? 'missing' : formatValue(high)}`,
          row.n !== undefined ? `n: ${row.n}` : '',
        ].filter(Boolean).join('<br/>')
      },
    },
    xAxis: valueAxis(opts.xName || 'Value', { min: extent.min, max: extent.max }),
    yAxis: categoryAxis(categories),
    series: [{
      type: 'custom',
      data: ranges.map((range, index) => [index, ...range]),
      renderItem: (params, api) => {
        const y = api.coord([extent.min, api.value(0)])[1]
        const low = api.value(1)
        const med = api.value(2)
        const high = api.value(3)
        if (!Number.isFinite(low) || !Number.isFinite(med) || !Number.isFinite(high)) return { type: 'group', children: [] }
        const lowPoint = api.coord([low, api.value(0)])
        const medPoint = api.coord([med, api.value(0)])
        const highPoint = api.coord([high, api.value(0)])
        return {
          type: 'group',
          children: [
            { type: 'line', shape: { x1: lowPoint[0], y1: y, x2: highPoint[0], y2: y }, style: { stroke: '#8ab9e6', lineWidth: 4 } },
            { type: 'circle', shape: { cx: medPoint[0], cy: y, r: 6 }, style: { fill: '#1f5d9a' } },
          ],
        }
      },
      encode: { x: [1, 2, 3], y: 0 },
    }],
  })
}

export function dumbbellOption(rows = [], categoryKey = 'name', startKey = 'start', endKey = 'end', opts = {}) {
  const categories = rows.map((row) => row[categoryKey] || row.name || '')
  const startValues = rows.map((row) => nullableNumber(row[startKey]))
  const endValues = rows.map((row) => nullableNumber(row[endKey]))
  const extent = stableExtent([...startValues, ...endValues].filter((value) => value !== null), { includeZero: opts.includeZero === true })
  return chartBase({
    __exportName: opts.exportName || 'paired_dumbbell',
    __semantic: { minPoints: 2, totalCount: rows.length, displayedCount: rows.length, method: opts.method || 'paired dumbbell comparison' },
    grid: { top: 42, right: 34, bottom: 46, left: 156, containLabel: true },
    tooltip: {
      ...chartBase().tooltip,
      formatter: (params) => {
        const row = rows[params.dataIndex] || {}
        return [
          row[categoryKey] || row.name || 'item',
          `${opts.startLabel || startKey}: ${formatValue(row[startKey])}`,
          `${opts.endLabel || endKey}: ${formatValue(row[endKey])}`,
          `delta: ${formatValue((nullableNumber(row[endKey]) ?? 0) - (nullableNumber(row[startKey]) ?? 0))}`,
        ].join('<br/>')
      },
    },
    xAxis: valueAxis(opts.xName || 'Value', { min: extent.min, max: extent.max }),
    yAxis: categoryAxis(categories),
    series: [{
      type: 'custom',
      data: rows.map((row, index) => [index, startValues[index], endValues[index]]),
      renderItem: (params, api) => {
        const y = api.coord([extent.min, api.value(0)])[1]
        const start = api.value(1)
        const end = api.value(2)
        if (!Number.isFinite(start) || !Number.isFinite(end)) return { type: 'group', children: [] }
        const p1 = api.coord([start, api.value(0)])
        const p2 = api.coord([end, api.value(0)])
        return {
          type: 'group',
          children: [
            { type: 'line', shape: { x1: p1[0], y1: y, x2: p2[0], y2: y }, style: { stroke: '#8ab9e6', lineWidth: 3 } },
            { type: 'circle', shape: { cx: p1[0], cy: y, r: 5 }, style: { fill: '#1f5d9a' } },
            { type: 'circle', shape: { cx: p2[0], cy: y, r: 5 }, style: { fill: '#e69f00' } },
          ],
        }
      },
      encode: { x: [1, 2], y: 0 },
    }],
  })
}

export function forestOption(rows = [], labelKey = 'feature', effectKey = 'effect', lowKey = 'ci_low', highKey = 'ci_high', opts = {}) {
  return rangeOrBoxOption(
    rows.map((row) => ({
      ...row,
      low: row[lowKey],
      median: row[effectKey],
      high: row[highKey],
    })),
    labelKey,
    { ...opts, xName: opts.xName || 'Effect size', includeZero: true, method: opts.method || 'forest plot with confidence interval' },
  )
}

export function densityScatterOption(points = [], xKey, yKey, xName = '', yName = '', opts = {}) {
  const option = buildEnhancedScatterOption(points, xKey, yKey, xName, yName, {
    ...opts,
    showTrend: opts.showTrend ?? false,
    showBinnedMedian: opts.showBinnedMedian ?? true,
  })
  const total = points.length
  option.__semantic = {
    minPoints: opts.minPoints ?? 3,
    totalCount: total,
    displayedCount: option.series?.[0]?.data?.length || 0,
    method: total > 2000 ? 'progressive density-aware scatter; backend aggregation recommended above 50k points' : 'scatter with binned median overlay',
  }
  if (option.series?.[0]) {
    option.series[0].large = total > 2000
    option.series[0].progressive = total > 2000 ? 3000 : 0
    option.series[0].symbolSize = total > 2000 ? 4 : option.series[0].symbolSize
  }
  return option
}

export function sankeyOption(links = []) {
  const names = new Set()
  links.forEach((link) => {
    names.add(link.source)
    names.add(link.target)
  })
  return chartBase({
    tooltip: {
      ...chartBase().tooltip,
      formatter: (params) => {
        if (params.dataType === 'edge') {
          const raw = params.data.raw_count ?? params.data.count
          const parts = [`${params.data.source} -> ${params.data.target}`, `value: ${formatValue(params.data.value)}`]
          if (raw !== undefined) parts.push(`count: ${raw}`)
          return parts.join('<br/>')
        }
        return params.name
      },
    },
    series: [{
      type: 'sankey',
      emphasis: { focus: 'adjacency' },
      nodeGap: 18,
      nodeWidth: 18,
      draggable: false,
      data: [...names].map((name, idx) => ({ name, itemStyle: { color: palette[idx % palette.length] } })),
      links: links.map((link) => ({ ...link, value: finiteNumber(link.value), lineStyle: { color: 'gradient', opacity: 0.45 } })),
      label: { color: textColor },
    }],
  })
}

const atlasDomainPalette = {
  Bacteria: '#2FBF9B',
  Fungi: '#F39A18',
  Metazoa: '#7C5CE5',
  Plants: '#54B96B',
  Protists: '#19B6C8',
  Vertebrates: '#3D7FE6',
  Unclassified: '#94A3B8',
}

function atlasDomainColor(domain = '') {
  return atlasDomainPalette[domain] || '#94A3B8'
}

export function genomeSizeBoxOption(rows = []) {
  const validRows = rows.filter((row) => Number(row?.n) > 0)
  const domains = rows.map((row) => row.domain)
  const allValues = validRows.flatMap((row) => [row.whisker_low, row.whisker_high, ...(row.outliers || [])].map((value) => Number(value)).filter((value) => Number.isFinite(value) && value > 0))
  const minValue = Math.max(0.0001, Math.min(...allValues, 0.0001))
  const maxValue = Math.max(...allValues, 1)
  return chartBase({
    __exportName: 'species_atlas_genome_size_boxplot',
    __semantic: {
      minPoints: 1,
    },
    __dataRows: validRows.map((row) => ({
      domain: row.domain,
      n: row.n,
      min: row.min,
      q1: row.q1,
      median: row.median,
      q3: row.q3,
      max: row.max,
      whisker_low: row.whisker_low,
      whisker_high: row.whisker_high,
      excluded_count: row.excluded_count,
    })),
    grid: { top: 32, right: 34, bottom: 54, left: 118, containLabel: true },
    tooltip: {
      ...chartBase().tooltip,
      formatter: (params) => {
        const row = params.data?.raw || params.data || {}
        if (params.seriesType === 'scatter') {
          return `${row.domain}<br/>Outlier: ${formatValue(row.value?.[0], 4)} Mb`
        }
        return [
          `<strong>${row.domain}</strong>`,
          `n: ${row.n}`,
          `Q1: ${formatValue(row.q1, 4)} Mb`,
          `Median: ${formatValue(row.median, 4)} Mb`,
          `Q3: ${formatValue(row.q3, 4)} Mb`,
          `Whisker: ${formatValue(row.whisker_low, 4)} to ${formatValue(row.whisker_high, 4)} Mb`,
          `Excluded <=0/missing: ${row.excluded_count || 0}`,
        ].join('<br/>')
      },
    },
    xAxis: {
      type: 'log',
      logBase: 10,
      min: minValue,
      max: maxValue,
      name: 'Genome size (Mb, log scale)',
      nameLocation: 'middle',
      nameGap: 36,
      axisLabel: { color: axisColor },
      splitLine: { lineStyle: { color: splitColor } },
    },
    yAxis: {
      type: 'category',
      data: domains,
      axisLabel: { color: textColor },
      axisLine: { lineStyle: { color: 'rgba(42,89,140,0.14)' } },
      axisTick: { show: false },
    },
    series: [
      {
        type: 'custom',
        name: 'Box Plot',
        data: validRows.map((row) => ({ value: [row.whisker_low, row.q1, row.median, row.q3, row.whisker_high, domains.indexOf(row.domain)], raw: row })),
        renderItem: (params, api) => {
          const row = validRows[params.dataIndex] || {}
          const category = api.value(5)
          const low = api.coord([api.value(0), category])
          const q1 = api.coord([api.value(1), category])
          const median = api.coord([api.value(2), category])
          const q3 = api.coord([api.value(3), category])
          const high = api.coord([api.value(4), category])
          const color = atlasDomainColor(row.domain)
          const boxHeight = 18
          const y = q1[1]
          return {
            type: 'group',
            children: [
              { type: 'line', shape: { x1: low[0], y1: y, x2: high[0], y2: y }, style: { stroke: color, lineWidth: 2, opacity: 0.85 } },
              { type: 'line', shape: { x1: low[0], y1: y - 5, x2: low[0], y2: y + 5 }, style: { stroke: color, lineWidth: 2 } },
              { type: 'line', shape: { x1: high[0], y1: y - 5, x2: high[0], y2: y + 5 }, style: { stroke: color, lineWidth: 2 } },
              { type: 'rect', shape: { x: q1[0], y: y - boxHeight / 2, width: Math.max(1, q3[0] - q1[0]), height: boxHeight }, style: { fill: `${color}22`, stroke: color, lineWidth: 1.6 } },
              { type: 'line', shape: { x1: median[0], y1: y - boxHeight / 2, x2: median[0], y2: y + boxHeight / 2 }, style: { stroke: color, lineWidth: 2.4 } },
            ],
          }
        },
      },
      {
        type: 'scatter',
        name: 'Outliers',
        symbolSize: 4,
        data: validRows.flatMap((row) => (row.outliers || []).map((value) => {
          const yIndex = domains.indexOf(row.domain)
          return { value: [value, yIndex], raw: { domain: row.domain, value: [value, yIndex] }, itemStyle: { color: atlasDomainColor(row.domain) } }
        })),
      },
    ],
  })
}

export function genomeSizeViolinOption(rows = []) {
  const validRows = rows.filter((row) => Number(row?.n) > 0 && (row.violin || []).length)
  const domains = rows.map((row) => row.domain)
  const allValues = validRows.flatMap((row) => (row.violin || []).map((point) => Number(point.x)).filter((value) => Number.isFinite(value) && value > 0))
  const minValue = Math.max(0.0001, Math.min(...allValues, 0.0001))
  const maxValue = Math.max(...allValues, 1)
  return chartBase({
    __exportName: 'species_atlas_genome_size_violin',
    __semantic: {
      minPoints: 1,
    },
    __dataRows: validRows.flatMap((row) => (row.violin || []).map((point) => ({ domain: row.domain, x: point.x, density: point.density, n: row.n, median: row.median }))),
    grid: { top: 32, right: 34, bottom: 54, left: 118, containLabel: true },
    tooltip: {
      ...chartBase().tooltip,
      formatter: (params) => {
        const row = params.data?.raw || {}
        return `${row.domain}<br/>Genome size: ${formatValue(row.x, 4)} Mb<br/>Relative density: ${formatValue(row.density, 3)}<br/>n: ${row.n}`
      },
    },
    xAxis: {
      type: 'log',
      logBase: 10,
      min: minValue,
      max: maxValue,
      name: 'Genome size (Mb, log scale)',
      nameLocation: 'middle',
      nameGap: 36,
      axisLabel: { color: axisColor },
      splitLine: { lineStyle: { color: splitColor } },
    },
    yAxis: {
      type: 'category',
      data: domains,
      axisLabel: { color: textColor },
      axisLine: { lineStyle: { color: 'rgba(42,89,140,0.14)' } },
      axisTick: { show: false },
    },
    series: [{
      type: 'custom',
      data: validRows.map((row) => ({ value: [domains.indexOf(row.domain)], raw: row })),
      renderItem: (params, api) => {
        const row = validRows[params.dataIndex] || {}
        const yIndex = api.value(0)
        const center = api.coord([row.median || row.violin?.[0]?.x || 1, yIndex])[1]
        const band = 16
        const top = []
        const bottom = []
        ;(row.violin || []).forEach((point) => {
          const x = api.coord([point.x, yIndex])[0]
          const delta = Number(point.density || 0) * band
          top.push([x, center - delta])
          bottom.unshift([x, center + delta])
        })
        return {
          type: 'polygon',
          shape: { points: [...top, ...bottom] },
          style: { fill: `${atlasDomainColor(row.domain)}25`, stroke: atlasDomainColor(row.domain), lineWidth: 1.4 },
        }
      },
    }],
  })
}

export function omicsAvailabilityOption(availability = {}, total = 0) {
  const rows = [
    { name: 'All 3 omics', value: Number(availability.all_3 || 0), color: '#48C9A5' },
    { name: '2 omics', value: Number(availability.two_omics || 0), color: '#3D8AF5' },
    { name: '1 omic', value: Number(availability.one_omics || 0), color: '#F59E0B' },
    { name: 'No omics', value: Number(availability.no_omics || 0), color: '#F04452' },
  ]
  return chartBase({
    __exportName: 'species_atlas_omics_availability',
    __semantic: { minPoints: 1 },
    __dataRows: rows.map((row) => ({ ...row, pct: total ? (row.value * 100 / total) : 0 })),
    tooltip: { ...chartBase().tooltip, formatter: (params) => `${params.name}<br/>${params.value.toLocaleString()} species (${params.percent}%)` },
      series: [{
        type: 'pie',
        radius: ['52%', '76%'],
        center: ['50%', '52%'],
        itemStyle: { borderColor: '#fff', borderWidth: 2, borderRadius: 6 },
        label: { show: false },
        data: rows.map((row) => ({ name: row.name, value: row.value, itemStyle: { color: row.color } })),
    }],
  })
}

export function coreCompletenessRingsOption(completeness = {}) {
  const rings = [
    { key: 'genome', label: 'Genome', center: ['18%', '48%'], color: '#48C9A5' },
    { key: 'transcriptome', label: 'Transcriptome', center: ['50%', '48%'], color: '#3D8AF5' },
    { key: 'proteome', label: 'Proteome', center: ['82%', '48%'], color: '#8B5CF6' },
  ]
  return chartBase({
    __exportName: 'species_atlas_core_feature_completeness',
    __semantic: { minPoints: 1 },
    __dataRows: rings.map((ring) => ({ omics: ring.key, ...(completeness[ring.key] || {}) })),
    tooltip: {
      ...chartBase().tooltip,
      formatter: (params) => {
        const row = params.data?.raw || {}
        return `${row.label}<br/>Completeness: ${formatValue(row.pct, 1)}%<br/>valid/applicable: ${Number(row.valid_cells || 0).toLocaleString()} / ${Number(row.applicable_cells || 0).toLocaleString()}<br/>datasets: ${Number(row.datasets || 0).toLocaleString()}`
      },
    },
    series: rings.map((ring) => {
      const row = completeness[ring.key] || {}
      const pct = Math.max(0, Math.min(100, Number(row.pct || 0)))
      return {
          type: 'pie',
          name: ring.label,
          radius: [36, 48],
          center: ring.center,
        silent: false,
        label: { show: false },
        itemStyle: { borderColor: '#fff', borderWidth: 2 },
        data: [
          { name: ring.label, value: pct, raw: { ...row, label: ring.label }, itemStyle: { color: ring.color } },
          { name: 'missing', value: Math.max(0, 100 - pct), raw: { ...row, label: ring.label }, itemStyle: { color: 'rgba(143, 166, 189, 0.18)' }, tooltip: { show: false } },
        ],
      }
    }),
  })
}
