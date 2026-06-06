"""External professional-corpus RAG: separate store, hybrid search, conditional tool exposure."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from code_qa import corpus
from code_qa.index import store
from code_qa.index.builder import build
from code_qa.retrieval import IndexHandle, Toolbox, build_retrieval

CORPUS_DOC = """\
# Secure Signing Standard

## Timestamping

Signatures SHOULD be timestamped with an RFC 3161 authority so they outlive the cert.

## Key storage

Private keys MUST live in an HSM or cloud KMS, never on disk.
"""


@pytest.fixture
def corpus_dir(monkeypatch):
    cache = Path(tempfile.mkdtemp())
    monkeypatch.setattr(corpus, "cache_root", lambda: cache)  # keep the corpus store out of ~/.cache
    d = Path(tempfile.mkdtemp())
    (d / "standard.md").write_text(CORPUS_DOC)
    return d


def test_ensure_corpus_builds_and_caches(corpus_dir):
    import sqlite3

    path = corpus.ensure_corpus(corpus_dir)
    assert path is not None and path.exists()
    con = sqlite3.connect(path)
    headings = {r[0] for r in con.execute("SELECT heading FROM doc_chunks")}
    con.close()
    assert {"Timestamping", "Key storage"} <= headings


def test_ensure_corpus_none_for_empty_dir(monkeypatch):
    cache = Path(tempfile.mkdtemp())
    monkeypatch.setattr(corpus, "cache_root", lambda: cache)
    assert corpus.ensure_corpus(Path(tempfile.mkdtemp())) is None  # no docs
    assert corpus.ensure_corpus(Path("/nope/does/not/exist")) is None


def test_search_corpus_hybrid(corpus_dir, sample_repo, tmp_path, fake_embedder):
    emb = fake_embedder
    corpus_path = corpus.ensure_corpus(corpus_dir, embedder=emb)
    db = tmp_path / "i.sqlite"
    store.write(build(sample_repo), db)
    tb = Toolbox(IndexHandle(repo_root=sample_repo.path, store_path=db), embedder=emb, corpus_path=corpus_path)

    out = tb.search_corpus("how should keys be stored")
    assert "Key storage" in out and "standard.md" in out
    assert "never overrides" in out  # the provenance disclaimer travels with the result


def test_search_corpus_tool_only_when_configured(sample_repo, tmp_path, corpus_dir):
    db = tmp_path / "i.sqlite"
    store.write(build(sample_repo), db)
    without = build_retrieval(IndexHandle(repo_root=sample_repo.path, store_path=db))
    assert "search_corpus" not in {t.name for t in without.tools}

    corpus_path = corpus.ensure_corpus(corpus_dir)
    with_corpus = build_retrieval(IndexHandle(repo_root=sample_repo.path, store_path=db), corpus_path=corpus_path)
    assert "search_corpus" in {t.name for t in with_corpus.tools}
