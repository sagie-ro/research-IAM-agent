"""code-qa CLI: `chat` (default), `index`, `inspect`."""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from .config import Settings
from .graph import build_graph
from .index import service
from .llm import ModelFactory
from .source import RepoSource

_COMMANDS = {"chat", "index", "inspect"}


def _looks_like_url(s: str) -> bool:
    return s.startswith(("http://", "https://", "git@")) or s.endswith(".git")


def _resolve_repo(repo: str, ref: str | None) -> RepoSource:
    return RepoSource.from_git(repo, ref) if _looks_like_url(repo) else RepoSource.from_local(repo)


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    argv = list(sys.argv[1:] if argv is None else argv)
    command = "chat"
    if argv and argv[0] in _COMMANDS:
        command = argv.pop(0)
    return {"chat": _chat, "index": _index, "inspect": _inspect}[command](argv)


def _chat(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="code-qa chat", description="Ask questions about a repository.")
    parser.add_argument("--repo", help="Local path or git URL of the target repository.")
    parser.add_argument("--ref", help="Git ref/branch (use with a git URL).")
    parser.add_argument("--once", help="Ask a single question, print the answer, and exit.")
    args = parser.parse_args(argv)

    console = Console()
    settings = Settings()
    factory = ModelFactory(settings)

    repo_summary: str | None = None
    if args.repo:
        source = _resolve_repo(args.repo, args.ref)
        repo_summary = source.summary()
        console.print(f"[green]Loaded[/] {repo_summary}")

    app = build_graph(settings, factory)

    def ask(question: str) -> str:
        return app.invoke({"question": question, "repo_summary": repo_summary}).get("answer", "")

    if args.once is not None:
        console.print(ask(args.once))
        return 0

    console.print("[bold]code-qa[/] — ask about the codebase (Ctrl-D to exit).")
    while True:
        try:
            question = console.input("[cyan]>[/] ")
        except (EOFError, KeyboardInterrupt):
            console.print("\nbye")
            return 0
        if question.strip():
            console.print(ask(question))


def _index(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="code-qa index", description="Build the structural index.")
    parser.add_argument("--repo", required=True, help="Local path or git URL.")
    parser.add_argument("--ref", help="Git ref/branch (use with a git URL).")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild even if cached.")
    args = parser.parse_args(argv)

    console = Console()
    source = _resolve_repo(args.repo, args.ref)
    console.print(f"Indexing [bold]{source.summary()}[/] …")
    path, built = service.ensure_index(source, rebuild=args.rebuild)
    console.print(f"[green]{'Built' if built else 'Reused cache'}[/] -> {path}")
    _render_stats(console, service.stats(path))
    return 0


def _inspect(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="code-qa inspect", description="Show index statistics.")
    parser.add_argument("--repo", required=True, help="Local path or git URL.")
    parser.add_argument("--ref", help="Git ref/branch (use with a git URL).")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild before inspecting.")
    args = parser.parse_args(argv)

    console = Console()
    source = _resolve_repo(args.repo, args.ref)
    path, built = service.ensure_index(source, rebuild=args.rebuild)
    if built:
        console.print(f"[dim]built index -> {path}[/]")
    _render_stats(console, service.stats(path))
    return 0


def _render_stats(console: Console, s: dict) -> None:
    meta = s["meta"]
    console.print(
        f"\n[bold]repo[/] {meta.get('repo_path', '?')}  "
        f"[bold]sha[/] {(meta.get('sha') or 'live')[:8]}  "
        f"[bold]schema[/] v{meta.get('schema_version', '?')}"
    )
    console.print(
        f"[bold]files[/] {s['files_total']}  "
        f"[bold]doc-flagged[/] {s['doc_files']}  "
        f"[bold]parse errors[/] {s['parse_errors']}"
    )

    files = Table(title="files by language", show_edge=False, pad_edge=False)
    files.add_column("language")
    files.add_column("count", justify="right")
    for lang, n in s["files_by_lang"].items():
        files.add_row(lang, str(n))
    console.print(files)

    syms = Table(title="symbols", show_edge=False, pad_edge=False)
    syms.add_column("kind")
    syms.add_column("count", justify="right")
    for kind, n in s["symbols_by_kind"].items():
        syms.add_row(kind, str(n))
    console.print(syms)

    edges = Table(title="edges", show_edge=False, pad_edge=False)
    edges.add_column("type")
    edges.add_column("count", justify="right")
    for typ, n in s["edges_by_type"].items():
        extra = ""
        if typ == "calls" and s["calls_total"]:
            pct = 100 * s["calls_resolved"] // s["calls_total"]
            extra = f"  [dim]({s['calls_resolved']} resolved, {pct}%)[/]"
        edges.add_row(typ, f"{n}{extra}")
    console.print(edges)

    console.print(
        f"\n[bold]entry points[/]: {s['entries_total']}  "
        f"[bold]call-paths[/]: {s['call_path_edges']} edges from "
        f"{s['entries_with_paths']} entries (max depth {s['max_call_depth']})"
    )
    for qual, file_id in s["entries"][:12]:
        console.print(f"  [cyan]{file_id}[/] :: {qual}")


if __name__ == "__main__":
    raise SystemExit(main())
