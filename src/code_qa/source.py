"""RepoSource — resolve a target repository (local path or git clone) to a tree
pinned at a commit SHA, with a language-aware file walk.

Read-only: we never build or execute the target (principle 1 / D1).
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

_IGNORE_DIRS = {
    ".git", "node_modules", "target", "build", "dist", "out",
    ".venv", "venv", "__pycache__", ".idea", ".gradle", ".mvn",
}
_BINARY_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".gz", ".tar",
    ".jar", ".war", ".class", ".exe", ".dll", ".so", ".dylib", ".bin", ".lock",
}


@dataclass
class RepoSource:
    path: Path
    sha: str | None

    @classmethod
    def from_local(cls, path: str | Path) -> "RepoSource":
        p = Path(path).expanduser().resolve()
        if not p.is_dir():
            raise ValueError(f"Not a directory: {p}")
        return cls(path=p, sha=_git_sha(p))

    @classmethod
    def from_git(cls, url: str, ref: str | None = None, dest: str | Path | None = None) -> "RepoSource":
        target = (
            Path(dest).expanduser().resolve()
            if dest
            else Path.home() / ".cache" / "code-qa" / _slug(url)
        )
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            cmd = ["git", "clone", "--depth", "1"]
            if ref:
                cmd += ["--branch", ref]
            cmd += [url, str(target)]
            subprocess.run(cmd, check=True)
        return cls(path=target, sha=_git_sha(target))

    def list_files(self) -> list[Path]:
        files: list[Path] = []
        for root, dirs, names in os.walk(self.path):
            dirs[:] = [d for d in dirs if d not in _IGNORE_DIRS]
            for name in names:
                if Path(name).suffix.lower() in _BINARY_EXT:
                    continue
                files.append(Path(root) / name)
        return files

    def summary(self) -> str:
        sha = self.sha[:8] if self.sha else "no-sha"
        return f"{self.path.name} @ {sha} ({len(self.list_files())} text files)"


def _git_sha(p: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(p), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()
    except Exception:
        return None


def _slug(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:12]
