"""RepoMedic MCP server.

Exposes a repository as MCP tools (search, read, static analysis, architecture, git, tests,
safe editing). Works with RepoMedic's own Gemma agents and with any MCP client
(Claude Desktop, VS Code, Cursor, MCP Inspector...).

    python -m repomedic.mcp_server --root path/to/repo
"""
import argparse
import functools
import json
import os
import re
from collections import Counter
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from repomedic.mcp_server import analyzers, architecture, gitops, testing
from repomedic.mcp_server.editing import EditError, apply_search_replace, unified_diff
from repomedic.mcp_server.sandbox import Sandbox
from repomedic.mcp_server.symbols import add_imports as add_imports_in
from repomedic.mcp_server.symbols import replace_symbol as replace_symbol_in

MAX_OUTPUT = 12_000

server = MCPServer(
    "repomedic",
    instructions=(
        "Tools for diagnosing and repairing a code repository. Paths are relative to the repository root. "
        "Start with repo_overview, use scan_code/analyze_architecture for leads, read_file/search_code to "
        "confirm, apply_edit to change code, and run_tests to verify."
    ),
    log_level="WARNING",
)

_sandbox: Sandbox | None = None


def sandbox() -> Sandbox:
    global _sandbox
    if _sandbox is None:
        _sandbox = Sandbox(os.environ.get("REPOMEDIC_ROOT", os.getcwd()))
    return _sandbox


def set_root(root: str) -> None:
    global _sandbox
    _sandbox = Sandbox(root)


def _clip(text: str, limit: int = MAX_OUTPUT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated {len(text) - limit} chars]"


def tool(fn):
    """Register a tool and turn expected failures into clean MCP tool errors."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ToolError:
            raise
        except (PermissionError, FileNotFoundError, IsADirectoryError, EditError, ValueError) as exc:
            raise ToolError(str(exc)) from exc

    return server.tool()(wrapper)


# --------------------------------------------------------------------------- exploration
@tool
def repo_overview() -> str:
    """Summarize the repository: languages, size, top-level layout, test command, git state, recent commits."""
    sb = sandbox()
    langs, total = Counter(), 0
    for p in sb.iter_files("*"):
        total += 1
        if p.suffix:
            langs[p.suffix] += 1
    top = sorted(
        (p.name + ("/" if p.is_dir() else "")) for p in sb.root.iterdir()
        if p.name not in {".git", ".venv", "venv", "node_modules", "__pycache__"}
    )
    cmd = testing.detect_command(sb.root)
    info = {
        "root": sb.root.name,
        "files": total,
        "languages": dict(langs.most_common(8)),
        "top_level": top[:40],
        "test_command": " ".join(cmd) if cmd else None,
        "git": None,
    }
    if gitops.is_repo(sb.root):
        _, branch = gitops.git(sb.root, "branch", "--show-current")
        _, status = gitops.git(sb.root, "status", "--porcelain")
        _, log = gitops.git(sb.root, "log", "--oneline", "-5")
        info["git"] = {"branch": branch, "dirty_files": len(status.splitlines()), "recent_commits": log.splitlines()}
    return json.dumps(info, indent=2)


@tool
def list_files(pattern: str = "*", limit: int = 200) -> str:
    """List repository files matching a glob (e.g. '*.py', 'src/*'). `*` matches across directories."""
    sb = sandbox()
    files = [sb.rel(p) for p in sb.iter_files(pattern)]
    out = "\n".join(files[:limit])
    if len(files) > limit:
        out += f"\n... and {len(files) - limit} more"
    return out or "(no files match)"


@tool
def read_file(path: str, start_line: int = 1, end_line: int = 0, numbered: bool = True) -> str:
    """Read a text file (optionally a line range). With numbered=true each line is prefixed with its line number."""
    sb = sandbox()
    p = sb.resolve(path)
    if not p.is_file():
        raise FileNotFoundError(f"No such file: {path}")
    if not sb.is_text(p):
        raise ValueError(f"{path} is binary or too large to read")
    lines = sb.read_text(p).splitlines()
    start = max(1, start_line)
    end = len(lines) if end_line <= 0 else min(len(lines), end_line)
    chunk = lines[start - 1:end]
    if numbered:
        width = len(str(end))
        body = "\n".join(f"{i:>{width}} | {ln}" for i, ln in enumerate(chunk, start))
        return _clip(f"# {path} (lines {start}-{end} of {len(lines)})\n{body}")
    return _clip("\n".join(chunk))


@tool
def search_code(query: str, pattern: str = "*", regex: bool = False, max_results: int = 60) -> str:
    """Search file contents for text (or a regex). Returns `path:line: text` matches."""
    sb = sandbox()
    try:
        rx = re.compile(query if regex else re.escape(query), re.I)
    except re.error as exc:
        raise ValueError(f"Invalid regex: {exc}") from exc
    hits = []
    for p in sb.iter_files(pattern):
        if not sb.is_text(p):
            continue
        for i, line in enumerate(sb.read_text(p).splitlines(), 1):
            if rx.search(line):
                hits.append(f"{sb.rel(p)}:{i}: {line.strip()[:200]}")
                if len(hits) >= max_results:
                    return "\n".join(hits) + "\n... (more results truncated)"
    return "\n".join(hits) or f"No matches for {query!r}"


# --------------------------------------------------------------------------- analysis
@tool
def scan_code(path: str = ".") -> str:
    """Run RepoMedic's static analyzers (security, bugs, reliability, performance, maintainability) on a file or directory."""
    findings = [f.to_dict() for f in analyzers.scan(sandbox(), path)]
    return json.dumps({"count": len(findings), "findings": findings}, indent=1)


@tool
def analyze_architecture() -> str:
    """Build the internal import graph and report circular dependencies, layering violations, god modules and hotspots."""
    return json.dumps(architecture.analyze(sandbox()), indent=1)


# --------------------------------------------------------------------------- git
@tool
def git_status() -> str:
    """Show the current branch and changed files."""
    _, out = gitops.git(sandbox().root, "status", "--short", "--branch")
    return out or "clean"


@tool
def git_diff(path: str = "", staged: bool = False) -> str:
    """Show the uncommitted diff (optionally for one path)."""
    sb = sandbox()
    args = ["diff", "--no-color"] + (["--staged"] if staged else [])
    if path:
        args += ["--", sb.rel(sb.resolve(path))]
    _, out = gitops.git(sb.root, *args)
    return _clip(out) or "(no changes)"


@tool
def git_log(limit: int = 10, path: str = "") -> str:
    """Show recent commits (optionally only those touching a path)."""
    sb = sandbox()
    args = ["log", f"-{max(1, min(limit, 50))}", "--pretty=format:%h %ad %an: %s", "--date=short"]
    if path:
        args += ["--", sb.rel(sb.resolve(path))]
    _, out = gitops.git(sb.root, *args)
    return out or "(no commits)"


@tool
def git_blame(path: str, start_line: int, end_line: int) -> str:
    """Show who last changed each line in a range — useful to find the commit that introduced a bug."""
    sb = sandbox()
    rel = sb.rel(sb.resolve(path))
    _, out = gitops.git(sb.root, "blame", "-s", "-L", f"{start_line},{end_line}", "--", rel)
    return _clip(out)


@tool
def git_create_branch(name: str) -> str:
    """Create and switch to a new branch for fixes (never edits the user's current branch)."""
    if not re.fullmatch(r"[A-Za-z0-9._/-]{1,100}", name):
        raise ValueError("Invalid branch name")
    code, out = gitops.git(sandbox().root, "checkout", "-b", name)
    if code != 0:
        raise ValueError(out)
    return f"Switched to new branch {name}"


@tool
def git_switch(name: str) -> str:
    """Switch to an existing branch."""
    code, out = gitops.git(sandbox().root, "checkout", name)
    if code != 0:
        raise ValueError(out)
    return f"Switched to branch {name}"


@tool
def git_commit(message: str, paths: list[str]) -> str:
    """Stage the given paths and commit them as the RepoMedic bot."""
    sb = sandbox()
    rels = [sb.rel(sb.resolve(p)) for p in paths]
    if not rels:
        raise ValueError("No paths to commit")
    code, out = gitops.git(sb.root, "add", "--", *rels)
    if code != 0:
        raise ValueError(out)
    code, out = gitops.git(sb.root, *gitops.BOT_IDENTITY, "commit", "-m", message)
    if code != 0:
        raise ValueError(out)
    _, sha = gitops.git(sb.root, "rev-parse", "--short", "HEAD")
    return f"Committed {sha}: {message.splitlines()[0]}"


# --------------------------------------------------------------------------- tests & edits
@tool
def run_tests(target: str = "", timeout: int = 180) -> str:
    """Run the project's test suite (or a target like 'tests/test_api.py'). Returns counts, failing tests and output tail."""
    result = testing.run(sandbox().root, target, timeout)
    output = result.pop("output")
    result["output_tail"] = output[-4000:]
    return json.dumps(result, indent=1)


@tool
def apply_edit(path: str, search: str, replace: str) -> str:
    """Replace one exact snippet of code in a file. `search` must match existing code exactly once.
    Python edits are syntax-checked before writing. Use an empty `search` only to create a new file."""
    sb = sandbox()
    p = sb.resolve(path)
    if not search:
        if p.exists():
            raise EditError("File exists; provide `search` text to replace.")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(replace, encoding="utf-8")
        return unified_diff("", replace, sb.rel(p))
    if not p.is_file():
        raise FileNotFoundError(f"No such file: {path}")
    raw = p.read_bytes().decode("utf-8", errors="replace")
    after = apply_search_replace(raw, search, replace)
    if after == raw:
        raise EditError("Edit produced no change.")
    if p.suffix == ".py":
        try:
            compile(after, path, "exec")
        except SyntaxError as exc:
            raise EditError(f"Edit rejected: it would introduce a SyntaxError at line {exc.lineno}: {exc.msg}") from exc
    with open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write(after)
    return unified_diff(raw, after, sb.rel(p))


def _write_python(path: str, transform) -> str:
    sb = sandbox()
    p = sb.resolve(path)
    if not p.is_file():
        raise FileNotFoundError(f"No such file: {path}")
    raw = p.read_bytes().decode("utf-8", errors="replace")
    after = transform(raw)
    if after == raw:
        raise EditError("Edit produced no change.")
    try:
        compile(after, path, "exec")
    except SyntaxError as exc:
        raise EditError(f"Edit rejected: it would introduce a SyntaxError at line {exc.lineno}: {exc.msg}") from exc
    with open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write(after)
    return unified_diff(raw, after, sb.rel(p))


@tool
def replace_symbol(path: str, symbol: str, new_code: str, imports: list[str] | None = None) -> str:
    """Replace a whole Python function or class (e.g. 'list_products' or 'Cart.add') with `new_code`,
    the complete new definition. Optional `imports` lines are added if missing. Syntax-checked before writing."""
    def transform(text: str) -> str:
        text = replace_symbol_in(text, symbol, new_code)
        return add_imports_in(text, imports) if imports else text

    return _write_python(path, transform)


@tool
def add_imports(path: str, imports: list[str]) -> str:
    """Add import lines (e.g. 'from shop.errors import OutOfStock') to a Python file if they are missing."""
    return _write_python(path, lambda text: add_imports_in(text, imports))


@tool
def revert_file(path: str) -> str:
    """Discard uncommitted changes to a file (git checkout)."""
    sb = sandbox()
    rel = sb.rel(sb.resolve(path))
    if gitops.is_tracked(sb.root, rel):
        code, out = gitops.git(sb.root, "checkout", "--", rel)
        if code != 0:
            raise ValueError(out)
        return f"Reverted {rel}"
    p = sb.resolve(rel)
    if p.exists():
        p.unlink()
        return f"Removed untracked file {rel}"
    return f"{rel} unchanged"


# --------------------------------------------------------------------------- prompts
@server.prompt()
def diagnose_repository() -> str:
    """A ready-made prompt for MCP clients: full health check of the repository."""
    return (
        "Diagnose this repository. 1) Call repo_overview. 2) Call scan_code and analyze_architecture. "
        "3) Call run_tests to see what is failing. 4) Use read_file/search_code to confirm the most severe leads. "
        "Report a ranked list of real problems with file:line, why it matters, and a concrete fix."
    )


@server.prompt()
def fix_issue(issue: str) -> str:
    """A ready-made prompt for MCP clients: fix a bug report with test verification."""
    return (
        f"Fix this issue:\n\n{issue}\n\nLocate the root cause with search_code/read_file, make the smallest "
        "correct change with apply_edit, then run_tests. If tests regress, revert_file and try again."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="RepoMedic MCP server (stdio)")
    parser.add_argument("--root", default=os.environ.get("REPOMEDIC_ROOT", os.getcwd()),
                        help="Repository root to expose")
    args = parser.parse_args()
    set_root(str(Path(args.root).resolve()))
    server.run()


if __name__ == "__main__":
    main()
