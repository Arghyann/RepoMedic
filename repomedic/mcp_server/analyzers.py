"""Deterministic static analysis (Python AST). Cheap, fast evidence that the LLM agents triage.

Each rule is precise enough to be a useful lead and cheap enough to run on every file;
Gemma then decides in context whether a finding is a real problem.
"""
import ast
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from repomedic.mcp_server.sandbox import Sandbox

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
SEVERITY_PENALTY = {"critical": 15, "high": 8, "medium": 3, "low": 1}

RULES = {
    "RM001": ("SQL query built with string formatting (SQL injection)", "critical", "security"),
    "RM002": ("Mutable default argument shared across calls", "high", "bug"),
    "RM003": ("Bare `except:` swallows every error, including KeyboardInterrupt", "medium", "reliability"),
    "RM004": ("Exception silently swallowed", "medium", "reliability"),
    "RM005": ("Timezone-naive datetime", "medium", "bug"),
    "RM006": ("Weak hash algorithm (MD5/SHA1) used", "high", "security"),
    "RM007": ("Hardcoded secret or credential", "high", "security"),
    "RM008": ("Dangerous dynamic execution / deserialization", "high", "security"),
    "RM009": ("Shell command execution with shell=True", "high", "security"),
    "RM010": ("Database query inside a loop (N+1 pattern)", "medium", "performance"),
    "RM011": ("Network call without a timeout", "medium", "reliability"),
    "RM012": ("`assert` used for runtime validation (stripped with -O)", "low", "reliability"),
    "RM013": ("Function too complex (high cyclomatic complexity)", "medium", "maintainability"),
    "RM014": ("Function too long", "low", "maintainability"),
    "RM015": ("Comparing secrets with == (timing attack)", "medium", "security"),
}

SQL_RE = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE|REPLACE|CREATE|DROP|ALTER)\b", re.I)
SECRET_NAME_RE = re.compile(
    r"(secret|secret_?key|signing_?key|passw(or)?d|pwd|api_?key|access_?key|auth_?token|private_?key|token)$", re.I
)
QUERY_METHODS = {"execute", "executemany", "executescript", "raw", "fetch", "fetchrow", "fetchval"}
NETWORK_FUNCS = {
    ("requests", "get"), ("requests", "post"), ("requests", "put"), ("requests", "patch"),
    ("requests", "delete"), ("requests", "head"), ("requests", "request"),
    ("httpx", "get"), ("httpx", "post"), ("httpx", "put"), ("httpx", "patch"), ("httpx", "delete"),
    ("request", "urlopen"), ("urllib.request", "urlopen"),
}


@dataclass
class Finding:
    rule: str
    title: str
    severity: str
    category: str
    file: str
    line: int
    message: str
    snippet: str = ""
    symbol: str = ""

    def to_dict(self):
        return asdict(self)


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Call):
        return _dotted(node.func)
    return ""


def _literal_text(node: ast.AST) -> str:
    """Concatenate the literal string parts of an expression."""
    parts = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            parts.append(sub.value)
    return " ".join(parts)


def _is_dynamic_string(node: ast.AST) -> bool:
    if isinstance(node, ast.JoinedStr):
        return any(isinstance(v, ast.FormattedValue) for v in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
        return isinstance(node.left, (ast.Constant, ast.JoinedStr, ast.BinOp)) and bool(_literal_text(node))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format":
        return isinstance(node.func.value, ast.Constant)
    return False


def _complexity(func: ast.AST) -> int:
    score = 1
    for node in ast.walk(func):
        if isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.IfExp, ast.ExceptHandler, ast.With, ast.AsyncWith)):
            score += 1
        elif isinstance(node, ast.BoolOp):
            score += len(node.values) - 1
        elif isinstance(node, ast.comprehension):
            score += 1 + len(node.ifs)
        elif isinstance(node, ast.match_case):
            score += 1
    return score


class _Visitor(ast.NodeVisitor):
    def __init__(self, rel: str, lines: list[str], is_test: bool):
        self.rel = rel
        self.lines = lines
        self.is_test = is_test
        self.findings: list[Finding] = []
        self.loop_depth = 0
        self.func_stack: list[str] = []
        self.sql_vars: list[dict[str, int]] = [{}]

    # -- helpers -----------------------------------------------------------
    def add(self, rule: str, node: ast.AST, message: str, severity: str | None = None):
        title, default_sev, category = RULES[rule]
        line = getattr(node, "lineno", 1)
        snippet = self.lines[line - 1].strip() if 0 < line <= len(self.lines) else ""
        sev = severity or default_sev
        if self.is_test and category == "security":
            sev = "low"
        self.findings.append(Finding(rule, title, sev, category, self.rel, line, message, snippet[:200],
                                     ".".join(self.func_stack)))

    # -- scopes ------------------------------------------------------------
    def _visit_function(self, node):
        args = node.args
        defaults = list(args.defaults) + [d for d in args.kw_defaults if d is not None]
        for default in defaults:
            if isinstance(default, (ast.List, ast.Dict, ast.Set)) or (
                isinstance(default, ast.Call) and _dotted(default.func) in {"list", "dict", "set", "defaultdict"}
            ):
                self.add("RM002", default, f"`{node.name}` uses a mutable default; it is created once and shared by every call. Use None and create it inside the function.")
        if not self.is_test:
            cc = _complexity(node)
            if cc > 12:
                self.add("RM013", node, f"`{node.name}` has cyclomatic complexity {cc} (> 12). Split it into smaller functions.")
            length = (getattr(node, "end_lineno", node.lineno) or node.lineno) - node.lineno + 1
            if length > 80:
                self.add("RM014", node, f"`{node.name}` is {length} lines long (> 80).")
        self.func_stack.append(node.name)
        self.sql_vars.append({})
        saved_depth, self.loop_depth = self.loop_depth, 0
        self.generic_visit(node)
        self.loop_depth = saved_depth
        self.sql_vars.pop()
        self.func_stack.pop()

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function

    def _visit_loop(self, node):
        self.loop_depth += 1
        self.generic_visit(node)
        self.loop_depth -= 1

    visit_For = _visit_loop
    visit_AsyncFor = _visit_loop
    visit_While = _visit_loop

    # -- statements ----------------------------------------------------------
    def visit_Assign(self, node: ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name):
                if _is_dynamic_string(node.value) and SQL_RE.search(_literal_text(node.value)):
                    self.sql_vars[-1][target.id] = node.lineno
                if (
                    SECRET_NAME_RE.search(target.id)
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)
                    and len(node.value.value) >= 6
                    and not self.is_test
                ):
                    self.add("RM007", node, f"`{target.id}` is hardcoded in source. Load it from the environment or a secret manager.")
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler):
        if node.type is None:
            self.add("RM003", node, "Catch specific exceptions (e.g. `except sqlite3.Error:`) and log them.")
        elif all(isinstance(s, (ast.Pass, ast.Continue)) or (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant)) for s in node.body):
            self.add("RM004", node, "The exception is caught and ignored; failures become invisible.")
        self.generic_visit(node)

    def visit_Assert(self, node: ast.Assert):
        if not self.is_test:
            self.add("RM012", node, "Raise an explicit exception instead; asserts disappear under `python -O`.")
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare):
        if any(isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops):
            names = [_dotted(n).lower() for n in [node.left, *node.comparators]]
            if any(re.search(r"(hash|token|signature|digest|secret)", n) for n in names if n) and not self.is_test:
                self.add("RM015", node, "Use `hmac.compare_digest` for constant-time comparison of secrets.")
        self.generic_visit(node)

    # -- calls ---------------------------------------------------------------
    def visit_Call(self, node: ast.Call):
        name = _dotted(node.func)
        short = name.rsplit(".", 1)[-1]
        kwargs = {kw.arg for kw in node.keywords if kw.arg}

        if short in QUERY_METHODS and node.args:
            arg = node.args[0]
            if _is_dynamic_string(arg) and SQL_RE.search(_literal_text(arg)):
                self.add("RM001", node, "User data is interpolated into SQL. Use parameter placeholders (`?`/`%s`) and pass values separately.")
            elif isinstance(arg, ast.Name):
                for scope in reversed(self.sql_vars):
                    if arg.id in scope:
                        self.add("RM001", node, f"`{arg.id}` (built with string formatting on line {scope[arg.id]}) is executed as SQL. Use parameter placeholders.")
                        break
            if self.loop_depth > 0 and short in {"execute", "fetch", "fetchrow", "fetchval"}:
                self.add("RM010", node, "A query runs once per loop iteration. Batch it (`WHERE id IN (...)`) or join.")

        if name in {"datetime.now", "datetime.datetime.now"} and not node.args and "tz" not in kwargs:
            self.add("RM005", node, "`datetime.now()` without tz returns a naive datetime; comparing it with aware datetimes raises TypeError. Use `datetime.now(timezone.utc)`.")
        elif name in {"datetime.utcnow", "datetime.datetime.utcnow"}:
            self.add("RM005", node, "`utcnow()` returns a naive datetime and is deprecated. Use `datetime.now(timezone.utc)`.")

        if name in {"hashlib.md5", "hashlib.sha1", "md5", "sha1"} and "usedforsecurity" not in kwargs:
            self.add("RM006", node, "MD5/SHA1 are broken for security use. For passwords use bcrypt/argon2/`hashlib.scrypt`.")
        elif name == "hashlib.new" and node.args and isinstance(node.args[0], ast.Constant) and str(node.args[0].value).lower() in {"md5", "sha1"}:
            self.add("RM006", node, "MD5/SHA1 are broken for security use.")

        if name in {"eval", "exec"} and not self.is_test:
            self.add("RM008", node, f"`{name}` executes arbitrary code.")
        elif name in {"pickle.loads", "pickle.load", "marshal.loads"}:
            self.add("RM008", node, "Unpickling untrusted data executes arbitrary code.")
        elif name in {"yaml.load"} and "Loader" not in kwargs:
            self.add("RM008", node, "`yaml.load` without a safe Loader can construct arbitrary objects. Use `yaml.safe_load`.")

        if name.startswith("subprocess.") and any(
            kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True for kw in node.keywords
        ):
            self.add("RM009", node, "shell=True with interpolated input enables command injection. Pass an argument list.")
        elif name in {"os.system", "os.popen"}:
            self.add("RM009", node, f"`{name}` runs through the shell. Use subprocess with an argument list.", severity="medium")

        parts = name.rsplit(".", 1)
        if len(parts) == 2 and (parts[0], parts[1]) in NETWORK_FUNCS and "timeout" not in kwargs:
            self.add("RM011", node, "Without a timeout a slow upstream can hang this worker forever.")
        elif name == "urlopen" and "timeout" not in kwargs and len(node.args) < 3:
            self.add("RM011", node, "Without a timeout a slow upstream can hang this worker forever.")

        self.generic_visit(node)


def analyze_source(source: str, rel: str) -> list[Finding]:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [Finding("RM000", "Syntax error", "critical", "bug", rel, exc.lineno or 1, str(exc))]
    parts = Path(rel).parts
    is_test = any(p in {"tests", "test"} for p in parts) or Path(rel).name.startswith("test_") or Path(rel).name == "conftest.py"
    visitor = _Visitor(rel, source.splitlines(), is_test)
    visitor.visit(tree)
    return visitor.findings


def scan(sandbox: Sandbox, path: str = ".") -> list[Finding]:
    target = sandbox.resolve(path)
    files = [target] if target.is_file() else [
        p for p in sandbox.iter_files("*.py") if target in p.parents or p == target
    ]
    findings: list[Finding] = []
    for file in files:
        if sandbox.is_text(file):
            findings.extend(analyze_source(sandbox.read_text(file), sandbox.rel(file)))
    findings.sort(key=lambda f: (SEVERITY_ORDER.get(f.severity, 9), f.file, f.line))
    return findings


def health_score(findings: list[dict]) -> int:
    penalty = sum(SEVERITY_PENALTY.get(f["severity"], 0) for f in findings)
    return max(0, 100 - penalty)
