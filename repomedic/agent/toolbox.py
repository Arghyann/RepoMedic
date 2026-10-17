"""MCP client side: launches the RepoMedic MCP server over stdio and exposes its tools to the agents."""
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from mcp import Client, StdioServerParameters

Emit = Callable[[dict], None]


@dataclass
class ToolResult:
    text: str
    ok: bool

    def json(self):
        return json.loads(self.text)


class Toolbox:
    """Async context manager that owns one MCP session to a repository."""

    def __init__(self, root: str | Path, emit: Emit | None = None, server=None):
        self.root = Path(root).resolve()
        self.emit = emit or (lambda _event: None)
        self.calls = 0
        self.tools: dict = {}
        if server is not None:  # in-process server (tests)
            self._client = Client(server)
        else:
            env = {**os.environ, "PYTHONIOENCODING": "utf-8", "REPOMEDIC_ROOT": str(self.root)}
            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", "repomedic.mcp_server", "--root", str(self.root)],
                env=env,
            )
            self._client = Client(params)

    async def __aenter__(self):
        await self._client.__aenter__()
        self.tools = {t.name: t for t in (await self._client.list_tools()).tools}
        return self

    async def __aexit__(self, *exc):
        return await self._client.__aexit__(*exc)

    async def call(self, name: str, args: dict | None = None, *, agent: str = "System", quiet: bool = False) -> ToolResult:
        args = args or {}
        self.calls += 1
        if not quiet:
            self.emit({"type": "tool_call", "agent": agent, "tool": name, "args": _preview_args(args)})
        if name not in self.tools:
            result = ToolResult(f"ERROR: unknown tool '{name}'. Available: {', '.join(self.tools)}", False)
        else:
            res = await self._client.call_tool(name, args)
            text = "\n".join(getattr(c, "text", "") for c in res.content)
            if res.is_error:
                text = "ERROR: " + text.replace(f"Error executing tool {name}: ", "")
            result = ToolResult(text, not res.is_error)
        if not quiet:
            self.emit({"type": "tool_result", "agent": agent, "tool": name, "ok": result.ok,
                       "preview": result.text[:600]})
        return result

    # -- tool descriptions for the LLM -------------------------------------------------
    def ollama_tools(self, names: list[str]) -> list[dict]:
        out = []
        for name in names:
            t = self.tools[name]
            schema = _clean_schema(t.input_schema)
            out.append({"type": "function", "function": {"name": name, "description": t.description or "", "parameters": schema}})
        return out

    def describe(self, names: list[str]) -> str:
        lines = []
        for name in names:
            t = self.tools[name]
            props = t.input_schema.get("properties", {})
            required = set(t.input_schema.get("required", []))
            params = []
            for pname, spec in props.items():
                typ = spec.get("type", "any")
                params.append(pname + (f": {typ}" if pname in required else f": {typ} = {json.dumps(spec.get('default'))}"))
            desc = (t.description or "").strip().splitlines()[0] if t.description else ""
            lines.append(f"- {name}({', '.join(params)}): {desc}")
        return "\n".join(lines)


def _clean_schema(schema: dict) -> dict:
    schema = json.loads(json.dumps(schema))
    schema.pop("title", None)
    for spec in schema.get("properties", {}).values():
        spec.pop("title", None)
    return schema


def _preview_args(args: dict) -> dict:
    out = {}
    for k, v in args.items():
        if isinstance(v, str) and len(v) > 300:
            v = v[:300] + "…"
        out[k] = v
    return out
