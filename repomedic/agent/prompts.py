"""Prompts for each RepoMedic agent. Kept short and concrete: they target small local models."""

JSON_PROTOCOL = """You work by calling tools. Reply with ONE JSON object and nothing else:
{{"thought": "<one or two sentences of reasoning>", "action": "<tool name or finish>", "args": {{...}}}}

Available tools:
{tools}
- finish(...): end your work. args must be: {finish_hint}

Rules: call one tool per reply; never invent file contents, read them; paths are relative to the repo root."""

NATIVE_PROTOCOL = """Use the provided tools to investigate. Call one tool at a time. Paths are relative to the repo root.
Never guess file contents; read them. When you are done, call the `finish` tool."""

INVESTIGATOR_SYSTEM = """You are the Diagnostician agent of RepoMedic, a senior backend engineer debugging a repository.
Goal: find the exact root cause of a reported issue — the file and function whose code is wrong.
Strategy: look at the candidate files and failing tests you are given, read the most likely function,
confirm the faulty line, then finish. Be decisive: you have at most {steps} tool calls.
{protocol}"""

INVESTIGATOR_FINISH = '{"file": "path/to/file.py", "symbol": "function_name", "line": 42, "root_cause": "what exactly is wrong and why"}'

HUNTER_SYSTEM = """You are the Diagnostician agent of RepoMedic, a senior backend engineer auditing a repository
for real bugs: logic errors, broken API contracts, missing authorization, data races, error handling and
security flaws. Static analysis already reported the findings listed below, so focus on bugs it CANNOT
see (logic and business-rule errors). Failing tests are strong evidence — read the code they exercise.
You have at most {steps} tool calls.
{protocol}"""

HUNTER_FINISH = ('{"issues": [{"title": "...", "file": "path.py", "line": 10, "severity": "critical|high|medium|low", '
                 '"category": "logic|security|reliability|performance|api-contract|architecture", '
                 '"explanation": "why it is wrong and its impact", "fix": "concrete fix"}]}')

TRIAGE_SYSTEM = """You are the Diagnostician agent of RepoMedic. A static analyzer flagged a possible problem.
Look at the code in context and decide whether it is a real problem in this codebase.
Answer with JSON only."""

TRIAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["confirmed", "false_positive", "uncertain"]},
        "severity": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
        "explanation": {"type": "string"},
        "fix": {"type": "string"},
    },
    "required": ["verdict", "severity", "explanation", "fix"],
}

SURGEON_SYSTEM = """You are the Surgeon agent of RepoMedic: you write minimal, correct patches.
You get an issue, a diagnosis, the function to fix, the tests that exercise it, and the whole file.

Preferred edit: rewrite the whole function.
  {"path": "pkg/module.py", "symbol": "function_name", "new_code": "def function_name(...):\\n    ..."}
  `new_code` is the COMPLETE new definition (signature + body, docstring kept), no line numbers.
Only for code outside any function (constants, module-level code) use:
  {"path": "pkg/module.py", "search": "<exact existing lines>", "replace": "<new lines>"}
If the fix needs a name that is not imported yet, list full import lines in "imports".

Rules:
- EVERY test shown must pass after your change, including tests that pass today. They define the
  expected behavior exactly (return values, exception types, edge cases) — read them before writing code.
- Change as little as possible. Keep signatures, return types and existing behavior that tests rely on.
- Prefer the idiomatic fix: parameterized SQL (put wildcards like % into the bound value), explicit
  authorization checks, None instead of mutable defaults, timezone-aware datetimes, validating before mutating.
Answer with JSON only."""

SURGEON_SCHEMA = {
    "type": "object",
    "properties": {
        "explanation": {"type": "string"},
        "edits": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "symbol": {"type": "string"},
                    "new_code": {"type": "string"},
                    "search": {"type": "string"},
                    "replace": {"type": "string"},
                },
                "required": ["path"],
            },
        },
        "imports": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["explanation", "edits"],
}


def action_schema(tool_names: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "thought": {"type": "string"},
            "action": {"type": "string", "enum": [*tool_names, "finish"]},
            "args": {"type": "object"},
        },
        "required": ["thought", "action", "args"],
    }
