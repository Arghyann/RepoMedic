"""Web UI: streams every agent step (thoughts, MCP tool calls, patches, test runs) over Server-Sent Events."""
import asyncio
import json
import sys
import threading
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse

from repomedic.agent.llm import LLMError, OllamaLLM
from repomedic.agent.orchestrator import RepoMedic
from repomedic.benchmark import BENCH_DIR, load_cases, run_benchmark
from repomedic.config import Settings
from repomedic.workspace import sandbox_copy

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="RepoMedic")


def _settings(model: str = "", tool_mode: str = "") -> Settings:
    s = Settings()
    if model:
        s.model = model
    if tool_mode in ("auto", "json"):
        s.tool_mode = tool_mode
    return s


def _stream(job) -> StreamingResponse:
    """Run `job(emit)` on its own event loop thread (Proactor on Windows, needed for MCP stdio subprocesses)."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def emit(event):
        loop.call_soon_threadsafe(queue.put_nowait, event)

    def worker():
        lp = asyncio.ProactorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
        try:
            lp.run_until_complete(job(emit))
        except LLMError as exc:
            emit({"type": "error", "message": str(exc)})
        except Exception as exc:  # surface everything to the UI
            emit({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
        finally:
            emit(None)
            lp.close()

    threading.Thread(target=worker, daemon=True).start()

    async def events():
        while True:
            event = await queue.get()
            if event is None:
                yield "event: end\ndata: {}\n\n"
                return
            yield f"data: {json.dumps(event, default=str)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/config")
async def config():
    s = Settings()
    llm = OllamaLLM(s)
    try:
        models, ollama = await llm.list_models(), "ok"
    except LLMError as exc:
        models, ollama = [], str(exc)
    finally:
        await llm.aclose()
    return {
        "model": s.model, "ollama_host": s.ollama_host, "ollama": ollama, "models": models,
        "tool_mode": s.tool_mode, "bench_repo": str(BENCH_DIR / "buggy_shop"),
        "cases": [{"id": c["id"], "title": c["title"], "issue": c["issue"]} for c in load_cases()],
    }


@app.get("/api/run")
async def run_job(mode: str, repo: str, issue: str = "", model: str = "", tool_mode: str = "", sandbox: int = 1):
    settings = _settings(model, tool_mode)

    async def job(emit):
        target = repo
        if mode == "fix" and sandbox:
            target = str(sandbox_copy(repo))
            emit({"type": "log", "agent": "System", "message": f"Working on a disposable copy: {target}"})
        medic = RepoMedic(settings, emit)
        if mode == "scan":
            await medic.scan(target)
        elif mode == "diagnose":
            await medic.diagnose(target)
        elif mode == "fix":
            if not issue.strip():
                emit({"type": "error", "message": "Describe the issue to fix."})
                return
            await medic.fix(target, issue)
        else:
            emit({"type": "error", "message": f"Unknown mode {mode}"})

    return _stream(job)


@app.get("/api/bench")
async def bench(model: str = "", tool_mode: str = "", cases: str = "", suite: str = "main"):
    settings = _settings(model, tool_mode)
    ids = [c for c in cases.split(",") if c] or None

    async def job(emit):
        def on_result(r):
            emit({"type": "bench_case", **{k: v for k, v in r.items() if k != "diff"}})

        summary = await run_benchmark(settings, ids, emit=emit, on_result=on_result,
                                      suite=suite if suite in ("main", "heldout", "all") else "main")
        summary["results"] = [{k: v for k, v in r.items() if k != "diff"} for r in summary["results"]]
        emit({"type": "bench_done", **summary})

    return _stream(job)


def serve(host: str = "127.0.0.1", port: int = 8765):
    import uvicorn

    print(f"RepoMedic UI: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
