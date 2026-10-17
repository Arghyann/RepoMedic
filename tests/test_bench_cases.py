"""Benchmark integrity: every case's bug really breaks its judging tests, and the gold fix
makes exactly those tests pass without breaking anything else."""
import importlib.util
import shutil

import pytest

from repomedic.benchmark import BENCH_DIR, load_suite
from repomedic.mcp_server import testing
from repomedic.mcp_server.editing import apply_search_replace

_spec = importlib.util.spec_from_file_location("gold_patches", BENCH_DIR / "gold_patches.py")
gold_patches = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gold_patches)

CASES = load_suite("all")


def test_every_case_has_a_gold_patch():
    assert {c["id"] for c in CASES} == set(gold_patches.GOLD)


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_case_is_valid(case, tmp_path):
    repo = tmp_path / "repo"
    shutil.copytree(BENCH_DIR / case.get("repo", "buggy_shop"), repo,
                    ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    targets = set(case["target_tests"])

    before = set(testing.run(repo)["failing"])
    assert targets <= before, f"judging tests should fail before the fix: {targets - before}"

    for path, search, replace in gold_patches.GOLD[case["id"]]:
        file = repo / path
        file.write_text(apply_search_replace(file.read_text(encoding="utf-8"), search, replace), encoding="utf-8")

    after = set(testing.run(repo)["failing"])
    assert after == before - targets, f"gold fix should fix exactly the targets; still failing/new: {after - (before - targets)}"
