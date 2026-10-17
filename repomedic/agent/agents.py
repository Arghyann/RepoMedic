"""The tool-using agent loop.

Gemma 4 gets the MCP tools as native function definitions. If the model stops producing tool
calls (or REPOMEDIC_TOOL_MODE=json), the loop transparently switches to grammar-constrained JSON
actions, which work with any Ollama model — including Gemma 3, which has no native tool calling.
"""
import json
from dataclasses import dataclass
from typing import Awaitable, Callable

from repomedic.agent import prompts
from repomedic.agent.llm import LLMError, OllamaLLM, extract_json
from repomedic.agent.toolbox import Emit, Toolbox
from repomedic.config import Settings

OBS_LIMIT = 3500
OLD_OBS_LIMIT = 500

Validator = Callable[[dict], Awaitable[str | None]]


@dataclass
class AgentContext:
    llm: OllamaLLM
    toolbox: Toolbox
    settings: Settings
    emit: Emit


async def _no_validation(_args: dict) -> str | None:
    return None


def _compact(messages: list[dict], keep_last: int = 4) -> None:
    """Shrink old tool observations so long investigations fit a small context window."""
    obs_idx = [i for i, m in enumerate(messages) if m["role"] == "tool" or m.get("_obs")]
    for i in obs_idx[:-keep_last]:
        content = messages[i]["content"]
        if len(content) > OLD_OBS_LIMIT:
            messages[i]["content"] = content[:OLD_OBS_LIMIT] + "\n... [older output truncated]"


def _clean(messages: list[dict]) -> list[dict]:
    return [{k: v for k, v in m.items() if not k.startswith("_")} for m in messages]


async def run_tool_agent(
    ctx: AgentContext,
    *,
    agent: str,
    system: str,
    task: str,
    tools: list[str],
    finish_hint: str,
    finish_schema: dict,
    max_steps: int,
    validate: Validator = _no_validation,
) -> dict | None:
    tools = [t for t in tools if t in ctx.toolbox.tools]
    native = ctx.settings.tool_mode != "json"
    seen: set[str] = set()
    transcript: list[str] = []
    misses = 0

    def json_messages() -> list[dict]:
        protocol = prompts.JSON_PROTOCOL.format(tools=ctx.toolbox.describe(tools), finish_hint=finish_hint)
        content = task
        if transcript:
            content += "\n\nWhat you found so far:\n" + "\n\n".join(transcript)[-6000:]
        return [{"role": "system", "content": system.format(steps=max_steps, protocol=protocol)},
                {"role": "user", "content": content}]

    def native_messages() -> list[dict]:
        return [{"role": "system", "content": system.format(steps=max_steps, protocol=prompts.NATIVE_PROTOCOL)},
                {"role": "user", "content": task}]

    messages = native_messages() if native else json_messages()
    finish_tool = {"type": "function", "function": {
        "name": "finish", "description": "Submit your final answer. Arguments: " + finish_hint,
        "parameters": finish_schema}}

    async def execute(name: str, args: dict) -> str:
        if name not in tools:
            return f"ERROR: '{name}' is not available. Use one of: {', '.join(tools)} or finish."
        key = name + json.dumps(args, sort_keys=True)
        if key in seen:
            return "You already made this exact call; its result is above. Try something different or finish."
        seen.add(key)
        result = await ctx.toolbox.call(name, args, agent=agent)
        text = result.text if len(result.text) <= OBS_LIMIT else result.text[:OBS_LIMIT] + "\n... [truncated]"
        transcript.append(f"{name}({json.dumps(args)[:200]}) ->\n{text[:1200]}")
        return text

    for step in range(1, max_steps + 2):
        last = step > max_steps
        _compact(messages)
        if last:
            messages.append({"role": "user", "content": "Tool budget exhausted. Call finish now with your best answer.", "_obs": False})

        if native:
            specs = ([] if last else ctx.toolbox.ollama_tools(tools)) + [finish_tool]
            try:
                reply = await ctx.llm.chat(_clean(messages), tools=specs)
            except LLMError as exc:
                if "does not support tools" in str(exc):
                    ctx.emit({"type": "log", "agent": agent, "level": "warn",
                              "message": "Model has no native tool calling; switching to grammar-constrained JSON actions."})
                    native, messages = False, json_messages()
                    continue
                raise
            thought = (reply.thinking or reply.content).strip()
            calls = reply.tool_calls
            if not calls and reply.content:
                try:
                    data = extract_json(reply.content)
                    name = data.get("action") or data.get("name")
                    if name:
                        calls = [{"name": name, "arguments": data.get("args") or data.get("arguments") or {}}]
                        thought = data.get("thought", thought)
                except LLMError:
                    pass
            if thought:
                ctx.emit({"type": "thought", "agent": agent, "step": step, "text": thought[:1500]})
            if not calls:
                misses += 1
                if misses >= 2:
                    ctx.emit({"type": "log", "agent": agent, "level": "warn",
                              "message": "Native tool calls not produced; falling back to grammar-constrained JSON actions."})
                    native, messages = False, json_messages()
                    continue
                messages.append({"role": "assistant", "content": reply.content})
                messages.append({"role": "user", "content": "Call one of the tools, or call finish when you are done."})
                continue
            messages.append({"role": "assistant", "content": reply.content,
                             "tool_calls": [{"function": {"name": c["name"], "arguments": c["arguments"]}} for c in calls]})
            for call in calls:
                if call["name"] == "finish":
                    error = await validate(call["arguments"])
                    if error is None:
                        return call["arguments"]
                    messages.append({"role": "tool", "tool_name": "finish", "content": f"Rejected: {error}"})
                else:
                    text = await execute(call["name"], call["arguments"])
                    messages.append({"role": "tool", "tool_name": call["name"], "content": text})
        else:
            schema = prompts.action_schema([] if last else tools)
            data = await ctx.llm.json(_clean(messages), schema)
            action, args = data.get("action", ""), data.get("args") or {}
            if data.get("thought"):
                ctx.emit({"type": "thought", "agent": agent, "step": step, "text": str(data["thought"])[:1500]})
            messages.append({"role": "assistant", "content": json.dumps(data)})
            if action == "finish":
                error = await validate(args)
                if error is None:
                    return args
                messages.append({"role": "user", "content": f"finish rejected: {error}. Fix it and call finish again.", "_obs": True})
            else:
                text = await execute(action, args)
                messages.append({"role": "user", "content": f"Observation from {action}:\n{text}", "_obs": True})
    return None
