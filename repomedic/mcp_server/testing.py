"""Test-runner detection and result parsing."""
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

SUMMARY_RE = re.compile(r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed)")
FAILED_RE = re.compile(r"^(FAILED|ERROR) (\S+)", re.M)


def _repo_python(root: Path) -> str:
    for candidate in (".venv/Scripts/python.exe", ".venv/bin/python", "venv/Scripts/python.exe", "venv/bin/python"):
        path = root / candidate
        if path.exists():
            return str(path)
    return sys.executable


def detect_command(root: Path) -> list[str] | None:
    override = os.getenv("REPOMEDIC_TEST_CMD")
    if override:
        return shlex.split(override, posix=os.name != "nt")
    if any((root / f).exists() for f in ("pytest.ini", "conftest.py", "tox.ini")) or (root / "tests").is_dir() \
            or "pytest" in _read(root / "pyproject.toml") or "pytest" in _read(root / "setup.cfg"):
        return [_repo_python(root), "-m", "pytest", "-q", "-rfE", "-p", "no:cacheprovider", "--tb=short", "--color=no"]
    if (root / "package.json").exists():
        return ["npm", "test", "--silent"]
    if (root / "go.mod").exists():
        return ["go", "test", "./..."]
    if (root / "Cargo.toml").exists():
        return ["cargo", "test", "--quiet"]
    return None


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def run(root: Path, target: str = "", timeout: int = 180) -> dict:
    cmd = detect_command(root)
    if cmd is None:
        return {"ok": False, "ran": False, "summary": "No test runner detected (set REPOMEDIC_TEST_CMD).",
                "passed": 0, "failed": 0, "errors": 0, "failing": [], "output": ""}
    if target:
        cmd = [*cmd, *target.split()]
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
    start = time.time()
    try:
        proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout, env=env, shell=(os.name == "nt" and cmd[0] == "npm"))
        output, code = proc.stdout + proc.stderr, proc.returncode
    except subprocess.TimeoutExpired:
        output, code = f"Test run exceeded {timeout}s timeout", 124
    except FileNotFoundError as exc:
        output, code = f"Could not run tests: {exc}", 127
    counts = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    for num, kind in SUMMARY_RE.findall(output):
        key = "errors" if kind.startswith("error") else kind
        if key in counts:
            counts[key] = int(num)
    failing = sorted({m[1] for m in FAILED_RE.findall(output)})
    summary = next((ln.strip(" =") for ln in reversed(output.splitlines()) if SUMMARY_RE.search(ln)), f"exit code {code}")
    return {
        "ok": code == 0, "ran": True, "exit_code": code, "command": " ".join(cmd), "summary": summary,
        "seconds": round(time.time() - start, 2), "failing": failing, **counts, "output": output,
    }
