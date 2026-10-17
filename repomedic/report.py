"""Markdown health report for `repomedic diagnose`."""
import time
from pathlib import Path

ICON = {"critical": "🟥", "high": "🟧", "medium": "🟨", "low": "🟦"}


def render(repo_name: str, data: dict, issues: list[dict], model: str) -> str:
    tests = data.get("tests") or {}
    arch = data["architecture"]
    out = [
        f"# 🩺 RepoMedic report — `{repo_name}`",
        "",
        f"_Generated {time.strftime('%Y-%m-%d %H:%M')} · model `{model}` (local via Ollama) · tools via MCP_",
        "",
        f"**Health score: {data['score']}/100** · {len(data['findings'])} static findings · "
        f"{len(issues)} AI-reviewed issues · tests: {tests.get('summary', 'not run')}",
        "",
    ]
    confirmed = [i for i in issues if i.get("verdict") != "false_positive"]
    if confirmed:
        out += ["## AI-confirmed issues", "", "| Sev | Issue | Location | Source |", "|---|---|---|---|"]
        for i in sorted(confirmed, key=lambda i: ["critical", "high", "medium", "low"].index(i.get("severity", "low"))
                        if i.get("severity") in ("critical", "high", "medium", "low") else 9):
            out.append(f"| {ICON.get(i.get('severity'), '')} {i.get('severity')} | {i.get('title')} | "
                       f"`{i.get('file')}:{i.get('line')}` | {i.get('source')} |")
        out.append("")
        for i in confirmed:
            out += [f"### {i.get('title')} — `{i.get('file')}:{i.get('line')}`", "",
                    i.get("explanation", ""), "", f"**Fix:** {i.get('fix', '')}", ""]
    dismissed = [i for i in issues if i.get("verdict") == "false_positive"]
    if dismissed:
        out += ["## Dismissed by AI triage (likely false positives)", ""]
        out += [f"- `{i['file']}:{i['line']}` {i['title']} — {i.get('explanation', '')}" for i in dismissed]
        out.append("")
    out += ["## Static analysis findings", "", "| Sev | Rule | Location | Message |", "|---|---|---|---|"]
    for f in data["findings"]:
        out.append(f"| {ICON.get(f['severity'], '')} {f['severity']} | {f['rule']} | `{f['file']}:{f['line']}` | {f['message']} |")
    out += ["", "## Architecture", "", f"- Modules analysed: {arch['modules']}"]
    out += [f"- Circular dependency: {' → '.join(c + [c[0]])}" for c in arch["cycles"]] or ["- No circular imports"]
    out += [f"- Layering violation: `{v['from']}` → `{v['to']}`" for v in arch["layer_violations"]]
    out += ["", "| Module | Fan-in | Fan-out | Lines |", "|---|---|---|---|"]
    out += [f"| `{h['module']}` | {h['fan_in']} | {h['fan_out']} | {h['lines']} |" for h in arch["hotspots"]]
    if tests.get("failing"):
        out += ["", "## Failing tests", ""] + [f"- `{t}`" for t in tests["failing"]]
    return "\n".join(out) + "\n"


def write_report(root: str, data: dict, issues: list[dict], model: str) -> Path:
    repo_name = Path(root).resolve().name
    reports = Path.cwd() / "reports"
    reports.mkdir(exist_ok=True)
    path = reports / f"{repo_name}-{time.strftime('%Y%m%d-%H%M%S')}.md"
    path.write_text(render(repo_name, data, issues, model), encoding="utf-8")
    return path
