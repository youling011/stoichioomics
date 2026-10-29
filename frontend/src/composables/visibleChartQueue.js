import {nextTick} from 'vue'

// Preserve every chart and its original position; fetch when its existing card
// approaches the viewport. Full exports remain independent of this scheduler.
export async function visibleChartQueue(ids, load, signal, workspace) {
  await nextTick()
  if (signal.aborted) return
  const queued = new Set(), pending = []
  let active = 0
  const run = () => {
    while (!signal.aborted && active < 2 && pending.length) {
      const id = pending.shift(); active++
      Promise.resolve().then(() => load(id)).finally(() => { active--; run() })
    }
  }
  const enqueue = id => { if (!queued.has(id)) { queued.add(id); pending.push(id); run() } }
  ids.slice(0, 2).forEach(enqueue)
  if (typeof IntersectionObserver === 'undefined') { ids.forEach(enqueue); return }
  const observer = new IntersectionObserver(entries => {
    for (const entry of entries) if (entry.isIntersecting) {
      enqueue(entry.target.dataset.chartId); observer.unobserve(entry.target)
    }
  }, {rootMargin: '300px'})
  const root = document.querySelector(workspace)
  for (const id of ids) {
    const node = root?.querySelector(`[data-chart-id="${CSS.escape(id)}"]`)
    if (node) observer.observe(node)
    else enqueue(id)
  }
  signal.addEventListener('abort', () => observer.disconnect(), {once: true})
}
