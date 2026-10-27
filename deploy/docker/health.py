"""Probe the real read-only Django readiness endpoint over the private uWSGI socket."""
import os
import socket
import struct
import sys

def probe():
    host=os.environ.get('DJANGO_ALLOWED_HOSTS','localhost').split(',')[0].strip()
    values={'REQUEST_METHOD':'GET','PATH_INFO':'/api/health/ready/','REQUEST_URI':'/api/health/ready/',
            'QUERY_STRING':'','SERVER_NAME':host,'HTTP_HOST':host,'SERVER_PORT':'443',
            'SERVER_PROTOCOL':'HTTP/1.1','HTTP_X_FORWARDED_PROTO':'https','UWSGI_SCHEME':'https'}
    payload=b''
    for key,value in values.items():
        key,value=key.encode(),value.encode()
        payload+=struct.pack('<H',len(key))+key+struct.pack('<H',len(value))+value
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
        client.settimeout(12)
        client.connect('/opt/local/run/uwsgi.sock')
        client.sendall(b'\0'+struct.pack('<H',len(payload))+b'\0'+payload)
        response=client.recv(4096)
    return response.split(b'\r\n',1)[0].split()[1:2]==[b'200']

if __name__=='__main__':
    try: ok=probe()
    except (OSError,ValueError,IndexError):ok=False
    sys.exit(0 if ok else 1)
