"""Per-role chat-model factory (the provider seam).

Default provider is Anthropic (local-first tier separation); Azure OpenAI is the
alternate, wrapping the boilerplate's Entra ID service-principal token provider.
Models are built lazily and cached per role.
"""

from __future__ import annotations

from langchain.chat_models import init_chat_model

from .config import RoleModel, Settings


def build_chat_model(role: RoleModel, settings: Settings):
    if not role.model:
        raise ValueError(
            "No model configured for this role. Set ROUTER_MODEL / RETRIEVER_MODEL / "
            "RESEARCHER_MODEL in your .env (see .env.example, PLAN.md section 7)."
        )

    if role.provider == "anthropic":
        # Reads ANTHROPIC_API_KEY from the environment.
        return init_chat_model(role.model, model_provider="anthropic")

    if role.provider in ("azure_openai", "azure"):
        # Reuse the boilerplate auth: Entra ID service principal -> bearer token.
        from azure.identity import EnvironmentCredential, get_bearer_token_provider
        from langchain_openai import AzureChatOpenAI

        token_provider = get_bearer_token_provider(
            EnvironmentCredential(), "https://cognitiveservices.azure.com/.default"
        )
        return AzureChatOpenAI(
            azure_deployment=role.model,
            azure_endpoint=settings.azure_openai_endpoint,
            api_version=settings.azure_openai_api_version,
            azure_ad_token_provider=token_provider,
        )

    raise ValueError(f"Unknown chat provider: {role.provider!r}")


class ModelFactory:
    """Lazily builds and caches one chat model per role."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._cache: dict[str, object] = {}

    def get(self, role_name: str):
        if role_name not in self._cache:
            self._cache[role_name] = build_chat_model(
                self._settings.role(role_name), self._settings
            )
        return self._cache[role_name]
