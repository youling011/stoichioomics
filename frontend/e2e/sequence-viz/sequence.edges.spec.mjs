import {createRequire} from 'node:module'
const require=createRequire(new URL('../../package.json',import.meta.url)),{test,expect}=require('@playwright/test')
const sid='arabidopsis_thaliana',base=`/api/stoichdb/species/${sid}/genome/visualizations/`
test('Full Genome coding PCA uses eligible Full rows and retains Full provenance',async({page,request})=>{
 const manifest=(await(await request.get(base+'?scope=full')).json()).data;expect(manifest.readiness).toBe('ready');const result=(await(await request.get(base+'charts/GD11/?scope=full&artifact_version='+manifest.artifact_version)).json()).data.result;expect(result.status).toBe('available');expect(result.coverage.n_fit).toBe(27628)
 await page.goto(`/species/${sid}?panel=genome&tab=analysis&scope=full`);const plot=page.locator('[data-chart-id="GD11"]').first();await expect(plot).toHaveAttribute('data-status','available');await expect(plot).toContainText('27628 fitted')
})
test('Cohort export follows changed selection; zero, one and two species stay explicit',async({page,request})=>{
 await page.goto(`/species/${sid}?panel=genome&tab=analysis&scope=core`);const cohort=page.getByTestId('sequence-cohort');await expect(cohort).toContainText('Included 8 of 8')
 const selected=()=>cohort.locator('.sequence-viz-controls').nth(1).getByRole('button')
 while(await selected().count()>2)await selected().last().click()
 await cohort.getByRole('button',{name:'Update cohort',exact:true}).click();await expect(cohort).toContainText('Included 2 of 2');let href=await cohort.getByRole('link',{name:'Cohort inputs / distance / linkage JSON'}).getAttribute('href');let exported=(await(await request.get(href)).json());expect(exported.species).toHaveLength(2);expect(exported.distance).toHaveLength(2);expect(exported.pca.status).toBe('unavailable')
 await selected().last().click();await cohort.getByRole('button',{name:'Update cohort',exact:true}).click();await expect(cohort).toContainText('Included 1 of 1');await selected().last().click();await cohort.getByRole('button',{name:'Update cohort',exact:true}).click();await expect(cohort).toContainText('Included 0 of 0');href=await cohort.getByRole('link',{name:'Cohort inputs / distance / linkage JSON'}).getAttribute('href');exported=(await(await request.get(href)).json());expect(exported.selected_species).toEqual([]);expect(exported.species).toEqual([])
})
test('Missing Full remains unavailable without substituting Core',async({request})=>{
 const id='buchnera_aphidicola_str_bp_baizongia_pistaciae_gca_000007725';for(const m of ['genome','transcriptome']){const p=`/api/stoichdb/species/${id}/${m}/visualizations/`;const c=(await(await request.get(p)).json()).data,f=(await(await request.get(p+'?scope=full')).json()).data;expect(c.readiness).toBe('ready');expect(c.n_source).toBeGreaterThan(500);expect(f.readiness).toBe('unavailable');expect(f.available_scopes).toEqual(['core'])}
})
test('200 percent CSS zoom preserves access to both deep-analysis modules',async({page})=>{
 await page.setViewportSize({width:1440,height:1000});for(const m of ['genome','transcriptome']){await page.goto(`/species/${sid}?panel=${m}&tab=analysis`);await expect(page.getByTestId('sequence-cohort')).toBeVisible();await page.evaluate(()=>document.documentElement.style.zoom='2');await page.getByTestId('sequence-candidates').scrollIntoViewIfNeeded();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2)).toBeTruthy();await page.evaluate(()=>document.documentElement.style.zoom='1')}
})
