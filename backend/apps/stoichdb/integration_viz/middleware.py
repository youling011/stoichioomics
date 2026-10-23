from django.middleware.gzip import GZipMiddleware
class IntegrationCompressionMiddleware(GZipMiddleware):
    """Compress exact large integration payloads without changing other APIs."""
    def process_response(self,request,response):
        if '/integration/visualizations/' not in request.path:return response
        return super().process_response(request,response)
