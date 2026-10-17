import time, json, random, threading, sys
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

MAX_CONCURRENT = 3 # Tiny bottleneck!
active_connections = 0
lock = threading.Lock()

LOG_FILE = "/tmp/chaos_server.log"

def write_log(log_dict):
    line = json.dumps(log_dict) + "\n"
    print(line.strip(), flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line)
    except Exception:
        pass

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
                write_log(log)
                self.send_response(503)
                self.end_headers()
                return
            active_connections += 1

        try:
            # Normal database query duration (fast)
            time.sleep(random.uniform(0.1, 0.25))
            log = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "service": "checkout-service",
                "request": "/api/v1/checkout",
                "status": 200,
                "message": "Order placed successfully"
            }
            write_log(log)
            self.send_response(200)
            self.end_headers()
        finally:
            with lock:
                active_connections -= 1

    def do_GET(self):
        self.do_POST()

# Gentle background thread generating steady 200 OK logs
def gentle_normal_traffic():
    time.sleep(1) # Wait for server startup
    import urllib.request
    while True:
        try:
            req = urllib.request.Request("http://127.0.0.1:8080/api/v1/checkout", data=b"{}", method="POST")
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                pass
        except Exception:
            pass
        # Send 1 request every 1.5 - 2.5 seconds (never exceeds limit of 3!)
        time.sleep(random.uniform(1.5, 2.5))

threading.Thread(target=gentle_normal_traffic, daemon=True).start()

if __name__ == "__main__":
    print(f"🚀 Chaos server started on port 8080 (Bottleneck limit: {MAX_CONCURRENT} conns)", file=sys.stderr)
    ThreadingHTTPServer.allow_reuse_address = True
    server = ThreadingHTTPServer(("0.0.0.0", 8080), ChaosHandler)
    try:
        server.serve_forever()
    except (KeyboardInterrupt, SystemExit):
        server.server_close()
