"""Disposable working copies, so demos and evals never touch the original repository."""
import shutil
import tempfile
from pathlib import Path

from repomedic.mcp_server.gitops import BOT_IDENTITY, git, is_repo
from repomedic.mcp_server.sandbox import IGNORED_DIRS


def sandbox_copy(src: str | Path) -> Path:
    src = Path(src).resolve()
    dst = Path(tempfile.mkdtemp(prefix=f"repomedic-{src.name}-")) / src.name
    ignore = shutil.ignore_patterns(*(IGNORED_DIRS - {".git"}))
    shutil.copytree(src, dst, ignore=ignore)
    if not (dst / ".git").exists() or not is_repo(dst):
        shutil.rmtree(dst / ".git", ignore_errors=True)
        git(dst, "init", "-q", "-b", "main")
    _, status = git(dst, "status", "--porcelain")
    if status.strip():
        git(dst, "add", "-A")
        git(dst, *BOT_IDENTITY, "commit", "-q", "-m", "RepoMedic snapshot")
    return dst
