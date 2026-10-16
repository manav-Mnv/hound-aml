"""Runtime settings, read once from the environment."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv() -> None:
    """Minimal .env support (backend/.env or repo-root .env); real env vars win."""
    here = Path(__file__).resolve()
    for path in (here.parents[2] / ".env", here.parents[3] / ".env"):
        if path.is_file():
            for line in path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    key, value = key.strip(), value.strip().strip('"').strip("'")
                    if key and value and not os.environ.get(key, "").strip():
                        os.environ[key] = value


_load_dotenv()


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    falkor_host: str = field(default_factory=lambda: _env("FALKORDB_HOST", "localhost"))
    falkor_port: int = field(default_factory=lambda: int(_env("FALKORDB_PORT", "6379")))
    falkor_username: str | None = field(default_factory=lambda: os.environ.get("FALKORDB_USERNAME"))
    falkor_password: str | None = field(default_factory=lambda: os.environ.get("FALKORDB_PASSWORD"))

    # One FalkorDB instance, many isolated graphs: one per bank plus a shared consortium graph.
    graph_prefix: str = field(default_factory=lambda: _env("HOUND_GRAPH_PREFIX", "hound"))
    tenants: tuple[str, ...] = ("alpha", "beta")

    model: str = field(default_factory=lambda: _env("HOUND_MODEL", "claude-opus-5-5"))
    effort: str = field(default_factory=lambda: _env("HOUND_EFFORT", "medium"))
    # "auto" uses Claude when a key is configured and falls back to the offline playbook runner.
    agent_mode: str = field(default_factory=lambda: _env("HOUND_AGENT_MODE", "auto"))
    max_agent_turns: int = field(default_factory=lambda: int(_env("HOUND_MAX_TURNS", "14")))
    live_runs_per_hour: int = field(default_factory=lambda: int(_env("HOUND_LIVE_RUNS_PER_HOUR", "30")))

    # Key for hashing identifiers before they leave a bank's graph (314(b)-style sharing).
    consortium_key: str = field(default_factory=lambda: _env("HOUND_CONSORTIUM_KEY", "hound-demo-consortium-key"))

    def graph_name(self, tenant: str) -> str:
        return f"{self.graph_prefix}:{tenant}"

    @property
    def consortium_graph(self) -> str:
        return f"{self.graph_prefix}:consortium"

    @property
    def has_llm(self) -> bool:
        if self.agent_mode == "offline":
            return False
        return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip() or os.environ.get("ANTHROPIC_AUTH_TOKEN", "").strip())


settings = Settings()
