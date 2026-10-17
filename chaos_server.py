import time, json, random, threading, sys
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

MAX_CONCURRENT = 3 # Tiny bottleneck!
active_connections = 0
lock = threading.Lock()

class ChaosHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass # Suppress default noise

    def do_POST(self):
        global active_connections
        with lock:
            if active_connections >= MAX_CONCURRENT:
                # Log authentic 503 connection pool crash
                log = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "service": "checkout-service",
                    "request": "/api/v1/checkout",
                    "status": 503,
                    "error": "ConnectionPoolExhausted",
                    "message": f"HikariPool-1 limit reached: {active_connections}/{MAX_CONCURRENT} active. Request rejected."
                }
                print(json.dumps(log), flush=True)
                self.send_response(503)
                self.end_headers()
                return
            active_connections += 1

        try:
            # Simulate slow database query that hogs the connection
            time.sleep(random.uniform(0.3, 0.8))
            log = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "service": "checkout-service",
                "request": "/api/v1/checkout",
                "status": 200,
                "message": "Order placed successfully"
            }
            print(json.dumps(log), flush=True)
            self.send_response(200)
            self.end_headers()
        finally:
            with lock:
                active_connections -= 1

    def do_GET(self):
        self.do_POST()

if __name__ == "__main__":
    print(f"🚀 Chaos server started on port 8080 (Bottleneck limit: {MAX_CONCURRENT} conns)", file=sys.stderr)
    server = ThreadingHTTPServer(("0.0.0.0", 8080), ChaosHandler)
    server.serve_forever()
