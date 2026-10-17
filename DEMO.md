# 🚀 RepoMedic: AI-Powered Real-Time SRE Log Analyzer
### Live Incident Diagnosis & Remediation with Google Gemma

This guide contains the exact steps and commands to demonstrate the live end-to-end incident detection and autonomous AI diagnosis pipeline.

---

## 🏗️ Architecture Under the Hood

```
[Remote Debian Cloud VM]                             [Local SRE Workstation]
┌─────────────────────────────────┐                 ┌───────────────────────────┐
│ 1. chaos_server.py (Daemon)     │                 │                           │
│    Bottlenecked (Max conns: 3)  │                 │  stream_monitor.py        │
│                │                │                 │  (Sliding-Window Filter)  │
│                ▼                │                 │             │             │
│    /tmp/chaos_server.log        │──(ssh tail -f)─►│             ▼             │
│                ▲                │                 │  Google Gemma Model       │
│                │                │                 │  (gemma-4-26b-a4b-it)     │
│ 2. burst_hammer (Go Process)    │                 │             │             │
│    50 Concurrent Goroutines     │                 │             ▼             │
└─────────────────────────────────┘                 │  Actionable RCA & Fixes   │
                                                    └───────────────────────────┘
```

---

## ⚡ Quick Demo Walkthrough (3 Steps)

### Prerequisites (Run Once)
Ensure you are in the project folder and the virtual environment is active:
```bash
cd /home/aryan/Projects/hack
source .venv/bin/activate
```

---

### Step 1: Start the Live Stream Monitor (Terminal 1)
Run the real-time stream monitor. This tails live logs from the remote cloud VM and watches for anomaly bursts:

```bash
ssh debian "tail -f /tmp/chaos_server.log" | python stream_monitor.py
```

**What to point out during the demo:**
* The server on the cloud VM is running smoothly in normal state.
* The terminal displays real-time green logs (`🟢 [200] POST /api/v1/checkout`) every ~2 seconds.
* The system is currently healthy with zero alerts.

---

### Step 2: Trigger the Production Outage (Terminal 2)
Open a second terminal window and fire the high-concurrency Go load generator to overwhelm the server:

```bash
ssh debian "./burst_hammer"
```

**What to point out during the demo:**
* The Go binary spawns 50 concurrent goroutines firing simultaneously at the checkout API.
* The server's 3-connection pool immediately saturates.
* In **Terminal 1**, watch the green stream instantly turn into a cascade of red `503` errors:
  ```text
  🔴 [503] POST /api/v1/checkout
  🔴 [503] POST /api/v1/checkout
  🔴 [503] POST /api/v1/checkout
  🔴 [503] POST /api/v1/checkout

  🚨 SERIOUS INCIDENT DETECTED: 4 failures on /api/v1/checkout within 10s!
  🧠 [Dispatching to Gemma (gemma-4-26b-a4b-it)] Analyzing incident on /api/v1/checkout...
  ```

---

### Step 3: Observe Autonomous AI Diagnosis (Terminal 1)
Within seconds, **Gemma** returns an SRE incident brief with root cause analysis and immediate remediation:

```text
============================================================
🎯 GEMMA ROOT-CAUSE & REMEDIATION:
============================================================
### 1. Diagnosis
Root Cause: Database Connection Pool Exhaustion.
The `checkout-service` is unable to handle incoming requests because its 
HikariCP connection pool is saturated. The configuration is currently set 
to a maximum of only 3 connections, all of which are currently active/busy. 
This is causing the service to reject new requests with a 503 Service Unavailable error.

### 2. Probable Solution
Immediate Remediation (Mitigation):
1. Increase Pool Size: Immediately increase the `maximum-pool-size` configuration 
   for `HikariPool-1` in the checkout-service (e.g., increase from 3 to 15 or 20, 
   depending on database capacity).
2. Redeploy/Refresh Config: Apply the configuration change via a rolling restart 
   or a dynamic configuration update to alleviate the bottleneck.

Follow-up Investigation (Root Cause Analysis):
1. Check for Connection Leaks: Verify if the application is properly closing 
   database connections in finally blocks.
2. Analyze Query Performance: Check for slow-running SQL queries holding connections.
============================================================
```

Once the Go burst wave finishes, the stream automatically recovers and returns to showing steady green `🟢 [200]` entries.

---

## 🛠️ Management & Utility Commands

### Verify Server Status on Remote VM
```bash
ssh debian "pgrep -fl python3"
```

### Restart Server Daemon on Remote VM (If Ever Needed)
```bash
ssh debian "pkill -f chaos_server.py || true; rm -f /tmp/chaos_server.log; nohup python3 -u chaos_server.py </dev/null >/tmp/server_stdout.log 2>&1 &"
```

### Test Offline / Batch Analysis on Pre-recorded Incidents
To show how the analyzer handles pre-recorded log dumps (e.g., for CI/CD or post-incident review):
```bash
python aryan/gemma_log_analyzer.py --file aryan/sample_logs.jsonl --google
```

### Validate Google API Key
```bash
python aryan/test_genai.py
```
