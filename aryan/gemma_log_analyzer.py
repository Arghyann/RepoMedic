#!/usr/bin/env python3
"""
Gemma Log Filter & RCA Dispatcher
Reads live logs from stdin or a file, extracts anomalies, clusters errors,
and formats/dispatches incident snapshots to Google Gemma for root cause analysis.
"""

import sys
import os
import json
import argparse
import urllib.request
import urllib.error
from collections import Counter, defaultdict
from datetime import datetime

class LogFilter:
    """Filters, deduplicates, and condenses raw log streams into a concise anomaly snapshot."""
    
    def __init__(self, error_threshold_pct=10.0, window_size=50):
        self.error_threshold_pct = error_threshold_pct
        self.window_size = window_size
        self.reset()

    def reset(self):
        self.total_count = 0
        self.error_logs = []
        self.status_counts = Counter()
        self.endpoint_failures = Counter()
        self.clustered_signatures = defaultdict(lambda: {"count": 0, "sample": None})

    def is_problematic(self, log: dict) -> bool:
        """Determines if a log entry represents a failure or abnormal event."""
        # Check HTTP status codes
        status = log.get("status") or log.get("status_code") or log.get("code")
        if status is not None:
            try:
                status_int = int(status)
                if status_int >= 400:
                    return True
            except (ValueError, TypeError):
                pass

        # Check log level
        level = str(log.get("level", "") or log.get("severity", "")).upper()
        if level in ("ERROR", "CRITICAL", "FATAL", "PANIC"):
            return True

        # Check for error indicators in message
        message = str(log.get("message", "") or log.get("error", "") or log.get("request", "")).lower()
        error_keywords = ("exception", "timeout", "exhausted", "failed", "refused", "oom", "panic")
        if any(keyword in message for keyword in error_keywords):
            return True

        return False

    def extract_signature(self, log: dict) -> str:
        """Creates a cluster key so 1000 identical errors don't flood the prompt."""
        status = log.get("status") or log.get("status_code") or "ERR"
        method = log.get("method") or "REQ"
        target = log.get("request") or log.get("endpoint") or log.get("path") or log.get("message", "unknown")
        # Strip query params / timestamps / IDs to cluster cleanly
        clean_target = str(target).split("?")[0]
        return f"[{status}] {method} {clean_target}"

    def ingest(self, log_entry: dict):
        self.total_count += 1
        
        status = log_entry.get("status") or log_entry.get("status_code")
        if status:
            self.status_counts[str(status)] += 1

        if self.is_problematic(log_entry):
            self.error_logs.append(log_entry)
            sig = self.extract_signature(log_entry)
            self.clustered_signatures[sig]["count"] += 1
            if self.clustered_signatures[sig]["sample"] is None:
                self.clustered_signatures[sig]["sample"] = log_entry

            endpoint = log_entry.get("request") or log_entry.get("endpoint") or "unknown"
            self.endpoint_failures[endpoint] += 1

    def get_summary(self) -> dict:
        if self.total_count == 0:
            return None

        error_rate = (len(self.error_logs) / self.total_count) * 100

        # Format clustered errors for compact Gemma consumption
        clustered_summary = []
        for sig, data in sorted(self.clustered_signatures.items(), key=lambda x: x[1]["count"], reverse=True):
            clustered_summary.append({
                "signature": sig,
                "occurrences": data["count"],
                "sample_log": data["sample"]
            })

        return {
            "total_logs_analyzed": self.total_count,
            "total_errors": len(self.error_logs),
            "error_rate_pct": round(error_rate, 2),
            "status_code_distribution": dict(self.status_counts),
            "top_failing_endpoints": self.endpoint_failures.most_common(5),
            "clustered_errors": clustered_summary[:5]  # Top 5 most frequent error patterns
        }


class GemmaClient:
    """Builds Gemma-optimized prompts and interfaces with Ollama / OpenAI-compatible / Google AI Studio / stdout."""

    def __init__(self, ollama_url="http://localhost:11434", model="gemma2:9b", endpoint=None, api_key=None):
        self.ollama_url = ollama_url
        self.model = model
        self.endpoint = endpoint
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

    def build_gemma_prompt(self, summary: dict) -> str:
        """Formats the anomaly summary into Gemma's prompt template."""
        context_str = json.dumps(summary, indent=2)

        prompt = f"""<start_of_turn>user
You are an expert Site Reliability Engineer (SRE).
Below is an incident report extracted from production web logs.

INCIDENT TELEMETRY SNAPSHOT:
```json
{context_str}
```

Based on the clustered errors and status distributions above:
1. **Root Cause Diagnosis**: What is the root failure mechanism?
2. **Impact Assessment**: What users / endpoints are affected and how severely?
3. **Actionable Remediation**: Provide concrete, step-by-step commands or configuration fixes to resolve this immediately.
<end_of_turn>
<start_of_turn>model
"""
        return prompt

    def query_ollama(self, prompt: str) -> str:
        """Sends the prompt to a local Ollama instance running Gemma."""
        endpoint = f"{self.ollama_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            endpoint,
            data=data,
            headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                res_json = json.loads(resp.read().decode("utf-8"))
                return res_json.get("response", "")
        except urllib.error.URLError as e:
            return f"[Ollama Connection Error: Could not connect to {endpoint}. Is Ollama running? Error: {e}]"

    def query_openai_compat(self, prompt: str) -> str:
        """Sends prompt to any local OpenAI-compatible server (vLLM, LM Studio, llama-server)."""
        url = f"{self.endpoint.rstrip('/')}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2
        }
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                res_json = json.loads(resp.read().decode("utf-8"))
                return res_json["choices"][0]["message"]["content"]
        except Exception as e:
            return f"[OpenAI-compat API Error: {e}]"
    def query_google_ai(self, prompt: str) -> str:
        """Sends prompt directly to Google's Generative AI API using GOOGLE_API_KEY."""
        # Check if google-genai SDK is available
        try:
            from google import genai
            client = genai.Client()
            model_name = self.model if "gemma" in self.model else "gemma-4-31b-it"
            interaction = client.interactions.create(
                model=model_name,
                input=prompt
            )
            return interaction.output_text
        except Exception:
            pass

        # Fallback to direct HTTP API via urllib
        if not self.api_key:
            return "[Error: No GOOGLE_API_KEY found in .env or environment]"
        
        model_name = self.model if "gemma" in self.model else "gemma-4-31b-it"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={self.api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1024}
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                res_json = json.loads(resp.read().decode("utf-8"))
                candidate = res_json.get("candidates", [{}])[0]
                return candidate.get("content", {}).get("parts", [{}])[0].get("text", "")
        except Exception as e:
            return f"[Google API Error: {e}]"


def process_stream(filter_obj: LogFilter, gemma_client: GemmaClient, args):
    """Processes live logs coming through standard input."""
    print("🚀 [Gemma Log Filter] Listening to stdin stream... (Ctrl+C to quit)\n")
    
    ticker_count = 0
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            # If log is plain text, wrap into minimal structure
            entry = {"message": line, "status": 500 if "error" in line.lower() else 200}

        filter_obj.ingest(entry)
        ticker_count += 1

        # Real-time stdout visual indicator
        status = entry.get("status", 200)
        method = entry.get("method", "")
        req = entry.get("request") or entry.get("endpoint") or entry.get("message", "")
        badge = "🔴 ERR" if filter_obj.is_problematic(entry) else "🟢 OK "
        print(f"[{badge}] {status} {method} {str(req)[:60]}")

        # Check window trigger
        if filter_obj.total_count >= filter_obj.window_size:
            summary = filter_obj.get_summary()
            if summary and summary["error_rate_pct"] >= filter_obj.error_threshold_pct:
                handle_incident(summary, gemma_client, args)
            filter_obj.reset()


def load_env(env_path=".env"):
    """Load key-value pairs from .env into os.environ if present."""
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def handle_incident(summary: dict, gemma_client: GemmaClient, args):
    print("\n" + "="*70)
    print(f"🚨 INCIDENT SPIKE DETECTED: {summary['error_rate_pct']}% Errors across {summary['total_logs_analyzed']} requests!")
    print("="*70)

    prompt = gemma_client.build_gemma_prompt(summary)

    if args.google:
        print(f"\n🧠 Querying Google Gemma ({gemma_client.model})...")
        response = gemma_client.query_google_ai(prompt)
        print("\n--- [GEMMA DIAGNOSIS & REMEDIATION] ---")
        print(response)
    elif args.endpoint:
        print(f"\n🧠 Querying Gemma ({args.model}) via {args.endpoint}...")
        response = gemma_client.query_openai_compat(prompt)
        print("\n--- [GEMMA DIAGNOSIS & REMEDIATION] ---")
        print(response)
    elif args.ollama:
        print(f"\n🧠 Querying Gemma ({args.model}) via Ollama...")
        response = gemma_client.query_ollama(prompt)
        print("\n--- [GEMMA DIAGNOSIS & REMEDIATION] ---")
        print(response)
    else:
        print("\n--- [GEMMA PROMPT (Ready to feed to model)] ---")
        print(prompt)
        print("💡 Hint: Run with `--google` (uses .env GOOGLE_API_KEY) or `--ollama` to automatically query Gemma.")

    print("\n" + "-"*70 + "\n")


def main():
    load_env()
    parser = argparse.ArgumentParser(description="Filter logs and prepare incident diagnosis for Gemma")
    parser.add_argument("--file", "-f", help="Path to static log file to analyze (instead of stdin)")
    parser.add_argument("--threshold", "-t", type=float, default=10.0, help="Error rate %% threshold to trigger alert (default: 10.0)")
    parser.add_argument("--window", "-w", type=int, default=50, help="Sliding window size (default: 50 logs)")
    parser.add_argument("--google", action="store_true", help="Send prompt directly to Google's hosted Gemma using GOOGLE_API_KEY in .env")
    parser.add_argument("--ollama", action="store_true", help="Send prompt directly to local Ollama instance")
    parser.add_argument("--endpoint", help="Custom OpenAI-compatible endpoint URL (e.g., http://localhost:8000/v1)")
    parser.add_argument("--api-key", help="API key for endpoint (or set GEMINI_API_KEY / GOOGLE_API_KEY env var)")
    parser.add_argument("--model", default="gemma-4-31b-it", help="Gemma model name (default: gemma-4-31b-it for Google API)")
    parser.add_argument("--ollama-url", default="http://localhost:11434", help="Ollama base URL")
    parser.add_argument("--dry-run", action="store_true", help="Only display the formatted Gemma prompt without querying")

    args = parser.parse_args()

    filter_obj = LogFilter(error_threshold_pct=args.threshold, window_size=args.window)
    gemma_client = GemmaClient(
        ollama_url=args.ollama_url,
        model=args.model,
        endpoint=args.endpoint,
        api_key=args.api_key or os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    )

    if args.file:
        if not os.path.exists(args.file):
            print(f"Error: File '{args.file}' not found.")
            sys.exit(1)
        print(f"📂 Analyzing static log file: {args.file}")
        with open(args.file, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        filter_obj.ingest(json.loads(line))
                    except json.JSONDecodeError:
                        filter_obj.ingest({"message": line, "status": 500 if "error" in line.lower() else 200})
        summary = filter_obj.get_summary()
        if summary:
            handle_incident(summary, gemma_client, args)
        else:
            print("No valid logs found in file.")
    else:
        # Check if stdin has data
        if sys.stdin.isatty():
            print("Usage Examples:")
            print("  1. Stream live from Docker flog:")
            print("     docker run --rm mingrammer/flog -f json -l -d 0.1s | python3 gemma_log_analyzer.py")
            print("  2. Analyze an existing log file:")
            print("     python3 gemma_log_analyzer.py --file sample_logs.jsonl")
            print("  3. Direct to Ollama:")
            print("     python3 gemma_log_analyzer.py --file sample_logs.jsonl --ollama --model gemma2:2b\n")
            print("Error: No input provided on stdin and no --file specified.")
            sys.exit(1)

        process_stream(filter_obj, gemma_client, args)

if __name__ == "__main__":
    main()
