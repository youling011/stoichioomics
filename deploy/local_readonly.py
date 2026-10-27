"""Temporary local acceptance mode; disabled for isolated writable validation."""
from django.http import JsonResponse

class LocalReadOnlyMiddleware:
    def __init__(self,get_response):self.get_response=get_response
    def __call__(self,request):
        if request.method not in {'GET','HEAD','OPTIONS'}:
            return JsonResponse({'ok':False,'message':'当前入口处于只读验证模式，写入和计算提交尚未开放。',
                                 'details':{'code':'local_readonly_validation'}},status=503)
        return self.get_response(request)
