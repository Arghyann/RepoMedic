from repomedic.mcp_server.analyzers import analyze_source
from repomedic.mcp_server.architecture import analyze
from repomedic.mcp_server.sandbox import Sandbox


def rules(src: str, path: str = "app/service.py") -> set[str]:
    return {f.rule for f in analyze_source(src, path)}


def test_sql_injection_fstring_and_variable():
    assert "RM001" in rules('def f(c, t):\n    c.execute(f"SELECT * FROM x WHERE n = {t}")\n')
    assert "RM001" in rules('def f(c, t):\n    q = "SELECT * FROM x WHERE n = \'%s\'" % t\n    c.execute(q)\n')
    assert "RM001" not in rules('def f(c, t):\n    c.execute("SELECT * FROM x WHERE n = ?", (t,))\n')


def test_mutable_default_and_bare_except():
    found = rules("def f(x=[]):\n    try:\n        pass\n    except:\n        pass\n")
    assert {"RM002", "RM003"} <= found


def test_naive_datetime_and_weak_hash_and_secret():
    src = "import hashlib\nfrom datetime import datetime\nAPI_KEY = 'abcdef123456'\n" \
          "def f():\n    hashlib.md5(b'x')\n    return datetime.now()\n"
    assert {"RM005", "RM006", "RM007"} <= rules(src)
    assert "RM005" not in rules("from datetime import datetime, timezone\nx = datetime.now(timezone.utc)\n")


def test_n_plus_one_and_timeout():
    src = "import requests\ndef f(c, ids):\n    for i in ids:\n        c.execute('SELECT 1 WHERE id=?', (i,))\n" \
          "    requests.get('http://x')\n"
    assert {"RM010", "RM011"} <= rules(src)


def test_tests_are_not_flagged_for_secrets():
    assert "RM007" not in rules("PASSWORD = 'hunter22'\n", "tests/test_x.py")


def test_architecture_detects_cycle(tmp_path):
    pkg = tmp_path / "app"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "a.py").write_text("from app import b\n")
    (pkg / "b.py").write_text("def f():\n    from app import a\n")
    result = analyze(Sandbox(tmp_path))
    assert result["cycles"] == [["app.a", "app.b"]]
