"""Bounded Arrow string comparison, byte-exact CSV reconstruction, no source writes."""
import csv, hashlib, io, json, struct
from pathlib import Path
import pyarrow as pa
import pyarrow.csv as acsv
import pyarrow.compute as pc
from .projection import CoreRecipe, GENOME_ZERO_FIELDS
from .asset_state import change_token

class HashingFile(io.RawIOBase):
 def __init__(self,path):
  super().__init__();self.handle=Path(path).open('rb');self.hasher=hashlib.sha256()
 def readable(self):return True
 def readinto(self,buffer):
  n=self.handle.readinto(buffer)
  if n:self.hasher.update(memoryview(buffer)[:n])
  return n
 def close(self):
  if not self.closed:self.handle.close()
  super().close()

def stat_of(path):
 p=Path(path);s=p.stat()
 return {'size':s.st_size,'mtime_ns':s.st_mtime_ns,'mtime':s.st_mtime,'ino':s.st_ino,'resolved_path':str(p.resolve()),'change_token':change_token(p)}

def profile(path):
 with Path(path).open('rb') as f:
  prefix=f.read(65536)
  f.seek(max(0,f.seek(0,2)-8));tail=f.read()
 bom=prefix.startswith(b'\xef\xbb\xbf')
 text=prefix.decode('utf-8-sig')
 header=next(csv.reader(io.StringIO(text,newline='')))
 term='\r\n' if b'\r\n' in prefix.split(b'\n',1)[0]+b'\n' else '\n'
 quoting=csv.QUOTE_ALL if text.startswith('"') else csv.QUOTE_MINIMAL
 return header,{'line_terminator':term,'bom':bom,'quoting':quoting},tail.endswith(term.encode())

def reader(path,header):
 raw=HashingFile(path);buf=io.BufferedReader(raw,buffer_size=1024*1024)
 try:
  r=acsv.open_csv(buf,read_options=acsv.ReadOptions(block_size=4*1024*1024,use_threads=False),
     parse_options=acsv.ParseOptions(newlines_in_values=True),
     convert_options=acsv.ConvertOptions(column_types={k:pa.string() for k in header},strings_can_be_null=False,null_values=[]))
  return r,raw,buf
 except BaseException:buf.close();raise

def numeric(a):
 clean=pc.utf8_trim_whitespace(a)
 good=pc.match_substring_regex(clean,pattern=r'^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$')
 return pc.cast(pc.if_else(good,clean,pa.scalar('0')),pa.float64(),safe=False)

def project(batch,recipe):
 columns={name:batch.column(name) for name in recipe.columns if name!='coding_valid' or recipe.omics!='genome'}
 if recipe.omics=='genome' and ('coding_valid' in recipe.columns or (recipe.fill_noncoding=='zero' and set(recipe.columns)&set(GENOME_ZERO_FIELDS))):
  a,b,c=[numeric(batch.column(k)) for k in ['is_coding','codon_total_valid','aa_total_20']]
  valid=pc.and_(pc.and_(pc.equal(pc.trunc(a),1.0),pc.greater_equal(b,1.0)),pc.greater_equal(c,1.0))
  valid=pc.and_(valid,pc.and_(pc.is_finite(a),pc.and_(pc.is_finite(b),pc.is_finite(c))))
  if 'coding_valid' in recipe.columns:columns['coding_valid']=pc.if_else(valid,pa.scalar('1'),pa.scalar('0'))
  if recipe.fill_noncoding=='zero':
   for name in recipe.columns:
    if name in GENOME_ZERO_FIELDS:columns[name]=pc.if_else(valid,columns[name],pa.scalar('0'))
 return pa.record_batch([columns[name] for name in recipe.columns],names=list(recipe.columns))

def encoded_rows(batch,fmt):
 arrays=[]
 for a in batch.columns:
  needs=pc.match_substring_regex(a,pattern='[,"\r\n]')
  if fmt['quoting']==csv.QUOTE_MINIMAL and not pc.any(needs).as_py():
   arrays.append(a);continue
  escaped=pc.replace_substring(a,pattern='"',replacement='""')
  enclosed=pc.binary_join_element_wise(pa.scalar('"'),escaped,pa.scalar('"'),pa.scalar(''))
  arrays.append(enclosed if fmt['quoting']==csv.QUOTE_ALL else pc.if_else(needs,enclosed,a))
 rows=pc.binary_join_element_wise(*arrays,pa.scalar(','))
 return rows.to_pylist()

def verify(core,full,omics):
 before=[stat_of(p) for p in [core,full]]
 ch,fmt,final=profile(core);fh,_,_=profile(full)
 recipe=CoreRecipe(omics,tuple(ch));recipe.validate_full_header(fh)
 primary={'genome':'gene_id','transcriptome':'transcript_id','proteome':'protein_id'}[omics]
 if primary not in ch or primary not in fh:raise ValueError('Primary identifier missing')
 report={'core_path':str(core),'full_path':str(full),'omics':omics,'header':ch,'full_header':fh,'serialization':fmt,
 'core_stat':before[0],'full_stat':before[1],'rows':0,'full_rows':0,'cells':0,'different_cells':0,'id_mismatches':0,'duplicates':0,'empty_ids':0,'examples':[]}
 raw_objects=[];virtual=hashlib.sha256();logical=hashlib.sha256();virtual_size=0
 buf=io.StringIO(newline='');csv.writer(buf,lineterminator=fmt['line_terminator'],quoting=fmt['quoting']).writerow(ch)
 header=(b'\xef\xbb\xbf' if fmt['bom'] else b'')+buf.getvalue().encode('utf-8');virtual.update(header);virtual_size+=len(header)
 logical.update(struct.pack('>Q',len(header)));logical.update(header)
 core_ids=set();full_ids=set()
 try:
  cr,craw,cbuf=reader(core,ch);raw_objects.append(cbuf)
  fr,fraw,fbuf=reader(full,fh);raw_objects.append(fbuf)
  ca=fa=None;co=fo=0;done_c=done_f=False
  while True:
   if ca is None or co==ca.num_rows:
    try:ca=cr.read_next_batch();co=0
    except StopIteration:done_c=True;ca=None
   if fa is None or fo==fa.num_rows:
    try:fa=fr.read_next_batch();fo=0
    except StopIteration:done_f=True;fa=None
   if done_f and not done_c:raise ValueError('Core contains records not present in Full')
   if done_c:
    # Core may be the original shorter prefix; retain its exact population.
    if not done_f:
     while fa is not None:
      rest=fa.slice(fo)
      ids=rest.column(primary).to_pylist();unique=set(ids)
      report['duplicates']+=len(ids)-len(unique)+len(unique&full_ids);full_ids.update(unique)
      report['empty_ids']+=sum(not x.strip() for x in ids)
      report['full_rows']+=len(ids)
      try:fa=fr.read_next_batch();fo=0
      except StopIteration:fa=None
    break
   count=min(ca.num_rows-co,fa.num_rows-fo)
   a=ca.slice(co,count);wide=fa.slice(fo,count);b=project(wide,recipe)
   for block,seen in [(a,core_ids),(wide,full_ids)]:
    ids=block.column(primary).to_pylist();unique=set(ids)
    report['duplicates']+=len(ids)-len(unique)+len(unique&seen);seen.update(unique)
    report['empty_ids']+=sum(not x.strip() for x in ids)
   report['id_mismatches']+=pc.sum(pc.cast(pc.not_equal(a.column(primary),b.column(primary)),pa.int64())).as_py() or 0
   if not a.equals(b):
    for name in ch:
     different=pc.not_equal(a.column(name),b.column(name));n=pc.sum(pc.cast(different,pa.int64())).as_py() or 0
     report['different_cells']+=n
     if n and len(report['examples'])<5:
      idx=pc.indices_nonzero(different)[0].as_py()
      report['examples'].append({'row':report['rows']+idx,'field':name,'core':a.column(name)[idx].as_py(),'rebuilt':b.column(name)[idx].as_py()})
   strings=encoded_rows(b,fmt)
   raw=(fmt['line_terminator'].join(strings)+fmt['line_terminator']).encode('utf-8')
   virtual.update(raw);virtual_size+=len(raw)
   for row in strings:
    encoded=row.encode('utf-8');logical.update(struct.pack('>Q',len(encoded)));logical.update(encoded)
   report['rows']+=count;report['full_rows']+=count;report['cells']+=count*len(ch);co+=count;fo+=count
  report.update(core_sha256=craw.hasher.hexdigest(),full_sha256=fraw.hasher.hexdigest(),virtual_csv_sha256=virtual.hexdigest(),logical_cell_hash=logical.hexdigest(),virtual_size=virtual_size)
 finally:
  for obj in raw_objects:obj.close()
 report['stable']=before==[stat_of(p) for p in [core,full]]
 report['logical_match']=report['stable'] and not any(report[k] for k in ['different_cells','id_mismatches','duplicates','empty_ids']) and core_ids.issubset(full_ids)
 report['byte_match']=final and report['core_sha256']==report['virtual_csv_sha256'] and virtual_size==before[0]['size']
 report['binding_ready']=report['logical_match'] and report['byte_match']
 report['row_selection']=({'kind':'prefix','count':report['rows'],'full_rows':report['full_rows']} if report['rows']!=report['full_rows'] else None)
 return report


def iter_core_bytes(full_path,recipe,*,line_terminator='\n',bom=False,quoting=csv.QUOTE_MINIMAL,expected_sha256='',row_limit=None):
    if line_terminator not in {'\n','\r\n'} or quoting not in {csv.QUOTE_MINIMAL,csv.QUOTE_ALL}:
        raise ValueError('Unsupported CSV serialization')
    fmt={'line_terminator':line_terminator,'bom':bom,'quoting':quoting}
    with Path(full_path).open('r',encoding='utf-8-sig',newline='') as stream:header=next(csv.reader(stream),[])
    recipe.validate_full_header(header)
    raw=HashingFile(full_path)
    with io.BufferedReader(raw) as handle:
        batches=acsv.open_csv(handle,read_options=acsv.ReadOptions(block_size=4*1024*1024,use_threads=False),
          parse_options=acsv.ParseOptions(newlines_in_values=True),
          convert_options=acsv.ConvertOptions(include_columns=list(recipe.required_columns()),
            column_types={k:pa.string() for k in header},strings_can_be_null=False,null_values=[]))
        buf=io.StringIO(newline='');csv.writer(buf,lineterminator=line_terminator,quoting=quoting).writerow(recipe.columns)
        yield (b'\xef\xbb\xbf' if bom else b'')+buf.getvalue().encode('utf-8')
        emitted=0;source_rows=0
        for batch in batches:
            source_rows+=batch.num_rows
            if row_limit is not None:
                remaining=row_limit-emitted
                if remaining<=0:continue
                batch=batch.slice(0,min(remaining,batch.num_rows))
            rows=encoded_rows(project(batch,recipe),fmt)
            emitted+=batch.num_rows
            if rows:yield (line_terminator.join(rows)+line_terminator).encode('utf-8')
        if row_limit is not None and emitted!=row_limit:raise ValueError('Full cannot supply the verified Core row range')
        if expected_sha256 and raw.hasher.hexdigest()!=expected_sha256:
            raise ValueError('Full checksum changed during consumption')
    return raw.hasher.hexdigest()
