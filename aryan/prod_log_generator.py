#!/usr/bin/env python3
"""
Realistic Production Log Stream Generator
Simulates a live microservice stream: emits normal traffic, and periodically
injects realistic incidents (DB pool full, Disk full, Memory OOM, Downstream timeout).
"""

import time
import json
import random
import sys
from datetime import datetime, timezone

NORMAL_ENDPOINTS = [
    ("/api/v1/products", "GET", 200),
    ("/api/v1/health", "GET", 200),
    ("/api/v1/cart", "GET", 200),
    ("/api/v1/user/profile", "GET", 200),
    ("/auth/status", "GET", 200)
]

INCIDENT_TYPES = [
    "db_pool_exhaustion",
    "disk_full",
    "memory_oom",
    "downstream_timeout"
]

def make_normal_log():
    endpoint, method, status = random.choice(NORMAL_ENDPOINTS)
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service": "storefront-api",
        "method": method,
        "request": endpoint,
        "status": status,
        "latency_ms": round(random.uniform(15.0, 85.0), 2),
        "message": "Request completed successfully"
    }

def make_incident_log(incident_type):
    ts = datetime.now(timezone.utc).isoformat()

    if incident_type == "db_pool_exhaustion":
        return {
            "timestamp": ts,
            "service": "checkout-service",
            "method": "POST",
            "request": "/api/v1/checkout",
            "status": 503,
            "latency_ms": 3000.0,
            "error_type": "ConnectionPoolTimeoutException",
            "message": "HikariPool-1: Timeout acquiring connection after 3000ms. Active: 50/50, Idle: 0, Waiting: 128"
        }
    elif incident_type == "disk_full":
        return {
            "timestamp": ts,
            "service": "order-logger",
            "method": "POST",
            "request": "/api/v1/orders/export",
            "status": 500,
            "latency_ms": 120.0,
            "error_type": "DiskFullException",
            "message": "IOException: No space left on device. /var/log/orders/audit.log write failed (mount /dev/sda1 at 100% inode capacity)"
        }
    elif incident_type == "memory_oom":
        return {
            "timestamp": ts,
            "service": "report-generator",
            "method": "POST",
            "request": "/api/v1/reports/pdf",
            "status": 500,
            "latency_ms": 8500.0,
            "error_type": "OutOfMemoryError",
            "message": "java.lang.OutOfMemoryError: Java heap space. GC overhead limit exceeded allocating byte[104857600]"
        }
    elif incident_type == "downstream_timeout":
        return {
            "timestamp": ts,
            "service": "payment-gateway",
            "method": "POST",
            "request": "/api/v1/payments/charge",
            "status": 504,
            "latency_ms": 10000.0,
            "error_type": "GatewayTimeoutException",
            "message": "Read timed out after 10000ms connecting to downstream provider: https://api.stripe.com/v1/charges"
        }

def stream(rate_sec=0.15):
    """Streams continuous logs and injects an incident burst every 20-30 seconds."""
    print("🚀 Starting realistic production log generator...", file=sys.stderr)
    start_time = time.time()
    next_incident_time = start_time + 10.0 # First incident in 10s
    current_incident = None
    incident_burst_count = 0

    while True:
        now = time.time()

        # Check if it's time to trigger an incident burst
        if now >= next_incident_time and current_incident is None:
            current_incident = random.choice(INCIDENT_TYPES)
            incident_burst_count = random.randint(5, 8)
            print(f"\n⚠️ [SIMULATING INCIDENT BURST: {current_incident}]", file=sys.stderr)

        if current_incident and incident_burst_count > 0:
            log_obj = make_incident_log(current_incident)
            incident_burst_count -= 1
            if incident_burst_count == 0:
                current_incident = None
                next_incident_time = now + random.uniform(20.0, 35.0) # Next incident in 20-35s
        else:
            log_obj = make_normal_log()

        # Print JSON directly to stdout for piping
        print(json.dumps(log_obj), flush=True)
        time.sleep(rate_sec)

if __name__ == "__main__":
    stream()
