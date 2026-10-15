export const OMICS_COLORS = {
  genome: '#0F9D8A',
  transcriptome: '#1769E0',
  proteome: '#7448C8',
}

const CLADE_COLORS = {
  vertebrates: '#18A8D8',
  plants: '#39B96C',
  fungi: '#E48A23',
  metazoa: '#1769E0',
  protists: '#7448C8',
  bacteria: '#D95467',
  unclassified: '#8A96A8',
}

const tooltip = {
  trigger: 'item',
  backgroundColor: '#ffffff',
  borderColor: '#D9E5F5',
  borderWidth: 1,
  textStyle: { color: '#0B2A5B', fontSize: 12 },
  extraCssText: 'box-shadow:0 8px 20px rgba(11,42,91,.12);border-radius:8px;',
}

function compact(value) {
  const n = Number(value || 0)
  if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`
  if (n >= 1000) return `${Math.round(n / 1000)}K`
  return String(n)
}

export function homeTreemapOption(rows = []) {
  const data = rows.map((row) => ({
    name: row.label,
    value: Number(row.species_count || 0),
    itemStyle: { color: row.color || CLADE_COLORS[row.key] || CLADE_COLORS.unclassified },
    raw: row,
  }))
  return {
    tooltip: {
      ...tooltip,
      formatter: (params) => {
        const raw = params.data?.raw || {}
        return `<strong>${raw.label || params.name}</strong><br/>Species: ${Number(raw.species_count || 0).toLocaleString()}<br/>Share: ${raw.percentage ?? 0}%`
      },
    },
    series: [{
      type: 'treemap',
      roam: false,
      nodeClick: false,
      breadcrumb: { show: false },
      label: {
        show: true,
        color: '#ffffff',
        fontWeight: 800,
        fontSize: 14,
        lineHeight: 19,
        formatter: (params) => {
          const raw = params.data?.raw || {}
          return `${raw.label || params.name}\n${compact(raw.species_count)}\n${raw.percentage ?? 0}%`
        },
      },
      upperLabel: { show: false },
      itemStyle: {
        borderColor: '#ffffff',
        borderWidth: 3,
        gapWidth: 3,
        borderRadius: 8,
      },
      levels: [{ itemStyle: { borderColor: '#ffffff', borderWidth: 3, gapWidth: 3 } }],
      data,
    }],
    __semantic: { minPoints: 1, emptyReason: 'No clade distribution rows were returned.' },
  }
}

export function homeOmicsCoverageOption(rows = []) {
  const labels = rows.map((row) => row.label)
  const makeSeries = (key, name) => ({
    name,
    type: 'bar',
    stack: 'omics',
    barWidth: 30,
    emphasis: { focus: 'series' },
    itemStyle: { color: OMICS_COLORS[key], borderRadius: key === 'proteome' ? [5, 5, 0, 0] : 0 },
    label: {
      show: false,
      color: '#ffffff',
      fontSize: 10,
      fontWeight: 700,
      formatter: (params) => Number(params.value || 0) > 0 ? compact(params.value) : '',
    },
    data: rows.map((row) => Number(row[key] || 0)),
  })
  return {
    color: Object.values(OMICS_COLORS),
    tooltip: {
      ...tooltip,
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
    },
    legend: {
      top: 0,
      right: 4,
      itemWidth: 9,
      itemHeight: 9,
      textStyle: { color: '#263752', fontSize: 11 },
    },
    grid: { top: 44, left: 54, right: 18, bottom: 54, containLabel: true },
    xAxis: {
      type: 'category',
      data: labels,
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#D7E2F1' } },
      axisLabel: { color: '#263752', rotate: 34, fontSize: 11 },
    },
    yAxis: {
      type: 'value',
      name: '# Species',
      splitLine: { lineStyle: { color: '#E8EEF7' } },
      axisLabel: { color: '#5C677D', formatter: compact },
    },
    series: [
      makeSeries('genome', 'Genome'),
      makeSeries('transcriptome', 'Transcriptome'),
      makeSeries('proteome', 'Proteome'),
    ],
    __semantic: { minPoints: 1, emptyReason: 'No omics coverage rows were returned.' },
  }
}

export function homeReadinessHeatmapOption(payload = {}) {
  const columns = payload.columns || []
  const rows = payload.rows || []
  const data = []
  rows.forEach((row, y) => {
    ;(row.values || []).forEach((value, x) => {
      if (value === null || value === undefined) return
      data.push([x, y, Number(value)])
    })
  })
  return {
    tooltip: {
      ...tooltip,
      formatter: (params) => {
        const [x, y, value] = params.value || []
        return `<strong>${rows[y]?.label || ''}</strong><br/>${columns[x] || ''}: ${Number(value).toFixed(1)}%`
      },
    },
    grid: { top: 28, left: 92, right: 28, bottom: 44, containLabel: true },
    xAxis: {
      type: 'category',
      data: columns,
      splitArea: { show: true },
      axisLabel: { color: '#263752', fontSize: 10, interval: 0 },
      axisLine: { lineStyle: { color: '#D7E2F1' } },
    },
    yAxis: {
      type: 'category',
      data: rows.map((row) => row.label),
      splitArea: { show: true },
      axisLabel: { color: '#263752', fontSize: 11 },
      axisLine: { lineStyle: { color: '#D7E2F1' } },
    },
    visualMap: {
      min: 0,
      max: 100,
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: 0,
      inRange: { color: ['#F4E4BA', '#7CC7A6', '#006B4F'] },
      textStyle: { color: '#5C677D', fontSize: 10 },
    },
    series: [{
      type: 'heatmap',
      data,
      label: {
        show: false,
        color: '#ffffff',
        fontSize: 10,
        formatter: (params) => Math.round(params.value?.[2] || 0),
      },
      itemStyle: { borderColor: '#ffffff', borderWidth: 1 },
    }],
    __semantic: {
      minPoints: 1,
      emptyReason: payload.method || 'No cached Feature Hub readiness profile is available. Cells are shown as N/A in the supporting panel.',
    },
  }
}
