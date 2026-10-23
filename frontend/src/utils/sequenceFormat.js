export {number,escape,palette} from './proteomeFormat.js'
export function label(key){return String(key||'').replaceAll('_',' ').replace('delta gc pp','Promoter − exon GC (pp)').replace('gene span bp','Gene span (bp)').replace('coding coverage raw','ORF / ACGU span').replace('derived gc3 fraction','GC3 fraction').replace('derived codon entropy bits','Codon entropy (bits)')}
