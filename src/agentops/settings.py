"""Centraliseret konfiguration. Alle værdier kan overrides via environment variables / .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "postgresql+psycopg://agentops:agentops@localhost:5432/agentops"

    # MLflow
    mlflow_tracking_uri: str = "http://localhost:5000"
    mlflow_experiment_name: str = "agentops-developer-platform"

    # LLM Gateway
    llm_default_provider: str = "test"
    anthropic_api_key: str = ""
    anthropic_default_model: str = "claude-opus-5"
    anthropic_fast_model: str = "claude-haiku-4-5-20251001"
    openai_api_key: str = ""
    openai_default_model: str = "gpt-4.1"
    openai_fast_model: str = "gpt-4.1-mini"
    llm_request_timeout_seconds: float = 60.0
    llm_max_retries: int = 2

    # Agent / sikkerhed
    agent_workspace_root: str = "./demo_repo"
    agent_max_tool_calls: int = 25
    agent_tool_timeout_seconds: float = 30.0
    agent_auto_approve_high_risk: bool = False

    # MCP server
    mcp_server_host: str = "127.0.0.1"
    mcp_server_port: int = 8765

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    log_level: str = "INFO"

    # Evaluation
    eval_results_root: str = ""
    """Tomt = brug standardplaceringen (evals/results/) — overrides bruges primært af tests."""

    @property
    def workspace_root(self) -> Path:
        return Path(self.agent_workspace_root).resolve()

    @property
    def resolved_eval_results_root(self) -> Path | None:
        return Path(self.eval_results_root).resolve() if self.eval_results_root else None


@lru_cache
def get_settings() -> Settings:
    return Settings()
