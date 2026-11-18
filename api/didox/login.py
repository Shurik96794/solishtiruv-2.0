from http.server import BaseHTTPRequestHandler
import json
class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body=json.dumps({"error":"Didox login xizmati hali sozlanmagan. Server ulanishini tekshiring."},ensure_ascii=False).encode()
        self.send_response(503)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Content-Length",str(len(body)))
        self.end_headers()
        self.wfile.write(body)
