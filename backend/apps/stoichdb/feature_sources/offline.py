"""Bounded-memory reader for the unchanged v1 offline JSON binding contract.

Only metadata are indexed. Feature bytes and projection rules are untouched.
The index retains offsets/aliases, not all receipt objects. No file handle is
kept open between calls and no persistent source Core cache is created.
"""
from collections import OrderedDict
from collections.abc import Mapping
import json
from pathlib import Path
from .asset_state import change_token
from .projection import ProjectionError
from .provenance import recipe_digest


class _JSONStream:
    def __init__(self,stream):
        import codecs
        self.stream=stream;self.decoder=codecs.getincrementaldecoder('utf-8')()
        self.buffer='';self.position=0;self.eof=False
    def more(self):
        block=self.stream.read(65536)
        self.buffer+=self.decoder.decode(block,final=not block)
        if not block:self.eof=True
    def consume(self,count):
        value=self.buffer[:count];self.position+=len(value.encode('utf-8'));self.buffer=self.buffer[count:]
        return value
    def whitespace(self):
        while True:
            n=len(self.buffer)-len(self.buffer.lstrip())
            if n:self.consume(n)
            if self.buffer or self.eof:return
            self.more()
    def character(self,expected):
        self.whitespace()
        if not self.buffer.startswith(expected):raise ProjectionError('Malformed offline manifest structure')
        self.consume(len(expected))
    def value(self):
        self.whitespace();start=self.position
        while True:
            try:value,count=json.JSONDecoder().raw_decode(self.buffer)
            except json.JSONDecodeError as exc:
                if self.eof:raise ProjectionError('Malformed offline manifest JSON') from exc
                self.more();continue
            self.consume(count);return value,start,self.position-start
    def members(self):
        self.character('{');first=True
        while True:
            self.whitespace()
            if self.buffer.startswith('}'):self.consume(1);return
            if not first:self.character(',')
            key,_,_=self.value()
            if not isinstance(key,str):raise ProjectionError('Offline manifest object key must be text')
            self.character(':');first=False;yield key


class IndexedBindings(Mapping):
    """Mapping-compatible v1 source registry with a bounded 128-record cache."""
    def __init__(self,filename,alias_key):
        self.filename=Path(filename);self.alias_key=alias_key;self.index={};self.recipes={};self.cache=OrderedDict()
        self.identity=self._identity();format_name=None;seen=set()
        with self.filename.open('rb') as f:
            parser=_JSONStream(f)
            for name in parser.members():
                if name in seen:raise ProjectionError('Duplicate offline manifest section')
                seen.add(name)
                if name=='bindings':
                    for key in parser.members():
                        row,offset,length=parser.value()
                        if key in self.index:raise ProjectionError('Duplicate offline source alias')
                        if not isinstance(row,dict) or alias_key(row['legacy_path'])!=key:raise ProjectionError('Offline alias identity mismatch')
                        self.index[key]=(offset,length,row['legacy_path'],row.get('representation','csv'))
                else:
                    value,_,_=parser.value()
                    if name=='format':format_name=value
                    elif name=='recipes':self.recipes=value
            parser.whitespace()
            if parser.buffer or not parser.eof:raise ProjectionError('Trailing offline manifest content')
        if format_name!='stoich-corefull-bindings-v1' or 'bindings' not in seen:raise ProjectionError('Unknown offline source manifest')
        if not isinstance(self.recipes,dict):raise ProjectionError('Invalid offline recipe catalog')
        for rid,recipe in self.recipes.items():
            if recipe_digest(recipe)!=rid:raise ProjectionError('Offline recipe identity mismatch')
        self._guard()
    def _identity(self):
        st=self.filename.stat()
        return st.st_size,st.st_mtime_ns,change_token(self.filename)
    def _guard(self):
        if self._identity()!=self.identity:raise ProjectionError('Offline binding manifest changed; reload its exact registry')
    def _decode(self,key,data):
        row=json.loads(data)
        if 'recipe' not in row:
            try:row['recipe']=self.recipes[row['recipe_id']]
            except KeyError as exc:raise ProjectionError('Offline recipe missing') from exc
        if recipe_digest(row['recipe'])!=row['recipe_id'] or self.alias_key(row['legacy_path'])!=key:
            raise ProjectionError('Offline recipe or alias identity mismatch')
        return row
    def __getitem__(self,key):
        self._guard()
        if key in self.cache:
            self.cache.move_to_end(key);return self.cache[key]
        offset,length,_,_=self.index[key]
        with self.filename.open('rb') as f:f.seek(offset);data=f.read(length)
        row=self._decode(key,data);self._guard();self.cache[key]=row
        if len(self.cache)>128:self.cache.popitem(last=False)
        return row
    def __iter__(self):return iter(self.index)
    def __len__(self):return len(self.index)
    def values(self):
        self._guard()
        try:
            with self.filename.open('rb') as f:
                for key,(offset,length,_,_) in self.index.items():
                    f.seek(offset);yield self._decode(key,f.read(length))
        finally:self._guard()
    def alias_records(self):
        self._guard()
        for _,_,path,representation in self.index.values():yield {'legacy_path':path,'representation':representation}
        self._guard()
