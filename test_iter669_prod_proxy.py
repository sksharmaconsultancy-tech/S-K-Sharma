"""Serve /app/frontend/dist with /api proxied to localhost:8001 (prod-build test)."""
import http.server, socketserver, urllib.request, os

DIST = "/app/frontend/dist"
BACKEND = "http://localhost:8001"

class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=DIST, **kw)

    def do_ALL(self):
        if self.path.startswith("/api"):
            url = BACKEND + self.path
            body = None
            ln = int(self.headers.get("Content-Length") or 0)
            if ln:
                body = self.rfile.read(ln)
            req = urllib.request.Request(url, data=body, method=self.command)
            for k in ("Authorization", "Content-Type"):
                if self.headers.get(k):
                    req.add_header(k, self.headers[k])
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    data = r.read()
                    self.send_response(r.status)
                    self.send_header("Content-Type", r.headers.get("Content-Type", "application/json"))
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
            except urllib.error.HTTPError as e:
                data = e.read()
                self.send_response(e.code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            return
        # SPA-ish static: map /route -> /route.html
        p = self.path.split("?")[0]
        if p != "/" and "." not in os.path.basename(p) and os.path.exists(DIST + p + ".html"):
            self.path = p + ".html"
        if self.command == "GET":
            super().do_GET()
        else:
            self.send_response(405); self.end_headers()

    do_GET = do_ALL
    do_POST = do_ALL

    def log_message(self, *a):
        pass

with socketserver.ThreadingTCPServer(("", 9099), H) as srv:
    srv.serve_forever()
