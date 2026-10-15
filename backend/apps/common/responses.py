from rest_framework.response import Response
from backend.apps.common.json_safe import sanitize_for_json


def ok(data=None, status=200):
    payload = {
        "ok": True,
        "data": sanitize_for_json(data),
    }
    return Response(payload, status=status)


def err(message, status=400, details=None):
    payload = {
        "ok": False,
        "error": {
            "message": str(message),
        },
    }
    if details is not None:
        payload["error"]["details"] = sanitize_for_json(details)
    return Response(payload, status=status)