import {defineConfig} from '@playwright/test'
export default defineConfig({globalSetup:'./e2e/proteome.setup.mjs',testDir:'./e2e',testMatch:'proteome.*.spec.mjs',fullyParallel:false,workers:1,retries:0,timeout:240000,expect:{timeout:90000},outputDir:'test-results/proteome',reporter:[['list'],['json',{outputFile:process.env.PROTEOME_PLAYWRIGHT_REPORT||'test-results/proteome-report.json'}]],use:{baseURL:process.env.PROTEOME_FRONTEND_URL||'http://127.0.0.1:5177',viewport:{width:1440,height:1000},reducedMotion:'reduce',headless:true,launchOptions:{executablePath:process.env.PROTEOME_CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe'},trace:'retain-on-failure',screenshot:'only-on-failure',acceptDownloads:true}})


