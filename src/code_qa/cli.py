"""code-qa CLI: `chat` (default, conversational), `index`, `inspect`, `eval`."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from .config import Settings
from .graph import build_graph
from .index import service
from .llm import ModelFactory
from .retrieval import IndexHandle, build_retrieval
from .source import RepoSource

_COMMANDS = {"chat", "index", "inspect", "eval"}
_QUIT = {"/exit", "/quit", "exit", "quit"}
_HISTORY_TURNS = 24  # keep the last N messages (user+assistant) in context


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
    try:
        return {"chat": _chat, "index": _index, "inspect": _inspect, "eval": _eval}[command](argv)
    except KeyboardInterrupt:
        return 130
    except (ValueError, FileNotFoundError, subprocess.CalledProcessError) as exc:
        Console().print(f"[red]error:[/] {exc}")
        return 1


def _chat(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="code-qa chat", description="Converse about a repository.")
    parser.add_argument("--repo", help="Local path or git URL of the target repository.")
    parser.add_argument("--ref", help="Git ref/branch (use with a git URL).")
    parser.add_argument("--once", help="Ask a single question, print the answer, and exit.")
    parser.add_argument("--corpus", help="Directory of external reference docs (professional-corpus RAG).")
    parser.add_argument("--show-trace", action="store_true", help="Print the reasoning trace after each answer.")
    args = parser.parse_args(argv)

    console = Console()
    settings = Settings()
    factory = ModelFactory(settings)

    retrieval = None
    if args.repo:
        source = _resolve_repo(args.repo, args.ref)
        console.print(f"[green]Loaded[/] {source.summary()} — building/loading index …")
        path, built = service.ensure_index(source)
        console.print(f"[dim]{'built' if built else 'cached'} index{_delta_note(path) if built else ''} -> {path}[/]")
        embedder = _setup_embeddings(console, settings, path)
        corpus_path = _setup_corpus(console, args.corpus or settings.corpus_path, embedder)
        retrieval = build_retrieval(IndexHandle(repo_root=source.path, store_path=path), embedder, corpus_path)
    else:
        console.print("[yellow]No --repo given; running in chat-only mode (no code retrieval).[/]")

    app = build_graph(settings, factory, retrieval)
    history: list[dict] = []

    def ask(question: str) -> bool:
        try:
            result = app.invoke({"question": question, "history": history, "trace": []})
        except Exception as exc:  # an LLM/network error shouldn't kill the session
            console.print(f"[red]error:[/] {_friendly_llm_error(exc)}")
            return False
        answer = result.get("answer", "")
        console.print(answer)
        _render_evidence(console, result)
        if args.show_trace:
            _render_trace(console, result.get("trace", []))
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": answer})
        if len(history) > _HISTORY_TURNS:
            del history[: len(history) - _HISTORY_TURNS]
        return True

    if args.once is not None:
        return 0 if ask(args.once) else 1

    console.print("[bold]code-qa[/] — conversational. Ask follow-ups; [cyan]/reset[/] clears, [cyan]/exit[/] quits.")
    while True:
        try:
            question = console.input("[cyan]you ›[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\nbye")
            return 0
        if not question:
            continue
        if question in _QUIT:
            console.print("bye")
            return 0
        if question == "/reset":
            history.clear()
            console.print("[dim](conversation reset)[/]")
            continue
        ask(question)


def _friendly_llm_error(exc: Exception) -> str:
    """Turn a provider exception into a short, actionable message (keeps the REPL alive)."""
    msg = str(exc)
    low = msg.lower()
    if "credit balance is too low" in low or "billing" in low or "quota" in low:
        return (
            "the chat model's account is out of credits/quota. Add credits for the configured provider, "
            "or switch chat to Azure: set LLM_PROVIDER=azure_openai (+ AZURE_OPENAI_ENDPOINT / "
            "AZURE_OPENAI_API_VERSION) and point ROUTER_MODEL / RETRIEVER_MODEL / RESEARCHER_MODEL at your "
            "Azure chat deployment name(s). Your Azure embeddings already work, so the creds are in place."
        )
    if any(s in low for s in ("authentication", "api key", "unauthorized", "401", "invalid x-api-key")):
        return "model authentication failed — check the provider keys/credentials in your .env."
    if "rate limit" in low or "429" in low or "overloaded" in low:
        return "the model is rate-limiting/overloaded; wait a moment and retry."
    return f"{type(exc).__name__}: {msg[:300]}"


def _render_evidence(console: Console, result: dict) -> None:
    if result.get("findings", {}).get("findings"):
        console.print("[dim]— citations —[/]")
        for f in result["findings"]["findings"]:
            loc = f"{f['file']}:{f['line_start']}" + (f"-{f['line_end']}" if f.get("line_end") else "")
            console.print(f"  [cyan]{loc}[/] {f.get('symbol') or ''} — {f.get('note', '')}")
    report = result.get("report")
    if report and report.get("steps"):
        console.print("[dim]— flow —[/]")
        for st in report["steps"]:
            calls = f" → {', '.join(st.get('calls', []))}" if st.get("calls") else ""
            console.print(f"  [cyan]{st.get('location', '')}[/] {st.get('symbol', '')}{calls}")
        for note in report.get("boundary_notes", []):
            console.print(f"  [yellow]boundary:[/] {note}")


def _render_trace(console: Console, trace: list) -> None:
    console.print("[dim]— trace (agent · event) —[/]")
    for ev in trace:
        agent = ev.get("agent", "-")
        event = ev.get("event", "")
        rest = {k: v for k, v in ev.items() if k not in ("agent", "event")}
        console.print(f"  [magenta]{agent:<12}[/] [bold]{event}[/] [dim]{json.dumps(rest) if rest else ''}[/]")


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


def _eval(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="code-qa eval", description="Run the eval suite (needs an LLM key).")
    parser.add_argument("--only", help="Run only cases whose id contains this substring.")
    parser.add_argument("--save", default="eval_results.json", help="Write the metrics JSON here.")
    args = parser.parse_args(argv)
    from .eval.runner import run

    return run(only=args.only, save=args.save)


def _setup_corpus(console: Console, corpus_dir, embedder):
    """Build/load the optional external professional corpus; return its store path or None."""
    if not corpus_dir:
        return None
    try:
        from .corpus import ensure_corpus

        corpus_path = ensure_corpus(corpus_dir, embedder)
        if corpus_path is None:
            console.print(f"[yellow]corpus: no documents found under {corpus_dir}[/]")
        else:
            console.print(f"[dim]corpus: loaded reference docs from {corpus_dir}[/]")
        return corpus_path
    except Exception as exc:
        console.print(f"[yellow]corpus disabled ({type(exc).__name__}: {exc})[/]")
        return None


def _setup_embeddings(console: Console, settings: Settings, path):
    """Build the configured embedder (if any) and embed any un-embedded doc chunks. Semantic
    search is additive — on any failure we warn and fall back to keyword doc search."""
    try:
        from .embeddings import build_embedder, index_doc_vectors

        embedder = build_embedder(settings)
        if embedder is None:
            return None
        n = index_doc_vectors(path, embedder)
        console.print(f"[dim]embeddings: {embedder.model}"
                      + (f" (+{n} doc vectors)" if n else " (cached)") + "[/]")
        return embedder
    except Exception as exc:
        console.print(f"[yellow]embeddings disabled ({type(exc).__name__}: {exc}); using keyword doc search[/]")
        return None


def _delta_note(path) -> str:
    meta = service.stats(path)["meta"]
    if "delta_reparsed" in meta:
        return f" [delta: reused {meta.get('delta_reused', '?')}, reparsed {meta['delta_reparsed']}]"
    return " [full build]"


def _render_stats(console: Console, s: dict) -> None:
    meta = s["meta"]
    delta = (
        f"  [bold]delta[/] reused {meta['delta_reused']}, reparsed {meta['delta_reparsed']}"
        if "delta_reparsed" in meta else ""
    )
    console.print(
        f"\n[bold]repo[/] {meta.get('repo_path', '?')}  "
        f"[bold]sha[/] {(meta.get('sha') or 'live')[:8]}  "
        f"[bold]schema[/] v{meta.get('schema_version', '?')}{delta}"
    )
    console.print(
        f"[bold]files[/] {s['files_total']}  "
        f"[bold]doc-flagged[/] {s['doc_files']}  "
        f"[bold]doc-chunks[/] {s.get('doc_chunks', 0)}  "
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
