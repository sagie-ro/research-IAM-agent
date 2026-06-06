"""Inc 6 — incremental delta indexing: reuse unchanged files, re-parse only changes."""

from __future__ import annotations

import tempfile
from pathlib import Path

from code_qa.index import service, store
from code_qa.index.builder import build, build_delta


def test_delta_no_change_reuses_everything(sample_repo):
    old = build(sample_repo)
    same = build_delta(sample_repo, old)
    assert int(same.meta["delta_reparsed"]) == 0
    assert int(same.meta["delta_reused"]) == len(old.files)
    assert {s.id for s in same.symbols} == {s.id for s in old.symbols}


def test_delta_reparses_only_changed_source(sample_repo):
    old = build(sample_repo)
    mod = sample_repo.path / "pkg" / "mod.py"
    mod.write_text(mod.read_text() + "\n\ndef added():\n    return 1\n")

    delta = build_delta(sample_repo, old)
    assert int(delta.meta["delta_reparsed"]) == 1  # only mod.py re-parsed
    assert "added" in {s.name for s in delta.symbols}

    full = build(sample_repo)  # the delta result must equal a from-scratch rebuild
    assert {s.id for s in delta.symbols} == {s.id for s in full.symbols}
    assert {(e.src_id, e.type, e.dst_name) for e in delta.edges} == {(e.src_id, e.type, e.dst_name) for e in full.edges}


def test_delta_reparses_changed_doc(sample_repo):
    old = build(sample_repo)
    (sample_repo.path / "docs" / "guide.md").write_text("# Cats\n\nCats meow loudly.\n")

    delta = build_delta(sample_repo, old)
    text = " ".join(c.text for c in delta.doc_chunks).lower()
    assert "cats meow" in text and "a dog barks" not in text  # chunks reflect the edit


def test_ensure_index_runs_delta_on_live_repo(sample_repo, monkeypatch):
    cache = Path(tempfile.mkdtemp())  # outside the repo tree (sample_repo shares the test's tmp_path)
    monkeypatch.setattr(service, "cache_root", lambda: cache)
    _, built1 = service.ensure_index(sample_repo)
    assert built1  # first build is full
    path, built2 = service.ensure_index(sample_repo)  # live tree rebuilds — via delta
    meta = store.read_stats(path)["meta"]
    assert meta.get("delta_reparsed") == "0"
    assert int(meta.get("delta_reused", "0")) >= 5  # everything reused, nothing changed
