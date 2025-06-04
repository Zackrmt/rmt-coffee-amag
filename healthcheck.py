from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import logging

class HealthCheck(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'OK')
        else:
            self.send_response(404)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Not Found')

def run_health_server():
    server_address = ('', 8080)
    httpd = HTTPServer(server_address, HealthCheck)
    logging.info('Starting health check server on port 8080')
    httpd.serve_forever()

def start_health_server():
    thread = threading.Thread(target=run_health_server, daemon=True)
    thread.start()
