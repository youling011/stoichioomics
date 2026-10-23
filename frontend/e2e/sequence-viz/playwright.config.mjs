import {createRequire} from 'node:module'
const require=createRequire(new URL('../../package.json',import.meta.url))
const {defineConfig}=require('@playwright/test')
export default defineConfig({globalSetup:'./sequence.setup.mjs',testDir:'.',testIgnore:['**/stage/**'],testMatch:'sequence.*.spec.mjs',workers:1,fullyParallel:false,retries:0,timeout:300000,expect:{timeout:90000},outputDir:'./browser-results',reporter:[['list'],['json',{outputFile:'./browser_results.json'}]],use:{baseURL:'http://127.0.0.1:5177',viewport:{width:1440,height:1000},headless:true,reducedMotion:'reduce',launchOptions:{executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'},acceptDownloads:true,screenshot:'only-on-failure'}})
