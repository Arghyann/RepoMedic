#!/usr/bin/env python3
"""
Tests the GOOGLE_API_KEY from .env by calling the Google Generative Language API.
Uses standard library urllib (no pip dependencies required).
"""

import os
import sys
import json
import urllib.request
import urllib.error

def load_env(env_path=".env"):
    """Simple parser to load key-value pairs from .env into os.environ."""
    if not os.path.exists(env_path):
        return None
    
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip("'\"")
                os.environ[key] = val
    return os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")

def test_api_key():
    print("🔍 Checking .env file...")
    api_key = load_env()

    if not api_key:
        print("❌ Error: No GOOGLE_API_KEY (or GEMINI_API_KEY) found in .env")
        sys.exit(1)

    masked_key = api_key[:6] + "..." + api_key[-4:] if len(api_key) > 10 else "***"
    print(f"🔑 Found key: {masked_key}")
    print("📡 Sending test request to Google Generative AI API...")

    # Step 1: Test authentication by listing available models
    models_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    try:
        req = urllib.request.Request(models_url, headers={"User-Agent": "KeyTestScript/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = [m.get("name", "").replace("models/", "") for m in data.get("models", [])]
            gemma_models = [m for m in models if "gemma" in m.lower()]
            gemini_models = [m for m in models if "gemini" in m.lower()]
            
            print("✅ SUCCESS: API Key is VALID and ACTIVE!")
            print(f"   Total models accessible: {len(models)}")
            if gemma_models:
                print(f"   Available Gemma models: {', '.join(gemma_models[:5])}")
            if gemini_models:
                print(f"   Available Gemini models: {', '.join(gemini_models[:5])}")

    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        try:
            err_json = json.loads(error_body)
            err_msg = err_json.get("error", {}).get("message", error_body)
        except Exception:
            err_msg = error_body
        print(f"❌ AUTHENTICATION FAILED (HTTP {e.code}): {err_msg}")
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"❌ NETWORK ERROR: Unable to reach Google API ({e.reason})")
        sys.exit(1)

    # Step 2: Test a quick text generation request with Gemma
    print("\n🧪 Testing inference with Google's Gemma (gemma-4-31b-it)...")
    gen_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemma-4-31b-it:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": "Reply with only: PONG"}]}],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 20}
    }
    
    req = urllib.request.Request(
        gen_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            candidate = data.get("candidates", [{}])[0]
            text = candidate.get("content", {}).get("parts", [{}])[0].get("text", "").strip()
            print(f"🤖 Gemma Response: {text}")
            print("\n🎉 Everything is working properly!")
    except Exception as e:
        print(f"⚠️ Inference error: {e}")

if __name__ == "__main__":
    test_api_key()
