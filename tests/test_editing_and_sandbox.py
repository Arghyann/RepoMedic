import pytest

from repomedic.mcp_server.editing import EditError, apply_search_replace
from repomedic.mcp_server.sandbox import Sandbox

SRC = "def f(page):\n    offset = page * 10\n    return offset\n"


def test_exact_replace():
    assert "page - 1" in apply_search_replace(SRC, "    offset = page * 10\n", "    offset = (page - 1) * 10\n")


def test_fuzzy_replace_fixes_indentation():
    out = apply_search_replace(SRC, "offset = page * 10", "offset = (page - 1) * 10")
    assert "    offset = (page - 1) * 10\n" in out


def test_ambiguous_and_missing():
    with pytest.raises(EditError):
        apply_search_replace("x = 1\nx = 1\n", "x = 1", "x = 2")
    with pytest.raises(EditError):
        apply_search_replace(SRC, "nope", "x")


def test_sandbox_blocks_escape(tmp_path):
    sb = Sandbox(tmp_path)
    with pytest.raises(PermissionError):
        sb.resolve("../outside.txt")
    with pytest.raises(PermissionError):
        sb.resolve(".git/config")
    assert sb.resolve("a/b.py") == tmp_path.resolve() / "a" / "b.py"
