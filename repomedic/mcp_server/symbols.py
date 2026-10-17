"""Replace a whole function/class by name using the AST.

Small models are far more reliable at "rewrite this function" than at reproducing an exact
search string, so this is the Surgeon's preferred way to edit Python code.
"""
import ast
import re
import textwrap

from repomedic.mcp_server.editing import EditError


def _find(tree: ast.AST, symbol: str) -> list[ast.AST]:
    parts = symbol.split(".")
    scopes = [tree]
    for i, part in enumerate(parts):
        found = []
        for scope in scopes:
            for node in ast.walk(scope) if i == 0 else getattr(scope, "body", []):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == part:
                    found.append(node)
        scopes = found
    return scopes


def symbol_source(text: str, symbol: str) -> str | None:
    try:
        nodes = _find(ast.parse(text), symbol)
    except SyntaxError:
        return None
    if len(nodes) != 1:
        return None
    node = nodes[0]
    start = min([d.lineno for d in getattr(node, "decorator_list", [])] + [node.lineno])
    return "\n".join(text.splitlines()[start - 1:node.end_lineno])


def add_imports(text: str, imports: list[str]) -> str:
    lines = text.splitlines(keepends=True)
    newline = "\r\n" if lines and lines[0].endswith("\r\n") else "\n"
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        raise EditError(f"File does not parse: {exc}") from exc
    last = 0
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            last = node.end_lineno
        elif not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
            break
    existing = {ln.strip() for ln in lines}
    new = [imp.strip() + newline for imp in imports if imp.strip() and imp.strip() not in existing]
    return "".join(lines[:last] + new + lines[last:])


def replace_symbol(text: str, symbol: str, new_code: str) -> str:
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        raise EditError(f"File does not parse: {exc}") from exc
    nodes = _find(tree, symbol)
    if not nodes:
        names = sorted({n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))})
        raise EditError(f"No function or class named {symbol!r}. Available: {', '.join(names)}")
    if len(nodes) > 1:
        raise EditError(f"{symbol!r} is defined {len(nodes)} times; use Class.method to disambiguate.")
    node = nodes[0]
    short = symbol.rsplit(".", 1)[-1]
    code = textwrap.dedent(new_code.replace("\r\n", "\n")).strip("\n")
    code = re.sub(r"^```(?:python)?\s*|\s*```$", "", code.strip()).strip("\n")
    if not re.search(rf"^(@.*\n)*\s*(async\s+def|def|class)\s+{re.escape(short)}\b", code, re.M):
        raise EditError(f"new_code must be the complete definition of `{short}` (starting with `def {short}(`).")

    lines = text.splitlines(keepends=True)
    start = min([d.lineno for d in getattr(node, "decorator_list", [])] + [node.lineno])
    first = lines[start - 1]
    indent = first[: len(first) - len(first.lstrip())]
    newline = "\r\n" if first.endswith("\r\n") else "\n"
    block = [(indent + ln if ln.strip() else "") + newline for ln in code.split("\n")]
    return "".join(lines[: start - 1] + block + lines[node.end_lineno:])
