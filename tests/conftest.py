"""Shared fixtures: a tiny synthetic repo built into a real SQLite index (key-free)."""

from __future__ import annotations

import hashlib
import re

import pytest

from code_qa.index import store
from code_qa.index.builder import build
from code_qa.retrieval import IndexHandle, Toolbox
from code_qa.source import RepoSource


class FakeEmbedder:
    """Deterministic bag-of-words hashing embedder (16-dim) — no network, stable across runs."""

    model = "fake-16"

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * 16
        for w in re.findall(r"[a-z]+", text.lower()):
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 16] += 1.0
        return v

    def embed_documents(self, texts):
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)


@pytest.fixture
def fake_embedder():
    return FakeEmbedder()

PY_SRC = """\
import os


class Animal:
    def speak(self):
        return noise()


class Dog(Animal):
    def speak(self):
        bark()
        return super().speak()


def noise():
    return "..."


def bark():
    return "woof"


def main():
    Dog().speak()


if __name__ == "__main__":
    main()
"""

JAVA_SRC = """\
package demo;

public class Service implements Runnable {
    public static void main(String[] args) {
        new Service().run();
    }

    public void run() {
        helper();
    }

    void helper() {}
}
"""

GUIDE_MD = """\
# Animal Guide

This guide explains the demo's animal model.

## Dogs

A Dog barks when it speaks, then defers to its parent Animal.

## Design notes

Sounds are produced by the noise helper. (Docs may lag the code.)
"""


@pytest.fixture
def sample_repo(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text(PY_SRC)
    (tmp_path / "Service.java").write_text(JAVA_SRC)
    (tmp_path / "README.md").write_text("# Demo\nA sample repository.\n")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text(GUIDE_MD)
    (tmp_path / "asset.bin").write_bytes(b"\x00\x01\x02binary-blob")
    return RepoSource.from_local(tmp_path)


@pytest.fixture
def built_index(sample_repo, tmp_path):
    index = build(sample_repo)
    db = tmp_path / "index.sqlite"
    store.write(index, db)
    return index, db


@pytest.fixture
def toolbox(sample_repo, built_index):
    _, db = built_index
    return Toolbox(IndexHandle(repo_root=sample_repo.path, store_path=db))
