"""Local web page for the pilot (127.0.0.1 only): the conversation, the task tree, and a server-sent event stream."""
import json
import queue
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

STATIC = Path(__file__).resolve().parent / 'static'


def make_handler(pilot):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, fmt, *args):          # quiet console
            pass

        def _json(self, obj, code=200):
            body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def _body(self):
            n = int(self.headers.get('Content-Length') or 0)
            return json.loads(self.rfile.read(n).decode('utf-8') or '{}') if n else {}

        def do_GET(self):
            if self.path in ('/', '/index.html'):
                body = (STATIC / 'index.html').read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers(); self.wfile.write(body)
            elif self.path == '/api/items':
                self._json({'items': pilot.items})
            elif self.path == '/api/tree':
                self._json(pilot.tree())
            elif self.path == '/api/events':
                self._events()
            elif self.path.startswith('/api/view/'):         # /api/view/<page|doc|queries|executions>[/<id>]
                parts = self.path.split('?')[0].split('/')[3:]
                self._json(pilot.view(parts[0], parts[1] if len(parts) > 1 else None))
            elif self.path.startswith('/record/'):         # the executor's session, read-only, on request
                path = pilot.export_record(self.path.split('/')[-1])
                if not path: return self._json({'error': 'no session record for this executor'}, 404)
                body = Path(path).read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers(); self.wfile.write(body)
            else:
                self._json({'error': 'not found'}, 404)

        def do_POST(self):
            try:
                body = self._body()
                if self.path == '/api/message':
                    text = (body.get('text') or '').strip()
                    if not text: return self._json({'error': 'empty'}, 400)
                    self._json(pilot.message(text))
                elif self.path == '/api/ui':
                    op = body.pop('op', '')
                    self._json(pilot.ui(op, **body))
                else:
                    self._json({'error': 'not found'}, 404)
            except Exception as e:
                self._json({'error': str(e)}, 500)

        def _events(self):
            q = pilot.subscribe()
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Connection', 'keep-alive')
            self.end_headers()
            try:
                while True:
                    try:
                        ev = q.get(timeout=15)
                        data = 'data: ' + json.dumps(ev, ensure_ascii=False) + '\n\n'
                    except queue.Empty:
                        data = ': ping\n\n'
                    self.wfile.write(data.encode('utf-8')); self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                pass
            finally:
                pilot.unsubscribe(q)

    return Handler


def serve(pilot, host='127.0.0.1', port=8765):
    httpd = ThreadingHTTPServer((host, port), make_handler(pilot))
    httpd.daemon_threads = True
    return httpd
