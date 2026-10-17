import subprocess
from pathlib import Path

BOT_IDENTITY = ["-c", "user.name=RepoMedic", "-c", "user.email=repomedic@localhost"]


def git(root: Path, *args: str, timeout: int = 60) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
        )
    except FileNotFoundError:
        return 127, "git is not installed or not on PATH"
    except subprocess.TimeoutExpired:
        return 124, f"git {' '.join(args)} timed out"
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def is_repo(root: Path) -> bool:
    code, out = git(root, "rev-parse", "--is-inside-work-tree")
    return code == 0 and out.strip() == "true"


def is_tracked(root: Path, rel: str) -> bool:
    code, _ = git(root, "ls-files", "--error-unmatch", rel)
    return code == 0
