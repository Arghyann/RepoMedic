"""Architecture analysis: internal import graph, circular dependencies, layering violations, hotspots."""
import ast
from collections import defaultdict
from pathlib import PurePosixPath

from repomedic.mcp_server.analyzers import Finding
from repomedic.mcp_server.sandbox import Sandbox

# Higher number = closer to the edge of the system. Lower layers must not import higher ones.
LAYERS = [
    (3, {"api", "routes", "views", "handlers", "controllers", "endpoints", "cli", "web"}),
    (2, {"services", "service", "usecases", "domain", "logic"}),
    (1, {"models", "db", "database", "repositories", "repository", "dao", "schemas", "orm"}),
]


def _module_name(rel: str) -> str:
    path = PurePosixPath(rel).with_suffix("")
    parts = list(path.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _layer(module: str) -> int | None:
    for part in reversed(module.split(".")):
        for rank, names in LAYERS:
            if part in names:
                return rank
    return None


def _resolve_relative(module: str, is_pkg: bool, level: int, target: str | None) -> str:
    base = module.split(".") if is_pkg else module.split(".")[:-1]
    if level > 1:
        base = base[: len(base) - (level - 1)]
    return ".".join([*base, target] if target else base)


def _strongly_connected(graph: dict[str, set[str]]) -> list[list[str]]:
    index, low, on_stack, stack, result = {}, {}, set(), [], []
    counter = [0]

    def visit(v):
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on_stack.add(v)
        for w in graph.get(v, ()):
            if w not in index:
                visit(w)
                low[v] = min(low[v], low[w])
            elif w in on_stack:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                comp.append(w)
                if w == v:
                    break
            if len(comp) > 1:
                result.append(sorted(comp))

    for v in sorted(graph):
        if v not in index:
            visit(v)
    return result


def analyze(sandbox: Sandbox) -> dict:
    files = {sandbox.rel(p): p for p in sandbox.iter_files("*.py") if sandbox.is_text(p)}
    modules = {_module_name(rel): rel for rel in files}
    # Allow resolving imports when the package lives under src/ or another source root.
    suffix_index = defaultdict(list)
    for mod in modules:
        parts = mod.split(".")
        for i in range(len(parts)):
            suffix_index[".".join(parts[i:])].append(mod)

    def internal(name: str) -> str | None:
        while name:
            if name in modules:
                return name
            if len(suffix_index.get(name, [])) == 1:
                return suffix_index[name][0]
            name = name.rpartition(".")[0]
        return None

    graph: dict[str, set[str]] = defaultdict(set)
    edges_lines: dict[tuple[str, str], int] = {}
    sizes: dict[str, int] = {}
    func_counts: dict[str, int] = {}
    for mod, rel in modules.items():
        source = sandbox.read_text(files[rel])
        sizes[mod] = source.count("\n") + 1
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        func_counts[mod] = sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in ast.walk(tree))
        is_pkg = rel.endswith("__init__.py")
        graph.setdefault(mod, set())
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Import):
                targets = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = _resolve_relative(mod, is_pkg, node.level, node.module) if node.level else (node.module or "")
                targets = [f"{base}.{a.name}" for a in node.names] or [base]
            for t in targets:
                dep = internal(t)
                if dep and dep != mod:
                    graph[mod].add(dep)
                    edges_lines.setdefault((mod, dep), node.lineno)

    fan_in = defaultdict(int)
    for src, deps in graph.items():
        for dep in deps:
            fan_in[dep] += 1

    findings: list[Finding] = []
    cycles = _strongly_connected(graph)
    for cycle in cycles:
        first = cycle[0]
        nxt = next((d for d in graph[first] if d in cycle), cycle[-1])
        findings.append(Finding(
            "RA001", "Circular import dependency", "medium", "architecture", modules[first],
            edges_lines.get((first, nxt), 1),
            f"Modules form an import cycle: {' -> '.join(cycle + [cycle[0]])}. Extract the shared piece or invert the dependency.",
            symbol=first,
        ))

    violations = []
    for src, deps in graph.items():
        src_layer = _layer(src)
        for dep in deps:
            dep_layer = _layer(dep)
            if src_layer is not None and dep_layer is not None and src_layer < dep_layer:
                violations.append({"from": src, "to": dep})
                findings.append(Finding(
                    "RA002", "Layering violation", "medium", "architecture", modules[src],
                    edges_lines.get((src, dep), 1),
                    f"Lower-layer module `{src}` imports higher-layer `{dep}`; dependencies should point inward.",
                    symbol=src,
                ))

    for mod, size in sizes.items():
        if size > 500 or func_counts.get(mod, 0) > 30:
            findings.append(Finding(
                "RA003", "God module", "low", "architecture", modules[mod], 1,
                f"`{mod}` has {size} lines and {func_counts.get(mod, 0)} functions; consider splitting by responsibility.",
                symbol=mod,
            ))

    hotspots = sorted(
        ({"module": m, "fan_in": fan_in[m], "fan_out": len(graph.get(m, ())), "lines": sizes.get(m, 0)} for m in modules),
        key=lambda h: (-h["fan_in"], -h["lines"]),
    )[:8]
    return {
        "modules": len(modules),
        "edges": [{"from": s, "to": d} for s, deps in sorted(graph.items()) for d in sorted(deps)],
        "cycles": cycles,
        "layer_violations": violations,
        "hotspots": hotspots,
        "findings": [f.to_dict() for f in findings],
    }
