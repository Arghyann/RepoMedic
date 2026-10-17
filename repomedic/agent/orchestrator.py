"""The RepoMedic pipeline: Scout -> Diagnostician -> Surgeon -> Verifier, all talking to the repo over MCP.

    scan      deterministic static + architecture analysis (no LLM, seconds)
    diagnose  scan + Gemma triage of each lead + Gemma bug hunt guided by failing tests
    fix       localize an issue, patch it, verify with tests, retry on failure, commit to a branch
"""
import ast
import json
import re
import time
from collections import Counter

from repomedic.agent import prompts
from repomedic.agent.agents import AgentContext, run_tool_agent
from repomedic.agent.llm import LLMError, OllamaLLM
from repomedic.agent.toolbox import Emit, Toolbox
from repomedic.config import Settings
from repomedic.mcp_server.analyzers import SEVERITY_ORDER, health_score
from repomedic.mcp_server.symbols import symbol_source

STOPWORDS = set("""
the and for that this with from have when what which there their they them then than into only also should would
could does doing done were been being some more most other such very just about after before over under again
further once here where why how all any both each few same own while above below between through during user
users customers customer report reports reported returns return returned instead whole every never always
error errors issue issues bug bugs fails failing failed broken production endpoint endpoints get post put delete
able allowed must need needs using used use make makes shows show seen appear appears already earlier first
""".split())


def _keywords(text: str, limit: int = 8) -> list[str]:
    words = []
    for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", text):
        lw = w.lower()
        if lw not in STOPWORDS and lw not in words:
            words.append(lw)
    return words[:limit]


def _extract_function(source: str, name: str) -> str | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    lines = source.splitlines()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return "\n".join(lines[node.lineno - 1: node.end_lineno])
    return None


def _outline(source: str) -> str:
    """Imports, module-level assignments and def/class signatures: enough context at a fraction of the tokens."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source
    lines = source.splitlines()
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)) or (
                isinstance(node, (ast.Assign, ast.AnnAssign)) and node in tree.body):
            out.append((node.lineno, "\n".join(lines[node.lineno - 1:node.end_lineno])))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body_start = node.body[0].lineno if node.body else node.lineno + 1
            out.append((node.lineno, "\n".join(lines[node.lineno - 1:body_start - 1]).rstrip() + " ..."))
    return "\n".join(text for _, text in sorted(out))


def _error_lines(output: str, limit: int = 25) -> str:
    """The assertion/exception lines from pytest output: what a model needs to correct itself."""
    keep = [ln for ln in output.splitlines()
            if ln.startswith(("E ", "FAILED", "ERROR")) or "Error:" in ln or ln.strip().startswith("assert")]
    return "\n".join(keep[-limit:]) or output[-1500:]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "fix"


class RepoMedic:
    def __init__(self, settings: Settings | None = None, emit: Emit | None = None):
        self.settings = settings or Settings()
        self.emit = emit or (lambda _e: None)

    def stage(self, agent: str, title: str):
        self.emit({"type": "stage", "agent": agent, "title": title})

    def log(self, agent: str, message: str, level: str = "info"):
        self.emit({"type": "log", "agent": agent, "message": message, "level": level})

    # ------------------------------------------------------------------ scout
    async def _scout(self, tb: Toolbox, run_tests: bool = True) -> dict:
        self.stage("Scout", "Mapping the repository")
        overview = (await tb.call("repo_overview", agent="Scout")).json()
        scan = (await tb.call("scan_code", agent="Scout")).json()
        arch = (await tb.call("analyze_architecture", agent="Scout")).json()
        findings = scan["findings"] + arch["findings"]
        findings.sort(key=lambda f: (SEVERITY_ORDER.get(f["severity"], 9), f["file"], f["line"]))
        score = health_score(findings)
        self.emit({
            "type": "findings", "findings": findings, "score": score,
            "architecture": {k: arch[k] for k in ("modules", "cycles", "layer_violations", "hotspots")},
            "edges": arch["edges"],
        })
        tests = None
        if run_tests and overview.get("test_command"):
            self.stage("Verifier", "Running the test suite (baseline)")
            tests = (await tb.call("run_tests", agent="Verifier")).json()
            self.emit({"type": "tests", "agent": "Verifier", "label": "baseline",
                       **{k: v for k, v in tests.items() if k != "output_tail"}})
        return {"overview": overview, "findings": findings, "architecture": arch, "score": score, "tests": tests}

    async def scan(self, root: str) -> dict:
        start = time.time()
        async with Toolbox(root, self.emit) as tb:
            data = await self._scout(tb)
        result = {"type": "result", "mode": "scan", "score": data["score"], "findings": len(data["findings"]),
                  "seconds": round(time.time() - start, 1), "tool_calls": tb.calls}
        self.emit(result)
        return {**data, **result}

    # ------------------------------------------------------------------ diagnose
    async def diagnose(self, root: str) -> dict:
        start = time.time()
        llm = OllamaLLM(self.settings)
        issues: list[dict] = []
        try:
            async with Toolbox(root, self.emit) as tb:
                data = await self._scout(tb)
                try:
                    await llm.ensure_ready()
                except LLMError as exc:
                    self.log("System", f"{exc} — returning the static report only.", "warn")
                    result = self._diagnose_result(data, issues, llm, tb, start, root)
                    self.emit(result)
                    return result
                ctx = AgentContext(llm, tb, self.settings, self.emit)
                issues += await self._triage(ctx, data["findings"])
                issues += await self._hunt(ctx, data)
                result = self._diagnose_result(data, issues, llm, tb, start, root)
                self.emit(result)
                return result
        finally:
            await llm.aclose()

    def _diagnose_result(self, data, issues, llm, tb, start, root) -> dict:
        from repomedic.report import write_report

        report_path = write_report(root, data, issues, self.settings.model)
        return {"type": "result", "mode": "diagnose", "score": data["score"], "issues": issues,
                "findings": len(data["findings"]), "report": str(report_path), "seconds": round(time.time() - start, 1),
                "tool_calls": tb.calls, "llm": llm.usage.to_dict(), "model": self.settings.model}

    async def _triage(self, ctx: AgentContext, findings: list[dict]) -> list[dict]:
        leads = [f for f in findings if f["severity"] in ("critical", "high", "medium")][: self.settings.triage_limit]
        if not leads:
            return []
        self.stage("Diagnostician", f"Triaging {len(leads)} static-analysis leads with {self.settings.model}")
        out = []
        for f in leads:
            window = await ctx.toolbox.call("read_file", {"path": f["file"], "start_line": max(1, f["line"] - 12),
                                                          "end_line": f["line"] + 12}, agent="Diagnostician")
            messages = [
                {"role": "system", "content": prompts.TRIAGE_SYSTEM},
                {"role": "user", "content": (
                    f"Finding {f['rule']} ({f['severity']}): {f['title']}\nAt {f['file']}:{f['line']}\n"
                    f"Analyzer says: {f['message']}\n\nCode:\n{window.text}"
                )},
            ]
            try:
                verdict = await ctx.llm.json(messages, prompts.TRIAGE_SCHEMA)
            except LLMError as exc:
                self.log("Diagnostician", f"Triage failed for {f['file']}:{f['line']}: {exc}", "warn")
                continue
            issue = {
                "source": "static+gemma", "rule": f["rule"], "title": f["title"], "file": f["file"], "line": f["line"],
                "severity": verdict.get("severity", f["severity"]), "category": f["category"],
                "verdict": verdict.get("verdict", "uncertain"), "explanation": verdict.get("explanation", ""),
                "fix": verdict.get("fix", ""),
            }
            self.emit({"type": "issue", **issue})
            out.append(issue)
        return out

    async def _hunt(self, ctx: AgentContext, data: dict) -> list[dict]:
        self.stage("Diagnostician", "Hunting for logic bugs static analysis cannot see")
        tests = data["tests"] or {}
        static = "\n".join(f"- {f['rule']} {f['file']}:{f['line']} {f['title']}" for f in data["findings"][:15])
        task = (
            f"Repository overview:\n{json.dumps(data['overview'], indent=1)[:1500]}\n\n"
            f"Static findings already known (do not repeat them):\n{static or '(none)'}\n\n"
            f"Failing tests ({tests.get('failed', 0)} failed, {tests.get('passed', 0)} passed):\n"
            + "\n".join(f"- {t}" for t in tests.get("failing", [])[:20])
            + f"\n\nTest output (tail):\n{(tests.get('output_tail') or '')[-2500:]}\n\n"
            "Find the most important bugs in the application code. Report each with file and line."
        )

        async def validate(args: dict) -> str | None:
            if not isinstance(args.get("issues"), list):
                return "args must contain an `issues` list"
            return None

        result = await run_tool_agent(
            ctx, agent="Diagnostician", system=prompts.HUNTER_SYSTEM, task=task,
            tools=["read_file", "search_code", "list_files", "git_log", "git_blame"],
            finish_hint=prompts.HUNTER_FINISH, finish_schema=HUNTER_FINISH_SCHEMA,
            max_steps=self.settings.max_hunt_steps, validate=validate,
        )
        out = []
        for raw in (result or {}).get("issues", [])[:10]:
            if not isinstance(raw, dict) or not raw.get("title"):
                continue
            issue = {"source": "gemma-hunt", "rule": "AI", "verdict": "confirmed", "category": "logic",
                     "severity": "medium", "line": 0, "file": "", "explanation": "", "fix": "", **raw}
            self.emit({"type": "issue", **issue})
            out.append(issue)
        return out

    # ------------------------------------------------------------------ fix
    async def fix(self, root: str, issue: str, title: str | None = None) -> dict:
        start = time.time()
        title = title or issue.strip().splitlines()[0][:72]
        llm = OllamaLLM(self.settings)
        try:
            await llm.ensure_ready()
            async with Toolbox(root, self.emit) as tb:
                ctx = AgentContext(llm, tb, self.settings, self.emit)
                result = await self._fix(ctx, issue, title)
                result.update({"type": "result", "mode": "fix", "seconds": round(time.time() - start, 1),
                               "tool_calls": tb.calls, "llm": llm.usage.to_dict(), "model": self.settings.model})
                self.emit(result)
                return result
        finally:
            await llm.aclose()

    async def _fix(self, ctx: AgentContext, issue: str, title: str) -> dict:
        tb = ctx.toolbox
        self.stage("Scout", "Preparing a safe workspace")
        status = (await tb.call("git_status", agent="Scout")).text
        if "not a git repository" in status:
            return {"success": False, "error": "Fix mode needs a git repository (run `git init && git add -A && git commit -m init`)."}
        lines = status.splitlines()
        dirty = [ln for ln in lines[1:] if ln.strip() and not ln.startswith("??")]
        if dirty:
            return {"success": False, "error": "Working tree has uncommitted changes; commit or stash them first."}
        original_branch = lines[0][3:].split("...")[0].strip() if lines and lines[0].startswith("## ") else ""

        baseline = (await tb.call("run_tests", agent="Verifier")).json()
        self.emit({"type": "tests", "agent": "Verifier", "label": "baseline",
                   **{k: v for k, v in baseline.items() if k != "output_tail"}})
        branch = f"repomedic/{_slug(title)}-{int(time.time()) % 100000}"
        await tb.call("git_create_branch", {"name": branch}, agent="Scout")

        # ---- localize ----------------------------------------------------------------
        self.stage("Diagnostician", "Localizing the root cause")
        keywords = _keywords(issue)
        candidates = await self._candidate_files(tb, keywords)
        related_tests = self._related_tests(baseline.get("failing", []), keywords)
        test_context = await self._test_sources(tb, related_tests)
        self.log("Diagnostician", f"Keywords {keywords} -> candidates {[c for c, _ in candidates]}")

        task = (
            f"Issue report:\n{issue}\n\n"
            "Candidate files from keyword search (most relevant first):\n"
            + "\n".join(f"- {path} ({score} hits)" for path, score in candidates)
            + "\n\nFailing tests that look related:\n"
            + ("\n".join(f"- {t}" for t in related_tests) or "(none)")
            + (f"\n\nTheir source:\n{test_context}" if test_context else "")
            + "\n\nFind the application function that causes this issue."
        )

        async def validate_loc(args: dict) -> str | None:
            path = str(args.get("file", "")).strip()
            if not path:
                return "`file` is required"
            check = await tb.call("read_file", {"path": path, "end_line": 1}, quiet=True)
            return None if check.ok else f"file {path!r} does not exist"

        loc = await run_tool_agent(
            ctx, agent="Diagnostician", system=prompts.INVESTIGATOR_SYSTEM, task=task,
            tools=["read_file", "search_code", "list_files", "git_log", "git_blame"],
            finish_hint=prompts.INVESTIGATOR_FINISH, finish_schema=INVESTIGATOR_FINISH_SCHEMA,
            max_steps=self.settings.max_investigate_steps, validate=validate_loc,
        )
        if not loc:
            fallback = next((c for c, _ in candidates if "test" not in c), candidates[0][0] if candidates else "")
            if not fallback:
                return {"success": False, "error": "Could not localize the issue.", "branch": branch}
            loc = {"file": fallback, "root_cause": "Not confirmed; best keyword match.", "symbol": ""}
        self.emit({"type": "diagnosis", "agent": "Diagnostician", **loc})

        # ---- patch + verify loop -----------------------------------------------------
        symbol = re.sub(r"[^\w.]", "", str(loc.get("symbol") or "").split("(")[0])
        guard_tests = await self._tests_exercising(tb, symbol, related_tests)
        guard_context = await self._test_sources(tb, guard_tests) or test_context
        if guard_tests:
            self.log("Surgeon", f"{len(guard_tests)} tests exercise `{symbol or loc['file']}`; all must pass")
        feedback, attempts = "", 0
        before_failing = set(baseline.get("failing", []))
        for attempt in range(1, self.settings.max_attempts + 1):
            attempts = attempt
            self.stage("Surgeon", f"Writing a patch (attempt {attempt}/{self.settings.max_attempts})")
            source = await tb.call("read_file", {"path": loc["file"], "numbered": False}, agent="Surgeon")
            func_src = symbol_source(source.text, symbol) if symbol else None
            messages = [
                {"role": "system", "content": prompts.SURGEON_SYSTEM},
                {"role": "user", "content": (
                    f"Issue:\n{issue}\n\nDiagnosis: {loc.get('root_cause', '')}\n"
                    f"Location: {loc['file']} {symbol} line {loc.get('line', '?')}\n"
                    + (f"\nFunction to fix (`{symbol}` in {loc['file']}):\n```python\n{func_src}\n```\n" if func_src else "")
                    + (f"\nTests that exercise this code (ALL must pass):\n```python\n{guard_context}\n```\n" if guard_context else "")
                    + (f"\nRest of {loc['file']} (outline: imports, constants, signatures):\n```python\n{_outline(source.text)}\n```"
                       if func_src else f"\nFull content of {loc['file']}:\n```python\n{source.text}\n```")
                    + (f"\n\nYour previous attempt failed:\n{feedback}\nWrite a different, correct fix." if feedback else "")
                )},
            ]
            try:  # a little more variety on retries so the model does not repeat its mistake
                plan = await ctx.llm.json(messages, prompts.SURGEON_SCHEMA,
                                          temperature=None if attempt == 1 else 0.5)
            except LLMError as exc:
                feedback = f"Invalid response: {exc}"
                continue
            self.emit({"type": "thought", "agent": "Surgeon", "step": attempt, "text": plan.get("explanation", "")})

            touched, diffs, failed, seen_edits = [], [], None, set()
            imports = [i for i in plan.get("imports") or [] if isinstance(i, str)]
            for edit in plan.get("edits", [])[:6]:
                path = edit.get("path") or loc["file"]
                key = json.dumps([path, edit.get("symbol"), edit.get("new_code"), edit.get("search"), edit.get("replace")])
                if key in seen_edits:  # small models sometimes repeat an edit verbatim
                    continue
                seen_edits.add(key)
                if edit.get("new_code"):
                    res = await tb.call("replace_symbol", {
                        "path": path, "symbol": edit.get("symbol") or symbol,
                        "new_code": edit["new_code"], "imports": imports}, agent="Surgeon")
                    imports = []
                elif edit.get("search"):
                    res = await tb.call("apply_edit", {"path": path, "search": edit["search"],
                                                       "replace": edit.get("replace", "")}, agent="Surgeon")
                else:
                    failed = "Each edit needs either `symbol` + `new_code` or `search` + `replace`."
                    break
                if not res.ok and "produced no change" in res.text and path in touched:
                    continue  # an earlier edit in this patch already made this change
                if not res.ok:
                    failed = (f"Edit to {path} could not be applied: {res.text}\n"
                              "Return the COMPLETE new function with `symbol` and `new_code` instead.")
                    break
                if path not in touched:
                    touched.append(path)
                diffs.append(res.text)
            if not failed and imports and touched:
                res = await tb.call("add_imports", {"path": touched[0], "imports": imports}, agent="Surgeon")
                if res.ok:
                    diffs.append(res.text)
            if failed or not touched:
                feedback = failed or "No edits were produced."
                self.log("Surgeon", feedback.splitlines()[0], "warn")
                await self._revert(tb, touched)
                continue
            diff = "\n".join(diffs)
            self.emit({"type": "patch", "agent": "Surgeon", "attempt": attempt, "diff": diff, "files": touched})

            self.stage("Verifier", "Re-running tests against the patch")
            after = (await tb.call("run_tests", agent="Verifier")).json()
            self.emit({"type": "tests", "agent": "Verifier", "label": f"attempt {attempt}",
                       **{k: v for k, v in after.items() if k != "output_tail"}})
            after_failing = set(after.get("failing", []))
            fixed = sorted(before_failing - after_failing)
            broken = sorted(after_failing - before_failing)
            collection_error = after.get("errors", 0) > baseline.get("errors", 0) or (
                not after.get("ok") and after.get("failed", 0) == 0 and after.get("passed", 0) == 0)
            if broken or collection_error:
                feedback = (f"Your patch:\n{diff[:1500]}\n"
                            + (f"BROKE these tests that passed before: {broken}\n" if broken else "broke test collection.\n")
                            + (f"Their source:\n{await self._test_sources(tb, broken[:3])}\n" if broken else "")
                            + f"Errors:\n{_error_lines(after.get('output_tail', ''))}")
            elif fixed or (not before_failing and after.get("ok")):
                verified = bool(fixed)
                message = (f"fix: {title}\n\n{plan.get('explanation', '')}\n\nRoot cause: {loc.get('root_cause', '')}\n"
                           f"Tests fixed: {', '.join(fixed) or 'n/a (suite green)'}\n\n"
                           f"Generated by RepoMedic with {self.settings.model} (local, via Ollama + MCP)")
                commit = await tb.call("git_commit", {"message": message, "paths": touched}, agent="Verifier")
                return {"success": True, "verified": verified, "branch": branch, "commit": commit.text,
                        "attempts": attempt, "diff": diff, "fixed_tests": fixed, "diagnosis": loc,
                        "explanation": plan.get("explanation", ""), "original_branch": original_branch}
            else:
                feedback = (f"Your patch:\n{diff[:1500]}\napplied cleanly but did NOT fix the failing tests. "
                            f"Errors:\n{_error_lines(after.get('output_tail', ''))}")
            self.log("Verifier", feedback.splitlines()[0], "warn")
            await self._revert(tb, touched)

        if original_branch:
            await tb.call("git_switch", {"name": original_branch}, agent="Verifier")
        return {"success": False, "branch": branch, "attempts": attempts, "diagnosis": loc,
                "error": f"No verified fix after {attempts} attempts. Last feedback: {feedback[:300]}"}

    async def _revert(self, tb: Toolbox, paths: list[str]):
        for p in paths:
            await tb.call("revert_file", {"path": p}, agent="Verifier")

    async def _candidate_files(self, tb: Toolbox, keywords: list[str]) -> list[tuple[str, int]]:
        scores: Counter = Counter()
        for kw in keywords:
            res = await tb.call("search_code", {"query": kw, "max_results": 40}, quiet=True)
            if not res.ok or res.text.startswith("No matches"):
                continue
            per_file = Counter(line.split(":", 1)[0] for line in res.text.splitlines() if ":" in line)
            for path, hits in per_file.items():
                weight = 1 if ("test" in path or not path.endswith(".py")) else 2
                scores[path] += min(hits, 5) * weight
        return scores.most_common(6)

    @staticmethod
    def _related_tests(failing: list[str], keywords: list[str]) -> list[str]:
        scored = []
        for test in failing:
            words = set(re.split(r"[_/.:\-]+", test.lower()))
            overlap = sum(1 for k in keywords if k in words or any(k[:5] == w[:5] for w in words if len(w) > 4))
            if overlap:
                scored.append((overlap, test))
        scored.sort(reverse=True)
        return [t for _, t in scored[:3]]

    async def _tests_exercising(self, tb: Toolbox, symbol: str, first: list[str], limit: int = 6) -> list[str]:
        """Failing tests related to the issue, plus passing tests that call the symbol (they must keep passing)."""
        found = list(first)
        short = symbol.rsplit(".", 1)[-1]
        if not short:
            return found[:limit]
        res = await tb.call("search_code", {"query": short, "pattern": "*test*.py", "max_results": 80}, quiet=True)
        files = sorted({ln.split(":", 1)[0] for ln in res.text.splitlines() if ":" in ln} if res.ok else set())
        word = re.compile(rf"\b{re.escape(short)}\b")
        for path in files:
            src = await tb.call("read_file", {"path": path, "numbered": False}, quiet=True)
            if not src.ok:
                continue
            try:
                tree = ast.parse(src.text)
            except SyntaxError:
                continue
            lines = src.text.splitlines()
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
                    if word.search("\n".join(lines[node.lineno - 1:node.end_lineno])):
                        test_id = f"{path}::{node.name}"
                        if test_id not in found:
                            found.append(test_id)
        return found[:limit]

    async def _test_sources(self, tb: Toolbox, tests: list[str]) -> str:
        chunks = []
        for test in tests:
            path, _, name = test.partition("::")
            res = await tb.call("read_file", {"path": path, "numbered": False}, quiet=True)
            if res.ok:
                fn = _extract_function(res.text, name.split("[")[0])
                if fn:
                    chunks.append(f"# {path}\n{fn}")
        return "\n\n".join(chunks)


INVESTIGATOR_FINISH_SCHEMA = {
    "type": "object",
    "properties": {
        "file": {"type": "string", "description": "Path of the file containing the bug"},
        "symbol": {"type": "string", "description": "Function or class name"},
        "line": {"type": "integer"},
        "root_cause": {"type": "string", "description": "What is wrong and why"},
    },
    "required": ["file", "root_cause"],
}

HUNTER_FINISH_SCHEMA = {
    "type": "object",
    "properties": {
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"}, "file": {"type": "string"}, "line": {"type": "integer"},
                    "severity": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
                    "category": {"type": "string"}, "explanation": {"type": "string"}, "fix": {"type": "string"},
                },
                "required": ["title", "file", "severity", "explanation"],
            },
        }
    },
    "required": ["issues"],
}
