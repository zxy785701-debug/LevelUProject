from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from functools import partial
from pathlib import Path
root=Path(__file__).resolve().parents[1]/"frontend/dist-h5"
ThreadingHTTPServer(("127.0.0.1",10086),partial(SimpleHTTPRequestHandler,directory=str(root))).serve_forever()
