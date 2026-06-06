"""RepoSource — resolve a target repository to a tree pinned at a commit SHA.

For git URLs we do a *lean* clone: shallow + blobless partial clone, with a
sparse-checkout that materializes only the file types we parse (source + docs).
Crucially we still enumerate the FULL tree via `git ls-tree`, so binary/asset files
are known to the index as inventory (paths/types) even though their bytes are never
downloaded or parsed. Reading/disassembling binary *contents* is out of scope (D1).
Read-only throughout: we never build or execute the target.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

SOURCE_EXT = {".py", ".java"}
DOC_EXT = {".md", ".rst", ".txt", ".adoc"}
BINARY_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".bmp", ".svg",
    ".pdf", ".zip", ".gz", ".tar", ".7z",
    ".jar", ".war", ".class", ".exe", ".dll", ".dylib", ".so", ".bin", ".o",
    ".lock", ".pyc", ".p7b", ".p7s", ".cat", ".der", ".cer", ".pem", ".msi", ".cab",
}
# Sparse-checkout patterns (gitignore-style): only what we parse gets materialized.
_SPARSE_PATTERNS = [
    "*.py", "*.java", "*.kt", "*.scala",
    "*.md", "*.rst", "*.txt", "*.adoc",
    "README*", "readme*", "LICENSE*", "NOTICE*",
]
_IGNORE_DIRS = {
    ".git", "node_modules", "target", "build", "dist", "out",
    ".venv", "venv", "__pycache__", ".idea", ".gradle", ".mvn",
}


@dataclass
class RepoSource:
    path: Path
    sha: str | None
    is_git: bool = False

    @classmethod
    def from_local(cls, path: str | Path) -> "RepoSource":
        p = Path(path).expanduser().resolve()
        if not p.is_dir():
            raise ValueError(
                f"Not a directory: {p}. If this is a remote repo, pass its URL "
                "(e.g. https://github.com/owner/repo)."
            )
        sha = _git_sha(p)
        return cls(path=p, sha=sha, is_git=(p / ".git").exists() or sha is not None)

    @classmethod
    def from_git(cls, url: str, ref: str | None = None, dest: str | Path | None = None) -> "RepoSource":
        target = (
            Path(dest).expanduser().resolve()
            if dest
            else Path.home() / ".cache" / "code-qa" / _slug(url)
        )
        if not target.exists():
            _lean_clone(url, ref, target)
        return cls(path=target, sha=_git_sha(target), is_git=True)

    def tracked_paths(self) -> list[str]:
        """All repo-relative paths in the tree (binaries included), independent of
        which blobs were materialized."""
        if self.is_git:
            try:
                out = subprocess.run(
                    ["git", "-C", str(self.path), "ls-tree", "-r", "--name-only", "HEAD"],
                    capture_output=True, text=True, check=True,
                )
                paths = [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
                if paths:
                    return paths
            except Exception:
                pass
        return self._walk_paths()

    def materialized(self, relpath: str) -> bool:
        return (self.path / relpath).is_file()

    def summary(self) -> str:
        paths = self.tracked_paths()
        n_src = sum(1 for p in paths if Path(p).suffix.lower() in SOURCE_EXT)
        sha = self.sha[:8] if self.sha else "no-sha"
        return f"{self.path.name} @ {sha} ({len(paths)} files, {n_src} source)"

    def _walk_paths(self) -> list[str]:
        out: list[str] = []
        for root, dirs, names in os.walk(self.path):
            dirs[:] = [d for d in dirs if d not in _IGNORE_DIRS]
            for name in names:
                out.append(str((Path(root) / name).relative_to(self.path)).replace("\\", "/"))
        return out


def _lean_clone(url: str, ref: str | None, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        cmd = ["git", "clone", "--depth", "1", "--filter=blob:none", "--no-checkout"]
        if ref:
            cmd += ["--branch", ref]
        cmd += [url, str(dest)]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        subprocess.run(
            ["git", "-C", str(dest), "sparse-checkout", "set", "--no-cone", *_SPARSE_PATTERNS],
            check=True, capture_output=True, text=True,
        )
        subprocess.run(["git", "-C", str(dest), "checkout"], check=True, capture_output=True, text=True)
        # Safety: if sparse patterns matched nothing, fall back to a full checkout.
        if not any(dest.rglob("*.py")) and not any(dest.rglob("*.java")):
            subprocess.run(["git", "-C", str(dest), "sparse-checkout", "disable"], check=False)
            subprocess.run(["git", "-C", str(dest), "checkout"], check=False)
    except subprocess.CalledProcessError:
        # Fallback: plain shallow clone (older git / server without partial-clone).
        shutil.rmtree(dest, ignore_errors=True)
        cmd = ["git", "clone", "--depth", "1"]
        if ref:
            cmd += ["--branch", ref]
        cmd += [url, str(dest)]
        subprocess.run(cmd, check=True)


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
