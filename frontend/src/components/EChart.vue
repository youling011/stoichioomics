<template>
  <div class="echart-shell">
    <ModuleState
      v-if="isLoading"
      state="loading"
      title="Loading chart data"
      :message="loadingMessage"
    />
    <ModuleState
      v-else-if="error"
      state="error"
      title="Chart unavailable"
      :message="error"
    />
    <ModuleState
      v-else-if="isEmpty"
      state="missing"
      title="Chart unavailable"
      :message="resolvedEmptyReason"
      suggestion="Check field coverage, filters, sample size, or the supporting table for available rows."
    />
    <template v-else>
      <div v-if="showExports" class="chart-export-row">
        <button class="chart-export-btn" type="button" @click="download('png')">PNG 4x</button>
        <button class="chart-export-btn" type="button" @click="download('svg')">SVG</button>
        <button v-if="downloadableRows.length" class="chart-export-btn" type="button" @click="downloadData('csv')">CSV</button>
        <button v-if="downloadableRows.length" class="chart-export-btn" type="button" @click="downloadData('tsv')">TSV</button>
      </div>
      <div ref="el" class="chart-host"></div>
      <div v-if="resolvedCaption || metaLine" class="chart-caption">
        <p v-if="resolvedCaption">{{ resolvedCaption }}</p>
        <p v-if="metaLine">{{ metaLine }}</p>
      </div>
    </template>
  </div>
</template>
<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { isRequestLoading } from '../api/client'
import ModuleState from './ModuleState.vue'

const props = defineProps({
  option: { type: Object, required: true },
  height: { type: Number, default: 360 },
  emptyReason: { type: String, default: '' },
  allowEmpty: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  autoLoading: { type: Boolean, default: true },
  loadingMessage: { type: String, default: 'The platform is retrieving the supporting payload.' },
  error: { type: String, default: '' },
  caption: { type: String, default: '' },
  method: { type: String, default: '' },
  n: { type: [Number, String], default: '' },
  totalCount: { type: [Number, String], default: '' },
  displayedCount: { type: [Number, String], default: '' },
  aggregation: { type: String, default: '' },
  release: { type: String, default: '' },
  evidenceLevel: { type: String, default: '' },
  exportName: { type: String, default: '' },
  dataRows: { type: Array, default: () => [] },
  showExports: { type: Boolean, default: true },
})
const emit = defineEmits(['chart-click'])
const el = ref(null)
let chart
let observer
let echartsPromise

function dataPointIsRenderable(point) {
  if (point === null || point === undefined || point === '') return false
  if (Array.isArray(point)) return point.some(dataPointIsRenderable)
  if (typeof point === 'object') {
    if (Array.isArray(point.value)) return point.value.some(dataPointIsRenderable)
    if ('value' in point) return dataPointIsRenderable(point.value)
    return Object.keys(point).length > 0
  }
  return Number.isFinite(Number(point)) || typeof point === 'string'
}

function collectRenderableDataPoints(option = {}) {
  const series = Array.isArray(option.series) ? option.series : (option.series ? [option.series] : [])
  const points = []
  series.forEach((item) => {
    const data = item?.data
    if (Array.isArray(data)) {
      data.forEach((point) => {
        if (dataPointIsRenderable(point)) points.push(point)
      })
    } else if (dataPointIsRenderable(data)) {
      points.push(data)
    }
  })
  return points
}

function uniqueRenderableCount(points = []) {
  return new Set(points.map((point) => JSON.stringify(point?.value ?? point))).size
}

const renderablePoints = computed(() => collectRenderableDataPoints(props.option || {}))
const semantic = computed(() => props.option?.__semantic || {})
const hasData = computed(() => {
  const points = renderablePoints.value
  if (!points.length) return false
  const minPoints = Number(semantic.value.minPoints || 1)
  if (points.length < minPoints) return false
  if (semantic.value.uniqueCount !== false && uniqueRenderableCount(points) < Number(semantic.value.minUnique || 1)) return false
  return true
})
const isLoading = computed(() => !hasData.value && (props.loading || (props.autoLoading && isRequestLoading.value)))
const isEmpty = computed(() => !props.allowEmpty && !hasData.value && !isLoading.value && !props.error)
const resolvedEmptyReason = computed(() =>
  props.emptyReason ||
  props.option?.__scientificEmptyReason ||
  semantic.value.emptyReason ||
  'The chart payload has no renderable data points under the current scientific guard.',
)
const resolvedCaption = computed(() => props.caption || props.option?.__caption || props.option?.__semantic?.caption || '')
const metaLine = computed(() => {
  const parts = []
  const n = props.n || semantic.value.n
  const total = props.totalCount || semantic.value.totalCount
  const displayed = props.displayedCount || semantic.value.displayedCount
  const method = props.method || semantic.value.method
  const aggregation = props.aggregation || semantic.value.aggregation
  const release = props.release || semantic.value.release
  const evidence = props.evidenceLevel || semantic.value.evidenceLevel
  if (n !== '' && n !== undefined && n !== null) parts.push(`n=${n}`)
  if (displayed !== '' && total !== '' && displayed !== undefined && total !== undefined) parts.push(`shown=${displayed}/${total}`)
  if (method) parts.push(`method=${method}`)
  if (aggregation) parts.push(`aggregation=${aggregation}`)
  if (release) parts.push(`release=${release}`)
  if (evidence) parts.push(`evidence=${evidence}`)
  return parts.join(' · ')
})
const downloadableRows = computed(() => {
  if (props.dataRows.length) return props.dataRows
  if (Array.isArray(props.option?.__dataRows)) return props.option.__dataRows
  const dataset = props.option?.dataset
  const source = Array.isArray(dataset?.source) ? dataset.source : null
  if (source?.length) {
    const [first, ...rest] = source
    if (Array.isArray(first)) {
      const headers = first.map((item, index) => String(item || `col_${index + 1}`))
      return rest.map((row) => Object.fromEntries(headers.map((header, index) => [header, row?.[index]])))
    }
    if (typeof first === 'object') return source
  }
  const rows = []
  const series = Array.isArray(props.option?.series) ? props.option.series : (props.option?.series ? [props.option.series] : [])
  series.forEach((item) => {
    const data = Array.isArray(item?.data) ? item.data : []
    data.forEach((point, index) => {
      const value = point?.value ?? point
      const row = { series: item.name || item.type || 'series', index, raw: point?.raw ? JSON.stringify(point.raw) : '' }
      if (Array.isArray(value)) value.forEach((entry, i) => { row[`value_${i + 1}`] = entry })
      else row.value = value
      rows.push(row)
    })
  })
  return rows
})

function loadEcharts() {
  if (!echartsPromise) {
    echartsPromise = import('echarts')
  }
  return echartsPromise
}

function formatAxisValue(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return String(value ?? '')
  if (Math.abs(n) < 0.005) return '0'
  if (Math.abs(n) >= 1000000) return n.toExponential(1)
  if (Math.abs(n) >= 1000) return n.toLocaleString(undefined, { maximumFractionDigits: 0 })
  const text = n.toFixed(2)
  return text.replace(/\.00$/, '').replace(/(\.\d)0$/, '$1')
}

function isNumericLike(value) {
  if (value === null || value === undefined || value === '') return false
  return Number.isFinite(Number(value))
}

function shortAxisLabel(value, max = 14) {
  if (isNumericLike(value)) return formatAxisValue(value)
  const text = String(value ?? '').replaceAll('_', ' ')
  if (text.length <= max) return text
  const words = text.split(/\s+/).filter(Boolean)
  if (words.length > 1) {
    const lines = []
    let current = ''
    for (const word of words) {
      const next = current ? `${current} ${word}` : word
      if (next.length > max && current) {
        lines.push(current)
        current = word
        if (lines.length >= 2) break
      } else {
        current = next
      }
    }
    if (current && lines.length < 2) lines.push(current)
    return lines.join('\n')
  }
  return `${text.slice(0, Math.max(6, max - 1))}...`
}

function normalizeGrid(grid, hasTitle = false) {
  const minTop = hasTitle ? 82 : 58
  const normalizeOne = (item = {}) => ({
    ...item,
    top: Math.max(Number.parseFloat(item.top ?? minTop) || minTop, minTop),
    right: Math.max(Number.parseFloat(item.right ?? 56) || 56, 56),
    bottom: Math.max(Number.parseFloat(item.bottom ?? 88) || 88, 88),
    left: Math.max(Number.parseFloat(item.left ?? 118) || 118, 118),
    containLabel: true,
  })
  if (Array.isArray(grid)) return grid.map(normalizeOne)
  return normalizeOne(grid || {})
}

function normalizeAxis(axis, orientation = 'x') {
  const normalizeOne = (item = {}) => {
    const type = item.type || (item.data ? 'category' : 'value')
    const axisLabel = item.axisLabel || {}
    const isValue = type === 'value' || !item.data
    const categoryData = Array.isArray(item.data) ? item.data : []
    const categoryIsNumeric = categoryData.length > 0 && categoryData.filter((value) => value !== null && value !== undefined && value !== '').every(isNumericLike)
    return {
      ...item,
      type,
      splitNumber: isValue ? (item.splitNumber ?? 5) : item.splitNumber,
      nameLocation: item.nameLocation ?? 'middle',
      nameGap: item.nameGap ?? (orientation === 'x' ? 46 : 82),
      nameTextStyle: {
        ...(item.nameTextStyle || {}),
        width: item.nameTextStyle?.width ?? (orientation === 'y' ? 150 : 150),
        overflow: item.nameTextStyle?.overflow ?? 'truncate',
        ellipsis: item.nameTextStyle?.ellipsis ?? '...',
      },
      axisLabel: {
        ...axisLabel,
        hideOverlap: true,
        interval: axisLabel.interval ?? 'auto',
        margin: axisLabel.margin ?? 10,
        width: axisLabel.width ?? (orientation === 'y' ? 96 : 86),
        overflow: axisLabel.overflow ?? 'truncate',
        formatter: isValue
          ? formatAxisValue
          : (value) => categoryIsNumeric ? formatAxisValue(value) : shortAxisLabel(value, axisLabel.rotate ? 9 : 14),
      },
    }
  }
  if (Array.isArray(axis)) return axis.map((item) => normalizeOne(item))
  if (axis) return normalizeOne(axis)
  return axis
}

function normalizeTitle(title) {
  const normalizeOne = (item = {}) => ({
    ...item,
    textStyle: {
      ...(item.textStyle || {}),
      width: item.textStyle?.width ?? 420,
      overflow: item.textStyle?.overflow ?? 'truncate',
      ellipsis: item.textStyle?.ellipsis ?? '...',
    },
    subtextStyle: {
      ...(item.subtextStyle || {}),
      width: item.subtextStyle?.width ?? 520,
      overflow: item.subtextStyle?.overflow ?? 'truncate',
      ellipsis: item.subtextStyle?.ellipsis ?? '...',
      lineHeight: item.subtextStyle?.lineHeight ?? 15,
    },
  })
  if (Array.isArray(title)) return title.map(normalizeOne)
  return title ? normalizeOne(title) : title
}

function normalizeSeries(series) {
  const normalizeOne = (item = {}) => {
    if (!item || typeof item !== 'object') return item
    const next = { ...item }
    if (next.markLine?.label) {
      next.markLine = {
        ...next.markLine,
        label: {
          ...next.markLine.label,
          formatter: (params) => params?.name || formatAxisValue(params?.value),
        },
      }
    }
    return next
  }
  if (Array.isArray(series)) return series.map(normalizeOne)
  return series ? normalizeOne(series) : series
}

function normalizeOption(option = {}) {
  const hasTitle = Boolean(option?.title)
  return {
    ...option,
    title: normalizeTitle(option.title),
    grid: normalizeGrid(option.grid, hasTitle),
    xAxis: normalizeAxis(option.xAxis, 'x'),
    yAxis: normalizeAxis(option.yAxis, 'y'),
    series: normalizeSeries(option.series),
  }
}

function renderChart(option) {
  if (!chart) return
  chart.clear()
  chart.setOption(normalizeOption(option || {}), { notMerge: true, lazyUpdate: false })
  nextTick(() => chart && chart.resize())
}

function slug(value = '') {
  return String(value || 'chart')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 96) || 'chart'
}

function exportFileName(type) {
  const titleText = Array.isArray(props.option?.title) ? props.option.title[0]?.text : props.option?.title?.text
  return `${slug(props.exportName || props.option?.__exportName || titleText || 'stoichioomics_chart')}.${type}`
}

async function download(type = 'png') {
  if (!chart) return
  try {
    let url
    if (type === 'svg') {
      const echarts = await loadEcharts()
      const temp = document.createElement('div')
      temp.style.position = 'fixed'
      temp.style.left = '-10000px'
      temp.style.top = '0'
      temp.style.width = `${el.value?.clientWidth || 900}px`
      temp.style.height = `${props.height}px`
      document.body.appendChild(temp)
      const svgChart = echarts.init(temp, null, { renderer: 'svg' })
      svgChart.setOption(normalizeOption(props.option || {}), { notMerge: true, lazyUpdate: false })
      url = svgChart.getDataURL({ type: 'svg', backgroundColor: '#ffffff' })
      svgChart.dispose()
      temp.remove()
    } else {
      url = chart.getDataURL({ type: 'png', pixelRatio: 4, backgroundColor: '#ffffff' })
    }
    const a = document.createElement('a')
    a.href = url
    a.download = exportFileName(type)
    a.click()
  } catch (error) {
    const url = chart.getDataURL({ type: 'png', pixelRatio: 4, backgroundColor: '#ffffff' })
    const a = document.createElement('a')
    a.href = url
    a.download = exportFileName('png')
    a.click()
  }
}

function serializeRows(rows = [], delimiter = ',') {
  if (!rows.length) return ''
  const columns = [...rows.reduce((set, row) => {
    Object.keys(row || {}).forEach((key) => set.add(key))
    return set
  }, new Set())]
  const escapeCell = (value) => {
    const text = value === null || value === undefined ? '' : String(value)
    if (delimiter === '\t') return text.replace(/\t/g, ' ').replace(/\r?\n/g, ' ')
    if (/[",\n]/.test(text)) return `"${text.replace(/"/g, '""')}"`
    return text
  }
  return [columns.join(delimiter), ...rows.map((row) => columns.map((column) => escapeCell(row?.[column])).join(delimiter))].join('\n')
}

function downloadData(type = 'csv') {
  const delimiter = type === 'tsv' ? '\t' : ','
  const text = serializeRows(downloadableRows.value, delimiter)
  const blob = new Blob([text], { type: type === 'tsv' ? 'text/tab-separated-values;charset=utf-8' : 'text/csv;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = exportFileName(type)
  a.click()
  URL.revokeObjectURL(a.href)
}

async function initChart() {
  await nextTick()
  if (isEmpty.value || isLoading.value || chart || !el.value) return
  el.value.style.height = `${props.height}px`
  const echarts = await loadEcharts()
  if (!el.value) return
  chart = echarts.init(el.value, null, { renderer: props.option?.__renderer || 'canvas' })
  chart.on('click', (params) => {
    emit('chart-click', params)
    const raw = params?.data?.raw || params?.data || {}
    if (raw && (raw.entity_id || raw.gene_id || raw.protein_id || raw.transcript_id)) {
      window.dispatchEvent(new CustomEvent('stoich-entity-chart-click', { detail: raw }))
    }
  })
  renderChart(props.option)
  observer = new ResizeObserver(() => chart && chart.resize())
  observer.observe(el.value)
}

onMounted(async () => {
  await initChart()
})

watch(() => props.height, (value) => {
  if (isEmpty.value) return
  if (el.value) el.value.style.height = `${value}px`
  nextTick(() => chart && chart.resize())
})

watch(() => props.option, (v) => {
  if (isEmpty.value) return
  renderChart(v)
}, { deep: true })

function disposeChart() {
  if (observer) observer.disconnect()
  if (chart) chart.dispose()
  observer = null
  chart = null
}

watch([isEmpty, isLoading], async ([empty, loading]) => {
  if (empty || loading) {
    disposeChart()
    return
  }
  await initChart()
})

onBeforeUnmount(() => {
  disposeChart()
})
</script>
<style scoped>
.echart-shell {
  position: relative;
}
.chart-export-row {
  position: absolute;
  z-index: 2;
  top: 8px;
  right: 8px;
  display: flex;
  gap: 6px;
}
.chart-export-btn {
  border: 1px solid rgba(42, 89, 140, 0.16);
  background: rgba(255,255,255,0.9);
  color: #1f5d9a;
  border-radius: 999px;
  padding: 4px 8px;
  font-size: 0.75rem;
}
</style>
