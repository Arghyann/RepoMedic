"""Ollama client for Gemma: native function calling plus grammar-constrained JSON output."""
import json
import re
from dataclasses import dataclass, field

import httpx

from repomedic.config import Settings


class LLMError(RuntimeError):
    pass


@dataclass
class LLMReply:
    content: str = ""
    thinking: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    raw_message: dict = field(default_factory=dict)


@dataclass
class Usage:
    calls: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    gen_seconds: float = 0.0

    @property
    def tokens_per_second(self) -> float:
        return round(self.output_tokens / self.gen_seconds, 1) if self.gen_seconds else 0.0

    def to_dict(self) -> dict:
        return {"calls": self.calls, "prompt_tokens": self.prompt_tokens, "output_tokens": self.output_tokens,
                "tokens_per_second": self.tokens_per_second}


def extract_json(text: str):
    """Parse JSON from a model reply, tolerating code fences and surrounding prose."""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                esc = (ch == "\\") and not esc
                if ch == '"' and not esc:
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    raise LLMError(f"Model did not return valid JSON: {text[:200]!r}")


class OllamaLLM:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.model = settings.model
        self.usage = Usage()
        self._client = httpx.AsyncClient(base_url=settings.ollama_host, timeout=settings.request_timeout)

    async def aclose(self):
        await self._client.aclose()

    async def list_models(self) -> list[str]:
        try:
            r = await self._client.get("/api/tags", timeout=10)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMError(
                f"Cannot reach Ollama at {self.settings.ollama_host} ({exc.__class__.__name__}). "
                "Install it from https://ollama.com and run `ollama serve`."
            ) from exc
        return [m["name"] for m in r.json().get("models", [])]

    async def ensure_ready(self) -> None:
        models = await self.list_models()
        wanted = self.model if ":" in self.model else f"{self.model}:latest"
        if wanted not in models and self.model not in models and not self.model.endswith("-cloud"):
            raise LLMError(f"Model '{self.model}' is not pulled. Run: ollama pull {self.model}  (available: {', '.join(models) or 'none'})")

    async def chat(self, messages: list[dict], *, tools: list[dict] | None = None,
                   schema: dict | None = None, temperature: float | None = None) -> LLMReply:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.settings.temperature if temperature is None else temperature,
                "num_ctx": self.settings.num_ctx,
            },
        }
        if tools:
            payload["tools"] = tools
        if schema:
            payload["format"] = schema
        # Send it explicitly: Gemma 4 otherwise thinks by default, which is several times slower.
        payload["think"] = self.settings.think
        try:
            r = await self._client.post("/api/chat", json=payload)
        except httpx.HTTPError as exc:
            raise LLMError(f"Ollama request failed: {exc}") from exc
        if r.status_code == 400 and "think" in payload and "think" in r.text:
            payload.pop("think")
            r = await self._client.post("/api/chat", json=payload)
        if r.status_code != 200:
            raise LLMError(f"Ollama error {r.status_code}: {r.text[:300]}")
        data = r.json()
        self.usage.calls += 1
        self.usage.prompt_tokens += data.get("prompt_eval_count", 0) or 0
        self.usage.output_tokens += data.get("eval_count", 0) or 0
        self.usage.gen_seconds += (data.get("eval_duration", 0) or 0) / 1e9
        msg = data.get("message", {})
        calls = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function", {})
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            calls.append({"name": fn.get("name", ""), "arguments": args or {}})
        return LLMReply(content=msg.get("content", "") or "", thinking=msg.get("thinking", "") or "",
                        tool_calls=calls, raw_message=msg)

    async def json(self, messages: list[dict], schema: dict, retries: int = 1,
                   temperature: float | None = None) -> dict:
        """Grammar-constrained JSON generation (works for any Ollama model, including Gemma 3)."""
        last_err = None
        for _ in range(retries + 1):
            reply = await self.chat(messages, schema=schema, temperature=temperature)
            try:
                data = extract_json(reply.content)
                if isinstance(data, dict):
                    return data
                last_err = LLMError("Expected a JSON object")
            except LLMError as exc:
                last_err = exc
            messages = [*messages, {"role": "assistant", "content": reply.content},
                        {"role": "user", "content": "That was not a valid JSON object matching the schema. Reply with JSON only."}]
        raise last_err
