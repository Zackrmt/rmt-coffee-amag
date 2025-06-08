"""
UptimeRobot Integration Module
This module helps ensure the bot stays alive with UptimeRobot pings
"""

import os
import logging
import threading
import time
import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class UptimeHandler(BaseHTTPRequestHandler):
    """Simple HTTP handler for UptimeRobot pings"""
    
    def do_GET(self):
        """Handle GET requests for health check"""
        if self.path == '/ping' or self.path == '/' or self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            response = f"OK - {datetime.datetime.now().isoformat()}"
            self.wfile.write(response.encode())
            logger.debug(f"Health check received: {self.path}")
        else:
            self.send_response(404)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Not Found')
    
    def log_message(self, format, *args):
        """Override to control logging"""
        if args[0].startswith('GET /health') or args[0].startswith('GET /ping'):
            # Don't log health checks to reduce noise
            return
        logger.info("%s - - [%s] %s" % (self.client_address[0], self.log_date_time_string(), format % args))

def start_uptime_server(port=None):
    """Start a dedicated server for UptimeRobot pings"""
    if port is None:
        port = int(os.getenv('UPTIME_PORT', os.getenv('PORT', 10001)))
    
    server = HTTPServer(('0.0.0.0', port), UptimeHandler)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    logger.info(f"UptimeRobot ping server started on port {port}")
    return server

def keep_alive():
    """Main function to start the uptime server"""
    try:
        server = start_uptime_server()
        logger.info("UptimeRobot integration started successfully")
        
        # Keep the main thread alive
        while True:
            time.sleep(60)
            
    except Exception as e:
        logger.error(f"Error in UptimeRobot integration: {e}")
        raise

if __name__ == '__main__':
    # Run as standalone for testing
    logger.info("Starting UptimeRobot integration in standalone mode")
    keep_alive()
