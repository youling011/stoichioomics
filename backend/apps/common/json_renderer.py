"""The existing DRF JSON bytes, with serialization timing and size only."""
from rest_framework.renderers import JSONRenderer
from .request_timing import stage,json_bytes
class TimedJSONRenderer(JSONRenderer):
 def render(self,*args,**kwargs):
  with stage('json'):encoded=super().render(*args,**kwargs)
  json_bytes(len(encoded));return encoded
