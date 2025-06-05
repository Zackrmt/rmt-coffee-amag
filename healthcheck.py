from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import logging
import os
import json
from datetime import datetime

class HealthCheck(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            health_data = {
                'status': 'healthy',
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'version': '1.0.0'
            }
            self.wfile.write(json.dumps(health_data).encode())
        else:
            self.send_response(404)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Not Found')

def run_health_server():
    port = int(os.environ.get('PORT', 10000))
    server_address = ('', port)
    httpd = HTTPServer(server_address, HealthCheck)
    logging.info(f'Starting health check server on port {port}')
    httpd.serve_forever()

def start_health_server():
    thread = threading.Thread(target=run_health_server, daemon=True)
    thread.start()
