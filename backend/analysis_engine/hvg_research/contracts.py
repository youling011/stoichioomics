from dataclasses import dataclass
from .artifacts import member_hash
@dataclass(frozen=True)
class GeneUniverse:
 context_id:str
 genes:tuple
 hvg:tuple
 def validate(self):
  if len(set(self.genes))!=len(self.genes) or len(set(self.hvg))!=len(self.hvg):raise ValueError('Duplicate gene identifiers')
  if not set(self.hvg)<=set(self.genes):raise ValueError('H outside U')
  return {'U':len(self.genes),'H':len(self.hvg),'N':len(self.genes)-len(self.hvg),'hash':member_hash(self.genes)}
def validate_table(frame,name):
 if name=='hvg_labels' and frame.gene_id.duplicated().any():raise ValueError('Duplicate primary label')
 for col in frame:
  if col=='p_value' or col.startswith('q_'):
   v=frame[col].dropna()
   if len(v) and not v.between(0,1).all():raise ValueError(f'{name}.{col} outside [0,1]')
