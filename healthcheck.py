from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import logging
import os
import json
from datetime import datetime

class HealthCheck(BaseHTTPRequestHandler):
    def do_GET(self):
        """Handle GET requests to the health check endpoint."""
        if self.path == '/health':
            try:
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                health_data = {
                    'status': 'healthy',
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'version': '1.0.0',
                    'service': 'rmt-coffee-amag'
                }
                self.wfile.write(json.dumps(health_data).encode())
            except Exception as e:
                logging.error(f"Error in health check: {str(e)}")
                self.send_error(500, "Internal Server Error")
        else:
            self.send_response(404)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Not Found')
    
    def log_message(self, format, *args):
        # Suppress logging for health check requests
        pass

def run_health_server(port=None):
    """Run the health check server on the specified port."""
    try:
        if port is None:
            port = int(os.environ.get('HEALTH_CHECK_PORT', 10001))
        server_address = ('', port)
        httpd = HTTPServer(server_address, HealthCheck)
        logging.info(f'Starting health check server on port {port}')
        httpd.serve_forever()
    except Exception as e:
        logging.error(f"Failed to start health check server: {str(e)}")
        raise

def start_health_server(port=None):
    """Start the health check server in a separate thread.
    
    Args:
        port (int, optional): The port to run the health check server on.
                            If not provided, uses HEALTH_CHECK_PORT environment variable 
                            or defaults to 10001.
    """
    thread = threading.Thread(
        target=run_health_server,
        args=(port,),
        daemon=True
    )
    thread.start()
    logging.info("Health check server thread started")
