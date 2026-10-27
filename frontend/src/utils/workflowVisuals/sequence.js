import {buildPacketOptions} from './shared.js'
export const sequenceChartIds=Array.from({length:25},(_,i)=>'S'+String(i+1).padStart(2,'0'))
export function sequenceOptions(packet){if(!sequenceChartIds.includes(packet?.chart_id))throw new Error('Unknown sequence chart');return buildPacketOptions(packet)}
