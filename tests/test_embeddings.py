"""Semantic doc RAG: incremental vector indexing + hybrid search, with graceful fallback.

Uses a deterministic fake embedder so the path is exercised without any cloud creds."""

from __future__ import annotations

from code_qa.config import Settings
from code_qa.embeddings import build_embedder, cosine, index_doc_vectors
from code_qa.index import store
from code_qa.index.builder import build
from code_qa.index.store import pack_vector, unpack_vector
from code_qa.retrieval import IndexHandle, Toolbox


def test_vector_pack_round_trip():
    v = [0.5, -1.25, 3.0, 0.0]
    assert unpack_vector(pack_vector(v)) == v


def test_cosine():
    assert cosine([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert abs(cosine([1.0, 0.0], [0.0, 1.0])) < 1e-9
    assert cosine([], [1.0]) == 0.0


def test_index_doc_vectors_is_incremental(sample_repo, tmp_path, fake_embedder):
    db = tmp_path / "i.sqlite"
    store.write(build(sample_repo), db)
    emb = fake_embedder
    assert index_doc_vectors(db, emb) > 0   # embeds the doc chunks
    assert index_doc_vectors(db, emb) == 0  # cached — nothing new to embed


def test_hybrid_search_uses_semantic_when_embedded(sample_repo, tmp_path, fake_embedder):
    db = tmp_path / "i.sqlite"
    store.write(build(sample_repo), db)
    emb = fake_embedder
    index_doc_vectors(db, emb)
    tb = Toolbox(IndexHandle(repo_root=sample_repo.path, store_path=db), embedder=emb)
    out = tb.search_docs("dog")
    assert "semantic+keyword" in out and "docs/guide.md" in out


def test_search_docs_falls_back_to_keyword(toolbox):
    out = toolbox.search_docs("dog barks")  # fixture toolbox has no embedder
    assert "keyword" in out and "semantic" not in out


def test_build_embedder_none_without_config():
    assert build_embedder(Settings(embedding_provider="none")) is None
    # azure selected but unconfigured -> None (graceful), not an exception
    assert build_embedder(
        Settings(embedding_provider="azure_openai", azure_openai_model_ada2=None, azure_openai_endpoint=None)
    ) is None
