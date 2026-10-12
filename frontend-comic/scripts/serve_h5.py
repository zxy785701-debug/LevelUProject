"""Serve the built comic app and forward /api to the unchanged FastAPI server."""
import argparse
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=10087)
    parser.add_argument('--backend',default='http://127.0.0.1:8000')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]/'dist-h5'
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self,*a,**kw):super().__init__(*a,directory=str(root),**kw)
        def proxy(self):
            payload=self.rfile.read(int(self.headers.get('Content-Length',0))) if self.command=='POST' else None
            req=Request(args.backend+self.path,data=payload,method=self.command,headers={'Content-Type':'application/json'})
            try:
                response=urlopen(req,timeout=110)
            except HTTPError as error:response=error
            except URLError:
                self.send_response(502);self.send_header('Content-Type','application/json; charset=utf-8');self.end_headers()
                self.wfile.write('{"code":"BACKEND_OFFLINE","message":"后端暂未连接，请启动后端后重试","data":null}'.encode());return
            with response:
                body=response.read();self.send_response(response.status)
                self.send_header('Content-Type',response.headers.get('Content-Type','application/json'))
                self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def do_GET(self):
            if self.path.startswith('/api/'):self.proxy()
            else:super().do_GET()
        def do_POST(self):
            if self.path.startswith('/api/'):self.proxy()
            else:self.send_error(404)
    print(f'Comic H5: http://127.0.0.1:{args.port}; API: {args.backend}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()

if __name__=='__main__':main()
