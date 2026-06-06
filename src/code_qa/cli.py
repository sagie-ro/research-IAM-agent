"""Interactive CLI entry point for code-qa."""

from __future__ import annotations

import argparse

from dotenv import load_dotenv
from rich.console import Console

from .config import Settings
from .graph import build_graph
from .llm import ModelFactory
from .source import RepoSource


def _looks_like_url(s: str) -> bool:
    return s.startswith(("http://", "https://", "git@")) or s.endswith(".git")


def main(argv: list[str] | None = None) -> int:
    # Populate os.environ from .env so the LLM SDKs and azure-identity see secrets.
    load_dotenv()

    parser = argparse.ArgumentParser(
        prog="code-qa", description="Conversational code Q&A over a repository."
    )
    parser.add_argument("--repo", help="Local path or git URL of the target repository.")
    parser.add_argument("--ref", help="Git ref/branch (use with a git URL).")
    parser.add_argument("--once", help="Ask a single question, print the answer, and exit.")
    args = parser.parse_args(argv)

    console = Console()
    settings = Settings()
    factory = ModelFactory(settings)

    repo_summary: str | None = None
    if args.repo:
        source = (
            RepoSource.from_git(args.repo, args.ref)
            if _looks_like_url(args.repo)
            else RepoSource.from_local(args.repo)
        )
        repo_summary = source.summary()
        console.print(f"[green]Loaded[/] {repo_summary}")

    app = build_graph(settings, factory)

    def ask(question: str) -> str:
        result = app.invoke({"question": question, "repo_summary": repo_summary})
        return result.get("answer", "")

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


if __name__ == "__main__":
    raise SystemExit(main())
