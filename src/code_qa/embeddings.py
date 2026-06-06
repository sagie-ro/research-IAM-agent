"""Embeddings — the optional semantic layer for doc RAG (separate provider seam, D10).

Default is Azure OpenAI `text-embedding-ada-002`, authenticated with the same Entra-ID
service principal as the chat models (llm.py). A local sentence-transformers backend is
supported if installed. When no embedder is configured/available, `build_embedder` returns
None and `search_docs` falls back to keyword ranking — semantic is strictly additive.

Vectors are stored in the index's `doc_vectors` table and embedded incrementally (only
chunks without a vector for the active model), so a stable repo is embedded once and cached.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .config import Settings
from .index import store

_AAD_SCOPE = "https://cognitiveservices.azure.com/.default"


@dataclass
class Embedder:
    """Thin wrapper over a LangChain embeddings client (duck-typed in tests)."""

    client: object
    model: str

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.client.embed_documents(list(texts))

    def embed_query(self, text: str) -> list[float]:
        return self.client.embed_query(text)


def build_embedder(settings: Settings) -> Embedder | None:
    """Construct the configured embedder, or None when semantic search isn't available.
    Azure is selected when an ada-2 deployment + endpoint are configured (the env the user
    provides), regardless of the `local` default for EMBEDDING_PROVIDER."""
    prov = (settings.embedding_provider or "").lower()
    if prov == "none":
        return None

    ada2 = settings.azure_openai_model_ada2
    if (prov in ("azure_openai", "azure") or ada2) and ada2 and settings.azure_openai_endpoint:
        from azure.identity import EnvironmentCredential, get_bearer_token_provider
        from langchain_openai import AzureOpenAIEmbeddings

        token_provider = get_bearer_token_provider(EnvironmentCredential(), _AAD_SCOPE)
        client = AzureOpenAIEmbeddings(
            azure_deployment=ada2,
            azure_endpoint=settings.azure_openai_endpoint,
            api_version=settings.azure_openai_api_version,
            azure_ad_token_provider=token_provider,
        )
        return Embedder(client, ada2)

    if prov == "local":
        try:  # optional heavy dep (sentence-transformers + torch); install via the `semantic` extra
            from langchain_huggingface import HuggingFaceEmbeddings
        except Exception:
            try:
                from langchain_community.embeddings import HuggingFaceEmbeddings
            except Exception:
                return None
        try:
            return Embedder(HuggingFaceEmbeddings(model_name=settings.embedding_model), settings.embedding_model)
        except Exception:
            return None

    return None


def index_doc_vectors(store_path, embedder: Embedder, batch_size: int = 64) -> int:
    """Embed doc chunks lacking a vector for this model; return how many were newly embedded."""
    pending = store.read_unembedded_chunks(store_path, embedder.model)
    for i in range(0, len(pending), batch_size):
        batch = pending[i:i + batch_size]
        vectors = embedder.embed_documents([text for _, text in batch])
        store.write_vectors(store_path, embedder.model, [(cid, vec) for (cid, _), vec in zip(batch, vectors)])
    return len(pending)


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0
