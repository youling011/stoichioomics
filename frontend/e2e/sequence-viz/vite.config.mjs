import vue from '@vitejs/plugin-vue'
import {fileURLToPath} from 'node:url'
const root=fileURLToPath(new URL('../../',import.meta.url))
export default {root,plugins:[vue()],cacheDir:root+'/.cache/sequence-viz-acceptance',server:{host:'127.0.0.1',port:5177,strictPort:true,proxy:{'/api':{target:'http://127.0.0.1:8007',changeOrigin:true}}}}
