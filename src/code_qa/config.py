"""Typed settings (Python config, env-backed).

Concrete model ids and secrets come from the environment / `.env` — never hardcoded —
so provider and model are swappable per agent role. See PLAN.md section 7.
"""

from __future__ import annotations

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

# Agent roles that bind to a chat model. Embeddings are handled separately.
CHAT_ROLES = ("router", "retriever", "researcher")


class RoleModel(BaseModel):
    """Resolved (provider, model) for one agent role."""

    provider: str
    model: str


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Chat provider: "anthropic" (default, local-first) | "azure_openai".
    llm_provider: str = "anthropic"

    # Per-role model ids (set in .env; see .env.example / PLAN.md section 7).
    router_model: str = "claude-haiku-4-5"
    retriever_model: str = "claude-sonnet-4-6"
    researcher_model: str = ""  # heavy Anthropic tier — set in .env

    # Embeddings (separate, pluggable provider; optional in Inc 0).
    embedding_provider: str = "local"
    embedding_model: str = "BAAI/bge-small-en-v1.5"

    # Anthropic.
    anthropic_api_key: str | None = None

    # Azure OpenAI (boilerplate AD service-principal auth).
    azure_openai_endpoint: str | None = None
    azure_openai_api_version: str | None = None

    # Scope-guard / abuse budgets (principle 7).
    max_question_chars: int = 4000

    def role(self, name: str) -> RoleModel:
        models = {
            "router": self.router_model,
            "retriever": self.retriever_model,
            "researcher": self.researcher_model,
        }
        if name not in models:
            raise KeyError(f"Unknown role: {name!r}")
        return RoleModel(provider=self.llm_provider, model=models[name])
