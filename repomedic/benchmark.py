"""RepoMedic-Bench: SWE-bench-style evaluation on realistic backend bugs.

For every case: copy the patient repo to a fresh temp dir, `git init`, hand the agent ONLY the issue
text, let it localize/patch/verify, then judge with the case's ground-truth tests.
"""
import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from repomedic.agent.llm import OllamaLLM
from repomedic.agent.orchestrator import RepoMedic
from repomedic.config import Settings
from repomedic.mcp_server.gitops import BOT_IDENTITY, git

BENCH_DIR = Path(__file__).resolve().parent.parent / "bench"


SUITES = {
    "main": ["cases.json"],               # buggy_shop: the 7 cases the agent design was developed on
    "heldout": ["heldout_cases.json"],    # buggy_bookings: written after the design was frozen
    "all": ["cases.json", "heldout_cases.json"],
}


def load_cases(path: Path = BENCH_DIR / "cases.json") -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_suite(suite: str = "main") -> list[dict]:
    if suite not in SUITES:
        raise ValueError(f"Unknown suite {suite!r}; choose one of {', '.join(SUITES)}")
    return [case for name in SUITES[suite] for case in load_cases(BENCH_DIR / name)]


def prepare_repo(src: Path, dst: Path) -> Path:
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    git(dst, "init", "-q", "-b", "main")
    git(dst, "add", "-A")
    git(dst, *BOT_IDENTITY, "commit", "-q", "-m", "initial import")
    return dst


def judge(repo: Path, target_tests: list[str]) -> bool:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *target_tests],
        cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={**__import__("os").environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    return proc.returncode == 0


async def run_case(case: dict, settings: Settings, emit=None) -> dict:
    patient = BENCH_DIR / case.get("repo", "buggy_shop")
    with tempfile.TemporaryDirectory(prefix=f"rm-{case['id']}-", ignore_cleanup_errors=True) as tmp:
        repo = prepare_repo(patient, Path(tmp) / "repo")
        start = time.time()
        medic = RepoMedic(settings, emit=emit)
        try:
            result = await medic.fix(str(repo), case["issue"], title=case["title"])
        except Exception as exc:  # a crash is a failed case, not a failed benchmark
            result = {"success": False, "error": f"{type(exc).__name__}: {exc}"}
        resolved = judge(repo, case["target_tests"])
        return {
            "id": case["id"], "repo": patient.name, "category": case["category"], "difficulty": case["difficulty"],
            "resolved": resolved, "agent_claimed_success": bool(result.get("success")),
            "attempts": result.get("attempts", 0), "seconds": round(time.time() - start, 1),
            "tool_calls": result.get("tool_calls", 0), "llm_calls": (result.get("llm") or {}).get("calls", 0),
            "localized_file": (result.get("diagnosis") or {}).get("file", ""),
            "error": result.get("error", ""), "diff": result.get("diff", ""),
        }


async def run_benchmark(settings: Settings, case_ids: list[str] | None = None, emit=None, on_result=None,
                        suite: str = "main") -> dict:
    cases = [c for c in load_suite(suite) if not case_ids or c["id"] in case_ids]
    llm = OllamaLLM(settings)
    try:
        await llm.ensure_ready()  # fail fast instead of failing every case
    finally:
        await llm.aclose()
    results = []
    for case in cases:
        r = await run_case(case, settings, emit)
        results.append(r)
        if on_result:
            on_result(r)
    solved = sum(r["resolved"] for r in results)
    return {
        "suite": suite, "model": settings.model, "tool_mode": settings.tool_mode, "max_attempts": settings.max_attempts,
        "resolved": solved, "total": len(results),
        "resolve_rate": round(100 * solved / len(results), 1) if results else 0.0,
        "false_claims": sum(r["agent_claimed_success"] and not r["resolved"] for r in results),
        "avg_seconds": round(sum(r["seconds"] for r in results) / max(1, len(results)), 1),
        "results": results, "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run_benchmark(Settings())), indent=2))
