import os
from dataclasses import dataclass, field


def _normalize_host(host: str) -> str:
    host = host.strip().rstrip("/")
    if not host.startswith(("http://", "https://")):
        host = "http://" + host
    return host.replace("0.0.0.0", "localhost")


@dataclass
class Settings:
    """Runtime settings. Every field can be overridden with a REPOMEDIC_* env var."""

    model: str = field(default_factory=lambda: os.getenv("REPOMEDIC_MODEL", "gemma4:e4b"))
    ollama_host: str = field(
        default_factory=lambda: _normalize_host(os.getenv("OLLAMA_HOST", "http://localhost:11434"))
    )
    # "auto" = Gemma 4 native function calling, falling back to grammar-constrained JSON.
    # "json" = always use grammar-constrained JSON (works with gemma3 and any other model).
    tool_mode: str = field(default_factory=lambda: os.getenv("REPOMEDIC_TOOL_MODE", "auto"))
    think: bool = field(default_factory=lambda: os.getenv("REPOMEDIC_THINK", "0") == "1")
    num_ctx: int = field(default_factory=lambda: int(os.getenv("REPOMEDIC_NUM_CTX", "8192")))
    temperature: float = field(default_factory=lambda: float(os.getenv("REPOMEDIC_TEMPERATURE", "0.1")))
    request_timeout: float = field(default_factory=lambda: float(os.getenv("REPOMEDIC_LLM_TIMEOUT", "600")))
    max_attempts: int = 3
    max_investigate_steps: int = 6
    max_hunt_steps: int = 8
    triage_limit: int = 6
