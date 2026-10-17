"""End-to-end test of the fix pipeline over a real MCP stdio session, with a scripted LLM.

The scripted Surgeon gets the first patch wrong on purpose, so this also proves that the
Verifier rejects a patch that fixes nothing, reverts it, and the retry succeeds.
"""
import asyncio
import json

import pytest

from repomedic.agent.llm import LLMReply, OllamaLLM
from repomedic.benchmark import BENCH_DIR, judge, load_cases, prepare_repo
from repomedic.agent.orchestrator import RepoMedic
from repomedic.config import Settings
from repomedic.mcp_server.gitops import git

FINISH = {"file": "shop/services/catalog.py", "symbol": "list_products", "line": 21,
          "root_cause": "offset is computed as page * page_size but pages are 1-indexed"}
PATCHES = [
    {"explanation": "Clamp the page.", "edits": [{"path": "shop/services/catalog.py",
                                                    "search": "offset = page * page_size",
                                                    "replace": "offset = max(page, 1) * page_size"}]},
    {"explanation": "Pages are 1-indexed, so subtract one.", "edits": [{
        "path": "shop/services/catalog.py", "symbol": "list_products",
        "new_code": (
            "def list_products(conn, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE):\n"
            '    """Return one page of products ordered by id. Pages are 1-indexed."""\n'
            "    offset = (page - 1) * page_size\n"
            "    rows = conn.execute(\n"
            '        "SELECT * FROM products ORDER BY id LIMIT ? OFFSET ?", (page_size, offset)\n'
            "    ).fetchall()\n"
            "    return [dict(r) for r in rows]\n"
        )}]},
]


PATCHES[1]["edits"] *= 2  # Gemma sometimes repeats an edit verbatim; that must not fail the attempt


class ScriptedLLM:
    def __init__(self, mode: str):
        self.mode = mode
        self.surgeon_calls = 0

    async def ensure_ready(self):
        return None

    async def chat(self, messages, *, tools=None, schema=None, temperature=None):
        system = messages[0]["content"]
        if "Surgeon" in system:
            patch = PATCHES[min(self.surgeon_calls, len(PATCHES) - 1)]
            self.surgeon_calls += 1
            return LLMReply(content=json.dumps(patch))
        investigated = any("catalog.py (lines" in m.get("content", "") for m in messages)
        if self.mode == "native":
            if not investigated:
                return LLMReply(content="Let me read the catalog.",
                                tool_calls=[{"name": "read_file", "arguments": {"path": "shop/services/catalog.py"}}])
            return LLMReply(content="Found it.", tool_calls=[{"name": "finish", "arguments": FINISH}])
        if not investigated:
            action = {"thought": "Read catalog", "action": "read_file", "args": {"path": "shop/services/catalog.py"}}
        else:
            action = {"thought": "Found it", "action": "finish", "args": FINISH}
        return LLMReply(content=json.dumps(action))


@pytest.mark.parametrize("mode", ["native", "json"])
def test_fix_pipeline_end_to_end(tmp_path, monkeypatch, mode):
    script = ScriptedLLM(mode)
    monkeypatch.setattr(OllamaLLM, "ensure_ready", lambda self: script.ensure_ready())
    monkeypatch.setattr(OllamaLLM, "chat", lambda self, messages, **kw: script.chat(messages, **kw))

    case = next(c for c in load_cases() if c["id"] == "pagination-off-by-one")
    repo = prepare_repo(BENCH_DIR / "buggy_shop", tmp_path / "repo")
    events = []
    settings = Settings(tool_mode="auto" if mode == "native" else "json")
    result = asyncio.run(RepoMedic(settings, emit=events.append).fix(str(repo), case["issue"], title=case["title"]))

    assert result["success"], result
    assert result["attempts"] == 2
    assert set(case["target_tests"]) <= set(result["fixed_tests"])
    assert judge(repo, case["target_tests"])
    _, log = git(repo, "log", "--oneline", "-1")
    assert "fix:" in log
    _, status = git(repo, "status", "--porcelain")
    assert status == ""
    assert any(e["type"] == "patch" for e in events)
    assert sum(1 for e in events if e["type"] == "tests") == 3  # baseline + 2 attempts
