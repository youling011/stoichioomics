// Requires the dedicated read-only verification backend; never migrates a database.
import {test,expect} from '@playwright/test'
import {readFileSync,writeFileSync} from 'node:fs'
import {createHash} from 'node:crypto'
const species=readFileSync(new URL('../tests/proteome/fixtures/acceptance_species.txt',import.meta.url),'utf8').trim().split(/\s+/)
const yeast='saccharomyces_cerevisiae',errors=new WeakMap()
const api=(sid,suffix='')=>`/api/stoichdb/species/${encodeURIComponent(sid)}/proteome/visualizations/${suffix}`
async function json(request,url){const response=await request.get(url,{timeout:120000});expect(response.status(),url).toBe(200);return (await response.json()).data}
async function opened(page,sid,tab='basic',scope='core'){
  await page.goto(`/species/${sid}?panel=proteome&tab=${tab}&scope=${scope}`,{waitUntil:'domcontentloaded',timeout:120000})
  const root=page.getByTestId('proteome-v3');await expect(root).toHaveAttribute('data-species-id',sid);await expect(root).toHaveAttribute('data-scope',scope)
  await page.waitForFunction(()=>{const f=[...document.querySelectorAll('[data-testid="proteome-v3"] [data-testid="proteome-figure"]')];return f.length>=13&&f.every(e=>e.dataset.status!=='loading')},null,{timeout:180000})
  if(tab==='analysis')await expect(root.locator('[data-chart-id="D16"]')).toBeVisible()
  await expect(root.locator('[data-status="failed"]')).toHaveCount(0)
  return root
}
test.beforeEach(async({page})=>{errors.set(page,[]);page.on('pageerror',e=>errors.get(page).push(e.message));page.on('response',r=>{if(r.url().includes('/api/')&&r.status()>=500)errors.get(page).push(`${r.status()} ${r.url()}`)})})
test.afterEach(async({page},info)=>{await info.attach('browser-errors',{body:JSON.stringify(errors.get(page)),contentType:'application/json'});expect(errors.get(page)).toEqual([])})

for(const sid of species)for(const tab of ['basic','analysis'])test(`${sid} / ${tab}: every chart position and complete source population`,async({page,request},info)=>{
  const m=await json(request,api(sid));expect(m.readiness).toBe('ready');const root=await opened(page,sid,tab)
  const expected=tab==='basic'?Array.from({length:15},(_,i)=>`B${String(i+1).padStart(2,'0')}`):Array.from({length:16},(_,i)=>`D${String(i+1).padStart(2,'0')}`)
  const actual=await root.locator('[data-chart-id]').evaluateAll(nodes=>nodes.map(n=>({id:n.dataset.chartId,status:n.dataset.status,species:n.dataset.speciesId})))
  for(const id of expected)expect(actual.some(r=>r.id===id),id).toBeTruthy()
  for(const row of actual.filter(r=>r.species))expect(row.species).toBe(sid)
  await expect(root.locator('.proteome-viz-summary')).toContainText(m.n_source.toLocaleString('en'))
  await info.attach('chart-ledger',{body:JSON.stringify({species:sid,tab,source_hash:m.source_hash,n_source:m.n_source,positions:actual}),contentType:'application/json'})
  await root.locator(`[data-chart-id="${tab==='basic'?'B01':'D01'}"]`).first().screenshot({path:info.outputPath(`${sid}_${tab}.png`),animations:'disabled'})
})

test('Full entry uses the actual Full population and retains the Core return route',async({page,request})=>{
  const full=await json(request,api(yeast)+'?scope=full');expect(full.readiness).toBe('ready');const root=await opened(page,yeast,'basic','full');await expect(root.locator('.proteome-viz-summary')).toContainText(full.n_source.toLocaleString('en'))
  const core=await json(request,api(yeast));expect(core.source_hash).not.toBe(full.source_hash);await opened(page,yeast,'analysis','core')
})

test('The field atlas reaches every numeric descriptor and exports the complete quantile catalog',async({page,request},info)=>{
  test.setTimeout(600000);await opened(page,yeast);const m=await json(request,api(yeast)),atlas=page.getByTestId('proteome-field-atlas'),seen=new Set()
  for(let p=1;p<=Math.ceil(m.fields.length/6);p++){
    if(p>1){const response=page.waitForResponse(r=>r.url().includes('/visualizations/fields/'));await atlas.getByTestId('field-page').selectOption(String(p));await response}
    await expect(atlas.locator('.proteome-field-grid .chart-host').first()).toBeVisible();for(const key of await atlas.locator('[data-field]').evaluateAll(nodes=>nodes.map(n=>n.dataset.field)))seen.add(key)
  }
  expect([...seen].sort()).toEqual(m.fields.map(f=>f.key).sort());expect(seen.has('Se_atoms')).toBeTruthy();expect(seen.has('AA_other_pct')).toBeTruthy()
  for(const format of ['csv','tsv']){const response=await request.get(await atlas.getByRole('link',{name:`Download all field quantiles (${format.toUpperCase()})`}).getAttribute('href'));expect(response.status()).toBe(200);const text=await response.text();expect(text.trim().split(/\r?\n/).length-1).toBe(m.fields.length);writeFileSync(info.outputPath(`all_quantiles.${format}`),text)}
  await atlas.screenshot({path:info.outputPath('last_field_page.png')})
})

test('Ten actual X/Y changes preserve every valid pair and bind exports to the displayed variant',async({page,request},info)=>{
  test.setTimeout(480000);await opened(page,yeast);const pairs=[['gravy','pI'],['Se_atoms','Se_atoms'],['N_S_ratio','S_atoms_per_aa'],['length_aa','mw_da'],['AA_other_pct','AA_A_pct'],['net_charge_pH7','gravy'],['avg_oxidation_state_C','pI'],['N_atoms_per_aa','S_atoms_per_aa'],['pI','pI'],['H_C_ratio','O_C_ratio']],ledger=[]
  for(const [x,y] of pairs){await page.getByTestId('pair-x').selectOption(x);await page.getByTestId('pair-y').selectOption(y);const response=page.waitForResponse(r=>r.url().includes('/visualizations/pair/'));await page.getByRole('button',{name:'Update relationship',exact:true}).click();const body=(await (await response).json()).data.result;expect(body.data.x).toBe(x);expect(body.data.y).toBe(y);expect(body.data.hex.bins.reduce((s,b)=>s+b.count,0)).toBe(body.coverage.n_valid);const figure=page.locator('[data-chart-id="B15"]').first();await expect(figure).toHaveAttribute('data-status',body.status);const href=await figure.getByRole('link',{name:'Methods & provenance'}).getAttribute('href');expect(href).toContain(body.variant_id);const exported=await request.get(href);expect((await exported.json()).figure.variant_id).toBe(body.variant_id);ledger.push({x,y,n_valid:body.coverage.n_valid,variant_id:body.variant_id})}
  await info.attach('pair-ledger',{body:JSON.stringify(ledger),contentType:'application/json'})
})

test('Structure windows include ranks after 5000 and exact last-record identifiers',async({page,request},info)=>{
  await opened(page,yeast,'analysis');const control=page.getByTestId('proteome-structure-window');await control.getByLabel('First sorted rank').fill('6501');const response=page.waitForResponse(r=>r.url().includes('/visualizations/structure/')&&r.url().includes('resolution=window'));await control.getByRole('button',{name:'Open precise window',exact:true}).click();const body=(await (await response).json()).data;expect(body.rank_start).toBe(6500);expect(body.rows.length).toBe(100);expect(body.rows[99].rank).toBe(6599);await expect(control.locator('.chart-host')).toBeVisible();await control.screenshot({path:info.outputPath('structure_last100.png')});const m=await json(request,api(yeast));expect(body.n_source).toBe(m.n_source)
})

test('Twenty rapid species route changes discard stale responses',async({page})=>{
  test.setTimeout(480000);await opened(page,yeast)
  for(let i=0;i<20;i++)await page.evaluate(({id,i})=>document.querySelector('#app').__vue_app__.config.globalProperties.$router.push({path:`/species/${id}`,query:{panel:'proteome',tab:i%2?'analysis':'basic'}}),{id:species[i%species.length],i})
  const last=species[19%species.length];await expect(page.getByTestId('proteome-v3')).toHaveAttribute('data-species-id',last);await page.waitForFunction(id=>[...document.querySelectorAll('[data-testid="proteome-v3"] [data-testid="proteome-figure"]')].length>=13&&[...document.querySelectorAll('[data-testid="proteome-v3"] [data-testid="proteome-figure"]')].every(e=>e.dataset.speciesId===id&&e.dataset.status!=='loading'),last,{timeout:180000})
})

test('Cohort selection changes update all three shared matrices and native summaries',async({page},info)=>{
  test.setTimeout(600000);await opened(page,yeast,'analysis');const c=page.getByTestId('proteome-cohort'),hashes=[]
  for(let i=0;i<10;i++){
    await c.locator('.proteome-cohort-list button').last().click();const changed=page.waitForResponse(r=>r.url().includes('/visualizations/cohort/')&&r.url().includes('species_ids='));await c.getByRole('button',{name:'Compare selected species'}).click();const r=(await (await changed).json()).data;hashes.push(r.cohort_hash);await expect(c.getByRole('button',{name:'Compare selected species'})).toBeEnabled()
    const restored=page.waitForResponse(r=>r.url().includes('/visualizations/cohort/')&&!r.url().includes('species_ids=')&&!r.url().includes('search='));await c.getByRole('button',{name:'Use representative cohort'}).click();const s=(await (await restored).json()).data;hashes.push(s.cohort_hash);expect(s.species_ids.length).toBe(r.species_ids.length+1);expect(s.cohort_hash).not.toBe(r.cohort_hash);await expect(c.getByRole('button',{name:'Compare selected species'})).toBeEnabled()
  }
  await info.attach('twenty-cohort-hashes',{body:JSON.stringify(hashes),contentType:'application/json'});await expect(c.getByText('Observed feature dispersion in original units')).toBeVisible()
})

for(const width of [390,768,1280,1440])test(`Responsive layout at ${width}px keeps plots, controls and long IDs within their containers`,async({page},info)=>{
  await page.setViewportSize({width,height:1000});for(const tab of ['basic','analysis']){const root=await opened(page,yeast,tab);await root.scrollIntoViewIfNeeded();const widths=await root.evaluate(el=>({client:el.clientWidth,scroll:el.scrollWidth,body:document.body.scrollWidth,viewport:innerWidth}));expect(widths.scroll).toBeLessThanOrEqual(widths.client+2);expect(widths.body).toBeLessThanOrEqual(widths.viewport+2);expect(await page.evaluate(()=>matchMedia('(prefers-reduced-motion: reduce)').matches)).toBeTruthy();await root.locator(`[data-chart-id="${tab==='basic'?'B01':'D01'}"]`).first().screenshot({path:info.outputPath(`${width}_${tab}.png`)})}
})

test('PNG and SVG downloads render every available independent chart',async({page},info)=>{
  test.setTimeout(900000);const exports=[]
  for(const tab of ['basic','analysis']){const root=await opened(page,yeast,tab),figures=root.locator('[data-testid="proteome-figure"]');for(let i=0;i<await figures.count();i++){const figure=figures.nth(i),id=await figure.getAttribute('data-chart-id');if(await figure.getByRole('button',{name:'SVG',exact:true}).count()===0)continue;await figure.scrollIntoViewIfNeeded();for(const type of ['SVG','PNG 4x']){const waiting=page.waitForEvent('download');await figure.getByRole('button',{name:type,exact:true}).click();const download=await waiting,path=info.outputPath(`${id}.${type==='SVG'?'svg':'png'}`);await download.saveAs(path);const bytes=readFileSync(path);expect(bytes.length).toBeGreaterThan(1000);if(type==='SVG'){expect(bytes.toString()).toContain('<svg');expect(bytes.toString()).not.toMatch(/\b(?:NaN|Infinity)\b/)}else expect(bytes.subarray(1,4).toString()).toBe('PNG');exports.push({id,type,bytes:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex')})}}}
  expect(new Set(exports.map(r=>r.id)).size).toBeGreaterThanOrEqual(28);await info.attach('export-hashes',{body:JSON.stringify(exports),contentType:'application/json'})
})

for(const panel of ['overview','cross','genome','transcriptome'])test(`Related Species module ${panel} retains a working page`,async({page})=>{await page.goto(`/species/${yeast}?panel=${panel}`,{waitUntil:'domcontentloaded'});await expect(page.getByRole('heading',{name:'Species Explorer',exact:true})).toBeVisible();await expect(page.locator('body')).toContainText('Saccharomyces');await expect(page.getByTestId('proteome-v3')).toHaveCount(0)})
test('Compare retains its independent interface',async({page})=>{await page.goto('/compare',{waitUntil:'domcontentloaded'});await expect(page.locator('body')).toContainText('Compare');await expect(page.getByTestId('proteome-v3')).toHaveCount(0)})

test('A non-precomputed registered species calculates on first visit and reuses its completed version',async({page,request},info)=>{
  test.setTimeout(600000);const candidates=(await json(request,api(yeast,'cohort/?search=xanthomonas'))).matches;expect(candidates.length).toBeGreaterThan(0);let chosen
  for(const s of candidates){const m=await json(request,api(s.species_id));if(m.readiness==='not_prepared'){chosen=s;break}}
  expect(chosen,'need an unprepared real dataset for first-visit acceptance').toBeTruthy();await page.goto(`/species/${chosen.species_id}?panel=proteome`,{waitUntil:'domcontentloaded'});await expect(page.getByTestId('proteome-preparation')).toHaveAttribute('data-status',/queued|running/,{timeout:180000});await page.waitForFunction(()=>document.querySelector('[data-chart-id="B01"]')?.dataset.status==='available',null,{timeout:300000});const m=await json(request,api(chosen.species_id));expect(m.readiness).toBe('ready');expect(m.n_source).toBeGreaterThan(0);await opened(page,chosen.species_id);const again=await json(request,api(chosen.species_id));expect(again.artifact_version).toBe(m.artifact_version);await info.attach('on-demand-result',{body:JSON.stringify(m),contentType:'application/json'})
})

