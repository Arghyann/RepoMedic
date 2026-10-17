"""RepoMedic command line.

    repomedic scan PATH                  static + architecture scan (no LLM)
    repomedic diagnose PATH              full AI diagnosis with Gemma
    repomedic fix PATH --issue "..."     localize, patch, verify, commit on a branch
    repomedic serve                      web UI at http://localhost:8765
    repomedic mcp --root PATH            run the MCP server (for Claude Desktop, VS Code, Cursor...)
"""
import argparse
import asyncio
import json
import sys

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from repomedic.config import Settings

console = Console()
AGENT_STYLE = {"Scout": "cyan", "Diagnostician": "magenta", "Surgeon": "yellow", "Verifier": "green", "System": "white"}
SEV_STYLE = {"critical": "bold red", "high": "red", "medium": "yellow", "low": "blue"}


def render_event(ev: dict) -> None:
    t, agent = ev.get("type"), ev.get("agent", "System")
    style = AGENT_STYLE.get(agent, "white")
    tag = f"[{style}]{agent:>13}[/]"
    if t == "stage":
        console.rule(f"[bold {style}]{agent}[/] · {ev['title']}")
    elif t == "thought":
        console.print(f"{tag} 💭 [italic]{ev['text'][:400]}[/]")
    elif t == "tool_call":
        args = json.dumps(ev.get("args", {}))
        console.print(f"{tag} 🔧 [bold]{ev['tool']}[/] [dim]{args[:140]}[/]")
    elif t == "tool_result" and not ev.get("ok"):
        console.print(f"{tag} [red]✗ {ev['preview'][:200]}[/]")
    elif t == "log":
        color = {"warn": "yellow", "error": "red"}.get(ev.get("level"), "dim")
        console.print(f"{tag} [{color}]{ev['message']}[/]")
    elif t == "findings":
        table = Table(title=f"Static findings — health score {ev['score']}/100", show_lines=False)
        for col in ("Sev", "Rule", "Location", "Problem"):
            table.add_column(col)
        for f in ev["findings"][:25]:
            table.add_row(f"[{SEV_STYLE.get(f['severity'], '')}]{f['severity']}[/]", f["rule"],
                          f"{f['file']}:{f['line']}", f["title"])
        console.print(table)
        for cycle in ev["architecture"]["cycles"]:
            console.print(f"[yellow]⟳ circular import:[/] {' → '.join(cycle + [cycle[0]])}")
    elif t == "tests":
        color = "green" if ev.get("ok") else "red"
        console.print(f"{tag} 🧪 [{color}]{ev.get('label')}: {ev.get('summary')}[/]")
    elif t == "issue":
        sev = ev.get("severity", "")
        mark = "[dim](dismissed)[/] " if ev.get("verdict") == "false_positive" else ""
        console.print(f"{tag} {mark}[{SEV_STYLE.get(sev, '')}]● {sev}[/] [bold]{ev.get('title')}[/] "
                      f"[dim]{ev.get('file')}:{ev.get('line')}[/]\n{' ' * 16}{ev.get('explanation', '')[:300]}")
    elif t == "diagnosis":
        console.print(Panel(f"[bold]{ev.get('file')}[/] {ev.get('symbol', '')}\n{ev.get('root_cause', '')}",
                            title="Diagnosis", border_style="magenta"))
    elif t == "patch":
        console.print(Syntax(ev["diff"], "diff", theme="ansi_dark"))
    elif t == "error":
        console.print(f"[bold red]Error:[/] {ev['message']}")


def print_result(result: dict) -> None:
    mode = result.get("mode")
    llm = result.get("llm") or {}
    stats = f"{result.get('seconds')}s · {result.get('tool_calls')} MCP tool calls"
    if llm:
        stats += f" · {llm.get('calls')} LLM calls · {llm.get('tokens_per_second')} tok/s"
    if mode == "fix":
        if result.get("success"):
            body = (f"[bold green]✔ Fixed and verified[/] in {result['attempts']} attempt(s)\n"
                    f"Branch: [bold]{result['branch']}[/]\n{result['commit']}\n"
                    f"Tests fixed: {', '.join(result.get('fixed_tests') or []) or 'suite green'}")
        else:
            body = f"[bold red]✘ Not fixed[/]\n{result.get('error')}"
        console.print(Panel(body + f"\n[dim]{stats}[/]", title="RepoMedic", border_style="green" if result.get("success") else "red"))
    elif mode == "diagnose":
        console.print(Panel(f"Health score [bold]{result['score']}/100[/] · {len(result['issues'])} AI-reviewed issues\n"
                            f"Report: {result['report']}\n[dim]{stats}[/]", title="RepoMedic diagnosis", border_style="cyan"))
    elif mode == "scan":
        console.print(Panel(f"Health score [bold]{result['score']}/100[/] · {result['findings']} findings\n[dim]{stats}[/]",
                            title="RepoMedic scan", border_style="cyan"))


def run_bench(settings: Settings, case_ids: list[str], suite: str = "main") -> int:
    from pathlib import Path

    from repomedic.benchmark import run_benchmark

    def quiet(ev: dict):
        if ev.get("type") in ("stage", "diagnosis", "tests") or (ev.get("type") == "log" and ev.get("level") == "warn"):
            render_event(ev)

    def on_result(r: dict):
        mark = "[green]✔ resolved[/]" if r["resolved"] else "[red]✘ unresolved[/]"
        console.print(Panel(f"{mark}  {r['id']} · {r['attempts']} attempt(s) · {r['seconds']}s", border_style="dim"))

    console.print(Panel.fit(f"[bold]RepoMedic-Bench[/] · suite [bold]{suite}[/] · model [magenta]{settings.model}[/] · "
                            f"tool mode {settings.tool_mode} · max attempts {settings.max_attempts}", border_style="cyan"))
    summary = asyncio.run(run_benchmark(settings, case_ids or None, emit=quiet, on_result=on_result, suite=suite))
    table = Table(title=f"RepoMedic-Bench — {summary['resolved']}/{summary['total']} resolved ({summary['resolve_rate']}%)")
    for col in ("Case", "Category", "Resolved", "Tries", "Time", "Localized file"):
        table.add_column(col)
    for r in summary["results"]:
        table.add_row(r["id"], r["category"], "✅" if r["resolved"] else "❌", str(r["attempts"]),
                      f"{r['seconds']}s", r["localized_file"])
    console.print(table)
    out = Path("bench/results")
    out.mkdir(parents=True, exist_ok=True)
    name = f"{suite}-{settings.model.replace(':', '_').replace('/', '_')}-{settings.tool_mode}-a{settings.max_attempts}.json"
    (out / name).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    console.print(f"[dim]Saved {out / name}[/]")
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to cp1252
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="repomedic", description="Local-first AI code doctor (Gemma + MCP)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("scan", "diagnose", "fix"):
        p = sub.add_parser(name)
        p.add_argument("path", nargs="?", default=".")
        p.add_argument("--model", help="Ollama model (default: $REPOMEDIC_MODEL or gemma4:e4b)")
        p.add_argument("--tool-mode", choices=["auto", "json"], help="native Gemma tool calls (auto) or JSON actions")
        if name == "fix":
            p.add_argument("--issue", required=True, help="Bug report text (e.g. a GitHub issue body)")
            p.add_argument("--attempts", type=int, default=3)
            p.add_argument("--sandbox", action="store_true", help="fix a disposable git copy instead of the repo itself")
    p = sub.add_parser("bench", help="run RepoMedic-Bench (SWE-bench-style eval on real backend bugs)")
    p.add_argument("--model")
    p.add_argument("--tool-mode", choices=["auto", "json"])
    p.add_argument("--attempts", type=int, default=3, help="max patch attempts (1 = ablation: no verify-retry loop)")
    p.add_argument("--cases", default="", help="comma-separated case ids (default: all)")
    p.add_argument("--suite", choices=["main", "heldout", "all"], default="main",
                   help="main = buggy_shop (7), heldout = buggy_bookings (3, never used for tuning), all = both")
    p = sub.add_parser("serve")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p = sub.add_parser("mcp")
    p.add_argument("--root", default=".")
    args = parser.parse_args(argv)

    if args.cmd == "mcp":
        from repomedic.mcp_server import server
        sys.argv = ["repomedic-mcp", "--root", args.root]
        server.main()
        return 0
    if args.cmd == "serve":
        from repomedic.web.app import serve
        serve(args.host, args.port)
        return 0

    from repomedic.agent.orchestrator import RepoMedic
    from repomedic.agent.llm import LLMError

    settings = Settings()
    if args.model:
        settings.model = args.model
    if args.tool_mode:
        settings.tool_mode = args.tool_mode
    if getattr(args, "attempts", None):
        settings.max_attempts = args.attempts
    if args.cmd == "bench":
        try:
            return run_bench(settings, [c for c in args.cases.split(",") if c], args.suite)
        except LLMError as exc:
            console.print(f"[bold red]LLM error:[/] {exc}")
            return 2
    if args.cmd == "fix" and args.sandbox:
        from repomedic.workspace import sandbox_copy
        args.path = str(sandbox_copy(args.path))
        console.print(f"[dim]Working on a disposable copy: {args.path}[/]")
    medic = RepoMedic(settings, emit=render_event)
    console.print(Panel.fit(f"[bold]RepoMedic[/] 🩺  {args.cmd} · [cyan]{args.path}[/] · model [magenta]{settings.model}[/]",
                            border_style="cyan"))
    try:
        if args.cmd == "scan":
            result = asyncio.run(medic.scan(args.path))
        elif args.cmd == "diagnose":
            result = asyncio.run(medic.diagnose(args.path))
        else:
            result = asyncio.run(medic.fix(args.path, args.issue))
    except LLMError as exc:
        console.print(f"[bold red]LLM error:[/] {exc}")
        return 2
    print_result(result)
    return 0 if result.get("success", True) else 1


if __name__ == "__main__":
    sys.exit(main())
