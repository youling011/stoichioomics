export const palette = {blue:'#2867A1',teal:'#168579',gold:'#B17A22',purple:'#7765A2',ink:'#18334A',muted:'#526575',line:'#DCE4EA',missing:'#E3E8EC'}
export function number(value,digits=4){
  if(value===null||value===undefined||!Number.isFinite(Number(value)))return 'NA'
  const n=Number(value)
  if(n===0)return '0'
  if(Math.abs(n)<.001||Math.abs(n)>=1e7)return n.toExponential(2)
  return new Intl.NumberFormat('en',{maximumSignificantDigits:digits}).format(n)
}
export function label(field){
  if(/^AA_[A-Z]_pct$/.test(field))return field.split('_')[1]
  const names={length_aa:'Length (aa)',mw_da:'Molecular weight (Da)',gravy:'GRAVY',pI:'pI',avg_oxidation_state_C:'ZC',instability_index:'Instability index',aa_entropy_bits:'AA entropy (bits)',C_N_ratio:'C/N',N_S_ratio:'N/S',O_C_ratio:'O/C',H_C_ratio:'H/C',O_N_ratio:'O/N',disulfide_density:'SS upper bound / aa',surface_access_em_mean:'Accessibility proxy',net_charge_pH7:'Net charge at pH 7'}
  return names[field]||String(field).replace('_atoms_per_aa',' / aa').replace('_atoms',' atoms').replace(/^aa_/,'').replaceAll('_',' ')
}
export function escape(value){return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
export function signedColor(value,limit=3){
  if(value===null||!Number.isFinite(Number(value)))return palette.missing
  const t=Math.min(1,Math.abs(value)/limit),a=[250,250,250],b=value<0?[52,114,168]:[160,97,54]
  return `rgb(${a.map((n,i)=>Math.round(n+(b[i]-n)*t)).join(',')})`
}
