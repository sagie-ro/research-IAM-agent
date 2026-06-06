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

    # Embeddings (separate, pluggable provider). "azure_openai" (ada-2) | "local" | "none".
    embedding_provider: str = "local"
    embedding_model: str = "BAAI/bge-small-en-v1.5"

    # Anthropic.
    anthropic_api_key: str | None = None

    # Azure OpenAI (boilerplate AD service-principal auth). One chat deployment serves every
    # agent role; embeddings use the ada-2 deployment.
    azure_openai_endpoint: str | None = None
    azure_openai_api_version: str | None = None
    azure_openai_model_gpt4o: str | None = None  # chat deployment (all roles when provider=azure_openai)
    azure_openai_model_ada2: str | None = None  # embedding deployment (text-embedding-ada-002)

    # External professional-corpus RAG (optional; a directory of reference docs).
    corpus_path: str | None = None

    # Budgeted web search for the researcher. Provider: "duckduckgo" (keyless, default) | "tavily" | "none".
    web_search_provider: str = "duckduckgo"
    web_search_results: int = 5  # results per query
    web_search_max: int = 3  # budget: max web searches per trace
    tavily_api_key: str | None = None  # only needed for provider="tavily"

    # Scope-guard / abuse budgets (principle 7).
    max_question_chars: int = 4000
    retriever_max_steps: int = 6  # tool-call budget per retriever worker
    researcher_max_steps: int = 8  # tool-call budget for the researcher (trace questions)
    max_parallel_retrievers: int = 6  # fan-out width cap per spawn_retrievers call
    max_retrievers_per_trace: int = 50  # hard ceiling on total retrievers spawned per trace
    max_context_fetches: int = 2  # how many times the router may fetch code before deciding

    def role(self, name: str) -> RoleModel:
        """Resolve (provider, deployment/model) for an agent role. Provider-aware so switching
        providers needs no per-role edits: Anthropic uses the per-role tier ids; Azure maps every
        chat role to the single AZURE_OPENAI_MODEL_GPT4O deployment."""
        if name not in CHAT_ROLES:
            raise KeyError(f"Unknown role: {name!r}")
        if self.llm_provider in ("azure_openai", "azure"):
            model = self.azure_openai_model_gpt4o or ""
        else:
            model = {
                "router": self.router_model,
                "retriever": self.retriever_model,
                "researcher": self.researcher_model,
            }[name]
        return RoleModel(provider=self.llm_provider, model=model)
