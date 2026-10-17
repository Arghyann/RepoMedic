"""Path sandbox: every tool call is confined to the repository root."""
import os
from fnmatch import fnmatch
from pathlib import Path

IGNORED_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv", "env",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", "dist", "build",
    ".idea", ".vscode", ".repomedic", "site-packages", ".next", "target",
}
MAX_FILE_BYTES = 1_000_000


class Sandbox:
    def __init__(self, root: str | os.PathLike):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise FileNotFoundError(f"Repository root does not exist: {self.root}")

    def resolve(self, rel: str) -> Path:
        rel = (rel or ".").replace("\\", "/")
        path = (self.root / rel).resolve()
        if path != self.root and self.root not in path.parents:
            raise PermissionError(f"Path escapes repository root: {rel}")
        if ".git" in path.relative_to(self.root).parts:
            raise PermissionError("The .git directory is off-limits")
        return path

    def rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix() or "."

    def iter_files(self, pattern: str = "*"):
        """Yield repo files matching a glob, where `*` also matches across directories."""
        flat = pattern.replace("**/", "")
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = sorted(d for d in dirnames if d not in IGNORED_DIRS and not d.endswith(".egg-info"))
            for name in sorted(filenames):
                path = Path(dirpath) / name
                rel = self.rel(path)
                if fnmatch(rel, pattern) or fnmatch(rel, flat) or fnmatch(name, flat):
                    yield path

    @staticmethod
    def is_text(path: Path) -> bool:
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                return False
            with open(path, "rb") as fh:
                return b"\0" not in fh.read(2048)
        except OSError:
            return False

    @staticmethod
    def read_text(path: Path) -> str:
        return path.read_text(encoding="utf-8", errors="replace")
