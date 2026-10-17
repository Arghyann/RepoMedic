#!/usr/bin/env python3
"""
Real-Time Log Stream Monitor & Incident Dispatcher
Reads live logs from stdin, filters for serious failures, correlates by endpoint,
and dispatches incidents to Gemma.
"""

import sys
import json
import time
from collections import defaultdict, deque
from dotenv import load_dotenv

# Load GOOGLE_API_KEY from .env
load_dotenv()

from google import genai
client = genai.Client()

MODEL_NAME = "gemma-4-26b-a4b-it"

# Thresholds
WINDOW_SECONDS = 10     # Track errors over a 10-second sliding window
BURST_THRESHOLD = 4     # 4 or more errors on the same endpoint within 10s = Serious Incident
COOLDOWN_SECONDS = 30   # Don't re-trigger the same endpoint for 30s to avoid spam

# In-memory tracking
recent_errors = deque() # tuples of (timestamp, log_entry)
last_alerted = {}       # endpoint -> last alert timestamp

def is_serious(log: dict) -> bool:
    """Classifies if a log entry represents a serious failure."""
    status = log.get("status") or log.get("status_code")
    if status is not None:
        try:
            status_int = int(status)
            # 5xx = server failure, 429 = severe throttling
            if status_int >= 500 or status_int == 429:
                return True
        except (ValueError, TypeError):
            pass

    msg = str(log.get("message", "") or log.get("request", "")).lower()
    critical_words = ("oom", "exhausted", "panic", "timeout", "refused", "deadlock")
    return any(word in msg for word in critical_words)

def clean_old_errors(current_time):
    """Remove errors older than the sliding window."""
    while recent_errors and (current_time - recent_errors[0][0]) > WINDOW_SECONDS:
        recent_errors.popleft()

def ask_gemma_for_diagnosis(endpoint, count, samples):
    """Sends the correlated incident to Gemma for diagnosis."""
    prompt = f"""You are an SRE on-call engineer. A serious burst of errors was detected on endpoint: {endpoint}
Failure Rate: {count} errors within {WINDOW_SECONDS} seconds.

Sample Error Logs:
{json.dumps(samples, indent=2)}

Please provide:
1. **Diagnosis**: What went wrong?
2. **Probable Solution**: Immediate step-by-step remediation.
Keep the answer concise and actionable."""

    print(f"\n🧠 [Dispatching to Gemma ({MODEL_NAME})] Analyzing incident on {endpoint}...")
    try:
        interaction = client.interactions.create(
            model=MODEL_NAME,
            input=prompt
        )
        print("\n" + "="*60)
        print("🎯 GEMMA ROOT-CAUSE & REMEDIATION:")
        print("="*60)
        print(interaction.output_text)
        print("="*60 + "\n")
    except Exception as e:
        print(f"⚠️ Gemma Query Error: {e}\n")

def process_stream():
    print(f"🚀 Monitoring live log stream (Trigger: >={BURST_THRESHOLD} errors in {WINDOW_SECONDS}s)...")
    print("Format: [Status] Method Request\n")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            log_entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        now = time.time()
        status = log_entry.get("status", 200)
        method = log_entry.get("method", "GET")
        req = log_entry.get("request", "/")

        if is_serious(log_entry):
            print(f"🔴 \033[91m[{status}] {method} {req}\033[0m")
            recent_errors.append((now, log_entry))
            clean_old_errors(now)

            # Check if this endpoint has hit the burst threshold
            endpoint_counts = defaultdict(list)
            for ts, err in recent_errors:
                clean_req = err.get("request", "unknown").split("?")[0]
                endpoint_counts[clean_req].append(err)

            clean_req = req.split("?")[0]
            errors_on_endpoint = endpoint_counts[clean_req]

            if len(errors_on_endpoint) >= BURST_THRESHOLD:
                # Check cooldown to avoid flooding Gemma on every subsequent line
                if (now - last_alerted.get(clean_req, 0)) > COOLDOWN_SECONDS:
                    last_alerted[clean_req] = now
                    print(f"\n🚨 SERIOUS INCIDENT DETECTED: {len(errors_on_endpoint)} failures on {clean_req} within {WINDOW_SECONDS}s!")
                    ask_gemma_for_diagnosis(clean_req, len(errors_on_endpoint), errors_on_endpoint[:3])
        else:
            # Normal log (print subtle line)
            print(f"🟢 [{status}] {method} {req[:50]}")

if __name__ == "__main__":
    process_stream()
