"""Simple HTTP server with S2 API proxy to avoid CORS issues."""

import json
import urllib.request
import urllib.parse
from http.server import HTTPServer, SimpleHTTPRequestHandler


class ProxyHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/api/s2/'):
            self.proxy_s2()
        else:
            super().do_GET()

    def proxy_s2(self):
        # /api/s2/paper/search?query=... -> https://api.semanticscholar.org/graph/v1/paper/search?query=...
        s2_path = self.path[len('/api/s2/'):]
        url = f'https://api.semanticscholar.org/graph/v1/{s2_path}'
        try:
            req = urllib.request.Request(url)
            # Use API key if available (higher rate limit)
            s2_key = os.environ.get('S2_API_KEY', '')
            if s2_key:
                req.add_header('x-api-key', s2_key)
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def log_message(self, format, *args):
        pass  # quiet


if __name__ == '__main__':
    import os, sys
    # Serve from the directory where this script lives (docs/)
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    port = 8080
    server = HTTPServer(('', port), ProxyHandler)
    print(f'Paper Copilot running at http://localhost:{port}')
    server.serve_forever()
